import asyncio
from dataclasses import dataclass

import feedparser

INJURY_WORDS = ("injur", "ruled out", "sidelined", "fitness", "doubt", "setback")
TRANSFER_WORDS = ("transfer", "sign", "loan", "bid", "deal", "join", "fee", "contract")


@dataclass(frozen=True)
class Entry:
    title: str
    summary: str
    link: str


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
            entries.append(Entry(title, summary, link))
    return entries
