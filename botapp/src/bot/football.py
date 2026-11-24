"""فلتر يمنع أخبار كرة القدم النسائية من النشر.

الاستعمال في jobs.py، قبل استدعاء Writer.rewrite:

    from src.bot.filters import is_womens
    if is_womens(entry):
        continue   # تجاهل الخبر
"""
import re

# كلمات إنجليزية (بحدود الكلمة لتفادي الإيجابيات الكاذبة)
_EN = re.compile(
    r"\b(women|women's|womens|woman|ladies|lionesses|wsl|nwsl|"
    r"barclays women|women's super league|"
    r"women's champions league|uwcl)\b",
    re.IGNORECASE,
)
# إسبانية (مصدر As): femenino / féminas
_ES = re.compile(r"\b(femenin[oa]s?|f[eé]minas?|mujeres)\b", re.IGNORECASE)
# عربية
_AR = re.compile(r"(السيدات|النساء|نساء|نسائي|نسائية|للسيدات|للنساء|سيدات|لبؤات|اللبؤات)")


def is_womens(entry) -> bool:
    """True إذا كان الخبر عن كرة القدم النسائية (يفحص العنوان والملخص ورابط الخبر)."""
    parts = (
        getattr(entry, "title", "") or "",
        getattr(entry, "summary", "") or "",
        getattr(entry, "link", "") or getattr(entry, "url", "") or "",  # روابط مثل /football/women/
    )
    text = " ".join(parts)
    return bool(_EN.search(text) or _ES.search(text) or _AR.search(text))
