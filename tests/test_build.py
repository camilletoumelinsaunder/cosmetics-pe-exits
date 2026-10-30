"""Tests with SYNTHETIC companies and contacts only."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build  # noqa: E402
import match_contacts as mc  # noqa: E402


def test_norm_and_dates():
    assert build.norm("Laboratoires Exemple SAS") == "exemple"
    assert build.parse_date("2021-06-15") == "2021-06" and build.parse_date("2019") == "2019" and build.parse_date("n/a") is None


def test_merge_unions_funds_by_name():
    a = {"company": "Exemple Beauté", "country": "FR", "funds": [{"name": "Fonds A", "entry_date": "2020"}], "_file": "a.json"}
    b = {"company": "EXEMPLE BEAUTE", "siren": "123456789", "funds": [{"name": "Fonds A"}, {"name": "Fonds B"}], "_file": "b.json"}
    out = build.merge([a, b])
    assert len(out) == 1 and [f["name"] for f in out[0]["funds"]] == ["Fonds A", "Fonds B"] and out[0]["siren"] == "123456789"


def test_reference_fund_prefers_latest_majority():
    funds = [{"name": "Minor", "role": "minoritaire", "entry_date": "2023"},
             {"name": "Old", "role": "majoritaire", "entry_date": "2016-03"},
             {"name": "New", "role": "majoritaire", "entry_date": "2021-09"}]
    assert build.current_fund(funds)["name"] == "New"
    assert build.current_fund([{"name": "X", "entry_date": None}]) is None


def test_registry_name_match_requires_cosmetics_naf():
    cache = {"nom:exemple": {"fetched_at": "2026-10-30T00:00:00+00:00", "results": [
        {"siren": "111111111", "nom_complet": "EXEMPLE", "activite_principale": "56.10A", "etat_administratif": "A"},
        {"siren": "222222222", "nom_complet": "LABORATOIRES EXEMPLE", "activite_principale": "20.42Z", "etat_administratif": "A"}]}}
    found = build.registry_lookup({"company": "Exemple"}, cache, offline=True)
    assert found["rec"]["siren"] == "222222222" and "vérifier" in found["method"]


def test_contacts_match_company_and_fund():
    data = {"companies": [{"id": "exemple", "company": "Exemple Beauté", "funds": [{"name": "Eurazeo"}]}]}
    people = [{"id": "li-a", "prenom": "A", "nom": "B", "entreprise": "Eurazeo PME", "poste": "Director"},
              {"id": "li-c", "prenom": "C", "nom": "D", "entreprise": "Exemple Beauté", "poste": "CEO"},
              {"id": "li-e", "prenom": "E", "nom": "F", "entreprise": "Autre", "poste": "CFO"}]
    docs = mc.match(people, data)
    assert [d["id"] for d in docs] == ["li-a", "li-c"]
    assert docs[0]["liens"][0]["type"] == "fonds" and docs[1]["liens"][0]["type"] == "societe"
