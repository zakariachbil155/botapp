"""منشور مباريات اليوم (يُرسل كل صباح 10:30 بتوقيت المغرب).

المصدر: football-data.org (الخطة المجانية). تغطي: الدوري الإنجليزي والإسباني والإيطالي
والألماني والفرنسي، ودوري أبطال أوروبا، وكأس العالم، وأمم أوروبا.
للدوريات العربية والإفريقية والمنتخبات (ودية/تصفيات) يُستعمل مصدر مجاني إضافي (TheSportsDB)
بأفضل جهد: إن فشل يُكتفى بالمصدر الأول دون أي خطأ.

المفتاح: settings.football_token (نفسه المستعمل في /results و/table).
متغير البيئة TIMEZONE اختياري، الافتراضي Africa/Casablanca.
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
FINISHED_WORDS = {"match finished", "ft", "finished", "aet", "after extra time", "pen", "after penalties", "aot"}

COMP_AR = {
    "PL": "🏴 الدوري الإنجليزي الممتاز",
    "PD": "🇪🇸 الدوري الإسباني",
    "SA": "🇮🇹 الدوري الإيطالي",
    "BL1": "🇩🇪 الدوري الألماني",
    "FL1": "🇫🇷 الدوري الفرنسي",
    "CL": "🏆 دوري أبطال أوروبا",
    "WC": "🌍 كأس العالم",
    "EC": "🇪🇺 كأس أمم أوروبا",
}
COMP_ORDER = ["CL", "WC", "EC", "PL", "PD", "SA", "BL1", "FL1"]

# مصدر إضافي مجاني للدوريات العربية والمنتخبات (اسم الدوري عند المصدر -> عنوان عربي)
EXTRA_URL = "https://www.thesportsdb.com/api/v1/json/3/eventsday.php"
EXTRA_LEAGUES = {
    "saudi pro league": "🇸🇦 دوري روشن السعودي",
    "saudi professional league": "🇸🇦 دوري روشن السعودي",
    "egyptian premier league": "🇪🇬 الدوري المصري",
    "moroccan botola pro": "🇲🇦 البطولة الاحترافية المغربية",
    "botola pro": "🇲🇦 البطولة الاحترافية المغربية",
    "algerian ligue professionnelle 1": "🇩🇿 الدوري الجزائري",
    "tunisian ligue professionnelle 1": "🇹🇳 الدوري التونسي",
    "caf champions league": "🌍 دوري أبطال إفريقيا",
    "caf confederation cup": "🌍 كأس الكونفدرالية الإفريقية",
    "afc champions league elite": "🌏 دوري أبطال آسيا",
    "arab cup": "🏆 كأس العرب",
    "africa cup of nations": "🏆 كأس أمم إفريقيا",
    "international friendlies": "🤝 مباريات ودية دولية",
    "friendlies": "🤝 مباريات ودية دولية",
    "fifa world cup qualifying": "🌍 تصفيات كأس العالم",
    "world cup qualifying": "🌍 تصفيات كأس العالم",
    "uefa nations league": "🇪🇺 دوري الأمم الأوروبية",
    "uefa european championship qualifying": "🇪🇺 تصفيات أمم أوروبا",
}
EXTRA_ORDER = ["🌍", "🏆", "🤝", "🇪🇺", "🇸🇦", "🇪🇬", "🇲🇦", "🇩🇿", "🇹🇳", "🌏"]

# (مفتاح إنجليزي بحروف صغيرة، الاسم العربي، مهم؟، علم المنتخب أو "")
# الترتيب مهم: الأطول والأخص أولاً.
TEAMS = [
    # إسبانيا
    ("real madrid", "ريال مدريد", True, ""), ("barcelona", "برشلونة", True, ""),
    ("atlético", "أتلتيكو مدريد", True, ""), ("atletico", "أتلتيكو مدريد", True, ""),
    ("sevilla", "إشبيلية", False, ""), ("real sociedad", "ريال سوسيداد", False, ""),
    ("villarreal", "فياريال", False, ""), ("athletic", "أتلتيك بيلباو", False, ""),
    ("valencia", "فالنسيا", False, ""), ("betis", "ريال بيتيس", False, ""),
    ("girona", "جيرونا", False, ""),
    # إنجلترا
    ("manchester city", "مانشستر سيتي", True, ""), ("manchester united", "مانشستر يونايتد", True, ""),
    ("liverpool", "ليفربول", True, ""), ("arsenal", "أرسنال", True, ""), ("chelsea", "تشيلسي", True, ""),
    ("tottenham", "توتنهام", True, ""), ("newcastle", "نيوكاسل", False, ""),
    ("aston villa", "أستون فيلا", False, ""), ("west ham", "وست هام", False, ""),
    ("brighton", "برايتون", False, ""), ("everton", "إيفرتون", False, ""),
    ("crystal palace", "كريستال بالاس", False, ""), ("fulham", "فولهام", False, ""),
    # إيطاليا
    ("juventus", "يوفنتوس", True, ""), ("internazionale", "إنتر ميلان", True, ""),
    ("inter milan", "إنتر ميلان", True, ""), ("ac milan", "ميلان", True, ""),
    ("napoli", "نابولي", True, ""), ("roma", "روما", False, ""), ("lazio", "لاتسيو", False, ""),
    ("atalanta", "أتالانتا", False, ""), ("fiorentina", "فيورنتينا", False, ""),
    ("como", "كومو", False, ""), ("bologna", "بولونيا", False, ""),
    # ألمانيا
    ("bayern", "بايرن ميونخ", True, ""), ("dortmund", "بوروسيا دورتموند", True, ""),
    ("leverkusen", "باير ليفركوزن", True, ""), ("leipzig", "لايبزيغ", False, ""),
    ("frankfurt", "آينتراخت فرانكفورت", False, ""), ("stuttgart", "شتوتغارت", False, ""),
    # فرنسا
    ("paris saint", "باريس سان جيرمان", True, ""), ("paris sg", "باريس سان جيرمان", True, ""),
    ("marseille", "مارسيليا", True, ""), ("monaco", "موناكو", True, ""),
    ("lyonnais", "ليون", False, ""), ("lyon", "ليون", False, ""), ("lille", "ليل", False, ""),
    ("nice", "نيس", False, ""), ("lens", "لانس", False, ""),
    # أوروبا
    ("benfica", "بنفيكا", True, ""), ("porto", "بورتو", True, ""),
    ("sporting", "سبورتينغ لشبونة", True, ""), ("ajax", "أياكس", True, ""),
    ("psv", "آيندهوفن", False, ""), ("feyenoord", "فينورد", False, ""),
    ("galatasaray", "غلطة سراي", True, ""), ("fenerbahçe", "فنربخشة", True, ""),
    ("fenerbahce", "فنربخشة", True, ""), ("besiktas", "بشكتاش", False, ""),
    ("celtic", "سيلتيك", True, ""), ("rangers", "رينجرز", False, ""),
    ("club brugge", "كلوب بروج", False, ""), ("olympiacos", "أولمبياكوس", False, ""),
    ("shakhtar", "شاختار دونيتسك", False, ""), ("red star", "النجم الأحمر", False, ""),
    ("crvena zvezda", "النجم الأحمر", False, ""), ("salzburg", "سالزبورغ", False, ""),
    ("bodø/glimt", "بودو غليمت", False, ""), ("bodo/glimt", "بودو غليمت", False, ""),
    ("pae aek", "إيه إي كيه أثينا", False, ""), ("aek athens", "إيه إي كيه أثينا", False, ""),
    ("slovan", "سلوفان براتيسلافا", False, ""), ("lask", "لاسك", False, ""),
    # أندية سعودية
    ("al-hilal", "الهلال", True, "🇸🇦"), ("al hilal", "الهلال", True, "🇸🇦"),
    ("al-nassr", "النصر", True, "🇸🇦"), ("al nassr", "النصر", True, "🇸🇦"),
    ("al-ittihad", "الاتحاد", True, "🇸🇦"), ("al ittihad", "الاتحاد", True, "🇸🇦"),
    ("al-ahli saudi", "الأهلي السعودي", True, "🇸🇦"), ("al-ahli jeddah", "الأهلي السعودي", True, "🇸🇦"),
    ("al-shabab", "الشباب", False, "🇸🇦"), ("al-ettifaq", "الاتفاق", False, "🇸🇦"),
    ("al-fateh", "الفتح", False, "🇸🇦"), ("al-taawoun", "التعاون", False, "🇸🇦"),
    # أندية مصرية
    ("al ahly", "الأهلي المصري", True, "🇪🇬"), ("al-ahly", "الأهلي المصري", True, "🇪🇬"),
    ("zamalek", "الزمالك", True, "🇪🇬"), ("pyramids", "بيراميدز", True, "🇪🇬"),
    ("al masry", "المصري البورسعيدي", False, "🇪🇬"), ("ismaily", "الإسماعيلي", False, "🇪🇬"),
    # أندية مغربية
    ("wydad", "الوداد", True, "🇲🇦"), ("raja", "الرجاء", True, "🇲🇦"),
    ("far rabat", "الجيش الملكي", True, "🇲🇦"), ("as far", "الجيش الملكي", True, "🇲🇦"),
    ("maghreb fassi", "المغرب الفاسي", False, "🇲🇦"), ("rs berkane", "نهضة بركان", True, "🇲🇦"),
    ("berkane", "نهضة بركان", True, "🇲🇦"), ("hassania", "حسنية أكادير", False, "🇲🇦"),
    # أندية جزائرية وتونسية
    ("mc alger", "مولودية الجزائر", True, "🇩🇿"), ("mouloudia", "مولودية الجزائر", True, "🇩🇿"),
    ("belouizdad", "شباب بلوزداد", True, "🇩🇿"), ("jsk", "شبيبة القبائل", False, "🇩🇿"),
    ("kabylie", "شبيبة القبائل", False, "🇩🇿"), ("usm alger", "اتحاد العاصمة", True, "🇩🇿"),
    ("esperance", "الترجي", True, "🇹🇳"), ("espérance", "الترجي", True, "🇹🇳"),
    ("club africain", "النادي الإفريقي", True, "🇹🇳"), ("etoile du sahel", "النجم الساحلي", True, "🇹🇳"),
    ("sfaxien", "الصفاقسي", False, "🇹🇳"),
    # منتخبات عربية
    ("morocco", "المغرب", True, "🇲🇦"), ("algeria", "الجزائر", True, "🇩🇿"),
    ("tunisia", "تونس", True, "🇹🇳"), ("egypt", "مصر", True, "🇪🇬"),
    ("saudi arabia", "السعودية", True, "🇸🇦"), ("saudi", "السعودية", True, "🇸🇦"),
    ("qatar", "قطر", True, "🇶🇦"), ("united arab emirates", "الإمارات", True, "🇦🇪"),
    ("uae", "الإمارات", True, "🇦🇪"), ("iraq", "العراق", True, "🇮🇶"),
    ("jordan", "الأردن", True, "🇯🇴"), ("palestine", "فلسطين", True, "🇵🇸"),
    ("oman", "عُمان", True, "🇴🇲"), ("kuwait", "الكويت", True, "🇰🇼"),
    ("bahrain", "البحرين", True, "🇧🇭"), ("lebanon", "لبنان", True, "🇱🇧"),
    ("syria", "سوريا", True, "🇸🇾"), ("libya", "ليبيا", True, "🇱🇾"),
    ("sudan", "السودان", True, "🇸🇩"), ("mauritania", "موريتانيا", True, "🇲🇷"),
    ("yemen", "اليمن", True, "🇾🇪"), ("comoros", "جزر القمر", True, "🇰🇲"),
    # منتخبات إفريقية
    ("senegal", "السنغال", True, "🇸🇳"), ("nigeria", "نيجيريا", True, "🇳🇬"),
    ("ivory coast", "كوت ديفوار", True, "🇨🇮"), ("côte d", "كوت ديفوار", True, "🇨🇮"),
    ("cameroon", "الكاميرون", True, "🇨🇲"), ("ghana", "غانا", True, "🇬🇭"),
    ("mali", "مالي", False, "🇲🇱"), ("south africa", "جنوب إفريقيا", False, "🇿🇦"),
    ("dr congo", "الكونغو الديمقراطية", False, "🇨🇩"),
    # منتخبات عالمية
    ("france", "فرنسا", True, "🇫🇷"), ("spain", "إسبانيا", True, "🇪🇸"),
    ("england", "إنجلترا", True, "🏴"), ("germany", "ألمانيا", True, "🇩🇪"),
    ("italy", "إيطاليا", True, "🇮🇹"), ("portugal", "البرتغال", True, "🇵🇹"),
    ("brazil", "البرازيل", True, "🇧🇷"), ("argentina", "الأرجنتين", True, "🇦🇷"),
    ("netherlands", "هولندا", True, "🇳🇱"), ("belgium", "بلجيكا", True, "🇧🇪"),
    ("croatia", "كرواتيا", True, "🇭🇷"), ("uruguay", "الأوروغواي", True, "🇺🇾"),
    ("colombia", "كولومبيا", False, "🇨🇴"), ("mexico", "المكسيك", False, "🇲🇽"),
    ("united states", "الولايات المتحدة", False, "🇺🇸"), ("japan", "اليابان", False, "🇯🇵"),
    ("south korea", "كوريا الجنوبية", False, "🇰🇷"), ("turkey", "تركيا", False, "🇹🇷"),
    ("türkiye", "تركيا", False, "🇹🇷"), ("switzerland", "سويسرا", False, "🇨🇭"),
    ("denmark", "الدنمارك", False, "🇩🇰"), ("poland", "بولندا", False, "🇵🇱"),
]

WEEKDAYS = ["الاثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
MONTHS = ["يناير", "فبراير", "مارس", "أبريل", "مايو", "يونيو",
          "يوليو", "أغسطس", "سبتمبر", "أكتوبر", "نوفمبر", "ديسمبر"]

# مطابقة بالكلمة الكاملة حتى لا تطابق roma مع Romania ولا nice مع Venice.
# المسافة تطابق مسافة أو شرطة (Al Hilal / Al-Hilal).
_PATTERNS = [
    (re.compile(r"\b" + re.escape(k).replace(r"\ ", r"[ \-]") + r"\b"), ar, big, flag)
    for k, ar, big, flag in TEAMS
]
_YOUTH = re.compile(r"\bu[ -]?(1[5-9]|2[0-3])\b|\bolympic\b", re.I)
_WOMEN = re.compile(r"\bwomen|\bfemin|\bladies\b|\bgirls\b|\bw$", re.I)
RLM = "&#8207;"  # علامة اتجاه من اليمين لليسار (كيان HTML بلا محارف مخفية في الملف)


def _team(name: str) -> tuple[str, bool, str]:
    """يعيد (الاسم العربي، مهم؟، علم). الاسم غير المعروف يبقى كما هو."""
    low = (name or "").lower()
    for pat, ar, big, flag in _PATTERNS:
        if pat.search(low):
            return ar, big, flag
    clean = (name or "؟").replace(" FC", "").replace("FC ", "").strip()
    return clean, False, ""


def _day_label(d: datetime) -> str:
    return f"{WEEKDAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]} {d.year}"


async def fetch_matches(
    day: datetime, token: str, client: httpx.AsyncClient | None = None
) -> list[dict]:
    """يجلب مباريات اليوم (بتوقيت المغرب). نطلب يوماً قبل وبعد ثم نفلتر محلياً بسبب فرق UTC."""
    if not token:
        log.warning("football token is not set; cannot fetch fixtures")
        return []
    params = {
        "competitions": COMPETITIONS,
        "dateFrom": (day - timedelta(days=1)).strftime("%Y-%m-%d"),
        "dateTo": (day + timedelta(days=1)).strftime("%Y-%m-%d"),
    }
    own = client is None
    client = client or httpx.AsyncClient(timeout=20)
    try:
        r = await client.get(API_URL, params=params, headers={"X-Auth-Token": token})
        r.raise_for_status()
        return r.json().get("matches", [])
    finally:
        if own:
            await client.aclose()


async def fetch_extra(day: datetime, client: httpx.AsyncClient | None = None) -> list[dict]:
    """مباريات الدوريات العربية والمنتخبات من TheSportsDB. أي فشل يعيد قائمة فارغة."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=20)
    out: list[dict] = []
    try:
        for delta in (-1, 0, 1):
            d = (day + timedelta(days=delta)).strftime("%Y-%m-%d")
            try:
                r = await client.get(EXTRA_URL, params={"d": d, "s": "Soccer"})
                r.raise_for_status()
                out.extend(r.json().get("events") or [])
            except Exception:
                log.warning("extra fixtures source failed for %s", d, exc_info=True)
    finally:
        if own:
            await client.aclose()
    return out


