"""
ebook_creator.py - Convert Markdown files and URLs into a Kindle-ready EPUB.

Usage:
    uv run ebook_creator.py path/to/config.txt
"""

import argparse
import os
import re
import smtplib
import subprocess
import sys
import uuid
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import markdown
import requests
from dotenv import load_dotenv
from ebooklib import epub

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------

CSS_CONTENT = """\
body { font-family: Georgia, serif; line-height: 1.6; margin: 5%; }

.cover { text-align: center; margin-top: 30%; }
.cover h1 { font-size: 2.5em; }

.separator { text-align: center; margin-top: 40%; padding-top: 2em; border-top: 2px solid #333; }
.separator h1 { font-size: 2em; }

ol.toc { list-style: none; padding: 0; }
ol.toc li { margin: 0.5em 0; font-size: 1.1em; }
.num { color: #666; margin-right: 0.5em; }

h1, h2, h3 { line-height: 1.2; margin-top: 1.5em; }
code { font-family: monospace; background: #f4f4f4; padding: 0.2em 0.4em; }
pre code { display: block; padding: 1em; overflow-x: auto; }
blockquote { border-left: 3px solid #ccc; margin-left: 0; padding-left: 1em; color: #555; }
"""


# ---------------------------------------------------------------------------
# Custom exception
# ---------------------------------------------------------------------------

class EbookError(Exception):
    pass


# ---------------------------------------------------------------------------
# Config parsing
# ---------------------------------------------------------------------------

def parse_config(config_path: Path) -> tuple[str, list[dict]]:
    """Parse the simple config format and return (title, sources)."""
    if not config_path.exists():
        raise EbookError(f"Config file not found: {config_path}")

    text = config_path.read_text(encoding="utf-8")
    title = None
    sources = []

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("title:"):
            title = line[6:].strip()
        elif urlparse(line).scheme in ("http", "https"):
            sources.append({"type": "url", "value": line})
        else:
            sources.append({"type": "path", "value": line})

    if not title:
        raise EbookError("Config must contain a 'title:' line.")
    if not sources:
        raise EbookError("Config contains no sources (URLs or file paths).")

    return title, sources


# ---------------------------------------------------------------------------
# Slug helpers
# ---------------------------------------------------------------------------

def make_slug(source: str, existing: set) -> str:
    """Create a unique filesystem-safe slug from a source string."""
    segment = Path(urlparse(source).path).name or source
    base = re.sub(r"[^\w]", "_", segment)[:40].strip("_") or "chapter"
    slug = base
    i = 2
    while slug in existing:
        slug = f"{base}_{i}"
        i += 1
    existing.add(slug)
    return slug


# ---------------------------------------------------------------------------
# Markdown utilities
# ---------------------------------------------------------------------------

def strip_frontmatter(text: str) -> tuple[str, str | None]:
    """
    Strip YAML frontmatter and return (body, frontmatter_title).
    frontmatter_title is the value of the 'title:' key inside the block, if any.
    """
    fm_title = None
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            fm_block = text[3:end]
            for fm_line in fm_block.splitlines():
                m = re.match(r"^title:\s*(.+)", fm_line, re.IGNORECASE)
                if m:
                    fm_title = m.group(1).strip().strip('"').strip("'")
                    break
            text = text[end + 4:].lstrip()
    return text, fm_title


def extract_heading(text: str) -> str | None:
    """Extract the first H1 heading from Markdown text."""
    for line in text.splitlines():
        if line.startswith("# ") and not line.startswith("## "):
            return line[2:].strip()
    return None


def to_html(md_text: str) -> str:
    """Convert Markdown to an XHTML body fragment."""
    return markdown.markdown(
        md_text,
        extensions=["extra", "sane_lists"],
        output_format="xhtml",
    )


def _build_chapter(raw_md: str, slug: str, fallback: str) -> dict:
    """Convert raw Markdown into a chapter dict."""
    body, fm_title = strip_frontmatter(raw_md)
    heading = extract_heading(body) or fm_title or fallback
    html = to_html(body)
    return {"slug": slug, "heading": heading, "html": html, "images": []}


# ---------------------------------------------------------------------------
# Image embedding
# ---------------------------------------------------------------------------

_IMG_EXTENSIONS = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}


def _guess_media_type(content_type: str, url: str) -> tuple[str, str]:
    """Return (media_type, extension) from Content-Type header or URL."""
    ct = content_type.split(";")[0].strip().lower()
    if ct in _IMG_EXTENSIONS:
        return ct, _IMG_EXTENSIONS[ct]
    # Fallback: guess from URL extension
    ext = Path(urlparse(url).path).suffix.lower()
    for mt, e in _IMG_EXTENSIONS.items():
        if ext == e:
            return mt, e
    return "image/png", ".png"


def _unwrap_image_proxy(url: str) -> str:
    """Unwrap Next.js /_next/image proxy URLs to their underlying source URL."""
    parsed = urlparse(url)
    if "/_next/image" in parsed.path:
        inner = parse_qs(parsed.query).get("url", [None])[0]
        if inner:
            return inner
    return url


