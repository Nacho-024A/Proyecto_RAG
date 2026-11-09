"""Servidor de Nexora: conecta la interfaz web (web/) con el RAG (src/).

Ejecutar:   python server.py      (o: uvicorn server:app)
Abrir:      http://127.0.0.1:8000

Cada chat vive en una carpeta:  data/chats/<id>/documento.pdf + chat.json
"""
import json
import re
import shutil
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import fitz  # pymupdf
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.rag import RAGIndex, get_embedder

ROOT = Path(__file__).resolve().parent
CHATS = ROOT / "data" / "chats"
WEB = ROOT / "web"
CHATS.mkdir(parents=True, exist_ok=True)

MAX_BYTES = 200 * 1024 * 1024
ID_RE = re.compile(r"^[a-f0-9]{12}$")

_indexes = {}                    # chat_id -> RAGIndex cargado en memoria
_build_lock = threading.Lock()   # construir/restaurar índices (uno a la vez)
_meta_lock = threading.Lock()    # escribir chat.json


@asynccontextmanager
async def lifespan(app):
    # Carga el modelo de embeddings en segundo plano para que la primera subida no espere tanto
    def warm():
        with _build_lock:
            get_embedder()
    threading.Thread(target=warm, daemon=True).start()
    yield


app = FastAPI(title="Nexora", lifespan=lifespan)


# ---------------------------------------------------------------- utilidades
def chat_dir(chat_id: str) -> Path:
    if not ID_RE.match(chat_id):
        raise HTTPException(404, "Chat no encontrado.")
    d = CHATS / chat_id
    if not (d / "chat.json").exists():
        raise HTTPException(404, "Chat no encontrado.")
    return d


def read_meta(d: Path) -> dict:
    return json.loads((d / "chat.json").read_text(encoding="utf-8"))


def write_meta(d: Path, meta: dict) -> None:
    tmp = d / "chat.json.tmp"
    tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(d / "chat.json")


def get_index(chat_id: str) -> RAGIndex:
    """Devuelve el índice del chat; si no está en memoria (p. ej. tras reiniciar), lo reconstruye del PDF."""
    with _build_lock:
        idx = _indexes.get(chat_id)
        if idx is None:
            idx = RAGIndex()
            idx.load_pdf(str(CHATS / chat_id / "documento.pdf"))
            _indexes[chat_id] = idx
        return idx


@lru_cache(maxsize=64)
def _render(pdf_path: str, n: int) -> bytes:
    doc = fitz.open(pdf_path)
    try:
        return doc[n - 1].get_pixmap(dpi=110).tobytes("png")
    finally:
        doc.close()


class Ask(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


# ---------------------------------------------------------------- API
@app.get("/api/chats")
def list_chats():
    items = []
    for d in CHATS.iterdir():
        if d.is_dir() and (d / "chat.json").exists():
            try:
                m = read_meta(d)
                items.append({"id": m["id"], "name": m["name"], "n_pages": m["n_pages"], "created": m["created"]})
            except (OSError, ValueError, KeyError):
                continue
    items.sort(key=lambda x: x["created"], reverse=True)
    return [{"id": i["id"], "name": i["name"], "n_pages": i["n_pages"]} for i in items]


@app.post("/api/chats")
def create_chat(file: UploadFile = File(...)):
    name = Path(file.filename or "documento.pdf").name
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "Solo se aceptan archivos PDF.")

    chat_id = uuid.uuid4().hex[:12]
    d = CHATS / chat_id
    d.mkdir(parents=True)
    pdf_path = d / "documento.pdf"

    def cleanup():
        shutil.rmtree(d, ignore_errors=True)

    try:
        size = 0
        with open(pdf_path, "wb") as out:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(413, "El archivo supera los 200 MB.")
                out.write(chunk)
        with _build_lock:
            idx = RAGIndex()
            n_pages, n_chunks = idx.load_pdf(str(pdf_path))
    except HTTPException:
        cleanup()
        raise
    except ValueError as e:  # PDF escaneado (sin texto)
        cleanup()
        raise HTTPException(422, str(e))
    except Exception as e:
        cleanup()
        raise HTTPException(400, f"No se pudo leer el PDF: {e}")

    meta = {
        "id": chat_id, "name": name, "n_pages": n_pages, "n_chunks": n_chunks,
        "created": datetime.now().isoformat(timespec="seconds"), "messages": [],
    }
    write_meta(d, meta)
    _indexes[chat_id] = idx
    return meta


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: str):
    return read_meta(chat_dir(chat_id))


@app.post("/api/chats/{chat_id}/ask")
def ask(chat_id: str, body: Ask):
    d = chat_dir(chat_id)
    question = body.question.strip()
    try:
        r = get_index(chat_id).answer(question)
    except Exception as e:
        raise HTTPException(502, f"No se pudo obtener la respuesta del modelo: {str(e)[:300]}")
    with _meta_lock:
        meta = read_meta(d)
        meta["messages"] += [
            {"role": "user", "text": question, "pages": []},
            {"role": "assistant", "text": r["answer"], "pages": r["pages"]},
        ]
        write_meta(d, meta)
    return {"answer": r["answer"], "pages": r["pages"]}


@app.get("/api/chats/{chat_id}/pages/{n:int}.png")
def page_image(chat_id: str, n: int):
    d = chat_dir(chat_id)
    if not 1 <= n <= read_meta(d)["n_pages"]:
        raise HTTPException(404, "Página no encontrada.")
    return Response(
        _render(str(d / "documento.pdf"), n),
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@app.get("/api/chats/{chat_id}/file")
def pdf_file(chat_id: str):
    """El PDF original, para que el visor (pdf.js) lo muestre con texto seleccionable y zoom."""
    d = chat_dir(chat_id)
    return FileResponse(d / "documento.pdf", media_type="application/pdf")


@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str):
    d = chat_dir(chat_id)
    idx = _indexes.pop(chat_id, None)
    if idx is not None and getattr(idx, "col", None) is not None:
        try:
            idx.client.delete_collection(idx.col.name)
        except Exception:
            pass
    (d / "chat.json").unlink(missing_ok=True)  # deja de aparecer en el historial aunque falle el resto
    shutil.rmtree(d, ignore_errors=True)
    _render.cache_clear()
    return {"ok": True}


# La interfaz (debe ir al final, después de las rutas /api)
app.mount("/", StaticFiles(directory=str(WEB), html=True), name="web")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="127.0.0.1", port=8000)
