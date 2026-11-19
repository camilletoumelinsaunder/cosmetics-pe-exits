"""Build site/data.json for the cosmetics & luxury PE-exit tracker.

Inputs (never invented, every fact carries its source URL):
- inputs/deals/*.json   research files: {"companies": [...], "exited": [...]} (see CLAUDE.md for the schema)
- inputs/import/*.csv   optional export from a licensed database (PitchBook, Capital IQ, Mergermarket, CFNEWS),
                        one row per company and fund, columns listed in inputs/import/README.md
French companies are enriched with the Recherche d'entreprises API (filed CA and net result, headcount band,
registered officers), with the date of the call. Missing values stay null and show as "à vérifier".

Usage:
    python3 scripts/build.py            # uses the API cache in data/, calls the API for new companies
    python3 scripts/build.py --offline  # cache only
"""
import argparse
import csv
import datetime as dt
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
CFG = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
CACHE = ROOT / "data" / "api_cache.json"
OUT = ROOT / "site" / "data.json"
API_SOURCE = "API Recherche d'entreprises (comptes déposés, RNE)"

IMPORT_COLUMNS = {  # import file column -> field (case-insensitive)
    "company": "company", "société": "company", "country": "country", "pays": "country", "segment": "segment",
    "siren": "siren", "fund": "fund", "fonds": "fund", "role": "role", "entry_date": "entry_date",
    "date d'entrée": "entry_date", "deal_type": "deal_type", "seller": "seller", "ceo": "ceo",
    "revenue": "ca", "ca": "ca", "ebitda": "ebitda", "year": "year", "source": "source", "source_date": "source_date",
}


def slug(value: str) -> str:
    text = unicodedata.normalize("NFD", str(value).lower())
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def norm(value: str) -> str:
    """Company or fund name reduced for matching: no accents, legal forms or punctuation."""
    text = " " + slug(value).replace("-", " ") + " "
    for word in (" sas ", " sa ", " sarl ", " group ", " groupe ", " laboratoires ", " laboratoire ", " france ",
                 " the ", " et ", " cie ", " holding ", " spa ", " srl ", " gmbh ", " ltd ", " bv "):
        text = text.replace(word, " ")
    return " ".join(text.split())


def short_name(value: str) -> str:
    """'Groupe Vabel (Vabel Cosmétique, ...)' -> 'Groupe Vabel'; 'Alkos - filiale de kdc/one' -> 'Alkos'."""
    return re.split(r"\s[(\-–/]|\s-\s", value)[0].strip()


def parse_date(value) -> str | None:
    """Keep 'YYYY' or 'YYYY-MM' as published; anything else is dropped."""
    if not value:
        return None
    m = re.match(r"^(\d{4})(?:-(\d{2}))?", str(value).strip())
    return (m.group(1) + (f"-{m.group(2)}" if m.group(2) else "")) if m else None


# ---------- Inputs ----------

