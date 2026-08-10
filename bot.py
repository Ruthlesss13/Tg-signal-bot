"""
ربات تلگرام سیگنال‌دهی فیوچرز (نوسان‌گیری) - نسخه نهایی
--------------------------------------------------------------------------
ارزها: DOGE, SOL, SHIB, BTC, ETH (فیوچرز Bybit، در برابر USDT)
استراتژی: EMA(12/26) برای جهت + EMA200 برای فیلتر روند + RSI(14) + ATR برای پله‌بندی

ساختار منو:
    منوی اصلی
      ├── 💰 قیمت لحظه‌ای  → نمایش قیمت همه ارزها
      └── 📈 انتخاب ارز    → لیست ۵ ارز
              └── (انتخاب یک ارز) → صفحه‌ی ارز
                      └── 🎯 پیشنهاد لحظه‌ای → تحلیل لانگ/شورت در ۳ پله با حد سود/ضرر

در همه‌ی صفحات دکمه‌ی 🔙 بازگشت وجود داره.
همچنین هر ۱۵ دقیقه گزارش خودکار (قیمت‌ها + سیگنال‌های فعال) برای اعضا ارسال می‌شه.

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
COIN_ICONS = {"DOGE": "🐕", "SOL": "◎", "SHIB": "🦴", "BTC": "₿", "ETH": "Ξ"}
COIN_CODES = ["DOGE", "SOL", "SHIB", "BTC", "ETH"]
SYMBOL_MAP = {code: f"{code}/USDT:USDT" for code in COIN_CODES}  # صرافی Bybit (فیوچرز/سواپ)
SYMBOLS = list(SYMBOL_MAP.values())

TIMEFRAME = "15m"
CHECK_INTERVAL_SECONDS = 60 * 15      # ارسال خودکار هر ۱۵ دقیقه
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

ENTRY_LADDER_ATR = [0.0, 0.35, 0.75]
SL_LADDER_ATR = [1.0, 1.25, 1.5]
SL_BASE = SL_LADDER_ATR[0]
TP_LADDER_ATR = [SL_BASE * 1.2, SL_BASE * 2.0, SL_BASE * 3.0]

exchange = ccxt.bybit({"options": {"defaultType": "swap"}})


@dataclass
class TradePlan:
    symbol: str
    direction: str          # "LONG" یا "SHORT"
    trend: str
    rsi: float
    entries: list = field(default_factory=list)
    stop_losses: list = field(default_factory=list)
    take_profits: list = field(default_factory=list)


last_plans: dict[str, TradePlan] = {}
subscribed_chat_ids: set[int] = set()


# ---------- داده و تحلیل ----------

def fetch_ohlcv(symbol: str, timeframe: str = TIMEFRAME, limit: int = 250) -> pd.DataFrame:
    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
    return df


def fetch_current_prices() -> dict[str, float]:
    prices = {}
    for symbol in SYMBOLS:
        try:
            ticker = exchange.fetch_ticker(symbol)
            prices[symbol] = ticker["last"]
        except Exception as e:
            logger.error(f"خطا در گرفتن قیمت {symbol}: {e}")
    return prices


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
    trend_label = "صعودی 📈" if price_above_trend else "نزولی 📉"

    if last_fast > last_slow and price_above_trend and last_rsi < RSI_OVERBOUGHT:
        direction = "LONG"
    elif last_fast < last_slow and not price_above_trend and last_rsi > RSI_OVERSOLD:
        direction = "SHORT"
    else:
        return None

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
        symbol=symbol, direction=direction, trend=trend_label, rsi=last_rsi,
        entries=entries, stop_losses=stop_losses, take_profits=take_profits,
    )


def refresh_all_plans() -> dict[str, TradePlan]:
    for symbol in SYMBOLS:
        try:
            plan = generate_trade_plan(symbol)
            if plan:
                last_plans[symbol] = plan
            elif symbol in last_plans:
                del last_plans[symbol]
        except Exception as e:
            logger.error(f"خطا برای {symbol}: {e}")
    return last_plans


# ---------- قالب‌بندی پیام‌ها (شیک با مارک‌داون) ----------

def fmt_price(p: float) -> str:
    return f"{p:,.6f}"


def format_prices_pretty(prices: dict[str, float]) -> str:
    if not prices:
        return "⚠️ دریافت قیمت لحظه‌ای الان ممکن نشد. کمی بعد دوباره امتحان کن."
    lines = ["💰 *قیمت لحظه‌ای ارزها*", "━━━━━━━━━━━━━━━"]
    for symbol, price in prices.items():
        code = symbol.split("/")[0]
        icon = COIN_ICONS.get(code, "")
        lines.append(f"{icon}  *{code}*   `{fmt_price(price)}`")
    return "\n".join(lines)


def format_plan_pretty(plan: TradePlan, code: str) -> str:
    icon = COIN_ICONS.get(code, "")
    dir_txt = "🟢 لانگ (خرید)" if plan.direction == "LONG" else "🔴 شورت (فروش)"
    nums = ["1️⃣", "2️⃣", "3️⃣"]

    entries_txt = "\n".join(f"   {nums[i]} `{fmt_price(p)}`" for i, p in enumerate(plan.entries))
    tp_txt = "\n".join(f"   {nums[i]} `{fmt_price(p)}`" for i, p in enumerate(plan.take_profits))
    sl_txt = "\n".join(f"   {nums[i]} `{fmt_price(p)}`" for i, p in enumerate(plan.stop_losses))

    return (
        f"{icon} *{code}/USDT* — {dir_txt}\n"
        f"روند: {plan.trend}  |  RSI: {plan.rsi:.1f}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📥 *نقاط ورود (۳ پله)*\n{entries_txt}\n\n"
        f"🎯 *حد سود (۳ پله)*\n{tp_txt}\n\n"
        f"🛑 *حد ضرر (۳ پله)*\n{sl_txt}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💡 بعد از رسیدن به سود پله ۱، حد ضرر رو به نقطه ورود منتقل کن.\n"
        f"⚠️ ابزار تحلیل تکنیکاله، نه توصیه مالی."
    )


def format_no_signal(code: str) -> str:
    icon = COIN_ICONS.get(code, "")
    return (
        f"{icon} *{code}/USDT*\n\n"
        f"فعلاً سیگنال واضحی نیست — روند اصلی (EMA200) و مومنتوم کوتاه‌مدت هم‌جهت نیستن.\n"
        f"کمی بعد دوباره امتحان کن."
    )


# ---------- منوهای شیشه‌ای ----------

def kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💰 قیمت لحظه‌ای", callback_data="menu_prices")],
        [InlineKeyboardButton("📈 انتخاب ارز", callback_data="menu_coins")],
    ])


def kb_prices() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی", callback_data="menu_prices")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")],
    ])


def kb_coins() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"{COIN_ICONS[c]} {c}", callback_data=f"coin_{c}")] for c in COIN_CODES]
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")])
    return InlineKeyboardMarkup(rows)


def kb_coin_detail(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 پیشنهاد لحظه‌ای", callback_data=f"suggest_{code}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_coins")],
    ])


def kb_suggestion(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی پیشنهاد", callback_data=f"suggest_{code}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"coin_{code}")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")],
    ])


# ---------- هندلر دکمه‌ها ----------

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    subscribed_chat_ids.add(update.effective_chat.id)

    if data == "menu_main":
        await query.edit_message_text(
            "🤖 *منوی اصلی*\nیکی از گزینه‌ها رو انتخاب کن:",
            reply_markup=kb_main(), parse_mode="Markdown",
        )

    elif data == "menu_prices":
        await query.edit_message_text("⏳ در حال دریافت قیمت لحظه‌ای...")
        prices = fetch_current_prices()
        await query.edit_message_text(
            format_prices_pretty(prices), reply_markup=kb_prices(), parse_mode="Markdown",
        )

    elif data == "menu_coins":
        await query.edit_message_text(
            "📈 *انتخاب ارز*\nارز مورد نظرت رو انتخاب کن:",
            reply_markup=kb_coins(), parse_mode="Markdown",
        )

    elif data.startswith("coin_"):
        code = data.split("_", 1)[1]
        icon = COIN_ICONS.get(code, "")
        await query.edit_message_text(
            f"{icon} *{code}/USDT*\nچی می‌خوای ببینی؟",
            reply_markup=kb_coin_detail(code), parse_mode="Markdown",
        )

    elif data.startswith("suggest_"):
        code = data.split("_", 1)[1]
        await query.edit_message_text("⏳ در حال تحلیل بازار...")
        symbol = SYMBOL_MAP.get(code)
        try:
            plan = generate_trade_plan(symbol)
        except Exception as e:
            logger.error(f"خطا در تحلیل {symbol}: {e}")
            plan = None
        text = format_plan_pretty(plan, code) if plan else format_no_signal(code)
        await query.edit_message_text(text, reply_markup=kb_suggestion(code), parse_mode="Markdown")


# ---------- ارسال خودکار دوره‌ای ----------

async def auto_report_loop(app: Application):
    while True:
        if subscribed_chat_ids:
            prices = fetch_current_prices()
            plans = refresh_all_plans()

            text = f"🕒 *گزارش خودکار* (هر ۱۵ دقیقه)\n\n{format_prices_pretty(prices)}\n\n"
            if plans:
                text += "\n\n".join(format_plan_pretty(p, p.symbol.split('/')[0]) for p in plans.values())
            else:
                text += "فعلاً سیگنال واضحی (لانگ/شورت) روی هیچ‌کدوم از ارزها نیست."

            for chat_id in list(subscribed_chat_ids):
                try:
                    await app.bot.send_message(
                        chat_id=chat_id, text=text, reply_markup=kb_main(), parse_mode="Markdown",
                    )
                except Exception as e:
                    logger.error(f"ارسال به {chat_id} ناموفق بود: {e}")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


# ---------- دستورات پایه ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subscribed_chat_ids.add(update.effective_chat.id)
    await update.message.reply_text(
        "✅ *خوش اومدی!*\n\n"
        "من هر ۱۵ دقیقه قیمت لحظه‌ای و سیگنال‌های فعال رو برات می‌فرستم.\n"
        "برای بررسی دستی هر ارز، از منوی زیر استفاده کن 👇\n\n"
        "برای توقف اشتراک: /stop\n\n"
        "⚠️ ابزار تحلیل تکنیکاله، نه توصیه مالی. تصمیم و ریسک نهایی با خودته.",
        reply_markup=kb_main(), parse_mode="Markdown",
    )


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subscribed_chat_ids.discard(update.effective_chat.id)
    await update.message.reply_text("❌ اشتراک قطع شد.")


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    subscribed_chat_ids.add(update.effective_chat.id)
    await update.message.reply_text(
        "🤖 *منوی اصلی*\nیکی از گزینه‌ها رو انتخاب کن:",
        reply_markup=kb_main(), parse_mode="Markdown",
    )


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        f"در حال رصد: {', '.join(COIN_CODES)}\n"
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
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("ربات در حال اجراست...")
    app.run_polling()


if __name__ == "__main__":
    main()
