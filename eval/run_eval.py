"""Evaluación del RAG de Nexora.

Uso (desde la raíz del proyecto, con el entorno activado):
    python eval/run_eval.py --rapido --juez        # línea base + configuración principal
    python eval/run_eval.py --juez                 # todas las configuraciones
    python eval/run_eval.py --solo-recuperacion    # sin llamar al LLM (solo mide la recuperación)

Lee el catálogo eval/preguntas.txt, corre cada configuración y guarda todo en
eval/resultados/raw.jsonl a medida que avanza. Si se corta (límite de la API, Ctrl+C),
vuelve a ejecutar el mismo comando: continúa donde se quedó.
Después: python eval/resumen.py
"""
import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.llm import generate  # noqa: E402
from src.rag import RAGIndex, answer_baseline  # noqa: E402

try:
    from src.rag import NO_INFO  # noqa: E402
except ImportError:
    NO_INFO = "No encontré esa información en el documento."

# (nombre, tamaño de chunk en caracteres, top-k). La primera es la configuración principal.
CONFIGS = [
    ("baseline", None, None),
    ("rag_c800_k5", 800, 5),
    ("rag_c800_k3", 800, 3),
    ("rag_c400_k5", 400, 5),
    ("rag_c1500_k5", 1500, 5),
    ("rag_c400_k3", 400, 3),
    ("rag_c1500_k3", 1500, 3),
]
QUICK = {"baseline", "rag_c800_k5"}

SECTION_RE = re.compile(r"^\s*\{(.+?)\}\s*$")
SEP_RE = re.compile(r"^\s*-{3,}\s*$")


# ----------------------------------------------------------------- catálogo
def categoria(nombre):
    n = nombre.lower()
    if "sin" in n and "respuesta" in n:
        return "sin_respuesta"
    if "relacion" in n:
        return "relacionadas"
    if "direct" in n:
        return "directas"
    raise ValueError(f"Sección desconocida: {{{nombre}}}. Usa Directas, Relacionar información o Sin respuesta.")


def parse_pages(txt):
    txt = txt.strip().strip("[]").strip()
    pages = set()
    for a, b in re.findall(r"(\d+)\s*[-–]\s*(\d+)", txt):
        pages.update(range(int(a), int(b) + 1))
    resto = re.sub(r"(\d+)\s*[-–]\s*(\d+)", " ", txt)
    pages.update(int(x) for x in re.findall(r"\d+", resto))
    return sorted(pages)


def parse_entry(text):
    body, sep, page_txt = text.rpartition("/")
    if not sep:
        raise ValueError("falta el '/' que separa la página")
    m = re.match(r"^(.*?\?)\s*/\s*(.*)$", body, re.S)  # la pregunta termina en '?' seguido de '/'
    if m:
        q, a = m.group(1), m.group(2)
    else:
        q, _, a = body.partition("/")
    return " ".join(q.split()), " ".join(a.split()), parse_pages(page_txt)


def load_questions(path, desfase=0):
    raw = Path(path).read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252")

    questions, cat, block = [], None, []

    def flush():
        nonlocal block
        entry = "\n".join(block).strip()
        block = []
        if not entry:
            return
        if cat is None:
            raise ValueError("Hay preguntas antes de la primera sección {…}.")
        try:
            q, a, pages = parse_entry(entry)
        except ValueError as e:
            raise ValueError(f"No pude leer esta entrada ({e}): {entry[:80]}...")
        pages = [p + desfase for p in pages]
        answerable = cat != "sin_respuesta"
        if answerable and not pages:
            print(f"AVISO: sin página en una pregunta de '{cat}': {q[:70]}")
        if not answerable and pages:
            print(f"AVISO: tiene página pero está en 'sin respuesta': {q[:70]}")
        questions.append({
            "id": hashlib.sha1(q.encode("utf-8")).hexdigest()[:10],
            "categoria": cat, "pregunta": q, "esperada": a,
            "paginas": pages, "answerable": answerable and bool(pages),
        })

    for line in text.splitlines():
        m = SECTION_RE.match(line)
        if m:
            flush()
            cat = categoria(m.group(1))
        elif SEP_RE.match(line):
            flush()
        else:
            block.append(line)
    flush()
    return questions


