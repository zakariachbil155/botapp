"""أدوات مشتركة: الأخبار العاجلة، علم المغرب، الأولوية، الساعات الهادئة،
الوسوم الثابتة، الأزرار، التوقيع، وذاكرة ملخص الليلة.

متغيرات بيئة اختيارية (كلها لها قيم افتراضية):
  CHANNEL_USERNAME  اسم القناة بلا @ (لتفعيل زر المشاركة والتوقيع)، أو CHANNEL_LINK برابط كامل
  QUIET_START / QUIET_END  ساعات الهدوء (الافتراضي 1 و 7)
  TIMEZONE  الافتراضي Africa/Casablanca
"""
import html
import logging
import os
import re
from datetime import datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

log = logging.getLogger(__name__)
TZ = ZoneInfo(os.getenv("TIMEZONE", "Africa/Casablanca"))

# ---------------------------------------------------------------- الوقت
def parse_hm(name: str, default: str) -> tuple[int, int]:
    """يقرأ HH:MM من متغير بيئة، ويعود للافتراضي إن كانت القيمة فارغة أو خاطئة."""
    raw = (os.getenv(name) or "").strip() or default
    try:
        h, m = (int(x) for x in raw.split(":"))
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError
    except ValueError:
        log.warning("Invalid %s=%r; falling back to %s", name, raw, default)
        h, m = (int(x) for x in default.split(":"))
    return h, m


def _hour(name: str, default: int) -> int:
    try:
        v = int((os.getenv(name) or "").strip() or default)
        return v if 0 <= v <= 23 else default
    except ValueError:
        return default


def is_quiet_now(now: datetime | None = None) -> bool:
    """هل نحن في ساعات الهدوء (1:00 إلى 7:00 افتراضياً بتوقيت المغرب)؟"""
    h = (now or datetime.now(TZ)).hour
    start, end = _hour("QUIET_START", 1), _hour("QUIET_END", 7)
    if start == end:
        return False
    return start <= h < end if start < end else (h >= start or h < end)


# ---------------------------------------------------------------- القناة
def channel_link(settings=None) -> str:
    link = (os.getenv("CHANNEL_LINK") or "").strip()
    if link:
        return link
    user = (os.getenv("CHANNEL_USERNAME") or "").strip().lstrip("@")
    if not user and settings is not None:
        cid = str(getattr(settings, "channel_id", "") or "")
        if cid.startswith("@"):
            user = cid[1:]
    return f"https://t.me/{user}" if user else ""


def signature(settings=None) -> str:
    """سطر التوقيع في آخر المنشور (فارغ إن لم يُضبط رابط القناة)."""
    link = channel_link(settings)
    return f"\n\n📢 {html.escape(link.replace('https://', ''))}" if link else ""


def buttons(url: str, settings=None):
    """أزرار تحت المنشور: «المصدر» و«مشاركة القناة»."""
    row = []
    if url and url.startswith(("http://", "https://")):
        row.append(InlineKeyboardButton("📰 المصدر", url=url))
    link = channel_link(settings)
    if link:
        share = "https://t.me/share/url?" + urlencode(
            {"url": link, "text": "قناة أخبار كرة القدم بالعربية ⚽"}
        )
        row.append(InlineKeyboardButton("📤 مشاركة القناة", url=share))
    return InlineKeyboardMarkup([row]) if row else None


# ---------------------------------------------------------------- التصنيف
_I = re.I
_TRANSFER_EN = re.compile(
    r"\b(here we go|official(ly)?\s+(announce|sign|confirm|unveil)\w*|official:|"
    r"completes?\s+(the\s+)?(signing|transfer|move)|signs?\s+(for|with)|"
    r"(signed|joins|joined)\s+(on|by|from)|agrees?\s+(a\s+)?(deal|terms|contract)|"
    r"unveiled as)\b", _I)
_COACH_EN = re.compile(
    r"\b(sack(s|ed)?|fire[sd]?|dismiss(es|ed)?|parts? company|relieved of|resigns?|steps? down|"
    r"appointed|named (as )?(new )?(head coach|manager|boss)|new (head coach|manager|boss))\b", _I)
_INJURY_EN = re.compile(
    r"\b(injur\w+|ruled out|sidelined|out for (the )?(rest|weeks|months|season)|"
    r"surgery|setback|torn|fracture|hamstring)\b", _I)
