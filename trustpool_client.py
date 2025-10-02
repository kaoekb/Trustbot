from __future__ import annotations

import re
from typing import Any, Dict, List

import aiohttp

from settings import settings


def _norm_name(s: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", (s or ""))


def _coin_for_workers(coin: str) -> str:
    # На Trustpool DOGE в воркерах = LTC (мердж-майнинг)
    c = (coin or "").upper()
    return "LTC" if c == "DOGE" else c


class TrustpoolClient:
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

    # -------- сырье --------
    async def home(self, coin: str) -> Dict[str, Any]:
        return await self._get("/observer/home", coin=coin)

    async def workers(self, coin: str, group_id: int = -1, status: str | None = None) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {"coin": coin, "group_id": group_id}
        if status:
            params["status"] = status
        j = await self._get("/observer/worker", **params)
        data = (j.get("data") or {}).get("data") or []
        return data if isinstance(data, list) else []

    async def payouts(self, coin: str) -> List[Dict[str, Any]]:
        j = await self._get("/observer/payment/detail", coin=coin)
        data = (j.get("data") or {}).get("data") or []
        return data if isinstance(data, list) else []

    # -------- удобные методы --------
    async def revenue_24h(self) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for coin in settings.coins:
            try:
                j = await self.home(coin)
                val = (j.get("data") or {}).get("profit_24hour") or "0"
                out[coin] = float(str(val).replace(",", "."))
            except Exception:
                out[coin] = 0.0
        return out

    async def worker_stats(self) -> List[Dict[str, Any]]:
        res: List[Dict[str, Any]] = []
        queried: set[str] = set()

        for coin in settings.coins:
            query_coin = _coin_for_workers(coin)
            if query_coin in queried:
                continue
            queried.add(query_coin)

            lst = await self.workers(coin=query_coin, group_id=-1)
            if not isinstance(lst, list):
                continue

            for w in lst:
                if not isinstance(w, dict):
                    continue
                raw_name = w.get("name") or w.get("worker") or "unknown"
                coin_u = (w.get("coin") or query_coin or "NA").upper()
                nkey = _norm_name(raw_name)
                alias = (
                    settings.worker_alias_scoped.get((coin_u, nkey))
                    or settings.worker_alias_global.get(nkey)
                    or raw_name
                )
                res.append(
                    {
                        "coin": coin_u,   # для мерджа будет "LTC" — это ок
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
        out: List[Dict[str, Any]] = []
        if not isinstance(pts_raw, list):
            return out
        for p in pts_raw[:limit]:
            if not isinstance(p, dict):
                continue
            try:
                out.append(
                    {
                        "time": int(p.get("time") or p.get("timestamp") or 0),
                        "amount": float(str(p.get("amount") or "0").replace(",", ".")),
                        "coin": (p.get("coin") or coin).upper(),
                        "txid": p.get("txid") or p.get("txId") or p.get("hash") or "",
                    }
                )
            except Exception:
                continue
        return out

    async def profit_chart(
        self,
        coin: str,
        range_type: str = "hour",
        size: int = 24 * 14,  # до 14 суток с запасом
    ) -> List[Dict[str, Any]]:
        """
        Возвращает список точек [{"time": <sec>, "profit": <float>}, ...]
        Поддерживает два формата Trustpool:
        A) {"start": <ms|sec>, "data": [<float>, ...]}  — равномерная сетка
        B) {"data": [{"time":..., "profit":...}, ...]}  — явные точки
        Все time нормализуем в СЕКУНДАХ.
        """
        try:
            j = await self._get("/observer/profit/chart", coin=coin, range_type=range_type, size=size)
        except Exception:
            return []

        # достаём payload
        payload = j.get("data") if isinstance(j, dict) else None
        if payload is None:
            return []

        out: List[Dict[str, Any]] = []

        # --- Вариант A: start + data (массив чисел) ---
        start = None
        series = None
        if isinstance(payload, dict):
            start = payload.get("start")
            series = payload.get("data")

        # если это «равномерная сетка»
        if start is not None and isinstance(series, list) and (not series or isinstance(series[0], (int, float, str))):
            # нормализуем start в сек
            try:
                t0 = int(start)
                if t0 > 2_000_000_000_000 or t0 > 50_000_000_000:  # миллисекунды
                    t0 //= 1000
            except Exception:
                t0 = 0

            step = 3600 if str(range_type).lower() == "hour" else 86400
            t = t0
            for v in series:
                try:
                    profit = float(str(v).replace(",", "."))
                except Exception:
                    profit = 0.0
                out.append({"time": t, "profit": profit})
                t += step
            return out

        # --- Вариант B: массив объектов (каждая точка со своим time/profit) ---
        data_list = None
        if isinstance(payload, dict):
            data_list = payload.get("data")
        if not isinstance(data_list, list):
            # иногда сам payload — уже список
            data_list = payload if isinstance(payload, list) else []

        for p in data_list:
            if not isinstance(p, dict):
                continue
            ts_raw = p.get("time") or p.get("ts") or p.get("date") or 0
            val_raw = p.get("profit") or p.get("value") or p.get("amount") or 0
            try:
                ts = int(ts_raw)
                if ts > 2_000_000_000_000 or ts > 50_000_000_000:
                    ts //= 1000  # ms → sec
                profit = float(str(val_raw).replace(",", "."))
                out.append({"time": ts, "profit": profit})
            except Exception:
                continue

        return out

