"""KontAKT redaction robot — applies the caseworker's redaction boxes.

Queue-driven, one queue element per document. For a single document it:

  1. fetches the saved redaction boxes (+ the SharePoint URL) from KontAKT,
  2. downloads the PDF from SharePoint,
  3. applies TRUE redaction (PyMuPDF — removes the text/image under each box),
  4. uploads the redacted PDF back to SharePoint, replacing the original file,
  5. reports back to KontAKT (new file hash + size; the doc is marked 'redacted').

Replacing the file in place keeps the SharePoint copy release-safe; the original
is still in GO/Nova if needed. The new file hash lets KontAKT bust its PDF cache
so the editor and "Åbn" show the redacted version.

Queue payload (set by KontAKT's "Anvend overstregninger" action):
    {"kontakt_case_id": 11, "doc_id": 42}

OO config:
    Constant   KontAKTSharePoint      — SharePoint site URL
    Credential SharePointCert         — username = thumbprint, password = cert path
    Credential SharePointAPI          — username = tenant,     password = client id
    Credential KontAKTAPI             — username = base URL,    password = X-API-Key
"""
from OpenOrchestrator.orchestrator_connection.connection import OrchestratorConnection
from OpenOrchestrator.database.queues import QueueElement
import hashlib
import json
import posixpath
import tempfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests

from robot_framework import reset
from robot_framework import redaction
from oomtm import sharepoint as sp


def process(
    orchestrator_connection: OrchestratorConnection,
    queue_element: QueueElement | None = None,
    client: "reset.Client | None" = None,
) -> None:
    orchestrator_connection.log_trace("Running process.")
    if queue_element is None:
        raise RuntimeError("KontAKTRedact is queue-driven; no queue_element given.")
    if client is None:  # e.g. a manual run outside the queue framework
        client = reset.open_all(orchestrator_connection)

    payload = json.loads(queue_element.data or "{}")
    case_id = int(payload["kontakt_case_id"])
    doc_id = int(payload["doc_id"])
    orchestrator_connection.log_info(f"Redact case={case_id} doc={doc_id}")

    try:
        result = _apply(orchestrator_connection, client, case_id, doc_id)
    except Exception as exc:
        orchestrator_connection.log_info(f"Redact failed: {exc!r}")
        _callback(orchestrator_connection, client, case_id, doc_id, {"ok": False, "note": str(exc)[:500]})
        raise

    _callback(orchestrator_connection, client, case_id, doc_id, result)
    orchestrator_connection.log_info(f"Redact done doc={doc_id}: ok={result.get('ok')}")


def _apply(orchestrator_connection, client, case_id, doc_id):
    info = _fetch_redactions(client, case_id, doc_id)
    rects = info.get("rects") or []
    if not rects:
        return {"ok": False, "note": "Ingen overstregninger at anvende."}

    with tempfile.TemporaryDirectory() as tmpdir:
        work = Path(tmpdir)
        src = work / "original.pdf"
        if not _fetch_content(client, case_id, doc_id, src):
            return {"ok": False, "note": "Dokumentet har ingen fil at redigere."}

        out = work / "redacted.pdf"
        applied = redaction.redact_pdf(str(src), str(out), rects, log=orchestrator_connection.log_info)

        sha = _sha256_hex(out)
        size = out.stat().st_size
        # Store the redacted PDF back (id-addressed → same file, keeps its name).
        _store_file(client, case_id, doc_id, out)

    return {"ok": True, "applied": applied, "sha256": sha, "file_size_bytes": size}


def _fetch_content(client, case_id, doc_id, local_path) -> bool:
    """Stream a document's stored bytes from KontAKT to ``local_path``. False if
    the file isn't in the store (404)."""
    r = requests.get(
        f"{client.kontakt_base}/api/v1/cases/{case_id}/documents/{doc_id}/content",
        headers={"X-API-Key": client.kontakt_key}, timeout=300, stream=True,
    )
    if r.status_code == 404:
        return False
    r.raise_for_status()
    with open(local_path, "wb") as fh:
        for chunk in r.iter_content(1 << 20):
            if chunk:
                fh.write(chunk)
    return True


def _store_file(client, case_id, doc_id, local_path):
    """POST the redacted PDF back into KontAKT's local store (no filename → keeps
    the document's current name)."""
    with open(local_path, "rb") as fh:
        r = requests.post(
            f"{client.kontakt_base}/api/v1/cases/{case_id}/documents/{doc_id}/store",
            params={"kind": "pdf"},
            headers={"X-API-Key": client.kontakt_key, "Content-Type": "application/octet-stream"},
            data=fh, timeout=600,
        )
    r.raise_for_status()


def _sha256_hex(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ----- KontAKT API -----------------------------------------------------------


def _fetch_redactions(client, case_id, doc_id):
    """GET the saved redaction boxes + SharePoint URL for this document."""
    r = requests.get(
        f"{client.kontakt_base}/api/v1/cases/{case_id}/documents/{doc_id}/redactions",
        headers={"X-API-Key": client.kontakt_key},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def _callback(orchestrator_connection, client, case_id: int, doc_id: int, body: dict) -> None:
    try:
        requests.post(
            f"{client.kontakt_base}/api/v1/cases/{case_id}/documents/{doc_id}/redacted",
            headers={"X-API-Key": client.kontakt_key, "Content-Type": "application/json"},
            json=body, timeout=30,
        )
    except Exception as exc:  # pylint: disable=broad-except
        orchestrator_connection.log_info(f"Callback to KontAKT failed: {exc!r}")
