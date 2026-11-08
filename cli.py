"""Prueba rápida en consola: python cli.py data/reglamento.pdf"""
import sys
from src.rag import RAGIndex

if len(sys.argv) < 2:
    sys.exit("Uso: python cli.py ruta/al/archivo.pdf")

idx = RAGIndex()
pages, chunks = idx.load_pdf(sys.argv[1])
print(f"Listo: {pages} páginas, {chunks} chunks. Escribe 'salir' para terminar.\n")

while True:
    q = input("Pregunta: ").strip()
    if q.lower() in ("salir", "exit", ""):
        break
    r = idx.answer(q)
    print(f"\n{r['answer']}\nPáginas: {r['pages']}\n")
