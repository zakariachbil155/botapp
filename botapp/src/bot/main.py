import html
import logging
from types import SimpleNamespace
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

from src.bot import extras, fixtures, football, summary
from src.bot.config import Settings, load_settings
from src.bot.feeds import INJURY_WORDS, TRANSFER_WORDS, fetch_entries
from src.bot.filters import is_womens
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
        entries = [e for e in await fetch_entries(urls, words) if not is_womens(e)][:6]
        sent = 0
        for entry in entries:
            if sent >= 3:
                break
            text = await writer.rewrite(entry)
            if not text:  # رفضه النموذج (SKIP: ليس كرة رجال)، فنتجاوزه
                continue
            text = extras.decorate(text, entry, extras.is_breaking(entry))
            if update.message:
                await update.message.reply_text(
                    html.escape(text) + extras.signature(s),
                    parse_mode=ParseMode.HTML,
                    reply_markup=extras.buttons(entry.link, s),
                    disable_web_page_preview=True,
                )
            sent += 1
        if not sent:
            await _reply(update, "لا توجد أخبار مطابقة الآن.")
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
        await _reply(update, "لم تنتهِ أي مباراة مهمة بعد. جرّب /todayresults_demo لمعاينة الشكل.")
        return
    for text in messages:
        await _reply(update, text)


async def test_cmd(update: Update, ctx: Ctx) -> None:
    """معاينة خاصة بك فقط (لا شيء يُنشر في القناة): /test summary|scorers|poll|news."""
    what = (ctx.args[0].lower() if getattr(ctx, "args", None) else "")
    settings, now = _settings(ctx), datetime.now(fixtures.TZ)
    chat_id = update.effective_chat.id
    if what in ("summary", "ملخص"):
        news = extras.top_news(5)
        try:
            matches = await fixtures.fetch_matches(now, settings.football_token)
        except Exception:
            matches = []
        res = fixtures.top_results_lines(matches, now, await fixtures.fetch_extra(now), 5)
        if news or res:
            await _reply(update, summary.build_digest(news, res, now))
        else:
            await _reply(update, "⚠️ معاينة ببيانات وهمية (لا محتوى حقيقي اليوم بعد):\n\n" + summary.demo_digest(now))
    elif what in ("scorers", "هدافون"):
        text = summary.build_scorers_message(await summary.collect_scorers(settings.football_token))
        await _reply(update, text or "تعذّر جلب الهدافين الآن.")
    elif what == "api":
        await _reply(update, html.escape(await fixtures.api_football_check(now)))
    elif what in ("poll", "استطلاع"):
        raw: list[dict] = []
        try:
            fixtures._collect(await fixtures.fetch_matches(now, settings.football_token),
                              await fixtures.fetch_extra(now), now, raw=raw)
        except Exception:
            log.exception("poll preview failed")
        big = [m for m in raw if m["both_big"]]
        m = big[0] if big else {"home": "ريال مدريد", "away": "باريس سان جيرمان", "kick": now}
        await ctx.bot.send_poll(chat_id=chat_id, **fixtures.poll_payload(m))
    elif what in ("news", "خبر"):
        entry = SimpleNamespace(title="Real Madrid star Mbappe ruled out for six weeks", summary="", link="https://t.me/")
        text = "🏥 غياب مبابي ستة أسابيع\n\nأعلن ريال مدريد غياب مبابي بسبب إصابة في عضلة الفخذ.\n\n📌 التفاصيل:\n• المدة: ستة أسابيع\n\n#ريال_مدريد #مبابي"
        text = extras.decorate(text, entry, extras.is_breaking(entry)) + extras.signature(settings)
        await ctx.bot.send_message(chat_id=chat_id, text=text, reply_markup=extras.buttons("https://t.me/", settings),
                                   parse_mode=ParseMode.HTML)
    else:
        await _reply(update, "المعاينات (تصلك أنت فقط):\n/test_summary — ملخص الليلة\n/test_scorers — الهدافون\n"
                             "/test_poll — الاستطلاع\n/test_news — شكل الخبر العاجل والأزرار\n"
                             "/test_api — فحص مفتاح API-Football")


def _alias(handler, arg: str):
    """يحوّل /test_api إلى /test api (نفس المعالج مع وسيط ثابت)."""
    async def run(update: Update, ctx: Ctx) -> None:
        ctx.args = [arg]
        await handler(update, ctx)
    return run


async def start(update: Update, _ctx: Ctx) -> None:
    await _reply(
        update,
        "أهلاً! الأوامر المتاحة:\n"
        "/نتائج [الدوري] — آخر النتائج\n"
        "/ترتيب [الدوري] — جدول الترتيب\n"
        "/إصابات — أخبار الإصابات\n"
        "/انتقالات — أخبار الانتقالات\n"
        "/مباريات — مباريات اليوم\n"
        "/todayresults — نتائج اليوم\n/todayresults_demo — معاينة شكل النتائج\n\n"
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
    "تجربة": test_cmd,
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
    args = [app.bot, settings]

    def cron(func, env: str, default: str, **extra) -> None:
        hour, minute = extras.parse_hm(env, default)
        scheduler.add_job(
            func, "cron", hour=hour, minute=minute, timezone=fixtures.TZ, args=args,
            max_instances=1, coalesce=True, misfire_grace_time=3600, **extra,
        )

    # كل الأوقات بتوقيت المغرب، ويمكن تغيير كل واحد بمتغير بيئة HH:MM
    cron(fixtures.post_todays_fixtures, "FIXTURES_TIME", "10:30")   # مباريات اليوم + تثبيت
    cron(fixtures.post_polls, "POLLS_TIME", "12:30")                # استطلاع «من سيفوز؟»
    cron(fixtures.post_todays_results, "RESULTS_TIME", "22:00")     # نتائج اليوم
    cron(summary.post_nightly_summary, "SUMMARY_TIME", "23:00")     # ملخص الليلة
    cron(fixtures.unpin_fixtures, "UNPIN_TIME", "23:55")            # إلغاء التثبيت
    cron(summary.post_weekly_scorers, "SCORERS_TIME", "12:00", day_of_week="mon")  # الهدافون
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
    app.add_handler(CommandHandler("test", test_cmd))
    # تيليغرام يعدّ الشرطة السفلية جزءًا من اسم الأمر، فندعم /test_api وأخواتها أيضًا
    for name, handler, arg in [
        ("test_summary", test_cmd, "summary"), ("test_scorers", test_cmd, "scorers"),
        ("test_poll", test_cmd, "poll"), ("test_news", test_cmd, "news"), ("test_api", test_cmd, "api"),
        ("todayresults_demo", today_results, "demo"),
    ]:
        app.add_handler(CommandHandler(name, _alias(handler, arg)))
    app.add_handler(MessageHandler(filters.Regex(r"^/[^\sA-Za-z]"), arabic_router))
    app.run_polling()


if __name__ == "__main__":
    main()
