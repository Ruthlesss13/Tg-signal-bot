"""
Telegram Signal Bot V6
اصلاحات اصلی:
1) تبدیل خروجی fetch_ohlcv از list به DataFrame
2) نرمال‌سازی timestamp و جلوگیری از مشکل داده هفتگی
3) پشتیبانی صحیح از نمادهای Futures/Swap در MEXC (:USDT)
4) جلوگیری از چند بار بروزرسانی سنگین همزمان
5) منطق سیگنال امتیازی‌تر تا در صورت هم‌جهت بودن چند اندیکاتور، سیگنال تولید شود
6) گزارش خطای واقعی در لاگ
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime

import ccxt
import jdatetime
import pandas as pd
import requests
from dotenv import load_dotenv
from ta.momentum import RSIIndicator, StochRSIIndicator
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.volatility import AverageTrueRange, BollingerBands
from telegram import BotCommand, BotCommandScopeChat, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

try:
    from zoneinfo import ZoneInfo
    TEHRAN_TZ = ZoneInfo("Asia/Tehran")
except Exception:
    TEHRAN_TZ = None

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("signal_bot")

# =========================
# ENV
# =========================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USER_IDS = {
    int(x) for x in os.getenv("ALLOWED_USER_IDS", "").split(",")
    if x.strip().isdigit()
}
ADMIN_USER_IDS = {
    int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",")
    if x.strip().isdigit()
}
ALWAYS_ALLOWED_USER_IDS = {
    int(x) for x in os.getenv("ALWAYS_ALLOWED_USER_IDS", "").split(",")
    if x.strip().isdigit()
}

# =========================
# SETTINGS
# =========================
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
SPOT_SYMBOL_MAP = {code: f"{code}/USDT" for code in COIN_CODES}
TIMEFRAME = "1h"

CHECK_INTERVAL_SECONDS = 15 * 60
TOP_SIGNALS_COUNT = 5

ADX_TREND_THRESHOLD = 16
MIN_SIGNAL_CONFIDENCE = 60

ENTRY_LADDER_ATR = [0.0, 0.6, 1.2]
ENTRY_WEIGHTS = [0.5, 0.3, 0.2]
SL_ATR_MULT = 2.0
TP_ATR_MULT = 4.0

TELEGRAM_MSG_LIMIT = 3500
IRT_RATE_TTL_SECONDS = 300
COINS_GRID_COLUMNS = 4
AUTO_KEEP_LAST_N = 3

RLM = "\u200f"
DATA_DIR = os.getenv("DATA_DIR", "/data")
STATE_FILE = os.path.join(DATA_DIR, "state.json")

# =========================
# EXCHANGE
# =========================
exchange = ccxt.mexc({
    "enableRateLimit": True,
    "options": {
        "defaultType": "swap",
        "adjustForTimeDifference": True,
    },
})

# =========================
# STATE
# =========================
last_plans = {}
subscribed_chat_ids = set()
user_currency = {}
auto_message_history = {}
overlay_messages = {}
interactive_screen_messages = {}
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


# =========================
# MARKET DATA CACHE
# =========================
class MarketDataCache:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self.prices = {}
        self.ohlcv_1h = {}
        self.ohlcv_4h = {}
        self.ohlcv_1d = {}
        self.valid_symbols = []
        self.exchange_symbols = {}
        self.last_price_update = 0.0
        self.last_ohlcv_update = 0.0
        self._sem = asyncio.Semaphore(6)
        self._update_lock = asyncio.Lock()

        self._load_markets()

    def _load_markets(self):
        try:
            markets = exchange.load_markets()

            for code in COIN_CODES:
                candidates = [
                    f"{code}/USDT:USDT",
                    f"{code}/USDT",
                ]

                selected = None
                for candidate in candidates:
                    market = markets.get(candidate)
                    if market and market.get("active", True):
                        if market.get("swap") or candidate.endswith(":USDT"):
                            selected = candidate
                            break

                if selected is None:
                    # fallback to spot if swap market is unavailable
                    spot = f"{code}/USDT"
                    if spot in markets:
                        selected = spot

                if selected:
                    self.exchange_symbols[code] = selected

            self.valid_symbols = list(self.exchange_symbols.values())

            logger.info(
                "✅ بازارهای معتبر: %s از %s",
                len(self.valid_symbols),
                len(COIN_CODES),
            )

            if not self.valid_symbols:
                logger.error("❌ هیچ بازار معتبری پیدا نشد.")

        except Exception as e:
            logger.exception("❌ خطا در load_markets: %s", e)

    def symbol_for_code(self, code):
        return self.exchange_symbols.get(code)

    def code_for_symbol(self, symbol):
        for code, ex_symbol in self.exchange_symbols.items():
            if ex_symbol == symbol:
                return code
        return symbol.split("/")[0]

    @staticmethod
    def _to_dataframe(raw):
        if raw is None:
            return None

        if isinstance(raw, pd.DataFrame):
            df = raw.copy()
        else:
            if not isinstance(raw, (list, tuple)) or not raw:
                return None

            df = pd.DataFrame(
                raw,
                columns=[
                    "timestamp",
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                ],
            )

        required = ["timestamp", "open", "high", "low", "close", "volume"]
        for col in required:
            if col not in df.columns:
                return None

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # CCXT timestamp is milliseconds.
        if pd.api.types.is_numeric_dtype(df["timestamp"]):
            df["timestamp"] = pd.to_datetime(
                df["timestamp"], unit="ms", utc=True, errors="coerce"
            )
        else:
            df["timestamp"] = pd.to_datetime(
                df["timestamp"], utc=True, errors="coerce"
            )

        df = df.dropna(
            subset=["timestamp", "open", "high", "low", "close", "volume"]
        )
        df = df.drop_duplicates(subset=["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)

        return df if not df.empty else None

    async def update_prices(self):
        if not self.valid_symbols:
            self._load_markets()

        async def fetch_one(symbol):
            async with self._sem:
                try:
                    ticker = await asyncio.to_thread(exchange.fetch_ticker, symbol)
                    price = (
                        ticker.get("last")
                        or ticker.get("close")
                        or ticker.get("bid")
                        or ticker.get("ask")
                    )
                    return symbol, float(price) if price is not None else None
                except Exception as e:
                    logger.warning("⚠️ قیمت %s: %s", symbol, e)
                    return symbol, None

        results = await asyncio.gather(
            *(fetch_one(s) for s in self.valid_symbols)
        )

        self.prices = {
            symbol: price
            for symbol, price in results
            if price is not None
        }
        self.last_price_update = time.time()

        logger.info("💰 قیمت‌ها: %s نماد", len(self.prices))
        return self.prices

    async def update_ohlcv(self, force=False):
        async with self._update_lock:
            if (
                not force
                and self.last_ohlcv_update
                and time.time() - self.last_ohlcv_update < 60
            ):
                return

            if not self.valid_symbols:
                self._load_markets()

            async def fetch_one(symbol, timeframe):
                async with self._sem:
                    try:
                        raw = await asyncio.to_thread(
                            exchange.fetch_ohlcv,
                            symbol,
                            timeframe,
                            250,
                        )
                        df = self._to_dataframe(raw)

                        if df is None or len(df) < 5:
                            logger.warning(
                                "⚠️ داده ناکافی %s %s",
                                symbol,
                                timeframe,
                            )
                            return symbol, timeframe, None

                        return symbol, timeframe, df

                    except Exception as e:
                        logger.warning(
                            "⚠️ OHLCV %s %s: %s",
                            symbol,
                            timeframe,
                            e,
                        )
                        return symbol, timeframe, None

            tasks = []
            for symbol in self.valid_symbols:
                for tf in ("1h", "4h", "1d"):
                    tasks.append(fetch_one(symbol, tf))

            results = await asyncio.gather(*tasks)

            new_1h = {}
            new_4h = {}
            new_1d = {}

            for symbol, tf, df in results:
                if df is None:
                    continue
                if tf == "1h":
                    new_1h[symbol] = df
                elif tf == "4h":
                    new_4h[symbol] = df
                elif tf == "1d":
                    new_1d[symbol] = df

            self.ohlcv_1h = new_1h
            self.ohlcv_4h = new_4h
            self.ohlcv_1d = new_1d
            self.last_ohlcv_update = time.time()

            logger.info(
                "📊 کندل‌ها: %s 1h / %s 4h / %s 1d",
                len(self.ohlcv_1h),
                len(self.ohlcv_4h),
                len(self.ohlcv_1d),
            )

    async def ensure_symbol_data(self, symbol):
        if (
            symbol not in self.ohlcv_1h
            or symbol not in self.ohlcv_4h
            or symbol not in self.ohlcv_1d
        ):
            await self.update_ohlcv(force=True)

    async def get_indicators(self, symbol):
        await self.ensure_symbol_data(symbol)

        df = self.ohlcv_1h.get(symbol)
        df4 = self.ohlcv_4h.get(symbol)

        if df is None or len(df) < 210:
            logger.warning(
                "⚠️ %s داده 1h کافی ندارد: %s",
                symbol,
                0 if df is None else len(df),
            )
            return None

        try:
            ema200 = EMAIndicator(
                close=df["close"], window=200
            ).ema_indicator()

            rsi = RSIIndicator(
                close=df["close"], window=14
            ).rsi()

            atr = AverageTrueRange(
                high=df["high"],
                low=df["low"],
                close=df["close"],
                window=14,
            ).average_true_range()

            macd = MACD(
                close=df["close"],
                window_slow=26,
                window_fast=12,
                window_sign=9,
            )
            macd_hist = macd.macd_diff()

            adx_ind = ADXIndicator(
                high=df["high"],
                low=df["low"],
                close=df["close"],
                window=14,
            )
            adx = adx_ind.adx()
            plus_di = adx_ind.adx_pos()
            minus_di = adx_ind.adx_neg()

            stoch = StochRSIIndicator(
                close=df["close"],
                window=14,
                smooth1=3,
                smooth2=3,
            )
            stoch_k = stoch.stochrsi_k() * 100

            bb = BollingerBands(
                close=df["close"],
                window=20,
                window_dev=2,
            )
            bb_percent = bb.bollinger_pband()

            volume_sma = df["volume"].rolling(20).mean()
            volume_ratio = df["volume"] / volume_sma

            values = {
                "price": df["close"].iloc[-1],
                "rsi": rsi.iloc[-1],
                "atr": atr.iloc[-1],
                "ema200": ema200.iloc[-1],
                "macd_hist": macd_hist.iloc[-1],
                "adx": adx.iloc[-1],
                "plus_di": plus_di.iloc[-1],
                "minus_di": minus_di.iloc[-1],
                "stoch_k": stoch_k.iloc[-1],
                "bb_percent": bb_percent.iloc[-1],
                "volume_ratio": volume_ratio.iloc[-1],
            }

            if any(pd.isna(v) for v in values.values()):
                logger.warning("⚠️ اندیکاتور ناقص برای %s", symbol)
                return None

            higher_tf_up = None
            if df4 is not None and len(df4) >= 205:
                ema4 = EMAIndicator(
                    close=df4["close"], window=200
                ).ema_indicator().iloc[-1]

                if pd.notna(ema4):
                    higher_tf_up = bool(
                        df4["close"].iloc[-1] > ema4
                    )

            values["price_above_trend"] = bool(
                values["price"] > values["ema200"]
            )
            values["higher_tf_trend_up"] = higher_tf_up
            values["trend_label"] = (
                "صعودی 📈"
                if values["price_above_trend"]
                else "نزولی 📉"
            )
            values["is_trending"] = (
                values["adx"] >= ADX_TREND_THRESHOLD
            )

            return values

        except Exception as e:
            logger.exception(
                "❌ خطا در اندیکاتورها %s: %s",
                symbol,
                e,
            )
            return None

    async def get_weekly_data(self, symbol):
        await self.ensure_symbol_data(symbol)

        df = self.ohlcv_1d.get(symbol)
        if df is None or df.empty:
            logger.warning("⚠️ daily برای %s موجود نیست", symbol)
            return None

        # فقط 7 روز آخر، بدون وابستگی به تعداد کندل ثابت.
        end = df["timestamp"].iloc[-1]
        start = end - pd.Timedelta(days=7)

        week = df[df["timestamp"] >= start].copy()

        # اگر timestamp صرافی/کندل ناقص بود، آخرین 8 کندل را به عنوان fallback بگیر.
        if len(week) < 2:
            week = df.tail(min(8, len(df))).copy()

        return week if len(week) >= 2 else None


cache = MarketDataCache()


# =========================
# ACCESS / CURRENCY
# =========================
def is_allowed(user_id):
    if user_id in ALWAYS_ALLOWED_USER_IDS:
        return True
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS


def is_admin(user_id):
    return user_id in ADMIN_USER_IDS


async def guard(update):
    user = update.effective_user
    if user and not is_allowed(user.id):
        if update.message:
            await update.message.reply_text(
                "⛔️ این ربات خصوصی است و شما دسترسی ندارید."
            )
        elif update.callback_query:
            await update.callback_query.answer(
                "⛔️ دسترسی ندارید.",
                show_alert=True,
            )
        return False
    return True


def fetch_irt_rate_nobitex():
    last_error = None
    for _ in range(3):
        try:
            r = requests.get(
                "https://api.nobitex.ir/market/stats",
                params={
                    "srcCurrency": "usdt",
                    "dstCurrency": "rls",
                },
                timeout=8,
            )
            r.raise_for_status()
            rial = float(
                r.json()["stats"]["usdt-rls"]["latest"]
            )
            return rial / 10
        except Exception as e:
            last_error = e
            time.sleep(1)
    raise last_error


def fetch_irt_rate_wallex():
    r = requests.get(
        "https://api.wallex.ir/v1/markets",
        timeout=8,
    )
    r.raise_for_status()
    data = r.json()
    return float(
        data["result"]["symbols"]["USDTTMN"]["stats"]["lastPrice"]
    )


def get_irt_rate():
    now = time.time()

    if (
        _irt_rate_cache["value"] is not None
        and now - _irt_rate_cache["ts"] < IRT_RATE_TTL_SECONDS
    ):
        return _irt_rate_cache["value"]

    for name, fn in (
        ("nobitex", fetch_irt_rate_nobitex),
        ("wallex", fetch_irt_rate_wallex),
    ):
        try:
            rate = fn()
            if rate and rate > 0:
                _irt_rate_cache.update(
                    value=rate,
                    ts=now,
                    source=name,
                )
                return rate
        except Exception as e:
            logger.warning("نرخ تومان %s: %s", name, e)

    return _irt_rate_cache["value"]


def get_pref(chat_id):
    return user_currency.get(chat_id, "USDT")


def fmt_irt(value):
    if value >= 1:
        return f"{value:,.0f}"
    if value == 0:
        return "0"
    return f"{value:.10f}".rstrip("0").rstrip(".")


def fmt_amount(usdt_value, chat_id):
    usdt_txt = f"{RLM}`{usdt_value:,.10f}` USDT"
    pref = get_pref(chat_id)

    if pref == "USDT":
        return usdt_txt

    rate = get_irt_rate()
    if not rate:
        return usdt_txt + " _(نرخ تومان موقتاً در دسترس نیست)_"

    irt_txt = f"{RLM}`{fmt_irt(usdt_value * rate)}` تومان"

    if pref == "IRT":
        return irt_txt
    return f"{usdt_txt}\n        {irt_txt}"


def sym(code):
    return f"{RLM}{code}/USDT{RLM}"


def shamsi_now():
    dt = datetime.now(TEHRAN_TZ) if TEHRAN_TZ else datetime.now()
    j = jdatetime.datetime.fromgregorian(datetime=dt)
    return j.strftime("%Y/%m/%d - %H:%M")


def shamsi_date(dt):
    try:
        if hasattr(dt, "to_pydatetime"):
            dt = dt.to_pydatetime()
        if hasattr(dt, "date"):
            dt = dt.date()
        return jdatetime.date.fromgregorian(date=dt).strftime("%Y/%m/%d")
    except Exception:
        return "-"


def rtl_lines(text):
    return "\n".join(
        (RLM + line) if line.strip() else line
        for line in text.split("\n")
    )


# =========================
# SIGNAL ENGINE
# =========================
def confidence_badge(confidence):
    if confidence >= 90:
        return "🔥🔥 فوق‌العاده قوی"
    if confidence >= 85:
        return "🔥 خیلی قوی"
    if confidence >= 80:
        return "⚡ قوی"
    if confidence >= 75:
        return "✨ نسبتاً قوی"
    if confidence >= 70:
        return "💫 متوسط رو به بالا"
    if confidence >= 65:
        return "🌤 متوسط"
    if confidence >= 60:
        return "🌥 قابل بررسی"
    return "💤 ضعیف"


def mood_emoji(plan):
    if plan.direction == "LONG":
        return "🚀" if plan.confidence >= 85 else "🔥" if plan.confidence >= 70 else "📈"
    return "🔻" if plan.confidence >= 85 else "⚠️" if plan.confidence >= 70 else "📉"


def score_direction(direction, ind):
    score = 0.0

    # Trend
    if direction == "LONG":
        if ind["price_above_trend"]:
            score += 20
        if ind["higher_tf_trend_up"] is True:
            score += 15
        elif ind["higher_tf_trend_up"] is False:
            score -= 12
    else:
        if not ind["price_above_trend"]:
            score += 20
        if ind["higher_tf_trend_up"] is False:
            score += 15
        elif ind["higher_tf_trend_up"] is True:
            score -= 12

    # MACD
    if direction == "LONG":
        score += 15 if ind["macd_hist"] > 0 else 0
    else:
        score += 15 if ind["macd_hist"] < 0 else 0

    # DI
    if direction == "LONG":
        score += 10 if ind["plus_di"] > ind["minus_di"] else 0
    else:
        score += 10 if ind["minus_di"] > ind["plus_di"] else 0

    # ADX
    if ind["adx"] >= 25:
        score += 15
    elif ind["adx"] >= ADX_TREND_THRESHOLD:
        score += 10
    else:
        score += 3

    # RSI
    rsi = ind["rsi"]
    if direction == "LONG":
        if 45 <= rsi <= 65:
            score += 10
        elif 35 <= rsi < 45 or 65 < rsi <= 72:
            score += 6
        elif 30 <= rsi < 35 or 72 < rsi <= 78:
            score += 2
    else:
        if 35 <= rsi <= 55:
            score += 10
        elif 28 <= rsi < 35 or 55 < rsi <= 65:
            score += 6
        elif 22 <= rsi < 28 or 65 < rsi <= 72:
            score += 2

    # Stoch RSI
    st = ind["stoch_k"]
    if direction == "LONG":
        if 20 <= st <= 80:
            score += 5
        elif 10 <= st < 20 or 80 < st <= 90:
            score += 2
    else:
        if 20 <= st <= 80:
            score += 5
        elif 10 <= st < 20 or 80 < st <= 90:
            score += 2

    # Volume
    vr = ind["volume_ratio"]
    if vr >= 1.3:
        score += 8
    elif vr >= 0.8:
        score += 5
    elif vr >= 0.5:
        score += 2

    # Bollinger
    bb = ind["bb_percent"]
    if 0.15 <= bb <= 0.85:
        score += 5
    elif 0.05 <= bb <= 0.95:
        score += 2

    return max(0.0, min(100.0, round(score, 1)))


def decide_direction(ind):
    long_score = score_direction("LONG", ind)
    short_score = score_direction("SHORT", ind)

    # حداقل شرایط پایه برای جلوگیری از سیگنال‌های کاملاً تصادفی.
    long_base = (
        ind["macd_hist"] > 0
        and ind["plus_di"] >= ind["minus_di"]
    )
    short_base = (
        ind["macd_hist"] < 0
        and ind["minus_di"] >= ind["plus_di"]
    )

    if long_base and long_score >= MIN_SIGNAL_CONFIDENCE:
        return "LONG", long_score

    if short_base and short_score >= MIN_SIGNAL_CONFIDENCE:
        return "SHORT", short_score

    return None, max(long_score, short_score)


def build_ladder_weighted(ind, direction):
    price = float(ind["price"])
    atr = float(ind["atr"])

    if atr <= 0:
        atr = price * 0.01

    entries = [
        price - atr * m if direction == "LONG"
        else price + atr * m
        for m in ENTRY_LADDER_ATR
    ]

    avg_entry = sum(
        e * w for e, w in zip(entries, ENTRY_WEIGHTS)
    )

    if direction == "LONG":
        stop = avg_entry - SL_ATR_MULT * atr
        tp = avg_entry + TP_ATR_MULT * atr
    else:
        stop = avg_entry + SL_ATR_MULT * atr
        tp = avg_entry - TP_ATR_MULT * atr

    return entries, [stop], [tp]


def get_funding_rate(symbol):
    try:
        if ":USDT" not in symbol:
            return 0.0

        funding = exchange.fetch_funding_rate(symbol)
        return float(funding.get("fundingRate") or 0) * 100
    except Exception as e:
        logger.debug("Funding %s: %s", symbol, e)
        return 0.0


async def generate_trade_plan(symbol):
    ind = await cache.get_indicators(symbol)
    if not ind:
        return None

    direction, confidence = decide_direction(ind)
    if not direction:
        return None

    entries, sl, tp = build_ladder_weighted(
        ind,
        direction,
    )

    funding = await asyncio.to_thread(
        get_funding_rate,
        symbol,
    )

    leverage = 1
    if confidence >= 80:
        leverage = 3
    elif confidence >= 70:
        leverage = 2

    return TradePlan(
        symbol=symbol,
        direction=direction,
        trend=ind["trend_label"],
        rsi=float(ind["rsi"]),
        current_price=float(ind["price"]),
        confidence=float(confidence),
        entries=entries,
        stop_losses=sl,
        take_profits=tp,
        funding_rate=funding,
        leverage=leverage,
    )


async def refresh_all_plans():
    if (
        not cache.last_ohlcv_update
        or time.time() - cache.last_ohlcv_update > 300
    ):
        await cache.update_ohlcv(force=True)

    sem = asyncio.Semaphore(8)

    async def one(symbol):
        async with sem:
            try:
                return await generate_trade_plan(symbol)
            except Exception as e:
                logger.exception("Signal error %s: %s", symbol, e)
                return None

    results = await asyncio.gather(
        *(one(s) for s in cache.valid_symbols)
    )

    plans = {
        p.symbol: p
        for p in results
        if p is not None
    }

    last_plans.clear()
    last_plans.update(plans)

    logger.info("📈 سیگنال‌های فعال: %s", len(plans))
    return last_plans


# =========================
# ANALYSIS TEXT
# =========================
async def generate_status_text_async(symbol, code, chat_id):
    ind = await cache.get_indicators(symbol)

    if not ind:
        return rtl_lines(
            f"{COIN_ICONS.get(code, '🔸')} *{code}*\n\n"
            "⚠️ داده‌ی کافی برای تحلیل این ارز دریافت نشد.\n"
            "اگر این پیام تازه بعد از روشن شدن ربات است، چند ثانیه بعد دوباره بزن."
        )

    direction, confidence = decide_direction(ind)

    adx = ind["adx"]
    if adx >= 25:
        adx_desc = "روند قوی 💪"
    elif adx >= ADX_TREND_THRESHOLD:
        adx_desc = "روند متوسط 🙂"
    else:
        adx_desc = "بازار رنج 😐"

    macd_desc = (
        "مثبت 📈"
        if ind["macd_hist"] > 0
        else "منفی 📉"
        if ind["macd_hist"] < 0
        else "خنثی ⚖️"
    )

    rsi = ind["rsi"]
    if rsi > 70:
        rsi_desc = "اشباع خرید ⚠️"
    elif rsi < 30:
        rsi_desc = "اشباع فروش ⚠️"
    else:
        rsi_desc = "نرمال"

    vr = ind["volume_ratio"]
    volume_desc = f"{vr:.2f}× میانگین"

    st = ind["stoch_k"]
    if st > 80:
        st_desc = "نزدیک اشباع خرید"
    elif st < 20:
        st_desc = "نزدیک اشباع فروش"
    else:
        st_desc = "نرمال"

    bb = ind["bb_percent"]
    bb_desc = (
        "نزدیک باند بالا"
        if bb >= 0.8
        else "نزدیک باند پایین"
        if bb <= 0.2
        else "داخل محدوده"
    )

    htf = ind["higher_tf_trend_up"]
    if htf is True:
        htf_desc = "صعودی 📈"
    elif htf is False:
        htf_desc = "نزولی 📉"
    else:
        htf_desc = "نامشخص"

    header = (
        f"🧭 *وضعیت لحظه‌ای* "
        f"{COIN_ICONS.get(code, '🔸')} *{sym(code)}*\n"
        f"🕒 {shamsi_now()}\n{DIVIDER}\n"
    )

    body = (
        f"💰 قیمت: {fmt_amount(ind['price'], chat_id)}\n"
        f"📊 روند EMA200: {ind['trend_label']}\n"
        f"⚡ ADX: {adx:.1f} — {adx_desc}\n"
        f"📈 MACD: {macd_desc}\n"
        f"🎯 RSI: {rsi:.1f} — {rsi_desc}\n"
        f"🌀 Stoch RSI: {st:.1f} — {st_desc}\n"
        f"📏 Bollinger: {bb:.2f} — {bb_desc}\n"
        f"🔊 حجم: {volume_desc}\n"
        f"🗺️ روند ۴ساعته: {htf_desc}\n"
        f"{DIVIDER}\n"
    )

    if direction:
        entries, sl, tp = build_ladder_weighted(
            ind,
            direction,
        )
        direction_text = (
            "🟢 لانگ (خرید)"
            if direction == "LONG"
            else "🔴 شورت (فروش)"
        )
        ladder = format_ladder_block(
            entries,
            tp,
            sl,
            chat_id,
        )
        footer = (
            f"📐 *سیگنال فعلی:* {direction_text}\n"
            f"🎯 اطمینان: *{confidence:.0f}٪* "
            f"({confidence_badge(confidence)})\n\n"
            f"{ladder}\n"
        )
    else:
        footer = (
            "💤 فعلاً سیگنال نهایی وجود ندارد.\n"
            f"امتیاز بهترین جهت: {confidence:.0f}٪\n"
            "برای جلوگیری از سیگنال ضعیف، چند شرط پایه باید هم‌جهت شوند.\n"
        )

    warn = (
        f"{DIVIDER}\n"
        "⚠️ این تحلیل تکنیکال است و تضمین سود یا توصیه مالی نیست."
    )

    return rtl_lines(
        header + body + footer + warn
    )


async def generate_weekly_summary_async(symbol, code, chat_id):
    week_df = await cache.get_weekly_data(symbol)

    if week_df is None or len(week_df) < 2:
        return rtl_lines(
            f"{COIN_ICONS.get(code, '🔸')} *{code}*\n\n"
            "⚠️ حداقل داده‌ی لازم برای تحلیل ۷ روزه دریافت نشد."
        )

    week_df = week_df.sort_values("timestamp").reset_index(drop=True)

    first_price = float(week_df["close"].iloc[0])
    current_price = float(week_df["close"].iloc[-1])

    if first_price <= 0:
        return "⚠️ قیمت تاریخی نامعتبر است."

    pct_change = (
        (current_price - first_price)
        / first_price
        * 100
    )

    highest = float(week_df["high"].max())
    lowest = float(week_df["low"].min())

    high_row = week_df.loc[week_df["high"].idxmax()]
    low_row = week_df.loc[week_df["low"].idxmin()]

    daily_pct = week_df["close"].pct_change() * 100
    volatility = float(daily_pct.dropna().std() or 0)

    if daily_pct.dropna().empty:
        best_day_pct = 0.0
        best_day_date = "-"
    else:
        idx = daily_pct.abs().idxmax()
        best_day_pct = float(daily_pct.loc[idx])
        best_day_date = shamsi_date(
            week_df.loc[idx, "timestamp"]
        )

    up_days = int((daily_pct > 0).sum())
    down_days = int((daily_pct < 0).sum())
    avg_volume = float(week_df["volume"].mean())

    # برای RSI روزانه، اگر کمتر از 15 کندل در هفته داشتیم
    # از تاریخچه کامل daily استفاده می‌کنیم.
    daily_all = cache.ohlcv_1d.get(symbol)

    rsi_value = None
    if daily_all is not None and len(daily_all) >= 15:
        try:
            rsi_value = float(
                RSIIndicator(
                    daily_all["close"],
                    window=14,
                ).rsi().iloc[-1]
            )
        except Exception:
            pass

    if pct_change > 10:
        trend_desc = "صعودی قوی 🚀"
    elif pct_change > 0:
        trend_desc = "صعودی ملایم 📈"
    elif pct_change > -10:
        trend_desc = "نزولی ملایم 📉"
    else:
        trend_desc = "نزولی قوی 🔻"

    rsi_text = (
        f"{rsi_value:.1f}"
        if rsi_value is not None
        else "-"
    )

    text = (
        f"📊 *تحلیل ۷ روز اخیر* "
        f"{COIN_ICONS.get(code, '🔸')} *{code}*\n"
        f"🕒 {shamsi_now()}\n{DIVIDER}\n"
        f"💰 قیمت ابتدای بازه: {fmt_amount(first_price, chat_id)}\n"
        f"💰 قیمت فعلی: {fmt_amount(current_price, chat_id)}\n"
        f"📈 تغییر ۷ روزه: *{pct_change:+.2f}٪* — {trend_desc}\n\n"
        f"📈 بیشترین قیمت: {fmt_amount(highest, chat_id)}\n"
        f"   📅 {shamsi_date(high_row['timestamp'])}\n"
        f"📉 کمترین قیمت: {fmt_amount(lowest, chat_id)}\n"
        f"   📅 {shamsi_date(low_row['timestamp'])}\n"
        f"{DIVIDER}\n"
        f"⚡ بیشترین نوسان روزانه: *{best_day_pct:+.2f}٪*\n"
        f"   📅 {best_day_date}\n"
        f"📐 نوسان‌پذیری: *{volatility:.2f}٪*\n"
        f"🟢 روزهای مثبت: {up_days} | "
        f"🔴 روزهای منفی: {down_days}\n"
        f"📊 میانگین حجم روزانه: `{avg_volume:,.0f}`\n"
        f"🎯 RSI روزانه فعلی: *{rsi_text}*\n"
        f"{DIVIDER}\n"
        "ℹ️ این گزارش بر اساس داده‌ی قیمتی صرافی تهیه شده و "
        "اطلاعات خبری/بنیادی را در نظر نمی‌گیرد."
    )

    return rtl_lines(text)


# =========================
# FORMATTING
# =========================
DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
BIG_DIVIDER = "═══════════════"


def format_ladder_block(entries, take_profits, stop_losses, chat_id):
    nums = ["1️⃣", "2️⃣", "3️⃣"]

    entries_txt = "\n".join(
        f"   {nums[i]} {fmt_amount(p, chat_id)}"
        for i, p in enumerate(entries)
    )

    tp_txt = "\n".join(
        f"   {nums[i]} {fmt_amount(p, chat_id)}"
        for i, p in enumerate(take_profits)
    )

    sl_txt = "\n".join(
        f"   {nums[i]} {fmt_amount(p, chat_id)}"
        for i, p in enumerate(stop_losses)
    )

    return (
        f"📥 *ورود پله‌ای*\n{entries_txt}\n\n"
        f"🎯 *حد سود*\n{tp_txt}\n\n"
        f"🛑 *حد ضرر*\n{sl_txt}"
    )


def format_plan_pretty(plan, code, chat_id):
    icon = COIN_ICONS.get(code, "🔸")
    direction = (
        "🟢 لانگ (خرید)"
        if plan.direction == "LONG"
        else "🔴 شورت (فروش)"
    )

    funding = (
        f"\n💰 فاندینگ: {plan.funding_rate:+.3f}%"
        if plan.funding_rate
        else ""
    )

    ladder = format_ladder_block(
        plan.entries,
        plan.take_profits,
        plan.stop_losses,
        chat_id,
    )

    return rtl_lines(
        f"{mood_emoji(plan)} {icon} *{sym(code)}* — {direction}\n"
        f"🕒 {shamsi_now()}\n"
        f"📊 روند: {plan.trend} | RSI: {plan.rsi:.1f}\n"
        f"🎯 اطمینان: *{plan.confidence:.0f}٪* "
        f"({confidence_badge(plan.confidence)})\n"
        f"⚡ اهرم پیشنهادی: {plan.leverage}x{funding}\n"
        f"{DIVIDER}\n"
        f"💰 قیمت: {fmt_amount(plan.current_price, chat_id)}\n\n"
        f"{ladder}\n"
        f"{DIVIDER}\n"
        "⚠️ امتیاز اطمینان تخمینی است، نه تضمین."
    )


def format_plan_compact(plan, code, chat_id):
    avg = (
        plan.entries[0] * 0.5
        + plan.entries[1] * 0.3
        + plan.entries[2] * 0.2
    )

    direction = (
        "🟢 لانگ"
        if plan.direction == "LONG"
        else "🔴 شورت"
    )

    return rtl_lines(
        f"{mood_emoji(plan)} {COIN_ICONS.get(code, '🔸')} "
        f"*{code}* — {direction} | "
        f"اطمینان: *{plan.confidence:.0f}٪*\n"
        f"   ورود میانگین: {fmt_amount(avg, chat_id)}\n"
        f"   🎯 سود: {fmt_amount(plan.take_profits[0], chat_id)}\n"
        f"   🛑 ضرر: {fmt_amount(plan.stop_losses[0], chat_id)}"
    )


def format_prices_pretty(prices, chat_id):
    if not prices:
        return "⚠️ قیمت لحظه‌ای دریافت نشد."

    lines = [
        "💰 *قیمت لحظه‌ای ارزها*",
        f"🕒 {shamsi_now()}",
        DIVIDER,
    ]

    for symbol, price in prices.items():
        code = cache.code_for_symbol(symbol)
        lines.append(
            f"{COIN_ICONS.get(code, '🔸')} *{code}* "
            f"{fmt_amount(price, chat_id)}"
        )

    return rtl_lines("\n".join(lines))


def split_long_message(text, limit=TELEGRAM_MSG_LIMIT):
    if len(text) <= limit:
        return [text]

    parts = []
    current = ""

    for block in text.split("\n\n"):
        if len(current) + len(block) + 2 > limit:
            if current:
                parts.append(current.strip())
            current = block
        else:
            current += (
                "\n\n" if current else ""
            ) + block

    if current:
        parts.append(current.strip())

    return parts


# =========================
# MESSAGE MANAGEMENT
# =========================
async def clear_interactive_screen(
    context,
    chat_id,
    keep_id=None,
):
    ids = interactive_screen_messages.pop(chat_id, [])

    for mid in ids:
        if mid == keep_id:
            continue
        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=mid,
            )
        except Exception:
            pass


def set_interactive_screen(chat_id, message_ids):
    interactive_screen_messages[chat_id] = message_ids


async def clear_overlay(context, chat_id):
    ids = overlay_messages.pop(chat_id, [])

    for mid in ids:
        try:
            await context.bot.delete_message(
                chat_id=chat_id,
                message_id=mid,
            )
        except Exception:
            pass


async def track_auto_message(app, chat_id, message_id):
    history = auto_message_history.setdefault(
        chat_id,
        [],
    )
    history.append(message_id)

    while len(history) > AUTO_KEEP_LAST_N:
        old = history.pop(0)
        try:
            await app.bot.delete_message(
                chat_id=chat_id,
                message_id=old,
            )
        except Exception:
            pass


# =========================
# KEYBOARDS
# =========================
def build_grid_keyboard(buttons, columns):
    rows = [
        buttons[i:i + columns]
        for i in range(0, len(buttons), columns)
    ]

    if rows and len(rows[-1]) < columns:
        missing = columns - len(rows[-1])
        rows[-1].extend(
            InlineKeyboardButton(
                "\u2063",
                callback_data="noop",
            )
            for _ in range(missing)
        )

    return rows


def kb_currency():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "💵 دلار (USDT)",
            callback_data="cur_USDT",
        )],
        [InlineKeyboardButton(
            "💴 تومان (IRT)",
            callback_data="cur_IRT",
        )],
        [InlineKeyboardButton(
            "💱 هر دو",
            callback_data="cur_BOTH",
        )],
    ])


def kb_main(user_id):
    rows = [
        [
            InlineKeyboardButton(
                "💰 قیمت لحظه‌ای",
                callback_data="menu_prices",
            ),
            InlineKeyboardButton(
                "🪙 انتخاب ارز",
                callback_data="menu_coins",
            ),
        ],
        [
            InlineKeyboardButton(
                "📊 همه پیشنهادات",
                callback_data="menu_all",
            ),
            InlineKeyboardButton(
                "🔄 شروع مجدد",
                callback_data="restart_currency",
            ),
        ],
    ]

    if is_admin(user_id):
        rows.append([
            InlineKeyboardButton(
                "⚙️ پنل مدیریت",
                callback_data="admin_panel",
            ),
            InlineKeyboardButton(
                "\u2063",
                callback_data="noop",
            ),
        ])

    return InlineKeyboardMarkup(rows)


def kb_back_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="menu_main",
        )]
    ])


def kb_coins():
    buttons = [
        InlineKeyboardButton(
            f"{COIN_ICONS[c]} {c}",
            callback_data=f"coin_{c}",
        )
        for c in COIN_CODES
    ]

    rows = build_grid_keyboard(
        buttons,
        COINS_GRID_COLUMNS,
    )

    rows.append([
        InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="menu_main",
        )
    ])

    return InlineKeyboardMarkup(rows)


def kb_coin_detail(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🧭 وضعیت لحظه‌ای",
            callback_data=f"suggest_{code}",
        )],
        [InlineKeyboardButton(
            "📆 تحلیل ۷ روز اخیر",
            callback_data=f"weekly_{code}",
        )],
        [InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="menu_coins",
        )],
    ])


def kb_suggestion(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔄 بروزرسانی",
            callback_data=f"suggest_{code}",
        )],
        [InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data=f"coin_{code}",
        )],
        [InlineKeyboardButton(
            "📋 لیست ارزها",
            callback_data="menu_coins",
        )],
        [InlineKeyboardButton(
            "🏠 منوی اصلی",
            callback_data="menu_main",
        )],
    ])


def kb_suggestion_from_auto(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔄 بروزرسانی",
            callback_data=f"suggest_{code}_auto",
        )],
        [InlineKeyboardButton(
            "✖️ بستن",
            callback_data="close_temp",
        )],
        [InlineKeyboardButton(
            "🏠 منوی اصلی",
            callback_data="menu_main",
        )],
    ])


def kb_weekly(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data=f"coin_{code}",
        )],
        [InlineKeyboardButton(
            "🏠 منوی اصلی",
            callback_data="menu_main",
        )],
    ])


def kb_admin_panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔄 بروزرسانی کامل",
            callback_data="menu_all",
        )],
        [InlineKeyboardButton(
            "🔙 بازگشت",
            callback_data="menu_main",
        )],
    ])


def kb_auto_report(top_plans):
    buttons = []

    for p in top_plans:
        code = cache.code_for_symbol(p.symbol)
        buttons.append(
            InlineKeyboardButton(
                f"{COIN_ICONS.get(code, '🔸')} {code}",
                callback_data=f"suggest_{code}_auto",
            )
        )

    rows = build_grid_keyboard(buttons, 3)
    rows.append([
        InlineKeyboardButton(
            "🏠 منوی اصلی",
            callback_data="menu_main",
        )
    ])

    return InlineKeyboardMarkup(rows)


# =========================
# TEXT
# =========================
def welcome_text():
    return rtl_lines(
        "🌟 *به سیگنالستان خوش اومدی!* 🌟\n"
        f"{DIVIDER}\n"
        f"🛰️ در حال رصد {len(COIN_CODES)} ارز هستم\n"
        "⏱️ هر ۱۵ دقیقه بهترین سیگنال‌ها بررسی می‌شوند\n"
        "👇 برای بررسی دستی از منوی زیر استفاده کن\n\n"
        "برای توقف اشتراک: /stop\n\n"
        "⚠️ تحلیل تکنیکال است، نه توصیه مالی."
    )


MENU_PROMPT = "👇 یکی از گزینه‌ها رو انتخاب کن:"
MAIN_MENU_HEADER = (
    "✨ *پنل سیگنال‌یار* ✨\n"
    + DIVIDER
    + "\n"
    + MENU_PROMPT
)


# =========================
# START / COMMANDS
# =========================
async def finish_start(context, chat_id, user_id):
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

    await clear_interactive_screen(
        context,
        chat_id,
    )

    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=welcome_text(),
        reply_markup=kb_main(user_id),
        parse_mode="Markdown",
    )

    set_interactive_screen(
        chat_id,
        [msg.message_id],
    )


# =========================
# CALLBACK HANDLER
# =========================
async def button_handler(update, context):
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

        await finish_start(
            context,
            chat_id,
            user_id,
        )
        return

    if data == "restart_currency":
        await clear_interactive_screen(
            context,
            chat_id,
            keep_id=query.message.message_id,
        )

        await query.edit_message_text(
            "👋 واحد پولی را انتخاب کن:",
            reply_markup=kb_currency(),
        )

        set_interactive_screen(
            chat_id,
            [query.message.message_id],
        )
        return

    if data == "close_temp":
        await clear_overlay(context, chat_id)
        return

    if data == "menu_main":
        await clear_interactive_screen(
            context,
            chat_id,
            keep_id=query.message.message_id,
        )

        try:
            await query.edit_message_text(
                MAIN_MENU_HEADER,
                reply_markup=kb_main(user_id),
                parse_mode="Markdown",
            )
        except Exception:
            pass

        set_interactive_screen(
            chat_id,
            [query.message.message_id],
        )
        return

    if data == "menu_prices":
        await clear_interactive_screen(
            context,
            chat_id,
            keep_id=query.message.message_id,
        )

        await query.edit_message_text(
            "⏳ در حال دریافت قیمت‌ها..."
        )

        if (
            not cache.last_price_update
            or time.time() - cache.last_price_update > 120
        ):
            await asyncio.wait_for(
                cache.update_prices(),
                timeout=45,
            )

        text = format_prices_pretty(
            cache.prices,
            chat_id,
        )

        await query.edit_message_text(
            text,
            reply_markup=kb_back_main(),
            parse_mode="Markdown",
        )

        set_interactive_screen(
            chat_id,
            [query.message.message_id],
        )
        return

    if data == "menu_coins":
        await clear_interactive_screen(
            context,
            chat_id,
            keep_id=query.message.message_id,
        )

        await query.edit_message_text(
            rtl_lines(
                f"🪙 *انتخاب ارز مورد نظر*\n"
                f"{DIVIDER}\n"
                f"{MENU_PROMPT}"
            ),
            reply_markup=kb_coins(),
            parse_mode="Markdown",
        )

        set_interactive_screen(
            chat_id,
            [query.message.message_id],
        )
        return

    if data.startswith("coin_"):
        code = data.split("_", 1)[1]

        await clear_interactive_screen(
            context,
            chat_id,
            keep_id=query.message.message_id,
        )

        await query.edit_message_text(
            rtl_lines(
                f"{COIN_ICONS.get(code, '🔸')} *{sym(code)}*\n"
                f"{DIVIDER}\n"
                f"{MENU_PROMPT}"
            ),
            reply_markup=kb_coin_detail(code),
            parse_mode="Markdown",
        )

        set_interactive_screen(
            chat_id,
            [query.message.message_id],
        )
        return

    if data.startswith("suggest_"):
        auto = data.endswith("_auto")
        code = (
            data[len("suggest_"):-len("_auto")]
            if auto
            else data[len("suggest_"):]
        )

        symbol = cache.symbol_for_code(code)

        if not symbol:
            await query.edit_message_text(
                f"⚠️ بازار {code} در MEXC پیدا نشد.",
                reply_markup=kb_back_main(),
            )
            return

        if auto:
            await clear_overlay(context, chat_id)

        await query.edit_message_text(
            "⏳ در حال دریافت و تحلیل داده‌های بازار..."
        )

        try:
            await asyncio.wait_for(
                cache.ensure_symbol_data(symbol),
                timeout=60,
            )

            text = await asyncio.wait_for(
                generate_status_text_async(
                    symbol,
                    code,
                    chat_id,
                ),
                timeout=20,
            )

            markup = (
                kb_suggestion_from_auto(code)
                if auto
                else kb_suggestion(code)
            )

            if auto:
                msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=markup,
                    parse_mode="Markdown",
                )
                overlay_messages[chat_id] = [
                    msg.message_id
                ]
            else:
                await query.edit_message_text(
                    split_long_message(text)[0],
                    reply_markup=markup,
                    parse_mode="Markdown",
                )

                set_interactive_screen(
                    chat_id,
                    [query.message.message_id],
                )

        except asyncio.TimeoutError:
            await query.edit_message_text(
                "⏰ دریافت اطلاعات بیش از حد طول کشید. "
                "لاگ سرور را بررسی کن.",
                reply_markup=kb_back_main(),
            )
        except Exception as e:
            logger.exception(
                "❌ وضعیت %s: %s",
                code,
                e,
            )
            await query.edit_message_text(
                f"❌ خطا در دریافت اطلاعات {code}.\n"
                f"جزئیات در لاگ سرور ثبت شد.",
                reply_markup=kb_back_main(),
            )

        return

    if data.startswith("weekly_"):
        code = data.split("_", 1)[1]
        symbol = cache.symbol_for_code(code)

        if not symbol:
            await query.edit_message_text(
                f"⚠️ بازار {code} در MEXC پیدا نشد.",
                reply_markup=kb_back_main(),
            )
            return

        await clear_interactive_screen(
            context,
            chat_id,
            keep_id=query.message.message_id,
        )

        await query.edit_message_text(
            "⏳ در حال دریافت اطلاعات ۷ روز اخیر..."
        )

        try:
            await asyncio.wait_for(
                cache.ensure_symbol_data(symbol),
                timeout=60,
            )

            summary = await asyncio.wait_for(
                generate_weekly_summary_async(
                    symbol,
                    code,
                    chat_id,
                ),
                timeout=20,
            )

            await query.edit_message_text(
                split_long_message(summary)[0],
                reply_markup=kb_weekly(code),
                parse_mode="Markdown",
            )

            set_interactive_screen(
                chat_id,
                [query.message.message_id],
            )

        except asyncio.TimeoutError:
            await query.edit_message_text(
                "⏰ دریافت داده‌های هفتگی طول کشید. "
                "دوباره تلاش کن.",
                reply_markup=kb_back_main(),
            )
        except Exception as e:
            logger.exception(
                "❌ Weekly %s: %s",
                code,
                e,
            )
            await query.edit_message_text(
                f"❌ خطا در تحلیل هفتگی {code}.",
                reply_markup=kb_back_main(),
            )

        return

    if data == "menu_all":
        await clear_interactive_screen(
            context,
            chat_id,
            keep_id=query.message.message_id,
        )

        await query.edit_message_text(
            "⏳ در حال تحلیل همه ارزها..."
        )

        try:
            plans = await asyncio.wait_for(
                refresh_all_plans(),
                timeout=90,
            )
        except asyncio.TimeoutError:
            await query.edit_message_text(
                "⏰ تحلیل همه ارزها طول کشید. دوباره تلاش کن.",
                reply_markup=kb_back_main(),
            )
            return

        if not plans:
            text = (
                f"📋 *نمایش همه پیشنهادات*\n"
                f"🕒 {shamsi_now()}\n\n"
                "😴 فعلاً سیگنال نهایی نداریم.\n"
                "🔍 داده‌ها دریافت شده‌اند، اما شرایط "
                "اندیکاتورها برای حداقل امتیاز سیگنال کافی نیست."
            )

            await query.edit_message_text(
                rtl_lines(text),
                reply_markup=kb_back_main(),
                parse_mode="Markdown",
            )

            set_interactive_screen(
                chat_id,
                [query.message.message_id],
            )
            return

        sorted_plans = sorted(
            plans.values(),
            key=lambda p: p.confidence,
            reverse=True,
        )

        full_text = (
            f"📋 *نمایش پیشنهادات*\n"
            f"🕒 {shamsi_now()}\n\n"
            + f"\n\n{BIG_DIVIDER}\n\n".join(
                format_plan_pretty(
                    p,
                    cache.code_for_symbol(p.symbol),
                    chat_id,
                )
                for p in sorted_plans
            )
        )

        chunks = split_long_message(full_text)
        new_ids = []

        await query.edit_message_text(
            chunks[0],
            parse_mode="Markdown",
        )
        new_ids.append(query.message.message_id)

        for chunk in chunks[1:-1]:
            m = await context.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode="Markdown",
            )
            new_ids.append(m.message_id)

        last = await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "👆 نتیجه بالا\n"
                "برای مشاهده جزئیات روی ارز موردنظر بزن."
            ),
            reply_markup=kb_auto_report(sorted_plans),
        )
        new_ids.append(last.message_id)

        set_interactive_screen(
            chat_id,
            new_ids,
        )
        return

    if data == "admin_panel":
        if not is_admin(user_id):
            await query.answer(
                "⛔️ فقط ادمین.",
                show_alert=True,
            )
            return

        await query.edit_message_text(
            rtl_lines(
                "🛠️ *پنل مدیریت*\n"
                f"{DIVIDER}\n"
                f"🕒 {shamsi_now()}\n"
                f"👥 اعضای فعال: {len(subscribed_chat_ids)}\n"
                f"⚡ سیگنال‌های فعال: {len(last_plans)}\n"
                f"🪙 ارزهای رصدشده: {len(COIN_CODES)}\n"
                f"📊 داده 1h: {len(cache.ohlcv_1h)}\n"
                f"📊 داده 4h: {len(cache.ohlcv_4h)}\n"
                f"📊 داده 1d: {len(cache.ohlcv_1d)}"
            ),
            reply_markup=kb_admin_panel(),
            parse_mode="Markdown",
        )
        return


# =========================
# AUTO REPORT
# =========================
async def send_report_to_user(
    app,
    chat_id,
    top_plans,
):
    header = (
        f"📢✨ *پیشنهادات لحظه‌ای* ✨📢\n"
        f"🕒 {shamsi_now()}\n"
        f"{BIG_DIVIDER}\n\n"
    )

    if top_plans:
        body = f"\n\n{DIVIDER}\n\n".join(
            format_plan_compact(
                p,
                cache.code_for_symbol(p.symbol),
                chat_id,
            )
            for p in top_plans
        )

        footer = (
            "\n\n⚠️ امتیاز اطمینان تخمینی است، نه تضمین."
        )

        keyboard = kb_auto_report(top_plans)
    else:
        body = (
            "😴 فعلاً سیگنال واضحی پیدا نشد."
        )
        footer = (
            "\n🔍 بازار ممکن است در حالت رنج باشد."
        )
        keyboard = kb_back_main()

    text = rtl_lines(
        header + body + footer
    )

    try:
        chunks = split_long_message(text)

        for chunk in chunks[:-1]:
            msg = await app.bot.send_message(
                chat_id=chat_id,
                text=chunk,
                parse_mode="Markdown",
            )
            await track_auto_message(
                app,
                chat_id,
                msg.message_id,
            )

        msg = await app.bot.send_message(
            chat_id=chat_id,
            text=chunks[-1],
            reply_markup=keyboard,
            parse_mode="Markdown",
        )

        await track_auto_message(
            app,
            chat_id,
            msg.message_id,
        )

    except Exception as e:
        logger.exception(
            "❌ ارسال خودکار به %s: %s",
            chat_id,
            e,
        )


async def auto_report_loop(app):
    # اولین اجرا کمی بعد از بالا آمدن ربات
    await asyncio.sleep(10)

    while True:
        try:
            if subscribed_chat_ids:
                await cache.update_prices()
                await cache.update_ohlcv(force=True)

                plans = await refresh_all_plans()

                top = sorted(
                    plans.values(),
                    key=lambda p: p.confidence,
                    reverse=True,
                )[:TOP_SIGNALS_COUNT]

                await asyncio.gather(
                    *(
                        send_report_to_user(
                            app,
                            chat_id,
                            top,
                        )
                        for chat_id in list(subscribed_chat_ids)
                    ),
                    return_exceptions=True,
                )

        except asyncio.CancelledError:
            raise

        except Exception as e:
            logger.exception(
                "❌ خطا در حلقه خودکار: %s",
                e,
            )

        await asyncio.sleep(
            CHECK_INTERVAL_SECONDS
        )


# =========================
# COMMANDS
# =========================
async def start(update, context):
    if not await guard(update):
        return

    chat_id = update.effective_chat.id

    await clear_interactive_screen(
        context,
        chat_id,
    )

    msg = await update.message.reply_text(
        "👋 واحد پولی نمایش قیمت‌ها را انتخاب کن:",
        reply_markup=kb_currency(),
    )

    set_interactive_screen(
        chat_id,
        [msg.message_id],
    )


async def stop(update, context):
    if not await guard(update):
        return

    subscribed_chat_ids.discard(
        update.effective_chat.id
    )
    save_state()

    await update.message.reply_text(
        "❌ اشتراک قطع شد.\n"
        "برای فعال‌سازی دوباره /start را بزن."
    )


async def menu_command(update, context):
    if not await guard(update):
        return

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    subscribed_chat_ids.add(chat_id)
    save_state()

    await clear_interactive_screen(
        context,
        chat_id,
    )

    msg = await update.message.reply_text(
        MAIN_MENU_HEADER,
        reply_markup=kb_main(user_id),
        parse_mode="Markdown",
    )

    set_interactive_screen(
        chat_id,
        [msg.message_id],
    )


async def status(update, context):
    if not await guard(update):
        return

    await update.message.reply_text(
        f"🕒 {shamsi_now()}\n"
        f"🪙 ارزها: {len(COIN_CODES)}\n"
        f"📊 داده 1h: {len(cache.ohlcv_1h)}\n"
        f"📊 داده 4h: {len(cache.ohlcv_4h)}\n"
        f"📊 داده 1d: {len(cache.ohlcv_1d)}\n"
        f"⚡ سیگنال‌ها: {len(last_plans)}\n"
        f"👥 اعضا: {len(subscribed_chat_ids)}\n"
        f"💱 نرخ تومان: "
        f"{_irt_rate_cache.get('source') or 'نامشخص'}"
    )


# =========================
# STATE
# =========================
def save_state():
    try:
        os.makedirs(
            DATA_DIR,
            exist_ok=True,
        )

        tmp = STATE_FILE + ".tmp"

        with open(
            tmp,
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                {
                    "subscribed_chat_ids": list(
                        subscribed_chat_ids
                    ),
                    "user_currency": user_currency,
                },
                f,
                ensure_ascii=False,
            )

        os.replace(tmp, STATE_FILE)

    except Exception as e:
        logger.warning(
            "⚠️ ذخیره state: %s",
            e,
        )


def load_state():
    global subscribed_chat_ids, user_currency

    try:
        with open(
            STATE_FILE,
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        subscribed_chat_ids = set(
            int(x)
            for x in data.get(
                "subscribed_chat_ids",
                [],
            )
        )

        user_currency = {
            int(k): v
            for k, v in data.get(
                "user_currency",
                {},
            ).items()
        }

        logger.info(
            "✅ state بازیابی شد: %s کاربر",
            len(subscribed_chat_ids),
        )

    except FileNotFoundError:
        logger.info(
            "ℹ️ state وجود ندارد؛ از صفر شروع می‌شود."
        )

    except Exception as e:
        logger.warning(
            "⚠️ خواندن state: %s",
            e,
        )


# =========================
# STARTUP
# =========================
async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start", "شروع ربات"),
        BotCommand("menu", "منوی اصلی"),
    ])

    app.create_task(
        auto_report_loop(app)
    )

    logger.info(
        "🚀 Signal Bot V6 started"
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError(
            "❌ BOT_TOKEN در .env تنظیم نشده است."
        )

    if not ALLOWED_USER_IDS:
        logger.warning(
            "⚠️ ALLOWED_USER_IDS تنظیم نشده؛ "
            "ربات برای همه باز است."
        )

    load_state()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(
        CommandHandler("start", start)
    )
    app.add_handler(
        CommandHandler("stop", stop)
    )
    app.add_handler(
        CommandHandler("menu", menu_command)
    )
    app.add_handler(
        CommandHandler("status", status)
    )
    app.add_handler(
        CallbackQueryHandler(button_handler)
    )

    logger.info(
        "✅ ربات در حال اجراست..."
    )

    app.run_polling()


if __name__ == "__main__":
    main()
