"""Sticky anonymous InnerTube identity per country."""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from desk.countries import get as get_country

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SESSION_FILE = DATA / "session.json"
_lock = threading.RLock()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# Which title YouTube should serve. "original" keeps the title the creator
# actually typed; "native" asks in the market language, which is what a local
# viewer sees -- including YouTube's multi-language titles, where a US channel
# arrives wearing an Arabic title.
TITLE_MODES = ("original", "native")
DEFAULT_TITLES = "original"
# Locale asked of InnerTube in "original" mode. There is no `hl` meaning "do not
# translate" -- YouTube serves whichever title track matches, and falls back to
# the creator's own title when none does. `en` is the wrong pick: it hands back
# the *English* track, so an Arabic channel that uploaded one reads as English.
# Icelandic has effectively no title tracks, so every row falls back to the
# original. Ages come back in Icelandic too; `desk.parse` reads and re-renders
# them (see `display_published`).
ORIGINAL_HL = "is"


def _clean_titles(value) -> str:
    value = str(value or "").strip().lower()
    return value if value in TITLE_MODES else DEFAULT_TITLES


def _empty() -> dict:
    return {"gl": "US", "hl": "en", "titles": DEFAULT_TITLES, "visitors": {}}


def load() -> dict:
    try:
        with _lock:
            raw = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty()
    if not isinstance(raw, dict):
        return _empty()
    raw.setdefault("gl", "US")
    raw.setdefault("hl", "en")
    raw["titles"] = _clean_titles(raw.get("titles"))
    raw.setdefault("visitors", {})
    if not isinstance(raw["visitors"], dict):
        raw["visitors"] = {}
    return raw


def save(state: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with _lock:
        SESSION_FILE.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")


def current() -> dict:
    """`hl` is the market language. `ui_hl` is what InnerTube is actually asked."""
    state = load()
    country = get_country(state.get("gl") or "US")
    state["gl"] = country["code"]
    state["hl"] = country["hl"]
    state["titles"] = _clean_titles(state.get("titles"))
    state["ui_hl"] = ORIGINAL_HL if state["titles"] == "original" else country["hl"]
    return state


def set_country(code: str) -> dict:
    state = load()
    country = get_country(code)
    state["gl"] = country["code"]
    state["hl"] = country["hl"]
    save(state)
    return state


def set_titles(mode: str) -> dict:
    state = load()
    state["titles"] = _clean_titles(mode)
    save(state)
    return state


def visitor_for(gl: str) -> str:
    state = load()
    row = (state.get("visitors") or {}).get(gl.upper()) or {}
    return str(row.get("visitorData") or "")


def remember_visitor(gl: str, visitor: str) -> None:
    if not visitor:
        return
    with _lock:
        try:
            raw = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raw = _empty()
        except (OSError, json.JSONDecodeError):
            raw = _empty()
        raw.setdefault("visitors", {})
        if not isinstance(raw["visitors"], dict):
            raw["visitors"] = {}
        row = raw["visitors"].setdefault(gl.upper(), {})
        row["visitorData"] = visitor
        row["updated"] = _now()
        DATA.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")


def remember_watch(gl: str, video_id: str) -> dict:
    vid = (video_id or "").strip()
    with _lock:
        try:
            raw = json.loads(SESSION_FILE.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raw = _empty()
        except (OSError, json.JSONDecodeError):
            raw = _empty()
        raw.setdefault("visitors", {})
        if not isinstance(raw["visitors"], dict):
            raw["visitors"] = {}
        row = raw["visitors"].setdefault(gl.upper(), {})
        watched = [x for x in (row.get("watched") or []) if x != vid]
        if vid:
            watched.insert(0, vid)
        row["watched"] = watched[:80]
        row["updated"] = _now()
        DATA.mkdir(parents=True, exist_ok=True)
        SESSION_FILE.write_text(json.dumps(raw, indent=2) + "\n", encoding="utf-8")
        return row


def watch_count(gl: str) -> int:
    row = (load().get("visitors") or {}).get(gl.upper()) or {}
    return len(row.get("watched") or [])
