"""ClamAV INSTREAM scan.

Talks to clamd on TCP. Returns (clean, signature). If ClamAV is
unreachable in dev, we fail-open with a WARN log rather than block —
production should invert this to fail-closed.
"""

import logging
import socket
import struct

from app.config import settings

log = logging.getLogger(__name__)


def scan_bytes(data: bytes) -> tuple[bool, str | None]:
    try:
        s = socket.create_connection((settings.clamav_host, settings.clamav_port), timeout=15)
    except OSError as e:
        log.warning("clamav unreachable, allowing upload (dev fail-open): %s", e)
        return True, None

    try:
        s.sendall(b"zINSTREAM\0")
        # send in 4-byte-length-prefixed chunks
        chunk = 64 * 1024
        for i in range(0, len(data), chunk):
            piece = data[i : i + chunk]
            s.sendall(struct.pack("!I", len(piece)) + piece)
        s.sendall(struct.pack("!I", 0))

        resp = b""
        while True:
            b = s.recv(4096)
            if not b:
                break
            resp += b
        text = resp.decode(errors="replace").strip("\x00\n ")
        if text.endswith("OK"):
            return True, None
        if "FOUND" in text:
            sig = text.split(":", 1)[-1].strip().replace("FOUND", "").strip()
            return False, sig
        log.warning("clamav unexpected response: %s", text)
        return True, None
    finally:
        s.close()
