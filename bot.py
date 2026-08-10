"""
ربات تلگرام سیگنال‌دهی (نوسان‌گیری) - نسخه کامل و اصلاح‌شده
--------------------------------------------------------------------------
ارزها (۲۰ عدد): DOGE, SOL, SHIB, BTC, ETH, BNB, ZEC, ADA, DOGS, NOT,
                LINK, LTC, UNI, GRAM, TRX, SUI, PEPE, HMSTR, BABYDOGE, PUMP
صرافی قیمت/تحلیل: KuCoin (اسپات)
نرخ تتر به تومان: نوبیتکس (اول) و در صورت خطا Wallex (دوم)

⚠️ نکته مهم: تمام حالت‌های داخل این فایل (اشتراک، واحد پولی، سیگنال‌ها) توی
حافظه‌ی برنامه نگه داشته می‌شن، نه دیتابیس. یعنی با هر ری‌استارت/دیپلوی جدید
سرور، این اطلاعات پاک می‌شه و کاربرها باید دوباره /start بزنن.

⚠️ این ربات ابزار تحلیل تکنیکال خودکار است، نه توصیه مالی.
⚠️ «امتیاز اطمینان» تخمین بر پایه قدرت اندیکاتورهاست، نه احتمال آماری واقعی.
⚠️ نرخ تومان از منابع بیرونی گرفته می‌شه و ممکنه لحظاتی در دسترس نباشه.
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
CHECK_INTERVAL_SECONDS = 60 * 15
TOP_SIGNALS_COUNT = 5
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
AUTO_KEEP_LAST_N = 3     # فقط ۳ پیام آخرِ «پیشنهادات خودکار» نگه داشته بشه

ENTRY_LADDER_ATR = [0.0, 0.35, 0.75]
SL_LADDER_ATR = [1.0, 1.25, 1.5]
SL_BASE = SL_LADDER_ATR[0]
TP_LADDER_ATR = [SL_BASE * 1.2, SL_BASE * 2.0, SL_BASE * 3.0]

TELEGRAM_MSG_LIMIT = 3500
IRT_RATE_TTL_SECONDS = 300

exchange = ccxt.kucoin()

# ---------- حالت‌های در حافظه ----------
last_plans: dict[str, "TradePlan"] = {}
subscribed_chat_ids: set[int] = set()
user_currency: dict[int, str] = {}
auto_message_history: dict[int, list[int]] = {}          # پیام‌های پیشنهاد خودکار (نگه‌داری ۳ تای آخر)
interactive_screen_messages: dict[int, list[int]] = {}    # پیام‌های صفحه‌ی تعاملی فعلی (فقط آخری بمونه)
_irt_rate_cache = {"value": None, "ts": 0.0, "source": None}


@dataclass
class TradePlan:
    symbol: str
    direction: str
    trend: str
    rsi: float
    current_price: float = 0.0
    confidence: float = 0.0
    entries: list = field(default_factory=list)
    stop_losses: list = field(default_factory=list)
    take_profits: list = field(default_factory=list)


# ---------- دسترسی ----------

def is_allowed(user_id: int) -> bool:
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_USER_IDS


async def guard(update: Update) -> bool:
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


def fetch_irt_rate_nobitex() -> float | None:
    resp = requests.get(
        "https://api.nobitex.ir/market/stats",
        params={"srcCurrency": "usdt", "dstCurrency": "rls"}, timeout=8,
    )
    rial = float(resp.json()["stats"]["usdt-rls"]["latest"])
    return rial / 10


def fetch_irt_rate_wallex() -> float | None:
    resp = requests.get("https://api.wallex.ir/v1/markets", timeout=8)
    data = resp.json()
    return float(data["result"]["symbols"]["USDTTMN"]["stats"]["lastPrice"])


def get_irt_rate() -> float | None:
    now = time.time()
    if _irt_rate_cache["value"] is not None and (now - _irt_rate_cache["ts"] < IRT_RATE_TTL_SECONDS):
        return _irt_rate_cache["value"]

    for name, fn in (("nobitex", fetch_irt_rate_nobitex), ("wallex", fetch_irt_rate_wallex)):
        try:
            rate = fn()
            if rate and rate > 0:
                _irt_rate_cache.update(value=rate, ts=now, source=name)
                return rate
        except Exception as e:
            logger.warning(f"گرفتن نرخ تومان از {name} ناموفق بود: {e}")

    return _irt_rate_cache["value"]  # آخرین مقدار معتبر قبلی (یا None)


def compute_confidence(direction: str, last_fast: float, last_slow: float, last_atr: float,
                        price: float, last_trend_ema: float, last_rsi: float) -> float:
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
        symbol=symbol, direction=direction, trend=trend_label, rsi=last_rsi,
        current_price=price, confidence=confidence,
        entries=entries, stop_losses=stop_losses, take_profits=take_profits,
    )


def generate_weekly_summary(symbol: str, code: str, chat_id: int) -> str:
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
        trend_desc = "صعودی قوی 🚀"
    elif pct_change > 0:
        trend_desc = "صعودی ملایم 📈"
    elif pct_change > -10:
        trend_desc = "نزولی ملایم 📉"
    else:
        trend_desc = "نزولی قوی 🔻"

    return (
        f"📊 *تحلیل ۷ روز اخیر {code}*\n{DIVIDER}\n"
        f"قیمت ۷ روز پیش: {fmt_amount(week_ago_price, chat_id)}\n"
        f"قیمت الان: {fmt_amount(current_price, chat_id)}\n"
        f"تغییر هفتگی: *{pct_change:+.2f}٪* — {trend_desc}\n\n"
        f"بیشترین قیمت هفته: {fmt_amount(highest, chat_id)}\n"
        f"کمترین قیمت هفته: {fmt_amount(lowest, chat_id)}\n"
        f"{DIVIDER}\n"
        f"بیشترین نوسان یک‌روزه: *{best_day_pct:+.2f}٪* در تاریخ {best_day_date}\n\n"
        f"ℹ️ این خلاصه فقط بر پایه‌ی داده‌ی قیمته؛ دلیل خبری/بنیادی افت یا رشد در این ابزار در دسترس نیست."
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
    pref = get_pref(chat_id)
    usdt_txt = f"`{usdt_value:,.8f}` USDT"

    if pref == "USDT":
        return usdt_txt

    rate = get_irt_rate()
    if not rate:
        if pref == "IRT":
            return usdt_txt + "  _(نرخ تومان موقتاً در دسترس نیست)_"
        return usdt_txt

    irt_txt = f"`{usdt_value * rate:,.0f}` تومان"
    if pref == "IRT":
        return irt_txt
    if pref == "BOTH":
        return f"{usdt_txt}\n        {irt_txt}"
    return usdt_txt


def now_str() -> str:
    dt = datetime.now(TEHRAN_TZ) if TEHRAN_TZ else datetime.now()
    return dt.strftime("%Y/%m/%d - %H:%M")


def mood_emoji(plan: TradePlan) -> str:
    if plan.direction == "LONG":
        return "🚀" if plan.confidence >= 80 else "📈"
    return "🔻" if plan.confidence >= 80 else "📉"


# ---------- قالب‌بندی پیام‌ها ----------

DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
BIG_DIVIDER = "═══════════════"


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
    emoji = mood_emoji(plan)
    nums = ["1️⃣", "2️⃣", "3️⃣"]

    entries_txt = "\n".join(f"   {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(plan.entries))
    tp_txt = "\n".join(f"   {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(plan.take_profits))
    sl_txt = "\n".join(f"   {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(plan.stop_losses))

    return (
        f"{emoji} *{code}/USDT* — {dir_txt}\n"
        f"روند: {plan.trend}  |  RSI: {plan.rsi:.1f}  |  🎯 اطمینان: *{plan.confidence:.0f}٪*\n"
        f"{DIVIDER}\n"
        f"💰 *قیمت لحظه‌ای*\n   {fmt_amount(plan.current_price, chat_id)}\n\n"
        f"📥 *نقاط ورود (۳ پله)*\n{entries_txt}\n\n"
        f"🎯 *حد سود (۳ پله)*\n{tp_txt}\n\n"
        f"🛑 *حد ضرر (۳ پله)*\n{sl_txt}\n"
        f"{DIVIDER}\n"
        f"💡 بعد از رسیدن به سود پله ۱، حد ضرر رو به نقطه ورود منتقل کن.\n"
        f"⚠️ امتیاز اطمینان تخمین تکنیکاله، نه تضمین."
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


# ---------- مدیریت پیام‌ها ----------

async def clear_interactive_screen(context: ContextTypes.DEFAULT_TYPE, chat_id: int, keep_id: int | None = None):
    """پیام(های) صفحه‌ی تعاملی قبلی رو پاک می‌کنه؛ فقط آخرین صفحه باید بمونه."""
    ids = interactive_screen_messages.pop(chat_id, [])
    for mid in ids:
        if mid == keep_id:
            continue
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass


def set_interactive_screen(chat_id: int, message_ids: list[int]):
    interactive_screen_messages[chat_id] = message_ids


async def send_tracked_screen(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str, **kwargs):
    """یه پیام تعاملی جدید می‌فرسته و به‌عنوان تنها صفحه‌ی فعلی ثبتش می‌کنه."""
    msg = await context.bot.send_message(chat_id=chat_id, text=text, **kwargs)
    set_interactive_screen(chat_id, [msg.message_id])
    return msg


async def send_coin_photo(context: ContextTypes.DEFAULT_TYPE, chat_id: int, code: str,
                           caption: str, reply_markup=None) -> int | None:
    """لوگوی واقعی ارز رو می‌فرسته؛ اگه در دسترس نبود فقط متن می‌فرسته. آیدی پیام رو برمی‌گردونه."""
    icon_url = f"https://raw.githubusercontent.com/spothq/cryptocurrency-icons/master/128/color/{code.lower()}.png"
    try:
        msg = await context.bot.send_photo(
            chat_id=chat_id, photo=icon_url, caption=caption, parse_mode="Markdown", reply_markup=reply_markup,
        )
    except Exception as e:
        logger.warning(f"لوگوی {code} در دسترس نبود: {e}")
        msg = await context.bot.send_message(
            chat_id=chat_id, text=caption, parse_mode="Markdown", reply_markup=reply_markup,
        )
    return msg.message_id


async def track_auto_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
    history = auto_message_history.setdefault(chat_id, [])
    history.append(message_id)
    while len(history) > AUTO_KEEP_LAST_N:
        old_id = history.pop(0)
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=old_id)
        except Exception:
            pass


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
        [InlineKeyboardButton("🔁 شروع مجدد", callback_data="restart_currency")],
    ]
    if is_admin(user_id):
        rows.append([InlineKeyboardButton("⚙️ پنل مدیریت", callback_data="admin_panel")])
    return InlineKeyboardMarkup(rows)


def kb_back_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")]])


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


def kb_suggestion(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"suggest_{code}")],
        [InlineKeyboardButton("🔙 بازگشت به لیست ارزها", callback_data="menu_coins")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")],
    ])


def kb_suggestion_from_auto(code: str) -> InlineKeyboardMarkup:
    """وقتی پیشنهاد از روی پیام خودکار باز شده، دکمه برگشت فقط همین صفحه رو می‌بنده."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"suggest_{code}_auto")],
        [InlineKeyboardButton("✖️ بستن", callback_data="close_temp")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")],
    ])


