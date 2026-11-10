"""Pipeline RAG: embeddings + Chroma + recuperación + respuesta con páginas."""
import uuid
import chromadb
from sentence_transformers import SentenceTransformer

from .ingest import extract_pages, looks_scanned, build_chunks
from .llm import generate

import re

NO_INFO = "No encontré esa información en el documento."

EMBED_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"  # funciona bien en español
_embedder = None

SYSTEM_RAG = (
    "Eres un asistente que responde preguntas sobre un documento. "
    "Responde SOLO con la información del contexto. Si la respuesta no está "
    f"en el contexto, responde exactamente: '{NO_INFO}' "
    "No inventes datos. Responde en español y de forma concisa. "
    "Después de cada afirmación cita la página de donde la tomaste con el "
    "formato [Pág. N], usando solo páginas que aparezcan en el contexto."
)
SYSTEM_BASELINE = "Responde en español y de forma concisa."


def get_embedder():
    global _embedder
    if _embedder is None:
        _embedder = SentenceTransformer(EMBED_MODEL)
    return _embedder


class RAGIndex:
    def __init__(self, chunk_size=400, overlap=80, top_k=5):
        self.chunk_size, self.overlap, self.top_k = chunk_size, overlap, top_k
        self.client = chromadb.EphemeralClient()
        self.col = None

    def load_pdf(self, path):
        pages = extract_pages(path)
        if looks_scanned(pages):
            raise ValueError("El PDF parece escaneado (sin texto). Sube uno con texto.")
        chunks = build_chunks(pages, self.chunk_size, self.overlap)
        # nombre único: EphemeralClient comparte estado dentro del proceso
        self.col = self.client.create_collection(
            f"doc_{uuid.uuid4().hex[:8]}", metadata={"hnsw:space": "cosine"}
        )
        embs = get_embedder().encode(
            [c["text"] for c in chunks], normalize_embeddings=True
        ).tolist()
        self.col.add(
            ids=[c["id"] for c in chunks],
            documents=[c["text"] for c in chunks],
            embeddings=embs,
            metadatas=[{"page": c["page"]} for c in chunks],
        )
        self.n_pages, self.n_chunks = len(pages), len(chunks)
        return self.n_pages, self.n_chunks

    def retrieve(self, question):
        q = get_embedder().encode([question], normalize_embeddings=True).tolist()
        res = self.col.query(query_embeddings=q, n_results=self.top_k)
        return [
            {"text": d, "page": m["page"], "score": 1 - dist}
            for d, m, dist in zip(
                res["documents"][0], res["metadatas"][0], res["distances"][0]
            )
        ]

    def answer(self, question):
        hits = self.retrieve(question)
        context = "\n\n".join(f"[Pág. {h['page']}] {h['text']}" for h in hits)
        user = f"Contexto:\n{context}\n\nPregunta: {question}"
        text = generate(SYSTEM_RAG, user)

        if NO_INFO.lower() in text.lower():
            return {"answer": NO_INFO, "pages": [], "hits": hits}

        valid = {h["page"] for h in hits}
        cited = [int(n) for n in re.findall(r"P[áa]g\.?\s*(\d+)", text)]
        pages = [p for p in dict.fromkeys(cited) if p in valid]
        if not pages:  # el modelo no citó: usa el fragmento más relevante
            pages = [hits[0]["page"]]
        return {"answer": text, "pages": pages, "hits": hits}


def answer_baseline(question):
    """Línea base: el mismo LLM sin RAG."""
    return generate(SYSTEM_BASELINE, question)
