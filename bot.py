"""
ربات تلگرام سیگنال‌دهی (نوسان‌گیری) - نسخه کامل و اصلاح‌شده
--------------------------------------------------------------------------
ارزها (۲۰ عدد): DOGE, SOL, SHIB, BTC, ETH, BNB, ZEC, ADA, DOGS, NOT,
                LINK, LTC, UNI, GRAM, TRX, SUI, PEPE, HMSTR, BABYDOGE, PUMP
صرافی قیمت/تحلیل: KuCoin (اسپات)
نرخ تتر به تومان: نوبیتکس (اول) و در صورت خطا Wallex (دوم)

⚠️ نکته مهم درباره ذخیره‌سازی: تنظیمات کاربرها (اشتراک، واحد پولی) توی یه فایل JSON
روی دیسک ذخیره می‌شه. اگه روی سرویس Railway یه Volume وصل نکرده باشی، این فایل با
هر دیپلوی جدید پاک می‌شه. برای ماندگاری دائمی، از داشبورد Railway یه Volume با
مسیر اتصال (mount path) دقیقاً "/data" به این سرویس اضافه کن.

⚠️ این ربات ابزار تحلیل تکنیکال خودکار است، نه توصیه مالی.
⚠️ «امتیاز اطمینان» تخمین بر پایه قدرت اندیکاتورهاست، نه احتمال آماری واقعی.
⚠️ نرخ تومان از منابع بیرونی گرفته می‌شه و ممکنه لحظاتی در دسترس نباشه.
"""

import asyncio
import json
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
import jdatetime
import pandas as pd
import requests
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator, MACD, ADXIndicator
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

TIMEFRAME = "1h"          # تایم‌فریم بزرگ‌تر = سیگنال قابل‌اعتمادتر و کمتر دچار نویز/سیگنال کاذب
CHECK_INTERVAL_SECONDS = 60 * 15
TOP_SIGNALS_COUNT = 5
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
ADX_TREND_THRESHOLD = 20   # زیر این مقدار یعنی بازار رنج/بی‌روند، سیگنال صادر نمی‌شه
AUTO_KEEP_LAST_N = 3     # فقط ۳ پیام آخرِ «پیشنهادات خودکار» نگه داشته بشه

# پله‌بندی ورود/سود/ضرر بر پایه ATR ساعتی (فاصله‌ها به‌اندازه‌ی کافی بزرگ برای معامله‌ی واقعی)
ENTRY_LADDER_ATR = [0.0, 0.6, 1.2]
SL_LADDER_ATR = [1.8, 2.2, 2.6]
TP_LADDER_ATR = [2.5, 4.0, 6.0]

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

# ---------- ذخیره‌سازی دائمی (نیازمند Volume روی Railway، وگرنه با هر دیپلوی پاک می‌شه) ----------
DATA_DIR = os.getenv("DATA_DIR", "/data")
STATE_FILE = os.path.join(DATA_DIR, "state.json")


def load_state():
    global subscribed_chat_ids, user_currency
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        subscribed_chat_ids = set(data.get("subscribed_chat_ids", []))
        user_currency = {int(k): v for k, v in data.get("user_currency", {}).items()}
        logger.info(f"وضعیت قبلی بازیابی شد: {len(subscribed_chat_ids)} کاربر از {STATE_FILE}")
    except FileNotFoundError:
        logger.info(f"فایل ذخیره‌سازی ({STATE_FILE}) پیدا نشد؛ از صفر شروع می‌شه.")
    except Exception as e:
        logger.warning(f"خطا در خواندن وضعیت ذخیره‌شده: {e}")


def save_state():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({
                "subscribed_chat_ids": list(subscribed_chat_ids),
                "user_currency": user_currency,
            }, f)
    except Exception as e:
        logger.warning(f"خطا در ذخیره‌ی وضعیت (احتمالاً Volume وصل نیست): {e}")


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
            price = ticker.get("last") or ticker.get("close") or ticker.get("bid") or ticker.get("ask")
            if not price:
                # بعضی ارزها (مثل توکن‌های خیلی جدید) فیلد last/close خالی برمی‌گردونن؛
                # آخرین قیمت بسته‌شدن از کندل‌ها رو به‌عنوان جایگزین می‌گیریم
                df = fetch_ohlcv(symbol, timeframe="15m", limit=2)
                if len(df):
                    price = df["close"].iloc[-1]
            if price:
                prices[symbol] = price
            else:
                logger.warning(f"قیمتی برای {symbol} پیدا نشد.")
        except Exception as e:
            logger.error(f"خطا در گرفتن قیمت {symbol}: {e}")
    return prices


