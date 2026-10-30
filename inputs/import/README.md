# Import from a licensed database (PitchBook, Capital IQ, Mergermarket, CFNEWS)

Drop a CSV export here (UTF-8), one row per company and fund. Recognised columns (case-insensitive):
company / société, country / pays, segment, siren, fund / fonds, role, entry_date / date d'entrée,
deal_type, seller, ceo, revenue / ca, ebitda, year, source, source_date.

`source` is mandatory (e.g. "PitchBook, export du 2026-11-04"): rows without it are rejected.
Then run `python3 scripts/build.py` and republish the page.
