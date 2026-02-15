from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request


SEARXNG_URL = "http://127.0.0.1:8080/search"


def extract_web_search_query(message: str) -> str | None:
    """
    Explicit trigger only. We don't want to auto-search for every question.
    Examples:
      - "busca en internet: X"
      - "busca en la red X"
      - "investiga en internet X"
    """
    msg = (message or "").strip()
    if not msg:
        return None

    patterns = [
        r"(?:busca|buscar|investiga|investigar|search)\s+(?:en\s+internet|en\s+la\s+red|web)\s*[:,-]?\s*(.+)$",
    ]
    for pat in patterns:
        m = re.search(pat, msg, flags=re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        q = (m.group(1) or "").strip().strip("\"'").strip()
        if q:
            return q[:400]
    return None


def searxng_search(query: str, *, max_results: int = 6, timeout_s: int = 12) -> dict:
    """
    Calls local SearXNG. Requires `search.formats` to include `json` in SearXNG settings.
    """
    q = (query or "").strip()
    if not q:
        return {"ok": False, "status": "empty_query", "query": "", "results": [], "error": "empty_query"}

    data = urllib.parse.urlencode({"q": q, "format": "json"}).encode("utf-8")
    req = urllib.request.Request(
        SEARXNG_URL,
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return {"ok": False, "status": "network_error", "query": q, "results": [], "error": str(e)}

    try:
        payload = json.loads(raw)
    except Exception as e:
        return {
            "ok": False,
            "status": "invalid_json",
            "query": q,
            "results": [],
            "error": f"{e}",
            "raw": raw[:600],
        }

    results = payload.get("results", [])
    if not isinstance(results, list):
        results = []

    trimmed: list[dict] = []
    for r in results[: max(1, int(max_results))]:
        if not isinstance(r, dict):
            continue
        url = str(r.get("url", "")).strip()
        title = str(r.get("title", "")).strip()
        content = str(r.get("content", "")).strip()
        engine = str(r.get("engine", "")).strip()
        if not url:
            continue
        trimmed.append({"url": url, "title": title, "content": content, "engine": engine})

    return {"ok": True, "status": "ok", "query": q, "results": trimmed}


def format_results_for_prompt(search_payload: dict) -> str:
    q = str(search_payload.get("query", "")).strip()
    results = search_payload.get("results", [])
    if not isinstance(results, list):
        results = []
    lines = [f"Resultados SearXNG (local) para: {q}"]
    for i, r in enumerate(results[:8], 1):
        if not isinstance(r, dict):
            continue
        title = str(r.get("title", "")).strip() or "(sin titulo)"
        url = str(r.get("url", "")).strip()
        content = str(r.get("content", "")).strip()
        engine = str(r.get("engine", "")).strip()
        snippet = content.replace("\n", " ").strip()
        if len(snippet) > 280:
            snippet = snippet[:280] + "..."
        engine_note = f" [{engine}]" if engine else ""
        lines.append(f"{i}. {title}{engine_note}\n{url}\n{snippet}".strip())
    return "\n\n".join(lines).strip()

