import html
import logging
import os
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from src.bot import fixtures, football
from src.bot.config import Settings, load_settings
from src.bot.feeds import INJURY_WORDS, TRANSFER_WORDS, fetch_entries
from src.bot.jobs import post_news
from src.bot.models import PostedItem  # noqa: F401  (registers the table)
from src.bot.writer import Writer
from src.db.session import Base, engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("bot")

Ctx = ContextTypes.DEFAULT_TYPE


def _settings(ctx: Ctx) -> Settings:
    settings: Settings = ctx.bot_data["settings"]
    return settings


async def _reply(update: Update, text: str) -> None:
    if update.message:
        await update.message.reply_text(
            text, parse_mode=ParseMode.HTML, disable_web_page_preview=True
        )


async def _league_command(update: Update, ctx: Ctx, kind: str) -> None:
    code = football.normalize_league(ctx.args[0] if ctx.args else None)
    if code is None:
        await _reply(update, "رمز الدوري غير معروف. المتاح: " + ", ".join(football.LEAGUES))
        return
    token = _settings(ctx).football_token
    try:
        text = (
            await football.standings_text(token, code)
            if kind == "table"
            else await football.results_text(token, code)
        )
    except Exception:
        log.exception("football-data request failed")
        await _reply(update, "تعذّر جلب البيانات الآن، حاول بعد قليل.")
        return
    await _reply(update, text)


async def results(update: Update, ctx: Ctx) -> None:
    await _league_command(update, ctx, "results")


async def table(update: Update, ctx: Ctx) -> None:
    await _league_command(update, ctx, "table")


async def _rss_command(update: Update, ctx: Ctx, kind: str) -> None:
    s = _settings(ctx)
    writer: Writer = ctx.bot_data["writer"]
    urls, words = (
        (s.injury_feeds, INJURY_WORDS) if kind == "injuries" else (s.transfer_feeds, TRANSFER_WORDS)
    )
    try:
        entries = (await fetch_entries(urls, words))[:3]
        if not entries:
            await _reply(update, "لا توجد أخبار مطابقة الآن.")
            return
        for entry in entries:
            text = await writer.rewrite(entry)
            await _reply(
                update, f'{html.escape(text)}\n\n<a href="{html.escape(entry.link)}">المصدر</a>'
            )
    except Exception:
        log.exception("RSS command failed")
        await _reply(update, "تعذّر جلب الأخبار الآن، حاول بعد قليل.")


async def injuries(update: Update, ctx: Ctx) -> None:
    await _rss_command(update, ctx, "injuries")


async def transfers(update: Update, ctx: Ctx) -> None:
    await _rss_command(update, ctx, "transfers")


async def today(update: Update, ctx: Ctx) -> None:
    """مباريات اليوم عند الطلب (نفس قائمة منشور 10:30)."""
    now = datetime.now(fixtures.TZ)
    try:
        matches = await fixtures.fetch_matches(now, _settings(ctx).football_token)
    except Exception:
        log.exception("fixtures request failed")
        await _reply(update, "تعذّر جلب المباريات الآن، حاول بعد قليل.")
        return
    extra = await fixtures.fetch_extra(now)
    messages = fixtures.build_messages(matches, now, extra)
    if not messages:
        await _reply(update, "لا توجد مباريات مهمة اليوم.")
        return
    for text in messages:
        await _reply(update, text)


async def today_results(update: Update, ctx: Ctx) -> None:
    """نتائج اليوم عند الطلب. `/todayresults demo` يعرض معاينة ببيانات وهمية."""
    now = datetime.now(fixtures.TZ)
    if getattr(ctx, "args", None) and ctx.args[0].lower() in ("demo", "تجريبي"):
        await _reply(update, "⚠️ معاينة ببيانات وهمية:")
        for text in fixtures.demo_results(now):
            await _reply(update, text)
        return
    try:
        matches = await fixtures.fetch_matches(now, _settings(ctx).football_token)
    except Exception:
        log.exception("results request failed")
        await _reply(update, "تعذّر جلب النتائج الآن، حاول بعد قليل.")
        return
    extra = await fixtures.fetch_extra(now)
    messages = fixtures.build_results_messages(matches, now, extra)
    if not messages:
        await _reply(update, "لم تنتهِ أي مباراة مهمة بعد. جرّب /todayresults demo لمعاينة الشكل.")
        return
    for text in messages:
        await _reply(update, text)


async def start(update: Update, _ctx: Ctx) -> None:
    await _reply(
        update,
        "أهلاً! الأوامر المتاحة:\n"
        "/نتائج [الدوري] — آخر النتائج\n"
        "/ترتيب [الدوري] — جدول الترتيب\n"
        "/إصابات — أخبار الإصابات\n"
        "/انتقالات — أخبار الانتقالات\n"
        "/مباريات — مباريات اليوم\n"
        "/todayresults — نتائج اليوم (demo للمعاينة)\n\n"
        "الدوريات: PL, PD, SA, BL1, FL1",
    )


# Telegram only treats Latin letters as bot commands, so Arabic commands
# like "/نتائج" arrive as plain text and are routed manually.
ARABIC_ROUTES = {
    "نتائج": results,
    "ترتيب": table,
    "إصابات": injuries,
    "اصابات": injuries,
    "انتقالات": transfers,
    "مباريات": today,
    "اليوم": today,
    "نتائج_اليوم": today_results,
}


async def arabic_router(update: Update, ctx: Ctx) -> None:
    if not update.message or not update.message.text:
        return
    parts = update.message.text.split()
    name = parts[0].lstrip("/").split("@")[0]
    handler = ARABIC_ROUTES.get(name)
    if handler:
        ctx.args = parts[1:]
        await handler(update, ctx)


async def _post_init(app: Application) -> None:  # type: ignore[type-arg]
    settings: Settings = app.bot_data["settings"]
    writer: Writer = app.bot_data["writer"]
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        post_news,
        "interval",
        minutes=settings.post_interval_minutes,
        args=[app.bot, settings, writer],
        max_instances=1,
    )
    # منشور مباريات اليوم كل صباح 10:30 بتوقيت المغرب
    scheduler.add_job(
        fixtures.post_todays_fixtures,
        "cron",
        hour=10,
        minute=30,
        timezone=fixtures.TZ,
        args=[app.bot, settings],
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    # نتائج مباريات اليوم كل مساء 22:00 بتوقيت المغرب (RESULTS_TIME=HH:MM لتغييره)
    rh, rm = (int(x) for x in os.getenv("RESULTS_TIME", "22:00").split(":"))
    scheduler.add_job(
        fixtures.post_todays_results,
        "cron",
        hour=rh,
        minute=rm,
        timezone=fixtures.TZ,
        args=[app.bot, settings],
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )
    scheduler.start()
    app.bot_data["scheduler"] = scheduler


def main() -> None:
    settings = load_settings()
    # Create missing tables on startup so deployment doesn't depend on running migrations.
    Base.metadata.create_all(engine)
    app = Application.builder().token(settings.telegram_token).post_init(_post_init).build()
    app.bot_data["settings"] = settings
    app.bot_data["writer"] = Writer(settings.groq_api_key, settings.groq_model)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("results", results))
    app.add_handler(CommandHandler("table", table))
    app.add_handler(CommandHandler("injuries", injuries))
    app.add_handler(CommandHandler("transfers", transfers))
    app.add_handler(CommandHandler("today", today))
    app.add_handler(CommandHandler("todayresults", today_results))
    app.add_handler(MessageHandler(filters.Regex(r"^/[^\sA-Za-z]"), arabic_router))
    app.run_polling()


if __name__ == "__main__":
    main()
