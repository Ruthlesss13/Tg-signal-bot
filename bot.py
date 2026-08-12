"""
ربات تلگرام سیگنال‌دهی - نسخه V5 (رفع مشکلات weekly و عدم سیگنال)
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

try:
    from zoneinfo import ZoneInfo
    TEHRAN_TZ = ZoneInfo("Asia/Tehran")
except Exception:
    TEHRAN_TZ = None

import ccxt
import jdatetime
import pandas as pd
import requests
from ta.momentum import RSIIndicator, StochRSIIndicator
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.volatility import AverageTrueRange, BollingerBands
from telegram import BotCommand, BotCommandScopeChat, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ---------- متغیرهای محیطی ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USER_IDS = {int(x) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip().isdigit()}
ADMIN_USER_IDS = {int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip().isdigit()}
ALWAYS_ALLOWED_USER_IDS = {int(x) for x in os.getenv("ALWAYS_ALLOWED_USER_IDS", "").split(",") if x.strip().isdigit()}

# ---------- تنظیمات ----------
COIN_ICONS = {
    "DOGE": "🐕", "SOL": "◎", "SHIB": "🦴", "BTC": "₿", "ETH": "Ξ",
    "BNB": "🔶", "ZEC": "🛡️", "ADA": "🔷", "DOGS": "🐾", "NOT": "💎",
    "LINK": "🔗", "LTC": "Ł", "UNI": "🦄", "GRAM": "✳️", "TRX": "⚡",
    "SUI": "💧", "PEPE": "🐸", "HMSTR": "🐹", "BABYDOGE": "🐶", "PUMP": "🚀",
    "SPCX": "🛰️", "PENDLE": "📐", "CAKE": "🥞", "S": "💨", "DEXE": "🗳️",
    "SKY": "☁️", "ASTER": "✴️", "HYPE": "🌊", "RENDER": "🖥️", "POL": "🟣",
    "ONDO": "🏦", "XAUT": "🥇", "ENA": "🌐", "FLOKI": "🐕‍🦺", "TAO": "🧠",
    "ARB": "🔵", "MAGIC": "🪄", "CFX": "🌲", "WLD": "👁️", "LDO": "🌊",
    "DYDX": "📉", "APT": "🅰️", "ENS": "🏷️", "ONE": "🎐", "API3": "🔌",
    "STORJ": "💾", "SLP": "🍯", "ZRX": "0️⃣", "ATOM": "⚛️", "AVAX": "🔺",
    "AXS": "🐚", "NEAR": "Ⓝ", "GMT": "👟", "CHZ": "🌶️", "HBAR": "Ⓗ",
    "CRO": "💠", "ETC": "⟠", "DOT": "⚪", "AAVE": "👻", "FIL": "📁",
    "XRP": "✕", "BCH": "🟢", "A": "🏛️", "XLM": "✨",
}
COIN_CODES = list(COIN_ICONS.keys())
SYMBOL_MAP = {code: f"{code}/USDT" for code in COIN_CODES}
SYMBOLS = list(SYMBOL_MAP.values())

TIMEFRAME = "1h"
CHECK_INTERVAL_SECONDS = 60 * 15
TOP_SIGNALS_COUNT = 5
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
ADX_TREND_THRESHOLD = 16
AUTO_KEEP_LAST_N = 3

ENTRY_LADDER_ATR = [0.0, 0.6, 1.2]
ENTRY_WEIGHTS = [0.5, 0.3, 0.2]
SL_ATR_MULT = 2.0
TP_ATR_MULT = 4.0

TELEGRAM_MSG_LIMIT = 3500
IRT_RATE_TTL_SECONDS = 300
COINS_GRID_COLUMNS = 4

RLM = "\u200f"
DATA_DIR = os.getenv("DATA_DIR", "/data")
STATE_FILE = os.path.join(DATA_DIR, "state.json")

# ---------- صرافی ----------
exchange = ccxt.mexc({
    "enableRateLimit": True,
    "options": {
        "defaultType": "swap",
        "adjustForTimeDifference": True,
    }
})

# ---------- حالت‌ها ----------
last_plans: dict[str, "TradePlan"] = {}
subscribed_chat_ids: set[int] = set()
user_currency: dict[int, str] = {}
auto_message_history: dict[int, list[int]] = {}
overlay_messages: dict[int, list[int]] = {}
interactive_screen_messages: dict[int, list[int]] = {}
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
    funding_rate: float = 0.0
    leverage: int = 1

# ---------- کش داده‌ها ----------
class MarketDataCache:
    _instance = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self.prices: dict[str, float] = {}
        self.ohlcv_1h: dict[str, pd.DataFrame] = {}
        self.ohlcv_4h: dict[str, pd.DataFrame] = {}
        self.ohlcv_1d: dict[str, pd.DataFrame] = {}
        self.last_price_update = 0.0
        self.last_ohlcv_update = 0.0
        self.valid_symbols: list[str] = []
        self._load_markets()
        self._sem = asyncio.Semaphore(10)

    def _load_markets(self):
        try:
            markets = exchange.load_markets()
            self.valid_symbols = [s for s in SYMBOLS if s in markets]
            logger.info(f"✅ {len(self.valid_symbols)} نماد معتبر از {len(SYMBOLS)} نماد")
        except Exception as e:
            logger.error(f"❌ خطا در بارگیری بازارها: {e}")
            self.valid_symbols = SYMBOLS

    async def update_prices(self):
        async def fetch_one(symbol):
            async with self._sem:
                try:
                    ticker = exchange.fetch_ticker(symbol)
                    price = ticker.get("last") or ticker.get("close") or ticker.get("bid") or ticker.get("ask")
                    return symbol, price
                except Exception as e:
                    logger.debug(f"خطا در دریافت قیمت {symbol}: {e}")
                    return symbol, None

        tasks = [fetch_one(sym) for sym in self.valid_symbols]
        results = await asyncio.gather(*tasks)
        self.prices = {sym: price for sym, price in results if price is not None}
        self.last_price_update = time.time()
        logger.debug(f"💰 بروزرسانی قیمت‌ها: {len(self.prices)} ارز")

    async def update_ohlcv(self):
        async def fetch_ohlcv_safe(symbol, tf):
            async with self._sem:
                try:
                    df = self._fetch_ohlcv_internal(symbol, timeframe=tf, limit=250)
                    return symbol, tf, df
                except Exception as e:
                    logger.debug(f"خطا در دریافت {symbol} {tf}: {e}")
                    return symbol, tf, None

        tasks_1h = [fetch_ohlcv_safe(sym, "1h") for sym in self.valid_symbols]
        tasks_4h = [fetch_ohlcv_safe(sym, "4h") for sym in self.valid_symbols]
        tasks_1d = [fetch_ohlcv_safe(sym, "1d") for sym in self.valid_symbols]
        results = await asyncio.gather(*tasks_1h, *tasks_4h, *tasks_1d)

        self.ohlcv_1h.clear()
        self.ohlcv_4h.clear()
        self.ohlcv_1d.clear()
        for symbol, tf, df in results:
            if df is not None and not df.empty:
                if tf == "1h":
                    self.ohlcv_1h[symbol] = df
                elif tf == "4h":
                    self.ohlcv_4h[symbol] = df
                elif tf == "1d":
                    self.ohlcv_1d[symbol] = df
        self.last_ohlcv_update = time.time()
        logger.info(f"📊 بروزرسانی کندل‌ها: {len(self.ohlcv_1h)} (1h) / {len(self.ohlcv_4h)} (4h) / {len(self.ohlcv_1d)} (1d)")

    def _fetch_ohlcv_internal(self, symbol, timeframe, limit):
        return exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    async def get_indicators(self, symbol: str) -> Optional[dict]:
        if symbol not in self.ohlcv_1h or symbol not in self.ohlcv_4h:
            return None
        df = self.ohlcv_1h[symbol]
        if len(df) < 210:
            return None
        return self._calc_indicators_from_df(df, symbol)

    def _calc_indicators_from_df(self, df, symbol):
        try:
            ema_trend = EMAIndicator(df["close"], window=200).ema_indicator()
            rsi_series = RSIIndicator(df["close"], window=14).rsi()
            atr_series = AverageTrueRange(df["high"], df["low"], df["close"], window=14).average_true_range()
            macd_ind = MACD(df["close"], window_slow=26, window_fast=12, window_sign=9)
            macd_hist_series = macd_ind.macd_diff()
            adx_ind = ADXIndicator(df["high"], df["low"], df["close"], window=14)
            adx_series = adx_ind.adx()
            plus_di_series = adx_ind.adx_pos()
            minus_di_series = adx_ind.adx_neg()
            stoch_ind = StochRSIIndicator(df["close"], window=14, smooth1=3, smooth2=3)
            stoch_k_series = stoch_ind.stochrsi_k() * 100
            bb_ind = BollingerBands(df["close"], window=20, window_dev=2)
            bb_percent_series = bb_ind.bollinger_pband()
            vol_sma = df["volume"].rolling(20).mean()
            volume_ratio_series = df["volume"] / vol_sma

            price = df["close"].iloc[-1]
            last_rsi = rsi_series.iloc[-1]
            last_atr = atr_series.iloc[-1]
            last_trend_ema = ema_trend.iloc[-1]
            last_macd_hist = macd_hist_series.iloc[-1]
            last_adx = adx_series.iloc[-1]
            last_plus_di = plus_di_series.iloc[-1]
            last_minus_di = minus_di_series.iloc[-1]
            last_stoch_k = stoch_k_series.iloc[-1]
            last_bb_percent = bb_percent_series.iloc[-1]
            last_volume_ratio = volume_ratio_series.iloc[-1]

            if any(pd.isna(x) for x in [last_trend_ema, last_adx, last_macd_hist, last_stoch_k]):
                return None
            if pd.isna(last_volume_ratio):
                last_volume_ratio = 1.0
            if pd.isna(last_bb_percent):
                last_bb_percent = 0.5

            higher_tf_trend_up = None
            df4h = self.ohlcv_4h.get(symbol)
            if df4h is not None and len(df4h) >= 205:
                ema200_4h = EMAIndicator(df4h["close"], window=200).ema_indicator().iloc[-1]
                if pd.notna(ema200_4h):
                    higher_tf_trend_up = df4h["close"].iloc[-1] > ema200_4h

            price_above_trend = price > last_trend_ema
            return {
                "price": price,
                "rsi": last_rsi,
                "atr": last_atr,
                "trend_ema": last_trend_ema,
                "macd_hist": last_macd_hist,
                "adx": last_adx,
                "plus_di": last_plus_di,
                "minus_di": last_minus_di,
                "stoch_k": last_stoch_k,
                "bb_percent": last_bb_percent,
                "volume_ratio": last_volume_ratio,
                "higher_tf_trend_up": higher_tf_trend_up,
                "price_above_trend": price_above_trend,
                "trend_label": "صعودی 📈" if price_above_trend else "نزولی 📉",
                "is_trending": last_adx >= ADX_TREND_THRESHOLD,
            }
        except Exception as e:
            logger.error(f"❌ خطا در محاسبه اندیکاتورها برای {symbol}: {e}")
            return None

    async def get_weekly_data(self, symbol: str) -> Optional[pd.DataFrame]:
        df = self.ohlcv_1d.get(symbol)
        if df is None:
            logger.warning(f"⚠️ داده‌های روزانه برای {symbol} موجود نیست")
            return None
        if len(df) < 8:
            logger.warning(f"⚠️ تعداد کندل‌های روزانه برای {symbol} کم است ({len(df)})، از همان موجود استفاده می‌شود")
            # باز هم داده را برمی‌گردانیم تا حداقل چیزی نمایش دهد
            return df
        end = df["timestamp"].iloc[-1]
        start = end - pd.Timedelta(days=7)
        week_df = df[df["timestamp"] >= start]
        if len(week_df) < 2:
            # اگر باز هم کم بود، کل دیتا را برگردان
            return df
        return week_df

cache = MarketDataCache()

# ---------- توابع کمکی ----------
def is_allowed(user_id: int) -> bool:
    if user_id in ALWAYS_ALLOWED_USER_IDS:
        return True
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

def fetch_irt_rate_nobitex() -> float | None:
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
    return _irt_rate_cache["value"]

def get_pref(chat_id: int) -> str:
    return user_currency.get(chat_id, "USDT")

def fmt_irt(value: float) -> str:
    if value >= 1:
        return f"{value:,.0f}"
    if value == 0:
        return "0"
    return f"{value:.10f}".rstrip("0").rstrip(".")

def fmt_amount(usdt_value: float, chat_id: int) -> str:
    pref = get_pref(chat_id)
    usdt_txt = f"{RLM}`{usdt_value:,.10f}` USDT{RLM}"
    if pref == "USDT":
        return usdt_txt
    rate = get_irt_rate()
    if not rate:
        if pref == "IRT":
            return usdt_txt + "  _(نرخ تومان موقتاً در دسترس نیست)_"
        return usdt_txt
    irt_txt = f"{RLM}`{fmt_irt(usdt_value * rate)}`{RLM} تومان"
    if pref == "IRT":
        return irt_txt
    if pref == "BOTH":
        return f"{usdt_txt}\n        {irt_txt}"
    return usdt_txt

def sym(code: str) -> str:
    return f"{RLM}{code}/USDT{RLM}"

def shamsi_now() -> str:
    dt = datetime.now(TEHRAN_TZ) if TEHRAN_TZ else datetime.now()
    j = jdatetime.datetime.fromgregorian(datetime=dt)
    return j.strftime("%Y/%m/%d - %H:%M")

def shamsi_date(dt) -> str:
    try:
        return jdatetime.date.fromgregorian(date=dt.date() if hasattr(dt, "date") else dt).strftime("%Y/%m/%d")
    except Exception:
        return "-"

def rtl_lines(text: str) -> str:
    return "\n".join((RLM + line) if line.strip() else line for line in text.split("\n"))

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

# ---------- منطق سیگنال با شرایط نرم‌تر (برای تست) ----------
def compute_confidence(direction: str, ind: dict) -> float:
    score = 0.0

    if direction == "LONG":
        score += 20 if ind["price_above_trend"] else -10
    else:
        score += 20 if not ind["price_above_trend"] else -10

    macd_ok = ind["macd_hist"] > 0 if direction == "LONG" else ind["macd_hist"] < 0
    score += 15 if macd_ok else -5

    score += min(15, (ind["adx"] / 50) * 15)

    di_ok = ind["plus_di"] > ind["minus_di"] if direction == "LONG" else ind["minus_di"] > ind["plus_di"]
    score += 10 if di_ok else -5

    score += min(10, max(0, (ind["volume_ratio"] - 0.7) * 20))  # نرم‌تر از قبل

    if direction == "LONG":
        if 45 <= ind["rsi"] <= 65:   # گسترده‌تر
            score += 10
        elif 65 < ind["rsi"] <= 72:
            score += 5
        elif 72 < ind["rsi"] <= 78:
            score += 2
        else:
            score -= 5
    else:
        if 30 <= ind["rsi"] <= 50:
            score += 10
        elif 25 <= ind["rsi"] < 30:
            score += 5
        elif 20 <= ind["rsi"] < 25:
            score += 2
        else:
            score -= 5

    if direction == "LONG":
        if 15 <= ind["stoch_k"] <= 85:  # گسترده‌تر
            score += 5
        elif 85 < ind["stoch_k"] <= 92:
            score += 2
        else:
            score -= 3
    else:
        if 15 <= ind["stoch_k"] <= 85:
            score += 5
        elif 8 <= ind["stoch_k"] < 15:
            score += 2
        else:
            score -= 3

    if 0.1 <= ind["bb_percent"] <= 0.9:  # گسترده‌تر
        score += 5
    elif 0.05 <= ind["bb_percent"] < 0.1 or 0.9 < ind["bb_percent"] <= 0.95:
        score += 2
    else:
        score -= 2

    if ind["higher_tf_trend_up"] is not None:
        higher_ok = (direction == "LONG" and ind["higher_tf_trend_up"]) or \
                    (direction == "SHORT" and not ind["higher_tf_trend_up"])
        score += 10 if higher_ok else -10

    return max(0, min(100, round(score, 1)))

def decide_direction(ind: dict) -> Optional[str]:
    # شرایط کمی نرم‌تر برای تولید سیگنال بیشتر
    long_ok = (
        ind["price_above_trend"] and ind["is_trending"]
        and ind["macd_hist"] > 0 and ind["plus_di"] > ind["minus_di"]
        and 45 <= ind["rsi"] <= 75   # گسترده‌تر
        and 15 <= ind["stoch_k"] <= 85
        and 0.1 <= ind["bb_percent"] <= 0.9
        and ind["volume_ratio"] >= 0.5  # نرم‌تر
        and (ind["higher_tf_trend_up"] is None or ind["higher_tf_trend_up"] is True)
    )
    short_ok = (
        not ind["price_above_trend"] and ind["is_trending"]
        and ind["macd_hist"] < 0 and ind["minus_di"] > ind["plus_di"]
        and 25 <= ind["rsi"] <= 55
        and 15 <= ind["stoch_k"] <= 85
        and 0.1 <= ind["bb_percent"] <= 0.9
        and ind["volume_ratio"] >= 0.5
        and (ind["higher_tf_trend_up"] is None or ind["higher_tf_trend_up"] is False)
    )
    if long_ok:
        return "LONG"
    if short_ok:
        return "SHORT"
    return None

def build_ladder_weighted(ind: dict, direction: str) -> tuple:
    price, atr = ind["price"], ind["atr"]
    entries = [
        price - (atr * m) if direction == "LONG" else price + (atr * m)
        for m in ENTRY_LADDER_ATR
    ]
    avg_entry = sum(e * w for e, w in zip(entries, ENTRY_WEIGHTS))
    stop_loss = avg_entry - (SL_ATR_MULT * atr) if direction == "LONG" else avg_entry + (SL_ATR_MULT * atr)
    take_profit = avg_entry + (TP_ATR_MULT * atr) if direction == "LONG" else avg_entry - (TP_ATR_MULT * atr)
    return entries, [stop_loss], [take_profit]

def get_funding_rate(symbol: str) -> float:
    try:
        funding = exchange.fetch_funding_rate(symbol.replace("/USDT", "/USDT:USDT"))
        return funding.get("fundingRate", 0.0) * 100
    except Exception:
        return 0.0

async def generate_trade_plan(symbol: str) -> Optional[TradePlan]:
    ind = await cache.get_indicators(symbol)
    if not ind:
        return None
    direction = decide_direction(ind)
    if not direction:
        return None

    confidence = compute_confidence(direction, ind)
    entries, stop_losses, take_profits = build_ladder_weighted(ind, direction)
    funding = get_funding_rate(symbol)

    leverage = 1
    if confidence >= 80:
        leverage = 3
    elif confidence >= 70:
        leverage = 2

    return TradePlan(
        symbol=symbol,
        direction=direction,
        trend=ind["trend_label"],
        rsi=ind["rsi"],
        current_price=ind["price"],
        confidence=confidence,
        entries=entries,
        stop_losses=stop_losses,
        take_profits=take_profits,
        funding_rate=funding,
        leverage=leverage,
    )

async def refresh_all_plans() -> dict[str, TradePlan]:
    if time.time() - cache.last_ohlcv_update > 300:
        await cache.update_ohlcv()

    sem = asyncio.Semaphore(10)

    async def generate_one(symbol):
        async with sem:
            try:
                return await generate_trade_plan(symbol)
            except Exception as e:
                logger.error(f"❌ خطا در تولید سیگنال {symbol}: {e}")
                return None

    tasks = [generate_one(sym) for sym in cache.valid_symbols]
    results = await asyncio.gather(*tasks)
    plans = {p.symbol: p for p in results if p is not None}
    last_plans.clear()
    last_plans.update(plans)
    logger.info(f"📈 تعداد سیگنال‌های فعال: {len(plans)}")
    return last_plans

# ---------- توابع تحلیل (نسخه‌های Async با بروزرسانی کش) ----------
async def generate_status_text_async(symbol: str, code: str, chat_id: int) -> str:
    ind = await cache.get_indicators(symbol)
    if not ind:
        icon = COIN_ICONS.get(code, "🔸")
        return rtl_lines(
            f"{icon} *{code}*\n\n"
            "⚠️ داده‌های تحلیل هنوز بارگذاری نشده‌اند.\n"
            "لطفاً چند لحظه دیگر دوباره تلاش کن یا از دکمه‌ی «🔄 بروزرسانی» استفاده کن."
        )
    
    icon = COIN_ICONS.get(code, "🔸")
    direction = decide_direction(ind)
    
    if ind["adx"] >= 25:
        adx_desc = "روند قوی و قابل‌اعتماد 💪"
    elif ind["adx"] >= ADX_TREND_THRESHOLD:
        adx_desc = "روند متوسط، نه خیلی قوی 🙂"
    else:
        adx_desc = "بازار رِنج و بدون روند مشخص 😐"

    if ind["macd_hist"] > 0:
        macd_desc = "مثبت و رو به تقویت مومنتوم صعودی 📈"
    elif ind["macd_hist"] < 0:
        macd_desc = "منفی و رو به تقویت مومنتوم نزولی 📉"
    else:
        macd_desc = "نزدیک خط صفر، خنثی ⚖️"

    rsi_val = ind["rsi"]
    if rsi_val > 70:
        rsi_desc = "اشباع خرید ⚠️ (احتمال اصلاح موقت بیشتره)"
    elif rsi_val < 30:
        rsi_desc = "اشباع فروش ⚠️ (احتمال برگشت موقت بیشتره)"
    else:
        rsi_desc = "منطقه‌ی نرمال، نه اشباع خرید نه فروش"

    vol_ratio = ind["volume_ratio"]
    if vol_ratio >= 1.3:
        volume_desc = f"بالاتر از حد معمول ({vol_ratio:.1f}× میانگین) — مشارکت بازار قویه 🔊"
    elif vol_ratio >= 0.8:
        volume_desc = f"نزدیک به میانگین معمول ({vol_ratio:.1f}×) 🔉"
    else:
        volume_desc = f"پایین‌تر از میانگین ({vol_ratio:.1f}×) — حرکت ممکنه ضعیف/غیرواقعی باشه 🔈"

    stoch_val = ind["stoch_k"]
    if stoch_val > 80:
        stoch_desc = "منطقه‌ی اشباع خرید ⚠️"
    elif stoch_val < 20:
        stoch_desc = "منطقه‌ی اشباع فروش ⚠️"
    else:
        stoch_desc = "منطقه‌ی نرمال"

    bb_val = ind["bb_percent"]
    if bb_val >= 1.0:
        bb_desc = "بالای باند بولینگر (نوسان شدید/اوج حرکت) 🎢"
    elif bb_val <= 0.0:
        bb_desc = "زیر باند بولینگر (نوسان شدید/کف حرکت) 🎢"
    elif bb_val >= 0.8:
        bb_desc = "نزدیک باند بالایی"
    elif bb_val <= 0.2:
        bb_desc = "نزدیک باند پایینی"
    else:
        bb_desc = "وسط محدوده، عادی"

    if ind["higher_tf_trend_up"] is True:
        htf_desc = "هم‌جهت با روند صعودی تایم‌فریم ۴ ساعته ✅"
    elif ind["higher_tf_trend_up"] is False:
        htf_desc = "هم‌جهت با روند نزولی تایم‌فریم ۴ ساعته ✅"
    else:
        htf_desc = "در دسترس نبود"

    if direction == "LONG":
        scenario = (
            "🔮 سناریوی محتمل‌تر *ادامه‌ی روند صعودیه*، به شرطی که قیمت بالای EMA200 بمونه، "
            "حجم معاملات از میانگین کمتر نشه و RSI وارد منطقه‌ی اشباع خرید (بالای ۷۰) نشه.\n"
            "⚠️ اگه MACD ضعیف بشه، ADX پایین بیاد یا Stochastic RSI به منطقه‌ی اشباع خرید برسه، "
            "احتمال توقف یا اصلاح روند بیشتر می‌شه."
        )
    elif direction == "SHORT":
        scenario = (
            "🔮 سناریوی محتمل‌تر *ادامه‌ی روند نزولیه*، به شرطی که قیمت زیر EMA200 بمونه، "
            "حجم معاملات از میانگین کمتر نشه و RSI وارد منطقه‌ی اشباع فروش (زیر ۳۰) نشه.\n"
            "⚠️ اگه MACD ضعیف بشه، ADX پایین بیاد یا Stochastic RSI به منطقه‌ی اشباع فروش برسه، "
            "احتمال برگشت یا اصلاح بیشتر می‌شه."
        )
    else:
        scenario = (
            "🔮 فعلاً اندیکاتورها هم‌جهت نیستن (یا بازار رِنجه، یا حجم/تایم‌فریم بالاتر تأییدش نمی‌کنه)، "
            "یعنی نه سیگنال خرید واضحیه نه فروش.\n"
            "بهتره صبر کنی تا شرایط هم‌جهت بشن."
        )

    header = f"🧭 *وضعیت لحظه‌ای* {icon} *{sym(code)}*\n🕒 {shamsi_now()}\n{DIVIDER}\n"
    body = (
        f"💰 قیمت لحظه‌ای: {fmt_amount(ind['price'], chat_id)}\n"
        f"📊 روند کلی (EMA200): {ind['trend_label']}\n"
        f"⚡ قدرت روند (ADX {ind['adx']:.1f}): {adx_desc}\n"
        f"📈 مومنتوم (MACD): {macd_desc}\n"
        f"🎯 RSI ({rsi_val:.1f}): {rsi_desc}\n"
        f"🌀 Stochastic RSI ({stoch_val:.0f}): {stoch_desc}\n"
        f"📏 موقعیت در باند بولینگر: {bb_desc}\n"
        f"🔊 حجم معاملات: {volume_desc}\n"
        f"🗺️ تایم‌فریم بالاتر (۴ساعته): {htf_desc}\n"
        f"{DIVIDER}\n"
        f"{scenario}\n"
    )

    if direction:
        entries, stop_losses, take_profits = build_ladder_weighted(ind, direction)
        confidence = compute_confidence(direction, ind)
        dir_txt = "🟢 لانگ (خرید)" if direction == "LONG" else "🔴 شورت (فروش)"
        badge = confidence_badge(confidence)
        ladder = format_ladder_block(entries, take_profits, stop_losses, chat_id)
        funding = get_funding_rate(symbol)
        funding_txt = f"\n💰 نرخ فاندینگ: {funding:+.3f}%" if funding != 0 else ""
        footer = (
            f"{DIVIDER}\n"
            f"📐 *پیشنهاد معاملاتی فعلی*: {dir_txt}  |  اطمینان: *{confidence:.0f}٪* ({badge}){funding_txt}\n\n"
            f"{ladder}\n"
        )
    else:
        footer = f"{DIVIDER}\n💤 فعلاً پله‌ی ورود/خروج مشخصی پیشنهاد نمی‌شه.\n"

    warn = "\n⚠️ این یک تفسیر فنیه، نه پیش‌بینی قطعی یا توصیه مالی. بازار همیشه می‌تونه برخلاف انتظار حرکت کنه."
    return rtl_lines(header + body + footer + warn)

async def generate_weekly_summary_async(symbol: str, code: str, chat_id: int) -> str:
    icon = COIN_ICONS.get(code, "🔸")
    week_df = await cache.get_weekly_data(symbol)
    if week_df is None or len(week_df) < 2:
        # تلاش برای دریافت مجدد داده‌های روزانه
        await cache.update_ohlcv()
        week_df = await cache.get_weekly_data(symbol)
        if week_df is None or len(week_df) < 2:
            return rtl_lines(
                f"{icon} *{code}*\n\n"
                "⚠️ داده‌های کافی برای تحلیل هفتگی در دسترس نیست.\n"
                "لطفاً چند ساعت دیگر دوباره تلاش کن."
            )

    week_ago_price = week_df["close"].iloc[0]
    current_price = week_df["close"].iloc[-1]
    pct_change = (current_price - week_ago_price) / week_ago_price * 100
    highest = week_df["high"].max()
    lowest = week_df["low"].min()
    highest_date = shamsi_date(week_df.loc[week_df["high"].idxmax(), "timestamp"])
    lowest_date = shamsi_date(week_df.loc[week_df["low"].idxmin(), "timestamp"])

    daily_pct = week_df["close"].pct_change() * 100
    idx_max = daily_pct.abs().idxmax()
    best_day_pct = daily_pct.loc[idx_max] if pd.notna(daily_pct.loc[idx_max]) else 0.0
    best_day_shamsi = shamsi_date(week_df.loc[idx_max, "timestamp"])

    volatility = daily_pct.std()
    up_days = int((daily_pct > 0).sum())
    down_days = int((daily_pct < 0).sum())
    avg_volume = week_df["volume"].mean()

    try:
        daily_rsi = RSIIndicator(week_df["close"], window=14).rsi().iloc[-1]
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

    text = (
        f"📊 *تحلیل ۷ روز اخیر* {icon} *{code}*\n"
        f"🕒 لحظه‌ی تحلیل: {shamsi_now()}\n{DIVIDER}\n"
        f"قیمت ۷ روز پیش: {fmt_amount(week_ago_price, chat_id)}\n"
        f"قیمت الان: {fmt_amount(current_price, chat_id)}\n"
        f"تغییر هفتگی: *{pct_change:+.2f}٪* — {trend_desc}\n\n"
        f"📈 بیشترین قیمت هفته: {fmt_amount(highest, chat_id)}\n"
        f"   📅 {highest_date}\n"
        f"📉 کمترین قیمت هفته: {fmt_amount(lowest, chat_id)}\n"
        f"   📅 {lowest_date}\n"
        f"{DIVIDER}\n"
        f"⚡ بیشترین نوسان یک‌روزه: *{best_day_pct:+.2f}٪*\n"
        f"   📅 {best_day_shamsi}\n\n"
        f"📐 نوسان‌پذیری هفته: *{volatility:.2f}٪*\n"
        f"🟢 روزهای مثبت: {up_days}  |  🔴 روزهای منفی: {down_days}\n"
        f"📊 میانگین حجم روزانه: `{avg_volume:,.0f}`\n"
        f"🎯 RSI روزانه فعلی: *{rsi_txt}* {rsi_note}\n"
        f"{DIVIDER}\n"
        f"ℹ️ این خلاصه فقط بر پایه‌ی داده‌ی قیمته؛ دلیل خبری/بنیادی افت یا رشد در این ابزار در دسترس نیست."
    )
    return rtl_lines(text)

# ---------- قالب‌بندی ----------
DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
BIG_DIVIDER = "═══════════════"

def format_prices_pretty(prices: dict[str, float], chat_id: int) -> str:
    if not prices:
        return "⚠️ دریافت قیمت لحظه‌ای الان ممکن نشد."
    lines = ["💰 *قیمت لحظه‌ای ارزها*", f"🕒 {shamsi_now()}", DIVIDER]
    for symbol, price in prices.items():
        code = symbol.split("/")[0]
        icon = COIN_ICONS.get(code, "🔸")
        lines.append(f"{icon} *{code}*   {fmt_amount(price, chat_id)}")
    return rtl_lines("\n".join(lines))

def format_ladder_block(entries, take_profits, stop_losses, chat_id) -> str:
    nums = ["1️⃣", "2️⃣", "3️⃣"]
    entries_txt = "\n".join(f"   {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(entries))
    tp_txt = "\n".join(f"   {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(take_profits))
    sl_txt = "\n".join(f"   {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(stop_losses))
    return (
        f"📥 *نقاط ورود (۳ پله)*\n{entries_txt}\n\n"
        f"🎯 *حد سود* (میانگین ورود + {TP_ATR_MULT} ATR)\n{tp_txt}\n\n"
        f"🛑 *حد ضرر* (میانگین ورود ± {SL_ATR_MULT} ATR)\n{sl_txt}"
    )

def format_plan_pretty(plan: TradePlan, code: str, chat_id: int) -> str:
    icon = COIN_ICONS.get(code, "🔸")
    dir_txt = "🟢 لانگ (خرید) 💹" if plan.direction == "LONG" else "🔴 شورت (فروش) 🔻"
    emoji = mood_emoji(plan)
    badge = confidence_badge(plan.confidence)
    ladder = format_ladder_block(plan.entries, plan.take_profits, plan.stop_losses, chat_id)
    funding_txt = f"\n💰 نرخ فاندینگ: {plan.funding_rate:+.3f}%" if plan.funding_rate != 0 else ""

    text = (
        f"{emoji} {icon} *{sym(code)}* — {dir_txt}\n"
        f"🕒 {shamsi_now()}\n"
        f"📊 روند: {plan.trend}  |  RSI: {plan.rsi:.1f}\n"
        f"🎯 اطمینان: *{plan.confidence:.0f}٪*  ({badge})\n"
        f"⚡️ اهرم پیشنهادی: {plan.leverage}x{funding_txt}\n"
        f"{DIVIDER}\n"
        f"💰 *قیمت لحظه‌ای*\n   {fmt_amount(plan.current_price, chat_id)}\n\n"
        f"{ladder}\n"
        f"{DIVIDER}\n"
        f"💡 بعد از رسیدن به سود پله ۱، حد ضرر رو به نقطه ورود منتقل کن.\n"
        f"⚠️ امتیاز اطمینان تخمین تکنیکاله، نه تضمین."
    )
    return rtl_lines(text)

def format_plan_compact(plan: TradePlan, code: str, chat_id: int) -> str:
    icon = COIN_ICONS.get(code, "🔸")
    emoji = mood_emoji(plan)
    dir_txt = "🟢 لانگ" if plan.direction == "LONG" else "🔴 شورت"
    funding_txt = f" | فاندینگ: {plan.funding_rate:+.2f}%" if plan.funding_rate != 0 else ""
    avg_entry = plan.entries[0]*0.5 + plan.entries[1]*0.3 + plan.entries[2]*0.2
    text = (
        f"{emoji} {icon} *{code}* — {dir_txt}  |  اطمینان: *{plan.confidence:.0f}٪*{funding_txt}\n"
        f"   ورود میانگین: {fmt_amount(avg_entry, chat_id)}\n"
        f"   سود: {fmt_amount(plan.take_profits[0], chat_id)}  |  ضرر: {fmt_amount(plan.stop_losses[0], chat_id)}"
    )
    return rtl_lines(text)

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

async def clear_overlay(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    ids = overlay_messages.pop(chat_id, [])
    for mid in ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass

async def track_auto_message(app_or_ctx, chat_id: int, message_id: int):
    history = auto_message_history.setdefault(chat_id, [])
    history.append(message_id)
    while len(history) > AUTO_KEEP_LAST_N:
        old_id = history.pop(0)
        try:
            await app_or_ctx.bot.delete_message(chat_id=chat_id, message_id=old_id)
        except Exception:
            pass

# ---------- کیبوردها ----------
def build_grid_keyboard(buttons: list[InlineKeyboardButton], columns: int) -> list[list[InlineKeyboardButton]]:
    rows = [buttons[i:i + columns] for i in range(0, len(buttons), columns)]
    if rows and len(rows[-1]) < columns:
        missing = columns - len(rows[-1])
        rows[-1] = rows[-1] + [InlineKeyboardButton("\u2063", callback_data="noop") for _ in range(missing)]
    return rows

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
        rows.append([
            InlineKeyboardButton("⚙️ پنل مدیریت ویژه", callback_data="admin_panel"),
            InlineKeyboardButton("\u2063", callback_data="noop"),
        ])
    return InlineKeyboardMarkup(rows)

def kb_back_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")]])

def kb_coins() -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(f"{COIN_ICONS[c]} {c}", callback_data=f"coin_{c}") for c in COIN_CODES]
    rows = build_grid_keyboard(buttons, COINS_GRID_COLUMNS)
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")])
    return InlineKeyboardMarkup(rows)

def kb_coin_detail(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧭 وضعیت لحظه‌ای", callback_data=f"suggest_{code}")],
        [InlineKeyboardButton("📆 تحلیل ۷ روز اخیر", callback_data=f"weekly_{code}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_coins")],
    ])

def kb_suggestion(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"suggest_{code}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"coin_{code}")],
        [InlineKeyboardButton("📋 لیست ارزها", callback_data="menu_coins")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")],
    ])

def kb_suggestion_from_auto(code: str) -> InlineKeyboardMarkup:
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
    buttons = []
    for p in top_plans:
        code = p.symbol.split("/")[0]
        buttons.append(InlineKeyboardButton(f"{COIN_ICONS.get(code, '🔸')} {code}", callback_data=f"suggest_{code}_auto"))
    rows = build_grid_keyboard(buttons, 3)
    rows.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")])
    return InlineKeyboardMarkup(rows)

# ---------- متن‌ها ----------
def welcome_text() -> str:
    text = (
        "🌟 *به سیگنالستان خوش اومدی!* 🌟\n"
        f"{DIVIDER}\n"
        f"🛰️ در حال رصد {len(COIN_CODES)} ارز هستم\n"
        "⏱️ هر ۱۵ دقیقه بهترین سیگنال‌های فعال رو با ⚡️ امتیاز اطمینان برات می‌فرستم\n"
        "👇 برای بررسی دستی، از منوی زیر استفاده کن\n\n"
        "برای توقف اشتراک: /stop\n\n"
        "⚠️ ابزار تحلیل تکنیکاله، نه توصیه مالی. تصمیم و ریسک نهایی با خودته."
    )
    return rtl_lines(text)

MENU_PROMPT = "👇 یکی از گزینه‌ها رو انتخاب کن:"
MAIN_MENU_HEADER = "✨ *پنل سیگنال‌یار* ✨\n" + DIVIDER + "\n" + MENU_PROMPT

# ---------- توابع اصلی ----------
async def finish_start(context: ContextTypes.DEFAULT_TYPE, chat_id: int, user_id: int):
    if is_admin(user_id):
        await context.bot.set_my_commands(
            [
                BotCommand("start", "شروع ربات"),
                BotCommand("menu", "منوی اصلی"),
                BotCommand("status", "وضعیت سیستم"),
                BotCommand("stop", "لغو اشتراک"),
            ],
            scope=BotCommandScopeChat(chat_id=chat_id),
        )
    else:
        await context.bot.set_my_commands(
            [BotCommand("menu", "منوی اصلی")],
            scope=BotCommandScopeChat(chat_id=chat_id),
        )
    await clear_interactive_screen(context, chat_id)
    msg = await context.bot.send_message(chat_id=chat_id, text=welcome_text(), reply_markup=kb_main(user_id), parse_mode="Markdown")
    set_interactive_screen(chat_id, [msg.message_id])
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

    if data == "noop":
        return

    if data.startswith("cur_"):
        user_currency[chat_id] = data.split("_", 1)[1]
        subscribed_chat_ids.add(chat_id)
        save_state()
        try:
            await query.message.delete()
        except Exception:
            pass
        await finish_start(context, chat_id, user_id)
        return

    if data == "restart_currency":
        subscribed_chat_ids.add(chat_id)
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text("👋 واحد پولی نمایش قیمت‌ها رو دوباره انتخاب کن:", reply_markup=kb_currency())
        set_interactive_screen(chat_id, [query.message.message_id])
        return

    if data == "close_temp":
        await clear_overlay(context, chat_id)
        return

    if data.startswith("suggest_") and data.endswith("_auto"):
        code = data[len("suggest_"):-len("_auto")]
        symbol = SYMBOL_MAP.get(code)
        await clear_overlay(context, chat_id)
        await query.edit_message_text("⏳ در حال دریافت داده‌های بازار...")
        try:
            await asyncio.wait_for(cache.update_ohlcv(), timeout=45)  # افزایش timeout
        except asyncio.TimeoutError:
            await query.edit_message_text("⏰ دریافت داده‌ها بیش از حد طول کشید. لطفاً دوباره تلاش کن.", reply_markup=kb_back_main())
            return
        try:
            text = await asyncio.wait_for(generate_status_text_async(symbol, code, chat_id), timeout=25)
        except asyncio.TimeoutError:
            text = f"🔸 *{code}*\n\nتحلیل بیش از حد طول کشید. لطفاً دوباره تلاش کن."
        msg = await context.bot.send_message(
            chat_id=chat_id, text=text, reply_markup=kb_suggestion_from_auto(code), parse_mode="Markdown",
        )
        overlay_messages[chat_id] = [msg.message_id]
        return

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
        await query.edit_message_text("⏳ در حال دریافت قیمت لحظه‌ای...")
        if time.time() - cache.last_price_update > 120:
            await cache.update_prices()
        prices = cache.prices
        text = format_prices_pretty(prices, chat_id)
        await query.edit_message_text(text, reply_markup=kb_back_main(), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id])

    elif data == "menu_coins":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        coins_header = f"🪙 *انتخاب ارز مورد نظر*\n{DIVIDER}\n{MENU_PROMPT}"
        await query.edit_message_text(coins_header, reply_markup=kb_coins(), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id])

    elif data.startswith("coin_"):
        code = data.split("_", 1)[1]
        icon = COIN_ICONS.get(code, "🔸")
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        text = f"{icon} *{sym(code)}*\n{DIVIDER}\n{MENU_PROMPT}"
        await query.edit_message_text(rtl_lines(text), reply_markup=kb_coin_detail(code), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id])

    elif data.startswith("suggest_"):
        code = data.split("_", 1)[1]
        symbol = SYMBOL_MAP.get(code)
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text("⏳ در حال دریافت داده‌های بازار...")
        try:
            await asyncio.wait_for(cache.update_ohlcv(), timeout=45)
        except asyncio.TimeoutError:
            await query.edit_message_text("⏰ دریافت داده‌ها بیش از حد طول کشید. لطفاً دوباره تلاش کن.", reply_markup=kb_back_main())
            set_interactive_screen(chat_id, [query.message.message_id])
            return
        try:
            text = await asyncio.wait_for(generate_status_text_async(symbol, code, chat_id), timeout=25)
        except asyncio.TimeoutError:
            text = f"🔸 *{code}*\n\nتحلیل بیش از حد طول کشید. لطفاً دوباره تلاش کن."
        await query.edit_message_text(split_long_message(text)[0], reply_markup=kb_suggestion(code), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id])

    elif data.startswith("weekly_"):
        code = data.split("_", 1)[1]
        symbol = SYMBOL_MAP.get(code)
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text("⏳ در حال دریافت داده‌های هفتگی...")
        try:
            await asyncio.wait_for(cache.update_ohlcv(), timeout=45)
        except asyncio.TimeoutError:
            await query.edit_message_text("⏰ دریافت داده‌ها بیش از حد طول کشید. لطفاً دوباره تلاش کن.", reply_markup=kb_back_main())
            set_interactive_screen(chat_id, [query.message.message_id])
            return
        try:
            summary = await asyncio.wait_for(generate_weekly_summary_async(symbol, code, chat_id), timeout=30)
        except asyncio.TimeoutError:
            summary = f"🔸 *{code}*\n\nدریافت داده‌های هفتگی بیش از حد طول کشید."
        await query.edit_message_text(summary, reply_markup=kb_weekly(code), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id])

    elif data == "menu_all":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text("⏳ در حال تحلیل همه‌ی ارزها... (حداکثر ۶۰ ثانیه)")
        try:
            plans = await asyncio.wait_for(refresh_all_plans(), timeout=60)
        except asyncio.TimeoutError:
            await query.edit_message_text(
                "⏰ تحلیل همه ارزها بیش از حد طول کشید. لطفاً دوباره تلاش کن.",
                reply_markup=kb_back_main()
            )
            set_interactive_screen(chat_id, [query.message.message_id])
            return

        if not plans:
            text = f"📋 *نمایش همه پیشنهادات*\n🕒 {shamsi_now()}\n\n"
            text += "😴 در حال حاضر هیچ سیگنال واضحی روی ارزها وجود ندارد.\n"
            text += "🔍 ممکن است بازار در حالت رنج باشد یا شرایط هم‌جهت نباشد.\n"
            text += "⏳ سعی کنید بعداً دوباره بررسی کنید."
            await query.edit_message_text(text, reply_markup=kb_back_main(), parse_mode="Markdown")
            set_interactive_screen(chat_id, [query.message.message_id])
            return

        sorted_plans = sorted(plans.values(), key=lambda p: p.confidence, reverse=True)
        full_text = f"📋 *نمایش همه پیشنهادات*\n🕒 {shamsi_now()}\n\n" + f"\n\n{BIG_DIVIDER}\n\n".join(
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
            f"🕒 {shamsi_now()}\n"
            f"👥 اعضای فعال: {len(subscribed_chat_ids)}\n"
            f"⚡️ سیگنال‌های فعال الان: {len(last_plans)}\n"
            f"🪙 تعداد ارز تحت رصد: {len(COIN_CODES)}\n"
            f"⏱️ فاصله گزارش خودکار: {CHECK_INTERVAL_SECONDS // 60} دقیقه"
        )
        await query.edit_message_text(rtl_lines(text), reply_markup=kb_admin_panel(), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id])

# ---------- ارسال خودکار ----------
async def auto_report_loop(app: Application):
    while True:
        try:
            if subscribed_chat_ids:
                await cache.update_prices()
                await cache.update_ohlcv()
                plans = await refresh_all_plans()
                top_plans = sorted(plans.values(), key=lambda p: p.confidence, reverse=True)[:TOP_SIGNALS_COUNT] if plans else []

                send_tasks = []
                for chat_id in list(subscribed_chat_ids):
                    send_tasks.append(send_report_to_user(app, chat_id, top_plans))
                await asyncio.gather(*send_tasks, return_exceptions=True)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(f"❌ خطا در حلقه خودکار: {e}")
            await asyncio.sleep(60)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)

async def send_report_to_user(app: Application, chat_id: int, top_plans: list[TradePlan]):
    header = f"📢✨ *پیشنهادات لحظه‌ای* ✨📢\n🕒 {shamsi_now()}\n{BIG_DIVIDER}\n\n"
    if top_plans:
        body = f"\n\n{DIVIDER}\n\n".join(
            format_plan_compact(p, p.symbol.split("/")[0], chat_id) for p in top_plans
        )
        footer = "\n\n⚠️ امتیاز اطمینان تخمینیه، نه تضمینی.\n👇 برای جزئیات هر ارز، دکمه‌ش رو لمس کن."
        keyboard = kb_auto_report(top_plans)
    else:
        body = "😴 فعلاً سیگنال واضحی روی هیچ‌کدوم از ارزها نیست."
        footer = "\n🔍 ممکن است بازار در حالت رنج باشد یا شرایط هم‌جهت نباشد."
        keyboard = kb_back_main()

    text = rtl_lines(header) + body + footer
    try:
        chunks = split_long_message(text)
        for chunk in chunks[:-1]:
            m = await app.bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")
            await track_auto_message(app, chat_id, m.message_id)
        m_last = await app.bot.send_message(chat_id=chat_id, text=chunks[-1], reply_markup=keyboard, parse_mode="Markdown")
        await track_auto_message(app, chat_id, m_last.message_id)
    except Exception as e:
        logger.error(f"ارسال به {chat_id} ناموفق بود: {e}")

# ---------- دستورات ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    chat_id = update.effective_chat.id
    await clear_interactive_screen(context, chat_id)
    msg = await update.message.reply_text("👋 واحد پولی نمایش قیمت‌ها رو انتخاب کن:", reply_markup=kb_currency())
    set_interactive_screen(chat_id, [msg.message_id])

async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard(update):
        return
    subscribed_chat_ids.discard(update.effective_chat.id)
    save_state()
    await update.message.reply_text("❌ اشتراک قطع شد. هر وقت خواستی، از منو گزینه‌ی «🔄 شروع مجدد» رو بزن یا /start رو بزن.")

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
        f"🕒 {shamsi_now()}\n"
        f"در حال رصد: {', '.join(COIN_CODES)}\n"
        f"تایم‌فریم: {TIMEFRAME}\n"
        f"فاصله گزارش خودکار: هر {CHECK_INTERVAL_SECONDS // 60} دقیقه\n"
        f"تعداد اعضا: {len(subscribed_chat_ids)}\n"
        f"سیگنال‌های فعال الان: {len(last_plans)}\n"
        f"منبع نرخ تومان: {_irt_rate_cache.get('source') or 'نامشخص'}"
    )

# ---------- ذخیره‌سازی ----------
def save_state():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        temp_file = STATE_FILE + ".tmp"
        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump({
                "subscribed_chat_ids": list(subscribed_chat_ids),
                "user_currency": user_currency,
            }, f)
        os.replace(temp_file, STATE_FILE)
        logger.debug("✅ وضعیت ذخیره شد")
    except Exception as e:
        logger.warning(f"⚠️ خطا در ذخیره‌سازی: {e}")

def load_state():
    global subscribed_chat_ids, user_currency
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        subscribed_chat_ids = set(data.get("subscribed_chat_ids", []))
        user_currency = {int(k): v for k, v in data.get("user_currency", {}).items()}
        logger.info(f"✅ وضعیت قبلی بازیابی شد: {len(subscribed_chat_ids)} کاربر")
    except FileNotFoundError:
        logger.info("ℹ️ فایل ذخیره‌سازی پیدا نشد؛ از صفر شروع می‌شه.")
    except Exception as e:
        logger.warning(f"⚠️ خطا در خواندن وضعیت: {e}")

# ---------- راه‌اندازی ----------
async def post_init(app: Application):
    await app.bot.set_my_commands([
        BotCommand("start", "شروع ربات"),
        BotCommand("menu", "منوی اصلی"),
    ])
    app.create_task(auto_report_loop(app))
    logger.info("🚀 ربات راه‌اندازی شد!")

def main():
    if not BOT_TOKEN:
        raise RuntimeError("❌ BOT_TOKEN تنظیم نشده!")
    if not ALLOWED_USER_IDS:
        logger.warning("⚠️ ALLOWED_USER_IDS تنظیم نشده — بات فعلاً برای همه باز است!")

    load_state()

    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("✅ ربات V5 در حال اجراست...")
    app.run_polling()

if __name__ == "__main__":
    main()