def _collect(
    matches: list[dict], extra: list[dict], day: datetime, results: bool = False
) -> dict[str, dict]:
    """يوحّد المصدرين: {مفتاح: {"title": عنوان, "rank": ترتيب, "rows": [(وقت، سطر)]}}."""
    groups: dict[str, dict] = {}

    def add(key, title, rank, kick, home, away, score=None):
        hn, hbig, hflag = home
        an, abig, aflag = away
        star = "🔥 " if hbig and abig else ""
        h = f"{hflag} {hn}".strip()
        a = f"{aflag} {an}".strip()
        if score is not None:
            line = f"{RLM}{star}{html.escape(h)} <b>({score[0]})</b> ⚔️ <b>({score[1]})</b> {html.escape(a)}{score[2]}"
        else:
            line = f"{RLM}🕒 <code>{kick:%H:%M}</code> ┃ {star}{html.escape(h)} ⚔️ {html.escape(a)}"
        g = groups.setdefault(key, {"title": title, "rank": rank, "rows": []})
        if (kick, line) not in g["rows"]:
            g["rows"].append((kick, line))

    for m in matches:
        if results:
            if m.get("status") != "FINISHED":
                continue
        elif m.get("status") in SKIP_STATUS:
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
        home = _team((m.get("homeTeam") or {}).get("name", ""))
        away = _team((m.get("awayTeam") or {}).get("name", ""))
        if code not in ALWAYS and not (home[1] or away[1]):
            continue
        score = None
        if results:
            sc = m.get("score") or {}
            ft = sc.get("fullTime") or {}
            if ft.get("home") is None or ft.get("away") is None:
                continue
            pen = sc.get("penalties") or {}
            note = ""
            if sc.get("duration") == "PENALTY_SHOOTOUT" and pen.get("home") is not None:
                note = f" <i>(ركلات الترجيح {pen['home']}-{pen['away']})</i>"
            score = (ft["home"], ft["away"], note)
        add(code, COMP_AR[code], COMP_ORDER.index(code), kick, home, away, score)

    for e in extra:
        league = (e.get("strLeague") or "").strip()
        title = EXTRA_LEAGUES.get(league.lower())
        hname, aname = e.get("strHomeTeam") or "", e.get("strAwayTeam") or ""
        if not title or not hname or not aname:
            continue
        if _WOMEN.search(hname + " " + aname + " " + league) or _YOUTH.search(hname + " " + aname):
            continue
        ts = e.get("strTimestamp") or ""
        try:
            if not ts and e.get("dateEvent") and e.get("strTime"):
                ts = f"{e['dateEvent']}T{e['strTime']}"
            kick = datetime.fromisoformat(ts.replace("Z", "")).replace(tzinfo=ZoneInfo("UTC")).astimezone(TZ)
        except ValueError:
            continue
        if kick.date() != day.date():
            continue
        home, away = _team(hname), _team(aname)
        if not (home[1] or away[1]):
            continue
        rank = 100 + next((i for i, em in enumerate(EXTRA_ORDER) if title.startswith(em)), 50)
        score = None
        if results:
            hs, as_ = e.get("intHomeScore"), e.get("intAwayScore")
            done = (e.get("strStatus") or "").lower() in FINISHED_WORDS
            if hs in (None, "") or as_ in (None, "") or not done:
                continue
            score = (hs, as_, "")
        add("X:" + title, title, rank, kick, home, away, score)
    return groups


