"""
append_to_gdoc.py — Append plain text to an existing Google Doc using ADC.

Usage:
    python V2/scripts/append_to_gdoc.py <doc_id> <text_file>

Requires gcloud ADC with documents scope. Re-run if you get 403:
    gcloud auth application-default login --scopes='https://www.googleapis.com/auth/documents,https://www.googleapis.com/auth/cloud-platform'
"""

from __future__ import annotations

import sys
from pathlib import Path

from google.auth import default as gauth_default
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/documents"]


def append_text(doc_id: str, text: str) -> None:
    creds, _ = gauth_default(scopes=SCOPES)
    docs = build("docs", "v1", credentials=creds)

    doc = docs.documents().get(documentId=doc_id).execute()
    end_index = doc["body"]["content"][-1]["endIndex"]
    insert_index = max(end_index - 1, 1)

    requests = [{
        "insertText": {
            "location": {"index": insert_index},
            "text": "\n" + text,
        }
    }]

    docs.documents().batchUpdate(
        documentId=doc_id,
        body={"requests": requests},
    ).execute()
    print(f"✓ Appended {len(text)} chars to doc {doc_id}")


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    doc_id = sys.argv[1]
    text = Path(sys.argv[2]).read_text(encoding="utf-8")
    append_text(doc_id, text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