def embed_images(chapters: list[dict]) -> list[epub.EpubImage]:
    """Download remote images, rewrite HTML src attributes, return EpubImage items."""
    all_images: list[epub.EpubImage] = []
    img_counter = 0

    for ch in chapters:
        html = ch["html"]
        img_tags = re.findall(r'<img\s[^>]*>', html)
        for tag in img_tags:
            src_match = re.search(r'src="([^"]+)"', tag)
            if not src_match:
                continue
            src = src_match.group(1)
            if not src.startswith(("http://", "https://")):
                continue

            download_url = _unwrap_image_proxy(src)

            try:
                resp = requests.get(download_url, timeout=15)
                if resp.status_code != 200 or len(resp.content) == 0:
                    raise ValueError(f"HTTP {resp.status_code}")
            except Exception as exc:
                print(f"  WARNING: Could not download image {src[:80]}: {exc}", file=sys.stderr)
                html = html.replace(tag, "")
                continue

            media_type, ext = _guess_media_type(
                resp.headers.get("content-type", ""), download_url,
            )
            img_counter += 1
            file_name = f"images/img_{img_counter:04d}{ext}"

            img_item = epub.EpubImage()
            img_item.file_name = file_name
            img_item.media_type = media_type
            img_item.content = resp.content
            all_images.append(img_item)

            new_tag = tag.replace(f'src="{src}"', f'src="{file_name}"')
            html = html.replace(tag, new_tag)

        ch["html"] = html

    return all_images


# ---------------------------------------------------------------------------
# Source fetching
# ---------------------------------------------------------------------------

