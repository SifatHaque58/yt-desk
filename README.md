# yt-desk

Local YouTube-shaped desk: **search, home, and Up next** from YouTube’s own InnerTube WEB API, through a split [Private Internet Access](https://www.privateinternetaccess.com/) tunnel so ranking matches the country you are sitting in as far as YouTube is concerned.

It is a sibling of [rizon-yt-scout](https://github.com/SifatHaque58/rizon-yt-scout). The scout finds creators. This one is for watching a market the way YouTube ranks it.

Not the YouTube Data API. No Google Cloud key. No LLM. Not a downloader — it never calls InnerTube `/player` and does not fetch streams.

---

## What is native, what is not

| Surface | Source | Geo |
|---|---|---|
| Search + typeahead | InnerTube `search` + Google suggest | Tunnel IP + `hl` / `gl` |
| Up next | InnerTube `/next` | Tunnel IP (this is the algo) |
| Views / likes / comments / subs | Same `/next` payload as Up next | No extra calls |
| Home / For You | `FEwhat_to_watch` after 3 watches in that country | Sticky `visitorData` per country |
| Cold start | Official `FEtrending` when WEB still serves it; otherwise this week’s locale “news” search | Tunnel IP + `gl` |
| Player | `youtube.com/embed` | **This machine’s IP** (see [Player and bot walls](#player-and-bot-walls)) |

`gl` is a hint. YouTube ranks the **exit IP**. A `gl=US` run from a Bangladesh home IP still fills with BD news. The header’s `YouTube: XX` is measured from youtube.com through the proxy — not from `piactl`.

Logged-out YouTube home is empty until you watch. Cookie / signed-in For You is not in this version.

---

## Requirements

- Python **3.10+** (3.11 tested)
- macOS, Linux, or Windows
- Network access to YouTube
- Optional: [Private Internet Access](https://www.privateinternetaccess.com/) with `piactl`, exiting in the **same country** you want ranked — especially for Up next

---

## Install

```bash
git clone https://github.com/SifatHaque58/yt-desk.git
cd yt-desk
./start.sh
```

Opens **http://127.0.0.1:5056** (5055 is the scout).

Manual:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python app.py
```

---

## Country + VPN

The desk can leave through a PIA exit in the market you picked, so search and Up next rank the way they do for someone actually there. Nothing else on the machine has to be tunnelled.

```
desk (InnerTube)  ──► 127.0.0.1:8118 ──► [pinned to utunN] ──► YouTube
browser / git     ──────────────────────────────────────────► en0
```

Connect PIA yourself, **split** it (All Other Apps → Bypass VPN), pick the region, then:

```bash
SCOUT_TUNNEL=1 ./start.sh
```

Or use **VPN on** in the header. That starts `tools/tun-http-proxy.py` on `127.0.0.1:8118`. Fail closed: routing on + proxy down = requests error, they do not leak a home-IP SERP.

`YouTube: MA` in the chip is measured. PIA’s region name is not trusted (the scout measured an Argentina exit that YouTube served as **US**). If the chip and the country picker disagree, pick another PIA region or run locale-only.

| Variable | Effect |
|---|---|
| `SCOUT_TUNNEL=1` | Start the proxy with the desk |
| `SCOUT_PROXY` | Proxy URL. `off` forces direct. Default `127.0.0.1:8118` when listening |
| `SCOUT_PROXY_PORT` | Proxy port (default 8118) |

Same env names as the scout so one proxy can serve both.

---

## Player and bot walls

The iframe is convenience. The related rail is the product.

YouTube often shows **“Sign in to confirm you’re not a bot”** when the **player** goes out a VPN/datacenter IP. Search can still work.

- **Split PIA** so the browser (and therefore the embed) uses your home IP. InnerTube stays on the tunnel.
- Or sign in on [youtube.com](https://www.youtube.com) in this browser, then play again. The embed is `youtube.com` on purpose — `youtube-nocookie.com` never sees that login.
- Or use **Watch on YouTube**.

If PIA is carrying the whole machine, the header warns. Split it if you want git and the browser off the tunnel.

---

## Using it

1. Pick a country. Set VPN on if you have an exit YouTube agrees is that market.
2. Home is this week’s ranked news (or trending) until you watch 3 videos in that country; then it asks For You.
3. Search like YouTube. Typeahead, upload-date filter, infinite scroll.
4. Watch: embed on the left, **Up next from `/next` through the tunnel** on the right. Views, likes, comments, and subs come from that same call.

A sticky anonymous `visitorData` is stored per country in `data/session.json` (not committed).

---

## HTTP API

All YouTube traffic from these routes uses the InnerTube client + proxy.

| Method | Path | |
|---|---|---|
| `GET` | `/` | UI |
| `GET` | `/api/countries` | Locale list |
| `GET` / `POST` | `/api/session` | `{gl}` |
| `GET` | `/api/proxy?check=true` | Tunnel + measured YouTube country |
| `POST` | `/api/proxy/start` · `/stop` | Loopback CONNECT proxy |
| `GET` | `/api/suggest?q=` | Typeahead |
| `GET` / `POST` | `/api/search` | `{q, uploaded, continuation}` |
| `GET` / `POST` | `/api/home` · `/api/trending` | Cold start / For You |
| `GET` / `POST` | `/api/watch/{id}` | Metadata, stats, related. POST for continuation |
| `POST` | `/api/history` | Local watch count per country |

Continuations are POST so tokens do not blow the URL.

---

## Project layout

```
app.py                 # FastAPI
desk/yt.py             # InnerTube WEB wrapper (no /player)
desk/parse.py          # Search / next / likes / comments
desk/tunnel.py         # PIA pin + measured country
desk/session.py        # visitorData per gl
tools/tun-http-proxy.py
web/static/            # UI
tests/
```

---

## Tests

```bash
PYTHONPATH=. python -m unittest discover -s tests -v
```

No live YouTube in CI. Against a running desk, smoke search / watch / related through the proxy.

---

## Limits

- Unofficial InnerTube. WEB payloads move; parsers are defensive.
- PIA region ≠ YouTube market. Measure before trusting a run.
- Anonymous For You is not a logged-in account feed.
- Embed geo and InnerTube geo are different on purpose when PIA is split.
- Same ToS posture as the scout: local metadata client, no streams, no scraping-at-scale claims.

---

## License

MIT
