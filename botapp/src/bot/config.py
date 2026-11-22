import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

DEFAULT_FEEDS = "https://feeds.bbci.co.uk/sport/football/rss.xml"


def _list(name: str, default: str = "") -> list[str]:
    return [x.strip() for x in os.getenv(name, default).split(",") if x.strip()]


@dataclass(frozen=True)
class Settings:
    telegram_token: str
    channel_id: str
    groq_api_key: str
    groq_model: str
    football_token: str
    news_feeds: list[str]
    injury_feeds: list[str]
    transfer_feeds: list[str]
    post_interval_minutes: int
    max_posts_per_run: int


def load_settings() -> Settings:
    missing = [
        n for n in ("TELEGRAM_BOT_TOKEN", "GROQ_API_KEY", "FOOTBALL_DATA_TOKEN") if not os.getenv(n)
    ]
    if missing:
        raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")
    return Settings(
        telegram_token=os.environ["TELEGRAM_BOT_TOKEN"],
        channel_id=os.getenv("CHANNEL_ID", ""),
        groq_api_key=os.environ["GROQ_API_KEY"],
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        football_token=os.environ["FOOTBALL_DATA_TOKEN"],
        news_feeds=_list("NEWS_FEEDS", DEFAULT_FEEDS),
        injury_feeds=_list("INJURY_FEEDS", DEFAULT_FEEDS),
        transfer_feeds=_list("TRANSFER_FEEDS", DEFAULT_FEEDS),
        post_interval_minutes=int(os.getenv("POST_INTERVAL_MINUTES", "30")),
        max_posts_per_run=int(os.getenv("MAX_POSTS_PER_RUN", "3")),
    )
