#!/usr/bin/env python3
"""CONNECT proxy on loopback that leaves through the PIA tunnel.

    python tools/tun-http-proxy.py

Chrome never gets the whole machine, and neither does this desk. PIA stays
split, so nothing on this laptop is tunnelled by default. This process listens
on 127.0.0.1:8118, and for every CONNECT it pins the outbound socket to the
current tunnel interface and source IP before dialling out. Scout points
InnerTube at it (`SCOUT_PROXY`); the shell, git, and the browser stay on the
home IP.

Two things it does that a hand-edited BIND_IP does not:

  * it follows the tunnel. `piactl monitor vpnip` streams the new address when
    you switch region, so a hop from Argentina to Egypt needs no rewrite and
    no restart by PID.
  * it fails closed. With the tunnel down a CONNECT gets 503, not a quiet
    fallback to the home IP -- a scout that leaks the real country is worse
    than a scout that stops, because the wrong-country rows look normal.

Flags:
  --port N        listen port (default 8118)
  --allow HOST    extra allowed host suffix, repeatable
  --allow-any     drop the host allowlist
  --open          serve even with the tunnel down (direct, no pinning)
  --quiet         only log errors
"""
from __future__ import annotations

import argparse
import errno
import os
import select
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from socketserver import ThreadingTCPServer, StreamRequestHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from desk import tunnel as tun  # noqa: E402

# Only these leave through the tunnel. The desk is a YouTube tool; anything
# else arriving here is a mistake (a stray global HTTPS_PROXY, usually) and
# is refused rather than quietly given a foreign exit.
DEFAULT_ALLOW = (
    "youtube.com",
    "youtu.be",
    "ytimg.com",
    "ggpht.com",
    "googlevideo.com",
    "googleapis.com",
    "google.com",
    # Not YouTube, and here for one reason: the header shows which address the
    # far end sees, and that can only be measured through this proxy. piactl's
    # own pubip reported the home address for a whole live session.
    "ipinfo.io",
)

PID_FILE = Path(__file__).resolve().parents[1] / "data" / "tun-proxy.pid"
IDLE_TIMEOUT = 180  # seconds a tunnelled connection may sit silent
BUFFER = 65536


class State:
    """The tunnel as the proxy currently understands it."""

    def __init__(self, *, open_mode: bool, quiet: bool) -> None:
        self.open_mode = open_mode
        self.quiet = quiet
        self.lock = threading.Lock()
        self.tunnel = tun.current()
        self.served = 0
        self.refused = 0

    def log(self, message: str, *, error: bool = False) -> None:
        if self.quiet and not error:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        print(f"{stamp} {message}", file=sys.stderr, flush=True)

    def get(self) -> tun.Tunnel:
        with self.lock:
            return self.tunnel

    def refresh(self, *, reason: str = "") -> tun.Tunnel:
        fresh = tun.current()
        with self.lock:
            before = self.tunnel
            self.tunnel = fresh
        if (before.ip, before.interface) != (fresh.ip, fresh.interface):
            where = f"{fresh.ip} on {fresh.interface}" if fresh.up else "down"
            self.log(f"bind -> {where} [{fresh.region or fresh.state}] {reason}".rstrip())
        return fresh


