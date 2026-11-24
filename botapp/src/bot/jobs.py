import html
import logging

from sqlalchemy import select
from telegram import Bot
from telegram.constants import ParseMode

from src.bot.config import Settings
from src.bot.feeds import Entry, fetch_entries
from src.bot.filters import is_womens
from src.bot.models import PostedItem
from src.bot.writer import Writer
from src.db.session import SessionLocal

log = logging.getLogger(__name__)

# Telegram limits: photo caption 1024 chars, plain message 4096 chars.
CAPTION_TEXT_MAX = 900
MESSAGE_TEXT_MAX = 3800


def _already_posted(link: str) -> bool:
    with SessionLocal() as s:
        return s.scalar(select(PostedItem.id).where(PostedItem.link == link)) is not None


def _mark_posted(link: str) -> None:
    with SessionLocal() as s:
        s.add(PostedItem(link=link))
        s.commit()


def _clean(text: str, limit: int) -> str:
    # Remove stray Markdown bold markers the model sometimes leaves behind.
    text = text.replace("**", "").strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def _compose(text: str, link: str) -> str:
    return f'{html.escape(text)}\n\n<a href="{html.escape(link)}">المصدر</a>'


async def _publish(bot: Bot, settings: Settings, entry: Entry, text: str) -> None:
    """Send with a photo when available; fall back to a text-only post."""
    if entry.image:
        try:
            await bot.send_photo(
                chat_id=settings.channel_id,
                photo=entry.image,
                caption=_compose(_clean(text, CAPTION_TEXT_MAX), entry.link),
                parse_mode=ParseMode.HTML,
            )
            return
        except Exception:
            log.warning("Photo post failed for %s; falling back to text", entry.link)
    await bot.send_message(
        chat_id=settings.channel_id,
        text=_compose(_clean(text, MESSAGE_TEXT_MAX), entry.link),
        parse_mode=ParseMode.HTML,
    )


async def post_news(bot: Bot, settings: Settings, writer: Writer) -> dict:
    """Scheduled job: rewrite fresh news items and publish them to the channel.

    Returns a stats dict (ignored by the scheduler, shown by the /post command).
    """
    stats = {
        "fetched": 0,
        "duplicates": 0,
        "womens": 0,
        "failed": 0,
        "posted": 0,
        "max_per_run": settings.max_posts_per_run,
        "last_error": "",
    }
    if not settings.channel_id:
        log.warning("CHANNEL_ID is not set; skipping scheduled posting")
        stats["last_error"] = "CHANNEL_ID is not set"
        return stats
    entries = await fetch_entries(settings.news_feeds)
    stats["fetched"] = len(entries)
    for entry in entries:
        if stats["posted"] >= settings.max_posts_per_run:
            break
        if _already_posted(entry.link):
            stats["duplicates"] += 1
            continue
        # Skip women's football before spending an AI call on it.
        if is_womens(entry):
            stats["womens"] += 1
            log.info("Skipping women's football item: %s", entry.title)
            continue
        try:
            text = await writer.rewrite(entry)
            await _publish(bot, settings, entry, text)
            _mark_posted(entry.link)
            stats["posted"] += 1
        except Exception as e:
            stats["failed"] += 1
            stats["last_error"] = repr(e)[:300]
            log.exception("Failed to post %s", entry.link)
    log.info("post_news finished: %s", stats)
    return stats
