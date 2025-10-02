import aiohttp
from settings import settings

CG = "https://api.coingecko.com/api/v3/simple/price"
MAP = {"BTC": "bitcoin", "LTC": "litecoin", "DOGE": "dogecoin"}

async def get_prices() -> dict[str, float]:
    ids = ",".join([MAP[c] for c in settings.coins if c in MAP])
    if not ids:
        return {}
    params = {"ids": ids, "vs_currencies": settings.fiat.lower()}
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
        async with s.get(CG, params=params) as r:
            r.raise_for_status()
            j = await r.json()
    out = {}
    for c, cg in MAP.items():
        if c in settings.coins and j.get(cg, {}).get(settings.fiat.lower()):
            out[c] = float(j[cg][settings.fiat.lower()])
    return out