def kb_weekly(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"coin_{code}")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")],
    ])


def kb_admin_panel() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی کامل الان", callback_data="menu_all")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")],
    ])


def kb_auto_report(top_plans: list[TradePlan]) -> InlineKeyboardMarkup:
    rows, row = [], []
    for p in top_plans:
        code = p.symbol.split("/")[0]
        row.append(InlineKeyboardButton(code, callback_data=f"suggest_{code}_auto"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")])
    return InlineKeyboardMarkup(rows)


# ---------- متن‌ها ----------

def welcome_text() -> str:
    return (
        "✅ *خوش اومدی!*\n\n"
        f"در حال رصد {len(COIN_CODES)} ارز هستم.\n"
        "هر ۱۵ دقیقه بهترین سیگنال‌های فعال رو با امتیاز اطمینان برات می‌فرستم.\n"
        "برای بررسی دستی، از منوی زیر استفاده کن 👇\n\n"
        "برای توقف اشتراک: /stop\n\n"
        "⚠️ ابزار تحلیل تکنیکاله، نه توصیه مالی. تصمیم و ریسک نهایی با خودته."
    )


MENU_PROMPT = "یکی از گزینه‌ها رو انتخاب کن:"


async def finish_start(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int):
    if is_admin(user_id):
        await context.bot.set_my_commands(
            [
                BotCommand("start", "🚀 شروع / انتخاب واحد پولی"),
                BotCommand("menu", "🤖 نمایش منوی اصلی"),
                BotCommand("status", "📊 وضعیت ربات"),
                BotCommand("stop", "❌ توقف اشتراک"),
            ],
            scope=BotCommandScopeChat(chat_id=chat_id),
        )
    else:
        await context.bot.set_my_commands(
            [BotCommand("menu", "🤖 نمایش منوی اصلی")],
            scope=BotCommandScopeChat(chat_id=chat_id),
        )
    await clear_interactive_screen(context, chat_id)
    msg = await send_tracked_screen(
        context, chat_id, welcome_text(), reply_markup=kb_main(user_id), parse_mode="Markdown",
    )
    return msg


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

    # ---- انتخاب واحد پولی (اولین بار یا از «شروع مجدد») ----
    if data.startswith("cur_"):
        user_currency[chat_id] = data.split("_", 1)[1]
        try:
            await query.message.delete()
        except Exception:
            pass
        await finish_start(context, chat_id, user_id)
        return

    if data == "restart_currency":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text(
            "👋 واحد پولی نمایش قیمت‌ها رو دوباره انتخاب کن:", reply_markup=kb_currency(),
        )
        set_interactive_screen(chat_id, [query.message.message_id])
        return

    # ---- بستن یه صفحه‌ی موقت که از روی پیام خودکار باز شده (بدون حذف پیام خودکار) ----
    if data == "close_temp":
        try:
            await query.message.delete()
        except Exception:
            pass
        return

    # ---- پیشنهاد لحظه‌ای از روی پیام خودکار (نباید پیام خودکار پاک بشه) ----
    if data.startswith("suggest_") and data.endswith("_auto"):
        code = data[len("suggest_"):-len("_auto")]
        symbol = SYMBOL_MAP.get(code)
        try:
            plan = generate_trade_plan(symbol)
        except Exception as e:
            logger.error(f"خطا در تحلیل {symbol}: {e}")
            plan = None

        # اگه این یه بروزرسانیه (پیام موقت قبلی وجود داره)، اون رو پاک کن؛ ولی پیام خودکار دست‌نخورده بمونه
        try:
            if query.message and query.message.photo:
                await query.message.delete()
        except Exception:
            pass

        if plan:
            dir_txt = "🟢 لانگ (خرید)" if plan.direction == "LONG" else "🔴 شورت (فروش)"
            short_caption = f"{mood_emoji(plan)} *{code}/USDT* — {dir_txt}\n🎯 اطمینان: *{plan.confidence:.0f}٪*"
            await send_coin_photo(context, chat_id, code, caption=short_caption)
            detail_text = format_plan_pretty(plan, code, chat_id)
            for chunk in split_long_message(detail_text):
                await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")
            await context.bot.send_message(
                chat_id=chat_id, text="👆 پیشنهاد لحظه‌ای", reply_markup=kb_suggestion_from_auto(code),
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id, text=format_no_signal(code),
                reply_markup=kb_suggestion_from_auto(code), parse_mode="Markdown",
            )
        return

    # ---- بقیه‌ی مسیرها: هر بار صفحه‌ی تعاملی قبلی جمع می‌شه ----
    if data == "menu_main":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        try:
            await query.edit_message_text(MENU_PROMPT, reply_markup=kb_main(user_id))
        except Exception:
            await query.message.delete()
            msg = await context.bot.send_message(chat_id=chat_id, text=MENU_PROMPT, reply_markup=kb_main(user_id))
            set_interactive_screen(chat_id, [msg.message_id])
            return
        set_interactive_screen(chat_id, [query.message.message_id])

    elif data == "menu_prices":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        try:
            await query.edit_message_text("⏳ در حال دریافت قیمت لحظه‌ای...")
        except Exception:
            pass
        prices = fetch_current_prices()
        text = format_prices_pretty(prices, chat_id)
        try:
            await query.edit_message_text(text, reply_markup=kb_back_main(), parse_mode="Markdown")
            set_interactive_screen(chat_id, [query.message.message_id])
        except Exception:
            msg = await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=kb_back_main(), parse_mode="Markdown")
            set_interactive_screen(chat_id, [msg.message_id])

    elif data == "menu_coins":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        try:
            await query.edit_message_text(
                f"🪙 *انتخاب ارز مورد نظر*\n{MENU_PROMPT}", reply_markup=kb_coins(), parse_mode="Markdown",
            )
            set_interactive_screen(chat_id, [query.message.message_id])
        except Exception:
            await query.message.delete()
            msg = await context.bot.send_message(
                chat_id=chat_id, text=f"🪙 *انتخاب ارز مورد نظر*\n{MENU_PROMPT}",
                reply_markup=kb_coins(), parse_mode="Markdown",
            )
            set_interactive_screen(chat_id, [msg.message_id])

    elif data.startswith("coin_"):
        code = data.split("_", 1)[1]
        await clear_interactive_screen(context, chat_id)
        try:
            await query.message.delete()
        except Exception:
            pass
        mid = await send_coin_photo(
            context, chat_id, code, caption=f"🔸 *{code}/USDT*\n{MENU_PROMPT}",
            reply_markup=kb_coin_detail(code),
        )
        set_interactive_screen(chat_id, [mid])

    elif data.startswith("suggest_"):
        code = data.split("_", 1)[1]
        symbol = SYMBOL_MAP.get(code)
        try:
            plan = generate_trade_plan(symbol)
        except Exception as e:
            logger.error(f"خطا در تحلیل {symbol}: {e}")
            plan = None

        await clear_interactive_screen(context, chat_id)
        try:
            await query.message.delete()
        except Exception:
            pass

        new_ids = []
        if plan:
            dir_txt = "🟢 لانگ (خرید)" if plan.direction == "LONG" else "🔴 شورت (فروش)"
            short_caption = f"{mood_emoji(plan)} *{code}/USDT* — {dir_txt}\n🎯 اطمینان: *{plan.confidence:.0f}٪*"
            mid1 = await send_coin_photo(context, chat_id, code, caption=short_caption)
            new_ids.append(mid1)
            detail_text = format_plan_pretty(plan, code, chat_id)
            chunks = split_long_message(detail_text)
            for chunk in chunks[:-1]:
                m = await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")
                new_ids.append(m.message_id)
            m_last = await context.bot.send_message(
                chat_id=chat_id, text=chunks[-1], reply_markup=kb_suggestion(code), parse_mode="Markdown",
            )
            new_ids.append(m_last.message_id)
        else:
            mid = await send_coin_photo(
                context, chat_id, code, caption=format_no_signal(code), reply_markup=kb_suggestion(code),
            )
            new_ids.append(mid)
        set_interactive_screen(chat_id, new_ids)

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
            set_interactive_screen(chat_id, [query.message.message_id])
        except Exception:
            await clear_interactive_screen(context, chat_id)
            try:
                await query.message.delete()
            except Exception:
                pass
            msg = await context.bot.send_message(
                chat_id=chat_id, text=summary, reply_markup=kb_weekly(code), parse_mode="Markdown",
            )
            set_interactive_screen(chat_id, [msg.message_id])

    elif data == "menu_all":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        try:
            await query.edit_message_text("⏳ در حال تحلیل همه‌ی ارزها (چند ثانیه طول می‌کشه)...")
        except Exception:
            pass
        plans = refresh_all_plans()
        if not plans:
            text = f"📋 *نمایش همه پیشنهادات*\n\nفعلاً هیچ سیگنال واضحی روی هیچ‌کدوم از ارزها نیست."
            await query.edit_message_text(text, reply_markup=kb_back_main(), parse_mode="Markdown")
            set_interactive_screen(chat_id, [query.message.message_id])
            return

        sorted_plans = sorted(plans.values(), key=lambda p: p.confidence, reverse=True)
        full_text = f"📋 *نمایش همه پیشنهادات*\n\n" + f"\n\n{BIG_DIVIDER}\n\n".join(
            format_plan_pretty(p, p.symbol.split("/")[0], chat_id) for p in sorted_plans
        )
        chunks = split_long_message(full_text)
        new_ids = []
        await query.edit_message_text(chunks[0], parse_mode="Markdown")
        new_ids.append(query.message.message_id)
        for chunk in chunks[1:-1]:
            m = await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")
            new_ids.append(m.message_id)
        if len(chunks) > 1:
            m_last = await context.bot.send_message(chat_id=chat_id, text=chunks[-1], reply_markup=kb_back_main(), parse_mode="Markdown")
            new_ids.append(m_last.message_id)
        else:
            m_last = await context.bot.send_message(chat_id=chat_id, text="👆 نتیجه‌ی کامل بالا", reply_markup=kb_back_main())
            new_ids.append(m_last.message_id)
        set_interactive_screen(chat_id, new_ids)

    elif data == "admin_panel":
        if not is_admin(user_id):
            await query.answer("⛔️ فقط ادمین.", show_alert=True)
            return
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        text = (
            "⚙️ *پنل مدیریت*\n" + DIVIDER + "\n"
            f"تعداد اعضای فعال: {len(subscribed_chat_ids)}\n"
            f"سیگنال‌های فعال الان: {len(last_plans)}\n"
            f"تعداد ارز تحت رصد: {len(COIN_CODES)}\n"
            f"فاصله گزارش خودکار: {CHECK_INTERVAL_SECONDS // 60} دقیقه"
        )
        await query.edit_message_text(text, reply_markup=kb_admin_panel(), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id])


