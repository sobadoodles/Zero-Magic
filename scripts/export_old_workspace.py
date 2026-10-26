"""Run against the OLD running app BEFORE stopping/replacing it. No API keys."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--url", default="http://127.0.0.1:8000")
parser.add_argument("--output", default="workspace-export.json")
args = parser.parse_args()
path = Path(args.output)
if path.exists():
    raise SystemExit("Output already exists; choose --output with a different filename.")


def get(route):
    with urlopen(args.url.rstrip("/")+route, timeout=20) as response:
        return json.load(response)


cards = get("/api/v1/cards")
people = get("/api/v1/people")
comments = []
for card in cards:
    comments.extend(get(f"/api/v1/cards/{card['id']}/comments"))
with path.open("x", encoding="utf-8") as handle:
    json.dump({"format":"zero-magic-export-v1", "exported_at":datetime.now(timezone.utc).isoformat(),
               "cards":cards,"people":people,"comments":comments},handle,indent=2,ensure_ascii=False)
print(f"Exported {len(cards)} cards, {len(people)} people, {len(comments)} comments to {path}.")
print("Keep this private. Verify the file before stopping your old server.")