def fetch_irt_rate_nobitex() -> float | None:
    """چند بار تلاش می‌کنه چون نوبیتکس منبع اصلی و دقیق‌تره؛ فقط در صورت شکست کامل به Wallex می‌ره."""
    last_error = None
    for attempt in range(3):
        try:
            resp = requests.get(
                "https://api.nobitex.ir/market/stats",
                params={"srcCurrency": "usdt", "dstCurrency": "rls"}, timeout=8,
            )
            rial = float(resp.json()["stats"]["usdt-rls"]["latest"])
            return rial / 10
        except Exception as e:
            last_error = e
            time.sleep(1.5)
    raise last_error


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


def compute_confidence(direction: str, adx: float, macd_hist: float, last_atr: float,
                        plus_di: float, minus_di: float, price: float, last_trend_ema: float,
                        last_rsi: float) -> float:
    """
    امتیاز اطمینان (۵۰ تا ۹۵) بر پایه‌ی ترکیب چند اندیکاتور:
      - قدرت روند (ADX)
      - قدرت مومنتوم (هیستوگرام MACD نسبت به نوسان بازار)
      - فاصله‌ی جهت‌دار (+DI / -DI)
      - همسویی RSI
      - فاصله‌ی قیمت از EMA200
    این یک احتمال آماری واقعی/بک‌تست‌شده نیست، بلکه شدت هم‌جهتی اندیکاتورهاست.
    """
    if last_atr <= 0:
        return 50.0

    score = 20.0
    score += min(25.0, (adx / 45.0) * 25.0)                              # قدرت روند
    score += min(20.0, (abs(macd_hist) / last_atr) * 40.0)               # قدرت مومنتوم
    score += min(20.0, (abs(plus_di - minus_di) / 35.0) * 20.0)          # فاصله جهت‌دار
    score += min(20.0, (abs(price - last_trend_ema) / last_atr) * 12.0)  # فاصله از روند اصلی

    if direction == "LONG":
        score += min(15.0, max(0.0, last_rsi - 50.0) / 20.0 * 15.0)
    else:
        score += min(15.0, max(0.0, 50.0 - last_rsi) / 20.0 * 15.0)

    return round(min(95.0, max(50.0, score)), 1)


