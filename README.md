# Python-KontAKTRedact

Applies a caseworker's redactions to a document's PDF and stores the redacted file back in KontAKT's local file store, for the **KontAKT** aktindsigt (FOI request) system.

KontAKT triggers this when a caseworker clicks **"Anvend overstregninger"** in the redaction editor. The redaction is **true** — the text/image under each box is removed from the PDF, not just covered.

## What it does

For one document:

1. Fetches the saved redaction boxes from KontAKT.
2. Downloads the PDF from KontAKT's local file store (`GET .../content`).
3. Applies **true redaction** with PyMuPDF — each box deletes the underlying text/image and is painted solid black.
4. Stores the redacted PDF back (`POST .../store`), **replacing the original in place** — the store is id-addressed, so it keeps the document's name (the un-redacted source still lives in GO/Nova).
5. Reports back to KontAKT with the new file hash + size; the document is marked `redacted`.

The boxes are placed by a human in the editor (from the OCR screening suggestions and/or drawn manually) — this robot does not detect anything itself.

## Input (one document)

| Field | Meaning |
|-------|---------|
| `kontakt_case_id` | KontAKT case id |
| `doc_id` | KontAKT document id |

The redaction rectangles are fetched from KontAKT (the rectangle set can be large, so it isn't put in the queue payload).

## Output

The redacted PDF replaces the original in the file store, plus a callback to KontAKT:

```json
{"ok": true, "applied": 8, "sha256": "…", "file_size_bytes": 12345}
```

The new `sha256` lets KontAKT bust its PDF cache so the editor and "Åbn" show the redacted version. On failure it reports `{"ok": false, "note": "…"}` and the document is marked `error` so the caseworker can retry.

## Required configuration

- Credential `KontAKTAPI` — username = base URL, password = API key

## Dependencies

[PyMuPDF](https://pymupdf.readthedocs.io/) for the true redaction. Files are read from and written back to KontAKT over its HTTP API (`/content`, `/store`).