# ---------- ارسال خودکار دوره‌ای ----------

async def auto_report_loop(app: Application):
    while True:
        if subscribed_chat_ids:
            plans = refresh_all_plans()
            top_plans = sorted(plans.values(), key=lambda p: p.confidence, reverse=True)[:TOP_SIGNALS_COUNT] if plans else []

            for chat_id in list(subscribed_chat_ids):
                header = f"📢 *پیشنهادات لحظه‌ای*  —  🕒 {now_str()}\n{BIG_DIVIDER}\n\n"
                if top_plans:
                    body = f"\n\n{DIVIDER}\n\n".join(
                        format_plan_pretty(p, p.symbol.split("/")[0], chat_id) for p in top_plans
                    )
                    footer = "\n\n⚠️ امتیاز اطمینان تخمینیه، نه تضمینی. برای هر ارز، از دکمه‌ی زیر لمس کن."
                    keyboard = kb_auto_report(top_plans)
                else:
                    body = "فعلاً سیگنال واضحی روی هیچ‌کدوم از ارزها نیست."
                    footer = ""
                    keyboard = kb_back_main()

                text = header + body + footer
                try:
                    for chunk in split_long_message(text)[:-1]:
                        m = await app.bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")
                        await track_auto_message(app, chat_id, m.message_id)
                    last_chunk = split_long_message(text)[-1]
                    m_last = await app.bot.send_message(chat_id=chat_id, text=last_chunk, reply_markup=keyboard, parse_mode="Markdown")
                    await track_auto_message(app, chat_id, m_last.message_id)
                except Exception as e:
                    logger.error(f"ارسال به {chat_id} ناموفق بود: {e}")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


