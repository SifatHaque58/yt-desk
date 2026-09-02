"""InnerTube payload parsers. WEB client only."""
from __future__ import annotations

import json
import re
from typing import Any, Optional

VIDEO_ID_RE = re.compile(r"/vi/([A-Za-z0-9_-]{11})")
NUM_RE = re.compile(
    r"([\d]+(?:[.,]\d+)?)\s*(K|M|B|ألف|مليون|mil|mi)?",
    re.I,
)

# Longest word first so "mille" is not read as Spanish "mil"→million.
_COUNT_RE = re.compile(
    r"(\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?|\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)\s*"
    r"(thousands?|millions?|million|mille|millones|mill[oó]n(?:es)?|milhões|milh[aã]o|mil|"
    r"ribu|juta|ألف|مليون|rb|jt|[KMB])?",
    re.I,
)
_SUB_WORD_RE = re.compile(
    r"subscribers?|مشترك(?:ين)?|abonn[ée]s?|inscrits?|inscritos?|suscriptores?",
    re.I,
)
_COUNT_MULT = {
    "k": 1_000,
    "mille": 1_000,
    "mil": 1_000,
    "thousand": 1_000,
    "thousands": 1_000,
    "ribu": 1_000,
    "rb": 1_000,
    "ألف": 1_000,
    "juta": 1_000_000,
    "jt": 1_000_000,
    "m": 1_000_000,
    "million": 1_000_000,
    "millions": 1_000_000,
    "millon": 1_000_000,
    "millón": 1_000_000,
    "millones": 1_000_000,
    "milhao": 1_000_000,
    "milhão": 1_000_000,
    "milhoes": 1_000_000,
    "milhões": 1_000_000,
    "مليون": 1_000_000,
    "b": 1_000_000_000,
}


def as_list(obj: Any) -> list:
    return obj if isinstance(obj, list) else []


