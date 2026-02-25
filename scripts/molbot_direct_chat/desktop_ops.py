from __future__ import annotations

import fcntl
import json
import shutil
import subprocess
import time
import uuid
from pathlib import Path

from .util import normalize_text


OPENED_WINDOWS_PATH = Path.home() / ".openclaw" / "direct_chat_opened_windows.json"
OPENED_WINDOWS_LOCK_PATH = Path.home() / ".openclaw" / ".direct_chat_opened_windows.lock"


def _desktop_dir() -> Path | None:
    home = Path.home()
    candidates = [home / "Escritorio", home / "Desktop"]
    return next((p for p in candidates if p.exists() and p.is_dir()), None)


def _wmctrl_list() -> dict[str, str]:
    if not shutil.which("wmctrl"):
        return {}
    try:
        proc = subprocess.run(["wmctrl", "-l"], capture_output=True, text=True, timeout=3)
    except Exception:
        return {}
    out: dict[str, str] = {}
    for line in (proc.stdout or "").splitlines():
        parts = line.split(None, 3)
        if len(parts) < 4:
            continue
        win_id = parts[0].strip()
        title = parts[3].strip()
        if win_id and title:
            out[win_id] = title
    return out


def _wmctrl_current_desktop() -> int | None:
    if not shutil.which("wmctrl"):
        return None
    try:
        proc = subprocess.run(["wmctrl", "-d"], capture_output=True, text=True, timeout=3)
    except Exception:
        return None
    for line in (proc.stdout or "").splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "*":
            try:
                return int(parts[0])
            except Exception:
                return None
    return None


def _wmctrl_move_to_desktop(win_id: str, desktop_idx: int) -> bool:
    if not shutil.which("wmctrl"):
        return False
    try:
        subprocess.run(
            ["wmctrl", "-i", "-r", win_id, "-t", str(desktop_idx)],
            timeout=3,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True
    except Exception:
        return False


def _opened_windows_load() -> dict:
    OPENED_WINDOWS_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with OPENED_WINDOWS_LOCK_PATH.open("a+", encoding="utf-8") as lockf:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_SH)
            if OPENED_WINDOWS_PATH.exists():
                try:
                    data = json.loads(OPENED_WINDOWS_PATH.read_text(encoding="utf-8") or "{}")
                    return data if isinstance(data, dict) else {}
                except Exception:
                    return {}
            return {}
    except Exception:
        return {}


def _opened_windows_save(data: dict) -> None:
    try:
        OPENED_WINDOWS_PATH.parent.mkdir(parents=True, exist_ok=True)
        OPENED_WINDOWS_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = OPENED_WINDOWS_PATH.with_suffix(".json.tmp")
        payload = json.dumps(data, ensure_ascii=False, indent=2)
        with OPENED_WINDOWS_LOCK_PATH.open("a+", encoding="utf-8") as lockf:
            fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
            tmp.write_text(payload, encoding="utf-8")
            tmp.replace(OPENED_WINDOWS_PATH)
    except Exception:
        return


def _record_opened_windows(session_id: str, items: list[dict]) -> None:
    data = _opened_windows_load()
    sess = data.get(session_id)
    if not isinstance(sess, dict):
        sess = {"items": []}
    if not isinstance(sess.get("items"), list):
        sess["items"] = []

    now = time.time()
    keep: list[dict] = []
    for it in sess["items"]:
        if not isinstance(it, dict):
            continue
        ts = float(it.get("ts", 0) or 0)
        if ts and (now - ts) < 30 * 60:
            keep.append(it)
    keep.extend(items)

    seen = set()
    deduped: list[dict] = []
    for it in reversed(keep):
        win_id = str(it.get("win_id", "")).strip()
        path = str(it.get("path", "")).strip()
        key = (win_id, path)
        if not win_id or not path or key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    sess["items"] = list(reversed(deduped))[-24:]
    data[session_id] = sess
    _opened_windows_save(data)