def _fetch_with_defuddle_cli(url: str) -> str | None:
    """Try fetching via local defuddle CLI. Returns markdown or None."""
    try:
        result = subprocess.run(
            ["npx", "defuddle", "parse", url, "--markdown"],
            capture_output=True, text=True, timeout=60,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout if result.stdout.strip() else None


def _fetch_with_defuddle_service(url: str) -> str | None:
    """Fallback: fetch via defuddle.md web service."""
    try:
        response = requests.get(f"https://defuddle.md/{url}", timeout=30)
        if response.status_code == 200 and response.text.strip():
            return response.text
    except requests.exceptions.RequestException:
        pass
    return None


def fetch_url(url: str, tmp_dir: Path, slug: str) -> dict | None:
    """Fetch a URL via defuddle (local CLI, then web service fallback)."""
    print(f"  Fetching: {url}")

    raw_md = _fetch_with_defuddle_cli(url)
    if raw_md is None:
        print(f"    Local defuddle failed, trying defuddle.md service...", file=sys.stderr)
        raw_md = _fetch_with_defuddle_service(url)

    if not raw_md or not raw_md.strip():
        print(f"  WARNING: {url} could not be fetched", file=sys.stderr)
        return None

    # Save to tmp for debugging
    (tmp_dir / f"{slug}.md").write_text(raw_md, encoding="utf-8")

    return _build_chapter(raw_md, slug, urlparse(url).netloc)


def read_local(path_str: str, config_dir: Path, slug: str) -> dict | None:
    """Read a local Markdown file and return a chapter dict, or None on error."""
    path = Path(path_str)
    if not path.is_absolute():
        path = config_dir / path

    if not path.exists():
        print(f"  WARNING: File not found: {path}", file=sys.stderr)
        return None

    print(f"  Reading: {path}")
    raw_md = path.read_text(encoding="utf-8")
    return _build_chapter(raw_md, slug, path.stem)


def fetch_sources(sources: list[dict], tmp_dir: Path, config_dir: Path) -> list[dict]:
    """Fetch all sources and return a list of chapter dicts."""
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Pre-compute slugs sequentially (make_slug mutates a shared set)
    existing_slugs: set = set()
    items = [(source, make_slug(source["value"], existing_slugs)) for source in sources]

    chapters: list[dict | None] = []
    for source, slug in items:
        if source["type"] == "url":
            chapters.append(fetch_url(source["value"], tmp_dir, slug))
        else:
            chapters.append(read_local(source["value"], config_dir, slug))

    return [ch for ch in chapters if ch]


# ---------------------------------------------------------------------------
# EPUB helpers
# ---------------------------------------------------------------------------

def wrap_html(title: str, body: str) -> str:
    """Wrap a body fragment in a proper HTML document."""
    return (
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" lang="en">\n'
        f'<head><meta charset="utf-8"/><title>{title}</title></head>\n'
        f'<body>{body}</body>\n'
        '</html>'
    )


def make_epub_page(file_name: str, title: str, body: str, css: epub.EpubItem) -> epub.EpubHtml:
    """Create an EpubHtml item with the stylesheet linked."""
    page = epub.EpubHtml(title=title, file_name=file_name, lang="en")
    page.content = wrap_html(title, body)
    page.add_item(css)
    return page


# ---------------------------------------------------------------------------
# EPUB assembly
# ---------------------------------------------------------------------------

def build_epub(title: str, chapters: list[dict], output_path: Path) -> None:
    """Assemble and write the EPUB file."""
    print(f"Downloading and embedding images...")
    image_items = embed_images(chapters)

    book = epub.EpubBook()
    book.set_identifier(str(uuid.uuid4()))
    book.set_title(title)
    book.set_language("en")
    book.add_author("ebook-creator")

    for img in image_items:
        book.add_item(img)
    print(f"  Embedded {len(image_items)} image(s)")

    # Stylesheet
    css = epub.EpubItem(
        uid="style",
        file_name="style/main.css",
        media_type="text/css",
        content=CSS_CONTENT,
    )
    book.add_item(css)

    # Cover page
    cover_page = make_epub_page(
        "cover.xhtml",
        title,
        f'<div class="cover"><h1>{title}</h1></div>',
        css,
    )
    book.add_item(cover_page)

    # TOC page
    toc_items = "".join(
        f'<li><span class="num">{i}.</span> '
        f'<a href="sep_{ch["slug"]}.xhtml">{ch["heading"]}</a></li>\n'
        for i, ch in enumerate(chapters, 1)
    )
    toc_page = make_epub_page(
        "toc.xhtml",
        "Contents",
        f"<h2>Contents</h2>\n<ol class=\"toc\">\n{toc_items}</ol>",
        css,
    )
    book.add_item(toc_page)

    # Chapter pages
    sep_pages = []
    content_pages = []
    for ch in chapters:
        sep_filename = f"sep_{ch['slug']}.xhtml"
        content_filename = f"chapter_{ch['slug']}.xhtml"
        sep = make_epub_page(
            sep_filename,
            ch["heading"],
            f'<div class="separator"><h1>{ch["heading"]}</h1></div>',
            css,
        )
        content = make_epub_page(
            content_filename,
            ch["heading"],
            ch["html"],
            css,
        )
        book.add_item(sep)
        book.add_item(content)
        sep_pages.append(sep)
        content_pages.append(content)

    # NCX and Nav (required for compatibility)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())

    # TOC structure
    book.toc = [
        epub.Link(f"sep_{ch['slug']}.xhtml", ch["heading"], ch["slug"])
        for ch in chapters
    ]

    # Spine
    spine = [cover_page, "nav", toc_page]
    for sep, content in zip(sep_pages, content_pages):
        spine.append(sep)
        spine.append(content)
    book.spine = spine

    epub.write_epub(str(output_path), book, {})


# ---------------------------------------------------------------------------
# Send to Kindle
# ---------------------------------------------------------------------------

def send_to_kindle(epub_path: Path, kindle_email: str) -> None:
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    if not smtp_user or not smtp_password:
        raise EbookError("SMTP_USER and SMTP_PASSWORD must be set in .env")

    msg = EmailMessage()
    msg["From"] = smtp_user
    msg["To"] = kindle_email
    msg["Subject"] = epub_path.stem
    msg.set_content("Sent via ebook-creator.")

    msg.add_attachment(
        epub_path.read_bytes(),
        maintype="application",
        subtype="epub+zip",
        filename=epub_path.name,
    )

    print(f"  Sending to {kindle_email}...")
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
            smtp.login(smtp_user, smtp_password)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError) as exc:
        raise EbookError(f"Failed to send email: {exc}") from exc


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Convert Markdown files and URLs to EPUB.")
    parser.add_argument("config", help="Path to the config file")
    parser.add_argument("--send", action="store_true",
                        help="Send the EPUB to Kindle after building")
    args = parser.parse_args()

    try:
        config_path = Path(args.config).resolve()
        title, sources = parse_config(config_path)
        config_dir = config_path.parent
        tmp_dir = config_dir / "tmp"

        print(f'Building "{title}" from {len(sources)} source(s)...')
        chapters = fetch_sources(sources, tmp_dir, config_dir)

        if not chapters:
            raise EbookError("No chapters could be loaded. Aborting.")

        failed = len(sources) - len(chapters)
        if failed:
            raise EbookError(
                f"{failed} of {len(sources)} source(s) failed to load. "
                f"Only {len(chapters)} chapter(s) were built. Aborting to avoid an incomplete ebook."
            )

        safe_title = re.sub(r"[^\w\s-]", "", title).strip()
        output_path = config_dir / f"{safe_title}.epub"

        print(f"Assembling EPUB ({len(chapters)} chapter(s))...")
        build_epub(title, chapters, output_path)
        print(f"Done: {output_path}")

        if args.send:
            kindle_email = os.environ.get("KINDLE_EMAIL")
            if not kindle_email:
                raise EbookError("KINDLE_EMAIL is not set in .env")
            send_to_kindle(output_path, kindle_email)
            print(f"Sent to Kindle: {kindle_email}")

    except EbookError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
