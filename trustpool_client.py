from __future__ import annotations

import re
from typing import Any, Dict, List

import aiohttp

from settings import settings


def _norm_name(s: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", (s or ""))


class TrustpoolClient:
    """
    Watcher API:
      /observer/home?coin=BTC
      /observer/worker?coin=BTC&group_id=-1
      /observer/payment/detail?coin=BTC
      /observer/profit/chart?coin=BTC&range_type=hour&size=168
    """

    def __init__(self, *, timeout_sec: int = 20):
        self.base = settings.base
        self.params_base = {"access_key": settings.access_key}
        self.timeout = aiohttp.ClientTimeout(total=timeout_sec)
        self.headers = {"Accept": "application/json"}

    async def _get(self, path: str, **params) -> Dict[str, Any]:
        url = f"{self.base}{path}"
        q = {**self.params_base, **params}
        async with aiohttp.ClientSession(timeout=self.timeout) as s:
            async with s.get(url, params=q, headers=self.headers) as r:
                r.raise_for_status()
                return await r.json()

    async def home(self, coin: str) -> Dict[str, Any]:
        return await self._get("/observer/home", coin=coin)

    async def workers(self, coin: str, group_id: int = -1, status: str | None = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"coin": coin, "group_id": group_id}
        if status:
            params["status"] = status
        j = await self._get("/observer/worker", **params)
        return (j.get("data") or {}).get("data") or []

    async def payouts(self, coin: str) -> List[Dict[str, Any]]:
        j = await self._get("/observer/payment/detail", coin=coin)
        return (j.get("data") or {}).get("data") or []

    async def revenue_24h(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for coin in settings.coins:
            j = await self.home(coin)
            val = (j.get("data") or {}).get("profit_24hour") or "0"
            try:
                out[coin] = float(str(val).replace(",", "."))
            except Exception:
                out[coin] = 0.0
        return out

    async def worker_stats(self) -> List[Dict[str, Any]]:
        res: List[Dict[str, Any]] = []
        for coin in settings.coins:
            lst = await self.workers(coin=coin, group_id=-1)
            for w in lst:
                raw_name = w.get("name") or w.get("worker") or "unknown"
                coin_u = (w.get("coin") or coin or "NA").upper()
                nkey = _norm_name(raw_name)
                alias = (
                    settings.worker_alias_scoped.get((coin_u, nkey))
                    or settings.worker_alias_global.get(nkey)
                    or raw_name
                )
                res.append(
                    {
                        "coin": coin_u,
                        "name": raw_name,
                        "alias": alias,
                        "last_active": int(w.get("last_active") or 0),
                        "status": w.get("status") or "unknown",
                        "recent_hashrate": w.get("recent_hashrate") or "0",
                        "hashrate_10min": w.get("hashrate_10min") or "0",
                        "hashrate_1hour": w.get("hashrate_1hour") or "0",
                        "hashrate_1day": w.get("hashrate_1day") or "0",
                        "reject_rate": w.get("reject_rate") or "0",
                    }
                )
        return res

    async def payouts_list(self, coin: str, limit: int = 10) -> List[Dict[str, Any]]:
        pts_raw = await self.payouts(coin)
        pts_raw = pts_raw[:limit]
        out: List[Dict[str, Any]] = []
        for p in pts_raw:
            try:
                out.append(
                    {
                        "time": int(p.get("time") or p.get("timestamp") or 0),
                        "amount": float(str(p.get("amount") or "0").replace(",", ".")),
                        "coin": p.get("coin") or coin,
                        "txid": p.get("txid") or p.get("txId") or p.get("hash") or "",
                    }
                )
            except Exception:
                continue
        return out

    async def profit_chart(self, coin: str, range_type: str = "hour", size: int = 24 * 7) -> List[Dict[str, Any]]:
        j = await self._get("/observer/profit/chart", coin=coin, range_type=range_type, size=size)
        data = (j.get("data") or {}).get("data") or j.get("data") or []
        out: List[Dict[str, Any]] = []
        for p in data:
            ts = p.get("time") or p.get("ts") or p.get("date") or 0
            val = p.get("profit") or p.get("value") or p.get("amount") or 0
            try:
                out.append({"time": int(ts), "profit": float(str(val).replace(",", "."))})
            except Exception:
                pass
        return out