# ---------- دستورات پایه ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    chat_id = update.effective_chat.id
    subscribed_chat_ids.add(chat_id)
    await clear_interactive_screen(context, chat_id)
    # /start همیشه از انتخاب واحد پولی شروع می‌شه (حتی اگه قبلاً انتخاب شده بود)
    msg = await update.message.reply_text(
        "👋 واحد پولی نمایش قیمت‌ها رو انتخاب کن:", reply_markup=kb_currency(),
    )
    set_interactive_screen(chat_id, [msg.message_id])


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    subscribed_chat_ids.discard(update.effective_chat.id)
    await update.message.reply_text("❌ اشتراک قطع شد. هر وقت خواستی، از منو گزینه‌ی «🔁 شروع مجدد» رو بزن یا /start رو بزن.")


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    subscribed_chat_ids.add(chat_id)
    await clear_interactive_screen(context, chat_id)
    msg = await update.message.reply_text(MENU_PROMPT, reply_markup=kb_main(user_id))
    set_interactive_screen(chat_id, [msg.message_id])


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    await update.message.reply_text(
        f"در حال رصد: {', '.join(COIN_CODES)}\n"
        f"تایم‌فریم: {TIMEFRAME}\n"
        f"فاصله گزارش خودکار: هر {CHECK_INTERVAL_SECONDS // 60} دقیقه\n"
        f"تعداد اعضا: {len(subscribed_chat_ids)}\n"
        f"سیگنال‌های فعال الان: {len(last_plans)}\n"
        f"منبع نرخ تومان: {_irt_rate_cache.get('source') or 'نامشخص'}"
    )


async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "🚀 شروع / انتخاب واحد پولی"),
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
