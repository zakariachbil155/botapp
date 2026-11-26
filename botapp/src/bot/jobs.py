import html
import logging
from types import SimpleNamespace

from sqlalchemy import select
from telegram import Bot
from telegram.constants import ParseMode

from src.bot import extras
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


def _compose(text: str, settings: Settings) -> str:
    # رابط المصدر صار زراً تحت المنشور، والتوقيع (إن وُجد رابط القناة) في آخره.
    return f"{html.escape(text)}{extras.signature(settings)}"


async def _publish(bot: Bot, settings: Settings, entry: Entry, text: str) -> None:
    """Send with a photo when available; fall back to a text-only post."""
    if entry.image:
        try:
            await bot.send_photo(
                chat_id=settings.channel_id,
                photo=entry.image,
                caption=_compose(_clean(text, CAPTION_TEXT_MAX), settings),
                parse_mode=ParseMode.HTML,
                reply_markup=extras.buttons(entry.link, settings),
            )
            return
        except Exception:
            log.warning("Photo post failed for %s; falling back to text", entry.link)
    await bot.send_message(
        chat_id=settings.channel_id,
        text=_compose(_clean(text, MESSAGE_TEXT_MAX), settings),
        parse_mode=ParseMode.HTML,
        reply_markup=extras.buttons(entry.link, settings),
    )


async def post_news(bot: Bot, settings: Settings, writer: Writer) -> None:
    """Scheduled job: rewrite fresh news items and publish them to the channel."""
    if not settings.channel_id:
        log.warning("CHANNEL_ID is not set; skipping scheduled posting")
        return
    entries = await fetch_entries(settings.news_feeds)
    quiet = extras.is_quiet_now()
    # العاجل أولاً ثم المغرب والعرب، ثم الباقي بترتيبه الأصلي (الفرز مستقر).
    scored = {id(e): (extras.is_breaking(e), extras.priority(e)) for e in entries}
    entries = sorted(entries, key=lambda e: -scored[id(e)][1])
    posted = 0
    for entry in entries:
        if posted >= settings.max_posts_per_run:
            break
        brk = scored[id(entry)][0]
        if quiet and not brk:
            continue  # ساعات الهدوء: العاجل فقط، والباقي ينتظر الصباح
        if _already_posted(entry.link):
            continue
        # Skip women's football before spending an AI call on it.
        if is_womens(entry):
            log.info("Skipping women's football item: %s", entry.title)
            continue
        try:
            text = await writer.rewrite(entry)
            if not text or is_womens(SimpleNamespace(title=text, summary="", link="")):
                # Not men's football (or the model refused): never publish, never retry.
                log.info("Skipping non-football/women's item: %s", entry.title)
                _mark_posted(entry.link)
                continue
            text = extras.decorate(text, entry, brk)
            await _publish(bot, settings, entry, text)
            _mark_posted(entry.link)
            extras.remember(entry, text, brk)
            posted += 1
        except Exception:
            log.exception("Failed to post %s", entry.link)
