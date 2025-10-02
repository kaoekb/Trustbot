from __future__ import annotations

import os
import re
from typing import Dict, Tuple, List

from dotenv import load_dotenv
from pydantic import BaseModel, Field, field_validator

load_dotenv()


def _normalize_key(s: str | None) -> str:
    """Заменяем всё, кроме [A-Za-z0-9_], на '_'."""
    return re.sub(r"[^A-Za-z0-9_]", "_", (s or ""))


class Settings(BaseModel):
    # Telegram
    tg_token: str = Field(default_factory=lambda: os.getenv("TELEGRAM_TOKEN", ""))
    tg_chats: List[int] = Field(
        default_factory=lambda: [
            int(x.strip()) for x in os.getenv("TELEGRAM_CHAT_IDS", "").split(",") if x.strip().isdigit()
        ]
    )

    # Trustpool Watcher API
    base: str = Field(default_factory=lambda: os.getenv("TRUSTPOOL_BASE", "https://trustpool.ru/res/saas").rstrip("/"))
    access_key: str = Field(default_factory=lambda: os.getenv("TRUSTPOOL_ACCESS_KEY", ""))

    # Business
    coins: List[str] = Field(default_factory=lambda: [c.strip().upper() for c in os.getenv("COINS", "BTC").split(",") if c.strip()])
    fiat: str = Field(default_factory=lambda: os.getenv("FIAT", "USD").upper())

    # Alerts
    alert_offline_min: int = Field(default_factory=lambda: int(os.getenv("ALERT_OFFLINE_MINUTES", "10")))
    alert_drop_pct: float = Field(default_factory=lambda: float(os.getenv("ALERT_HASHRATE_DROP_PCT", "35")))
    alert_min_daily_usd: float = Field(default_factory=lambda: float(os.getenv("ALERT_MIN_DAILY_USD", "0")))
    only_offline_alerts: bool = Field(default_factory=lambda: os.getenv("ONLY_OFFLINE_ALERTS", "false").lower() in {"1","true","yes"})

    # Алиасы
    worker_alias_scoped: Dict[Tuple[str, str], str] = Field(default_factory=dict)  # (COIN, normalized_name) -> alias
    worker_alias_global: Dict[str, str] = Field(default_factory=dict)              # normalized_name -> alias

    @field_validator("coins")
    @classmethod
    def _non_empty_coins(cls, v: List[str]) -> List[str]:
        return v or ["BTC"]

    @classmethod
    def build_alias_maps(cls) -> tuple[Dict[Tuple[str, str], str], Dict[str, str]]:
        scoped: Dict[Tuple[str, str], str] = {}
        global_: Dict[str, str] = {}
        for k, v in os.environ.items():
            if not k.startswith("WORKER_ALIAS_"):
                continue
            tail = k[len("WORKER_ALIAS_"):]
            parts = tail.split("_", 1)
            if len(parts) == 2 and parts[0].upper() in {"BTC", "LTC", "DOGE"}:
                coin = parts[0].upper()
                name_norm = _normalize_key(parts[1])
                scoped[(coin, name_norm)] = v
            else:
                name_norm = _normalize_key(tail)
                global_[name_norm] = v
        return scoped, global_

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        scoped, global_ = cls.build_alias_maps()
        s.worker_alias_scoped = scoped
        s.worker_alias_global = global_
        return s


settings = Settings.load()
