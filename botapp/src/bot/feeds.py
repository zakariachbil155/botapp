import asyncio
import re
from dataclasses import dataclass

import feedparser

INJURY_WORDS = ("injur", "ruled out", "sidelined", "fitness", "doubt", "setback")
TRANSFER_WORDS = ("transfer", "sign", "loan", "bid", "deal", "join", "fee", "contract")

_IMG_TAG = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)


@dataclass(frozen=True)
class Entry:
    title: str
    summary: str
    link: str
    image: str = ""


def _image_url(e) -> str:  # type: ignore[no-untyped-def]
    """Best-effort image extraction from an RSS entry; returns '' if none."""
    url = ""
    for key in ("media_thumbnail", "media_content"):
        items = e.get(key) or []
        if items and isinstance(items, list):
            url = str(items[0].get("url", "")).strip()
            if url:
                break
    if not url:
        for enc in e.get("enclosures") or []:
            if str(enc.get("type", "")).startswith("image"):
                url = str(enc.get("href") or enc.get("url") or "").strip()
                if url:
                    break
    if not url:
        for link in e.get("links") or []:
            if str(link.get("type", "")).startswith("image"):
                url = str(link.get("href", "")).strip()
                if url:
                    break
    if not url:
        m = _IMG_TAG.search(str(e.get("summary", "")))
        if m:
            url = m.group(1).strip()
    # BBC serves tiny 240px thumbnails by default; ask for a larger version.
    url = url.replace("/standard/240/", "/standard/800/")
    return url if url.startswith("http") else ""


async def fetch_entries(urls: list[str], keywords: tuple[str, ...] | None = None) -> list[Entry]:
    entries: list[Entry] = []
    for url in urls:
        parsed = await asyncio.to_thread(feedparser.parse, url)
        for e in parsed.entries:
            title = str(e.get("title", "")).strip()
            summary = str(e.get("summary", "")).strip()
            link = str(e.get("link", "")).strip()
            if not (title and link):
                continue
            text = f"{title} {summary}".lower()
            if keywords and not any(k in text for k in keywords):
                continue
            entries.append(Entry(title, summary, link, _image_url(e)))
    return entries