def txt(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        if "simpleText" in obj:
            return obj["simpleText"] or ""
        if "runs" in obj:
            parts = []
            for x in as_list(obj.get("runs")):
                if isinstance(x, dict):
                    parts.append(x.get("text") or "")
            return "".join(parts)
        if "content" in obj and isinstance(obj["content"], str):
            return obj["content"]
    return ""


def _normalize_count_text(s: str) -> str:
    return (
        str(s)
        .replace("\xa0", " ")
        .replace("\u202f", " ")
        .replace("\u2009", " ")
        .replace("\u2007", " ")
        .replace("’", "'")
        .replace("′", "'")
    )


def _to_float(num: str) -> Optional[float]:
    raw = num.strip().replace(" ", "")
    if not raw:
        return None
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        left, _, right = raw.partition(",")
        if "," not in right and right.isdigit() and 1 <= len(right) <= 2:
            raw = left + "." + right
        else:
            raw = raw.replace(",", "")
    elif raw.count(".") > 1:
        raw = raw.replace(".", "")
    elif raw.count(".") == 1:
        right = raw.split(".", 1)[1]
        if len(right) == 3 and right.isdigit():
            raw = raw.replace(".", "")
    try:
        return float(raw)
    except ValueError:
        return None


def parse_count(s: Optional[str]) -> Optional[int]:
    """Parse a YouTube count in EN/FR/AR/ES/PT compact form.

    French InnerTube uses a decimal comma (`1,92 k abonnés` = 1,920) and
    `mille`/`millions`. Do not strip commas first — that turned 1,92k into 192k.
    Handles (`@name1Msubscribers`) are not counts.
    """
    if not s:
        return None
    text = _normalize_count_text(s)
    if text.lstrip().startswith("@"):
        return None
    m = _COUNT_RE.search(text)
    if not m:
        m2 = re.search(r"(\d+)", text.replace(" ", ""))
        return int(m2.group(1)) if m2 else None
    n = _to_float(m.group(1))
    if n is None:
        return None
    suf = (m.group(2) or "").strip()
    if suf:
        key = suf.lower()
        key_cf = suf.casefold()
        mult = _COUNT_MULT.get(key) or _COUNT_MULT.get(key_cf) or _COUNT_MULT.get(suf)
        if not mult and len(suf) == 1:
            mult = _COUNT_MULT.get(suf.upper()) or _COUNT_MULT.get(suf.lower())
        if mult:
            n *= mult
    return int(n)


def find_token(obj: Any) -> Optional[str]:
    if isinstance(obj, dict):
        cc = obj.get("continuationCommand")
        if isinstance(cc, dict) and cc.get("token"):
            return cc["token"]
        for v in obj.values():
            t = find_token(v)
            if t:
                return t
    elif isinstance(obj, list):
        for v in obj:
            t = find_token(v)
            if t:
                return t
    return None


def _video_id_from(obj: Any) -> Optional[str]:
    found: list[str] = []

    def rec(o: Any) -> None:
        if found:
            return
        if isinstance(o, dict):
            if o.get("addedVideoId"):
                found.append(o["addedVideoId"])
                return
            vid = o.get("videoId")
            if isinstance(vid, str) and len(vid) == 11:
                found.append(vid)
                return
            u = o.get("url")
            if isinstance(u, str):
                m = VIDEO_ID_RE.search(u)
                if m:
                    found.append(m.group(1))
                    return
            for v in o.values():
                rec(v)
        elif isinstance(o, list):
            for v in o:
                rec(v)

    rec(obj)
    return found[0] if found else None


def length_of(obj: Any) -> str:
    """Duration badge from a video/lockup card, if InnerTube sent one."""
    found: list[str] = []

    def rec(o: Any) -> None:
        if found or not isinstance(o, (dict, list)):
            return
        if isinstance(o, dict):
            for key in ("lengthText", "thumbnailOverlayTimeStatusRenderer"):
                if key in o:
                    t = txt(o.get(key) if key == "lengthText" else (o.get(key) or {}).get("text"))
                    if t and ":" in t:
                        found.append(t)
                        return
            badge = o.get("thumbnailBadgeViewModel") or {}
            t = txt(badge.get("text")) if isinstance(badge, dict) else ""
            if t and ":" in t:
                found.append(t)
                return
            for v in o.values():
                rec(v)
        else:
            for v in o:
                rec(v)

    rec(obj)
    return found[0] if found else ""


def walk_search(data: dict) -> tuple[list[dict], list[dict]]:
    videos: list[dict] = []
    channels: list[dict] = []

    def rec(o: Any) -> None:
        if isinstance(o, dict):
            if "videoRenderer" in o:
                r = o["videoRenderer"] or {}
                runs = as_list((r.get("ownerText") or {}).get("runs"))
                owner = runs[0] if runs and isinstance(runs[0], dict) else {}
                browse = (owner.get("navigationEndpoint") or {}).get("browseEndpoint") or {}
                videos.append(
                    {
                        "video_id": r.get("videoId"),
                        "title": txt(r.get("title")),
                        "description": txt(r.get("descriptionSnippet")),
                        "channel": owner.get("text"),
                        "channel_id": browse.get("browseId"),
                        "published": txt(r.get("publishedTimeText")),
                        "views": parse_count(txt(r.get("viewCountText"))),
                        "length": length_of(r),
                    }
                )
            if "channelRenderer" in o:
                r = o["channelRenderer"] or {}
                if isinstance(r, dict):
                    sub_txt = txt(r.get("subscriberCountText"))
                    vid_txt = txt(r.get("videoCountText"))
                    handle = sub_txt if sub_txt.startswith("@") else None
                    subs = None
                    for s in (sub_txt, vid_txt):
                        if not s or s.startswith("@"):
                            continue
                        if _SUB_WORD_RE.search(s):
                            subs = parse_count(s)
                            break
                    channels.append(
                        {
                            "channel_id": r.get("channelId"),
                            "title": txt(r.get("title")),
                            "subs": subs,
                            "handle": handle,
                        }
                    )
            if "lockupViewModel" in o:
                item = _from_lockup(o.get("lockupViewModel") or {})
                if item:
                    videos.append(item)
            if "gridVideoRenderer" in o:
                item = _from_compact(o.get("gridVideoRenderer") or {})
                if item and item.get("video_id"):
                    videos.append(item)
            for v in o.values():
                rec(v)
        elif isinstance(o, list):
            for v in o:
                rec(v)

    rec(data if isinstance(data, dict) else {})
    return _dedupe_videos(videos), channels


def _dedupe_videos(videos: list[dict]) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    for v in videos:
        vid = v.get("video_id")
        if not vid or vid in seen:
            continue
        seen.add(vid)
        out.append(v)
    return out


def parse_subscribers(home: dict) -> Optional[int]:
    """Subscriber count from a channel `browse` payload.

    Prefer pageHeader metadata / accessibility labels over a regex across the
    whole header JSON. The JSON dump used to match `@Name1Msubscribers` as 1M
    and `1,92 k abonnés` as 92k (the `1,` was skipped).
    """
    home = home if isinstance(home, dict) else {}
    header = home.get("header") or {}
    found: list[tuple[int, int]] = []

    def add(text: Any, prio: int) -> None:
        if not isinstance(text, str):
            return
        t = text.strip()
        if not t or t.startswith("@"):
            return
        if not _SUB_WORD_RE.search(t):
            return
        n = parse_count(t)
        if n is not None and n >= 0:
            found.append((prio, n))

    def rec(o: Any) -> None:
        if isinstance(o, dict):
            al = o.get("accessibilityLabel")
            if isinstance(al, str):
                add(al, 3)
            content = o.get("content")
            if isinstance(content, str):
                add(content, 2)
            for key in ("subscriberCountText", "subscriberCountLabel"):
                if key in o:
                    add(txt(o.get(key)), 2)
            for v in o.values():
                rec(v)
        elif isinstance(o, list):
            for v in o:
                rec(v)

    rec(header)
    if not found:
        rec((home.get("metadata") or {}).get("channelMetadataRenderer") or {})
    if not found:
        return None
    nums = sorted({n for _, n in found if n is not None})
    # Compact "572K" (572000) plus an unmatched "572 thousand" (572) — keep K/M.
    if len(nums) >= 2 and nums[-1] >= nums[0] * 900:
        return nums[-1]
    found.sort(key=lambda x: x[0], reverse=True)
    return found[0][1]


# Display names YouTube puts on About → ISO2. Do not use topbar.countryCode
# (that is the viewer's locale) or availableCountryCodes (where the channel is allowed).
_COUNTRY_NAME_ISO = {
    "united arab emirates": "AE",
    "uae": "AE",
    "emirates": "AE",
    "الإمارات العربية المتحدة": "AE",
    "الامارات العربية المتحدة": "AE",
    "egypt": "EG",
    "مصر": "EG",
    "morocco": "MA",
    "maroc": "MA",
    "المغرب": "MA",
    "argentina": "AR",
    "argentina (the)": "AR",
    "brazil": "BR",
    "brasil": "BR",
    "qatar": "QA",
    "قطر": "QA",
    "kuwait": "KW",
    "الكويت": "KW",
    "pakistan": "PK",
    "پاکستان": "PK",
    "saudi arabia": "SA",
    "kingdom of saudi arabia": "SA",
    "السعودية": "SA",
    "india": "IN",
    "turkey": "TR",
    "türkiye": "TR",
    "turkiye": "TR",
    "united states": "US",
    "united states of america": "US",
    "united kingdom": "GB",
    "bangladesh": "BD",
    "indonesia": "ID",
    "nigeria": "NG",
    "kenya": "KE",
    "philippines": "PH",
    "nepal": "NP",
    "france": "FR",
    "algeria": "DZ",
    "الجزائر": "DZ",
}


def _iso_from_country_value(val: Any) -> Optional[str]:
    s = val if isinstance(val, str) else txt(val)
    s = (s or "").strip()
    if not s:
        return None
    if re.fullmatch(r"[A-Za-z]{2}", s):
        return s.upper()
    key = re.sub(r"\s+", " ", s).strip().lower()
    if key.startswith("the "):
        key = key[4:]
    return _COUNTRY_NAME_ISO.get(key) or _COUNTRY_NAME_ISO.get(s)


def about_continuation_token(home: dict) -> Optional[str]:
    """Token for the channel About engagement panel (...more on the header)."""
    found: list[str] = []

    def rec(o: Any) -> None:
        if found:
            return
        if isinstance(o, dict):
            if "showEngagementPanelEndpoint" in o:
                t = find_token(o.get("showEngagementPanelEndpoint"))
                if t:
                    found.append(t)
                    return
            for v in o.values():
                rec(v)
        elif isinstance(o, list):
            for v in o:
                rec(v)

    rec((home or {}).get("header") or {})
    return found[0] if found else None


def parse_channel_country(data: Any) -> Optional[str]:
    """Official YouTube channel country (About region), as ISO2."""
    found: list[str] = []

    def rec(o: Any) -> None:
        if found:
            return
        if isinstance(o, dict):
            vm = o.get("aboutChannelViewModel")
            if isinstance(vm, dict):
                iso = _iso_from_country_value(vm.get("country")) or _iso_from_country_value(
                    vm.get("countryCode")
                )
                if iso:
                    found.append(iso)
                    return
            full = o.get("channelAboutFullMetadataRenderer")
            if isinstance(full, dict):
                iso = _iso_from_country_value(full.get("country"))
                if iso:
                    found.append(iso)
                    return
            for v in o.values():
                rec(v)
        elif isinstance(o, list):
            for v in o:
                rec(v)

    rec(data if isinstance(data, (dict, list)) else {})
    return found[0] if found else None


def comment_count(nxt: dict) -> Optional[int]:
    found: list[Optional[int]] = []

    def rec(o: Any) -> None:
        if found:
            return
        if isinstance(o, dict):
            if o.get("panelIdentifier") == "engagement-panel-comments-section":
                hdr = (o.get("header") or {}).get("engagementPanelTitleHeaderRenderer") or {}
                found.append(parse_count(txt(hdr.get("contextualInfo"))))
                return
            hdr = o.get("commentsHeaderRenderer")
            if isinstance(hdr, dict):
                n = parse_count(txt(hdr.get("commentsCount") or hdr.get("countText")))
                if n is not None:
                    found.append(n)
                    return
            for k in ("commentCount", "commentsCount"):
                v = o.get(k)
                if isinstance(v, (int, float)) and v >= 0:
                    found.append(int(v))
                    return
                if isinstance(v, dict):
                    n = parse_count(txt(v))
                    if n is not None:
                        found.append(n)
                        return
            for v in o.values():
                rec(v)
        elif isinstance(o, list):
            for v in o:
                rec(v)

    rec(nxt)
    return found[0] if found else None


# Button/factoid labels that mean likes, not views.
LIKE_LABEL_RE = re.compile(
    r"\blikes?\b|j['’]aime|gefällt|me gusta|curtidas?|лайк|좋아요|いいね|"
    r"إعجاب|معجب|أعجب|suka|讚|点赞",
    re.I,
)


def like_count(nxt: dict) -> Optional[int]:
    """Likes on the watch page. Views and dislikes are ignored.

    InnerTube moves this around: likeCount* numbers, like-button title (12K),
    accessibilityText (“like this video along with 1,234 other people”),
    or a factoid labelled Likes / إعجاب.
    """
    found: list[int] = []

    def take(n: Optional[int]) -> None:
        if n is not None and n >= 0 and not found:
            found.append(int(n))

    def rec(o: Any, like_ctx: bool = False) -> None:
        if found:
            return
        if isinstance(o, dict):
            for k in (
                "likeCountIfIndifferentNumber",
                "likeCountIfLikedNumber",
                "likeCountNumber",
            ):
                v = o.get(k)
                if isinstance(v, bool):
                    continue
                if isinstance(v, (int, float)) and v >= 0:
                    take(int(v))
                    return
                if isinstance(v, str):
                    take(parse_count(v))
                    if found:
                        return
            fr = o.get("factoidRenderer") if "factoidRenderer" in o else None
            if fr is None and "label" in o and "value" in o:
                fr = o
            if isinstance(fr, dict):
                label = txt(fr.get("label"))
                if LIKE_LABEL_RE.search(label or ""):
                    take(parse_count(txt(fr.get("value"))))
                    if found:
                        return
            acc = o.get("accessibilityText")
            if isinstance(acc, str) and LIKE_LABEL_RE.search(acc):
                take(parse_count(acc))
                if found:
                    return
            if like_ctx:
                title = o.get("title")
                if isinstance(title, str) and re.search(r"\d", title):
                    take(parse_count(title))
                    if found:
                        return
                if isinstance(title, dict):
                    take(parse_count(txt(title)))
                    if found:
                        return
            for k, v in o.items():
                kl = str(k).lower()
                rec(v, like_ctx or ("like" in kl and "dislike" not in kl))
        elif isinstance(o, list):
            for v in o:
                rec(v, like_ctx)

    rec(nxt)
    return found[0] if found else None


def description_from_next(nxt: dict) -> str:
    nxt = nxt if isinstance(nxt, dict) else {}
    col = (nxt.get("contents") or {}).get("twoColumnWatchNextResults") or {}
    inner = col.get("results") or {}
    if not isinstance(inner, dict):
        inner = {}
    nest = inner.get("results") or {}
    if not isinstance(nest, dict):
        nest = {}
    contents = as_list(nest.get("contents"))
    desc = ""
    for c in contents:
        if not isinstance(c, dict):
            continue
        sec = c.get("videoSecondaryInfoRenderer") or {}
        desc = txt(sec.get("description")) or desc
        attr = sec.get("attributedDescription")
        if isinstance(attr, dict):
            desc = desc or json.dumps(attr, ensure_ascii=False)
        elif isinstance(attr, str):
            desc = desc or attr
    urls = extract_http_urls(nxt)
    if urls:
        desc = (desc + "\n" + "\n".join(urls)).strip()
    return desc


def attach_descriptions(vids, fetch_next, cache: dict | None = None) -> int:
    """Fill each hit's description from the search snippet, else fetch_next(id).

    Returns how many watch pages were fetched. Snippets and the cache skip a
    round-trip so a description-only search is not one next() per result.
    """
    store = cache if cache is not None else {}
    fetched = 0
    for it in vids or []:
        if not isinstance(it, dict):
            continue
        vid = it.get("video_id")
        existing = (it.get("description") or "").strip()
        if existing:
            if vid:
                store[vid] = existing
            continue
        if vid and vid in store:
            it["description"] = store[vid]
            continue
        if not vid or fetch_next is None:
            continue
        try:
            nxt = fetch_next(vid)
        except Exception:
            nxt = {}
        desc = description_from_next(nxt or {})
        it["description"] = desc
        store[vid] = desc
        fetched += 1
    return fetched


def extract_http_urls(obj: Any) -> list[str]:
    """http(s) URLs from InnerTube (urlEndpoint, youtube redirect q=, raw strings)."""
    found: list[str] = []
    seen: set[str] = set()

    def add(u: str) -> None:
        u = (u or "").strip()
        if not u or u in seen:
            return
        if u.startswith("http://") or u.startswith("https://"):
            seen.add(u)
            found.append(u)
            if "q=" in u and "youtube.com/redirect" in u:
                m = re.search(r"[?&]q=([^&]+)", u)
                if m:
                    from urllib.parse import unquote

                    add(unquote(m.group(1)))

    def rec(o: Any) -> None:
        if isinstance(o, dict):
            ep = o.get("urlEndpoint")
            if isinstance(ep, dict) and isinstance(ep.get("url"), str):
                add(ep["url"])
            if isinstance(o.get("url"), str):
                add(o["url"])
            for v in o.values():
                rec(v)
        elif isinstance(o, list):
            for v in o:
                rec(v)
        elif isinstance(o, str) and "http" in o:
            for m in re.findall(r"https?://[^\s\"'<>]+", o):
                add(m)

    rec(obj)
    return found


_RELATED_RENDERERS = {
    "compactVideoRenderer",
    "compactChannelRenderer",
    "gridChannelRenderer",
    "channelRenderer",
    "endScreenChannelRenderer",
    "lockupViewModel",
    "videoRenderer",
    "playlistVideoRenderer",
    "gridVideoRenderer",
}
_SKIP_RELATED = {
    "commentRenderer",
    "commentThreadRenderer",
    "engagementPanelSectionListRenderer",
    "frameworkUpdates",
    "playerOverlays",
}


def _uc_id(val: Any) -> Optional[str]:
    if isinstance(val, str) and val.startswith("UC") and len(val) >= 22:
        return val
    return None


# The views half of a lockup row, per locale. Anything not listed here falls
# through to the date and then the name slot, which is how the Indonesian
# Videos tab ("468 x ditonton") used to lose both its views and its date.
_VIEWS_RE = re.compile(
    r"view|مشاهد|vues|vistas|visualiza|görüntülenme|aufruf|"
    r"ditonton|tontonan|penonton|ملاحظات|بار دیکھا",
    re.I,
)


def _lockup_part_text(part: Any) -> str:
    if not isinstance(part, dict):
        return ""
    return txt(part.get("text")) or str(part.get("accessibilityLabel") or "")


def _lockup_channel(lv: dict) -> tuple[str, Optional[str], Optional[int], str]:
    """Channel name, id, views, published from a lockup card.

    Search cards often use row 0 = name, row 1 = views + date. The channel
    Videos tab uses a single row of [views, relative date] and no name.
    """
    meta = (lv.get("metadata") or {}).get("lockupMetadataViewModel") or {}
    cm = ((meta.get("metadata") or {}).get("contentMetadataViewModel") or {})
    rows = as_list(cm.get("metadataRows"))
    name = ""
    views = None
    published = ""
    for row in rows:
        for p in as_list(row.get("metadataParts") if isinstance(row, dict) else None):
            tx = _lockup_part_text(p)
            if not tx:
                continue
            if _VIEWS_RE.search(tx):
                n = parse_count(tx)
                if n is not None:
                    views = n
                continue
            if recency_days(tx) is not None or re.search(
                r"\bago\b|il y a|قبل |منذ |hours?|days?|weeks?|months?|years?",
                tx,
                re.I,
            ):
                published = published or tx
                continue
            if not name:
                name = tx
    cid = None

    def rec(o: Any) -> None:
        nonlocal cid
        if cid:
            return
        if isinstance(o, dict):
            bid = _uc_id(o.get("browseId"))
            if bid:
                cid = bid
                return
            for v in o.values():
                rec(v)
        elif isinstance(o, list):
            for v in o:
                rec(v)

    rec(meta.get("image") or lv)
    return name, cid, views, published


def _from_lockup(lv: dict) -> Optional[dict]:
    if not isinstance(lv, dict):
        return None
    ctype = lv.get("contentType") or ""
    if ctype and ctype != "LOCKUP_CONTENT_TYPE_VIDEO":
        return None
    title = ((lv.get("metadata") or {}).get("lockupMetadataViewModel") or {}).get("title") or {}
    t = title.get("content") if isinstance(title, dict) else txt(title)
    name, cid, views, published = _lockup_channel(lv)
    vid = lv.get("contentId") or _video_id_from(lv)
    if not vid:
        return None
    return {
        "video_id": vid,
        "title": t or "",
        "channel": name,
        "channel_id": cid,
        "views": views,
        "published": published,
        "length": length_of(lv),
    }


def _from_compact(r: dict) -> Optional[dict]:
    if not isinstance(r, dict):
        return None
    runs = as_list((r.get("shortBylineText") or {}).get("runs"))
    owner = runs[0] if runs and isinstance(runs[0], dict) else {}
    browse = (owner.get("navigationEndpoint") or {}).get("browseEndpoint") or {}
    return {
        "video_id": r.get("videoId"),
        "title": txt(r.get("title")),
        "channel": owner.get("text") or txt(r.get("shortBylineText")),
        "channel_id": r.get("channelId") or browse.get("browseId"),
        "views": parse_count(txt(r.get("viewCountText"))),
        "published": txt(r.get("publishedTimeText")),
        "length": length_of(r),
    }


def related_videos(data: Any) -> list[dict]:
    """Watch Next / end-screen video cards with channel ids."""
    out: list[dict] = []
    seen: set[str] = set()

    def add(item: Optional[dict]) -> None:
        if not item:
            return
        vid = item.get("video_id")
        if not vid or vid in seen:
            return
        seen.add(vid)
        out.append(item)

    def rec(o: Any) -> None:
        if isinstance(o, dict):
            if "lockupViewModel" in o:
                add(_from_lockup(o.get("lockupViewModel") or {}))
            if "compactVideoRenderer" in o:
                add(_from_compact(o.get("compactVideoRenderer") or {}))
            if "endScreenVideoRenderer" in o:
                add(_from_compact(o.get("endScreenVideoRenderer") or {}))
            for v in o.values():
                rec(v)
        elif isinstance(o, list):
            for v in o:
                rec(v)

    rec(data)
    return out


def watch_next_token(data: Any) -> Optional[str]:
    """Continuation for the related-video rail, not comments."""
    found: list[str] = []

    def rec(o: Any, ok: bool = False) -> None:
        if found:
            return
        if isinstance(o, dict):
            if o.get("targetId") == "watch-next-feed":
                ok = True
            if ok:
                cc = o.get("continuationCommand")
                if isinstance(cc, dict) and cc.get("token"):
                    found.append(cc["token"])
                    return
            for k, v in o.items():
                rec(v, ok or k in ("secondaryResults", "appendContinuationItemsAction"))
        elif isinstance(o, list):
            for v in o:
                rec(v, ok)

    rec(data)
    return found[0] if found else None


def related_channel_ids(data: Any) -> list[str]:
    """Channels YouTube puts next to a video or on a channel page — not comment authors."""
    ids: list[str] = []
    seen: set[str] = set()

    def rec(o: Any, in_related: bool = False) -> None:
        if isinstance(o, dict):
            if in_related:
                cid = _uc_id(o.get("channelId")) or _uc_id(o.get("browseId"))
                be = o.get("browseEndpoint")
                if not cid and isinstance(be, dict):
                    cid = _uc_id(be.get("browseId"))
                if cid and cid not in seen:
                    seen.add(cid)
                    ids.append(cid)
            for k, v in o.items():
                if k in _SKIP_RELATED:
                    continue
                rec(v, in_related or k in _RELATED_RENDERERS)
        elif isinstance(o, list):
            for v in o:
                rec(v, in_related)

    rec(data)
    return ids


def hashtag_browses(data: Any) -> list[tuple[str, str, str]]:
    """Return (tag, browseId, params) from hashtag tiles."""
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    def rec(o: Any) -> None:
        if isinstance(o, dict):
            if "hashtagTileRenderer" in o:
                t = o["hashtagTileRenderer"] or {}
                tag = txt(t.get("hashtag")).lstrip("#")
                be = ((t.get("onTapCommand") or {}).get("browseEndpoint") or {})
                bid, params = be.get("browseId"), be.get("params")
                key = f"{bid}:{params}"
                if tag and bid and params and key not in seen:
                    seen.add(key)
                    out.append((tag, bid, params))
            be = o.get("browseEndpoint") if isinstance(o.get("browseEndpoint"), dict) else {}
            bid = be.get("browseId")
            params = be.get("params")
            if isinstance(bid, str) and bid.startswith("FEhashtag") and params:
                key = f"{bid}:{params}"
                if key not in seen:
                    tag = (bid.replace("FEhashtag", "").lstrip("_") or txt(o.get("text") or o.get("hashtag"))).lstrip("#")
                    seen.add(key)
                    out.append((tag or "hashtag", bid, params))
            for v in o.values():
                rec(v)
        elif isinstance(o, list):
            for v in o:
                rec(v)

    rec(data)
    return out


# Relative-date words, per desk locale. YouTube answers in the language the
# pack asks for, so the Indonesian desk gets "2 bulan yang lalu" and the
# Pakistani one "2 مہینے پہلے". A unit this table does not know used to
# come back as None, and `score_row` reads an unknown age as "let it through" --
# which is how an Indonesian run filled up with channels last seen years ago.
_UNIT_DAYS: dict[str, int] = {}
for _tokens, _per in (
    (
        # under a day -- always 0
        "second seconds minute minutes hour hours "
        "seconde secondes heure heures "
        "segundo segundos minuto minutos hora horas "
        "detik menit minit jam "
        "ثانية ثوان ثواني دقيقة دقائق ساعة ساعات "
        "سیکنڈ منٹ گھنٹہ گھنٹے گھنٹوں",
        0,
    ),
    (
        "day days jour jours día días dia dias hari "
        "يوم أيام ايام "
        "دن دنوں روز",
        1,
    ),
    (
        "week weeks semaine semaines semana semanas minggu "
        "أسبوع اسبوع أسابيع اسابيع "
        "ہفتہ ہفتے ہفتوں",
        7,
    ),
    (
        "month months mois mes meses mês bulan "
        "شهر أشهر اشهر شهور "
        "مہینہ مہینے مہینوں ماہ",
        30,
    ),
    (
        "year years an ans année années annee annees "
        "año años ano anos tahun "
        "سنة سنوات سنين عام أعوام اعوام "
        "سال سالوں برس",
        365,
    ),
):
    for _t in _tokens.split():
        _UNIT_DAYS[_t] = _per

# Longest first so `meses` never matches as `mes` and `أشهر` never as `شهر`.
_AGE_RE = re.compile(
    r"(\d+)\s*(" + "|".join(re.escape(t) for t in sorted(_UNIT_DAYS, key=len, reverse=True)) + r")(?!\w)"
)

# Arabic-Indic and Urdu digits. YouTube writes counts in them for ar/ur.
_DIGIT_MAP = {chr(0x0660 + i): str(i) for i in range(10)}
_DIGIT_MAP.update({chr(0x06F0 + i): str(i) for i in range(10)})
_ARABIC_DIGITS = re.compile("[" + "".join(_DIGIT_MAP) + "]")

_TODAY_RE = re.compile(
    r"\btoday\b|just now|aujourd|\bhoy\b|\bhoje\b|hari ini|baru saja|baru sahaja|"
    r"اليوم|الآن"
)
_YESTERDAY_RE = re.compile(r"\byesterday\b|\bhier\b|\bayer\b|\bontem\b|\bkemarin\b|أمس")

# Arabic writes "one" and "two" into the noun, with no digit to match on:
# `قبل شهرين` is two months and `قبل شهر واحد` is one.
_WORD_AGES = [
    (re.compile(r"ساعتين|ساعتان|دقيقتين|ساعة واحدة|دقيقة واحدة"), 0),
    (re.compile(r"يومين|يومان"), 2),
    (re.compile(r"يوم واحد|يوماً واحداً"), 1),
    (re.compile(r"أسبوعين|أسبوعان"), 14),
    (re.compile(r"أسبوع واحد"), 7),
    (re.compile(r"شهرين|شهران"), 60),
    (re.compile(r"شهر واحد|شهراً واحداً"), 30),
    (re.compile(r"سنتين|سنتان|عامين|عامان"), 730),
    (re.compile(r"سنة واحدة|عام واحد"), 365),
]


def recency_days(published: Optional[str]) -> Optional[int]:
    """Days since upload from YouTube's relative date text, in any desk locale.

    Returns None only when the text carries no readable age at all. Callers
    treat None as unknown, so a locale this cannot read silently disables the
    recency floor -- keep `_UNIT_DAYS` in step with every pack language.
    """
    p = _ARABIC_DIGITS.sub(lambda m: _DIGIT_MAP[m.group(0)], (published or "").lower())
    if _TODAY_RE.search(p):
        return 0
    if _YESTERDAY_RE.search(p):
        return 1
    for pattern, days in _WORD_AGES:
        if pattern.search(p):
            return days
    m = _AGE_RE.search(p)
    if not m:
        return None
    return int(m.group(1)) * _UNIT_DAYS[m.group(2)]


def walk_videos(data: Any) -> list[dict]:
    """Flat video cards from search, trending, or home. Deduped by video id."""
    videos, _ = walk_search(data if isinstance(data, dict) else {})
    extra = related_videos(data)
    seen = {v.get("video_id") for v in videos if v.get("video_id")}
    for it in extra:
        vid = it.get("video_id")
        if vid and vid not in seen:
            videos.append(it)
            seen.add(vid)
    return [v for v in videos if v.get("video_id")]


def _views_from_watch(r: dict) -> Optional[int]:
    """Watch-page view count. WEB nests it under videoViewCountRenderer."""
    vc = r.get("viewCount")
    if isinstance(vc, dict):
        inner = vc.get("videoViewCountRenderer") or vc
        if isinstance(inner, dict):
            for key in ("viewCount", "shortViewCount", "extraShortViewCount", "unlabeledViewCountValue"):
                n = parse_count(txt(inner.get(key)))
                if n is not None:
                    return n
            raw = inner.get("originalViewCount")
            if isinstance(raw, str) and raw.isdigit():
                return int(raw)
            if isinstance(raw, (int, float)) and raw >= 0:
                return int(raw)
        n = parse_count(txt(vc))
        if n is not None:
            return n
    return parse_count(txt(vc)) if vc is not None else None


def watch_info(data: Any) -> dict:
    """Title / channel / views / likes / comments from a `/next` payload.

    Likes and comments are already on this watch page — no extra InnerTube call.
    """
    title = ""
    channel = ""
    channel_id = None
    views = None
    published = ""
    description = ""
    subscribers = None

    def rec(o: Any) -> None:
        nonlocal title, channel, channel_id, views, published, description, subscribers
        if isinstance(o, dict):
            if "videoPrimaryInfoRenderer" in o:
                r = o.get("videoPrimaryInfoRenderer") or {}
                title = title or txt(r.get("title"))
                if views is None:
                    views = _views_from_watch(r)
                published = published or txt(r.get("relativeDateText")) or txt(r.get("dateText"))
            if "videoSecondaryInfoRenderer" in o:
                r = o.get("videoSecondaryInfoRenderer") or {}
                owner = ((r.get("owner") or {}).get("videoOwnerRenderer") or {})
                _apply_owner(owner)
                description = description or _description_text(r)
            if "videoOwnerRenderer" in o:
                _apply_owner(o.get("videoOwnerRenderer") or {})
            for v in o.values():
                rec(v)
        elif isinstance(o, list):
            for v in o:
                rec(v)

    def _apply_owner(owner: dict) -> None:
        nonlocal channel, channel_id, subscribers
        if not isinstance(owner, dict):
            return
        channel = channel or txt(owner.get("title"))
        runs = as_list((owner.get("title") or {}).get("runs"))
        if runs and isinstance(runs[0], dict):
            browse = (runs[0].get("navigationEndpoint") or {}).get("browseEndpoint") or {}
            channel_id = channel_id or browse.get("browseId")
            channel = channel or runs[0].get("text") or channel
        subscribers = subscribers if subscribers is not None else parse_count(txt(owner.get("subscriberCountText")))

    rec(data)
    payload = data if isinstance(data, dict) else {}
    return {
        "title": title,
        "channel": channel,
        "channel_id": channel_id,
        "views": views,
        "likes": like_count(payload),
        "comments": comment_count(payload),
        "subscribers": subscribers,
        "published": published,
        "description": description,
    }


def _description_text(r: dict) -> str:
    d = txt(r.get("description"))
    if d:
        return d
    attr = r.get("attributedDescription")
    if isinstance(attr, dict) and isinstance(attr.get("content"), str):
        return attr["content"]
    return txt(attr)
