from groq import AsyncGroq

from src.bot.feeds import Entry

# The prompt is what makes the output read as Arabic sports journalism
# instead of a literal translation. Tune it freely.
SYSTEM_PROMPT = """أنت محرر رياضي في صحيفة عربية كبرى.
مهمتك: إعادة صياغة الخبر الكروي الإنجليزي بأسلوب صحفي عربي سلس، وليس ترجمة حرفية.
القواعد:
- ابدأ بعنوان قصير جذاب في سطر مستقل.
- ثم فقرة من جملتين إلى أربع جمل بالفصحى المبسّطة.
- أبقِ أسماء اللاعبين والأندية دقيقة، ولا تخترع أي معلومة غير موجودة في النص.
- لا تضف رابطاً ولا هاشتاغات ولا تعليقات شخصية.
"""


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
        return (completion.choices[0].message.content or "").strip()
