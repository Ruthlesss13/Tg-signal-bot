"""
ربات تلگرام سیگنال‌دهی (نوسان‌گیری) - نسخه کامل
--------------------------------------------------------------------------
ارزها (۲۰ عدد): DOGE, SOL, SHIB, BTC, ETH, BNB, ZEC, ADA, DOGS, NOT,
                LINK, LTC, UNI, GRAM, TRX, SUI, PEPE, HMSTR, BABYDOGE, PUMP
صرافی قیمت/تحلیل: KuCoin (اسپات) — چون Binance و Bybit از لوکیشن سرور مسدود بودن
نرخ تتر به تومان: از API عمومی نوبیتکس (Nobitex) گرفته می‌شه

قابلیت‌های این نسخه:
    - انتخاب واحد نمایش قیمت در همون اولین استارت: USDT / تومان / هر دو
    - قیمت‌ها تا ۸ رقم اعشار نمایش داده می‌شن
    - امتیاز اطمینان تخمینی برای هر سیگنال (نه احتمال آماری واقعی)
    - دسترسی محدود به لیست سفید کاربرها (ربات خصوصی)
    - منوی جدا برای ادمین (مدیریت) در مقابل کاربر عادی
    - حذف خودکار پیام‌های قدیمی بات، فقط ۳ پیام آخر نگه داشته می‌شه
    - گزارش خودکار هر ۱۵ دقیقه بدون منو، فقط متن خالص با تاریخ/ساعت

⚠️ این ربات ابزار تحلیل تکنیکال خودکار است، نه توصیه مالی.
⚠️ «امتیاز اطمینان» تخمین بر پایه قدرت اندیکاتورهاست، نه احتمال آماری واقعی یا تضمین‌شده.
⚠️ نرخ تومان از یک منبع بیرونی (نوبیتکس) گرفته می‌شه و ممکنه لحظاتی در دسترس نباشه.
⚠️ معاملات با اهرم ریسک بسیار بالایی دارد؛ مدیریت سرمایه با خودته.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime

try:
    from zoneinfo import ZoneInfo
    TEHRAN_TZ = ZoneInfo("Asia/Tehran")
except Exception:
    TEHRAN_TZ = None

import ccxt
import pandas as pd
import requests
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange
from telegram import BotCommand, BotCommandScopeChat, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")

# لیست سفید کاربرها: آیدی عددی تلگرام، جدا شده با کاما. اگه خالی باشه، بات برای همه بازه (پیشنهاد نمی‌شه)
ALLOWED_USER_IDS = {int(x) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip().isdigit()}
ADMIN_USER_IDS = {int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip().isdigit()}

# --- تنظیمات قابل تغییر ---
COIN_CODES = [
    "DOGE", "SOL", "SHIB", "BTC", "ETH",
    "BNB", "ZEC", "ADA", "DOGS", "NOT",
    "LINK", "LTC", "UNI", "GRAM", "TRX",
    "SUI", "PEPE", "HMSTR", "BABYDOGE", "PUMP",
]
SYMBOL_MAP = {code: f"{code}/USDT" for code in COIN_CODES}
SYMBOLS = list(SYMBOL_MAP.values())

TIMEFRAME = "15m"
CHECK_INTERVAL_SECONDS = 60 * 15      # ارسال خودکار هر ۱۵ دقیقه
TOP_SIGNALS_COUNT = 5                  # چند تا از بهترین سیگنال‌ها توی گزارش خودکار بیاد
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
KEEP_LAST_N_MESSAGES = 3               # فقط این تعداد پیام آخر بات توی چت بمونه

ENTRY_LADDER_ATR = [0.0, 0.35, 0.75]
SL_LADDER_ATR = [1.0, 1.25, 1.5]
SL_BASE = SL_LADDER_ATR[0]
TP_LADDER_ATR = [SL_BASE * 1.2, SL_BASE * 2.0, SL_BASE * 3.0]

TELEGRAM_MSG_LIMIT = 3500
IRT_RATE_TTL_SECONDS = 300

exchange = ccxt.kucoin()

# ---------- حالت‌های در حافظه (per-process؛ با ری‌استارت پاک می‌شن) ----------
last_plans: dict[str, "TradePlan"] = {}
subscribed_chat_ids: set[int] = set()
user_currency: dict[int, str] = {}          # chat_id -> "USDT" | "IRT" | "BOTH"
chat_message_history: dict[int, list[int]] = {}  # chat_id -> [message_id,...] برای حذف خودکار
_irt_rate_cache = {"value": None, "ts": 0.0}


@dataclass
class TradePlan:
    symbol: str
    direction: str          # "LONG" یا "SHORT"
    trend: str
    rsi: float
    confidence: float = 0.0
    entries: list = field(default_factory=list)
    stop_losses: list = field(default_factory=list)
    take_profits: list = field(default_factory=list)


# ---------- دسترسی ----------

def is_allowed(user_id: int) -> bool:
    if not ALLOWED_USER_IDS:
        return True  # اگه لیست سفید تنظیم نشده، فعلاً برای همه بازه
    return user_id in ALLOWED_USER_IDS


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_USER_IDS


async def guard(update: Update) -> bool:
    """اگه کاربر مجاز نبود، پیام رد دسترسی می‌ده و False برمی‌گردونه."""
    user = update.effective_user
    if user and not is_allowed(user.id):
        if update.message:
            await update.message.reply_text("⛔️ این ربات خصوصیه و دسترسی نداری.")
        elif update.callback_query:
            await update.callback_query.answer("⛔️ دسترسی نداری.", show_alert=True)
        return False
    return True


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


def fetch_usdt_irt_rate() -> float | None:
    """نرخ لحظه‌ای تتر به تومان از API عمومی نوبیتکس."""
    try:
        resp = requests.get(
            "https://api.nobitex.ir/market/stats",
            params={"srcCurrency": "usdt", "dstCurrency": "rls"},
            timeout=10,
        )
        data = resp.json()
        rial = float(data["stats"]["usdt-rls"]["latest"])
        return rial / 10  # ریال به تومان
    except Exception as e:
        logger.error(f"خطا در گرفتن نرخ تتر/تومان: {e}")
        return None


def get_irt_rate() -> float | None:
    now = time.time()
    if _irt_rate_cache["value"] is not None and (now - _irt_rate_cache["ts"] < IRT_RATE_TTL_SECONDS):
        return _irt_rate_cache["value"]
    rate = fetch_usdt_irt_rate()
    if rate:
        _irt_rate_cache["value"] = rate
        _irt_rate_cache["ts"] = now
        return rate
    return _irt_rate_cache["value"]  # اگه گرفتن نرخ جدید ناموفق بود، آخرین مقدار ذخیره‌شده (یا None) برگرده


def compute_confidence(direction: str, last_fast: float, last_slow: float, last_atr: float,
                        price: float, last_trend_ema: float, last_rsi: float) -> float:
    """
    امتیاز اطمینان تخمینی (۵۵ تا ۹۲) بر پایه قدرت هم‌جهتی مومنتوم/روند/RSI.
    این یک احتمال آماری واقعی یا بک‌تست‌شده نیست؛ صرفاً شدت هم‌جهتی اندیکاتورهاست.
    """
    if last_atr <= 0:
        return 55.0
    score = 50.0
    score += min(20.0, (abs(last_fast - last_slow) / last_atr) * 20.0)
    score += min(15.0, (abs(price - last_trend_ema) / last_atr) * 10.0)
    if direction == "LONG":
        score += min(15.0, max(0.0, last_rsi - 50.0) / 20.0 * 15.0)
    else:
        score += min(15.0, max(0.0, 50.0 - last_rsi) / 20.0 * 15.0)
    return round(min(92.0, max(55.0, score)), 1)


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

    confidence = compute_confidence(direction, last_fast, last_slow, last_atr, price, last_trend_ema, last_rsi)

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
        symbol=symbol, direction=direction, trend=trend_label, rsi=last_rsi, confidence=confidence,
        entries=entries, stop_losses=stop_losses, take_profits=take_profits,
    )


def generate_weekly_summary(symbol: str, code: str, chat_id: int) -> str:
    """خلاصه‌ی آماری ۷ روز اخیر بر پایه کندل‌های روزانه. دلیل خبری/بنیادی حرکت قیمت در این ابزار موجود نیست."""
    df = fetch_ohlcv(symbol, timeframe="1d", limit=8)
    if len(df) < 2:
        return f"🔸 *{code}*\n\nداده‌ی کافی برای تحلیل هفتگی در دسترس نیست."

    week_ago_price = df["close"].iloc[0]
    current_price = df["close"].iloc[-1]
    pct_change = (current_price - week_ago_price) / week_ago_price * 100
    highest = df["high"].max()
    lowest = df["low"].min()

    daily_pct = df["close"].pct_change() * 100
    idx_max = daily_pct.abs().idxmax()
    best_day_pct = daily_pct.loc[idx_max] if pd.notna(daily_pct.loc[idx_max]) else 0.0
    best_day_date = df.loc[idx_max, "timestamp"].strftime("%Y-%m-%d")

    if pct_change > 10:
        trend_desc = "صعودی قوی 📈"
    elif pct_change > 0:
        trend_desc = "صعودی ملایم 📈"
    elif pct_change > -10:
        trend_desc = "نزولی ملایم 📉"
    else:
        trend_desc = "نزولی قوی 📉"

    return (
        f"📊 *تحلیل ۷ روز اخیر {code}*\n{DIVIDER}\n"
        f"قیمت ۷ روز پیش: {fmt_amount(week_ago_price, chat_id)}\n"
        f"قیمت الان: {fmt_amount(current_price, chat_id)}\n"
        f"تغییر هفتگی: *{pct_change:+.2f}٪* — {trend_desc}\n\n"
        f"بیشترین قیمت هفته: {fmt_amount(highest, chat_id)}\n"
        f"کمترین قیمت هفته: {fmt_amount(lowest, chat_id)}\n"
        f"{DIVIDER}\n"
        f"بیشترین نوسان یک‌روزه: *{best_day_pct:+.2f}٪* در تاریخ {best_day_date}\n\n"
        f"ℹ️ این خلاصه فقط بر پایه‌ی داده‌ی قیمته. دلیل دقیق خبری/بنیادی افت یا رشد "
        f"(مثل اخبار یا رویدادهای خاص) در این ابزار در دسترس نیست."
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


# ---------- واحد پولی و قالب‌بندی قیمت ----------

def get_pref(chat_id: int) -> str:
    return user_currency.get(chat_id, "USDT")


def fmt_amount(usdt_value: float, chat_id: int) -> str:
    """قیمت رو با تا ۸ رقم اعشار، متناسب با واحد انتخابی کاربر، قالب‌بندی می‌کنه."""
    pref = get_pref(chat_id)
    usdt_txt = f"`{usdt_value:,.8f}` USDT"

    if pref == "USDT":
        return usdt_txt

    rate = get_irt_rate()
    if not rate:
        return usdt_txt + "  _(نرخ تومان موقتاً در دسترس نیست)_"

    irt_txt = f"`{usdt_value * rate:,.0f}` تومان"
    if pref == "IRT":
        return irt_txt
    return f"{usdt_txt}  |  {irt_txt}"


def now_str() -> str:
    dt = datetime.now(TEHRAN_TZ) if TEHRAN_TZ else datetime.now()
    return dt.strftime("%Y/%m/%d - %H:%M")


# ---------- قالب‌بندی پیام‌ها ----------

DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"


def format_prices_pretty(prices: dict[str, float], chat_id: int) -> str:
    if not prices:
        return "⚠️ دریافت قیمت لحظه‌ای الان ممکن نشد. کمی بعد دوباره امتحان کن."
    lines = ["💰 *قیمت لحظه‌ای ارزها*", DIVIDER]
    for symbol, price in prices.items():
        code = symbol.split("/")[0]
        lines.append(f"🔸 *{code}*   {fmt_amount(price, chat_id)}")
    return "\n".join(lines)


def format_plan_pretty(plan: TradePlan, code: str, chat_id: int) -> str:
    dir_txt = "🟢 لانگ (خرید)" if plan.direction == "LONG" else "🔴 شورت (فروش)"
    nums = ["1️⃣", "2️⃣", "3️⃣"]

    entries_txt = "\n".join(f"   {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(plan.entries))
    tp_txt = "\n".join(f"   {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(plan.take_profits))
    sl_txt = "\n".join(f"   {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(plan.stop_losses))

    return (
        f"🔸 *{code}/USDT* — {dir_txt}\n"
        f"روند: {plan.trend}  |  RSI: {plan.rsi:.1f}  |  🎯 اطمینان: *{plan.confidence:.0f}٪*\n"
        f"{DIVIDER}\n"
        f"📥 *نقاط ورود (۳ پله)*\n{entries_txt}\n\n"
        f"🎯 *حد سود (۳ پله)*\n{tp_txt}\n\n"
        f"🛑 *حد ضرر (۳ پله)*\n{sl_txt}\n"
        f"{DIVIDER}\n"
        f"💡 بعد از رسیدن به سود پله ۱، حد ضرر رو به نقطه ورود منتقل کن.\n"
        f"⚠️ امتیاز اطمینان تخمین تکنیکاله، نه تضمین. ابزار تحلیله، نه توصیه مالی."
    )


def format_plan_compact(plan: TradePlan, code: str, chat_id: int) -> str:
    dir_txt = "🟢 لانگ" if plan.direction == "LONG" else "🔴 شورت"
    return (
        f"🔸 *{code}* — {dir_txt}  |  اطمینان: *{plan.confidence:.0f}٪*\n"
        f"   ورود: {fmt_amount(plan.entries[0], chat_id)}\n"
        f"   سود۱: {fmt_amount(plan.take_profits[0], chat_id)}  |  ضرر: {fmt_amount(plan.stop_losses[0], chat_id)}"
    )


def format_no_signal(code: str) -> str:
    return (
        f"🔸 *{code}/USDT*\n\n"
        f"فعلاً سیگنال واضحی نیست — روند اصلی (EMA200) و مومنتوم کوتاه‌مدت هم‌جهت نیستن.\n"
        f"کمی بعد دوباره امتحان کن."
    )


def split_long_message(text: str, limit: int = TELEGRAM_MSG_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for block in text.split("\n\n"):
        if len(current) + len(block) + 2 > limit:
            if current:
                parts.append(current.strip())
            current = block
        else:
            current += ("\n\n" if current else "") + block
    if current:
        parts.append(current.strip())
    return parts


# ---------- مدیریت تاریخچه پیام (حذف خودکار، فقط N پیام آخر) ----------

async def track_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    history = chat_message_history.setdefault(chat_id, [])
    history.append(message_id)
    while len(history) > KEEP_LAST_N_MESSAGES:
        old_id = history.pop(0)
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=old_id)
        except Exception:
            pass  # پیام قدیمی‌تر از ۴۸ ساعت یا از قبل حذف‌شده رو نمی‌شه پاک کرد، مشکلی نیست


async def send_tracked(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, **kwargs):
    msg = await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
    await track_message(context, chat_id, msg.message_id)
    return msg


async def send_coin_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, code: str,
                             caption: str, reply_markup=None):
    """پیام رو همراه با لوگوی واقعی ارز می‌فرسته؛ اگه لوگو در دسترس نبود، فقط متن می‌فرسته."""
    try:
        msg = await context.bot.send_photo(
            chat_id=chat_id, photo=get_icon_url(code), caption=caption,
            parse_mode="Markdown", reply_markup=reply_markup,
        )
    except Exception as e:
        logger.warning(f"لوگوی {code} در دسترس نبود، به‌صورت متنی فرستاده شد: {e}")
        msg = await context.bot.send_message(
            chat_id=chat_id, text=caption, parse_mode="Markdown", reply_markup=reply_markup,
        )
    await track_message(context, chat_id, msg.message_id)
    return msg


# ---------- منوهای شیشه‌ای ----------

def kb_currency() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 دلار (USDT)", callback_data="cur_USDT")],
        [InlineKeyboardButton("💴 تومان (IRT)", callback_data="cur_IRT")],
        [InlineKeyboardButton("💱 هر دو", callback_data="cur_BOTH")],
    ])


def kb_main(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("💰 قیمت لحظه‌ای ارزها", callback_data="menu_prices")],
        [InlineKeyboardButton("🪙 انتخاب ارز مورد نظر", callback_data="menu_coins")],
        [InlineKeyboardButton("📋 نمایش همه پیشنهادات", callback_data="menu_all")],
        [InlineKeyboardButton("🔁 شروع مجدد / تغییر واحد پولی", callback_data="restart_currency")],
    ]
    if is_admin(user_id):
        rows.append([InlineKeyboardButton("⚙️ پنل مدیریت", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


def kb_prices() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی", callback_data="menu_prices")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")],
    ])


def kb_coins() -> InlineKeyboardMarkup:
    rows, row = [], []
    for c in COIN_CODES:
        row.append(InlineKeyboardButton(c, callback_data=f"coin_{c}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")])
    return InlineKeyboardMarkup(rows)


def kb_coin_detail(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎯 پیشنهاد لحظه‌ای", callback_data=f"suggest_{code}")],
        [InlineKeyboardButton("📊 تحلیل ۷ روز اخیر", callback_data=f"weekly_{code}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_coins")],
    ])


def kb_weekly(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"coin_{code}")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")],
    ])


def get_icon_url(code: str) -> str:
    """آدرس لوگوی واقعی ارز، از یه مجموعه آیکون عمومی و رایگان."""
    return f"https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/128/color/{code.lower()}.png"


def kb_suggestion(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی پیشنهاد", callback_data=f"suggest_{code}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"coin_{code}")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")],
    ])


def kb_all() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی", callback_data="menu_all")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")],
    ])


def kb_admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی کامل الان", callback_data="menu_all")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")],
    ])


# ---------- متن خوش‌آمد ----------

def welcome_text() -> str:
    return (
        "✅ *خوش اومدی!*\n\n"
        f"در حال رصد {len(COIN_CODES)} ارز هستم.\n"
        "هر ۱۵ دقیقه بهترین سیگنال‌های فعال رو با امتیاز اطمینان برات می‌فرستم.\n"
        "برای بررسی دستی، از منوی زیر استفاده کن 👇\n\n"
        "برای توقف اشتراک: /stop\n\n"
        "⚠️ ابزار تحلیل تکنیکاله، نه توصیه مالی. تصمیم و ریسک نهایی با خودته."
    )


async def finish_start(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int):
    if not is_admin(user_id):
        # فقط برای کاربر عادی، بعد از استارت لیست دستورات محدود به «منو» بشه
        await context.bot.set_my_commands(
            [BotCommand("menu", "🤖 نمایش منوی اصلی")],
            scope=BotCommandScopeChat(chat_id=chat_id),
        )
    else:
        # برای ادمین، همیشه لیست کامل دستورات فعال بمونه
        await context.bot.set_my_commands(
            [
                BotCommand("start", "🚀 شروع / انتخاب واحد پولی"),
                BotCommand("menu", "🤖 نمایش منوی اصلی"),
                BotCommand("status", "📊 وضعیت ربات"),
                BotCommand("stop", "❌ توقف اشتراک"),
            ],
            scope=BotCommandScopeChat(chat_id=chat_id),
        )
    await send_tracked(
        context, chat_id, welcome_text(),
        reply_markup=kb_main(user_id), parse_mode="Markdown",
    )


# ---------- هندلر دکمه‌ها ----------

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    subscribed_chat_ids.add(chat_id)

    if data.startswith("cur_"):
        user_currency[chat_id] = data.split("_", 1)[1]
        await query.message.delete()
        chat_message_history.pop(chat_id, None)
        await finish_start(context, chat_id, user_id)
        return

    if data == "menu_main":
        await query.edit_message_text(
            "🤖 *منوی اصلی*\nیکی از گزینه‌ها رو انتخاب کن:",
            reply_markup=kb_main(user_id), parse_mode="Markdown",
        )

    elif data == "menu_prices":
        await query.edit_message_text("⏳ در حال دریافت قیمت لحظه‌ای...")
        prices = fetch_current_prices()
        await query.edit_message_text(
            format_prices_pretty(prices, chat_id), reply_markup=kb_prices(), parse_mode="Markdown",
        )

    elif data == "menu_coins":
        await query.edit_message_text(
            "🪙 *انتخاب ارز مورد نظر*\nارز مورد نظرت رو انتخاب کن:",
            reply_markup=kb_coins(), parse_mode="Markdown",
        )

    elif data.startswith("coin_"):
        code = data.split("_", 1)[1]
        try:
            await query.message.delete()
        except Exception:
            pass
        await send_coin_message(
            context, chat_id, code,
            caption=f"🔸 *{code}/USDT*\nچی می‌خوای ببینی؟",
            reply_markup=kb_coin_detail(code),
        )

    elif data.startswith("suggest_"):
        code = data.split("_", 1)[1]
        symbol = SYMBOL_MAP.get(code)
        try:
            plan = generate_trade_plan(symbol)
        except Exception as e:
            logger.error(f"خطا در تحلیل {symbol}: {e}")
            plan = None

        try:
            await query.message.delete()
        except Exception:
            pass

        if plan:
            dir_txt = "🟢 لانگ (خرید)" if plan.direction == "LONG" else "🔴 شورت (فروش)"
            short_caption = f"🔸 *{code}/USDT* — {dir_txt}\n🎯 اطمینان: *{plan.confidence:.0f}٪*"
            await send_coin_message(context, chat_id, code, caption=short_caption)
            detail_text = format_plan_pretty(plan, code, chat_id)
            await send_tracked(context, chat_id, detail_text, reply_markup=kb_suggestion(code), parse_mode="Markdown")
        else:
            await send_coin_message(
                context, chat_id, code,
                caption=format_no_signal(code), reply_markup=kb_suggestion(code),
            )

    elif data.startswith("weekly_"):
        code = data.split("_", 1)[1]
        symbol = SYMBOL_MAP.get(code)
        try:
            summary = generate_weekly_summary(symbol, code, chat_id)
        except Exception as e:
            logger.error(f"خطا در تحلیل هفتگی {symbol}: {e}")
            summary = f"🔸 *{code}*\n\nخطا در دریافت داده‌ی هفتگی. کمی بعد دوباره امتحان کن."

        try:
            await query.edit_message_caption(caption=summary, reply_markup=kb_weekly(code), parse_mode="Markdown")
        except Exception:
            try:
                await query.message.delete()
            except Exception:
                pass
            await send_tracked(context, chat_id, summary, reply_markup=kb_weekly(code), parse_mode="Markdown")

    elif data == "restart_currency":
        try:
            await query.message.delete()
        except Exception:
            pass
        chat_message_history.pop(chat_id, None)
        msg = await context.bot.send_message(
            chat_id=chat_id,
            text="👋 واحد پولی نمایش قیمت‌ها رو دوباره انتخاب کن:",
            reply_markup=kb_currency(),
        )
        await track_message(context, chat_id, msg.message_id)

    elif data == "menu_all":
        await query.edit_message_text("⏳ در حال تحلیل همه‌ی ارزها (چند ثانیه طول می‌کشه)...")
        plans = refresh_all_plans()
        if not plans:
            await query.edit_message_text(
                "📋 *نمایش همه پیشنهادات*\n\nفعلاً هیچ سیگنال واضحی روی هیچ‌کدوم از ارزها نیست.",
                reply_markup=kb_all(), parse_mode="Markdown",
            )
            return
        sorted_plans = sorted(plans.values(), key=lambda p: p.confidence, reverse=True)
        full_text = "📋 *نمایش همه پیشنهادات*\n\n" + "\n\n".join(
            format_plan_pretty(p, p.symbol.split("/")[0], chat_id) for p in sorted_plans
        )
        chunks = split_long_message(full_text)
        await query.edit_message_text(chunks[0], parse_mode="Markdown")
        for chunk in chunks[1:-1]:
            await query.message.reply_text(chunk, parse_mode="Markdown")
        if len(chunks) > 1:
            await query.message.reply_text(chunks[-1], reply_markup=kb_all(), parse_mode="Markdown")
        else:
            await query.message.reply_text("👆 نتیجه‌ی کامل بالا", reply_markup=kb_all())

    elif data == "admin_panel":
        if not is_admin(user_id):
            await query.answer("⛔️ فقط ادمین.", show_alert=True)
            return
        text = (
            "⚙️ *پنل مدیریت*\n" + DIVIDER + "\n"
            f"تعداد اعضای فعال: {len(subscribed_chat_ids)}\n"
            f"سیگنال‌های فعال الان: {len(last_plans)}\n"
            f"تعداد ارز تحت رصد: {len(COIN_CODES)}\n"
            f"فاصله گزارش خودکار: {CHECK_INTERVAL_SECONDS // 60} دقیقه"
        )
        await query.edit_message_text(text, reply_markup=kb_admin_panel(), parse_mode="Markdown")


# ---------- ارسال خودکار دوره‌ای ----------

async def auto_report_loop(app: Application):
    while True:
        if subscribed_chat_ids:
            plans = refresh_all_plans()
            top_plans = sorted(plans.values(), key=lambda p: p.confidence, reverse=True)[:TOP_SIGNALS_COUNT] if plans else []

            for chat_id in list(subscribed_chat_ids):
                header = f"📢 *پیشنهادات لحظه‌ای*  —  🕒 {now_str()}\n\n"
                if top_plans:
                    body = "\n\n".join(format_plan_compact(p, p.symbol.split("/")[0], chat_id) for p in top_plans)
                    body += "\n\n⚠️ امتیاز اطمینان تخمینیه، نه تضمینی."
                else:
                    body = "فعلاً سیگنال واضحی روی هیچ‌کدوم از ارزها نیست."
                try:
                    msg = await app.bot.send_message(chat_id=chat_id, text=header + body, parse_mode="Markdown")
                    await track_message_no_context(app, chat_id, msg.message_id)
                except Exception as e:
                    logger.error(f"ارسال به {chat_id} ناموفق بود: {e}")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


async def track_message_no_context(app: Application, chat_id: int, message_id: int):
    history = chat_message_history.setdefault(chat_id, [])
    history.append(message_id)
    while len(history) > KEEP_LAST_N_MESSAGES:
        old_id = history.pop(0)
        try:
            await app.bot.delete_message(chat_id=chat_id, message_id=old_id)
        except Exception:
            pass


# ---------- دستورات پایه ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    subscribed_chat_ids.add(chat_id)

    if chat_id not in user_currency:
        msg = await update.message.reply_text(
            "👋 قبل از شروع، واحد پولی نمایش قیمت‌ها رو انتخاب کن:",
            reply_markup=kb_currency(),
        )
        await track_message(context, chat_id, msg.message_id)
        return

    await finish_start(context, chat_id, user_id)


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    subscribed_chat_ids.discard(update.effective_chat.id)
    await update.message.reply_text("❌ اشتراک قطع شد.")


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    subscribed_chat_ids.add(chat_id)
    msg = await update.message.reply_text(
        "🤖 *منوی اصلی*\nیکی از گزینه‌ها رو انتخاب کن:",
        reply_markup=kb_main(user_id), parse_mode="Markdown",
    )
    await track_message(context, chat_id, msg.message_id)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    await update.message.reply_text(
        f"در حال رصد: {', '.join(COIN_CODES)}\n"
        f"تایم‌فریم: {TIMEFRAME}\n"
        f"فاصله گزارش خودکار: هر {CHECK_INTERVAL_SECONDS // 60} دقیقه\n"
        f"تعداد اعضا: {len(subscribed_chat_ids)}\n"
        f"سیگنال‌های فعال الان: {len(last_plans)}"
    )


async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "🚀 شروع و عضویت در سیگنال‌ها"),
        BotCommand("menu", "🤖 نمایش منوی اصلی"),
    ])
    asyncio.create_task(auto_report_loop(app))


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN تنظیم نشده! فایل .env رو بساز و توکن رو بذار توش.")
    if not ALLOWED_USER_IDS:
        logger.warning("ALLOWED_USER_IDS تنظیم نشده — بات فعلاً برای همه باز است!")

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
