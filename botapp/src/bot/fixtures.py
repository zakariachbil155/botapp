"""منشور مباريات اليوم (يُرسل كل صباح 10:30 بتوقيت المغرب).

المصدر: football-data.org (الخطة المجانية). تغطي: الدوري الإنجليزي والإسباني والإيطالي
والألماني والفرنسي، ودوري أبطال أوروبا، وكأس العالم، وأمم أوروبا.
لا تغطي الدوري المغربي ولا الدوريات العربية ولا الإفريقية.

متغيرات البيئة:
    FOOTBALL_DATA_API_KEY   مفتاح football-data.org (مطلوب)
    TIMEZONE                اختياري، الافتراضي Africa/Casablanca
"""
import html
import logging
import os
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from telegram import Bot
from telegram.constants import ParseMode

from src.bot.config import Settings

log = logging.getLogger(__name__)

API_URL = "https://api.football-data.org/v4/matches"
TZ = ZoneInfo(os.getenv("TIMEZONE", "Africa/Casablanca"))
MESSAGE_MAX = 3800

# رموز مسابقات الخطة المجانية
COMPETITIONS = "PL,PD,SA,BL1,FL1,CL,WC,EC"
# مسابقات تُنشر كل مبارياتها، وغيرها لا يُنشر إلا إذا كان فيه نادٍ كبير
ALWAYS = {"CL", "WC", "EC"}
SKIP_STATUS = {"CANCELLED", "POSTPONED", "SUSPENDED"}

COMP_AR = {
    "PL": "🏴󠁧󠁢󠁥󠁮󠁧󠁿 الدوري الإنجليزي الممتاز",
    "PD": "🇪🇸 الدوري الإسباني",
    "SA": "🇮🇹 الدوري الإيطالي",
    "BL1": "🇩🇪 الدوري الألماني",
    "FL1": "🇫🇷 الدوري الفرنسي",
    "CL": "🏆 دوري أبطال أوروبا",
    "WC": "🌍 كأس العالم",
    "EC": "🇪🇺 كأس أمم أوروبا",
}
COMP_ORDER = ["CL", "WC", "EC", "PL", "PD", "SA", "BL1", "FL1"]

# (جزء من الاسم الإنجليزي بحروف صغيرة، الاسم العربي، نادٍ كبير؟)
# الترتيب مهم: الأطول والأخص أولاً (internazionale قبل milan).
TEAMS = [
    ("real madrid", "ريال مدريد", True), ("paris saint", "باريس سان جيرمان", True),
    ("barcelona", "برشلونة", True), ("atlético", "أتلتيكو مدريد", True),
    ("atletico", "أتلتيكو مدريد", True),
    ("manchester city", "مانشستر سيتي", True), ("manchester united", "مانشستر يونايتد", True),
    ("liverpool", "ليفربول", True), ("arsenal", "أرسنال", True), ("chelsea", "تشيلسي", True),
    ("tottenham", "توتنهام", True), ("juventus", "يوفنتوس", True),
    ("internazionale", "إنتر ميلان", True), ("ac milan", "ميلان", True), ("napoli", "نابولي", True),
    ("bayern", "بايرن ميونخ", True), ("dortmund", "بوروسيا دورتموند", True),
    ("leverkusen", "باير ليفركوزن", True), ("marseille", "مارسيليا", True),
    ("monaco", "موناكو", True), ("benfica", "بنفيكا", True), ("porto", "بورتو", True),
    ("sporting", "سبورتينغ لشبونة", True), ("ajax", "أياكس", True),
    ("galatasaray", "غلطة سراي", True), ("fenerbahçe", "فنربخشة", True),
    ("fenerbahce", "فنربخشة", True), ("celtic", "سيلتيك", True),
    # أندية أخرى للترجمة فقط
    ("newcastle", "نيوكاسل", False), ("aston villa", "أستون فيلا", False),
    ("west ham", "وست هام", False), ("brighton", "برايتون", False), ("everton", "إيفرتون", False),
    ("sevilla", "إشبيلية", False), ("real sociedad", "ريال سوسيداد", False),
    ("villarreal", "فياريال", False), ("athletic", "أتلتيك بيلباو", False),
    ("valencia", "فالنسيا", False), ("betis", "ريال بيتيس", False),
    ("roma", "روما", False), ("lazio", "لاتسيو", False), ("atalanta", "أتالانتا", False),
    ("fiorentina", "فيورنتينا", False), ("lyonnais", "ليون", False), ("lille", "ليل", False),
    ("nice", "نيس", False), ("leipzig", "لايبزيغ", False), ("frankfurt", "آينتراخت فرانكفورت", False),
    ("stuttgart", "شتوتغارت", False),
    # منتخبات
    ("morocco", "المغرب", True), ("algeria", "الجزائر", True), ("tunisia", "تونس", True),
    ("egypt", "مصر", True), ("saudi", "السعودية", True), ("qatar", "قطر", True),
    ("france", "فرنسا", True), ("spain", "إسبانيا", True), ("england", "إنجلترا", True),
    ("germany", "ألمانيا", True), ("italy", "إيطاليا", True), ("portugal", "البرتغال", True),
    ("brazil", "البرازيل", True), ("argentina", "الأرجنتين", True),
    ("netherlands", "هولندا", True), ("belgium", "بلجيكا", True),
]

WEEKDAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
          "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]


# مطابقة بالكلمة الكاملة حتى لا تطابق roma مع Romania ولا nice مع Venice
_PATTERNS = [(re.compile(r"\b" + re.escape(k) + r"\b"), ar, big) for k, ar, big in TEAMS]


def _team(name: str) -> tuple[str, bool]:
    """يعيد (الاسم العربي، هل هو نادٍ/منتخب كبير)."""
    low = (name or "").lower()
    for pat, ar, big in _PATTERNS:
        if pat.search(low):
            return ar, big
    clean = (name or "؟").replace(" FC", "").replace("FC ", "").strip()
    return clean, False


def _day_label(d: datetime) -> str:
    return f"{WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}"


async def fetch_matches(day: datetime, client: httpx.AsyncClient | None = None) -> list[dict]:
    """يجلب مباريات اليوم (بتوقيت المغرب). نطلب يوماً قبل وبعد ثم نفلتر محلياً بسبب فرق UTC."""
    key = os.getenv("FOOTBALL_DATA_API_KEY", "")
    if not key:
        log.warning("FOOTBALL_DATA_API_KEY is not set; skipping fixtures post")
        return []
    params = {
        "competitions": COMPETITIONS,
        "dateFrom": (day - timedelta(days=1)).strftime("%Y-%m-%d"),
        "dateTo": (day + timedelta(days=1)).strftime("%Y-%m-%d"),
    }
    own = client is None
    client = client or httpx.AsyncClient(timeout=20)
    try:
        r = await client.get(API_URL, params=params, headers={"X-Auth-Token": key})
        r.raise_for_status()
        return r.json().get("matches", [])
    finally:
        if own:
            await client.aclose()


def build_messages(matches: list[dict], day: datetime) -> list[str]:
    """يبني نص المنشور (قد يكون أكثر من رسالة إن طال). قائمة فارغة إن لم توجد مباريات."""
    groups: dict[str, list[tuple[datetime, str]]] = {}
    for m in matches:
        if m.get("status") in SKIP_STATUS:
            continue
        try:
            kick = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")).astimezone(TZ)
        except (KeyError, ValueError):
            continue
        if kick.date() != day.date():
            continue
        code = (m.get("competition") or {}).get("code", "")
        if code not in COMP_AR:
            continue
        home, hbig = _team((m.get("homeTeam") or {}).get("name", ""))
        away, abig = _team((m.get("awayTeam") or {}).get("name", ""))
        if code not in ALWAYS and not (hbig or abig):
            continue
        line = f"🕒 {kick:%H:%M} | {html.escape(home)} 🆚 {html.escape(away)}"
        groups.setdefault(code, []).append((kick, line))

    if not groups:
        return []

    header = f"📅 <b>مباريات اليوم</b> — {_day_label(day)}"
    footer = "⏰ التوقيت بتوقيت المغرب"
    blocks = []
    for code in COMP_ORDER:
        if code in groups:
            lines = [ln for _, ln in sorted(groups[code])]
            blocks.append(f"<b>{COMP_AR[code]}</b>\n" + "\n".join(lines))

    messages, cur = [], header
    for b in blocks:
        if len(cur) + len(b) + len(footer) + 4 > MESSAGE_MAX:
            messages.append(cur)
            cur = b
        else:
            cur += "\n\n" + b
    messages.append(cur + "\n\n" + footer)
    return messages


async def post_todays_fixtures(bot: Bot, settings: Settings) -> None:
    """مهمة مجدولة: تنشر قائمة مباريات اليوم في القناة (لا تنشر شيئاً إن لم توجد مباريات)."""
    if not settings.channel_id:
        log.warning("CHANNEL_ID is not set; skipping fixtures post")
        return
    today = datetime.now(TZ)
    try:
        matches = await fetch_matches(today)
    except Exception:
        log.exception("Failed to fetch today's fixtures")
        return
    for text in build_messages(matches, today):
        await bot.send_message(
            chat_id=settings.channel_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
