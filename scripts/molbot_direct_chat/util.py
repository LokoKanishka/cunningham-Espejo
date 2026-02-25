from __future__ import annotations

import json
import re
import unicodedata


def extract_url(text: str) -> str | None:
    m = re.search(r"(https?://[^\s]+)", text or "", flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def normalize_text(value: str) -> str:
    lowered = (value or "").lower()
    no_accents = "".join(c for c in unicodedata.normalize("NFKD", lowered) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", no_accents).strip()


def safe_session_id(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]", "", value or "")[:64]
    return cleaned or "default"


def parse_json_object(raw: str) -> dict | None:
    data = (raw or "").strip()
    if not data:
        return None
    try:
        parsed = json.loads(data)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass
    start = data.find("{")
    end = data.rfind("}")
    if start >= 0 and end > start:
        try:
            parsed = json.loads(data[start : end + 1])
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None

