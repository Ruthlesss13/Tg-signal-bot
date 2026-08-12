```python
"""
Telegram Signal Bot V8
Additions:
- New indicators: EMA20, EMA50, EMA cross, ATR%, +DI/-DI, VWAP, ROC, CCI, Williams %R,
  Bollinger Width, Volume Spike, distance from EMA200/50%, 4h ADX confirmation.
- Signal reasons with checks/warnings.
- Category scores: Trend, Momentum, Volume, Volatility, HTF.
- Enhanced weekly analysis with many statistics.
- Coin grid shows all COIN_CODES with swap status (OK/NO SWAP).
- Removed double-counting by using category weights.
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
from ta.momentum import RSIIndicator, StochRSIIndicator, ROCIndicator, WilliamsRIndicator
from ta.trend import EMAIndicator, MACD, ADXIndicator, CCIIndicator
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

# Category weights for final confidence
WEIGHT_TREND = 0.30
WEIGHT_MOMENTUM = 0.25
WEIGHT_VOLUME = 0.15
WEIGHT_VOLATILITY = 0.10
WEIGHT_HTF = 0.20

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
        self.prices = {}  # code -> live ticker price
        self.ohlcv = {tf: {} for tf in TIMEFRAMES}  # tf -> code -> DataFrame
        self.ohlcv_updated_at = {tf: {} for tf in TIMEFRAMES}
        self.valid_codes = []
        self.exchange_symbols = {}  # code -> real CCXT unified contract symbol
        self.market_meta = {}  # code -> market dict
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
                len(self.valid_codes), len(COIN_CODES),
            )
            for code in COIN_CODES:
                if code not in selected:
                    logger.debug("No active USDT linear swap for %s", code)
            if not self.valid_codes:
                logger.error("No MEXC USDT linear swap market was found.")
        except Exception as e:
            logger.exception(
                "load_markets failed: %s [%s]",
                e, type(e).__name__,
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
                        ticker.get("last") or ticker.get("close")
                        or ticker.get("bid") or ticker.get("ask")
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
        self.prices = {code: price for code, price in results if price is not None}
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
                    exchange.fetch_ohlcv, symbol, timeframe, None, limit,
                )
                df = self._to_dataframe(raw)
                if df is None or len(df) < 10:
                    logger.warning(
                        "OHLCV insufficient | code=%s | type=%s | symbol=%s | tf=%s | rows=%s",
                        code,
                        self.market_meta.get(code, {}).get("type"),
                        symbol, timeframe,
                        0 if df is None else len(df),
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
                    code, type(e).__name__, symbol,
                    market.get("type"), timeframe, e,
                )
                return None

    async def ensure_symbol_data(self, code, timeframes=None, force=False):
        if timeframes is None:
            timeframes = TIMEFRAMES
        missing = [
            tf for tf in timeframes
            if force or code not in self.ohlcv[tf]
            or time.time() - self.ohlcv_updated_at[tf].get(code, 0) > OHLCV_TTL_SECONDS
        ]
        if not missing:
            return True
        async with self._symbol_lock(code):
            missing = [
                tf for tf in timeframes
                if force or code not in self.ohlcv[tf]
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
                    code, TIMEFRAMES, force=force,
                )
            await asyncio.gather(*(one(code) for code in target_codes))
            self.last_full_ohlcv_update = time.time()
            logger.info(
                "OHLCV refresh complete: 1h=%s 4h=%s 1d=%s",
                len(self.ohlcv["1h"]), len(self.ohlcv["4h"]), len(self.ohlcv["1d"]),
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
            # Basic indicators
            close = df["close"]
            ema200 = EMAIndicator(close, window=200).ema_indicator()
            ema50 = EMAIndicator(close, window=50).ema_indicator()
            ema20 = EMAIndicator(close, window=20).ema_indicator()

            rsi = RSIIndicator(close, window=14).rsi()

            atr = AverageTrueRange(
                df["high"], df["low"], close, window=14
            ).average_true_range()

            macd = MACD(close, window_slow=26, window_fast=12, window_sign=9)
            macd_hist = macd.macd_diff()

            adx_ind = ADXIndicator(df["high"], df["low"], close, window=14)
            adx = adx_ind.adx()
            plus_di = adx_ind.adx_pos()
            minus_di = adx_ind.adx_neg()

            stoch = StochRSIIndicator(close, window=14, smooth1=3, smooth2=3)
            stoch_k = stoch.stochrsi_k() * 100

            bb = BollingerBands(close, window=20, window_dev=2)
            bb_percent = bb.bollinger_pband()
            bb_width = (bb.bollinger_hband() - bb.bollinger_lband()) / bb.bollinger_mavg() * 100

            volume_sma = df["volume"].rolling(20).mean()
            volume_ratio = df["volume"] / volume_sma

            # Additional indicators
            roc = ROCIndicator(close, window=10).roc()
            cci = CCIIndicator(df["high"], df["low"], close, window=20).cci()
            williams_r = WilliamsRIndicator(df["high"], df["low"], close, lbp=14).williams_r()

            # VWAP approximation using cumulative typical price * volume
            typical = (df["high"] + df["low"] + close) / 3
            cum_typical_vol = (typical * df["volume"]).cumsum()
            cum_vol = df["volume"].cumsum()
            vwap = cum_typical_vol / cum_vol

            # 4h indicators
            htf_trend_up = None
            adx_4h = None
            if df4 is not None and len(df4) >= 205:
                close4 = df4["close"]
                ema4 = EMAIndicator(close4, window=200).ema_indicator().iloc[-1]
                if pd.notna(ema4):
                    htf_trend_up = bool(close4.iloc[-1] > ema4)
                # 4h ADX
                adx4_ind = ADXIndicator(df4["high"], df4["low"], close4, window=14)
                adx_4h = adx4_ind.adx().iloc[-1]

            # Prices
            current_price = float(close.iloc[-1])
            ema200_val = float(ema200.iloc[-1])
            ema50_val = float(ema50.iloc[-1])
            ema20_val = float(ema20.iloc[-1])

            # Distances
            dist_ema200 = (current_price - ema200_val) / ema200_val * 100
            dist_ema50 = (current_price - ema50_val) / ema50_val * 100

            # Cross
            ema20_gt_ema50 = ema20_val > ema50_val

            values = {
                "price": current_price,
                "rsi": rsi.iloc[-1],
                "atr": atr.iloc[-1],
                "atr_percent": (atr.iloc[-1] / current_price) * 100,
                "ema200": ema200_val,
                "ema50": ema50_val,
                "ema20": ema20_val,
                "ema20_gt_ema50": ema20_gt_ema50,
                "macd_hist": macd_hist.iloc[-1],
                "adx": adx.iloc[-1],
                "plus_di": plus_di.iloc[-1],
                "minus_di": minus_di.iloc[-1],
                "stoch_k": stoch_k.iloc[-1],
                "bb_percent": bb_percent.iloc[-1],
                "bb_width": bb_width.iloc[-1],
                "volume_ratio": volume_ratio.iloc[-1],
                "roc": roc.iloc[-1],
                "cci": cci.iloc[-1],
                "williams_r": williams_r.iloc[-1],
                "vwap": vwap.iloc[-1],
                "dist_ema200": dist_ema200,
                "dist_ema50": dist_ema50,
                "higher_tf_trend_up": htf_trend_up,
                "adx_4h": adx_4h,
                "price_above_trend": bool(current_price > ema200_val),
                "trend_label": "صعودی 📈" if current_price > ema200_val else "نزولی 📉",
                "is_trending": bool(adx.iloc[-1] >= ADX_TREND_THRESHOLD),
            }

            if any(pd.isna(v) for v in values.values() if not isinstance(v, bool)):
                logger.warning("Incomplete indicators | code=%s", code)
                return None
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
    usdt_txt = f"{RLM}{usdt_value:,.10f} USDT"
    pref = get_pref(chat_id)
    if pref == "USDT":
        return usdt_txt

    rate = get_irt_rate()
    if not rate:
        return usdt_txt + " _(نرخ تومان موقتاً در دسترس نیست)_"
    irt_txt = f"{RLM}`{fmt_irt(usdt_value * rate)}` تومان"
    if pref == "IRT":
        return irt_txt
    return f"{usdt_txt}\n {irt_txt}"


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


def compute_signal_scores(ind, direction):
    """
    Returns (total_score, category_scores_dict, reasons_list)
    category_scores: trend, momentum, volume, volatility, htf
    reasons: list of (emoji, text) where emoji is '✅' or '⚠️'
    """
    # Initialize scores
    trend_score = 0
    mom_score = 0
    vol_score = 0
    vola_score = 0
    htf_score = 0
    reasons = []

    # --- Trend category ---
    price_above_ema200 = ind["price_above_trend"]
    price_above_ema50 = ind["price"] > ind["ema50"]
    ema20_gt_ema50 = ind["ema20_gt_ema50"]
    adx = ind["adx"]
    plus_di = ind["plus_di"]
    minus_di = ind["minus_di"]
    di_aligned = plus_di > minus_di if direction == "LONG" else minus_di > plus_di
    dist_ema200 = ind["dist_ema200"]
    dist_ema50 = ind["dist_ema50"]

    if direction == "LONG":
        if price_above_ema200:
            trend_score += 20
            reasons.append(("✅", "قیمت بالای EMA200"))
        else:
            reasons.append(("⚠️", f"قیمت پایین‌تر از EMA200 ({dist_ema200:+.1f}%)"))

        if price_above_ema50:
            trend_score += 10
            reasons.append(("✅", "قیمت بالای EMA50"))
        else:
            reasons.append(("⚠️", f"قیمت پایین‌تر از EMA50 ({dist_ema50:+.1f}%)"))

        if ema20_gt_ema50:
            trend_score += 10
            reasons.append(("✅", "EMA20 بالای EMA50"))
        else:
            reasons.append(("⚠️", "EMA20 پایین‌تر از EMA50"))

        if adx >= 25:
            trend_score += 15
            reasons.append(("✅", f"ADX = {adx:.1f} (روند قوی)"))
        elif adx >= ADX_TREND_THRESHOLD:
            trend_score += 10
            reasons.append(("✅", f"ADX = {adx:.1f} (روند متوسط)"))
        else:
            reasons.append(("⚠️", f"ADX = {adx:.1f} (روند ضعیف)"))

        if di_aligned:
            trend_score += 10
            reasons.append(("✅", "+DI > -DI" if direction == "LONG" else "-DI > +DI"))
        else:
            reasons.append(("⚠️", "جهت DI مخالف است"))

    else:  # SHORT
        if not price_above_ema200:
            trend_score += 20
            reasons.append(("✅", "قیمت پایین‌تر از EMA200"))
        else:
            reasons.append(("⚠️", f"قیمت بالای EMA200 ({dist_ema200:+.1f}%)"))

        if not price_above_ema50:
            trend_score += 10
            reasons.append(("✅", "قیمت پایین‌تر از EMA50"))
        else:
            reasons.append(("⚠️", f"قیمت بالای EMA50 ({dist_ema50:+.1f}%)"))

        if not ema20_gt_ema50:
            trend_score += 10
            reasons.append(("✅", "EMA20 پایین‌تر از EMA50"))
        else:
            reasons.append(("⚠️", "EMA20 بالای EMA50"))

        if adx >= 25:
            trend_score += 15
            reasons.append(("✅", f"ADX = {adx:.1f} (روند قوی)"))
        elif adx >= ADX_TREND_THRESHOLD:
            trend_score += 10
            reasons.append(("✅", f"ADX = {adx:.1f} (روند متوسط)"))
        else:
            reasons.append(("⚠️", f"ADX = {adx:.1f} (روند ضعیف)"))

        if di_aligned:
            trend_score += 10
            reasons.append(("✅", "-DI > +DI" if direction == "SHORT" else "+DI > -DI"))
        else:
            reasons.append(("⚠️", "جهت DI مخالف است"))

    # Cap trend
    trend_score = min(100, trend_score)

    # --- Momentum category ---
    rsi = ind["rsi"]
    macd_hist = ind["macd_hist"]
    roc = ind["roc"]
    cci = ind["cci"]
    williams_r = ind["williams_r"]
    stoch_k = ind["stoch_k"]

    if direction == "LONG":
        # RSI: prefer 45-65
        if 45 <= rsi <= 65:
            mom_score += 15
            reasons.append(("✅", f"RSI = {rsi:.1f} (منطقه مطلوب)"))
        elif 35 <= rsi < 45 or 65 < rsi <= 72:
            mom_score += 10
            reasons.append(("⚠️", f"RSI = {rsi:.1f} (نزدیک مرز)"))
        else:
            reasons.append(("⚠️", f"RSI = {rsi:.1f} (خارج از محدوده)"))

        # MACD positive
        if macd_hist > 0:
            mom_score += 10
            reasons.append(("✅", "MACD مثبت"))
        else:
            reasons.append(("⚠️", "MACD منفی"))

        # ROC positive
        if roc > 0:
            mom_score += 5
            reasons.append(("✅", f"ROC = {roc:.1f}% (مثبت)"))
        else:
            reasons.append(("⚠️", f"ROC = {roc:.1f}% (منفی)"))

        # CCI > 0 (but not overbought)
        if cci > 0 and cci < 100:
            mom_score += 5
            reasons.append(("✅", f"CCI = {cci:.1f} (صعودی)"))
        elif cci >= 100:
            mom_score += 2
            reasons.append(("⚠️", f"CCI = {cci:.1f} (اشباع خرید)"))
        else:
            reasons.append(("⚠️", f"CCI = {cci:.1f} (نزولی)"))

        # Williams %R: > -20 overbought, < -80 oversold. Prefer -20 to -80
        if -80 <= williams_r <= -20:
            mom_score += 5
            reasons.append(("✅", f"Williams %R = {williams_r:.1f} (نرمال)"))
        elif williams_r < -80:
            mom_score += 7
            reasons.append(("✅", f"Williams %R = {williams_r:.1f} (اشباع فروش)"))
        else:
            reasons.append(("⚠️", f"Williams %R = {williams_r:.1f} (اشباع خرید)"))

        # Stoch RSI: prefer 20-70
        if 20 <= stoch_k <= 70:
            mom_score += 5
            reasons.append(("✅", f"Stoch RSI = {stoch_k:.1f} (نرمال)"))
        elif stoch_k < 20:
            mom_score += 7
            reasons.append(("✅", f"Stoch RSI = {stoch_k:.1f} (اشباع فروش)"))
        else:
            reasons.append(("⚠️", f"Stoch RSI = {stoch_k:.1f} (نزدیک اشباع خرید)"))

    else:  # SHORT
        # RSI: prefer 35-55
        if 35 <= rsi <= 55:
            mom_score += 15
            reasons.append(("✅", f"RSI = {rsi:.1f} (منطقه مطلوب)"))
        elif 28 <= rsi < 35 or 55 < rsi <= 65:
            mom_score += 10
            reasons.append(("⚠️", f"RSI = {rsi:.1f} (نزدیک مرز)"))
        else:
            reasons.append(("⚠️", f"RSI = {rsi:.1f} (خارج از محدوده)"))

        # MACD negative
        if macd_hist < 0:
            mom_score += 10
            reasons.append(("✅", "MACD منفی"))
        else:
            reasons.append(("⚠️", "MACD مثبت"))

        # ROC negative
        if roc < 0:
            mom_score += 5
            reasons.append(("✅", f"ROC = {roc:.1f}% (منفی)"))
        else:
            reasons.append(("⚠️", f"ROC = {roc:.1f}% (مثبت)"))

        # CCI < 0 (but not oversold)
        if cci < 0 and cci > -100:
            mom_score += 5
            reasons.append(("✅", f"CCI = {cci:.1f} (نزولی)"))
        elif cci <= -100:
            mom_score += 2
            reasons.append(("⚠️", f"CCI = {cci:.1f} (اشباع فروش)"))
        else:
            reasons.append(("⚠️", f"CCI = {cci:.1f} (صعودی)"))

        # Williams %R: > -20 overbought, < -80 oversold. Prefer -20 to -80
        if -80 <= williams_r <= -20:
            mom_score += 5
            reasons.append(("✅", f"Williams %R = {williams_r:.1f} (نرمال)"))
        elif williams_r > -20:
            mom_score += 7
            reasons.append(("✅", f"Williams %R = {williams_r:.1f} (اشباع خرید)"))
        else:
            reasons.append(("⚠️", f"Williams %R = {williams_r:.1f} (اشباع فروش)"))

        # Stoch RSI: prefer 30-80
        if 30 <= stoch_k <= 80:
            mom_score += 5
            reasons.append(("✅", f"Stoch RSI = {stoch_k:.1f} (نرمال)"))
        elif stoch_k > 80:
            mom_score += 7
            reasons.append(("✅", f"Stoch RSI = {stoch_k:.1f} (اشباع خرید)"))
        else:
            reasons.append(("⚠️", f"Stoch RSI = {stoch_k:.1f} (نزدیک اشباع فروش)"))

    mom_score = min(100, mom_score)

    # --- Volume category ---
    vol_ratio = ind["volume_ratio"]
    if vol_ratio >= 1.5:
        vol_score += 30
        reasons.append(("✅", f"حجم = {vol_ratio:.2f}× میانگین (اسپایک)"))
    elif vol_ratio >= 1.2:
        vol_score += 20
        reasons.append(("✅", f"حجم = {vol_ratio:.2f}× میانگین (بالا)"))
    elif vol_ratio >= 0.8:
        vol_score += 10
        reasons.append(("⚠️", f"حجم = {vol_ratio:.2f}× میانگین (متوسط)"))
    else:
        reasons.append(("⚠️", f"حجم = {vol_ratio:.2f}× میانگین (کم)"))

    # Also check if price is above VWAP (for long) or below (for short)
    vwap = ind["vwap"]
    if direction == "LONG":
        if ind["price"] > vwap:
            vol_score += 10
            reasons.append(("✅", "قیمت بالای VWAP"))
        else:
            reasons.append(("⚠️", "قیمت پایین‌تر از VWAP"))
    else:
        if ind["price"] < vwap:
            vol_score += 10
            reasons.append(("✅", "قیمت پایین‌تر از VWAP"))
        else:
            reasons.append(("⚠️", "قیمت بالای VWAP"))

    vol_score = min(100, vol_score)

    # --- Volatility category ---
    atr_pct = ind["atr_percent"]
    bb_width = ind["bb_width"]
    bb_percent = ind["bb_percent"]

    # For long: prefer low volatility (tight range) and BB not too high
    if direction == "LONG":
        if atr_pct < 2:
            vola_score += 20
            reasons.append(("✅", f"ATR% = {atr_pct:.2f}% (کم)"))
        elif atr_pct < 4:
            vola_score += 10
            reasons.append(("⚠️", f"ATR% = {atr_pct:.2f}% (متوسط)"))
        else:
            reasons.append(("⚠️", f"ATR% = {atr_pct:.2f}% (بالا)"))

        if bb_percent < 0.3:
            vola_score += 15
            reasons.append(("✅", f"Bollinger %B = {bb_percent:.2f} (نزدیک پایین)"))
        elif bb_percent < 0.6:
            vola_score += 10
            reasons.append(("✅", f"Bollinger %B = {bb_percent:.2f} (وسط)"))
        else:
            vola_score += 5
            reasons.append(("⚠️", f"Bollinger %B = {bb_percent:.2f} (نزدیک بالا)"))

        # BB width: narrow means potential breakout
        if bb_width < 10:
            vola_score += 10
            reasons.append(("✅", f"Bollinger Width = {bb_width:.2f}% (فشرده)"))
        else:
            reasons.append(("⚠️", f"Bollinger Width = {bb_width:.2f}% (گشاد)"))

    else:  # SHORT
        if atr_pct < 2:
            vola_score += 20
            reasons.append(("✅", f"ATR% = {atr_pct:.2f}% (کم)"))
        elif atr_pct < 4:
            vola_score += 10
            reasons.append(("⚠️", f"ATR% = {atr_pct:.2f}% (متوسط)"))
        else:
            reasons.append(("⚠️", f"ATR% = {atr_pct:.2f}% (بالا)"))

        if bb_percent > 0.7:
            vola_score += 15
            reasons.append(("✅", f"Bollinger %B = {bb_percent:.2f} (نزدیک بالا)"))
        elif bb_percent > 0.4:
            vola_score += 10
            reasons.append(("✅", f"Bollinger %B = {bb_percent:.2f} (وسط)"))
        else:
            vola_score += 5
            reasons.append(("⚠️", f"Bollinger %B = {bb_percent:.2f} (نزدیک پایین)"))

        if bb_width < 10:
            vola_score += 10
            reasons.append(("✅", f"Bollinger Width = {bb_width:.2f}% (فشرده)"))
        else:
            reasons.append(("⚠️", f"Bollinger Width = {bb_width:.2f}% (گشاد)"))

    vola_score = min(100, vola_score)

    # --- Higher Timeframe (HTF) category ---
    htf_trend = ind["higher_tf_trend_up"]
    adx_4h = ind.get("adx_4h")

    if htf_trend is not None:
        if direction == "LONG":
            if htf_trend:
                htf_score += 40
                reasons.append(("✅", "4H EMA200 تأیید صعودی"))
            else:
                reasons.append(("⚠️", "4H EMA200 تأیید نزولی"))
        else:
            if not htf_trend:
                htf_score += 40
                reasons.append(("✅", "4H EMA200 تأیید نزولی"))
            else:
                reasons.append(("⚠️", "4H EMA200 تأیید صعودی"))
    else:
        reasons.append(("⚠️", "4H EMA200 نامشخص"))

    if adx_4h is not None:
        if adx_4h >= 25:
            htf_score += 30
            reasons.append(("✅", f"4H ADX = {adx_4h:.1f} (روند قوی)"))
        elif adx_4h >= ADX_TREND_THRESHOLD:
            htf_score += 15
            reasons.append(("✅", f"4H ADX = {adx_4h:.1f} (روند متوسط)"))
        else:
            reasons.append(("⚠️", f"4H ADX = {adx_4h:.1f} (روند ضعیف)"))
    else:
        reasons.append(("⚠️", "4H ADX در دسترس نیست"))

    htf_score = min(100, htf_score)

    # --- Total confidence ---
    total = (
        trend_score * WEIGHT_TREND
        + mom_score * WEIGHT_MOMENTUM
        + vol_score * WEIGHT_VOLUME
        + vola_score * WEIGHT_VOLATILITY
        + htf_score * WEIGHT_HTF
    )
    total = round(total, 1)

    category_scores = {
        "trend": round(trend_score, 1),
        "momentum": round(mom_score, 1),
        "volume": round(vol_score, 1),
        "volatility": round(vola_score, 1),
        "htf": round(htf_score, 1),
    }

    return total, category_scores, reasons


def decide_direction(ind):
    long_score, long_cat, long_reasons = compute_signal_scores(ind, "LONG")
    short_score, short_cat, short_reasons = compute_signal_scores(ind, "SHORT")

    # Basic base conditions to avoid weak signals
    long_base = ind["macd_hist"] > 0 and ind["plus_di"] >= ind["minus_di"]
    short_base = ind["macd_hist"] < 0 and ind["minus_di"] >= ind["plus_di"]

    if (
        long_base
        and long_score >= MIN_SIGNAL_CONFIDENCE
        and long_score >= short_score + MIN_DIRECTION_GAP
    ):
        return "LONG", long_score, long_cat, long_reasons
    if (
        short_base
        and short_score >= MIN_SIGNAL_CONFIDENCE
        and short_score >= long_score + MIN_DIRECTION_GAP
    ):
        return "SHORT", short_score, short_cat, short_reasons
    return None, max(long_score, short_score), None, None


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

    direction, confidence, cat_scores, reasons = decide_direction(ind)
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
            f"{COIN_ICONS.get(code, '🔸')} {code}\n\n"
            "⚠️ داده‌ی کافی برای تحلیل این ارز دریافت نشد."
        )

    direction, confidence, cat_scores, reasons = decide_direction(ind)

    # Build header
    header = (
        f"🧭 *وضعیت لحظه‌ای* {COIN_ICONS.get(code, '🔸')} *{sym(code)}*\n"
        f"🕒 {shamsi_now()}\n{DIVIDER}\n"
    )

    # Build base stats (only a few)
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

    # If direction exists, build reasons and category bars
    if direction and confidence >= MIN_SIGNAL_CONFIDENCE:
        direction_text = "🟢 لانگ (خرید)" if direction == "LONG" else "🔴 شورت (فروش)"

        # Build reasons block
        reasons_block = f"*دلایل {direction_text}*\n"
        for emoji, txt in reasons:
            reasons_block += f"{emoji} {txt}\n"

        # Build category bars
        bar_length = 10
        categories = [
            ("Trend", cat_scores.get("trend", 0)),
            ("Momentum", cat_scores.get("momentum", 0)),
            ("Volume", cat_scores.get("volume", 0)),
            ("Volatility", cat_scores.get("volatility", 0)),
            ("HTF Confirm", cat_scores.get("htf", 0)),
        ]
        bars = "📊 *کیفیت سیگنال*\n"
        for name, score in categories:
            filled = int(round(score / 10))
            filled = min(bar_length, max(0, filled))
            bar = "█" * filled + "░" * (bar_length - filled)
            bars += f"{name} {bar} {score:.0f}%\n"

        # Entry ladder
        entries, sl, tp = build_ladder_weighted(ind, direction)
        ladder = format_ladder_block(entries, tp, sl, chat_id)

        # Risk/Reward
        avg_entry = sum(e * w for e, w in zip(entries, ENTRY_WEIGHTS))
        if direction == "LONG":
            risk = (avg_entry - sl[0]) / avg_entry * 100
            reward = (tp[0] - avg_entry) / avg_entry * 100
        else:
            risk = (sl[0] - avg_entry) / avg_entry * 100
            reward = (avg_entry - tp[0]) / avg_entry * 100
        rr = reward / risk if risk > 0 else 0
        risk_reward = f"📐 ریسک/بازده: 1:{rr:.2f} (ریسک {risk:.2f}%, بازده {reward:.2f}%)"

        # Entry to SL/TP distances in ATR
        atr = ind["atr"]
        sl_dist_atr = abs(avg_entry - sl[0]) / atr if atr > 0 else 0
        tp_dist_atr = abs(tp[0] - avg_entry) / atr if atr > 0 else 0
        atr_info = f"📏 فاصله تا SL: {sl_dist_atr:.1f} ATR | تا TP: {tp_dist_atr:.1f} ATR"

        footer = (
            f"📐 *سیگنال فعلی:* {direction_text}\n"
            f"🎯 اطمینان: *{confidence:.0f}٪* ({confidence_badge(confidence)})\n\n"
            f"{reasons_block}\n"
            f"{bars}\n"
            f"{ladder}\n"
            f"{risk_reward}\n"
            f"{atr_info}\n"
        )
    else:
        footer = (
            "💤 فعلاً سیگنال نهایی وجود ندارد.\n"
            f"امتیاز بهترین جهت: {confidence:.0f}٪\n"
            "برای جلوگیری از سیگنال ضعیف، جهت‌های متضاد باید اختلاف امتیاز کافی داشته باشند.\n"
        )

    return rtl_lines(header + body + footer + DIVIDER + "\n⚠️ این تحلیل تکنیکال است و تضمین سود یا توصیه مالی نیست.")


async def generate_weekly_summary_async(code, chat_id):
    week_df = await cache.get_weekly_data(code)
    if week_df is None or len(week_df) < 2:
        return rtl_lines(
            f"{COIN_ICONS.get(code, '🔸')} {code}\n\n"
            "⚠️ حداقل داده‌ی لازم برای تحلیل ۷ روزه دریافت نشد."
        )

    week_df = week_df.sort_values("timestamp").reset_index(drop=True)
    first_price = float(week_df["close"].iloc[0])
    current_price = float(week_df["close"].iloc[-1])
    if first_price <= 0:
        return "⚠️ قیمت تاریخی نامعتبر است."

    # Basic stats
    pct_change_7d = (current_price - first_price) / first_price * 100

    # 24h, 3d, 7d changes
    if len(week_df) >= 2:
        price_1d_ago = float(week_df["close"].iloc[-2]) if len(week_df) >= 2 else current_price
        pct_change_24h = (current_price - price_1d_ago) / price_1d_ago * 100
    else:
        pct_change_24h = 0.0

    if len(week_df) >= 4:
        price_3d_ago = float(week_df["close"].iloc[-4]) if len(week_df) >= 4 else first_price
        pct_change_3d = (current_price - price_3d_ago) / price_3d_ago * 100
    else:
        pct_change_3d = pct_change_7d

    # High/Low
    highest = float(week_df["high"].max())
    lowest = float(week_df["low"].min())
    high_row = week_df.loc[week_df["high"].idxmax()]
    low_row = week_df.loc[week_df["low"].idxmin()]
    range_pct = (highest - lowest) / lowest * 100

    # Daily returns
    daily_pct = week_df["close"].pct_change() * 100
    daily_returns = daily_pct.dropna()
    if not daily_returns.empty:
        volatility = float(daily_returns.std())
        best_day_pct = float(daily_returns.max())
        worst_day_pct = float(daily_returns.min())
        best_day_date = shamsi_date(week_df.loc[daily_returns.idxmax(), "timestamp"]) if not daily_returns.isnull().all() else "-"
        worst_day_date = shamsi_date(week_df.loc[daily_returns.idxmin(), "timestamp"]) if not daily_returns.isnull().all() else "-"
        up_days = int((daily_returns > 0).sum())
        down_days = int((daily_returns < 0).sum())
    else:
        volatility = 0.0
        best_day_pct = worst_day_pct = 0.0
        best_day_date = worst_day_date = "-"
        up_days = down_days = 0

    # Average volume
    avg_volume = float(week_df["volume"].mean())

    # Volume trend: compare last 2 days average vs overall average
    if len(week_df) >= 3:
        last_2_vol = week_df["volume"].tail(2).mean()
        volume_trend = "افزایشی 🔊" if last_2_vol > avg_volume * 1.1 else "کاهشی 🔇" if last_2_vol < avg_volume * 0.9 else "ثابت"
    else:
        volume_trend = "ناشناخته"

    # Daily indicators (full daily data)
    daily_all = cache.ohlcv["1d"].get(code)
    rsi_daily = None
    ema20_daily = None
    ema50_daily = None
    macd_hist_daily = None
    adx_daily = None
    bb_position = None
    bb_width_daily = None
    if daily_all is not None and len(daily_all) >= 15:
        try:
            close_d = daily_all["close"]
            rsi_daily = float(RSIIndicator(close_d, window=14).rsi().iloc[-1])
            ema20_d = EMAIndicator(close_d, window=20).ema_indicator().iloc[-1]
            ema50_d = EMAIndicator(close_d, window=50).ema_indicator().iloc[-1]
            ema20_daily = float(ema20_d)
            ema50_daily = float(ema50_d)
            macd_d = MACD(close_d, window_slow=26, window_fast=12, window_sign=9)
            macd_hist_daily = float(macd_d.macd_diff().iloc[-1])
            adx_d = ADXIndicator(daily_all["high"], daily_all["low"], close_d, window=14)
            adx_daily = float(adx_d.adx().iloc[-1])
            bb_d = BollingerBands(close_d, window=20, window_dev=2)
            bb_position = float(bb_d.bollinger_pband().iloc[-1]) * 100
            bb_width_daily = (bb_d.bollinger_hband().iloc[-1] - bb_d.bollinger_lband().iloc[-1]) / bb_d.bollinger_mavg().iloc[-1] * 100
        except Exception:
            pass

    # Max Drawdown and Max Run-up over the period
    cumulative = (week_df["close"] / first_price) * 100
    peak = cumulative.cummax()
    drawdown = (peak - cumulative) / peak * 100
    max_drawdown = float(drawdown.max()) if not drawdown.empty else 0.0

    # Max Run-up: maximum percentage increase from the start
    max_runup = float(((cumulative / 100) - 1).max() * 100)

    # Consecutive up/down days
    if not daily_returns.empty:
        # Count consecutive positive/negative at the end
        returns_sign = (daily_returns > 0).astype(int)
        # Find last run
        last_sign = returns_sign.iloc[-1] if not returns_sign.empty else 0
        consecutive = 0
        for val in reversed(returns_sign):
            if val == last_sign:
                consecutive += 1
            else:
                break
        consecutive_days = consecutive
        consecutive_type = "صعودی" if last_sign == 1 else "نزولی"
    else:
        consecutive_days = 0
        consecutive_type = "نامشخص"

    # Trend strength (weekly)
    if adx_daily is not None:
        if adx_daily >= 25:
            trend_strength = "قوی 💪"
        elif adx_daily >= ADX_TREND_THRESHOLD:
            trend_strength = "متوسط 🙂"
        else:
            trend_strength = "ضعیف 😐"
    else:
        trend_strength = "نامشخص"

    # Price vs EMAs
    if ema20_daily is not None and ema50_daily is not None:
        price_vs_ema = "EMA20 > EMA50" if ema20_daily > ema50_daily else "EMA20 < EMA50"
    else:
        price_vs_ema = "نامشخص"

    # Trend direction
    trend_desc = (
        "صعودی قوی 🚀" if pct_change_7d > 10 else
        "صعودی ملایم 📈" if pct_change_7d > 0 else
        "نزولی ملایم 📉" if pct_change_7d > -10 else
        "نزولی قوی 🔻"
    )

    # Build text
    lines = []
    lines.append(f"📊 *تحلیل ۷ روز اخیر* {COIN_ICONS.get(code, '🔸')} *{code}*")
    lines.append(f"🕒 {shamsi_now()}")
    lines.append(DIVIDER)
    lines.append(f"💰 قیمت ابتدای بازه: {fmt_amount(first_price, chat_id)}")
    lines.append(f"💰 قیمت فعلی: {fmt_amount(current_price, chat_id)}")
    lines.append(f"📈 تغییر ۷ روزه: *{pct_change_7d:+.2f}٪* — {trend_desc}")
    lines.append(f"📈 تغییر ۲۴ ساعت: {pct_change_24h:+.2f}٪")
    lines.append(f"📈 تغییر ۳ روز: {pct_change_3d:+.2f}٪")
    lines.append("")
    lines.append(f"📈 بیشترین قیمت: {fmt_amount(highest, chat_id)}")
    lines.append(f" 📅 {shamsi_date(high_row['timestamp'])}")
    lines.append(f"📉 کمترین قیمت: {fmt_amount(lowest, chat_id)}")
    lines.append(f" 📅 {shamsi_date(low_row['timestamp'])}")
    lines.append(f"📐 محدوده نوسان: {range_pct:.2f}%")
    lines.append(DIVIDER)
    lines.append(f"⚡ بیشترین رشد روزانه: *{best_day_pct:+.2f}%* ({best_day_date})")
    lines.append(f"⚡ بیشترین افت روزانه: *{worst_day_pct:+.2f}%* ({worst_day_date})")
    lines.append(f"📐 نوسان‌پذیری روزانه: *{volatility:.2f}%*")
    lines.append(f"🟢 روز مثبت: {up_days} | 🔴 روز منفی: {down_days}")
    lines.append(f"🔁 پشت‌سرهم {consecutive_type}: {consecutive_days} روز")
    lines.append(f"📉 بیشینه کاهش (Max DD): *{max_drawdown:.2f}%*")
    lines.append(f"📈 بیشینه رشد (Max Run-up): *{max_runup:.2f}%*")
    lines.append(f"📊 بازده تجمعی: *{pct_change_7d:+.2f}%*")
    lines.append("")
    lines.append(f"📊 میانگین حجم روزانه: `{avg_volume:,.0f}`")
    lines.append(f"🔊 روند حجم: {volume_trend}")
    lines.append("")
    if rsi_daily is not None:
        lines.append(f"🎯 RSI روزانه فعلی: *{rsi_daily:.1f}*")
    else:
        lines.append("🎯 RSI روزانه فعلی: -*")
    if ema20_daily is not None and ema50_daily is not None:
        lines.append(f"📈 EMA20 روزانه: {fmt_amount(ema20_daily, chat_id)}")
        lines.append(f"📈 EMA50 روزانه: {fmt_amount(ema50_daily, chat_id)}")
        lines.append(f"📊 وضعیت قیمت نسبت به EMA20/50: {price_vs_ema}")
    if macd_hist_daily is not None:
        lines.append(f"📈 MACD روزانه: {'مثبت 📈' if macd_hist_daily > 0 else 'منفی 📉'}")
    if adx_daily is not None:
        lines.append(f"💪 ADX روزانه: {adx_daily:.1f} — {trend_strength}")
    if bb_position is not None:
        lines.append(f"📏 Bollinger Position: {bb_position:.1f}%")
    if bb_width_daily is not None:
        lines.append(f"📏 Bollinger Width: {bb_width_daily:.2f}%")
    lines.append(DIVIDER)
    lines.append("ℹ️ گزارش فقط بر اساس داده قیمت/حجم قراردادهای Perpetual MEXC است.")

    return rtl_lines("\n".join(lines))


def format_ladder_block(entries, take_profits, stop_losses, chat_id):
    nums = ["1️⃣", "2️⃣", "3️⃣"]
    entries_txt = "\n".join(
        f" {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(entries)
    )
    tp_txt = "\n".join(
        f" {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(take_profits)
    )
    sl_txt = "\n".join(
        f" {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(stop_losses)
    )
    return (
        f"📥 ورود پله‌ای\n{entries_txt}\n\n"
        f"🎯 حد سود\n{tp_txt}\n\n"
        f"🛑 حد ضرر\n{sl_txt}"
    )


def format_plan_pretty(plan, code, chat_id):
    direction = "🟢 لانگ (خرید)" if plan.direction == "LONG" else "🔴 شورت (فروش)"
    funding = f"\n💰 فاندینگ: {plan.funding_rate:+.3f}%" if plan.funding_rate else ""
    return rtl_lines(
        f"{mood_emoji(plan)} {COIN_ICONS.get(code, '🔸')} {sym(code)} — {direction}\n"
        f"🕒 {shamsi_now()}\n"
        f"📊 روند: {plan.trend} | RSI: {plan.rsi:.1f}\n"
        f"🎯 اطمینان: {plan.confidence:.0f}٪ ({confidence_badge(plan.confidence)})\n"
        f"⚡ اهرم پیشنهادی: {plan.leverage}x{funding}\n{DIVIDER}\n"
        f"💰 قیمت: {fmt_amount(plan.current_price, chat_id)}\n\n"
        f"{format_ladder_block(plan.entries, plan.take_profits, plan.stop_losses, chat_id)}\n"
        f"{DIVIDER}\n⚠️ امتیاز اطمینان تخمینی است، نه تضمین."
    )


def format_plan_compact(plan, code, chat_id):
    avg = sum(e * w for e, w in zip(plan.entries, ENTRY_WEIGHTS))
    direction = "🟢 لانگ" if plan.direction == "LONG" else "🔴 شورت"
    return rtl_lines(
        f"{mood_emoji(plan)} {COIN_ICONS.get(code, '🔸')} {code} — {direction} | "
        f"اطمینان: {plan.confidence:.0f}٪\n"
        f" ورود میانگین: {fmt_amount(avg, chat_id)}\n"
        f" 🎯 سود: {fmt_amount(plan.take_profits[0], chat_id)}\n"
        f" 🛑 ضرر: {fmt_amount(plan.stop_losses[0], chat_id)}"
    )


def format_prices_pretty(prices, chat_id):
    if not prices:
        return "⚠️ قیمت لحظه‌ای دریافت نشد."
    lines = ["💰 قیمت لحظه‌ای قراردادها", f"🕒 {shamsi_now()}", DIVIDER]
    for code, price in prices.items():
        lines.append(
            f"{COIN_ICONS.get(code, '🔸')} {code} {fmt_amount(price, chat_id)}"
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
    # Show all COIN_CODES with status
    buttons = []
    for c in COIN_CODES:
        if c in cache.valid_codes:
            label = f"{COIN_ICONS.get(c, '🔸')} {c} ✅"
        else:
            label = f"{COIN_ICONS.get(c, '🔸')} {c} ❌"
        buttons.append(InlineKeyboardButton(label, callback_data=f"coin_{c}"))
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
        "🌟 به سیگنالستان خوش اومدی! 🌟\n"
        f"{DIVIDER}\n"
        f"🛰️ در حال رصد {len(cache.valid_codes)} قرارداد Perpetual هستم\n"
        "⏱️ هر ۱۵ دقیقه بهترین سیگنال‌ها بررسی می‌شوند\n"
        "👇 برای بررسی دستی از منوی زیر استفاده کن\n\n"
        "برای توقف اشتراک: /stop\n\n"
        "⚠️ تحلیل تکنیکال است، نه توصیه مالی."
    )


MENU_PROMPT = "👇 یکی از گزینه‌ها رو انتخاب کن:"
MAIN_MENU_HEADER = "✨ پنل سیگنال‌یار ✨\n" + DIVIDER + "\n" + MENU_PROMPT


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
                chat_id=chat_id,
                text=chunk,
                parse_mode="Markdown"
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
        f"📢✨ پیشنهادات لحظه‌ای ✨📢\n"
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
                chat_id=chat_id,
                text=chunk,
                parse_mode="Markdown"
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
                    *(send_report_to_user(app, chat_id, top) for chat_id in list(subscribed_chat_ids)),
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
    logger.info("Signal Bot V8 started")


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
```
