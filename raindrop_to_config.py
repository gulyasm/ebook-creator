"""
raindrop_to_config.py - Generate an ebook-creator config from Raindrop 'to-read' collection.

Usage:
    uv run raindrop_to_config.py /path/to/output/folder
"""

import argparse
import os
import sys
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv

RAINDROP_API = "https://api.raindrop.io/rest/v1"
COLLECTION_NAME = "to-read"


def get_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def find_collection_id(token: str, name: str) -> int:
    """Find a collection ID by name (case-insensitive). Checks root and child collections."""
    for endpoint in ("/collections", "/collections/childrens"):
        resp = requests.get(f"{RAINDROP_API}{endpoint}", headers=get_headers(token), timeout=10)
        resp.raise_for_status()
        for col in resp.json().get("items", []):
            if col["title"].lower() == name.lower():
                return col["_id"]
    raise SystemExit(f"Collection '{name}' not found.")


def fetch_urls(token: str, collection_id: int) -> list[str]:
    """Fetch all bookmark URLs from a collection, handling pagination."""
    urls = []
    page = 0
    while True:
        resp = requests.get(
            f"{RAINDROP_API}/raindrops/{collection_id}",
            headers=get_headers(token),
            params={"page": page, "perPage": 50},
            timeout=10,
        )
        resp.raise_for_status()
        items = resp.json().get("items", [])
        if not items:
            break
        urls.extend(item["link"] for item in items)
        page += 1
    return urls


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Create an ebook-creator config from Raindrop.")
    parser.add_argument("output_dir", help="Folder to create the config file in")
    args = parser.parse_args()

    token = os.environ.get("RAINDROP_TOKEN")
    if not token:
        sys.exit("Error: RAINDROP_TOKEN is not set in .env")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    title = f"{today} - Articles to read"

    collection_id = find_collection_id(token, COLLECTION_NAME)
    urls = fetch_urls(token, collection_id)

    if not urls:
        sys.exit(f"No bookmarks found in '{COLLECTION_NAME}'.")

    config_path = output_dir / "config.txt"
    lines = [f"title: {title}", ""] + urls
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(config_path)


if __name__ == "__main__":
    main()
