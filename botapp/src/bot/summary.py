"""ملخص الليلة (أهم 5 أخبار وأبرز النتائج) وهدّافو الدوريات الأسبوعيون."""
import html
import logging
from datetime import datetime

import httpx
from telegram import Bot
from telegram.constants import ParseMode

from src.bot import extras, fixtures
from src.bot.config import Settings

log = logging.getLogger(__name__)

SEP = "┈┈┈┈┈┈┈┈┈┈┈┈┈┈"
SCORERS_URL = "https://api.football-data.org/v4/competitions/{code}/scorers"
SCORER_COMPS = [
    ("PL", "🏴 الدوري الإنجليزي الممتاز"),
    ("PD", "🇪🇸 الدوري الإسباني"),
    ("SA", "🇮🇹 الدوري الإيطالي"),
    ("BL1", "🇩🇪 الدوري الألماني"),
    ("FL1", "🇫🇷 الدوري الفرنسي"),
    ("CL", "🏆 دوري أبطال أوروبا"),
]
MEDALS = ["🥇", "🥈", "🥉", "4.", "5."]


# ------------------------------------------------------------- ملخص الليلة
def build_digest(news: list[dict], results: list[str], day: datetime) -> str:
    """نص ملخص الليلة، أو سلسلة فارغة إن لم يوجد أي محتوى."""
    if not news and not results:
        return ""
    parts = ["😴 <b>ملخص الليلة</b>", f"🗓 {fixtures._day_label(day)}", SEP]
    if news:
        parts.append("📰 <b>أبرز أخبار اليوم</b>")
        for i, n in enumerate(news, 1):
            title = html.escape(n["title"])
            link = html.escape(n["link"], quote=True)
            parts.append(f'<b>{i}.</b> <a href="{link}">{title}</a>' if link else f"<b>{i}.</b> {title}")
        parts.append("")
    if results:
        parts.append("📊 <b>أبرز النتائج</b>")
        parts.extend(results)
        parts.append("")
    parts += [SEP, "🌙 ليلة سعيدة وإلى لقاء الغد", "", "#ملخص_الليلة #كرة_القدم"]
    return "\n".join(parts)


async def post_nightly_summary(bot: Bot, settings: Settings) -> None:
    if not settings.channel_id:
        return
    now = datetime.now(fixtures.TZ)
    try:
        matches = await fixtures.fetch_matches(now, settings.football_token)
    except Exception:
        log.exception("Failed to fetch results for the nightly summary")
        matches = []
    extra = await fixtures.fetch_extra(now)
    results = fixtures.top_results_lines(matches, now, extra, 5)
    text = build_digest(extras.top_news(5), results, now)
    if not text:
        return
    await bot.send_message(
        chat_id=settings.channel_id,
        text=text + extras.signature(settings),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


# ------------------------------------------------------------- الهدافون
def build_scorers_message(data: dict[str, list[dict]]) -> str:
    """data: {رمز المسابقة: قائمة هدافين من football-data}. فارغة إن لم توجد بيانات."""
    blocks: list[str] = []
    best = None
    for code, title in SCORER_COMPS:
        rows = []
        for i, sc in enumerate((data.get(code) or [])[:5]):
            name = (sc.get("player") or {}).get("name") or "؟"
            team = fixtures._team((sc.get("team") or {}).get("name", ""))[0]
            goals = sc.get("goals") or 0
            rows.append(f"{fixtures.RLM}{MEDALS[i]} {html.escape(name)} ({html.escape(team)}) — <b>{goals}</b> ⚽")
            if code != "CL" and (best is None or goals > best[0]):
                best = (goals, name, team, title)
        if rows:
            blocks.append(f"<b>{title}</b>\n" + "\n".join(rows))
    if not blocks:
        return ""
    head = ["🎯 <b>هدّافو الدوريات الكبرى</b>", "الأرقام تراكمية منذ بداية الموسم", SEP]
    if best:
        head += [f"🌟 <b>الهداف الأول بين الدوريات الخمسة:</b> {html.escape(best[1])} ({html.escape(best[2])}) — {best[0]} هدفًا", ""]
    return "\n".join(head) + "\n" + "\n\n".join(blocks) + f"\n\n{SEP}\n#الهدافون #كرة_القدم"


async def collect_scorers(token: str) -> dict[str, list[dict]]:
    """يجلب أفضل الهدافين لكل مسابقة (يتجاوز المسابقة التي تفشل)."""
    data: dict[str, list[dict]] = {}
    if not token:
        return data
    async with httpx.AsyncClient(timeout=20) as client:
        for code, _ in SCORER_COMPS:
            try:
                r = await client.get(
                    SCORERS_URL.format(code=code), params={"limit": 5},
                    headers={"X-Auth-Token": token},
                )
                r.raise_for_status()
                data[code] = r.json().get("scorers", [])
            except Exception as exc:
                log.warning("scorers %s unavailable (%s)", code, exc)
    return data


# بيانات وهمية للمعاينة الخاصة (/test) فقط، لا تُنشر في القناة أبداً
DEMO_NEWS = [
    {"title": "🚨 عاجل ┃ غياب مبابي ستة أسابيع بسبب إصابة في عضلة الفخذ", "link": "https://t.me/"},
    {"title": "⚽ 🇲🇦 حكيمي يسجل هدفين ويقود المغرب للفوز", "link": "https://t.me/"},
    {"title": "🔄 ليفربول يقترب من ضم مهاجم جديد", "link": "https://t.me/"},
]


def demo_digest(day: datetime) -> str:
    results = [
        f"{fixtures.RLM}🔥 ريال مدريد <b>(2)</b> ⚔️ <b>(1)</b> باريس سان جيرمان",
        f"{fixtures.RLM}🔥 🇸🇦 الهلال <b>(3)</b> ⚔️ <b>(1)</b> 🇸🇦 النصر",
    ]
    return build_digest(DEMO_NEWS, results, day)


async def post_weekly_scorers(bot: Bot, settings: Settings) -> None:
    if not settings.channel_id or not settings.football_token:
        return
    data = await collect_scorers(settings.football_token)
    text = build_scorers_message(data)
    if text:
        await bot.send_message(
            chat_id=settings.channel_id,
            text=text + extras.signature(settings),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


def build_weekly(news: list[dict], day: datetime) -> str:
    if not news:
        return ""
    parts = ["🗓 <b>ملخص الأسبوع</b>", f"📅 حتى {fixtures._day_label(day)}", SEP,
             "📰 <b>أهم 5 أخبار هذا الأسبوع</b>"]
    for i, n in enumerate(news, 1):
        title = html.escape(n["title"])
        link = html.escape(n["link"], quote=True)
        parts.append(f'<b>{i}.</b> <a href="{link}">{title}</a>' if link else f"<b>{i}.</b> {title}")
    parts += ["", SEP, "🔔 أسبوع سعيد ونراكم على خير", "", "#ملخص_الأسبوع #كرة_القدم"]
    return "\n".join(parts)


async def post_weekly_summary(bot: Bot, settings: Settings) -> None:
    if not settings.channel_id:
        return
    text = build_weekly(extras.top_week(5), datetime.now(fixtures.TZ))
    if text:
        await bot.send_message(
            chat_id=settings.channel_id,
            text=text + extras.signature(settings),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
