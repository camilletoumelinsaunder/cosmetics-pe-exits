"""Fetch company logos from each company's OFFICIAL website (the `website` field of the research files).

Only the company's own site is used: the icon it declares (apple-touch-icon, then the largest <link rel=icon>),
then /apple-touch-icon.png, then the site's favicon via Google's favicon service. Generic placeholder icons are
dropped. Each logo is normalised to a 96x96 PNG in site/logos/<company id>.png and listed with its source URL
and fetch date in site/logos/index.json. Companies without a website or a usable icon get initials on the page.

Usage:
    python3 scripts/fetch_logos.py           # fetch missing logos only
    python3 scripts/fetch_logos.py --force   # refetch all
"""
import argparse
import datetime as dt
import hashlib
import io
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "data.json"
OUT = ROOT / "site" / "logos"
INDEX = OUT / "index.json"
SIZE = 96
UA = {"User-Agent": "Mozilla/5.0 (compatible; pe-tracker-logo-fetch/1.0)"}


class IconLinks(HTMLParser):
    """Collect <link rel=...icon...> tags with their declared size."""

    def __init__(self):
        super().__init__()
        self.icons = []

    def handle_starttag(self, tag, attrs):
        if tag != "link":
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        rel = a.get("rel", "").lower()
        if "icon" not in rel or not a.get("href"):
            return
        sizes = [int(n) for n in re.findall(r"(\d+)x\d+", a.get("sizes", ""))]
        score = (2 if "apple-touch-icon" in rel else 1, max(sizes) if sizes else (180 if "apple" in rel else 32))
        self.icons.append((score, a["href"]))


def get(url: str, **kw) -> requests.Response | None:
    try:
        r = requests.get(url, headers=UA, timeout=15, allow_redirects=True, **kw)
        return r if r.status_code == 200 else None
    except requests.RequestException:
        return None


def to_png(content: bytes) -> bytes | None:
    """Square 96x96 PNG on a transparent background; None if not a usable raster image."""
    try:
        img = Image.open(io.BytesIO(content))
        if getattr(img, "n_frames", 1) > 1 and img.format == "ICO":
            img = max((Image.open(io.BytesIO(content)).ico.getimage(s) for s in img.ico.sizes()), key=lambda i: i.width)
        img = img.convert("RGBA")
    except Exception:
        return None
    if img.width < 16 or img.height < 16:
        return None
    img.thumbnail((SIZE, SIZE), Image.LANCZOS)
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    canvas.paste(img, ((SIZE - img.width) // 2, (SIZE - img.height) // 2), img)
    buf = io.BytesIO()
    canvas.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def candidates(website: str) -> list[str]:
    home = get(website)
    base = home.url if home else website
    urls = []
    if home and "html" in home.headers.get("content-type", ""):
        p = IconLinks()
        try:
            p.feed(home.text[:400_000])
        except Exception:
            pass
        urls += [urljoin(base, href) for _, href in sorted(p.icons, reverse=True)]
    root = f"{urlparse(base).scheme or 'https'}://{urlparse(base).netloc or urlparse(website).netloc}"
    urls += [root + "/apple-touch-icon.png", f"https://www.google.com/s2/favicons?domain={urlparse(root).netloc}&sz=128"]
    return list(dict.fromkeys(u for u in urls if not u.lower().endswith(".svg")))


def placeholder_hashes() -> set[str]:
    """Hash of the generic icon Google returns for a domain without favicon."""
    r = get("https://www.google.com/s2/favicons?domain=no-such-domain-pe-tracker.invalid&sz=128")
    png = to_png(r.content) if r else None
    return {hashlib.sha1(png).hexdigest()} if png else set()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    force = ap.parse_args().force
    companies = json.loads(DATA.read_text(encoding="utf-8"))["companies"]
    OUT.mkdir(parents=True, exist_ok=True)
    index = json.loads(INDEX.read_text(encoding="utf-8")) if INDEX.exists() else {}
    skip = placeholder_hashes()
    done = failed = 0
    for c in companies:
        cid, site = c["id"], c.get("website")
        if not site or (cid in index and not force and (OUT / index[cid]["file"]).exists()):
            continue
        for url in candidates(site):
            r = get(url)
            png = to_png(r.content) if r else None
            if png and hashlib.sha1(png).hexdigest() not in skip:
                (OUT / f"{cid}.png").write_bytes(png)
                index[cid] = {"file": f"{cid}.png", "source_url": url, "website": site,
                              "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}
                done += 1
                break
        else:
            failed += 1
            print("  pas de logo:", cid, site)
    INDEX.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{done} logos récupérés, {failed} sans logo utilisable, {len(index)} au total -> {OUT}")


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
