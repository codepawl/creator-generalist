"""Fetch full-quality WAV recordings from BigSoundBank (CC0, recorded with microphones, no attribution needed).

  fetch_bigsoundbank.py "<query>" [--n 8] [--folder <library>/bank/bigsoundbank]

Searches the site, downloads each result's broadcast WAV (not the MP3 preview) and writes a manifest.json entry
per file (licence cc0, author, page), so index.py picks them up. Lossy previews made our sounds cheap: the reel's
old sources were all MP3 or OGG, some cut off at 16 kHz or lower.
"""
import argparse
import html
import json
import re
import sys
import urllib.parse
from pathlib import Path

import requests

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent))
from sound_library import LIBRARY_DIRECTORY  # noqa: E402

SITE = "https://bigsoundbank.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
RESULT = re.compile(r'src="/UPLOAD/mp3/(\d{4,5})\.mp3".{0,600}?aria-label="Listen to this sound : ([^"]+)"', re.S)


def search(query, count):
    page = requests.get(f"{SITE}/search", params={"q": query}, headers=HEADERS, timeout=30)
    page.raise_for_status()
    seen = []
    for number, title in RESULT.findall(page.text):
        if number not in [item[0] for item in seen]:
            seen.append((number, html.unescape(title)))
    return seen[:count]


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("query")
    parser.add_argument("--n", type=int, default=8)
    parser.add_argument("--folder", default=str(LIBRARY_DIRECTORY / "bank" / "bigsoundbank"))
    arguments = parser.parse_args()
    folder = Path(arguments.folder)
    folder.mkdir(parents=True, exist_ok=True)
    manifest_path = folder / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else []
    known = {entry["file"] for entry in manifest}
    for number, title in search(arguments.query, arguments.n):
        name = f"{number}-{slug(title)}.wav"
        target = folder / name
        if name not in known or not target.exists():
            response = requests.get(f"{SITE}/UPLOAD/bwf-en/{number}.wav", headers=HEADERS, timeout=120)
            if response.status_code != 200:
                # Some entries have no WAV upload; skip them instead of losing the rest of the search.
                print(f"skipped {number} {title}: WAV answered {response.status_code}")
                continue
            target.write_bytes(response.content)
        if name not in known:
            manifest.append({"file": name, "title": title, "licence": "CC0-1.0", "author": "Joseph Sardin",
                             "origin": f"{SITE}/search?q={urllib.parse.quote(arguments.query)}#{number}",
                             "tags": slug(arguments.query).split("-") + slug(title).split("-")})
            known.add(name)
        print(f"{target}  {target.stat().st_size / 1e6:.1f} MB  {title}")
    manifest_path.write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
