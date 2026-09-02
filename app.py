#!/usr/bin/env python3
"""Country-native YouTube desk — InnerTube WEB through the scout tunnel."""
from __future__ import annotations

import re
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from desk import session as sess
from desk import tunnel
from desk.countries import COUNTRIES, get as get_country
from desk.yt import YT, YTError

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "web" / "static"
HOME_AFTER_WATCHES = 3
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")

_lock = threading.RLock()
_yt: YT | None = None
_yt_key = ""


@asynccontextmanager
async def lifespan(_app: FastAPI):
    _log_exit_route()
    yield


app = FastAPI(title="yt-desk", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")


def _log_exit_route() -> None:
    state = tunnel.status()
    tun = state.get("tunnel") or {}
    if tun.get("whole_machine"):
        print("==> PIA is carrying the WHOLE machine (default route is the tunnel).")
        print("    Split it (All Other Apps -> Bypass VPN) or git and the browser ride along too.")
    if state.get("routed") and tun.get("up"):
        print(f"==> YouTube via {state['proxy']} -> {tun['ip']} on {tun['interface']} [{tun.get('region')}]")
    elif state.get("routed"):
        print(f"==> YouTube via {state['proxy']} -- tunnel {tun.get('state')}, CONNECT will 503")
    else:
        print("==> YouTube direct (no tunnel proxy) -- this machine's country")


def _client() -> YT:
    """One InnerTube WEB client per locale + proxy. Sticky visitorData per gl."""
    global _yt, _yt_key
    state = sess.current()
    proxy = tunnel.proxy_url()
    key = f"{state['hl']}|{state['gl']}|{proxy}"
    if _yt is None or _yt_key != key:
        yt = YT(state["hl"], state["gl"])
        yt.set_visitor(sess.visitor_for(state["gl"]))
        _yt = yt
        _yt_key = key
    return _yt


def _remember_visitor(yt: YT) -> None:
    gl = sess.current()["gl"]
    sess.remember_visitor(gl, yt.visitor_data)


def _run_yt(fn):
    with _lock:
        yt = _client()
        out = fn(yt)
        _remember_visitor(yt)
        return out


def _fail(exc: Exception, status: int = 502) -> JSONResponse:
    return JSONResponse({"error": str(exc)}, status_code=status)


@app.get("/")
def index() -> HTMLResponse:
    return HTMLResponse((STATIC / "index.html").read_text(encoding="utf-8"))


@app.get("/api/countries")
def countries() -> JSONResponse:
    return JSONResponse(COUNTRIES)


@app.get("/api/session")
def session_get() -> JSONResponse:
    state = sess.current()
    gl = state["gl"]
    country = get_country(gl)
    return JSONResponse(
        {
            "gl": gl,
            "hl": state["hl"],
            "name": country["name"],
            "watches": sess.watch_count(gl),
            "home_ready": sess.watch_count(gl) >= HOME_AFTER_WATCHES,
        }
    )


@app.post("/api/session")
def session_set(body: dict | None = None) -> JSONResponse:
    code = str((body or {}).get("gl") or "")
    sess.set_country(code)
    return session_get()


@app.get("/api/proxy")
def proxy_status(check: bool = Query(False)):
    state = tunnel.status()
    if check:
        state["observed"] = tunnel.observed_country(state["proxy"])
        state["exit_ip"] = tunnel.exit_ip(state["proxy"])
    return JSONResponse(state)


@app.post("/api/proxy/start")
def proxy_start(body: dict | None = None):
    port = int((body or {}).get("port", 8118))
    result = tunnel.start_proxy(port)
    return JSONResponse({**result, "status": tunnel.status()})


@app.post("/api/proxy/stop")
def proxy_stop(body: dict | None = None):
    port = int((body or {}).get("port", 8118))
    result = tunnel.stop_proxy(port)
    return JSONResponse({**result, "status": tunnel.status()})


@app.get("/api/suggest")
def suggest(q: str = "") -> JSONResponse:
    try:
        rows = _run_yt(lambda yt: yt.suggest(q))
        return JSONResponse({"query": q, "suggestions": rows})
    except YTError as exc:
        return _fail(exc)


def _search_body(q: str, uploaded: str | None, continuation: str | None) -> JSONResponse:
    if not (q or "").strip() and not continuation:
        return JSONResponse({"videos": [], "channels": [], "continuation": None})
    try:
        out = _run_yt(
            lambda yt: yt.search_page(q, continuation=continuation or None, uploaded=uploaded or None)
        )
        return JSONResponse(out)
    except YTError as exc:
        return _fail(exc)


@app.get("/api/search")
def search(
    q: str = "",
    uploaded: str | None = None,
    continuation: str | None = None,
) -> JSONResponse:
    return _search_body(q, uploaded, continuation)


@app.post("/api/search")
def search_post(body: dict | None = None) -> JSONResponse:
    body = body or {}
    return _search_body(
        str(body.get("q") or ""),
        body.get("uploaded") or None,
        body.get("continuation") or None,
    )


@app.get("/api/trending")
def trending(continuation: str | None = None) -> JSONResponse:
    try:
        out = _run_yt(lambda yt: yt.trending(continuation=continuation or None))
        return JSONResponse(out)
    except YTError as exc:
        return _fail(exc)


@app.post("/api/trending")
def trending_post(body: dict | None = None) -> JSONResponse:
    return trending((body or {}).get("continuation") or None)


@app.get("/api/home")
def home(continuation: str | None = None) -> JSONResponse:
    gl = sess.current()["gl"]
    watches = sess.watch_count(gl)
    try:
        def run(yt: YT):
            if watches < HOME_AFTER_WATCHES and not continuation:
                out = yt.trending()
            else:
                out = yt.home(continuation=continuation or None)
                if out.get("empty"):
                    out = yt.trending()
                else:
                    out["source"] = "home"
            out["watches"] = watches
            out["need"] = HOME_AFTER_WATCHES
            return out

        return JSONResponse(_run_yt(run))
    except YTError as exc:
        return _fail(exc)


@app.post("/api/home")
def home_post(body: dict | None = None) -> JSONResponse:
    return home((body or {}).get("continuation") or None)


@app.get("/api/watch/{video_id}")
def watch(video_id: str, continuation: str | None = None) -> JSONResponse:
    if not VIDEO_ID_RE.match(video_id or ""):
        return JSONResponse({"error": "invalid video id"}, status_code=400)
    try:
        out = _run_yt(lambda yt: yt.watch(video_id, continuation=continuation or None))
        return JSONResponse(out)
    except YTError as exc:
        return _fail(exc)


@app.post("/api/watch/{video_id}")
def watch_post(video_id: str, body: dict | None = None) -> JSONResponse:
    return watch(video_id, (body or {}).get("continuation") or None)


@app.post("/api/history")
def history(body: dict | None = None) -> JSONResponse:
    vid = str((body or {}).get("video_id") or "")
    if vid and not VIDEO_ID_RE.match(vid):
        return JSONResponse({"error": "invalid video id"}, status_code=400)
    gl = sess.current()["gl"]
    row = sess.remember_watch(gl, vid)
    return JSONResponse(
        {
            "gl": gl,
            "watches": len(row.get("watched") or []),
            "home_ready": len(row.get("watched") or []) >= HOME_AFTER_WATCHES,
        }
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="127.0.0.1", port=5056, reload=False)
