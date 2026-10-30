"""Match the user's LinkedIn connections to tracked companies and their funds.

Contacts are personal data: this script never writes into the repository. It reads the connections file
written by the acquisition dashboard's linkedin_sync.py and writes one JSON document per matched contact
into an output directory outside the repo; Claude then loads them into the page database (collection
`contacts`), never overwriting existing documents.

Matching uses the CURRENT company of each connection only (LinkedIn export), so former employees are missed.

Usage:
    python3 scripts/match_contacts.py CONNECTIONS_JSON OUT_DIR
"""
import datetime as dt
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from build import norm  # noqa: E402


def same_org(a: str, b: str) -> bool:
    """Equal normalised names, or one is the other plus extra words ('eurazeo' / 'eurazeo pme')."""
    if not a or not b or min(len(a), len(b)) < 4:
        return False
    return a == b or a.startswith(b + " ") or b.startswith(a + " ")


def targets(data: dict) -> list[dict]:
    out = []
    for c in data["companies"]:
        out.append({"type": "societe", "id": c["id"], "nom": c["company"], "key": norm(c["company"])})
        for f in c.get("funds", []):
            out.append({"type": "fonds", "id": c["id"], "nom": f["name"], "key": norm(f["name"])})
    return out


def match(connections: list[dict], data: dict) -> list[dict]:
    tg, now, docs = targets(data), dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), []
    for p in connections:
        key = norm(p.get("entreprise") or "")
        links = {(t["type"], t["id"], t["nom"]) for t in tg if same_org(key, t["key"])}
        if links:
            docs.append({"id": p["id"], "prenom": p.get("prenom", ""), "nom": p.get("nom", ""), "poste": p.get("poste", ""),
                         "entreprise": p.get("entreprise", ""), "linkedin": p.get("linkedin", ""),
                         "liens": [{"type": t, "societe": i, "nom": n} for t, i, n in sorted(links)],
                         "source": "API LinkedIn (portabilité), poste actuel", "notes": "", "created_at": now, "updated_at": now})
    return docs


def main() -> None:
    connections = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    data = json.loads((ROOT / "site" / "data.json").read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    out.mkdir(parents=True, exist_ok=True)
    docs = match(connections, data)
    for d in docs:
        (out / f"{d['id']}.json").write_text(json.dumps({k: v for k, v in d.items() if k != "id"}, ensure_ascii=False), encoding="utf-8")
    print(f"{len(docs)} relations rapprochées sur {len(connections)} -> {out}")
    for d in docs:
        print(f"  {d['prenom']} {d['nom']} · {d['poste']} · {d['entreprise']} -> {', '.join(l['nom'] for l in d['liens'])}")


if __name__ == "__main__":
    main()