# ----------------------------------------------------------------- almacén
class Store:
    """Registros en un .jsonl; si una clave se repite, gana la última línea."""
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data = {}
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self.data[rec["key"]] = rec

    def put(self, rec):
        self.data[rec["key"]] = rec
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# ----------------------------------------------------------------- juez
JUEZ_SYS = (
    "Eres un evaluador estricto y objetivo. Comparas la respuesta de un sistema con una referencia. "
    'Responde SOLO con un JSON en una línea, sin texto adicional: {"correcta": 0 o 1, "alucina": 0 o 1}.'
)


def judge_prompt(rec):
    if rec["answerable"]:
        return (
            f"Pregunta: {rec['question']}\nRespuesta esperada (referencia): {rec['expected']}\n"
            f"Respuesta del sistema: {rec['answer']}\n\n"
            "correcta = 1 si la respuesta del sistema contiene la información esencial de la referencia y no la "
            "contradice (puede añadir detalles correctos); 0 si falta lo esencial, la contradice o dice que no encontró la información.\n"
            "alucina = 1 si afirma datos concretos (cifras, plazos, nombres, correos, reglas) que contradicen la "
            "referencia o parecen inventados; 0 en caso contrario (decir que no encontró la información NO es alucinar)."
        )
    return (
        f"Pregunta: {rec['question']}\nRespuesta del sistema: {rec['answer']}\n\n"
        "Esta pregunta NO tiene respuesta en el documento que se consulta. "
        "correcta = 1 si el sistema indica que no tiene o no encuentra esa información en el documento, sin inventar; "
        "0 si responde como si el documento la contuviera.\n"
        "alucina = 1 si ofrece datos concretos presentándolos como si fueran del documento; 0 en caso contrario."
    )


def judge(rec):
    out = generate(JUEZ_SYS, judge_prompt(rec), 200)
    m = re.search(r"\{.*?\}", out, re.S)
    if not m:
        raise ValueError(f"respuesta del juez no válida: {out[:80]}")
    j = json.loads(m.group(0))
    return {"correcta": int(j["correcta"]), "alucina": int(j["alucina"])}


# ----------------------------------------------------------------- ejecución
class Abort(Exception):
    pass


