from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import List, Dict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)

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
    Используем запас 10 суток (size=240).
    """
    data = await client.profit_chart(coin=coin, range_type="hour", size=240)
    return sum(p["profit"] for p in data if start_ts <= int(p["time"]) <= end_ts)


async def _broadcast(app: Application, text: str):
    # Рассылка во все TELEGRAM_CHAT_IDS
    if not settings.tg_chats:
        return
    for chat_id in settings.tg_chats:
        try:
            await app.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            print(f"Send to {chat_id} failed: {e}")


def _main_menu_keyboard() -> InlineKeyboardMarkup:
    kb = [
        [
            InlineKeyboardButton("📅 Сегодня (МСК)", callback_data="today_msk"),
            InlineKeyboardButton("💸 С последней выплаты", callback_data="today_since"),
        ],
        [
            InlineKeyboardButton("⚙️ Хешрейт", callback_data="hashrate"),
        ],
        [
            InlineKeyboardButton("🧾 Выплаты: BTC", callback_data="payouts_BTC"),
            InlineKeyboardButton("🧾 Выплаты: LTC", callback_data="payouts_LTC"),
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
    # совместимость: если пользователь набирает /today, покажем меню today
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
        # не роняем бота на ошибке
        try:
            await q.answer(f"Ошибка: {e}", show_alert=True)
        except Exception:
            pass


# ======================= core UI actions =======================

async def _handle_today_msk(update: Update, ctx: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    """Доход за сегодня по МСК (с 00:00 МСК до сейчас) с суммой по монетам в фиат."""
    start_ts, end_ts = _msk_midnight_to_now_utc_range()
    px = await get_prices()

    msk_sum_by_coin: Dict[str, float] = {}
    for coin in settings.coins:
        msk_sum_by_coin[coin] = await _sum_profit_between(coin, start_ts, end_ts)

    def _fiat_total(d: Dict[str, float]) -> float:
        return sum((d.get(c, 0.0) * px.get(c, 0.0)) for c in settings.coins)

    now_msk = datetime.now(MSK)
    start_msk = datetime(now_msk.year, now_msk.month, now_msk.day, 0, 0, 0, tzinfo=MSK)
    lines = [
        f"📅 Доход за сегодня (МСК)\nс {start_msk.strftime('%H:%M %Z')} по {now_msk.strftime('%H:%M %Z')}:"
    ]
    for c in settings.coins:
        amt = msk_sum_by_coin[c]
        fiat = amt * px.get(c, 0.0)
        lines.append(f"• {c}: {amt:.8f} ≈ {fiat:.2f} {settings.fiat}")
    lines.append(f"Итого ≈ {_fiat_total(msk_sum_by_coin):.2f} {settings.fiat}")

    text = "\n".join(lines)
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, reply_markup=_main_menu_keyboard())
    else:
        await update.effective_chat.send_message(text, reply_markup=_main_menu_keyboard())


async def _handle_today_since(update: Update, ctx: ContextTypes.DEFAULT_TYPE, edit: bool = False):
    """Доход с момента последней выплаты по каждой монете."""
    now_utc_ts = int(datetime.now(timezone.utc).timestamp())
    px = await get_prices()

    last_payout_ts_by_coin: Dict[str, int] = {}
    for coin in settings.coins:
        pays = await client.payouts_list(coin, limit=1)
        if pays:
            last_payout_ts_by_coin[coin] = int(pays[0]["time"])

    since_pay_sum_by_coin: Dict[str, float] = {}
    for coin in settings.coins:
        lp_ts = last_payout_ts_by_coin.get(coin)
        if lp_ts:
            since_pay_sum_by_coin[coin] = await _sum_profit_between(coin, lp_ts, now_utc_ts)
        else:
            since_pay_sum_by_coin[coin] = 0.0

    def _fiat_total(d: Dict[str, float]) -> float:
        return sum((d.get(c, 0.0) * px.get(c, 0.0)) for c in settings.coins)

    lines = ["💸 Доход с момента последней выплаты:"]
    for c in settings.coins:
        amt = since_pay_sum_by_coin[c]
        fiat = amt * px.get(c, 0.0)
        lp = last_payout_ts_by_coin.get(c)
        lp_str = _fmt_ts(lp, tz=MSK) if lp else "—"
        lines.append(f"• {c}: {amt:.8f} ≈ {fiat:.2f} {settings.fiat} (последняя выплата: {lp_str})")
    lines.append(f"Итого ≈ {_fiat_total(since_pay_sum_by_coin):.2f} {settings.fiat}")

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
    if mode in {"BTC", "LTC", "DOGE"}:
        coins: List[str] = [mode]
    else:
        coins = list(settings.coins)

    lines: List[str] = []
    for coin in coins:
        pts = await client.payouts_list(coin, limit=10)
        lines.append(f"🧾 Последние выплаты {coin}:")
        if not pts:
            lines.append("• нет данных")
        else:
            for p in pts:
                when = _fmt_ts(int(p["time"]), tz=MSK)
                lines.append(f"• {when}: {p['amount']} {coin}")
        lines.append("")  # разделитель

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

        # Выплаты — оставляем; если не нужно, закомментируй следующий блок
        latest_payouts = []
        for c in settings.coins:
            p = await client.payouts(c)
            if p:
                latest_payouts = p
                break
        events += await check_payouts(latest_payouts)
    else:
        # при необходимости можно вернуть другие проверки
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

    # Команды
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("today", cmd_today))
    app.add_handler(CommandHandler("hashrate", cmd_hashrate))
    app.add_handler(CommandHandler("payouts", cmd_payouts))

    # Инлайн-кнопки
    app.add_handler(CallbackQueryHandler(cb_router))

    app.run_polling()


if __name__ == "__main__":
    main()
