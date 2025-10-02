import time
from dataclasses import dataclass
from typing import List, Dict
from settings import settings
from storage import kv_get, kv_set

@dataclass
class Event:
    kind: str
    msg: str

def _mins_since(ts: int) -> float:
    return (time.time() - ts) / 60 if ts else float("inf")

async def check_offline(workers: List[Dict]) -> List[Event]:
    ev = []
    for w in workers:
        if _mins_since(w.get("last_active") or 0) > settings.alert_offline_min:
            ev.append(Event("offline", f"⚠️ {w.get('alias') or w.get('name')} офлайн > {settings.alert_offline_min} мин"))
    return ev

async def check_payouts(latest: list[dict]) -> List[Event]:
    if not latest:
        return []
    last_id = await kv_get("last_payout_ts")
    newest = str(latest[0].get("time") or "")
    if newest and newest != last_id:
        await kv_set("last_payout_ts", newest)
        amt = latest[0].get("amount"); coin = latest[0].get("coin")
        return [Event("payout", f"✅ Выплата: {amt} {coin}")]
    return []
