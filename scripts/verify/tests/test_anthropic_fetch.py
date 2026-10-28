"""The page fetch is pinned: same host over https only, and one overall deadline that covers the body."""
from __future__ import annotations

import threading
import time
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from verify.sources.anthropic_pricing import PageStructureError, fetch_pinned

HTTP = ("http",)


class H(BaseHTTPRequestHandler):
    other_port = 0

    def log_message(self, *a):  # quiet
        pass

    def do_GET(self):
        if self.path == "/ok":
            body = b"hello"
            self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)
        elif self.path == "/same":
            self.send_response(302); self.send_header("Location", "/ok"); self.end_headers()
        elif self.path == "/other-host":
            self.send_response(302); self.send_header("Location", f"http://localhost:{self.server.server_port}/ok"); self.end_headers()
        elif self.path == "/other-port":
            self.send_response(302); self.send_header("Location", f"http://127.0.0.1:{H.other_port}/ok"); self.end_headers()
        elif self.path == "/downgrade":
            self.send_response(302); self.send_header("Location", f"https://127.0.0.1:{self.server.server_port}/ok"); self.end_headers()
        elif self.path == "/drip":
            self.send_response(200); self.send_header("Content-Length", "1000"); self.end_headers()
            try:
                for _ in range(1000):
                    self.wfile.write(b"x"); self.wfile.flush(); time.sleep(0.2)
            except OSError:
                pass
        elif self.path == "/big":
            body = b"x" * 5000
            self.send_response(200); self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404); self.end_headers()


@pytest.fixture(scope="module")
def servers():
    a, b = ThreadingHTTPServer(("127.0.0.1", 0), H), ThreadingHTTPServer(("127.0.0.1", 0), H)
    H.other_port = b.server_port
    for s in (a, b):
        threading.Thread(target=s.serve_forever, daemon=True).start()
    yield a.server_port
    for s in (a, b):
        s.shutdown()


def url(port, path):
    return f"http://127.0.0.1:{port}{path}"


def test_plain_get_and_same_host_redirect_work(servers):
    assert fetch_pinned(url(servers, "/ok"), total=5, schemes=HTTP) == b"hello"
    assert fetch_pinned(url(servers, "/same"), total=5, schemes=HTTP) == b"hello"


@pytest.mark.parametrize("path", ["/other-host", "/other-port", "/downgrade"])
def test_redirects_off_host_or_off_scheme_fail(servers, path):
    with pytest.raises(urllib.error.URLError, match="refused"):
        fetch_pinned(url(servers, path), total=5, schemes=HTTP)


def test_production_default_is_https_only(servers):
    with pytest.raises(urllib.error.URLError, match="not allowed"):
        fetch_pinned(url(servers, "/ok"), total=5)


def test_a_slow_drip_body_cannot_outlast_the_total_deadline(servers):
    t0 = time.monotonic()
    with pytest.raises(TimeoutError):
        fetch_pinned(url(servers, "/drip"), total=1.0, schemes=HTTP)
    assert time.monotonic() - t0 < 3.5


def test_size_cap(servers):
    with pytest.raises(PageStructureError):
        fetch_pinned(url(servers, "/big"), total=5, schemes=HTTP, max_bytes=1000)