def close_recorded_windows(session_id: str) -> tuple[int, list[str]]:
    data = _opened_windows_load()
    sess = data.get(session_id)
    if not isinstance(sess, dict):
        return 0, []
    items = sess.get("items", [])
    if not isinstance(items, list) or not items:
        return 0, []
    if not shutil.which("wmctrl"):
        return 0, ["wmctrl_missing"]

    closed = 0
    errors: list[str] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        win_id = str(it.get("win_id", "")).strip()
        if not win_id:
            continue
        try:
            subprocess.run(["wmctrl", "-ic", win_id], timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            closed += 1
        except Exception as e:
            errors.append(str(e))

    data.pop(session_id, None)
    _opened_windows_save(data)
    return closed, errors


def reset_recorded_windows(session_id: str) -> None:
    data = _opened_windows_load()
    if session_id in data:
        data.pop(session_id, None)
        _opened_windows_save(data)


def open_desktop_item(name_hint: str, session_id: str) -> dict:
    desktop = _desktop_dir()
    if desktop is None:
        return {"ok": False, "error": "No encontré carpeta de escritorio en ~/Escritorio ni ~/Desktop."}
    hint = normalize_text(name_hint)
    if not hint:
        return {"ok": False, "error": "Decime qué carpeta/archivo del escritorio querés abrir."}

    entries = sorted(desktop.iterdir(), key=lambda p: p.name.lower())
    chosen: Path | None = None
    for p in entries:
        if hint == normalize_text(p.name):
            chosen = p
            break
    if chosen is None:
        for p in entries:
            if hint in normalize_text(p.name):
                chosen = p
                break
    if chosen is None:
        for p in entries:
            if normalize_text(p.name).startswith(hint):
                chosen = p
                break
    if chosen is None:
        return {"ok": False, "error": f"No encontré '{name_hint}' en tu escritorio."}

    if chosen.is_dir() and not shutil.which("nautilus") and not shutil.which("xdg-open"):
        return {"ok": False, "error": "No encontré nautilus ni xdg-open (no puedo abrir carpetas)."}
    if chosen.is_file() and not shutil.which("xdg-open"):
        return {"ok": False, "error": "No encontré xdg-open en el sistema (no puedo abrir archivos)."}

    before = _wmctrl_list()
    target_desktop = _wmctrl_current_desktop()
    try:
        if chosen.is_dir() and shutil.which("nautilus"):
            subprocess.Popen(["nautilus", "--new-window", str(chosen)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        else:
            subprocess.Popen(["xdg-open", str(chosen)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except Exception as e:
        return {"ok": False, "error": f"No pude abrir '{chosen.name}': {e}"}

    opened_items: list[dict] = []
    if before:
        time.sleep(0.9)
        after = _wmctrl_list()
        new_ids = [wid for wid in after.keys() if wid not in before]

        name_tokens = []
        if chosen.is_file():
            name_tokens.append(normalize_text(chosen.stem))
        name_tokens.append(normalize_text(chosen.name))

        def title_matches(t: str) -> bool:
            tt = normalize_text(t)
            return any(tok and tok in tt for tok in name_tokens)

        matched_ids = [wid for wid, title in after.items() if title and title_matches(title)]
        record_ids = list(dict.fromkeys(matched_ids))[:6]
        if chosen.is_dir() and not record_ids and len(new_ids) == 1:
            record_ids = [new_ids[0]]

        for wid in record_ids:
            if target_desktop is not None:
                _wmctrl_move_to_desktop(wid, target_desktop)
            opened_items.append(
                {
                    "id": str(uuid.uuid4()),
                    "path": str(chosen),
                    "name": chosen.name,
                    "win_id": wid,
                    "title": after.get(wid, ""),
                    "ts": time.time(),
                }
            )
        if opened_items:
            _record_opened_windows(session_id, opened_items)

    return {
        "ok": True,
        "name": chosen.name,
        "path": str(chosen),
        "kind": "carpeta" if chosen.is_dir() else "archivo",
        "tracked_windows": len(opened_items),
    }

