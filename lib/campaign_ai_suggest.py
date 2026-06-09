"""Mistral-powered email suggestions for admin campaign editor."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

MISTRAL_CHAT_URL = "https://api.mistral.ai/v1/chat/completions"
DEFAULT_MODEL = "mistral-small-latest"


def _mistral_key() -> str:
    return os.getenv("MISTRAL_API_KEY", "").strip()


def default_model() -> str:
    return os.getenv("MISTRAL_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL


def is_available() -> bool:
    return bool(_mistral_key())


def suggest_email(topic: str, company: str = "", addressing: str = "sie") -> dict[str, Any]:
    key = _mistral_key()
    model = default_model()
    if not key:
        return {
            "available": False,
            "subject": f"{topic} - kurze Einordnung",
            "paragraphs": [
                "ich wollte mich kurz mit einem relevanten Update melden.",
                "Wenn du magst, zeige ich dir in 15 Minuten den konkreten Fit fuer deinen Prozess.",
            ],
        }

    tone = "informell (Du)" if addressing.lower() == "du" else "formell (Sie)"
    prompt = (
        f"Schreibe eine kurze B2B-Akquise-E-Mail auf Deutsch ({tone}) zum Thema: {topic}. "
        f"Firma des Empfaengers: {company or 'unbekannt'}. "
        "Antworte nur als JSON mit keys subject (string) und paragraphs (array of 2-3 strings, ohne Anrede)."
    )
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.7,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        MISTRAL_CHAT_URL,
        data=json.dumps(payload).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            body = json.loads(response.read().decode("utf-8"))
        content = body["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        paragraphs = parsed.get("paragraphs") or []
        if isinstance(paragraphs, str):
            paragraphs = [paragraphs]
        return {
            "available": True,
            "subject": str(parsed.get("subject") or topic).strip(),
            "paragraphs": [str(p).strip() for p in paragraphs if str(p).strip()],
            "model": model,
        }
    except (urllib.error.HTTPError, KeyError, json.JSONDecodeError, IndexError) as err:
        return {
            "available": False,
            "subject": f"{topic} - kurze Einordnung",
            "paragraphs": [
                "ich wollte mich kurz mit einem relevanten Update melden.",
                "Wenn Sie moechten, zeige ich Ihnen den konkreten Fit in einem kurzen Call.",
            ],
            "error": str(err),
        }
