from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import List, Dict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler

from settings import settings
from trustpool_client import TrustpoolClient
from prices import get_prices
from alerts import check_offline, check_payouts
from storage import init_db

MSK = ZoneInfo("Europe/Moscow")
client = TrustpoolClient()

# ======================= helpers =======================

def _fmt_ts(ts: int, tz: ZoneInfo = MSK) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, tz=tz).strftime("%Y-%m-%d %H:%M %Z")

def _msk_midnight_to_now_utc_range() -> tuple[int, int]:
    now_utc = datetime.now(timezone.utc)
    now_msk = now_utc.astimezone(MSK)
    start_msk = datetime(now_msk.year, now_msk.month, now_msk.day, 0, 0, 0, tzinfo=MSK)
    start_utc = start_msk.astimezone(timezone.utc)
    return int(start_utc.timestamp()), int(now_utc.timestamp())

async def _sum_profit_between(coin: str, start_ts: int, end_ts: int) -> float:
    """
    Суммируем прибыль coin по точкам почасового графика в интервале [start_ts, end_ts].
    Доп. защита: если time в миллисекундах — приводим к секундам.
    """
    data = await client.profit_chart(coin=coin, range_type="hour", size=24 * 14)
    total = 0.0
    for p in data:
        if not isinstance(p, dict):
            continue
        ts = int(p.get("time", 0) or 0)
        if ts > 2_000_000_000_000:
            ts //= 1000
        elif ts > 50_000_000_000:
            ts //= 1000
        if start_ts <= ts <= end_ts:
            try:
                total += float(p.get("profit", 0.0) or 0.0)
            except Exception:
                pass
    return total

async def _broadcast(app: Application, text: str):
    if not settings.tg_chats:
        return
    for chat_id in settings.tg_chats:
        try:
            await app.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            print(f"Send to {chat_id} failed: {e}")

def _fiat_total(amounts: Dict[str, float], prices: Dict[str, float]) -> float:
    if not isinstance(amounts, dict) or not isinstance(prices, dict):
        return 0.0
    total = 0.0
    for c in settings.coins:
        a = float(amounts.get(c, 0.0) or 0.0)
        p = float(prices.get(c, 0.0) or 0.0)
        total += a * p
    return total

def _price(prices, coin: str) -> float:
    # безопасно берём цену монеты
    try:
        return float((prices or {}).get(coin, 0.0) or 0.0)
    except Exception:
        return 0.0

def _main_menu_keyboard() -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton("📅 Сегодня (МСК)", callback_data="today_msk"),
            InlineKeyboardButton("💸 С последней выплаты", callback_data="today_since"),
        ],
        [InlineKeyboardButton("⚙️ Хешрейт", callback_data="hashrate")],
        [
            InlineKeyboardButton("🧾 Выплаты: BTC", callback_data="payouts_BTC"),
            InlineKeyboardButton("🧾 Выплаты: LTC+DOGE", callback_data="payouts_LTC"),
            InlineKeyboardButton("🧾 Выплаты: ALL", callback_data="payouts_ALL"),
        ],
    ]
    return InlineKeyboardMarkup(kb)

# ======================= command handlers =======================

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "Привет! Я Trustbot. Выбирай действие кнопками ниже.\n\n"
        "— «Сегодня (МСК)» — доход с 00:00 МСК до текущего момента\n"
        "— «С последней выплаты» — доход с момента последней выплаты по каждой монете\n"
        "— «Выплаты» — последние транзакции по BTC/LTC/ALL\n"
        "— «Хешрейт» — состояние воркеров"
    )
    await update.effective_chat.send_message(text, reply_markup=_main_menu_keyboard())

async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _handle_today_msk(update, ctx)

async def cmd_hashrate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await _handle_hashrate(update, ctx)

async def cmd_payouts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args or []
    mode = (args[0].upper() if args else "ALL")
    await _handle_payouts_generic(update, ctx, mode)

# ======================= callback handlers =======================