def load_research() -> tuple[list[dict], list[dict]]:
    companies, exited = [], []
    for path in sorted((ROOT / "inputs" / "deals").glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for c in data.get("companies", []):
            c["_file"] = path.name
            companies.append(c)
        exited.extend(data.get("exited", []))
    return companies, exited


def load_import() -> list[dict]:
    """Rows of a licensed-database export, grouped by company. Rows without source are rejected."""
    out, rejected = {}, []
    for path in sorted((ROOT / "inputs" / "import").glob("*.csv")):
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for raw in csv.DictReader(fh):
                row = {IMPORT_COLUMNS[k.strip().lower()]: (v or "").strip() for k, v in raw.items() if k and k.strip().lower() in IMPORT_COLUMNS}
                if not row.get("company") or not row.get("source"):
                    rejected.append(f"{path.name}: {row.get('company') or '?'} (société ou source manquante)")
                    continue
                src = f"{row['source']} (import {path.name})"
                c = out.setdefault(norm(row["company"]), {"company": row["company"], "country": row.get("country") or None,
                                   "segment": row.get("segment") or None, "siren": row.get("siren") or None,
                                   "funds": [], "key_figures": [], "exit_signals": [], "previous_owners": [], "_file": path.name})
                if row.get("fund"):
                    c["funds"].append({"name": row["fund"], "role": row.get("role") or None, "entry_date": row.get("entry_date") or None,
                                       "deal_type": row.get("deal_type") or None, "seller": row.get("seller") or None,
                                       "source_url": None, "source_title": src, "source_date": row.get("source_date") or None})
                for metric in ("ca", "ebitda"):
                    if row.get(metric):
                        c["key_figures"].append({"metric": metric.upper(), "value": row[metric], "year": row.get("year") or None,
                                                 "source_url": None, "source_title": src})
                if row.get("ceo") and not c.get("ceo"):
                    c["ceo"] = {"name": row["ceo"], "title": "CEO", "source_url": None, "source_title": src}
    for r in rejected:
        print("rejeté:", r)
    return list(out.values())


def merge(companies: list[dict]) -> list[dict]:
    """One record per company (same SIREN or same normalised name); funds and facts are unioned."""
    merged = {}
    for c in companies:
        key = ("siren", c["siren"]) if c.get("siren") and re.fullmatch(r"\d{9}", str(c["siren"])) else ("nom", norm(c["company"]))
        if key not in merged and key[0] == "siren":  # same company found earlier without SIREN
            key = next((k for k, v in merged.items() if norm(v["company"]) == norm(c["company"])), key)
        cur = merged.get(key)
        if not cur:
            merged[key] = {**c, "funds": list(c.get("funds") or []), "_files": [c.get("_file")]}
            continue
        cur["_files"].append(c.get("_file"))
        for field in ("country", "segment", "secteur", "maillon", "positionnement", "sub_segment", "hq_city", "website", "siren", "ceo", "notes"):
            cur[field] = cur.get(field) or c.get(field)
        for field in ("key_figures", "exit_signals", "previous_owners"):
            cur[field] = (cur.get(field) or []) + (c.get(field) or [])
        known = {norm(f["name"]) for f in cur["funds"]}
        cur["funds"] += [f for f in c.get("funds") or [] if norm(f["name"]) not in known]
    return list(merged.values())


# ---------- French registry ----------

def api_search(params: dict) -> dict:
    cfg = CFG["api"]
    for attempt in range(1, cfg["max_retries"] + 1):
        try:
            r = requests.get(f"{cfg['recherche_entreprises_base']}/search", params=params, timeout=cfg["timeout_s"])
            if r.status_code == 200:
                time.sleep(cfg["min_interval_s"])
                return r.json()
            if r.status_code not in {429, 500, 502, 503, 504}:
                raise RuntimeError(f"HTTP {r.status_code}")
        except requests.RequestException:
            pass
        time.sleep(min(2 ** attempt, 30))
    raise RuntimeError("Recherche d'entreprises: échec après plusieurs tentatives")


def registry_lookup(c: dict, cache: dict, offline: bool) -> dict | None:
    """Registry record for a French company: by SIREN, else by exact normalised name within cosmetics NAF codes."""
    siren = str(c.get("siren") or "")
    key = f"siren:{siren}" if re.fullmatch(r"\d{9}", siren) else f"nom:{norm(short_name(c['company']))}"
    if key not in cache:
        if offline:
            return None
        try:
            body = api_search({"q": siren if key.startswith("siren") else short_name(c["company"]), "per_page": 10, "page": 1})
        except RuntimeError as exc:
            print("  API:", c["company"], exc)
            return None
        cache[key] = {"fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), "results": body.get("results", [])}
    entry = cache[key]
    results = entry["results"]
    if key.startswith("siren"):
        rec, method = next((r for r in results if r.get("siren") == siren), None), "SIREN publié dans la source"
    else:
        target = norm(short_name(c["company"]))
        rec = next((r for r in results if r.get("activite_principale") in CFG["naf_cosmetics"] and r.get("etat_administratif") == "A"
                    and target in {norm(r.get("nom_complet") or ""), norm(r.get("nom_raison_sociale") or ""), norm(r.get("sigle") or "")}), None)
        method = "Nom identique et code NAF du périmètre cosmétique ou luxe (rapprochement à vérifier)"
    if not rec:
        return None
    return {"rec": rec, "fetched_at": entry["fetched_at"], "method": method}


def registry_fields(found: dict) -> dict:
    rec, fetched = found["rec"], found["fetched_at"]
    finances = []
    for year, values in sorted((rec.get("finances") or {}).items(), reverse=True):
        for metric in ("ca", "resultat_net"):
            if values.get(metric) is not None:
                finances.append({"metric": metric, "year": year, "value": values[metric], "source": API_SOURCE, "fetched_at": fetched})
    officers = [{"nom": " ".join(filter(None, [d.get("prenoms"), d.get("nom")])) or d.get("denomination"),
                 "qualite": d.get("qualite"), "type": d.get("type_dirigeant"),
                 "siren_morale": d.get("siren")} for d in rec.get("dirigeants") or []]
    siege = rec.get("siege") or {}
    return {"siren": rec["siren"], "legal_name": rec.get("nom_complet"), "naf": rec.get("activite_principale"),
            "effectif_code": rec.get("tranche_effectif_salarie"), "effectif_year": rec.get("annee_tranche_effectif_salarie"),
            "commune": siege.get("libelle_commune"), "departement": siege.get("departement"),
            "date_creation": rec.get("date_creation"), "finances": finances[:8], "officers": officers,
            "registry_source": API_SOURCE, "registry_fetched_at": fetched, "registry_match": found["method"]}


# ---------- Classification ----------

def classify(rec: dict, review: dict) -> None:
    """Secteur x maillon x positionnement (labels in config.yaml). Old research files only carry `segment`
    (cosmetics value-chain step), so they map to secteur "Beauté & parfum" and the matching maillon.
    The analyst positionnement in review.json wins over the research file."""
    tax = CFG["taxonomy"]
    rec["secteur"] = rec.get("secteur") or tax["default_secteur"]
    rec["maillon"] = rec.get("maillon") or tax["segment_to_maillon"].get(rec.get("segment") or "")
    rec["positionnement"] = review.get("positionnement") or rec.get("positionnement")
    rec["segment"] = rec["maillon"]  # kept for older page code and exports
    for field, allowed in (("secteur", tax["secteurs"]), ("maillon", tax["maillons"]), ("positionnement", tax["positionnements"])):
        if rec.get(field) not in allowed:
            print(f"  classification: {rec.get('company')} -> {field} inconnu ({rec.get(field)!r})")


# ---------- Carve-outs ----------

CO_STATUTS = ("Processus en cours", "Candidat", "Réalisé")


def load_carveouts() -> list[dict]:
    """inputs/carveouts/*.json: assets large groups sell or may sell (corporate-owned, kept apart from PE holdings).
    A record needs at least one sourced fact; records without one are rejected."""
    tax, out = CFG["taxonomy"], []
    for path in sorted((ROOT / "inputs" / "carveouts").glob("*.json")):
        for x in json.loads(path.read_text(encoding="utf-8")).get("carveouts", []):
            x = dict(x)
            x["id"] = x.get("id") or slug(f"{x.get('parent', '')}-{x.get('asset', '')}")
            x["date"] = parse_date(x.get("date"))
            x["facts"] = [f for f in x.get("facts") or [] if f.get("source_url")]
            x["source_file"] = path.name
            if not x["facts"]:
                print(f"  carve-out rejeté (aucun fait sourcé): {x.get('parent')} / {x.get('asset')}")
                continue
            for field, allowed in (("statut", CO_STATUTS), ("secteur", tax["secteurs"]), ("maillon", tax["maillons"]),
                                   ("positionnement", tax["positionnements"])):
                if x.get(field) not in allowed:
                    print(f"  carve-out: {x['id']} -> {field} inconnu ({x.get(field)!r})")
            out.append(x)
    seen, uniq = set(), []
    for x in out:
        if x["id"] not in seen:
            seen.add(x["id"]); uniq.append(x)
    return uniq


# ---------- Output ----------

def load_review() -> dict:
    """inputs/review.json: analyst review per company id (doubts on ownership, a_completer = missing details,
    status comment, exit thesis, positionnement, overrides)."""
    path = ROOT / "inputs" / "review.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def verification(rec: dict, review: dict) -> tuple[str, list[str]]:
    """'Vérifié' only when ownership and entry date are sourced without doubt; otherwise list what to check."""
    points = list(review.get("doubts") or [])
    ref = next((f for f in rec["funds"] if f["name"] == rec["ref_fund"]), None)
    if not ref:
        points.append("Date d'entrée du fonds non trouvée.")
    else:
        if ref["entry_date"] and "-" not in ref["entry_date"]:
            points.append("Mois d'entrée non publié (année seule).")
        if not ref.get("role"):
            points.append("Rôle du fonds (majoritaire ou minoritaire) non publié.")
    if not any(f.get("source_url") or f.get("source_title") for f in rec["funds"]):
        points.append("Aucune source pour l'actionnariat.")
    return ("À vérifier" if points else "Vérifié"), list(dict.fromkeys(points))


def current_fund(funds: list[dict]) -> dict | None:
    """Reference fund for the holding period: latest majority entry, else latest dated entry."""
    dated = [f for f in funds if parse_date(f.get("entry_date"))]
    major = [f for f in dated if f.get("role") == "majoritaire"]
    pool = major or dated
    return max(pool, key=lambda f: parse_date(f["entry_date"])) if pool else None


def build(offline: bool = False) -> dict:
    research, exited = load_research()
    companies = merge(research + load_import())
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    reviews, out = load_review(), []
    logos_path = ROOT / "site" / "logos" / "index.json"  # written by scripts/fetch_logos.py
    logos = json.loads(logos_path.read_text(encoding="utf-8")) if logos_path.exists() else {}
    for c in companies:
        rec = {k: v for k, v in c.items() if not k.startswith("_")}
        rec["id"] = c.get("id") or slug(c["company"])  # explicit id keeps shared follow-up and contacts attached
        rec["sources_files"] = sorted({f for f in c.get("_files", []) if f})
        for f in rec["funds"]:
            f["entry_date"] = parse_date(f.get("entry_date"))
        ref = current_fund(rec["funds"])
        review = reviews.get(rec["id"], {})
        forced = (review.get("override") or {}).get("ref_fund")
        if forced:
            ref = next((f for f in rec["funds"] if f["name"] == forced), ref)
        rec["ref_fund"], rec["ref_entry"] = (ref["name"], ref["entry_date"]) if ref else (None, None)
        rec["verification"], rec["verification_points"] = verification(rec, review)
        rec["a_completer"] = review.get("a_completer") or []  # missing details that do not question ownership
        if rec["id"] in logos and (ROOT / "site" / "logos" / logos[rec["id"]]["file"]).exists():
            rec["logo"] = "logos/" + logos[rec["id"]]["file"]
        rec["priorite"] = review.get("priorite")
        classify(rec, review)
        if review.get("these"):
            rec["comment"] = {"statut": review.get("statut"), "these": review["these"], "auteur": "Analyse Claude à partir des sources citées",
                              "date": dt.date.today().isoformat()}
        if (c.get("country") or "").upper() == "FR":
            found = registry_lookup(c, cache, offline)
            if found:
                rec.update(registry_fields(found))
        out.append(rec)
    CACHE.parent.mkdir(exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    out.sort(key=lambda r: r["company"].lower())
    for x in exited:
        x["secteur"] = x.get("secteur") or CFG["taxonomy"]["default_secteur"]
        x["maillon"] = x.get("maillon") or CFG["taxonomy"]["segment_to_maillon"].get(x.get("segment") or "")
        x["segment"] = x["maillon"]
    return {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "holding_window_years": CFG["holding_window_years"], "secteurs": CFG["taxonomy"]["secteurs"],
            "maillons": CFG["taxonomy"]["maillons"], "positionnements": CFG["taxonomy"]["positionnements"],
            "companies": out, "exited": exited, "carveouts": load_carveouts()}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    data = build(ap.parse_args().offline)
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    fr = [c for c in data["companies"] if (c.get("country") or "").upper() == "FR"]
    print(f"{len(data['companies'])} sociétés ({len(fr)} FR, {sum(1 for c in fr if c.get('siren') and c.get('finances') is not None)} rapprochées du registre), "
          f"{len(data['exited'])} sorties récentes, {len(data['carveouts'])} carve-outs -> {OUT}")


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
