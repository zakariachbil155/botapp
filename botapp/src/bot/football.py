import asyncio
import html
import time
from datetime import date, timedelta
from typing import Any

import requests

BASE_URL = "https://api.football-data.org/v4"
CACHE_TTL_SECONDS = 120

LEAGUES = {
    "PL": "الدوري الإنجليزي",
    "PD": "الدوري الإسباني",
    "SA": "الدوري الإيطالي",
    "BL1": "الدوري الألماني",
    "FL1": "الدوري الفرنسي",
}
# The guide uses L1 for Ligue 1; the API code is FL1.
ALIASES = {"L1": "FL1"}

_cache: dict[str, tuple[float, Any]] = {}


def normalize_league(arg: str | None) -> str | None:
    code = (arg or "PL").upper()
    code = ALIASES.get(code, code)
    return code if code in LEAGUES else None


async def _get(token: str, path: str, params: dict[str, str] | None = None) -> Any:
    key = f"{path}?{sorted((params or {}).items())}"
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]

    def call() -> Any:
        resp = requests.get(
            f"{BASE_URL}{path}",
            headers={"X-Auth-Token": token},
            params=params,
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()

    data = await asyncio.to_thread(call)
    _cache[key] = (time.monotonic(), data)
    return data


async def standings_text(token: str, code: str) -> str:
    data = await _get(token, f"/competitions/{code}/standings")
    table = data["standings"][0]["table"]
    lines = [
        f"{'#':>2} {'الفريق':<14} {'لعب':>3} {'ف':>2} {'ت':>2} {'خ':>2} {'فارق':>4} {'نقاط':>4}"
    ]
    for row in table:
        name = (row["team"].get("shortName") or row["team"]["name"])[:14]
        lines.append(
            f"{row['position']:>2} {name:<14} {row['playedGames']:>3} {row['won']:>2} "
            f"{row['draw']:>2} {row['lost']:>2} {row['goalDifference']:>4} {row['points']:>4}"
        )
    body = html.escape("\n".join(lines))
    return f"<b>ترتيب {LEAGUES[code]}</b>\n<pre>{body}</pre>"


async def results_text(token: str, code: str) -> str:
    today = date.today()
    params = {
        "status": "FINISHED",
        "dateFrom": (today - timedelta(days=5)).isoformat(),
        "dateTo": today.isoformat(),
    }
    data = await _get(token, f"/competitions/{code}/matches", params)
    matches = data.get("matches", [])[-10:]
    if not matches:
        return f"لا توجد نتائج حديثة في {LEAGUES[code]}."
    lines = []
    for m in matches:
        home = m["homeTeam"].get("shortName") or m["homeTeam"]["name"]
        away = m["awayTeam"].get("shortName") or m["awayTeam"]["name"]
        score = m["score"]["fullTime"]
        lines.append(f"{home} {score['home']} - {score['away']} {away}")
    body = html.escape("\n".join(lines))
    return f"<b>آخر نتائج {LEAGUES[code]}</b>\n<pre>{body}</pre>"