def generate_trade_plan(symbol: str) -> TradePlan | None:
    df = fetch_ohlcv(symbol)
    if len(df) < 60:
        return None

    ema_trend = EMAIndicator(df["close"], window=200).ema_indicator()
    rsi_series = RSIIndicator(df["close"], window=14).rsi()
    atr_series = AverageTrueRange(df["high"], df["low"], df["close"], window=14).average_true_range()

    macd_ind = MACD(df["close"], window_slow=26, window_fast=12, window_sign=9)
    macd_hist_series = macd_ind.macd_diff()

    adx_ind = ADXIndicator(df["high"], df["low"], df["close"], window=14)
    adx_series = adx_ind.adx()
    plus_di_series = adx_ind.adx_pos()
    minus_di_series = adx_ind.adx_neg()

    price = df["close"].iloc[-1]
    last_rsi = rsi_series.iloc[-1]
    last_atr = atr_series.iloc[-1]
    last_trend_ema = ema_trend.iloc[-1]
    last_macd_hist = macd_hist_series.iloc[-1]
    last_adx = adx_series.iloc[-1]
    last_plus_di = plus_di_series.iloc[-1]
    last_minus_di = minus_di_series.iloc[-1]

    if pd.isna(last_trend_ema) or pd.isna(last_adx) or pd.isna(last_macd_hist):
        return None

    price_above_trend = price > last_trend_ema
    trend_label = "صعودی 📈" if price_above_trend else "نزولی 📉"
    is_trending = last_adx >= ADX_TREND_THRESHOLD

    long_ok = (
        price_above_trend and is_trending
        and last_macd_hist > 0 and last_plus_di > last_minus_di
        and 40 < last_rsi < RSI_OVERBOUGHT
    )
    short_ok = (
        not price_above_trend and is_trending
        and last_macd_hist < 0 and last_minus_di > last_plus_di
        and RSI_OVERSOLD < last_rsi < 60
    )

    if long_ok:
        direction = "LONG"
    elif short_ok:
        direction = "SHORT"
    else:
        return None

    confidence = compute_confidence(
        direction, last_adx, last_macd_hist, last_atr, last_plus_di, last_minus_di,
        price, last_trend_ema, last_rsi,
    )

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
    df = fetch_ohlcv(symbol, timeframe="1d", limit=15)
    if len(df) < 2:
        return f"🔸 *{code}*\n\nداده‌ی کافی برای تحلیل هفتگی در دسترس نیست."

    week_df = df.tail(8)  # ۷ روز کامل + امروز
    week_ago_price = week_df["close"].iloc[0]
    current_price = week_df["close"].iloc[-1]
    pct_change = (current_price - week_ago_price) / week_ago_price * 100
    highest = week_df["high"].max()
    lowest = week_df["low"].min()
    highest_date = week_df.loc[week_df["high"].idxmax(), "timestamp"].strftime("%Y-%m-%d")
    lowest_date = week_df.loc[week_df["low"].idxmin(), "timestamp"].strftime("%Y-%m-%d")

    daily_pct = week_df["close"].pct_change() * 100
    idx_max = daily_pct.abs().idxmax()
    best_day_pct = daily_pct.loc[idx_max] if pd.notna(daily_pct.loc[idx_max]) else 0.0
    best_day_dt = week_df.loc[idx_max, "timestamp"]
    best_day_date = best_day_dt.strftime("%Y-%m-%d")
    try:
        best_day_shamsi = jdatetime.date.fromgregorian(date=best_day_dt.date()).strftime("%Y/%m/%d")
    except Exception:
        best_day_shamsi = "-"

    # نوسان (انحراف معیار تغییرات روزانه) و تعداد روزهای مثبت/منفی
    volatility = daily_pct.std()
    up_days = int((daily_pct > 0).sum())
    down_days = int((daily_pct < 0).sum())
    avg_volume = week_df["volume"].mean()

    # RSI روزانه برای زمینه‌ی مومنتوم فعلی
    try:
        daily_rsi = RSIIndicator(df["close"], window=14).rsi().iloc[-1]
        rsi_txt = f"{daily_rsi:.1f}"
        if daily_rsi > 70:
            rsi_note = "(اشباع خرید ⚠️)"
        elif daily_rsi < 30:
            rsi_note = "(اشباع فروش ⚠️)"
        else:
            rsi_note = ""
    except Exception:
        rsi_txt, rsi_note = "-", ""

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
        f"📈 بیشترین قیمت هفته: {fmt_amount(highest, chat_id)}\n"
        f"   📅 {highest_date}\n"
        f"📉 کمترین قیمت هفته: {fmt_amount(lowest, chat_id)}\n"
        f"   📅 {lowest_date}\n"
        f"{DIVIDER}\n"
        f"⚡ بیشترین نوسان یک‌روزه: *{best_day_pct:+.2f}٪*\n"
        f"   📅 {best_day_date} میلادی  |  {best_day_shamsi} شمسی\n\n"
        f"📐 نوسان‌پذیری هفته (انحراف معیار روزانه): *{volatility:.2f}٪*\n"
        f"🟢 روزهای مثبت: {up_days}  |  🔴 روزهای منفی: {down_days}\n"
        f"📊 میانگین حجم معاملات روزانه: `{avg_volume:,.0f}`\n"
        f"🎯 RSI روزانه فعلی: *{rsi_txt}* {rsi_note}\n"
        f"{DIVIDER}\n"
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


