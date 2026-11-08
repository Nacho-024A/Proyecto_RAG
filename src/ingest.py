"""Lectura del PDF por página y chunking dentro de cada página."""
import fitz  # pymupdf


def extract_pages(path):
    """Devuelve [(num_pagina, texto), ...] con numeración desde 1."""
    doc = fitz.open(path)
    pages = [(i, page.get_text().strip()) for i, page in enumerate(doc, start=1)]
    doc.close()
    return pages


def looks_scanned(pages, min_chars=50, ratio=0.8):
    """True si casi todas las páginas casi no tienen texto (PDF escaneado)."""
    if not pages:
        return True
    empty = sum(1 for _, t in pages if len(t) < min_chars)
    return empty / len(pages) >= ratio


def chunk_page(text, size=800, overlap=150):
    """Parte el texto de UNA página en ventanas de ~size caracteres."""
    text = " ".join(text.split())
    if not text:
        return []
    if len(text) <= size:
        return [text]
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            cut = text.rfind(" ", start, end)
            if cut > start + size // 2:
                end = cut
        chunks.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def build_chunks(pages, size=800, overlap=150):
    """Chunks con metadato de página. Ningún chunk cruza páginas."""
    out = []
    for page_num, text in pages:
        for j, c in enumerate(chunk_page(text, size, overlap)):
            out.append({"id": f"p{page_num}_c{j}", "text": c, "page": page_num})
    return out