def build_messages(matches: list[dict], day: datetime, extra: list[dict] | None = None) -> list[str]:
    """يبني نص المنشور (قد يكون أكثر من رسالة إن طال). قائمة فارغة إن لم توجد مباريات."""
    groups = _collect(matches, extra or [], day)
    if not groups:
        return []

    total = sum(len(g["rows"]) for g in groups.values())
    sep = "┈┈┈┈┈┈┈┈┈┈┈┈┈┈"
    header = (
        f"📅 <b>مباريات اليوم</b>\n"
        f"🗓 {_day_label(day)}\n"
        f"⚽ {total} مباراة مهمة\n"
        f"{sep}"
    )
    footer = f"{sep}\n⏰ جميع الأوقات بتوقيت المغرب\n🔥 = مواجهة بين طرفين كبيرين\n\n#مباريات_اليوم #كرة_القدم"
    blocks = []
    for g in sorted(groups.values(), key=lambda x: x["rank"]):
        lines = [ln for _, ln in sorted(g["rows"])]
        blocks.append(f"<b>{g['title']}</b>\n" + "\n".join(lines))

    messages, cur = [], header
    for b in blocks:
        if len(cur) + len(b) + len(footer) + 4 > MESSAGE_MAX:
            messages.append(cur)
            cur = b
        else:
            cur += "\n\n" + b
    messages.append(cur + "\n\n" + footer)
    return messages