def fmt_irt(value: float) -> str:
    """قیمت تومان رو متناسب با اندازه‌ش قالب‌بندی می‌کنه؛ برای مقادیر زیر ۱ تومان (ارزهای خیلی ارزون)
    اعشار واقعی نشون می‌ده، نه اینکه گرد بشه به صفر یا یک."""
    if value >= 1:
        return f"{value:,.0f}"
    if value == 0:
        return "0"
    return f"{value:.8f}".rstrip("0").rstrip(".")


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

    irt_txt = f"`{fmt_irt(usdt_value * rate)}` تومان"
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
        if plan.confidence >= 85:
            return "🚀"
        elif plan.confidence >= 70:
            return "🔥"
        return "📈"
    if plan.confidence >= 85:
        return "🔻"
    elif plan.confidence >= 70:
        return "⚠️"
    return "📉"


def confidence_badge(confidence: float) -> str:
    if confidence >= 90:
        return "🔥🔥 فوق‌العاده قوی"
    elif confidence >= 85:
        return "🔥 خیلی قوی"
    elif confidence >= 80:
        return "⚡ قوی"
    elif confidence >= 75:
        return "✨ نسبتاً قوی"
    elif confidence >= 70:
        return "💫 متوسط رو به بالا"
    elif confidence >= 65:
        return "🌤 متوسط"
    elif confidence >= 60:
        return "🌥 ضعیف رو به متوسط"
    return "💤 ضعیف"


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
    dir_txt = "🟢 لانگ (خرید) 💹" if plan.direction == "LONG" else "🔴 شورت (فروش) 🔻"
    emoji = mood_emoji(plan)
    badge = confidence_badge(plan.confidence)
    nums = ["1️⃣", "2️⃣", "3️⃣"]

    entries_txt = "\n".join(f"   {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(plan.entries))
    tp_txt = "\n".join(f"   {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(plan.take_profits))
    sl_txt = "\n".join(f"   {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(plan.stop_losses))

    return (
        f"{emoji} *{code}/USDT* — {dir_txt}\n"
        f"📊 روند: {plan.trend}  |  RSI: {plan.rsi:.1f}\n"
        f"🎯 اطمینان: *{plan.confidence:.0f}٪*  ({badge})\n"
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
        [InlineKeyboardButton("💱 هر دو ✨", callback_data="cur_BOTH")],
    ])


def kb_main(user_id: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("💰 قیمت‌ لحظه‌ای", callback_data="menu_prices"),
            InlineKeyboardButton("🪙 انتخاب ارز", callback_data="menu_coins"),
        ],
        [
            InlineKeyboardButton("📊 همه پیشنهادات", callback_data="menu_all"),
            InlineKeyboardButton("🔄 شروع مجدد", callback_data="restart_currency"),
        ],
    ]
    if is_admin(user_id):
        rows.append([InlineKeyboardButton("⚙️ پنل مدیریت ویژه", callback_data="admin_panel")])
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
        [InlineKeyboardButton("📆 تحلیل ۷ روز اخیر", callback_data=f"weekly_{code}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_coins")],
    ])


def kb_suggestion(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"suggest_{code}")],
        [InlineKeyboardButton("🔙 بازگشت به مرحله قبل", callback_data=f"coin_{code}")],
        [InlineKeyboardButton("📋 لیست ارزها", callback_data="menu_coins")],
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
        "🌟 *به سیگنالستان خوش اومدی!* 🌟\n"
        f"{DIVIDER}\n"
        f"🛰️ در حال رصد {len(COIN_CODES)} ارز هستم\n"
        "⏱️ هر ۱۵ دقیقه بهترین سیگنال‌های فعال رو با ⚡️ امتیاز اطمینان برات می‌فرستم\n"
        "👇 برای بررسی دستی، از منوی زیر استفاده کن\n\n"
        "برای توقف اشتراک: /stop\n\n"
        "⚠️ ابزار تحلیل تکنیکاله، نه توصیه مالی. تصمیم و ریسک نهایی با خودته."
    )


MENU_PROMPT = "👇 یکی از گزینه‌ها رو انتخاب کن:"
MAIN_MENU_HEADER = "✨ *پنل سیگنال‌یار* ✨\n" + DIVIDER + "\n" + MENU_PROMPT