_BREAKING_AR = re.compile(
    r"(انتقال رسمي|رسمياً|رسميا|إقالة|إقالته|أقال|يقال|تعيين|استقالة|يغيب|إصابة|إصابته|تمزق|كسر)")
_BREAKING_ES = re.compile(
    r"\b(oficial|destituido|cesado|dimite|lesi[oó]n|lesionado|rotura|fichaje cerrado)\b", _I)

_STARS = re.compile(
    r"\b(mbapp[eé]|haaland|messi|ronaldo|salah|vin[ií]cius|bellingham|yamal|lewandowski|"
    r"kane|neymar|benzema|mahrez|man[eé]|osimhen|de bruyne|rodri|saka|modric|modri[cć]|"
    r"hakimi|ziyech|bounou|amrabat|en-nesyri|diaz|regragui|guardiola|ancelotti|mourinho|"
    r"klopp|arteta|xavi|flick|simeone|tuchel|ten hag|amorim|southgate|"
    r"vinicius|griezmann|lautaro|kvaratskhelia|foden|odegaard|pedri|gavi)\b"
    r"|(مبابي|هالاند|ميسي|رونالدو|صلاح|فينيسيوس|بيلينغهام|يامال|حكيمي|زياش|بونو|"
    r"الركراكي|غوارديولا|أنشيلوتي|مورينيو|أرتيتا|سيميوني)", _I)

_MOROCCO = re.compile(
    r"\b(morocc\w+|atlas lions|hakimi|ziyech|bounou|regragui|amrabat|en-nesyri|"
    r"brahim d[ií]az|wydad|raja casablanca|botola|marruecos|marroqu[ií])\b"
    r"|(المغرب|مغربي|مغربية|أسود الأطلس|الوداد|الرجاء|حكيمي|زياش|بونو|الركراكي|عموري)", _I)
_ARAB = re.compile(
    r"\b(egypt\w*|salah|algeria\w*|mahrez|tunisia\w*|saudi|al[- ](hilal|nassr|ittihad|ahli|ahly)|"
    r"zamalek|pyramids|qatar\w*|arab\w*|esperance|iraq\w*|jordan\w*|uae|emirates)\b"
    r"|(مصر|الجزائر|تونس|السعودية|الهلال|النصر|الاتحاد|الأهلي|الزمالك|قطر|العراق|الأردن|عربي|عربية)", _I)

_TAG_INJURY = re.compile(
    r"\b(injur\w+|ruled out|sidelined|surgery|setback|torn|fracture|hamstring|lesi[oó]n|lesionado)\b"
    r"|(إصابة|إصابته|يغيب|غياب|تمزق|كسر)", _I)
_TAG_TRANSFER = re.compile(
    r"\b(transfer\w*|sign(s|ed|ing)?|loan|bid|deal|here we go|join(s|ed)?|contract|fichaje\w*)\b"
    r"|(انتقال|صفقة|ينضم|تعاقد|إعارة|عقد)", _I)
_TAG_RESULT = re.compile(
    r"\b(beat|beats|win|wins|won|defeat\w*|draw|drew|thrash\w*|victory|lose|loses|lost|"
    r"derrota|victoria|empate)\b|(فوز|هزيمة|تعادل|يفوز|يتغلب|يسقط)", _I)

_big_cache = None
_big_ar: list[str] = []


def _mentions_big_club(text: str) -> bool:
    """يستعمل قاموس الأندية الكبيرة في fixtures.py (يُحمَّل عند الحاجة)."""
    global _big_cache, _big_ar
    if _big_cache is None:
        try:
            from src.bot import fixtures  # noqa: WPS433 (استيراد متأخر لتفادي الدوران)
            _big_cache = [p for p, _ar, big, _f in fixtures._PATTERNS if big]
            _big_ar = [ar for _p, ar, big, _f in fixtures._PATTERNS if big]
        except Exception:  # pragma: no cover
            _big_cache = []
    low = text.lower()
    return any(p.search(low) for p in _big_cache) or any(ar in text for ar in _big_ar)


def _text(entry) -> str:
    return f"{getattr(entry, 'title', '') or ''} {(getattr(entry, 'summary', '') or '')[:300]}"


