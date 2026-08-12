"""
Telegram Signal Bot V7
اصلاحات:
- فقط MEXC USDT linear perpetual swap انتخاب می‌شود.
- symbol داخلی ربات code است؛ symbol واقعی MEXC از market['symbol'] گرفته می‌شود.
- هیچ Spot fallback وجود ندارد.
- OHLCV برای هر symbol/timeframe به‌صورت مستقل cache/fetch می‌شود.
- کندل در حال تشکیل از محاسبات اندیکاتورها و تحلیل ۷ روزه حذف می‌شود.
- refresh سنگین با lock و TTL از دوباره‌کاری جلوگیری می‌کند.
- خطاهای API با type و unified symbol واقعی در لاگ ثبت می‌شوند.
- Funding با cache کوتاه‌مدت دریافت می‌شود.
- /status دیگر نرخ تومان را نمایش نمی‌دهد.
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

import ccxt
import jdatetime
import pandas as pd
import requests
from dotenv import load_dotenv
from ta.momentum import RSIIndicator, StochRSIIndicator
from ta.trend import EMAIndicator, MACD, ADXIndicator
from ta.volatility import AverageTrueRange, BollingerBands
from telegram import BotCommand, BotCommandScopeChat, InlineKeyboardButton, InlineKeyboardMarkup
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

BOT_TOKEN = os.getenv("BOT_TOKEN")
ALLOWED_USER_IDS = {
    int(x) for x in os.getenv("ALLOWED_USER_IDS", "").split(",") if x.strip().isdigit()
}
ADMIN_USER_IDS = {
    int(x) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip().isdigit()
}
ALWAYS_ALLOWED_USER_IDS = {
    int(x) for x in os.getenv("ALWAYS_ALLOWED_USER_IDS", "").split(",") if x.strip().isdigit()
}

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

TIMEFRAME = "1h"
TIMEFRAMES = ("1h", "4h", "1d")
CHECK_INTERVAL_SECONDS = 15 * 60
TOP_SIGNALS_COUNT = 5
ADX_TREND_THRESHOLD = 16
MIN_SIGNAL_CONFIDENCE = 60
MIN_DIRECTION_GAP = 5
ENTRY_LADDER_ATR = [0.0, 0.6, 1.2]
ENTRY_WEIGHTS = [0.5, 0.3, 0.2]
SL_ATR_MULT = 2.0
TP_ATR_MULT = 4.0
TELEGRAM_MSG_LIMIT = 3500
IRT_RATE_TTL_SECONDS = 300
COINS_GRID_COLUMNS = 4
AUTO_KEEP_LAST_N = 3

# Market/OHLCV caching.
OHLCV_TTL_SECONDS = 90
FULL_REFRESH_TTL_SECONDS = 240
FUNDING_TTL_SECONDS = 120
MAX_OHLCV_CONCURRENCY = 5
MAX_SIGNAL_CONCURRENCY = 8
RLM = "\u200f"

DATA_DIR = os.getenv("DATA_DIR", "/data")
STATE_FILE = os.path.join(DATA_DIR, "state.json")

DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
BIG_DIVIDER = "═══════════════"

exchange = ccxt.mexc({
    "enableRateLimit": True,
    "options": {
        "defaultType": "swap",
        "adjustForTimeDifference": True,
    },
})

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

        self.prices = {}                 # code -> live ticker price
        self.ohlcv = {tf: {} for tf in TIMEFRAMES}  # tf -> code -> DataFrame
        self.ohlcv_updated_at = {tf: {} for tf in TIMEFRAMES}
        self.valid_codes = []
        self.exchange_symbols = {}       # code -> real CCXT unified contract symbol
        self.market_meta = {}            # code -> market dict

        self.last_price_update = 0.0
        self.last_full_ohlcv_update = 0.0
        self.last_full_refresh_started = 0.0

        self._sem = asyncio.Semaphore(MAX_OHLCV_CONCURRENCY)
        self._price_sem = asyncio.Semaphore(8)
        self._update_lock = asyncio.Lock()
        self._symbol_locks = {}
        self._funding_cache = {}
        self._funding_lock = asyncio.Lock()

        self._load_markets()

    def _symbol_lock(self, code):
        if code not in self._symbol_locks:
            self._symbol_locks[code] = asyncio.Lock()
        return self._symbol_locks[code]

    def _load_markets(self):
        try:
            markets = exchange.load_markets(reload=True)
            selected = {}

            for code in COIN_CODES:
                candidates = []
                for symbol, market in markets.items():
                    if market.get("base") != code:
                        continue
                    if market.get("quote") != "USDT":
                        continue
                    if market.get("type") != "swap":
                        continue
                    if not market.get("swap", False):
                        continue
                    if market.get("settle") != "USDT":
                        continue
                    if not market.get("linear", False):
                        continue
                    if market.get("active") is False:
                        continue
                    candidates.append((symbol, market))

                if not candidates:
                    continue

                # Prefer the canonical USDT-settled unified symbol.
                candidates.sort(
                    key=lambda item: (
                        0 if item[0] == f"{code}/USDT:USDT" else 1,
                        item[0],
                    )
                )
                symbol, market = candidates[0]
                selected[code] = symbol
                self.market_meta[code] = market

            self.exchange_symbols = selected
            self.valid_codes = list(selected.keys())

            logger.info(
                "MEXC swap markets: %s/%s selected (USDT linear perpetual only)",
                len(self.valid_codes),
                len(COIN_CODES),
            )

            for code in COIN_CODES:
                if code not in selected:
                    logger.debug("No active USDT linear swap for %s", code)

            if not self.valid_codes:
                logger.error("No MEXC USDT linear swap market was found.")

        except Exception as e:
            logger.exception(
                "load_markets failed: %s [%s]",
                e,
                type(e).__name__,
            )

    def symbol_for_code(self, code) -> Optional[str]:
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
                columns=["timestamp", "open", "high", "low", "close", "volume"],
            )

        required = ["timestamp", "open", "high", "low", "close", "volume"]
        if any(col not in df.columns for col in required):
            return None

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        if pd.api.types.is_numeric_dtype(df["timestamp"]):
            df["timestamp"] = pd.to_datetime(
                df["timestamp"], unit="ms", utc=True, errors="coerce"
            )
        else:
            df["timestamp"] = pd.to_datetime(
                df["timestamp"], utc=True, errors="coerce"
            )

        df = (
            df.dropna(subset=required)
            .drop_duplicates(subset=["timestamp"])
            .sort_values("timestamp")
            .reset_index(drop=True)
        )

        return df if not df.empty else None

    @staticmethod
    def _drop_forming_candle(df):
        """Remove the latest candle because it may still be forming."""
        if df is None or len(df) < 2:
            return df

        now = pd.Timestamp.now(tz="UTC")
        latest = df["timestamp"].iloc[-1]

        # A candle is considered potentially open if its timestamp is newer
        # than the last completed interval.
        timeframe_delta = None
        if len(df) >= 2:
            timeframe_delta = df["timestamp"].iloc[-1] - df["timestamp"].iloc[-2]

        if timeframe_delta is not None and timeframe_delta > pd.Timedelta(0):
            if latest + timeframe_delta > now:
                return df.iloc[:-1].copy().reset_index(drop=True)

        # Conservative fallback: latest daily/hourly candle can be open.
        return df.iloc[:-1].copy().reset_index(drop=True)

    async def update_prices(self, force=False):
        if not self.valid_codes:
            self._load_markets()
        if not self.valid_codes:
            return self.prices

        if (
            not force
            and self.last_price_update
            and time.time() - self.last_price_update < 60
        ):
            return self.prices

        async def fetch_one(code):
            symbol = self.symbol_for_code(code)
            async with self._price_sem:
                try:
                    ticker = await asyncio.to_thread(exchange.fetch_ticker, symbol)
                    price = (
                        ticker.get("last")
                        or ticker.get("close")
                        or ticker.get("bid")
                        or ticker.get("ask")
                    )
                    return code, float(price) if price is not None else None
                except Exception as e:
                    logger.warning(
                        "ticker failed | code=%s | type=%s | symbol=%s | error=%s",
                        code, type(e).__name__, symbol, e,
                    )
                    return code, None

        results = await asyncio.gather(
            *(fetch_one(code) for code in self.valid_codes)
        )
        self.prices = {
            code: price for code, price in results if price is not None
        }
        self.last_price_update = time.time()
        logger.info("Live prices loaded: %s symbols", len(self.prices))
        return self.prices

    async def _fetch_ohlcv_symbol(self, code, timeframe, limit=250):
        symbol = self.symbol_for_code(code)
        if not symbol:
            logger.warning(
                "OHLCV skipped | code=%s | reason=no_swap_symbol",
                code,
            )
            return None

        async with self._sem:
            try:
                raw = await asyncio.to_thread(
                    exchange.fetch_ohlcv,
                    symbol,
                    timeframe,
                    None,
                    limit,
                )
                df = self._to_dataframe(raw)
                if df is None or len(df) < 10:
                    logger.warning(
                        "OHLCV insufficient | code=%s | type=%s | symbol=%s | tf=%s | rows=%s",
                        code, self.market_meta.get(code, {}).get("type"),
                        symbol, timeframe, 0 if df is None else len(df),
                    )
                    return None

                # Never use an open candle for analysis.
                closed = self._drop_forming_candle(df)
                if closed is None or len(closed) < 5:
                    logger.warning(
                        "OHLCV closed data insufficient | code=%s | symbol=%s | tf=%s | rows=%s",
                        code, symbol, timeframe,
                        0 if closed is None else len(closed),
                    )
                    return None
                return closed

            except Exception as e:
                market = self.market_meta.get(code, {})
                logger.warning(
                    "OHLCV failed | code=%s | type=%s | symbol=%s | market_type=%s | tf=%s | error=%s",
                    code,
                    type(e).__name__,
                    symbol,
                    market.get("type"),
                    timeframe,
                    e,
                )
                return None

    async def ensure_symbol_data(self, code, timeframes=None, force=False):
        if timeframes is None:
            timeframes = TIMEFRAMES

        missing = [
            tf for tf in timeframes
            if force
            or code not in self.ohlcv[tf]
            or time.time() - self.ohlcv_updated_at[tf].get(code, 0) > OHLCV_TTL_SECONDS
        ]
        if not missing:
            return True

        async with self._symbol_lock(code):
            missing = [
                tf for tf in timeframes
                if force
                or code not in self.ohlcv[tf]
                or time.time() - self.ohlcv_updated_at[tf].get(code, 0) > OHLCV_TTL_SECONDS
            ]
            for tf in missing:
                df = await self._fetch_ohlcv_symbol(code, tf)
                if df is not None:
                    self.ohlcv[tf][code] = df
                    self.ohlcv_updated_at[tf][code] = time.time()

        return all(code in self.ohlcv[tf] for tf in timeframes)

    async def update_ohlcv(self, force=False, codes=None):
        async with self._update_lock:
            now = time.time()
            if (
                not force
                and self.last_full_ohlcv_update
                and now - self.last_full_ohlcv_update < FULL_REFRESH_TTL_SECONDS
            ):
                return

            if not self.valid_codes:
                self._load_markets()
            if not self.valid_codes:
                return

            target_codes = list(codes or self.valid_codes)
            self.last_full_refresh_started = now

            async def one(code):
                # force=False here because this function already owns the
                # heavy refresh decision and per-symbol lock.
                await self.ensure_symbol_data(
                    code,
                    TIMEFRAMES,
                    force=force,
                )

            await asyncio.gather(*(one(code) for code in target_codes))

            self.last_full_ohlcv_update = time.time()
            logger.info(
                "OHLCV refresh complete: 1h=%s 4h=%s 1d=%s",
                len(self.ohlcv["1h"]),
                len(self.ohlcv["4h"]),
                len(self.ohlcv["1d"]),
            )

    async def get_indicators(self, code):
        ok = await self.ensure_symbol_data(code, ("1h", "4h"))
        if not ok:
            return None

        df = self.ohlcv["1h"].get(code)
        df4 = self.ohlcv["4h"].get(code)

        if df is None or len(df) < 210:
            logger.warning(
                "Indicators insufficient | code=%s | rows=%s",
                code, 0 if df is None else len(df),
            )
            # One targeted retry only.
            await self.ensure_symbol_data(code, ("1h", "4h"), force=True)
            df = self.ohlcv["1h"].get(code)
            df4 = self.ohlcv["4h"].get(code)
            if df is None or len(df) < 210:
                return None

        try:
            ema200 = EMAIndicator(df["close"], window=200).ema_indicator()
            rsi = RSIIndicator(df["close"], window=14).rsi()
            atr = AverageTrueRange(
                df["high"], df["low"], df["close"], window=14
            ).average_true_range()

            macd = MACD(
                df["close"], window_slow=26, window_fast=12, window_sign=9
            )
            macd_hist = macd.macd_diff()

            adx_ind = ADXIndicator(
                df["high"], df["low"], df["close"], window=14
            )
            adx = adx_ind.adx()
            plus_di = adx_ind.adx_pos()
            minus_di = adx_ind.adx_neg()

            stoch = StochRSIIndicator(
                df["close"], window=14, smooth1=3, smooth2=3
            )
            stoch_k = stoch.stochrsi_k() * 100

            bb = BollingerBands(df["close"], window=20, window_dev=2)
            bb_percent = bb.bollinger_pband()

            volume_sma = df["volume"].rolling(20).mean()
            volume_ratio = df["volume"] / volume_sma

            values = {
                "price": float(df["close"].iloc[-1]),
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
                logger.warning("Incomplete indicators | code=%s", code)
                return None

            higher_tf_up = None
            if df4 is not None and len(df4) >= 205:
                ema4 = EMAIndicator(df4["close"], window=200).ema_indicator().iloc[-1]
                if pd.notna(ema4):
                    higher_tf_up = bool(df4["close"].iloc[-1] > ema4)

            values["price_above_trend"] = bool(values["price"] > values["ema200"])
            values["higher_tf_trend_up"] = higher_tf_up
            values["trend_label"] = (
                "صعودی 📈" if values["price_above_trend"] else "نزولی 📉"
            )
            values["is_trending"] = bool(values["adx"] >= ADX_TREND_THRESHOLD)
            return values

        except Exception as e:
            logger.exception(
                "Indicator error | code=%s | type=%s | error=%s",
                code, type(e).__name__, e,
            )
            return None

    async def get_weekly_data(self, code):
        ok = await self.ensure_symbol_data(code, ("1d",))
        if not ok:
            await self.ensure_symbol_data(code, ("1d",), force=True)

        df = self.ohlcv["1d"].get(code)
        if df is None or df.empty:
            logger.warning("Daily data unavailable | code=%s", code)
            return None

        end = df["timestamp"].iloc[-1]
        start = end - pd.Timedelta(days=7)
        week = df[df["timestamp"] >= start].copy()

        if len(week) < 2:
            week = df.tail(min(8, len(df))).copy()

        return week if len(week) >= 2 else None

    async def get_funding_rate(self, code):
        symbol = self.symbol_for_code(code)
        if not symbol:
            return 0.0

        cached = self._funding_cache.get(code)
        if cached and time.time() - cached["ts"] < FUNDING_TTL_SECONDS:
            return cached["value"]

        async with self._funding_lock:
            cached = self._funding_cache.get(code)
            if cached and time.time() - cached["ts"] < FUNDING_TTL_SECONDS:
                return cached["value"]

            try:
                funding = await asyncio.to_thread(exchange.fetch_funding_rate, symbol)
                value = float(funding.get("fundingRate") or 0) * 100
                self._funding_cache[code] = {"value": value, "ts": time.time()}
                return value
            except Exception as e:
                logger.debug(
                    "Funding failed | code=%s | type=%s | symbol=%s | error=%s",
                    code, type(e).__name__, symbol, e,
                )
                return 0.0


cache = MarketDataCache()


def is_allowed(user_id):
    if user_id in ALWAYS_ALLOWED_USER_IDS or user_id in ADMIN_USER_IDS:
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
            await update.message.reply_text("⛔️ این ربات خصوصی است و شما دسترسی ندارید.")
        elif update.callback_query:
            await update.callback_query.answer("⛔️ دسترسی ندارید.", show_alert=True)
        return False
    return True


def fetch_irt_rate_nobitex():
    last_error = None
    for _ in range(3):
        try:
            r = requests.get(
                "https://api.nobitex.ir/market/stats",
                params={"srcCurrency": "usdt", "dstCurrency": "rls"},
                timeout=8,
            )
            r.raise_for_status()
            rial = float(r.json()["stats"]["usdt-rls"]["latest"])
            return rial / 10
        except Exception as e:
            last_error = e
            time.sleep(1)
    raise last_error


def fetch_irt_rate_wallex():
    r = requests.get("https://api.wallex.ir/v1/markets", timeout=8)
    r.raise_for_status()
    data = r.json()
    return float(data["result"]["symbols"]["USDTTMN"]["stats"]["lastPrice"])


def get_irt_rate():
    now = time.time()
    if (
        _irt_rate_cache["value"] is not None
        and now - _irt_rate_cache["ts"] < IRT_RATE_TTL_SECONDS
    ):
        return _irt_rate_cache["value"]

    for name, fn in (("nobitex", fetch_irt_rate_nobitex), ("wallex", fetch_irt_rate_wallex)):
        try:
            rate = fn()
            if rate and rate > 0:
                _irt_rate_cache.update(value=rate, ts=now, source=name)
                return rate
        except Exception as e:
            logger.warning("IRT rate %s failed: %s", name, e)
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
    return jdatetime.datetime.fromgregorian(datetime=dt).strftime("%Y/%m/%d - %H:%M")


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
    return "\n".join((RLM + line) if line.strip() else line for line in text.split("\n"))


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

    if direction == "LONG":
        score += 20 if ind["price_above_trend"] else 0
        if ind["higher_tf_trend_up"] is True:
            score += 15
        elif ind["higher_tf_trend_up"] is False:
            score -= 12
    else:
        score += 20 if not ind["price_above_trend"] else 0
        if ind["higher_tf_trend_up"] is False:
            score += 15
        elif ind["higher_tf_trend_up"] is True:
            score -= 12

    score += 15 if (
        ind["macd_hist"] > 0 if direction == "LONG" else ind["macd_hist"] < 0
    ) else 0

    score += 10 if (
        ind["plus_di"] > ind["minus_di"]
        if direction == "LONG"
        else ind["minus_di"] > ind["plus_di"]
    ) else 0

    if ind["adx"] >= 25:
        score += 15
    elif ind["adx"] >= ADX_TREND_THRESHOLD:
        score += 10
    else:
        score += 3

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

    # StochRSI now has directional meaning.
    st = ind["stoch_k"]
    if direction == "LONG":
        if 20 <= st <= 70:
            score += 5
        elif st < 20:
            score += 7
        elif 70 < st <= 85:
            score += 2
    else:
        if 30 <= st <= 80:
            score += 5
        elif st > 80:
            score += 7
        elif 15 <= st < 30:
            score += 2

    vr = ind["volume_ratio"]
    if vr >= 1.3:
        score += 8
    elif vr >= 0.8:
        score += 5
    elif vr >= 0.5:
        score += 2

    bb = ind["bb_percent"]
    if direction == "LONG":
        if 0.10 <= bb <= 0.70:
            score += 5
        elif bb < 0.10:
            score += 4
        elif bb <= 0.90:
            score += 2
    else:
        if 0.30 <= bb <= 0.90:
            score += 5
        elif bb > 0.90:
            score += 4
        elif bb >= 0.10:
            score += 2

    return max(0.0, min(100.0, round(score, 1)))


def decide_direction(ind):
    long_score = score_direction("LONG", ind)
    short_score = score_direction("SHORT", ind)

    long_base = ind["macd_hist"] > 0 and ind["plus_di"] >= ind["minus_di"]
    short_base = ind["macd_hist"] < 0 and ind["minus_di"] >= ind["plus_di"]

    if (
        long_base
        and long_score >= MIN_SIGNAL_CONFIDENCE
        and long_score >= short_score + MIN_DIRECTION_GAP
    ):
        return "LONG", long_score

    if (
        short_base
        and short_score >= MIN_SIGNAL_CONFIDENCE
        and short_score >= long_score + MIN_DIRECTION_GAP
    ):
        return "SHORT", short_score

    return None, max(long_score, short_score)


def build_ladder_weighted(ind, direction):
    price = float(ind["price"])
    atr = float(ind["atr"])
    if atr <= 0:
        atr = price * 0.01

    entries = [
        price - atr * m if direction == "LONG" else price + atr * m
        for m in ENTRY_LADDER_ATR
    ]
    avg_entry = sum(e * w for e, w in zip(entries, ENTRY_WEIGHTS))

    if direction == "LONG":
        stop = avg_entry - SL_ATR_MULT * atr
        tp = avg_entry + TP_ATR_MULT * atr
    else:
        stop = avg_entry + SL_ATR_MULT * atr
        tp = avg_entry - TP_ATR_MULT * atr

    return entries, [stop], [tp]


async def generate_trade_plan(code):
    ind = await cache.get_indicators(code)
    if not ind:
        return None

    direction, confidence = decide_direction(ind)
    if not direction:
        return None

    entries, sl, tp = build_ladder_weighted(ind, direction)
    funding = await cache.get_funding_rate(code)

    leverage = 1
    if confidence >= 80:
        leverage = 3
    elif confidence >= 70:
        leverage = 2

    return TradePlan(
        symbol=code,
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


async def refresh_all_plans(force_data=False):
    if (
        force_data
        or not cache.last_full_ohlcv_update
        or time.time() - cache.last_full_ohlcv_update > FULL_REFRESH_TTL_SECONDS
    ):
        await cache.update_ohlcv(force=force_data)

    sem = asyncio.Semaphore(MAX_SIGNAL_CONCURRENCY)

    async def one(code):
        async with sem:
            try:
                return await generate_trade_plan(code)
            except Exception as e:
                logger.exception(
                    "Signal error | code=%s | type=%s | error=%s",
                    code, type(e).__name__, e,
                )
                return None

    results = await asyncio.gather(*(one(c) for c in cache.valid_codes))
    plans = {p.symbol: p for p in results if p is not None}
    last_plans.clear()
    last_plans.update(plans)
    logger.info("Active signals: %s", len(plans))
    return last_plans


async def generate_status_text_async(code, chat_id):
    ind = await cache.get_indicators(code)
    if not ind:
        return rtl_lines(
            f"{COIN_ICONS.get(code, '🔸')} *{code}*\n\n"
            "⚠️ داده‌ی کافی برای تحلیل این ارز دریافت نشد."
        )

    direction, confidence = decide_direction(ind)

    adx = ind["adx"]
    adx_desc = "روند قوی 💪" if adx >= 25 else "روند متوسط 🙂" if adx >= ADX_TREND_THRESHOLD else "بازار رنج 😐"
    macd_desc = "مثبت 📈" if ind["macd_hist"] > 0 else "منفی 📉" if ind["macd_hist"] < 0 else "خنثی ⚖️"

    rsi = ind["rsi"]
    rsi_desc = "اشباع خرید ⚠️" if rsi > 70 else "اشباع فروش ⚠️" if rsi < 30 else "نرمال"
    st = ind["stoch_k"]
    st_desc = "نزدیک اشباع خرید" if st > 80 else "نزدیک اشباع فروش" if st < 20 else "نرمال"
    bb = ind["bb_percent"]
    bb_desc = "نزدیک باند بالا" if bb >= 0.8 else "نزدیک باند پایین" if bb <= 0.2 else "داخل محدوده"
    htf = ind["higher_tf_trend_up"]
    htf_desc = "صعودی 📈" if htf is True else "نزولی 📉" if htf is False else "نامشخص"

    header = (
        f"🧭 *وضعیت لحظه‌ای* {COIN_ICONS.get(code, '🔸')} *{sym(code)}*\n"
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
        f"🔊 حجم: {ind['volume_ratio']:.2f}× میانگین\n"
        f"🗺️ روند ۴ساعته: {htf_desc}\n{DIVIDER}\n"
    )

    if direction:
        entries, sl, tp = build_ladder_weighted(ind, direction)
        direction_text = "🟢 لانگ (خرید)" if direction == "LONG" else "🔴 شورت (فروش)"
        footer = (
            f"📐 *سیگنال فعلی:* {direction_text}\n"
            f"🎯 اطمینان: *{confidence:.0f}٪* ({confidence_badge(confidence)})\n\n"
            f"{format_ladder_block(entries, tp, sl, chat_id)}\n"
        )
    else:
        footer = (
            "💤 فعلاً سیگنال نهایی وجود ندارد.\n"
            f"امتیاز بهترین جهت: {confidence:.0f}٪\n"
            "برای جلوگیری از سیگنال ضعیف، جهت‌های متضاد باید اختلاف امتیاز کافی داشته باشند.\n"
        )

    return rtl_lines(
        header + body + footer + DIVIDER +
        "\n⚠️ این تحلیل تکنیکال است و تضمین سود یا توصیه مالی نیست."
    )


async def generate_weekly_summary_async(code, chat_id):
    week_df = await cache.get_weekly_data(code)
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

    pct_change = (current_price - first_price) / first_price * 100
    highest = float(week_df["high"].max())
    lowest = float(week_df["low"].min())

    high_row = week_df.loc[week_df["high"].idxmax()]
    low_row = week_df.loc[week_df["low"].idxmin()]

    daily_pct = week_df["close"].pct_change() * 100
    volatility = float(daily_pct.dropna().std() or 0)

    if daily_pct.dropna().empty:
        best_day_pct, best_day_date = 0.0, "-"
    else:
        idx = daily_pct.abs().idxmax()
        best_day_pct = float(daily_pct.loc[idx])
        best_day_date = shamsi_date(week_df.loc[idx, "timestamp"])

    up_days = int((daily_pct > 0).sum())
    down_days = int((daily_pct < 0).sum())
    avg_volume = float(week_df["volume"].mean())

    daily_all = cache.ohlcv["1d"].get(code)
    rsi_value = None
    if daily_all is not None and len(daily_all) >= 15:
        try:
            rsi_value = float(RSIIndicator(daily_all["close"], window=14).rsi().iloc[-1])
        except Exception:
            pass

    trend_desc = (
        "صعودی قوی 🚀" if pct_change > 10
        else "صعودی ملایم 📈" if pct_change > 0
        else "نزولی ملایم 📉" if pct_change > -10
        else "نزولی قوی 🔻"
    )

    text = (
        f"📊 *تحلیل ۷ روز اخیر* {COIN_ICONS.get(code, '🔸')} *{code}*\n"
        f"🕒 {shamsi_now()}\n{DIVIDER}\n"
        f"💰 قیمت ابتدای بازه: {fmt_amount(first_price, chat_id)}\n"
        f"💰 قیمت فعلی: {fmt_amount(current_price, chat_id)}\n"
        f"📈 تغییر ۷ روزه: *{pct_change:+.2f}٪* — {trend_desc}\n\n"
        f"📈 بیشترین قیمت: {fmt_amount(highest, chat_id)}\n"
        f"   📅 {shamsi_date(high_row['timestamp'])}\n"
        f"📉 کمترین قیمت: {fmt_amount(lowest, chat_id)}\n"
        f"   📅 {shamsi_date(low_row['timestamp'])}\n{DIVIDER}\n"
        f"⚡ بیشترین نوسان روزانه: *{best_day_pct:+.2f}٪*\n"
        f"   📅 {best_day_date}\n"
        f"📐 نوسان‌پذیری: *{volatility:.2f}٪*\n"
        f"🟢 روزهای مثبت: {up_days} | 🔴 روزهای منفی: {down_days}\n"
        f"📊 میانگین حجم روزانه: `{avg_volume:,.0f}`\n"
        f"🎯 RSI روزانه فعلی: *{rsi_value:.1f}*" if rsi_value is not None else
        f"📊 میانگین حجم روزانه: `{avg_volume:,.0f}`\n🎯 RSI روزانه فعلی: *-*"
    )

    # Rebuild safely because the conditional expression above would otherwise
    # omit the preceding sections.
    rsi_text = f"{rsi_value:.1f}" if rsi_value is not None else "-"
    text = (
        f"📊 *تحلیل ۷ روز اخیر* {COIN_ICONS.get(code, '🔸')} *{code}*\n"
        f"🕒 {shamsi_now()}\n{DIVIDER}\n"
        f"💰 قیمت ابتدای بازه: {fmt_amount(first_price, chat_id)}\n"
        f"💰 قیمت فعلی: {fmt_amount(current_price, chat_id)}\n"
        f"📈 تغییر ۷ روزه: *{pct_change:+.2f}٪* — {trend_desc}\n\n"
        f"📈 بیشترین قیمت: {fmt_amount(highest, chat_id)}\n"
        f"   📅 {shamsi_date(high_row['timestamp'])}\n"
        f"📉 کمترین قیمت: {fmt_amount(lowest, chat_id)}\n"
        f"   📅 {shamsi_date(low_row['timestamp'])}\n{DIVIDER}\n"
        f"⚡ بیشترین نوسان روزانه: *{best_day_pct:+.2f}٪*\n"
        f"   📅 {best_day_date}\n"
        f"📐 نوسان‌پذیری: *{volatility:.2f}٪*\n"
        f"🟢 روزهای مثبت: {up_days} | 🔴 روزهای منفی: {down_days}\n"
        f"📊 میانگین حجم روزانه: `{avg_volume:,.0f}`\n"
        f"🎯 RSI روزانه فعلی: *{rsi_text}*\n{DIVIDER}\n"
        "ℹ️ گزارش فقط بر اساس داده قیمت/حجم قراردادهای Perpetual MEXC است."
    )
    return rtl_lines(text)


def format_ladder_block(entries, take_profits, stop_losses, chat_id):
    nums = ["1️⃣", "2️⃣", "3️⃣"]
    entries_txt = "\n".join(
        f"   {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(entries)
    )
    tp_txt = "\n".join(
        f"   {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(take_profits)
    )
    sl_txt = "\n".join(
        f"   {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(stop_losses)
    )
    return (
        f"📥 *ورود پله‌ای*\n{entries_txt}\n\n"
        f"🎯 *حد سود*\n{tp_txt}\n\n"
        f"🛑 *حد ضرر*\n{sl_txt}"
    )


def format_plan_pretty(plan, code, chat_id):
    direction = "🟢 لانگ (خرید)" if plan.direction == "LONG" else "🔴 شورت (فروش)"
    funding = f"\n💰 فاندینگ: {plan.funding_rate:+.3f}%" if plan.funding_rate else ""
    return rtl_lines(
        f"{mood_emoji(plan)} {COIN_ICONS.get(code, '🔸')} *{sym(code)}* — {direction}\n"
        f"🕒 {shamsi_now()}\n"
        f"📊 روند: {plan.trend} | RSI: {plan.rsi:.1f}\n"
        f"🎯 اطمینان: *{plan.confidence:.0f}٪* ({confidence_badge(plan.confidence)})\n"
        f"⚡ اهرم پیشنهادی: {plan.leverage}x{funding}\n{DIVIDER}\n"
        f"💰 قیمت: {fmt_amount(plan.current_price, chat_id)}\n\n"
        f"{format_ladder_block(plan.entries, plan.take_profits, plan.stop_losses, chat_id)}\n"
        f"{DIVIDER}\n⚠️ امتیاز اطمینان تخمینی است، نه تضمین."
    )


def format_plan_compact(plan, code, chat_id):
    avg = sum(e * w for e, w in zip(plan.entries, ENTRY_WEIGHTS))
    direction = "🟢 لانگ" if plan.direction == "LONG" else "🔴 شورت"
    return rtl_lines(
        f"{mood_emoji(plan)} {COIN_ICONS.get(code, '🔸')} *{code}* — {direction} | "
        f"اطمینان: *{plan.confidence:.0f}٪*\n"
        f"   ورود میانگین: {fmt_amount(avg, chat_id)}\n"
        f"   🎯 سود: {fmt_amount(plan.take_profits[0], chat_id)}\n"
        f"   🛑 ضرر: {fmt_amount(plan.stop_losses[0], chat_id)}"
    )


def format_prices_pretty(prices, chat_id):
    if not prices:
        return "⚠️ قیمت لحظه‌ای دریافت نشد."
    lines = ["💰 *قیمت لحظه‌ای قراردادها*", f"🕒 {shamsi_now()}", DIVIDER]
    for code, price in prices.items():
        lines.append(
            f"{COIN_ICONS.get(code, '🔸')} *{code}* {fmt_amount(price, chat_id)}"
        )
    return rtl_lines("\n".join(lines))


def split_long_message(text, limit=TELEGRAM_MSG_LIMIT):
    if len(text) <= limit:
        return [text]

    parts, current = [], ""
    for block in text.split("\n\n"):
        if len(block) > limit:
            if current:
                parts.append(current.strip())
                current = ""
            for i in range(0, len(block), limit):
                parts.append(block[i:i + limit])
            continue

        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > limit:
            parts.append(current.strip())
            current = block
        else:
            current = candidate

    if current:
        parts.append(current.strip())
    return parts


async def clear_interactive_screen(context, chat_id, keep_id=None):
    ids = interactive_screen_messages.pop(chat_id, [])
    for mid in ids:
        if mid == keep_id:
            continue
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass


def set_interactive_screen(chat_id, message_ids):
    interactive_screen_messages[chat_id] = message_ids


async def clear_overlay(context, chat_id):
    ids = overlay_messages.pop(chat_id, [])
    for mid in ids:
        try:
            await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception:
            pass


async def track_auto_message(app, chat_id, message_id):
    history = auto_message_history.setdefault(chat_id, [])
    history.append(message_id)
    while len(history) > AUTO_KEEP_LAST_N:
        old = history.pop(0)
        try:
            await app.bot.delete_message(chat_id=chat_id, message_id=old)
        except Exception:
            pass


def build_grid_keyboard(buttons, columns):
    rows = [buttons[i:i + columns] for i in range(0, len(buttons), columns)]
    if rows and len(rows[-1]) < columns:
        rows[-1].extend(
            InlineKeyboardButton("\u2063", callback_data="noop")
            for _ in range(columns - len(rows[-1]))
        )
    return rows


def kb_currency():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 دلار (USDT)", callback_data="cur_USDT")],
        [InlineKeyboardButton("💴 تومان (IRT)", callback_data="cur_IRT")],
        [InlineKeyboardButton("💱 هر دو", callback_data="cur_BOTH")],
    ])


def kb_main(user_id):
    rows = [
        [
            InlineKeyboardButton("💰 قیمت لحظه‌ای", callback_data="menu_prices"),
            InlineKeyboardButton("🪙 انتخاب ارز", callback_data="menu_coins"),
        ],
        [
            InlineKeyboardButton("📊 همه پیشنهادات", callback_data="menu_all"),
            InlineKeyboardButton("🔄 شروع مجدد", callback_data="restart_currency"),
        ],
    ]
    if is_admin(user_id):
        rows.append([
            InlineKeyboardButton("⚙️ پنل مدیریت", callback_data="admin_panel"),
            InlineKeyboardButton("\u2063", callback_data="noop"),
        ])
    return InlineKeyboardMarkup(rows)


def kb_back_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")]
    ])


def kb_coins():
    buttons = [
        InlineKeyboardButton(f"{COIN_ICONS[c]} {c}", callback_data=f"coin_{c}")
        for c in COIN_CODES if c in cache.exchange_symbols
    ]
    rows = build_grid_keyboard(buttons, COINS_GRID_COLUMNS)
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")])
    return InlineKeyboardMarkup(rows)


def kb_coin_detail(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧭 وضعیت لحظه‌ای", callback_data=f"suggest_{code}")],
        [InlineKeyboardButton("📆 تحلیل ۷ روز اخیر", callback_data=f"weekly_{code}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_coins")],
    ])


def kb_suggestion(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"suggest_{code}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"coin_{code}")],
        [InlineKeyboardButton("📋 لیست ارزها", callback_data="menu_coins")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")],
    ])


def kb_suggestion_from_auto(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"suggest_{code}_auto")],
        [InlineKeyboardButton("✖️ بستن", callback_data="close_temp")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")],
    ])


def kb_weekly(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"coin_{code}")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")],
    ])


def kb_admin_panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی کامل", callback_data="menu_all")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")],
    ])


def kb_auto_report(top_plans):
    buttons = [
        InlineKeyboardButton(
            f"{COIN_ICONS.get(p.symbol, '🔸')} {p.symbol}",
            callback_data=f"suggest_{p.symbol}_auto",
        )
        for p in top_plans
    ]
    rows = build_grid_keyboard(buttons, 3)
    rows.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")])
    return InlineKeyboardMarkup(rows)


def welcome_text():
    return rtl_lines(
        "🌟 *به سیگنالستان خوش اومدی!* 🌟\n"
        f"{DIVIDER}\n"
        f"🛰️ در حال رصد {len(cache.valid_codes)} قرارداد Perpetual هستم\n"
        "⏱️ هر ۱۵ دقیقه بهترین سیگنال‌ها بررسی می‌شوند\n"
        "👇 برای بررسی دستی از منوی زیر استفاده کن\n\n"
        "برای توقف اشتراک: /stop\n\n"
        "⚠️ تحلیل تکنیکال است، نه توصیه مالی."
    )


MENU_PROMPT = "👇 یکی از گزینه‌ها رو انتخاب کن:"
MAIN_MENU_HEADER = "✨ *پنل سیگنال‌یار* ✨\n" + DIVIDER + "\n" + MENU_PROMPT


async def finish_start(context, chat_id, user_id):
    commands = [
        BotCommand("start", "شروع ربات"),
        BotCommand("menu", "منوی اصلی"),
        BotCommand("status", "وضعیت سیستم"),
        BotCommand("stop", "لغو اشتراک"),
    ] if is_admin(user_id) else [BotCommand("menu", "منوی اصلی")]

    await context.bot.set_my_commands(
        commands,
        scope=BotCommandScopeChat(chat_id=chat_id),
    )
    await clear_interactive_screen(context, chat_id)
    msg = await context.bot.send_message(
        chat_id=chat_id,
        text=welcome_text(),
        reply_markup=kb_main(user_id),
        parse_mode="Markdown",
    )
    set_interactive_screen(chat_id, [msg.message_id])


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
        await finish_start(context, chat_id, user_id)
        return

    if data == "restart_currency":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text("👋 واحد پولی را انتخاب کن:", reply_markup=kb_currency())
        set_interactive_screen(chat_id, [query.message.message_id])
        return

    if data == "close_temp":
        await clear_overlay(context, chat_id)
        return

    if data == "menu_main":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text(
            MAIN_MENU_HEADER,
            reply_markup=kb_main(user_id),
            parse_mode="Markdown",
        )
        set_interactive_screen(chat_id, [query.message.message_id])
        return

    if data == "menu_prices":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text("⏳ در حال دریافت قیمت‌ها...")
        try:
            await asyncio.wait_for(cache.update_prices(), timeout=45)
            await query.edit_message_text(
                format_prices_pretty(cache.prices, chat_id),
                reply_markup=kb_back_main(),
                parse_mode="Markdown",
            )
            set_interactive_screen(chat_id, [query.message.message_id])
        except Exception as e:
            logger.exception("Prices UI error: %s", e)
            await query.edit_message_text(
                f"❌ خطا در دریافت قیمت‌ها.\nنوع خطا: `{type(e).__name__}`",
                reply_markup=kb_back_main(),
                parse_mode="Markdown",
            )
        return

    if data == "menu_coins":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text(
            rtl_lines(f"🪙 *انتخاب ارز مورد نظر*\n{DIVIDER}\n{MENU_PROMPT}"),
            reply_markup=kb_coins(),
            parse_mode="Markdown",
        )
        set_interactive_screen(chat_id, [query.message.message_id])
        return

    if data.startswith("coin_"):
        code = data.split("_", 1)[1]
        if not cache.symbol_for_code(code):
            await query.edit_message_text(
                f"⚠️ قرارداد Perpetual برای {code} در MEXC پیدا نشد.",
                reply_markup=kb_back_main(),
            )
            return
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text(
            rtl_lines(f"{COIN_ICONS.get(code, '🔸')} *{sym(code)}*\n{DIVIDER}\n{MENU_PROMPT}"),
            reply_markup=kb_coin_detail(code),
            parse_mode="Markdown",
        )
        set_interactive_screen(chat_id, [query.message.message_id])
        return

    if data.startswith("suggest_"):
        auto = data.endswith("_auto")
        code = data[len("suggest_"):-len("_auto")] if auto else data[len("suggest_"):]
        if not cache.symbol_for_code(code):
            await query.edit_message_text(
                f"⚠️ قرارداد {code} در MEXC پیدا نشد.",
                reply_markup=kb_back_main(),
            )
            return

        if auto:
            await clear_overlay(context, chat_id)

        await query.edit_message_text("⏳ در حال دریافت و تحلیل داده‌های بازار...")
        try:
            await asyncio.wait_for(cache.ensure_symbol_data(code, ("1h", "4h")), timeout=60)
            text = await asyncio.wait_for(generate_status_text_async(code, chat_id), timeout=20)
            markup = kb_suggestion_from_auto(code) if auto else kb_suggestion(code)

            if auto:
                msg = await context.bot.send_message(
                    chat_id=chat_id,
                    text=text,
                    reply_markup=markup,
                    parse_mode="Markdown",
                )
                overlay_messages[chat_id] = [msg.message_id]
            else:
                await query.edit_message_text(
                    split_long_message(text)[0],
                    reply_markup=markup,
                    parse_mode="Markdown",
                )
                set_interactive_screen(chat_id, [query.message.message_id])

        except asyncio.TimeoutError:
            await query.edit_message_text(
                "⏰ دریافت اطلاعات بیش از حد طول کشید. لاگ سرور را بررسی کن.",
                reply_markup=kb_back_main(),
            )
        except Exception as e:
            logger.exception("Status UI error | code=%s: %s", code, e)
            await query.edit_message_text(
                f"❌ خطا در دریافت اطلاعات {code}.\nنوع خطا: `{type(e).__name__}`",
                reply_markup=kb_back_main(),
                parse_mode="Markdown",
            )
        return

    if data.startswith("weekly_"):
        code = data.split("_", 1)[1]
        if not cache.symbol_for_code(code):
            await query.edit_message_text(
                f"⚠️ قرارداد {code} در MEXC پیدا نشد.",
                reply_markup=kb_back_main(),
            )
            return

        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text("⏳ در حال دریافت اطلاعات ۷ روز اخیر...")
        try:
            await asyncio.wait_for(cache.ensure_symbol_data(code, ("1d",)), timeout=60)
            summary = await asyncio.wait_for(generate_weekly_summary_async(code, chat_id), timeout=20)
            await query.edit_message_text(
                split_long_message(summary)[0],
                reply_markup=kb_weekly(code),
                parse_mode="Markdown",
            )
            set_interactive_screen(chat_id, [query.message.message_id])
        except asyncio.TimeoutError:
            await query.edit_message_text(
                "⏰ دریافت داده‌های هفتگی طول کشید. دوباره تلاش کن.",
                reply_markup=kb_back_main(),
            )
        except Exception as e:
            logger.exception("Weekly UI error | code=%s: %s", code, e)
            await query.edit_message_text(
                f"❌ خطا در تحلیل هفتگی {code}.",
                reply_markup=kb_back_main(),
            )
        return

    if data == "menu_all":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text("⏳ در حال تحلیل همه ارزها...")
        try:
            plans = await asyncio.wait_for(refresh_all_plans(force_data=False), timeout=120)
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
                "شرایط اندیکاتورها برای حداقل امتیاز و اختلاف جهت کافی نیست."
            )
            await query.edit_message_text(
                rtl_lines(text),
                reply_markup=kb_back_main(),
                parse_mode="Markdown",
            )
            set_interactive_screen(chat_id, [query.message.message_id])
            return

        sorted_plans = sorted(plans.values(), key=lambda p: p.confidence, reverse=True)
        full_text = (
            f"📋 *نمایش پیشنهادات*\n🕒 {shamsi_now()}\n\n"
            + f"\n\n{BIG_DIVIDER}\n\n".join(
                format_plan_pretty(p, p.symbol, chat_id) for p in sorted_plans
            )
        )
        chunks = split_long_message(full_text)
        new_ids = []
        await query.edit_message_text(chunks[0], parse_mode="Markdown")
        new_ids.append(query.message.message_id)

        for chunk in chunks[1:]:
            m = await context.bot.send_message(
                chat_id=chat_id, text=chunk, parse_mode="Markdown"
            )
            new_ids.append(m.message_id)

        last = await context.bot.send_message(
            chat_id=chat_id,
            text="👆 نتیجه بالا\nبرای مشاهده جزئیات روی ارز موردنظر بزن.",
            reply_markup=kb_auto_report(sorted_plans),
        )
        new_ids.append(last.message_id)
        set_interactive_screen(chat_id, new_ids)
        return

    if data == "admin_panel":
        if not is_admin(user_id):
            await query.answer("⛔️ فقط ادمین.", show_alert=True)
            return
        await query.edit_message_text(
            rtl_lines(
                "🛠️ *پنل مدیریت*\n"
                f"{DIVIDER}\n"
                f"🕒 {shamsi_now()}\n"
                f"👥 اعضای فعال: {len(subscribed_chat_ids)}\n"
                f"⚡ سیگنال‌های فعال: {len(last_plans)}\n"
                f"🪙 قراردادهای Perpetual: {len(cache.valid_codes)}\n"
                f"📊 داده 1h: {len(cache.ohlcv['1h'])}\n"
                f"📊 داده 4h: {len(cache.ohlcv['4h'])}\n"
                f"📊 داده 1d: {len(cache.ohlcv['1d'])}"
            ),
            reply_markup=kb_admin_panel(),
            parse_mode="Markdown",
        )


async def send_report_to_user(app, chat_id, top_plans):
    header = (
        f"📢✨ *پیشنهادات لحظه‌ای* ✨📢\n"
        f"🕒 {shamsi_now()}\n{BIG_DIVIDER}\n\n"
    )
    if top_plans:
        body = f"\n\n{DIVIDER}\n\n".join(
            format_plan_compact(p, p.symbol, chat_id) for p in top_plans
        )
        footer = "\n\n⚠️ امتیاز اطمینان تخمینی است، نه تضمین."
        keyboard = kb_auto_report(top_plans)
    else:
        body = "😴 فعلاً سیگنال واضحی پیدا نشد."
        footer = "\n🔍 بازار ممکن است در حالت رنج باشد."
        keyboard = kb_back_main()

    try:
        chunks = split_long_message(rtl_lines(header + body + footer))
        for chunk in chunks[:-1]:
            msg = await app.bot.send_message(
                chat_id=chat_id, text=chunk, parse_mode="Markdown"
            )
            await track_auto_message(app, chat_id, msg.message_id)

        msg = await app.bot.send_message(
            chat_id=chat_id,
            text=chunks[-1],
            reply_markup=keyboard,
            parse_mode="Markdown",
        )
        await track_auto_message(app, chat_id, msg.message_id)
    except Exception as e:
        logger.exception(
            "Auto report failed | chat_id=%s | type=%s | error=%s",
            chat_id, type(e).__name__, e,
        )


async def auto_report_loop(app):
    await asyncio.sleep(10)
    while True:
        cycle_started = time.time()
        try:
            if subscribed_chat_ids:
                # One heavy refresh per cycle. refresh_all_plans reuses it.
                await cache.update_prices(force=True)
                await cache.update_ohlcv(force=True)
                plans = await refresh_all_plans(force_data=False)

                top = sorted(
                    plans.values(),
                    key=lambda p: p.confidence,
                    reverse=True,
                )[:TOP_SIGNALS_COUNT]

                await asyncio.gather(
                    *(send_report_to_user(app, chat_id, top)
                      for chat_id in list(subscribed_chat_ids)),
                    return_exceptions=True,
                )

        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception(
                "Auto loop failed | type=%s | error=%s",
                type(e).__name__, e,
            )

        elapsed = time.time() - cycle_started
        await asyncio.sleep(max(5, CHECK_INTERVAL_SECONDS - elapsed))


async def start(update, context):
    if not await guard(update):
        return
    chat_id = update.effective_chat.id
    await clear_interactive_screen(context, chat_id)
    msg = await update.message.reply_text(
        "👋 واحد پولی نمایش قیمت‌ها را انتخاب کن:",
        reply_markup=kb_currency(),
    )
    set_interactive_screen(chat_id, [msg.message_id])


async def stop(update, context):
    if not await guard(update):
        return
    subscribed_chat_ids.discard(update.effective_chat.id)
    save_state()
    await update.message.reply_text(
        "❌ اشتراک قطع شد.\nبرای فعال‌سازی دوباره /start را بزن."
    )


async def menu_command(update, context):
    if not await guard(update):
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    subscribed_chat_ids.add(chat_id)
    save_state()
    await clear_interactive_screen(context, chat_id)
    msg = await update.message.reply_text(
        MAIN_MENU_HEADER,
        reply_markup=kb_main(user_id),
        parse_mode="Markdown",
    )
    set_interactive_screen(chat_id, [msg.message_id])


async def status(update, context):
    if not await guard(update):
        return
    await update.message.reply_text(
        f"🕒 {shamsi_now()}\n"
        f"🪙 قراردادهای Perpetual: {len(cache.valid_codes)}\n"
        f"📊 داده 1h: {len(cache.ohlcv['1h'])}\n"
        f"📊 داده 4h: {len(cache.ohlcv['4h'])}\n"
        f"📊 داده 1d: {len(cache.ohlcv['1d'])}\n"
        f"⚡ سیگنال‌ها: {len(last_plans)}\n"
        f"👥 اعضا: {len(subscribed_chat_ids)}\n"
        f"🔄 آخرین بروزرسانی OHLCV: "
        f"{shamsi_now() if cache.last_full_ohlcv_update else 'هنوز انجام نشده'}"
    )


def save_state():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "subscribed_chat_ids": list(subscribed_chat_ids),
                    "user_currency": user_currency,
                },
                f,
                ensure_ascii=False,
            )
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        logger.warning("State save failed: %s", e)


def load_state():
    global subscribed_chat_ids, user_currency
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        subscribed_chat_ids = {int(x) for x in data.get("subscribed_chat_ids", [])}
        user_currency = {
            int(k): v for k, v in data.get("user_currency", {}).items()
        }
        logger.info("State restored: %s users", len(subscribed_chat_ids))
    except FileNotFoundError:
        logger.info("No state file; starting fresh.")
    except Exception as e:
        logger.warning("State load failed: %s", e)


async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start", "شروع ربات"),
        BotCommand("menu", "منوی اصلی"),
        BotCommand("status", "وضعیت سیستم"),
    ])
    app.create_task(auto_report_loop(app))
    logger.info("Signal Bot V7 started")


def main():
    if not BOT_TOKEN:
        raise RuntimeError("❌ BOT_TOKEN در .env تنظیم نشده است.")

    if not ALLOWED_USER_IDS:
        logger.warning(
            "⚠️ ALLOWED_USER_IDS تنظیم نشده؛ ربات برای همه باز است."
        )

    load_state()

    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()
