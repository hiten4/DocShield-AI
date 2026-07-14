"""Run parsers in an isolated subprocess with no network + resource limits.

We serialize the parsed Blocks with pickle over stdout. If the child crashes
(malicious file exploiting the parser), the parent catches it and quarantines
the document.
"""

import base64
import os
import pickle
import resource
import subprocess
import sys

_PARSER_MAP = {
    "application/pdf": "app.ingestion.parsers.pdf:parse_pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "app.ingestion.parsers.docx:parse_docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "app.ingestion.parsers.xlsx:parse_xlsx",
    "text/plain": "app.ingestion.parsers.txt:parse_txt",
}


class SandboxError(Exception):
    pass


def parse_in_sandbox(content_type: str, data: bytes, timeout: float = 60.0):
    ref = _PARSER_MAP.get(content_type)
    if not ref:
        raise SandboxError(f"unsupported content type: {content_type}")

    b64 = base64.b64encode(data).decode()
    child_code = _CHILD_CODE.format(ref=ref)
    try:
        proc = subprocess.run(
            [sys.executable, "-I", "-c", child_code],
            input=b64.encode(),
            timeout=timeout,
            check=False,
            capture_output=True,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "PYTHONHASHSEED": "0"},
        )
    except subprocess.TimeoutExpired as e:
        raise SandboxError("parser timeout — possible zip bomb / infinite loop") from e

    if proc.returncode != 0:
        raise SandboxError(f"parser crashed: {proc.stderr.decode(errors='replace')[:400]}")

    try:
        return pickle.loads(proc.stdout)
    except Exception as e:
        raise SandboxError(f"parser output invalid: {e}") from e


# Child process: sets rlimits, DROPS network, imports parser, decodes stdin, parses, pickles to stdout.
_CHILD_CODE = r"""
import base64, importlib, os, pickle, resource, socket, sys

# `python -I` strips PYTHONPATH and doesn't add cwd to sys.path; put /app back
# so the parser module (app.ingestion.parsers.*) can be imported.
sys.path.insert(0, "/app")

# Cap memory (~2 GB) and CPU (~30 s) to defuse memory-exhaustion / infinite loops.
resource.setrlimit(resource.RLIMIT_AS, (2 * 1024 * 1024 * 1024, 2 * 1024 * 1024 * 1024))
resource.setrlimit(resource.RLIMIT_CPU, (30, 30))

# Neuter network — any AF_INET socket() creation raises PermissionError.
class _NoNet(socket.socket):
    def __init__(self, *a, **k): raise PermissionError("network disabled in sandbox")
socket.socket = _NoNet

mod_name, func_name = "{ref}".split(":")
mod = importlib.import_module(mod_name)
func = getattr(mod, func_name)

data = base64.b64decode(sys.stdin.buffer.read())
blocks = func(data)
sys.stdout.buffer.write(pickle.dumps(blocks))
"""
