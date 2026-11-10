"""Único punto de contacto con el LLM (Este parametro se cambian dentro del .env)."""
import os
import time
import random
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=True)

URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def generate(system, user, max_tokens=2048):
    key = os.getenv("IA_API_KEY") #Se obtiene la clave de API desde el archivo .env
    if not key:
        raise RuntimeError("Falta IA_API_KEY: revisa tu archivo .env en la raíz del proyecto.")
    model = os.getenv("LLM_MODEL") #Se obtiene el modelo de LLM desde el archivo .env
    if not model:
        raise RuntimeError("Falta LLM_MODEL: revisa tu archivo .env en la raíz del proyecto.")

    body = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": [{"role": "user", "parts": [{"text": user}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.2},
    }
    headers = {"x-goog-api-key": key, "Content-Type": "application/json"}

    for attempt in range(5):
        r = requests.post(URL.format(model=model), headers=headers, json=body, timeout=60)
        # 429 = límite del plan gratuito; 500/503 = error temporal de Google
        if r.status_code in (429, 500, 503) and attempt < 4:
            time.sleep(5 * 2**attempt + random.random())
            continue
        if not r.ok:
            raise RuntimeError(f"Error {r.status_code} de Gemini: {r.text[:300]}")
        candidates = r.json().get("candidates") or []
        if not candidates:
            return "No pude generar una respuesta; intenta reformular la pregunta."
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)