async def cb_router(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    if not q or not q.data:
        return
    data = q.data
    try:
        if data == "today_msk":
            await _handle_today_msk(update, ctx, edit=True)
        elif data == "today_since":
            await _handle_today_since(update, ctx, edit=True)
        elif data == "hashrate":
            await _handle_hashrate(update, ctx, edit=True)
        elif data.startswith("payouts_"):
            _, coin = data.split("_", 1)
            await _handle_payouts_generic(update, ctx, coin, edit=True)
        else:
            await q.answer("Неизвестное действие", show_alert=False)
            return
        await q.answer()
    except Exception as e:
        try:
            await q.answer(f"Ошибка: {e}", show_alert=True)
        except Exception:
            pass

# ======================= core UI actions =======================

async def _handle_today_msk(update: Update, ctx: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    start_ts, end_ts = _msk_midnight_to_now_utc_range()
    prices_map = await get_prices()
    if not isinstance(prices_map, dict):
        prices_map = {}

    msk_sum_by_coin: Dict[str, float] = {}
    for coin in settings.coins:
        try:
            msk_sum_by_coin[coin] = await _sum_profit_between(coin, start_ts, end_ts)
        except Exception:
            msk_sum_by_coin[coin] = 0.0

    now_msk = datetime.now(MSK)
    start_msk = datetime(now_msk.year, now_msk.month, now_msk.day, 0, 0, 0, tzinfo=MSK)
    lines = [f"📅 Доход за сегодня (МСК)\nс {start_msk.strftime('%H:%M %Z')} по {now_msk.strftime('%H:%M %Z')}:"]

    for c in settings.coins:
        amt = float(msk_sum_by_coin.get(c, 0.0) or 0.0)
        fiat = amt * _price(prices_map, c)
        lines.append(f"• {c}: {amt:.8f} ≈ {fiat:.2f} {settings.fiat}")

    lines.append(f"Итого ≈ {_fiat_total(msk_sum_by_coin, prices_map):.2f} {settings.fiat}")
    text = "\n".join(lines)

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=_main_menu_keyboard())
    else:
        await update.effective_chat.send_message(text, reply_markup=_main_menu_keyboard())

async def _handle_today_since(update: Update, ctx: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    now_utc_ts = int(datetime.now(timezone.utc).timestamp())
    prices_map = await get_prices()
    if not isinstance(prices_map, dict):
        prices_map = {}

    last_payout_ts_by_coin: Dict[str, int] = {}
    for coin in settings.coins:
        try:
            pays = await client.payouts_list(coin, limit=1)
        except Exception:
            pays = []
        if pays:
            last_payout_ts_by_coin[coin] = int(pays[0].get("time", 0))

    since_pay_sum_by_coin: Dict[str, float] = {}
    for coin in settings.coins:
        lp_ts = int(last_payout_ts_by_coin.get(coin, 0) or 0)
        if lp_ts > 0:
            try:
                since_pay_sum_by_coin[coin] = await _sum_profit_between(coin, lp_ts, now_utc_ts)
            except Exception:
                since_pay_sum_by_coin[coin] = 0.0
        else:
            since_pay_sum_by_coin[coin] = 0.0

    lines = ["💸 Доход с момента последней выплаты:"]
    for c in settings.coins:
        amt = float(since_pay_sum_by_coin.get(c, 0.0) or 0.0)
        fiat = amt * _price(prices_map, c)
        lp = last_payout_ts_by_coin.get(c)
        lp_str = _fmt_ts(lp, tz=MSK) if lp else "—"
        lines.append(f"• {c}: {amt:.8f} ≈ {fiat:.2f} {settings.fiat} (последняя выплата: {lp_str})")

    lines.append(f"Итого ≈ {_fiat_total(since_pay_sum_by_coin, prices_map):.2f} {settings.fiat}")
    text = "\n".join(lines)

    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=_main_menu_keyboard())
    else:
        await update.effective_chat.send_message(text, reply_markup=_main_menu_keyboard())

async def _handle_hashrate(update: Update, ctx: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    ws = await client.worker_stats()
    on = sum(1 for w in ws if (w.get("status") or "").lower() == "active")
    off = len(ws) - on
    lines = [f"⚙️ Воркеры: online {on}, offline {off}"]
    for w in ws:
        lines.append(f"• {w['alias']}: {w['recent_hashrate']} (24h {w['hashrate_1day']}) — {w['coin']}")
    text = "\n".join(lines)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=_main_menu_keyboard())
    else:
        await update.effective_chat.send_message(text, reply_markup=_main_menu_keyboard())

async def _handle_payouts_generic(update: Update, ctx: ContextTypes.DEFAULT_TYPE, mode: str, edit: bool = False):
    mode = (mode or "ALL").upper()
    if mode == "LTC":
        coins: List[str] = ["LTC", "DOGE"]
    elif mode in {"BTC", "DOGE"}:
        coins = [mode]
    else:
        coins = list(settings.coins)

    lines: List[str] = []
    for coin in coins:
        try:
            pts = await client.payouts_list(coin, limit=10)
        except Exception:
            pts = []
        lines.append(f"🧾 Последние выплаты {coin}:")
        if not pts:
            lines.append("• нет данных")
        else:
            for p in pts:
                when = _fmt_ts(int(p.get("time", 0)), tz=MSK)
                lines.append(f"• {when}: {p.get('amount', 0)} {coin}")
        lines.append("")
    text = "\n".join(lines).strip()
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=_main_menu_keyboard())
    else:
        await update.effective_chat.send_message(text, reply_markup=_main_menu_keyboard())

# ======================= alerts loop =======================

async def poll_and_alert(context: ContextTypes.DEFAULT_TYPE):
    app = context.application
    ws = await client.worker_stats()

    events = []
    if settings.only_offline_alerts:
        events += await check_offline(ws)
        # выплаты (оставляем, можно вырубить — закомментировать блок)
        latest_payouts = []
        for c in settings.coins:
            try:
                p = await client.payouts(c)
            except Exception:
                p = []
            if p:
                latest_payouts = p
                break
        events += await check_payouts(latest_payouts)
    else:
        events += await check_offline(ws)

    if events:
        text = "🚨 Алерты:\n" + "\n".join(f"• {e.msg}" for e in events)
        await _broadcast(app, text)

# ======================= lifecycle =======================

async def on_startup(app: Application):
    await init_db()
    app.job_queue.run_repeating(poll_and_alert, interval=120, first=10, name="poll_and_alert")

def main():
    app = (
        Application.builder()
        .token(settings.tg_token)
        .post_init(on_startup)
        .build()
    )
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("hashrate", cmd_hashrate))
    app.add_handler(CommandHandler("payouts", cmd_payouts))
    app.add_handler(CallbackQueryHandler(cb_router))
    app.run_polling()

if __name__ == "__main__":
    main()
