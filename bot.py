"""
ربات تلگرام سیگنال‌دهی فیوچرز (نوسان‌گیری) - نسخه پیشرفته
------------------------------------------------------------
ارزها: DOGE, SOL, SHIB, BTC, ETH (فیوچرز Binance، در برابر USDT)
استراتژی: EMA(12/26) برای جهت + EMA200 برای فیلتر روند + RSI(14) + ATR برای پله‌بندی

قابلیت‌ها:
    - ورود در ۳ پله (DCA سبک) برای هر ارز
    - حد سود در ۳ پله (خروج پلکانی سود)
    - حد ضرر در ۳ پله (متناسب با هر پله ورود)
    - ارسال خودکار گزارش کامل هر ۳۰ دقیقه
    - منوی دکمه‌ای (Inline Keyboard) برای دریافت جداگانه‌ی هرکدوم:
        📥 نقاط ورود / 🎯 حد سود / 🛑 حد ضرر / 📊 گزارش کامل / 🔄 بروزرسانی فوری

نصب: pip install -r requirements.txt
قبل از اجرا: توکن بات رو در فایل .env بذار (نمونه در .env.example)

⚠️ این ربات ابزار تحلیل تکنیکال خودکار است، نه توصیه مالی.
⚠️ معاملات فیوچرز با اهرم ریسک بسیار بالایی دارد؛ مدیریت سرمایه با خودته.
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field

import ccxt
import pandas as pd
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")

# --- تنظیمات قابل تغییر ---
SYMBOLS = ["DOGE/USDT", "SOL/USDT", "SHIB/USDT", "BTC/USDT", "ETH/USDT"]
TIMEFRAME = "15m"
CHECK_INTERVAL_SECONDS = 60 * 30      # ارسال خودکار هر ۳۰ دقیقه
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

# فاصله پله‌های ورود (برحسب ضریب ATR) نسبت به قیمت لحظه‌ای
# پله‌ها نزدیک به هم هستن چون در تایم‌فریم ۱۵ دقیقه نوسان‌گیری می‌کنیم؛
# فاصله زیاد یعنی یا پله دوم/سوم هیچ‌وقت پر نمی‌شه، یا وقتی پر بشه دیگه روند عوض شده
ENTRY_LADDER_ATR = [0.0, 0.35, 0.75]

# فاصله حد ضرر هر پله (برحسب ضریب ATR) - نسبت به همون پله ورود
# پله اول (ورود اصلی) تنگ‌تره چون بیشترین حجم رو اونجا می‌ذاری؛
# پله‌های بعدی که میانگین رو پایین/بالا می‌برن، کمی بازتر هستن
SL_LADDER_ATR = [1.0, 1.25, 1.5]

# فاصله حد سود هر پله (برحسب ضریب ATR) - نسبت به قیمت لحظه‌ای
# نسبت ریسک‌به‌ریوارد پله اول ~1:1.2 ، پله دوم ~1:2 ، پله سوم ~1:3
SL_BASE = SL_LADDER_ATR[0]
TP_LADDER_ATR = [SL_BASE * 1.2, SL_BASE * 2.0, SL_BASE * 3.0]

exchange = ccxt.binanceusdm()


@dataclass
class TradePlan:
    symbol: str
    direction: str          # "LONG" یا "SHORT"
    trend: str               # "صعودی" یا "نزولی"
    rsi: float
    entries: list = field(default_factory=list)
    stop_losses: list = field(default_factory=list)
    take_profits: list = field(default_factory=list)


# آخرین پلن محاسبه‌شده برای هر ارز (برای پاسخ به دکمه‌های منو)
last_plans: dict[str, TradePlan] = {}
subscribed_chat_ids: set[int] = set()


def fetch_ohlcv(symbol: str, timeframe: str = TIMEFRAME, limit: int = 250) -> pd.DataFrame:
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


def generate_trade_plan(symbol: str) -> TradePlan | None:
    df = fetch_ohlcv(symbol)

    ema_fast = EMAIndicator(df["close"], window=12).ema_indicator()
    ema_slow = EMAIndicator(df["close"], window=26).ema_indicator()
    ema_trend = EMAIndicator(df["close"], window=200).ema_indicator()
    rsi_series = RSIIndicator(df["close"], window=14).rsi()
    atr_series = AverageTrueRange(df["high"], df["low"], df["close"], window=14).average_true_range()

    price = df["close"].iloc[-1]
    last_fast, last_slow = ema_fast.iloc[-1], ema_slow.iloc[-1]
    last_rsi = rsi_series.iloc[-1]
    last_atr = atr_series.iloc[-1]
    last_trend_ema = ema_trend.iloc[-1]

    price_above_trend = price > last_trend_ema
    trend_label = "صعودی" if price_above_trend else "نزولی"

    if last_fast > last_slow and price_above_trend and last_rsi < RSI_OVERBOUGHT:
        direction = "LONG"
    elif last_fast < last_slow and not price_above_trend and last_rsi > RSI_OVERSOLD:
        direction = "SHORT"
    else:
        return None  # روند و مومنتوم هم‌جهت نیستن، پلن واضحی وجود نداره

    entries, stop_losses, take_profits = [], [], []

    for atr_mult in ENTRY_LADDER_ATR:
        entry_price = price - (last_atr * atr_mult) if direction == "LONG" else price + (last_atr * atr_mult)
        entries.append(entry_price)

    for i, atr_mult in enumerate(SL_LADDER_ATR):
        base_entry = entries[i]
        sl_price = base_entry - (last_atr * atr_mult) if direction == "LONG" else base_entry + (last_atr * atr_mult)
        stop_losses.append(sl_price)

    for atr_mult in TP_LADDER_ATR:
        tp_price = price + (last_atr * atr_mult) if direction == "LONG" else price - (last_atr * atr_mult)
        take_profits.append(tp_price)

    return TradePlan(
        symbol=symbol,
        direction=direction,
        trend=trend_label,
        rsi=last_rsi,
        entries=entries,
        stop_losses=stop_losses,
        take_profits=take_profits,
    )


def refresh_all_plans() -> dict[str, TradePlan]:
    for symbol in SYMBOLS:
        try:
            plan = generate_trade_plan(symbol)
            if plan:
                last_plans[symbol] = plan
            elif symbol in last_plans:
                del last_plans[symbol]  # دیگه سیگنال معتبری نیست، پاکش کن
        except Exception as e:
            logger.error(f"خطا برای {symbol}: {e}")
    return last_plans


# ---------- قالب‌بندی پیام‌ها ----------

def fmt_price(p: float) -> str:
    return f"{p:,.6f}"


def format_full(plan: TradePlan) -> str:
    emoji = "🟢" if plan.direction == "LONG" else "🔴"
    entries_txt = "\n".join(f"   پله {i+1}: {fmt_price(p)}" for i, p in enumerate(plan.entries))
    sl_txt = "\n".join(f"   پله {i+1}: {fmt_price(p)}" for i, p in enumerate(plan.stop_losses))
    tp_txt = "\n".join(f"   پله {i+1}: {fmt_price(p)}" for i, p in enumerate(plan.take_profits))
    return (
        f"{emoji} {plan.symbol} — {plan.direction}\n"
        f"روند (EMA200): {plan.trend} | RSI: {plan.rsi:.1f}\n\n"
        f"📥 نقاط ورود (۳ پله):\n{entries_txt}\n\n"
        f"🎯 حد سود (۳ پله):\n{tp_txt}\n\n"
        f"🛑 حد ضرر (۳ پله):\n{sl_txt}\n\n"
        f"💡 بعد از رسیدن به حد سود پله ۱، حد ضررت رو به نقطه ورود (سربه‌سر) منتقل کن "
        f"تا ریسک باقی پوزیشن صفر بشه."
    )


def format_section(plans: dict[str, TradePlan], section: str, title: str) -> str:
    if not plans:
        return "فعلاً هیچ سیگنال واضحی روی ارزهای تحت رصد نیست. کمی بعد دوباره چک کن یا از 🔄 بروزرسانی فوری استفاده کن."

    lines = [f"{title}\n"]
    for plan in plans.values():
        emoji = "🟢" if plan.direction == "LONG" else "🔴"
        values = getattr(plan, section)
        vals_txt = " | ".join(f"پله{i+1}: {fmt_price(v)}" for i, v in enumerate(values))
        lines.append(f"{emoji} {plan.symbol} ({plan.direction}): {vals_txt}")
    return "\n".join(lines)


# ---------- منو (دکمه‌های شیشه‌ای) ----------

def build_menu() -> InlineKeyboardMarkup:
    keyboard = [
        [InlineKeyboardButton("📥 نقاط ورود", callback_data="entries"),
         InlineKeyboardButton("🎯 حد سود", callback_data="take_profits")],
        [InlineKeyboardButton("🛑 حد ضرر", callback_data="stop_losses"),
         InlineKeyboardButton("📊 گزارش کامل", callback_data="full")],
        [InlineKeyboardButton("🔄 بروزرسانی فوری", callback_data="refresh")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subscribed_chat_ids.add(update.effective_chat.id)
    await update.message.reply_text(
        "منوی سیگنال — هرکدوم رو جداگانه بخواه:",
        reply_markup=build_menu(),
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "refresh":
        await query.edit_message_text("⏳ در حال بروزرسانی...")
        plans = refresh_all_plans()
        text = format_section(plans, "entries", "📥 نقاط ورود بروزرسانی‌شده:") if plans else \
            "فعلاً هیچ سیگنال واضحی نیست."
        await query.message.reply_text(text, reply_markup=build_menu())
        return

    plans = last_plans
    if query.data == "entries":
        text = format_section(plans, "entries", "📥 نقاط ورود (۳ پله):")
    elif query.data == "take_profits":
        text = format_section(plans, "take_profits", "🎯 حد سود (۳ پله):")
    elif query.data == "stop_losses":
        text = format_section(plans, "stop_losses", "🛑 حد ضرر (۳ پله):")
    elif query.data == "full":
        if not plans:
            text = "فعلاً هیچ سیگنال واضحی نیست."
        else:
            text = "\n\n".join(format_full(p) for p in plans.values())
    else:
        text = "دستور نامشخص."

    await query.message.reply_text(text, reply_markup=build_menu())


# ---------- ارسال خودکار دوره‌ای ----------

async def auto_report_loop(app: Application):
    while True:
        if subscribed_chat_ids:
            plans = refresh_all_plans()
            if plans:
                text = "🕒 گزارش خودکار (هر ۳۰ دقیقه):\n\n" + "\n\n".join(format_full(p) for p in plans.values())
            else:
                text = "🕒 گزارش خودکار: فعلاً سیگنال واضحی روی هیچ‌کدوم از ارزها نیست."
            for chat_id in subscribed_chat_ids:
                try:
                    await app.bot.send_message(chat_id=chat_id, text=text, reply_markup=build_menu())
                except Exception as e:
                    logger.error(f"ارسال به {chat_id} ناموفق بود: {e}")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


# ---------- دستورات پایه ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subscribed_chat_ids.add(update.effective_chat.id)
    await update.message.reply_text(
        "✅ عضو دریافت سیگنال شدی!\n"
        f"ارزهای تحت رصد: {', '.join(SYMBOLS)}\n"
        "هر ۳۰ دقیقه گزارش کامل (ورود/سود/ضرر در ۳ پله) خودکار برات می‌فرستم.\n"
        "برای دریافت جداگانه هرکدوم، از دستور /menu استفاده کن.\n"
        "برای توقف: /stop\n\n"
        "⚠️ این ابزار تحلیل تکنیکاله، نه توصیه مالی. تصمیم و ریسک نهایی با خودته."
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subscribed_chat_ids.discard(update.effective_chat.id)
    await update.message.reply_text("❌ اشتراک قطع شد.")


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"در حال رصد: {', '.join(SYMBOLS)}\n"
        f"تایم‌فریم: {TIMEFRAME}\n"
        f"فاصله گزارش خودکار: هر {CHECK_INTERVAL_SECONDS // 60} دقیقه\n"
        f"تعداد اعضا: {len(subscribed_chat_ids)}\n"
        f"سیگنال‌های فعال الان: {len(last_plans)}"
    )


async def post_init(app: Application):
    asyncio.create_task(auto_report_loop(app))


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN تنظیم نشده! فایل .env رو بساز و توکن رو بذار توش.")

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("ربات در حال اجراست...")
    app.run_polling()


if __name__ == "__main__":
    main()
