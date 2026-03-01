from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request


SEARXNG_URL = "http://127.0.0.1:8080/search"
SITE_DOMAIN_FILTERS = {
    "youtube": "youtube.com",
    "wikipedia": "wikipedia.org",
}
SEARCH_VERB_RE = r"(?:busca|buscá|buscar|investiga|investigar|search|encontra|encontrá|encontrar)"
WEB_DEST_RE = r"(youtube|wikipedia|google|internet|la\s+red|web|la\s+web)"


def _clean_query(raw: str) -> str:
    q = (raw or "").strip().strip("\"'").strip()
    if not q:
        return ""
    q = re.sub(r"^(?:sobre|acerca\s+de)\s+", "", q, flags=re.IGNORECASE).strip()
    # Remove trailing operational directives ("abrí la página...", "open...", etc.).
    q = re.sub(
        r"(?:[,;:.]|\s+)(?:y\s+)?(?:abr\w*|open|mostr\w*|muestr\w*|pone\w*|pon[eé]\w*|reproduc\w*).*$",
        "",
        q,
        flags=re.IGNORECASE,
    ).strip()
    q = re.sub(r"\s+", " ", q).strip(" ,.;:-")
    return q


def _site_key_from_where(where: str) -> str | None:
    norm = re.sub(r"\s+", " ", (where or "").strip().lower())
    return norm if norm in ("youtube", "wikipedia", "google") else None


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

    patterns = [rf"{SEARCH_VERB_RE}\s+(?:en\s+internet|en\s+la\s+red|en\s+la\s+web|en\s+web|web)\s*[:,-]?\s*(.+)$"]
    for pat in patterns:
        m = re.search(pat, msg, flags=re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        q = _clean_query(m.group(1) or "")
        if q:
            return q[:400]

    # Common "latest/news" asks should also trigger local web search to avoid
    # stale/hallucinated answers when the user did request current information.
    news_patterns = [
        r"(?:noticias|novedades|actualidad|ultima(?:s)?|última(?:s)?)\s+(?:de|del|sobre)\s+(.+)$",
        r"(?:pod[eé]s?\s+contar(?:me)?|cont(?:a|á|á)me|cu[ée]nta(?:me)?|dec(?:ime|íme)|resum(?:ime|íme))\s+noticias\s+(?:de|del|sobre)\s+(.+)$",
        r"(?:que|qué)\s+(?:pasa|hay)\s+(?:con|en)\s+(.+?)\s+(?:hoy|ahora|actualmente)\b",
    ]
    for pat in news_patterns:
        m = re.search(pat, msg, flags=re.IGNORECASE | re.DOTALL)
        if not m:
            continue
        q = _clean_query((m.group(1) or "").strip(" \t,.;:!?¡¿"))
        if q:
            return q[:400]

    # Dictation often arrives as terse fragments like:
    # "hoy de el conflicto entre iran y esto...".
    # If it sounds like a current-affairs ask, treat it as web search query.
    lowered = re.sub(r"\s+", " ", msg).strip().lower()
    topical = bool(
        re.search(
            r"\b(conflicto|guerra|crisis|iran|israel|ee\.?\s*uu|estados\s+unidos|rusia|ucrania|economia|economía|inflaci[oó]n|d[oó]lar)\b",
            lowered,
            flags=re.IGNORECASE,
        )
    )
    timely = bool(re.search(r"\b(hoy|ahora|actual(?:idad|mente)?|reciente(?:s)?)\b", lowered, flags=re.IGNORECASE))
    if topical and timely:
        q = re.sub(r"^\s*(?:hoy|ahora|actualmente)\s*(?:de|del|sobre|acerca de)?\s*", "", msg, flags=re.IGNORECASE).strip()
        q = _clean_query(q.strip(" \t,.;:!?¡¿"))
        if q:
            return q[:400]
    return None


def extract_web_search_request(message: str) -> tuple[str, str | None] | None:
    """
    Returns (query, site_key) for explicit free-web search requests.
    site_key is one of: None, "youtube", "wikipedia", "google".
    """
    msg = (message or "").strip()
    if not msg:
        return None

    # "busca <tema> en youtube|wikipedia|google|internet|la red|web"
    m = re.search(
        rf"{SEARCH_VERB_RE}\s+(.+?)\s+en\s+{WEB_DEST_RE}\b",
        msg,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m:
        q = _clean_query(m.group(1) or "")
        where = (m.group(2) or "").strip().lower()
        site_key = _site_key_from_where(where)
        if q:
            return q[:400], site_key

    # "busca en youtube|wikipedia|google|internet|la red|web: <tema>"
    m = re.search(
        rf"{SEARCH_VERB_RE}\s+en\s+{WEB_DEST_RE}\s*[:,-]?\s*(.+)$",
        msg,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m:
        where = (m.group(1) or "").strip().lower()
        q = _clean_query(m.group(2) or "")
        site_key = _site_key_from_where(where)
        if q:
            return q[:400], site_key

    # "en youtube|wikipedia|google busca: <tema>"
    m = re.search(
        rf"en\s+(youtube|wikipedia|google)\s+{SEARCH_VERB_RE}\s*[:,-]?\s*(.+)$",
        msg,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m:
        where = (m.group(1) or "").strip().lower()
        q = _clean_query(m.group(2) or "")
        if q:
            return q[:400], where

    # "youtube|wikipedia|google busca: <tema>" (sin "en")
    # also accepts punctuation after site key: "youtube: busca <tema>"
    m = re.search(
        rf"(youtube|wikipedia|google)\s*[:,-]?\s+{SEARCH_VERB_RE}\s*[:,-]?\s*(.+)$",
        msg,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if m:
        where = (m.group(1) or "").strip().lower()
        q = _clean_query(m.group(2) or "")
        if q:
            return q[:400], where

    q_only = extract_web_search_query(msg)
    if q_only:
        return q_only, None
    return None


def searxng_search(
    query: str, *, site_key: str | None = None, max_results: int = 6, timeout_s: int = 12
) -> dict:
    """
    Calls local SearXNG. Requires `search.formats` to include `json` in SearXNG settings.
    """
    q = (query or "").strip()
    if not q:
        return {"ok": False, "status": "empty_query", "query": "", "results": [], "error": "empty_query"}

    domain = SITE_DOMAIN_FILTERS.get(str(site_key or "").strip().lower(), "")
    q_eff = f"{q} site:{domain}".strip() if domain else q
    data = urllib.parse.urlencode({"q": q_eff, "format": "json"}).encode("utf-8")
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
        return {"ok": False, "status": "network_error", "query": q, "results": [], "error": str(e), "site_key": site_key}

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
            "site_key": site_key,
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

    return {"ok": True, "status": "ok", "query": q, "results": trimmed, "site_key": site_key}


def format_results_for_prompt(search_payload: dict) -> str:
    q = str(search_payload.get("query", "")).strip()
    results = search_payload.get("results", [])
    if not isinstance(results, list):
        results = []
    site_key = str(search_payload.get("site_key", "")).strip()
    where = f" en {site_key}" if site_key in ("youtube", "wikipedia", "google") else ""
    lines = [f"Resultados SearXNG (local){where} para: {q}"]
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


def format_results_for_user(search_payload: dict) -> str:
    q = str(search_payload.get("query", "")).strip()
    site_key = str(search_payload.get("site_key", "")).strip()
    where = f" en {site_key}" if site_key in ("youtube", "wikipedia", "google") else " en la web"
    results = search_payload.get("results", [])
    if not isinstance(results, list):
        results = []
    if not results:
        return f"No encontré resultados{where} para: {q}"
    lines = [f"Encontré {len(results)} resultado(s){where} para: {q}"]
    for i, r in enumerate(results[:6], 1):
        if not isinstance(r, dict):
            continue
        title = str(r.get("title", "")).strip() or "(sin titulo)"
        url = str(r.get("url", "")).strip()
        snippet = str(r.get("content", "")).replace("\n", " ").strip()
        if len(snippet) > 160:
            snippet = snippet[:160] + "..."
        lines.append(f"{i}. {title}\n{url}\n{snippet}".strip())
    return "\n\n".join(lines).strip()
