"""Where the VPN tunnel is, and how the desk reaches YouTube through it.

The desk scouts markets it is not sitting in. A run for Egypt done from a US
IP gets a US-flavoured SERP and the wrong "Up next" rail, so the country tag
work in `score.py` is fighting the search itself. Routing the whole machine
through PIA is the blunt fix and it breaks everything else: git, the browser,
the other tools on this laptop.

So the tunnel is used surgically. PIA stays split -- this machine's normal
traffic never enters it -- and a small CONNECT proxy (`tools/tun-http-proxy.py`)
listens on loopback and pins each outbound socket to the tunnel interface.
Only InnerTube traffic is handed to that proxy. This module is the shared
knowledge of *where* the tunnel is; the proxy binds to it, `yt.py` points at
the proxy, and `/api/proxy` reports it.

Env:
  SCOUT_PROXY       proxy URL for InnerTube; "off"/"0" disables. Default
                    http://127.0.0.1:8118 when the proxy is up, else direct.
  SCOUT_BIND_IP     pin the tunnel IP by hand instead of asking piactl.
  SCOUT_BIND_IF     pin the tunnel interface by hand (e.g. utun4).
"""
from __future__ import annotations

import os
import re
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

PIACTL = "/usr/local/bin/piactl"
DEFAULT_PROXY = "http://127.0.0.1:8118"
TIMEOUT = 5

# Darwin socket options that pin a socket to one interface regardless of the
# routing table. Binding the source IP alone is not enough on macOS: the route
# lookup is by destination, so a tun-sourced packet still leaves via en0.
IP_BOUND_IF = 25  # <netinet/in.h>  IPPROTO_IP
IPV6_BOUND_IF = 125  # <netinet6/in6.h>  IPPROTO_IPV6


