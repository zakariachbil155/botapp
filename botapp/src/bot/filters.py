"""فلتر يُبقي أخبار كرة القدم للرجال فقط ويمنع أخبار كرة القدم النسائية.

الاستعمال في jobs.py، قبل استدعاء Writer.rewrite:

    from src.bot.filters import is_womens
    if is_womens(entry):
        continue   # تجاهل الخبر
"""
import re

# إنجليزية (بحدود الكلمة لتفادي الإيجابيات الكاذبة)
_EN = re.compile(
    r"\b(women|women's|womens|woman|ladies|lady|lionesses|matildas|wsl|nwsl|wwc|"
    r"female|females|girls|girl's|feminine|barclays women|"
    r"women's super league|women's champions league|women's world cup|"
    r"uwcl|liga f|d1 arkema|frauen|f[eé]minin[e]?s?)\b",
    re.IGNORECASE,
)
# إسبانية (مصدر As): femenino / féminas / mujeres / femení (كتالانية)
_ES = re.compile(r"\b(femenin[oa]s?|f[eé]minas?|mujer(es)?|femen[ií])\b", re.IGNORECASE)
# عربية
_AR = re.compile(
    r"(السيدات|النساء|نساء|نسائي|نسائية|النسائي|النسائية|للسيدات|للنساء|سيدات|"
    r"لبؤات|اللبؤات|الفتيات|فتيات|للفتيات|الإناث|إناث)"
)
# مقاطع في الرابط مثل /football/women/ أو /femenino/ أو /frauen/
_URL = re.compile(r"/(women|womens|woman|femenino|femenina|feminin|frauen|ladies)(/|-|$)", re.IGNORECASE)


def is_womens(entry) -> bool:
    """True إذا كان الخبر عن كرة القدم النسائية (يفحص العنوان والملخص ورابط الخبر)."""
    title = getattr(entry, "title", "") or ""
    summary = getattr(entry, "summary", "") or ""
    link = getattr(entry, "link", "") or getattr(entry, "url", "") or ""
    text = " ".join((title, summary))
    return bool(_EN.search(text) or _ES.search(text) or _AR.search(text) or _URL.search(link))
