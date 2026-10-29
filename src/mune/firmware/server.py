from __future__ import annotations

import http.server
from functools import partial
from pathlib import Path

from .manifest import MANIFEST_PATH, check_cabs, load_manifest


class _Handler(http.server.SimpleHTTPRequestHandler):
    allowed: set[str] = set()

    def do_GET(self):
        path = self.path.split("?", 1)[0].lstrip("/")
        if path.lower() not in self.allowed:
            self.log_message("refused %s (not part of the firmware set)", self.path)
            self.send_error(404)
            return
        self.path = "/" + path
        super().do_GET()

    def do_HEAD(self):
        self.do_GET()

    def list_directory(self, path):
        self.send_error(404)


def prepare(root: Path, allow_untrusted: bool = False) -> set[str]:
    manifest = root / MANIFEST_PATH
    if not manifest.exists():
        raise FileNotFoundError(f"{manifest} not found")
    allowed = {MANIFEST_PATH.lower()}
    cabs = []
    for upd in load_manifest(manifest):
        cab = root / upd.cab_name
        if cab.exists():
            cabs.append(cab)
            allowed.add(upd.cab_name.lower())
    bad = [c for c in check_cabs(cabs) if not c.trusted]
    if bad and not allow_untrusted:
        names = ", ".join(c.path.name for c in bad)
        raise PermissionError(f"refusing to serve unverified firmware: {names}")
    return allowed


def serve(root: Path, host: str = "127.0.0.1", port: int = 80, allow_untrusted: bool = False) -> None:
    root = root.resolve()
    allowed = prepare(root, allow_untrusted)
    handler = type("Handler", (_Handler,), {"allowed": allowed})
    httpd = http.server.ThreadingHTTPServer((host, port), partial(handler, directory=str(root)))
    print(f"Serving {len(allowed) - 1} verified firmware CAB(s) from {root} on http://{host}:{port}/")
    print("Point resources.zune.net at 127.0.0.1 (scripts/Set-ZuneHosts.ps1 -Local), then")
    print("open the Zune software and check for updates. Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
