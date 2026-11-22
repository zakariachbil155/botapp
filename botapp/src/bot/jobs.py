import html
import logging

from sqlalchemy import select
from telegram import Bot
from telegram.constants import ParseMode

from src.bot.config import Settings
from src.bot.feeds import fetch_entries
from src.bot.models import PostedItem
from src.bot.writer import Writer
from src.db.session import SessionLocal

log = logging.getLogger(__name__)


def _already_posted(link: str) -> bool:
    with SessionLocal() as s:
        return s.scalar(select(PostedItem.id).where(PostedItem.link == link)) is not None


def _mark_posted(link: str) -> None:
    with SessionLocal() as s:
        s.add(PostedItem(link=link))
        s.commit()


async def post_news(bot: Bot, settings: Settings, writer: Writer) -> None:
    """Scheduled job: rewrite fresh news items and publish them to the channel."""
    if not settings.channel_id:
        log.warning("CHANNEL_ID is not set; skipping scheduled posting")
        return
    entries = await fetch_entries(settings.news_feeds)
    posted = 0
    for entry in entries:
        if posted >= settings.max_posts_per_run:
            break
        if _already_posted(entry.link):
            continue
        try:
            text = await writer.rewrite(entry)
            await bot.send_message(
                chat_id=settings.channel_id,
                text=f'{html.escape(text)}\n\n<a href="{html.escape(entry.link)}">المصدر</a>',
                parse_mode=ParseMode.HTML,
            )
            _mark_posted(entry.link)
            posted += 1
        except Exception:
            log.exception("Failed to post %s", entry.link)
