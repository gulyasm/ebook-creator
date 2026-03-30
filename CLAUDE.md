# ebook-creator

Converts a list of Markdown files and URLs into a Kindle-ready EPUB.

## Scripts

- `ebook_creator.py` — builds an EPUB from a config file
- `raindrop_to_config.py` — generates a config from your Raindrop 'to-read' collection

## Usage

```bash
# Build EPUB from a config file
uv run ebook_creator.py path/to/config.txt

# Generate config from Raindrop, then build EPUB in one step
uv run ebook_creator.py $(uv run raindrop_to_config.py ~/Desktop/my-reading)
```

## Config format

```
title: My Ebook

# Lines starting with http/https are fetched via defuddle.md
https://example.com/article

# Other lines are local Markdown file paths (relative to the config file)
chapters/intro.md
```

- Lines starting with `#` are comments and are ignored
- Empty lines are ignored
- URL sources are fetched as `https://defuddle.md/{url}` and cached in a `tmp/` folder next to the config — `defuddle.md` is an external service; content fetching fails if it is down

## Output

The EPUB is saved to the same directory as the config file, named after the title (e.g. `My Ebook.epub`).

## EPUB structure

1. Cover page (title only)
2. Table of contents (clickable, with ordinal numbers)
3. For each chapter: separator page + content page

## Send to Kindle

Add `--send` flag to build and email the EPUB to your Kindle address:

```bash
uv run ebook_creator.py path/to/config.txt --send
```

Requires a `.env` file with:

```
KINDLE_EMAIL=yourname@kindle.com
SMTP_USER=youremail@gmail.com
SMTP_PASSWORD=xxxx-xxxx-xxxx-xxxx  # Gmail App Password
```

- `SMTP_PASSWORD` must be a Gmail App Password (not your account password)
- `SMTP_USER` must be added to Amazon's approved senders list in your Kindle settings
- See `.env.example` for setup instructions

## Raindrop integration

`raindrop_to_config.py` fetches all bookmarks from the `to-read` collection and writes a config file.

Requires in `.env`:

```
RAINDROP_TOKEN=your-test-token-here  # https://app.raindrop.io/settings/integrations
```

## Dependencies (managed by uv)

- `requests` — HTTP fetching
- `ebooklib` — EPUB creation
- `markdown` — Markdown to HTML conversion
- `python-dotenv` — loads `.env` for Kindle credentials

## Gotchas

- **Images must be embedded**: EPUB readers like Kindle and Apple Books reject EPUBs with remote `<img src="https://...">` URLs. All images must be downloaded and embedded inside the archive. Calibre tolerates remote URLs, so always test with Kindle/Apple Books.
- **Author metadata is required**: The EPUB must include `dc:creator` (author). Kindle and Apple Books reject EPUBs without it; Calibre does not.

## Git / Publishing

- `.claude/` is gitignored — local Claude Code settings only, not for the repo
