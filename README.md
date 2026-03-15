# ebook-creator

Convert a list of URLs and Markdown files into a Kindle-ready EPUB — and send it straight to your device.

## How it works

You give it a config file with a title and a list of sources. It fetches each URL (via [defuddle.md](https://defuddle.md), which strips pages down to clean readable text), reads any local Markdown files, and packages everything into a well-structured EPUB with a cover page, clickable table of contents, and a separator page before each chapter.

## Requirements

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) (Python package manager)

## Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/gulyasm/ebook-creator.git
cd ebook-creator
uv sync
```

## Usage

Create a config file:

```
title: My Reading List

# URLs are fetched and cleaned automatically
https://example.com/some-article
https://example.com/another-article

# Local Markdown files (relative to the config file)
notes/intro.md
```

Then run:

```bash
uv run ebook_creator.py path/to/config.txt
```

The EPUB is saved to the same directory as the config file, named after the title (e.g. `My Reading List.epub`).

### Config format

| Line | Meaning |
|------|---------|
| `title: My Ebook` | Sets the EPUB title (required) |
| `https://...` | URL to fetch and include as a chapter |
| `path/to/file.md` | Local Markdown file to include |
| `# comment` | Ignored |

## Send to Kindle

Build and send the EPUB to your Kindle in one step:

```bash
uv run ebook_creator.py path/to/config.txt --send
```

### Setup

**1. Create a `.env` file** in the project root:

```
KINDLE_EMAIL=yourname@kindle.com
SMTP_USER=youremail@gmail.com
SMTP_PASSWORD=xxxx-xxxx-xxxx-xxxx
```

See `.env.example` for a template.

**2. Get a Gmail App Password**

Your `SMTP_PASSWORD` must be a Gmail App Password, not your regular account password. To create one:

1. Go to your Google Account > Security
2. Enable 2-Step Verification if not already on
3. Search for "App Passwords" and generate one for "Mail"

**3. Approve your Gmail address on Amazon**

Amazon only delivers documents from approved senders:

1. Go to [Manage Your Content and Devices](https://www.amazon.com/mn/dcw/myx.html)
2. Open Preferences > Personal Document Settings
3. Add your Gmail address to the Approved Personal Document Email List
4. Your Kindle email address is listed on the same page

## Output structure

Every generated EPUB contains:

1. Cover page (title only)
2. Table of contents (clickable, with chapter numbers)
3. For each chapter: a separator title page followed by the content

## Licence

MIT
