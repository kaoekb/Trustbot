from datetime import datetime, timezone
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from settings import settings
from trustpool_client import TrustpoolClient
from prices import get_prices
from alerts import check_offline, check_payouts
from storage import init_db

client = TrustpoolClient()

# ---------- helpers ----------
def _fmt_ts(ts: int) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

async def _broadcast(app: Application, text: str):
    # Рассылка во все TELEGRAM_CHAT_IDS
    if not settings.tg_chats:
        return
    for chat_id in settings.tg_chats:
        try:
            await app.bot.send_message(chat_id=chat_id, text=text)
        except Exception as e:
            print(f"Send to {chat_id} failed: {e}")

# ---------- commands ----------
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "Привет! Я Trustbot.\n\n"
        "Команды:\n"
        "• /today — доход за 24 ч\n"
        "• /hashrate — состояние воркеров\n"
        "• /payouts <BTC|LTC|DOGE> — последние выплаты\n"
    )
    await update.effective_chat.send_message(text)

async def cmd_today(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    revenue = await client.revenue_24h()
    px = await get_prices()
    lines = ["📊 Доход за 24 ч:"]
    total = 0.0
    for c, v in revenue.items():
        fiat = v * px.get(c, 0)
        total += fiat
        lines.append(f"• {c}: {v:.8f} ≈ {fiat:.2f} {settings.fiat}")
    lines.append(f"— — —\nИтого ≈ {total:.2f} {settings.fiat}")
    await update.effective_chat.send_message("\n".join(lines))

async def cmd_hashrate(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ws = await client.worker_stats()
    on = sum(1 for w in ws if (w.get("status") or "").lower() == "active")
    off = len(ws) - on
    lines = [f"⚙️ Воркеры: online {on}, offline {off}"]
    for w in ws:
        lines.append(f"• {w['alias']}: {w['recent_hashrate']} (24h {w['hashrate_1day']}) — {w['coin']}")
    await update.effective_chat.send_message("\n".join(lines))

async def cmd_payouts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    args = ctx.args or []
    coin = (args[0].upper() if args else (settings.coins[0] if settings.coins else "BTC"))
    pts = await client.payouts_list(coin, limit=10)
    if not pts:
        return await update.effective_chat.send_message(f"Нет выплат по {coin}.")
    lines = [f"Последние выплаты {coin}:"]
    for p in pts[:10]:
        when = _fmt_ts(p["time"])
        amt = p["amount"]
        lines.append(f"• {when}: {amt} {coin}")
    await update.effective_chat.send_message("\n".join(lines))

# ---------- alerts ----------
async def poll_and_alert(context: ContextTypes.DEFAULT_TYPE):
    app = context.application
    ws = await client.worker_stats()

    events = []
    # Только офлайн — если включен флаг
    if settings.only_offline_alerts:
        events += await check_offline(ws)

        # Выплаты — оставляем (если не нужно, закомментируй блок ниже)
        latest_payouts = []
        for c in settings.coins:
            p = await client.payouts(c)
            if p:
                latest_payouts = p
                break
        events += await check_payouts(latest_payouts)
    else:
        # (опционально можно вернуть другие проверки)
        events += await check_offline(ws)

    if events:
        text = "🚨 Алерты:\n" + "\n".join(f"• {e.msg}" for e in events)
        await _broadcast(app, text)

# ---------- lifecycle ----------
async def on_startup(app: Application):
    await init_db()
    # опрос раз в 2 минуты
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
    app.run_polling()

if __name__ == "__main__":
    main()