def build_results_messages(
    matches: list[dict], day: datetime, extra: list[dict] | None = None
) -> list[str]:
    """نتائج اليوم للمباريات المنتهية فقط. قائمة فارغة إن لم تنتهِ أي مباراة مهمة."""
    groups = _collect(matches, extra or [], day, results=True)
    if not groups:
        return []
    total = sum(len(g["rows"]) for g in groups.values())
    sep = "┈┈┈┈┈┈┈┈┈┈┈┈┈┈"
    header = f"📊 <b>نتائج اليوم</b>\n🗓 {_day_label(day)}\n✅ {total} مباراة منتهية\n{sep}"
    footer = f"{sep}\n🔥 = مواجهة بين طرفين كبيرين\n\n#نتائج_المباريات #كرة_القدم"
    blocks = []
    for g in sorted(groups.values(), key=lambda x: x["rank"]):
        lines = [ln for _, ln in sorted(g["rows"])]
        blocks.append(f"<b>{g['title']}</b>\n" + "\n".join(lines))
    messages, cur = [], header
    for b in blocks:
        if len(cur) + len(b) + len(footer) + 4 > MESSAGE_MAX:
            messages.append(cur)
            cur = b
        else:
            cur += "\n\n" + b
    messages.append(cur + "\n\n" + footer)
    return messages


async def post_todays_results(bot: Bot, settings: Settings) -> None:
    """مهمة مجدولة: تنشر نتائج مباريات اليوم المنتهية في القناة."""
    if not settings.channel_id:
        log.warning("CHANNEL_ID is not set; skipping results post")
        return
    today = datetime.now(TZ)
    try:
        matches = await fetch_matches(today, settings.football_token)
    except Exception:
        log.exception("Failed to fetch today's results")
        matches = []
    extra = await fetch_extra(today)
    for text in build_results_messages(matches, today, extra):
        await bot.send_message(
            chat_id=settings.channel_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


async def post_todays_fixtures(bot: Bot, settings: Settings) -> None:
    """مهمة مجدولة: تنشر قائمة مباريات اليوم في القناة (لا تنشر شيئاً إن لم توجد مباريات)."""
    if not settings.channel_id:
        log.warning("CHANNEL_ID is not set; skipping fixtures post")
        return
    today = datetime.now(TZ)
    try:
        matches = await fetch_matches(today, settings.football_token)
    except Exception:
        log.exception("Failed to fetch today's fixtures")
        matches = []
    extra = await fetch_extra(today)
    for text in build_messages(matches, today, extra):
        await bot.send_message(
            chat_id=settings.channel_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