def is_breaking(entry) -> bool:
    """خبر عاجل: انتقال رسمي أو إقالة/تعيين مدرب أو إصابة، ويخص ناديًا أو نجمًا كبيرًا."""
    text = _text(entry)
    trigger = (
        _TRANSFER_EN.search(text) or _COACH_EN.search(text) or _INJURY_EN.search(text)
        or _BREAKING_AR.search(text) or _BREAKING_ES.search(text)
    )
    if not trigger:
        return False
    return bool(_STARS.search(text) or _MOROCCO.search(text) or _mentions_big_club(text))


def is_morocco(entry) -> bool:
    return bool(_MOROCCO.search(_text(entry)))


def is_arab(entry) -> bool:
    return bool(_ARAB.search(_text(entry)))


def priority(entry) -> int:
    """عاجل 100، مغربي 50، عربي 30 (تُجمع). كلما زاد الرقم نُشر الخبر أبكر."""
    return (100 if is_breaking(entry) else 0) + (50 if is_morocco(entry) else 0) + (
        30 if is_arab(entry) else 0)


def category_tag(entry) -> str:
    """الوسم الثابت: #إصابات أو #انتقالات أو #نتائج (الأولوية بهذا الترتيب)."""
    text = _text(entry)
    if _TAG_INJURY.search(text):
        return "#إصابات"
    if _TAG_TRANSFER.search(text):
        return "#انتقالات"
    if _TAG_RESULT.search(text):
        return "#نتائج"
    return ""


# ---------------------------------------------------------------- التزيين
_LEAD = re.compile(r"^[^\w#]+")
_TAGS = re.compile(r"#\w+")
MAX_TAGS_DECORATED = 4


def decorate(text: str, entry, brk: bool) -> str:
    """يضيف 🚨 عاجل وعلم المغرب إلى العنوان، ويضمن الوسم الثابت في سطر الوسوم."""
    lines = text.split("\n")
    head = lines[0]
    m = _LEAD.match(head)
    emoji = m.group(0).strip() if m else ""
    body = head[m.end():] if m else head
    flag = "🇲🇦 " if is_morocco(entry) else ""
    lines[0] = (f"🚨 عاجل ┃ {flag}{body}" if brk else f"{emoji} {flag}{body}").strip()

    tags: list[str] = []
    if lines and lines[-1].strip().startswith("#"):
        tags = _TAGS.findall(lines.pop())
        while lines and not lines[-1].strip():
            lines.pop()
    pre = (["#عاجل"] if brk else []) + ([category_tag(entry)] if category_tag(entry) else [])
    tags = pre + [t for t in tags if t not in pre][: MAX_TAGS_DECORATED - len(pre)]
    out = "\n".join(lines)
    return f"{out}\n\n{' '.join(tags)}" if tags else out


# ---------------------------------------------------------------- ذاكرة الملخص
DIGEST: list[dict] = []
WEEK: list[dict] = []


def remember(entry, text: str, brk: bool) -> None:
    """يحفظ الخبر المنشور لملخص الليلة (في الذاكرة فقط، ويُفرَّغ عند إعادة التشغيل)."""
    today = datetime.now(TZ).date()
    DIGEST[:] = [d for d in DIGEST if d["day"] == today]
    item = {
        "day": today, "title": text.split("\n")[0], "link": getattr(entry, "link", ""),
        "prio": priority(entry), "n": len(DIGEST),
    }
    DIGEST.append(item)
    cutoff = today - timedelta(days=7)
    WEEK[:] = [w for w in WEEK if w["day"] > cutoff]
    WEEK.append(dict(item))


def top_week(n: int = 5) -> list[dict]:
    """أهم أخبار آخر 7 أيام (الأعلى أولوية ثم الأحدث)."""
    cutoff = datetime.now(TZ).date() - timedelta(days=7)
    items = [w for w in WEEK if w["day"] > cutoff]
    items.sort(key=lambda w: (-w["prio"], -w["day"].toordinal(), -w["n"]))
    return items[:n]


def top_news(n: int = 5) -> list[dict]:
    today = datetime.now(TZ).date()
    items = [d for d in DIGEST if d["day"] == today]
    return sorted(items, key=lambda d: (-d["prio"], -d["n"]))[:n]
