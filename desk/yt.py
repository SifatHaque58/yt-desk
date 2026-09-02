"""WEB InnerTube client. No player/streaming calls."""
from __future__ import annotations

import time

import httpx
from innertube import InnerTube, Locale
from innertube.clients import Client

from desk import tunnel
from desk.countries import news_query
from desk.parse import find_token, related_videos, walk_search, walk_videos, watch_info, watch_next_token


class YTError(Exception):
    """Transport or YouTube payload failure. Do not score as a dead channel."""


# innertube builds its httpx.Client with no timeout, so httpx's 5s default
# applies to every call. Watch Next continuations are the fattest payload the
# desk asks for and they leave through the PIA proxy, so 5s trips on a normal
# slow page. Read gets the long leash; connect stays short so a dead tunnel
# fails fast instead of stalling a run.
TIMEOUT = httpx.Timeout(connect=10.0, read=30.0, write=15.0, pool=10.0)

# PIA rebinds mid-run (the tunnel IP changes and in-flight sockets die), which
# reads as a timeout rather than an error page. Retry the transport, never the
# payload errors above -- those are YouTube telling us something real.
RETRY_WAITS = (1.0, 3.0, 7.0)


def _safe_call(self, endpoint: str, params=None, body=None) -> dict:
    response = self.adaptor.dispatch(endpoint, params=params, body=body)
    if not isinstance(response, dict):
        raise YTError(f"{endpoint} returned a non-object payload")
    if response.get("error"):
        raise YTError(str(response.get("error")))
    response.pop("responseContext", None)
    return response


Client.__call__ = _safe_call  # type: ignore[method-assign]

VIDEO_FILTER = "EgIQAQ%3D%3D"
CHANNEL_FILTER = "EgIQAg%3D%3D"
VIDEOS_TAB = "EgZ2aWRlb3PyBgQKAjoA"
# InnerTube search `sp` for Upload date. Used by lookalike fallback
# (this week, then this month) instead of unfiltered competitor search.
UPLOAD_WEEK = "EgQIAxAB"
UPLOAD_MONTH = "EgQIBBAB"
UPLOAD_YEAR = "EgQIBRAB"
# Sort by upload date (latest first). 2026 WEB still honours CAI= even though
# the UI hid "Upload date". CAISAhAB is the same sort plus type=video.
UPLOAD_SORT = "CAI="
UPLOAD_SORT_VIDEO = "CAISAhAB"


def search_sp(*, channel: bool = False, uploaded: str | None = None) -> str:
    """InnerTube `params` / `sp` for a search."""
    if channel:
        return CHANNEL_FILTER
    if uploaded == "week":
        return UPLOAD_WEEK
    if uploaded == "month":
        return UPLOAD_MONTH
    if uploaded == "year":
        return UPLOAD_YEAR
    if uploaded == "latest":
        return UPLOAD_SORT_VIDEO
    return VIDEO_FILTER


def uploaded_for_floor(max_age_days) -> str:
    """Pick an InnerTube upload window from the desk's max-days floor."""
    try:
        days = int(max_age_days)
    except (TypeError, ValueError):
        return "latest"
    if days <= 7:
        return "week"
    if days <= 31:
        return "month"
    return "latest"