def _piactl(*args: str) -> str:
    """One-shot piactl read. Empty string when PIA is not installed or slow."""
    try:
        out = subprocess.run(
            [PIACTL, *args],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    value = out.stdout.strip()
    if out.returncode != 0 or value in {"Unknown", "Unavailable"}:
        return ""
    return value


def connection_state() -> str:
    return _piactl("get", "connectionstate") or "Unknown"


def region() -> str:
    return _piactl("get", "region") or ""


def public_ip() -> str:
    """PIA's view of the exit IP. Not proof the desk uses it -- see `verify`."""
    return _piactl("get", "pubip") or ""


def endpoint_ip() -> str:
    """The VPN *server* address piactl calls "vpnip".

    Named apart from the tunnel address on purpose. On WireGuard/macOS
    `piactl get vpnip` reports the server endpoint -- 64.40.151.246, reached
    over en0 via the LAN gateway -- not the 10.x address the tunnel actually
    assigned. Binding a socket to it would bind to nothing local. It is kept
    only as a label for which server is in use.
    """
    return _piactl("get", "vpnip")


def _ifconfig() -> str:
    try:
        return subprocess.run(
            ["/sbin/ifconfig"], capture_output=True, text=True, timeout=TIMEOUT
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _netstat_routes() -> str:
    try:
        return subprocess.run(
            ["/usr/sbin/netstat", "-rn", "-f", "inet"],
            capture_output=True,
            text=True,
            timeout=TIMEOUT,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _addresses_from_ifconfig(text: str) -> dict[str, str]:
    """`{interface: first IPv4}` for every interface that has one.

    macOS keeps several system `utun`s up at all times (Back to My Mac and
    friends); those carry link-local IPv6 only. Holding an IPv4 address is
    what separates a real VPN tunnel from them.
    """
    found: dict[str, str] = {}
    current = ""
    for line in text.splitlines():
        header = re.match(r"^([a-zA-Z0-9]+):\s", line)
        if header:
            current = header.group(1)
            continue
        stripped = line.strip()
        if stripped.startswith("inet ") and current and current not in found:
            parts = stripped.split()
            if len(parts) > 1:
                found[current] = parts[1]
    return found


def _tunnel_interface_from_routes(text: str) -> str:
    """The tun carrying the default route, when there is one.

    A full-tunnel PIA installs `0/1` and `128.0/1` over the real default
    rather than replacing it. Either half names the tunnel outright, so it is
    the most direct answer when the VPN is not split.
    """
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        destination, netif = parts[0], parts[-1]
        if destination in {"0/1", "128.0/1", "default"} and netif.startswith(("utun", "tun", "ppp")):
            return netif
    return ""


def interface_name() -> str:
    """Which interface the VPN tunnel is on, or "" when there is none.

    Resolved from the machine rather than remembered: PIA does not land on the
    same `utun` across reconnects, and a split tunnel has no default route to
    point at, so the IPv4-bearing tun is the fallback signal.
    """
    forced = os.environ.get("SCOUT_BIND_IF", "").strip()
    if forced:
        return forced
    addresses = _addresses_from_ifconfig(_ifconfig())
    routed = _tunnel_interface_from_routes(_netstat_routes())
    if routed and routed in addresses:
        return routed
    tunnels = [name for name in addresses if name.startswith(("utun", "tun", "ppp"))]
    return tunnels[0] if len(tunnels) == 1 else (tunnels[0] if tunnels else "")


def vpn_ip(interface: str = "") -> str:
    """The tunnel's own IPv4 address -- the one worth binding to.

    SCOUT_BIND_IP wins, so a tunnel PIA does not manage (or a test) can be
    pinned by hand.
    """
    forced = os.environ.get("SCOUT_BIND_IP", "").strip()
    if forced:
        return forced
    name = interface or interface_name()
    if not name:
        return ""
    return _addresses_from_ifconfig(_ifconfig()).get(name, "")


def full_tunnel() -> bool:
    """True when PIA is carrying the whole machine, not just this desk.

    Worth saying out loud: with a full tunnel the proxy is redundant and every
    other thing on the laptop -- git, the browser -- is on the foreign exit
    too. That is the setup this module exists to avoid.
    """
    return bool(_tunnel_interface_from_routes(_netstat_routes()))


@dataclass(frozen=True)
class Tunnel:
    ip: str
    interface: str
    state: str
    region: str
    whole_machine: bool = False

    @property
    def up(self) -> bool:
        return bool(self.ip)

    @property
    def index(self) -> int:
        """Interface index for IP_BOUND_IF. 0 when the name does not resolve."""
        if not self.interface:
            return 0
        try:
            return socket.if_nametoindex(self.interface)
        except OSError:
            return 0

    def as_dict(self) -> dict:
        return {
            "up": self.up,
            "ip": self.ip,
            "interface": self.interface,
            "state": self.state,
            "region": self.region,
            "whole_machine": self.whole_machine,
        }


def current() -> Tunnel:
    interface = interface_name()
    return Tunnel(
        ip=vpn_ip(interface),
        interface=interface,
        state=connection_state(),
        region=region(),
        whole_machine=full_tunnel(),
    )


def bind_socket(sock: socket.socket, tunnel: Tunnel) -> None:
    """Pin `sock` to the tunnel: interface first, then source address.

    IP_BOUND_IF is what actually overrides the route table on macOS. The
    source bind is kept because it is what makes the packet *look* like it
    came from the tunnel, and it is the whole mechanism on Linux.
    """
    index = tunnel.index
    if index:
        family = sock.family
        if family == socket.AF_INET6:
            sock.setsockopt(socket.IPPROTO_IPV6, IPV6_BOUND_IF, index)
        else:
            sock.setsockopt(socket.IPPROTO_IP, IP_BOUND_IF, index)
    if tunnel.ip and sock.family == socket.AF_INET:
        sock.bind((tunnel.ip, 0))


ROUTING_FLAG = Path(__file__).resolve().parents[1] / "data" / "routing-on"


def routing_wanted() -> bool:
    """True when the desk is supposed to pin YouTube to the tunnel.

    Fail closed in that state: a down proxy must not silently search from the
    home IP. Direct mode is only when routing is off.
    """
    value = os.environ.get("SCOUT_PROXY", "").strip()
    if value.lower() in {"off", "0", "no", "false", "direct"}:
        return False
    if value:
        return True
    if os.environ.get("SCOUT_TUNNEL", "0").strip().lower() not in {"0", "", "false", "no", "off"}:
        return True
    return ROUTING_FLAG.exists()


def proxy_url() -> str:
    """Proxy InnerTube should use, or "" for a direct connection.

    When routing is wanted, always return the proxy URL even if nothing is
    listening — InnerTube then fails instead of leaking a home-IP SERP.
    When routing is off, use the proxy only if it is already up.
    """
    value = os.environ.get("SCOUT_PROXY", "").strip()
    if value.lower() in {"off", "0", "no", "false", "direct"}:
        return ""
    if value:
        return value
    if routing_wanted():
        return DEFAULT_PROXY
    return DEFAULT_PROXY if proxy_listening(DEFAULT_PROXY) else ""


def _host_port(url: str) -> tuple[str, int]:
    body = url.split("://", 1)[-1]
    host, _, port = body.partition(":")
    return host or "127.0.0.1", int(port or 8118)


def proxy_listening(url: str = "") -> bool:
    host, port = _host_port(url or DEFAULT_PROXY)
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


# --- running the proxy from the desk ---------------------------------------
#
# The toggle in the header starts and stops this process. It is deliberately a
# separate process rather than a thread inside the desk: a proxy that dies with
# a reload, or wedges the event loop, would take the lists down with it.

ROOT = Path(__file__).resolve().parents[1]
PROXY_SCRIPT = ROOT / "tools" / "tun-http-proxy.py"
PID_FILE = ROOT / "data" / "tun-proxy.pid"
PROXY_LOG = ROOT / "tun-proxy.log"


def proxy_pid() -> int:
    """PID of a live proxy, or 0. A stale pid file counts as not running."""
    try:
        pid = int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0
    try:
        os.kill(pid, 0)
    except OSError:
        return 0
    return pid


def start_proxy(port: int = 8118) -> dict:
    """Launch the proxy detached and wait for it to accept a connection.

    Returns before the port is open only if it never opens -- the caller (and
    the header) would otherwise report "on" while the next run went direct.
    """
    try:
        ROUTING_FLAG.parent.mkdir(parents=True, exist_ok=True)
        ROUTING_FLAG.write_text("1\n", encoding="utf-8")
    except OSError:
        pass
    if proxy_listening(f"http://127.0.0.1:{port}"):
        return {"ok": True, "pid": proxy_pid(), "already": True}
    if not PROXY_SCRIPT.exists():
        return {"ok": False, "error": f"missing {PROXY_SCRIPT.name}"}
    try:
        log = open(PROXY_LOG, "a", encoding="utf-8")
    except OSError:
        log = subprocess.DEVNULL
    try:
        subprocess.Popen(
            [sys.executable, str(PROXY_SCRIPT), "--port", str(port)],
            cwd=str(ROOT),
            stdout=log,
            stderr=log,
            start_new_session=True,  # survives a desk reload
        )
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    for _ in range(40):  # ~4s
        if proxy_listening(f"http://127.0.0.1:{port}"):
            return {"ok": True, "pid": proxy_pid(), "already": False}
        time.sleep(0.1)
    return {"ok": False, "error": "proxy did not start listening"}


def stop_proxy(port: int = 8118) -> dict:
    """Stop the proxy and wait for the port to actually close."""
    pid = proxy_pid()
    if not pid:
        if proxy_listening(f"http://127.0.0.1:{port}"):
            return {"ok": False, "error": "something else is on that port"}
        try:
            ROUTING_FLAG.unlink()
        except OSError:
            pass
        return {"ok": True, "already": True}
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    for _ in range(30):  # ~3s
        if not proxy_listening(f"http://127.0.0.1:{port}"):
            try:
                ROUTING_FLAG.unlink()
            except OSError:
                pass
            return {"ok": True, "already": False}
        time.sleep(0.1)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    for _ in range(10):
        if not proxy_listening(f"http://127.0.0.1:{port}"):
            try:
                ROUTING_FLAG.unlink()
            except OSError:
                pass
            return {"ok": True, "already": False, "killed": True}
        time.sleep(0.1)
    return {"ok": False, "error": "proxy did not stop"}


def exit_ip(proxy: str | None = None, timeout: float = 12.0) -> str:
    """The address the far end sees, measured through `proxy`.

    Measured rather than asked: `piactl get pubip` reported the home address
    for the whole of a live Argentina session, so it cannot be shown in the
    header as "the VPN IP". The request goes through the proxy on purpose --
    that is the only path whose exit is the one runs will use.
    """
    import httpx

    url = DEFAULT_PROXY if proxy is None else proxy
    try:
        with httpx.Client(
            proxies={"all://": url} if url else {}, timeout=timeout
        ) as client:
            return client.get("https://ipinfo.io/ip").text.strip()
    except Exception:
        return ""


def status() -> dict:
    """What the desk is about to use. Read by `/api/proxy` and the CLI."""
    tunnel = current()
    url = proxy_url()
    listening = proxy_listening(DEFAULT_PROXY)
    return {
        "proxy": url,
        "proxy_up": proxy_listening(url) if url else False,
        "routed": bool(url),
        "on": listening,
        "pid": proxy_pid(),
        "tunnel": tunnel.as_dict(),
        "pia_endpoint": endpoint_ip(),
    }


# YouTube stamps the country it thinks you are in into the homepage config.
# That is the number that actually matters here: not "which IP am I", but
# "which market is YouTube ranking for me".
_GL = re.compile(r'"(?:GL|countryCode)"\s*:\s*"([A-Z]{2})"')
CHECK_URL = "https://www.youtube.com/"


def observed_country(proxy: str | None = None, timeout: float = 25.0) -> dict:
    """Ask YouTube which market it is serving, through `proxy` if given.

    Returns `{"country", "error"}`. A run for EG that comes back "BD" means the
    tunnel is not carrying the traffic, whatever piactl says.
    """
    import httpx

    url = DEFAULT_PROXY if proxy is None else proxy
    try:
        client = httpx.Client(
            proxies={"all://": url} if url else {},
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
    except Exception as exc:  # pragma: no cover - httpx config only
        return {"country": "", "error": str(exc)}
    try:
        with client:
            body = client.get(CHECK_URL).text
    except Exception as exc:
        return {"country": "", "error": f"{type(exc).__name__}: {exc}"}
    found = _GL.search(body)
    if not found:
        return {"country": "", "error": "no country marker in the YouTube config"}
    return {"country": found.group(1), "error": ""}
