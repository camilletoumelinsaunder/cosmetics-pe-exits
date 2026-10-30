# CLAUDE.md — Cosmetics PE-exit tracker (AlixPartners)

Separate project from the acquisition-screening dashboard. Tracks cosmetics companies held by private-equity
funds (France first, then Europe) to spot likely exits. UI in French, code comments in English.

Segments: Marques, Sous-traitants (façonniers / CDMO), Ingrédients et actifs, Packaging.

## Golden rule
- Never invent or estimate a fact. Every company, fund, entry date, CEO, figure and exit signal carries the
  URL (or import file) it comes from. Missing = « à vérifier ».
- The exit window is the only computed element: entry date of the reference fund + the user's holding
  hypothesis (default `config.yaml → holding_window_years`, editable on the page). The page says so.

## Data flow
1. `inputs/deals/*.json` — research files (schema below), compiled from press releases, fund portfolio pages
   and trade press, each fact with source_url.
2. `inputs/import/*.csv` — optional export from a licensed database (see `inputs/import/README.md`).
3. `python3 scripts/build.py` merges them (same SIREN or same normalised name), enriches French companies with
   the Recherche d'entreprises API (filed CA / net result, headcount band, registered officers, with call date;
   API cache in `data/`), and writes `site/data.json`.
4. Republish `site/index.html` with `data.json` to the artifact URL (see below).

Reference fund = latest dated majority entry, else latest dated entry. Name-based registry matches are accepted
only with an identical normalised name and a cosmetics-related NAF code, and are flagged « à vérifier ».

Research JSON schema: {"companies": [{company, country, segment, sub_segment, hq_city, website, siren,
funds: [{name, role, entry_date, deal_type, seller, source_url, source_title, source_date}],
previous_owners: [{name, entry, exit, source_url}], ceo: {name, title, source_url},
key_figures: [{metric, value, year, source_url}], exit_signals: [{fact, date, source_url}], notes}],
"exited": [...]}.

## Contacts (personal data)
- Stored only in the page database: collection `data/users/<viewer id>/pe/contacts` (private to each viewer; ArtifactData collection `data/users/me/pe/contacts`) (`li-<slug>` from LinkedIn, `m-<random>` manual),
  fields prenom, nom, poste, entreprise, linkedin, liens [{type: societe|fonds, societe: <company id>, nom}],
  notes, source. Never in the repo, data.json or the API cache.
- `scripts/match_contacts.py CONNECTIONS_JSON OUT_DIR` matches the user's LinkedIn connections (current
  company only) to tracked companies and their funds; Claude loads the result with ArtifactData, creating
  only missing documents.
- Per-company follow-up: collection `data/users/<viewer id>/pe/suivi/<company id>` {statut, priorite (overrides the analyst priority), dernier_contact, next_steps, prochaine_date, notes, updated_at}.

## Commands
```bash
python3 -m pytest -q tests
python3 scripts/build.py
python3 scripts/match_contacts.py ../acquisition-dashboard/data/linkedin_connections.json /tmp/contacts
```
