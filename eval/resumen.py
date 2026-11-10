"""Convierte eval/resultados/raw.jsonl en tablas para el README.

Uso:  python eval/resumen.py
Genera eval/resultados/resumen.md (tablas) y eval/resultados/detalle.csv (todas las respuestas, para revisar a mano).
"""
import csv
import json
from pathlib import Path

DIR = Path(__file__).resolve().parent / "resultados"
RAW = DIR / "raw.jsonl"
NOMBRES = {"directas": "Directas", "relacionadas": "Relacionar información", "sin_respuesta": "Sin respuesta"}


def load():
    data = {}
    for line in RAW.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            data[r["key"]] = r
    return list(data.values())


def pct(a, b):
    return f"{100 * a / b:.0f}% ({a}/{b})" if b else "—"


def main():
    if not RAW.exists():
        raise SystemExit("No existe eval/resultados/raw.jsonl: corre primero python eval/run_eval.py")
    recs = load()
    configs = list(dict.fromkeys(r["config"] for r in recs))

    filas = []
    for c in configs:
        rs = [r for r in recs if r["config"] == c and not r["error"]]
        errores = sum(1 for r in recs if r["config"] == c and r["error"])
        ans = [r for r in rs if r["answerable"]]
        sin = [r for r in rs if not r["answerable"]]
        es_rag = c != "baseline"
        con_juez = [r for r in rs if "judge" in r]

        recup = pct(sum(1 for r in ans if set(r["expected_pages"]) & set(r["retrieved_pages"])), len(ans)) if es_rag else "—"
        citada = (pct(sum(1 for r in ans if set(r["expected_pages"]) & set(r["cited_pages"])), len([r for r in ans if r["answer"]]))
                  if es_rag and any(r["answer"] for r in ans) else "—")

        def exact(cat):
            g = [r for r in con_juez if r["answerable"] and r["categoria"] == cat]
            return pct(sum(r["judge"]["correcta"] for r in g), len(g)) if g else "—"

        gs = [r for r in con_juez if not r["answerable"]]
        if gs:
            rechazo = pct(sum(r["judge"]["correcta"] for r in gs), len(gs))
        elif es_rag and any(r["answer"] for r in sin):
            g = [r for r in sin if r["answer"]]
            rechazo = pct(sum(1 for r in g if r["refused"]), len(g))
        else:
            rechazo = "—"
        falsos = (pct(sum(1 for r in ans if r["refused"]), len([r for r in ans if r["answer"]]))
                  if es_rag and any(r["answer"] for r in ans) else "—")
        aluc = pct(sum(r["judge"]["alucina"] for r in con_juez), len(con_juez)) if con_juez else "—"
        filas.append([c, recup, citada, exact("directas"), exact("relacionadas"), rechazo, falsos, aluc, str(errores)])

    cab = ["Configuración", "Recuperación (pág. esperada en los k chunks)", "Pág. esperada citada", "Exactitud directas",
           "Exactitud relacionar", "Rechazo correcto (sin respuesta)", "Falsos rechazos", "Alucinación", "Errores"]
    md = ["| " + " | ".join(cab) + " |", "|" + "|".join(["---"] * len(cab)) + "|"]
    md += ["| " + " | ".join(f) + " |" for f in filas]
    n_por_cat = {}
    for r in recs:
        if r["config"] == configs[0]:
            n_por_cat[r["categoria"]] = n_por_cat.get(r["categoria"], 0) + 1
    texto = ("Preguntas por categoría: " + ", ".join(f"{NOMBRES.get(k, k)} = {v}" for k, v in n_por_cat.items()) + "\n\n" + "\n".join(md) + "\n")
    (DIR / "resumen.md").write_text(texto, encoding="utf-8")
    print(texto)

    with open(DIR / "detalle.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["configuracion", "categoria", "pregunta", "respuesta_esperada", "paginas_esperadas", "respuesta_sistema",
                    "paginas_citadas", "paginas_recuperadas", "pagina_recuperada_ok", "pagina_citada_ok", "rechazo_automatico",
                    "juez_correcta", "juez_alucina", "error"])
        for r in recs:
            esp = set(r["expected_pages"])
            j = r.get("judge", {})
            w.writerow([r["config"], r["categoria"], r["question"], r["expected"], ",".join(map(str, r["expected_pages"])),
                        r["answer"] or "", ",".join(map(str, r["cited_pages"])), ",".join(map(str, r["retrieved_pages"])),
                        int(bool(esp & set(r["retrieved_pages"]))) if esp else "", int(bool(esp & set(r["cited_pages"]))) if esp else "",
                        "" if r["refused"] is None else int(r["refused"]), j.get("correcta", ""), j.get("alucina", ""), r["error"] or ""])
    print(f"Guardado: {DIR / 'resumen.md'} y {DIR / 'detalle.csv'}")


if __name__ == "__main__":
    main()