def hecho(rec, solo_recuperacion):
    """¿Ya está listo este registro? Los que dieron error, o que solo tienen recuperación, se rehacen."""
    if rec is None or rec.get("error"):
        return False
    if not solo_recuperacion and rec.get("answer") is None:
        return False
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preguntas", default=str(ROOT / "eval" / "preguntas.txt"))
    ap.add_argument("--pdf", default=str(ROOT / "data" / "reglamento.pdf"))
    ap.add_argument("--salida", default=str(ROOT / "eval" / "resultados" / "raw.jsonl"))
    ap.add_argument("--rapido", action="store_true", help="solo línea base + configuración principal")
    ap.add_argument("--configs", help="lista separada por comas, p. ej. baseline,rag_c800_k5")
    ap.add_argument("--juez", action="store_true", help="califica las respuestas con el LLM (correcta / alucina)")
    ap.add_argument("--solo-recuperacion", action="store_true", help="no llama al LLM; solo mide la recuperación")
    ap.add_argument("--pausa", type=float, default=4.0, help="segundos entre llamadas al LLM (plan gratuito)")
    ap.add_argument("--desfase", type=int, default=0, help="se suma a las páginas del catálogo (si usan otra numeración)")
    ap.add_argument("--max-errores", type=int, default=3, help="se detiene tras N errores seguidos")
    args = ap.parse_args()

    questions = load_questions(args.preguntas, args.desfase)
    by_cat = {}
    for q in questions:
        by_cat[q["categoria"]] = by_cat.get(q["categoria"], 0) + 1
    print(f"{len(questions)} preguntas leídas: {by_cat}")

    wanted = {c[0] for c in CONFIGS}
    if args.rapido:
        wanted = QUICK
    if args.configs:
        wanted = set(args.configs.split(","))
        desconocidas = wanted - {c[0] for c in CONFIGS}
        if desconocidas:
            sys.exit(f"Configuraciones desconocidas: {sorted(desconocidas)}. Válidas: {[c[0] for c in CONFIGS]}")
    configs = [c for c in CONFIGS if c[0] in wanted]
    if args.solo_recuperacion:
        configs = [c for c in configs if c[1] is not None]

    store = Store(args.salida)
    indexes = {}
    errors_in_row = 0
    llm_calls = 0

    def pause():
        nonlocal llm_calls
        llm_calls += 1
        time.sleep(args.pausa)

    try:
        for ci, (name, size, k) in enumerate(configs, 1):
            pendientes = [q for q in questions if not hecho(store.data.get(f"{name}|{q['id']}"), args.solo_recuperacion)]
            print(f"\n[{ci}/{len(configs)}] {name}: {len(pendientes)} pendientes de {len(questions)}")
            if not pendientes:
                continue

            idx = None
            if size is not None:
                if size not in indexes:
                    print(f"  construyendo índice (chunk {size})...")
                    indexes[size] = RAGIndex(chunk_size=size, overlap=round(size * 0.2))
                    indexes[size].load_pdf(args.pdf)
                idx = indexes[size]
                idx.top_k = k

            for n, q in enumerate(pendientes, 1):
                rec = {
                    "key": f"{name}|{q['id']}", "config": name, "categoria": q["categoria"],
                    "question": q["pregunta"], "expected": q["esperada"],
                    "expected_pages": q["paginas"], "answerable": q["answerable"],
                    "answer": None, "cited_pages": [], "retrieved_pages": [], "refused": None, "error": None,
                }
                try:
                    if idx is None:  # línea base: el LLM solo, sin documento
                        rec["answer"] = answer_baseline(q["pregunta"])
                        pause()
                    elif args.solo_recuperacion:
                        rec["retrieved_pages"] = sorted({h["page"] for h in idx.retrieve(q["pregunta"])})
                    else:
                        r = idx.answer(q["pregunta"])
                        rec["answer"] = r["answer"]
                        rec["cited_pages"] = r["pages"]
                        rec["retrieved_pages"] = sorted({h["page"] for h in r["hits"]})
                        rec["refused"] = NO_INFO.lower() in r["answer"].lower()
                        pause()
                    errors_in_row = 0
                except Exception as e:  # cuota agotada, red, etc.
                    rec["error"] = str(e)[:300]
                    errors_in_row += 1
                    print(f"  ! error en la pregunta {n}: {rec['error'][:120]}")
                    if errors_in_row >= args.max_errores:
                        raise Abort("Demasiados errores seguidos (¿cuota de la API agotada?).")
                store.put(rec)
                print(f"  {n}/{len(pendientes)} ok" if not rec["error"] else f"  {n}/{len(pendientes)} error", end="\r")
            print()

        if args.juez and not args.solo_recuperacion:
            todo = [r for r in store.data.values()
                    if r["config"] in {c[0] for c in configs} and r["answer"] and not r["error"] and "judge" not in r]
            print(f"\nCalificando con el juez: {len(todo)} respuestas pendientes")
            for n, rec in enumerate(todo, 1):
                try:
                    rec["judge"] = judge(rec)
                    errors_in_row = 0
                except Exception as e:
                    errors_in_row += 1
                    print(f"  ! el juez falló en {rec['key']}: {str(e)[:120]}")
                    if errors_in_row >= args.max_errores:
                        raise Abort("Demasiados errores seguidos al calificar.")
                    continue
                store.put(rec)
                print(f"  {n}/{len(todo)}", end="\r")
                time.sleep(args.pausa)
            print()
    except Abort as e:
        print(f"\nSe detuvo: {e}\nEl progreso quedó guardado. Vuelve a ejecutar el mismo comando más tarde para continuar.")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nInterrumpido. El progreso quedó guardado; vuelve a ejecutar el mismo comando para continuar.")
        sys.exit(1)

    print(f"\nListo. Resultados en {args.salida}\nSiguiente paso: python eval/resumen.py")


if __name__ == "__main__":
    main()