def watch_tunnel(state: State) -> None:
    """Follow the tunnel address so a region change needs no restart.

    `piactl monitor vpnip` prints the current value immediately and again on
    every change. It is re-spawned if PIA restarts, and a slow poll underneath
    covers the case where piactl is missing entirely.
    """
    while True:
        try:
            proc = subprocess.Popen(
                [tun.PIACTL, "monitor", "vpnip"],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
        except OSError:
            time.sleep(10)
            state.refresh(reason="(poll)")
            continue
        assert proc.stdout is not None
        for line in proc.stdout:
            if not line.strip():
                continue
            # The IP is read back through tunnel.current() rather than trusted
            # from the line, so the interface lookup stays in one place.
            state.refresh(reason="(piactl)")
        proc.wait()
        time.sleep(3)


def host_allowed(host: str, allow: tuple[str, ...]) -> bool:
    if not allow:
        return True
    host = host.lower().rstrip(".")
    return any(host == suffix or host.endswith("." + suffix) for suffix in allow)


class Handler(StreamRequestHandler):
    timeout = 30
    state: State
    allow: tuple[str, ...] = DEFAULT_ALLOW

    def _deny(self, code: int, reason: str) -> None:
        self.state.refused += 1
        body = f"{reason}\n".encode()
        try:
            self.wfile.write(
                f"HTTP/1.1 {code} {reason}\r\n"
                f"Content-Length: {len(body)}\r\n"
                "Proxy-Connection: close\r\n"
                "Connection: close\r\n\r\n".encode()
                + body
            )
        except OSError:
            pass

    def handle(self) -> None:
        try:
            request = self.rfile.readline(65536).decode("latin-1").strip()
        except OSError:
            return
        if not request:
            return
        parts = request.split()
        if len(parts) < 2:
            return self._deny(400, "Bad Request")
        method, target = parts[0].upper(), parts[1]
        # Drain the request headers; CONNECT carries no body.
        while True:
            try:
                line = self.rfile.readline(65536)
            except OSError:
                return
            if not line or line in (b"\r\n", b"\n"):
                break
        if method != "CONNECT":
            # Plain HTTP would travel in the clear and nothing here needs it.
            return self._deny(405, "CONNECT only")

        host, _, port_text = target.rpartition(":")
        if not host:
            return self._deny(400, "Bad Request")
        host = host.strip("[]")
        try:
            port = int(port_text)
        except ValueError:
            return self._deny(400, "Bad Request")

        if not host_allowed(host, self.allow):
            self.state.log(f"refused {host}:{port} (not on the allowlist)", error=True)
            return self._deny(403, "Host not allowed")

        tunnel = self.state.get()
        if not tunnel.up:
            tunnel = self.state.refresh(reason="(on demand)")
        if not tunnel.up and not self.state.open_mode:
            self.state.log(f"refused {host}:{port} (tunnel {tunnel.state})", error=True)
            return self._deny(503, "Tunnel down")

        try:
            upstream = self._dial(host, port, tunnel)
        except OSError as exc:
            self.state.log(f"{host}:{port} failed: {exc}", error=True)
            return self._deny(502, "Bad Gateway")

        try:
            self.wfile.write(b"HTTP/1.1 200 Connection established\r\n\r\n")
        except OSError:
            upstream.close()
            return
        self.state.served += 1
        with upstream:
            self._pump(upstream)

    def _dial(self, host: str, port: int, tunnel: tun.Tunnel) -> socket.socket:
        """Open a socket to host:port pinned to the tunnel.

        Every candidate address is tried, since a tunnel with no IPv6 address
        still resolves AAAA records for YouTube.
        """
        last: OSError = OSError(errno.EHOSTUNREACH, "no address")
        for family, kind, proto, _canon, address in socket.getaddrinfo(
            host, port, 0, socket.SOCK_STREAM
        ):
            if family == socket.AF_INET6 and not tunnel.index:
                continue
            sock = socket.socket(family, kind, proto)
            try:
                sock.settimeout(20)
                if tunnel.up:
                    tun.bind_socket(sock, tunnel)
                sock.connect(address)
                sock.settimeout(None)
                return sock
            except OSError as exc:
                sock.close()
                last = exc
        raise last

    def _pump(self, upstream: socket.socket) -> None:
        """Shuttle bytes both ways until either side hangs up or goes quiet."""
        client = self.connection
        client.settimeout(None)
        sockets = [client, upstream]
        while True:
            try:
                readable, _, errored = select.select(sockets, [], sockets, IDLE_TIMEOUT)
            except (OSError, ValueError):
                return
            if errored or not readable:
                return
            for sock in readable:
                other = upstream if sock is client else client
                try:
                    chunk = sock.recv(BUFFER)
                except OSError:
                    return
                if not chunk:
                    return
                try:
                    other.sendall(chunk)
                except OSError:
                    return


class Proxy(ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def write_pid() -> None:
    try:
        PID_FILE.parent.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(f"{os.getpid()}\n", encoding="utf-8")
    except OSError:
        pass


def clear_pid() -> None:
    try:
        if PID_FILE.exists() and PID_FILE.read_text(encoding="utf-8").strip() == str(os.getpid()):
            PID_FILE.unlink()
    except OSError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8118)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--allow", action="append", default=[])
    parser.add_argument("--allow-any", action="store_true")
    parser.add_argument("--open", action="store_true", help="serve with the tunnel down")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)

    state = State(open_mode=args.open, quiet=args.quiet)
    Handler.state = state
    Handler.allow = () if args.allow_any else DEFAULT_ALLOW + tuple(args.allow)

    threading.Thread(target=watch_tunnel, args=(state,), daemon=True).start()

    tunnel = state.get()
    where = f"{tunnel.ip} on {tunnel.interface}" if tunnel.up else f"down ({tunnel.state})"
    state.log(f"proxy on {args.host}:{args.port} -> tunnel {where} [{tunnel.region}]")
    if tunnel.whole_machine:
        state.log(
            "note: PIA holds the default route, so the whole machine is tunnelled "
            "-- split it if only YouTube should be",
            error=True,
        )
    if not tunnel.up and not args.open:
        state.log("tunnel is down: CONNECT gets 503 until PIA is up", error=True)

    server = Proxy((args.host, args.port), Handler)
    write_pid()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        state.log(f"stopping ({state.served} served, {state.refused} refused)")
    finally:
        server.server_close()
        clear_pid()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