class YT:
    """Every YouTube call the desk makes goes through here.

    Locale asks YouTube for a market; the proxy decides which country the
    request appears to come from. Both matter -- a `Locale("ar", "EG")` search
    made from a home IP still gets ranked for the home country, which is how a
    run fills up with plausible-looking rows from the wrong market. When
    `tunnel.proxy_url()` returns a proxy, InnerTube leaves through the PIA
    tunnel; otherwise it connects directly and the locale is all we have.

    `proxies={}` on the direct path is deliberate: it stops httpx picking up an
    unrelated `HTTPS_PROXY` from the environment behind the desk's back.
    """

    def __init__(self, language: str, location: str, pause: float = 0.35):
        lang = language if language not in ("es-419",) else "es"
        if tunnel.routing_wanted() and not tunnel.proxy_listening(tunnel.proxy_url() or tunnel.DEFAULT_PROXY):
            raise YTError("VPN routing is on but the tunnel proxy is not listening — refusing a leaked home-IP run")
        proxy = tunnel.proxy_url()
        self.proxy = proxy
        self.language = lang
        self.location = location
        self.client = InnerTube(
            "WEB",
            locale=Locale(lang, location),
            proxies={"all://": proxy} if proxy else {},
        )
        self.client.adaptor.session.timeout = TIMEOUT
        self.pause = pause

    @property
    def visitor_data(self) -> str:
        return str(self.client.adaptor.session.headers.get("X-Goog-Visitor-Id") or "")

    def set_visitor(self, value: str | None) -> None:
        if value:
            self.client.adaptor.session.headers["X-Goog-Visitor-Id"] = value

    def _sleep(self) -> None:
        time.sleep(self.pause)

    def _call(self, fn, *args, **kwargs):
        last: Exception | None = None
        for attempt in range(len(RETRY_WAITS) + 1):
            self._sleep()
            try:
                data = fn(*args, **kwargs)
            except YTError:
                raise
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last = exc
                if attempt < len(RETRY_WAITS):
                    time.sleep(RETRY_WAITS[attempt])
                    continue
                raise YTError(f"{exc} (after {attempt + 1} tries)") from exc
            except Exception as exc:
                raise YTError(str(exc)) from exc
            if not isinstance(data, dict):
                raise YTError("empty YouTube payload")
            return data
        raise YTError(str(last))

    def search_pages(
        self,
        query: str,
        *,
        channel: bool = False,
        pages: int = 2,
        uploaded: str | None = None,
    ) -> tuple[list[dict], list[dict]]:
        params = search_sp(channel=channel, uploaded=uploaded)
        videos: list[dict] = []
        channels: list[dict] = []
        data = self._call(self.client.search, query, params=params)
        v, c = walk_search(data)
        videos += v
        channels += c
        token = find_token(data)
        for _ in range(max(pages, 1) - 1):
            if not token:
                break
            data = self._call(self.client.search, continuation=token)
            v, c = walk_search(data)
            videos += v
            channels += c
            token = find_token(data)
        return videos, channels

    def browse(self, browse_id: str, params: str | None = None) -> dict:
        if params:
            return self._call(self.client.browse, browse_id, params=params)
        return self._call(self.client.browse, browse_id)

    def browse_continue(self, token: str) -> dict:
        if not token:
            return {}
        return self._call(self.client.browse, continuation=token)

    def videos_tab(self, channel_id: str) -> dict:
        return self.browse(channel_id, VIDEOS_TAB)

    def next(self, video_id: str) -> dict:
        if not video_id:
            return {}
        return self._call(self.client.next, video_id)

    def next_continue(self, token: str) -> dict:
        if not token:
            return {}
        return self._call(self.client.next, continuation=token)

    def search_page(
        self,
        query: str,
        *,
        continuation: str | None = None,
        channel: bool = False,
        uploaded: str | None = None,
    ) -> dict:
        if continuation:
            data = self._call(self.client.search, continuation=continuation)
        else:
            params = search_sp(channel=channel, uploaded=uploaded)
            data = self._call(self.client.search, query, params=params)
        videos, channels = walk_search(data)
        return {
            "videos": videos,
            "channels": channels,
            "continuation": find_token(data),
        }

    def trending(self, *, continuation: str | None = None) -> dict:
        """Official trending if WEB still serves it; else this week's news search.

        Logged-out `FEtrending` currently 400s on WEB, and `/feed/trending`
        HTML is the same empty nudge as home. A locale news search through
        this client is still ranked for `gl` + exit IP.
        """
        if continuation:
            data = self.browse_continue(continuation)
            return {
                "videos": walk_videos(data),
                "continuation": find_token(data),
                "empty": False,
                "source": "trending",
            }
        try:
            data = self.browse("FEtrending")
            videos = walk_videos(data)
            if videos:
                return {
                    "videos": videos,
                    "continuation": find_token(data),
                    "empty": False,
                    "source": "trending",
                }
        except YTError:
            pass
        q = news_query(self.language)
        out = self.search_page(q, uploaded="week")
        out["empty"] = not out.get("videos")
        out["source"] = "news"
        out["query"] = q
        return out

    def home(self, *, continuation: str | None = None) -> dict:
        if continuation:
            data = self.browse_continue(continuation)
        else:
            data = self.browse("FEwhat_to_watch")
        videos = walk_videos(data)
        return {
            "videos": videos,
            "continuation": find_token(data),
            "empty": not videos and not continuation,
        }

    def watch(self, video_id: str, *, continuation: str | None = None) -> dict:
        if continuation:
            data = self.next_continue(continuation)
            related = related_videos(data)
            return {
                "video": {"video_id": video_id},
                "related": related,
                "continuation": watch_next_token(data),
            }
        data = self.next(video_id)
        info = watch_info(data)
        info["video_id"] = video_id
        return {
            "video": info,
            "related": related_videos(data),
            "continuation": watch_next_token(data),
        }

    def suggest(self, query: str) -> list[str]:
        q = (query or "").strip()
        if not q:
            return []
        self._sleep()
        proxy = self.proxy
        try:
            with httpx.Client(
                proxies={"all://": proxy} if proxy else {},
                timeout=httpx.Timeout(connect=10.0, read=15.0, write=10.0, pool=10.0),
            ) as client:
                resp = client.get(
                    "https://suggestqueries.google.com/complete/search",
                    params={
                        "client": "firefox",
                        "ds": "yt",
                        "q": q,
                        "hl": self.language,
                        "gl": self.location,
                    },
                )
                resp.raise_for_status()
                payload = resp.json()
        except Exception as exc:
            raise YTError(str(exc)) from exc
        if not isinstance(payload, list) or len(payload) < 2:
            return []
        out = []
        for item in payload[1]:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out[:12]


def search_videos(yt, query: str, *, pages: int = 2, channel: bool = False, uploaded: str | None = None):
    """Search helper. Country desk is all-time video search unless `uploaded` is set."""
    kw = dict(channel=channel, pages=pages)
    if channel:
        uploaded = None
    try:
        return yt.search_pages(query, uploaded=uploaded, **kw)
    except TypeError:
        return yt.search_pages(query, **kw)
