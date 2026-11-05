"""Fetch the member's own LinkedIn connections through the DMA Member Data Portability API.

Self-serve for members located in the EEA / Switzerland: the member creates a developer
app on the default company page, requests "Member Data Portability API (Member)" and
generates a token with scope r_dma_portability_self_serve. The token is read from the
environment variable LINKEDIN_TOKEN (never from the repository or the chat).

Output: data/linkedin_connections.json (data/ is git-ignored), one record per connection
with the same document id the Associés tab computes, so existing contacts are skipped.

Usage:
    python3 scripts/linkedin_sync.py
"""
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from urllib.parse import unquote

import requests

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "linkedin_connections.json"
API = "https://api.linkedin.com/rest/memberSnapshotData"
VERSION = "202312"  # the only version this endpoint accepts

# LinkedIn export field names -> Associés fields (compared case-insensitively).
FIELDS = {"first name": "prenom", "last name": "nom", "url": "linkedin", "email address": "email",
          "company": "entreprise", "position": "poste", "connected on": "connected_on"}


def slug(value: str) -> str:
    """Same rule as the page: lower case, accents removed, other characters to '-'."""
    text = unicodedata.normalize("NFD", str(value).lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9_-]+", "-", text).strip("-")[:150]


def contact_id(linkedin_url: str) -> str | None:
    m = re.search(r"linkedin\.com/in/([^/?#]+)", linkedin_url or "", re.I)
    return "li-" + slug(unquote(m.group(1))) if m else None


def to_contact(raw: dict) -> dict:
    lowered = {k.strip().lower(): (v or "").strip() if isinstance(v, str) else v for k, v in raw.items()}
    return {field: lowered.get(name, "") or "" for name, field in FIELDS.items()}


def fetch_connections(token: str, session=requests) -> list[dict]:
    """All pages of the CONNECTIONS domain; the API ends with a 404 'No data found'."""
    headers = {"Authorization": f"Bearer {token}", "Linkedin-Version": VERSION}
    out, start = [], 0
    while True:
        for attempt in range(1, 6):
            r = session.get(API, params={"q": "criteria", "domain": "CONNECTIONS", "start": start},
                            headers=headers, timeout=60)
            if r.status_code not in {429, 500, 502, 503, 504}:
                break
            time.sleep(min(2 ** attempt, 30))
        if r.status_code == 404 or (r.status_code == 200 and not r.json().get("elements")):
            return out
        if r.status_code == 401:
            raise SystemExit("LinkedIn refuse le jeton (expiré ou invalide) : régénérez-le dans le portail développeur.")
        if r.status_code != 200:
            raise SystemExit(f"LinkedIn API: HTTP {r.status_code} {r.text[:200]}")
        for element in r.json().get("elements", []):
            out.extend(to_contact(item) for item in element.get("snapshotData", []))
        start += 1


def main() -> None:
    token = os.environ.get("LINKEDIN_TOKEN")
    if not token:
        raise SystemExit("LINKEDIN_TOKEN absent : ajoutez-le dans les réglages de l'environnement.")
    contacts, seen = [], set()
    for c in fetch_connections(token):
        cid = contact_id(c["linkedin"])
        if cid and cid not in seen:  # the API can return the same connection on several pages
            seen.add(cid)
            contacts.append({"id": cid, **c})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(contacts, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(contacts)} relations écrites dans {OUT}")


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