async def finish_start(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int):
    if is_admin(user_id):
        await context.bot.set_my_commands(
            [
                BotCommand("start", "شروع ربات"),
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
        save_state()
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
            short_caption = f"{mood_emoji(plan)} *{code}/USDT*"
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
            await query.edit_message_text(MAIN_MENU_HEADER, reply_markup=kb_main(user_id), parse_mode="Markdown")
        except Exception:
            await query.message.delete()
            msg = await context.bot.send_message(chat_id=chat_id, text=MAIN_MENU_HEADER, reply_markup=kb_main(user_id), parse_mode="Markdown")
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
        coins_header = f"🪙 *انتخاب ارز مورد نظر*\n{DIVIDER}\n{MENU_PROMPT}"
        try:
            await query.edit_message_text(coins_header, reply_markup=kb_coins(), parse_mode="Markdown")
            set_interactive_screen(chat_id, [query.message.message_id])
        except Exception:
            await query.message.delete()
            msg = await context.bot.send_message(
                chat_id=chat_id, text=coins_header, reply_markup=kb_coins(), parse_mode="Markdown",
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
            context, chat_id, code, caption=f"🔸✨ *{code}/USDT* ✨🔸\n{DIVIDER}\n{MENU_PROMPT}",
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
            short_caption = f"{mood_emoji(plan)} *{code}/USDT*"
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
        quick_links_kb = kb_auto_report(sorted_plans)
        for chunk in chunks[1:-1]:
            m = await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")
            new_ids.append(m.message_id)
        if len(chunks) > 1:
            m_last = await context.bot.send_message(chat_id=chat_id, text=chunks[-1], reply_markup=quick_links_kb, parse_mode="Markdown")
            new_ids.append(m_last.message_id)
        else:
            m_last = await context.bot.send_message(chat_id=chat_id, text="👆 نتیجه‌ی کامل بالا — برای هر ارز، دکمه‌ش رو بزن", reply_markup=quick_links_kb)
            new_ids.append(m_last.message_id)
        set_interactive_screen(chat_id, new_ids)

    elif data == "admin_panel":
        if not is_admin(user_id):
            await query.answer("⛔️ فقط ادمین.", show_alert=True)
            return
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        text = (
            "🛠️ *پنل مدیریت ویژه* 🛠️\n" + DIVIDER + "\n"
            f"👥 اعضای فعال: {len(subscribed_chat_ids)}\n"
            f"⚡️ سیگنال‌های فعال الان: {len(last_plans)}\n"
            f"🪙 تعداد ارز تحت رصد: {len(COIN_CODES)}\n"
            f"⏱️ فاصله گزارش خودکار: {CHECK_INTERVAL_SECONDS // 60} دقیقه"
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
                header = f"📢✨ *پیشنهادات لحظه‌ای* ✨📢\n🕒 {now_str()}\n{BIG_DIVIDER}\n\n"
                if top_plans:
                    body = f"\n\n{DIVIDER}\n\n".join(
                        format_plan_pretty(p, p.symbol.split("/")[0], chat_id) for p in top_plans
                    )
                    footer = "\n\n⚠️ امتیاز اطمینان تخمینیه، نه تضمینی.\n👇 برای جزئیات هر ارز، دکمه‌ش رو لمس کن."
                    keyboard = kb_auto_report(top_plans)
                else:
                    body = "😴 فعلاً سیگنال واضحی روی هیچ‌کدوم از ارزها نیست."
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
    save_state()
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
    save_state()
    await update.message.reply_text("❌ اشتراک قطع شد. هر وقت خواستی، از منو گزینه‌ی «🔁 شروع مجدد» رو بزن یا /start رو بزن.")


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    subscribed_chat_ids.add(chat_id)
    await clear_interactive_screen(context, chat_id)
    msg = await update.message.reply_text(MAIN_MENU_HEADER, reply_markup=kb_main(user_id), parse_mode="Markdown")
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
        BotCommand("start", "شروع ربات"),
        BotCommand("menu", "🤖 نمایش منوی اصلی"),
    ])
    asyncio.create_task(auto_report_loop(app))


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN تنظیم نشده! فایل .env رو بساز و توکن رو بذار توش.")
    if not ALLOWED_USER_IDS:
        logger.warning("ALLOWED_USER_IDS تنظیم نشده — بات فعلاً برای همه باز است!")

    load_state()

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
