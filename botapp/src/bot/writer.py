import re

from groq import AsyncGroq

from src.bot.feeds import Entry

# حد تعليق الصورة في تيليغرام 1024 حرفاً. نبقى تحته لأن سطر المصدر يُضاف بعد الصياغة.
MAX_CHARS = 330
SUMMARY_MAX = 160  # أقصى طول للملخص بالحروف
SUMMARY_SENTENCES = 1
MAX_BULLETS = 2
MAX_TAGS = 3

# الموجّه هو ما يجعل الناتج صحافة رياضية عربية لا ترجمة حرفية. عدّله بحرية.
SYSTEM_PROMPT = """أنت محرر رياضي في صحيفة عربية كبرى.
مهمتك: إعادة صياغة الخبر الكروي الإنجليزي بأسلوب صحفي عربي سلس ومختصر ومركّز، وليس ترجمة حرفية.

التنسيق المطلوب بالضبط (نص عادي دون أي رموز تنسيق مثل ** أو #عنوان):

[إيموجي] عنوان قصير جذاب في سطر واحد

فقرة ملخص من جملة واحدة قصيرة جداً (أقل من 150 حرفاً) بالفصحى المبسّطة، تذكر الحدث وأهم ما فيه فقط.

📌 التفاصيل:
• معلومة قصيرة جداً من النص (رقم أو اسم أو تاريخ)
• معلومة ثانية قصيرة جداً

#وسم1 #وسم2 #وسم3

اختر إيموجي العنوان حسب نوع الخبر:
- نتيجة مباراة: ⚽
- انتقال لاعب أو مفاوضات: 🔄
- إصابة أو غياب: 🏥
- تتويج أو لقب: 🏆
- إقالة أو تعيين مدرب: 🧑‍💼
- رقم قياسي أو إحصائية: 📊
- قرار تحكيمي أو عقوبة: 🟨
- خبر عاجل أو رسمي مهم: 🚨
- أي خبر آخر: 📰

قواعد الوسوم:
- ثلاثة وسوم عربية فقط، وكل وسم كلمة واحدة أو كلمات موصولة بشرطة سفلية (#الدوري_الإنجليزي).
- تخص النادي واللاعب والبطولة والموضوع الوارد في الخبر فقط، ولا تخترع وسوماً عامة.
- سطر الوسوم هو آخر سطر في الرد.

قواعد عامة:
- أبقِ أسماء اللاعبين والأندية دقيقة بالتهجئة العربية الشائعة.
- لا تخترع أي معلومة أو رقم أو تصريح غير موجود في النص.
- لا تحوّل الإشاعة إلى خبر مؤكد، واستخدم «بحسب تقارير» عند الحاجة.
- لا تضف رابطاً ولا مصدراً ولا تعليقات شخصية، ولا مبالغات ولا عناوين مضللة.
- الطول الكلي متوسط: بين 200 و300 حرف، ولا تكرر في التفاصيل ما قلته في الملخص.
"""

_URL = re.compile(r"https?://\S+")
_TAG = re.compile(r"#[\w؀-ۿ]+")


def _split_tags(text: str) -> tuple[str, list[str]]:
    """يفصل سطر الوسوم الأخير عن الجسم، ويعيد الوسوم منظّفة وفريدة."""
    lines = text.rstrip().split("\n")
    tags: list[str] = []
    while lines and (not lines[-1].strip() or lines[-1].strip().startswith("#")):
        last = lines.pop()
        tags = _TAG.findall(last) + tags
    seen, unique = set(), []
    for t in tags:
        if t not in seen:
            seen.add(t)
            unique.append(t)
    return "\n".join(lines).rstrip(), unique[:MAX_TAGS]


def _drop_details(body: str) -> str:
    """يحذف كتلة التفاصيل (📌 وما بعدها) إن ضاق المجال."""
    idx = body.find("📌")
    return body[:idx].rstrip() if idx != -1 else body


_SENT = re.compile(r"(?<=[.!؟?])\s+")


def _shorten_summary(summary: str) -> str:
    """يبقي أول جملتين فقط، وجملة واحدة إن زاد الطول عن الحد."""
    sentences = [x.strip() for x in _SENT.split(summary.strip()) if x.strip()]
    if not sentences:
        return summary.strip()
    out = " ".join(sentences[:SUMMARY_SENTENCES])
    if len(out) > SUMMARY_MAX and len(sentences) > 1:
        out = sentences[0]
    if len(out) > SUMMARY_MAX:
        cut = out[:SUMMARY_MAX]
        end = max(cut.rfind("،"), cut.rfind(" "))
        out = cut[:end].rstrip("،, ") + "…"
    return out


def _tighten_body(body: str) -> str:
    """يقصّ كتلة الملخص (بين العنوان وقسم التفاصيل) دون المساس بغيرها."""
    idx = body.find("📌")
    head, rest = (body[:idx].rstrip(), body[idx:]) if idx != -1 else (body, "")
    parts = head.split("\n\n", 1)
    if len(parts) == 2:
        head = parts[0] + "\n\n" + _shorten_summary(parts[1])
    if rest:
        lines = rest.split("\n")
        bullets = [x for x in lines[1:] if x.strip().startswith(("•", "-", "*"))][:MAX_BULLETS]
        rest = "\n".join([lines[0]] + bullets)
    return head + ("\n\n" + rest if rest else "")


def _clean(text: str) -> str:
    text = text.replace("**", "").replace("__", "")
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)  # عناوين markdown لا وسوم
    text = _URL.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    body, tags = _split_tags(text)
    body = _tighten_body(body)
    tag_line = " ".join(tags)

    def total(b: str) -> int:
        return len(b) + (len(tag_line) + 2 if tag_line else 0)

    if total(body) > MAX_CHARS:
        body = _drop_details(body)
    if total(body) > MAX_CHARS:
        room = MAX_CHARS - (len(tag_line) + 2 if tag_line else 0)
        cut = body[:room]
        end = max(cut.rfind("."), cut.rfind("،"), cut.rfind("\n"))
        body = (cut[: end + 1] if end > room * 0.5 else cut).rstrip()
    return f"{body}\n\n{tag_line}" if tag_line else body


class Writer:
    def __init__(self, api_key: str, model: str) -> None:
        self._client = AsyncGroq(api_key=api_key)
        self._model = model

    async def rewrite(self, entry: Entry) -> str:
        completion = await self._client.chat.completions.create(
            model=self._model,
            temperature=0.4,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"العنوان: {entry.title}\n\nالتفاصيل: {entry.summary}"},
            ],
        )
        return _clean((completion.choices[0].message.content or "").strip())
