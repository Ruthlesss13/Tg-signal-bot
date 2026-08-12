"""
Telegram Signal Bot V8 - Binance Edition (Complete)
- Exchange: Binance (USDT perpetual linear swaps)
- 64 coins with replacements for missing ones
- Market status for all coins (SWAP OK / NO SWAP / TICKER ERROR)
- 5-category scoring without double counting
- Signal reasons with ✅/⚠️
- Full weekly report with all statistics
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
from ta.volume import VolumeWeightedAveragePrice
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

# ---------- 64 coins with replacements ----------
COIN_ICONS = {
    "DOGE": "🐕", "SOL": "◎", "SHIB": "🦴", "BTC": "₿", "ETH": "Ξ",
    "BNB": "🔶", "ZEC": "🛡️", "ADA": "🔷", "DOGS": "🐾", "NOT": "💎",
    "LINK": "🔗", "LTC": "Ł", "UNI": "🦄", "TRX": "⚡", "VET": "🌿",      # replaced GRAM
    "SUI": "💧", "PEPE": "🐸", "HMSTR": "🐹", "BABYDOGE": "🐶", "PUMP": "🚀",
    "THETA": "🌀",  # replaced SPCX
    "PENDLE": "📐", "CAKE": "🥞", "S": "💨", "DEXE": "🗳️",
    "SKY": "☁️", "FTM": "🔥",  # replaced ASTER
    "HYPE": "🌊", "RENDER": "🖥️", "POL": "🟣",
    "ONDO": "🏦", "XAUT": "🥇", "ENA": "🌐", "FLOKI": "🐕‍🦺", "TAO": "🧠",
    "ARB": "🔵", "MAGIC": "🪄", "CFX": "🌲", "WLD": "👁️", "LDO": "🌊",
    "DYDX": "📉", "APT": "🅰️", "ENS": "🏷️", "ONE": "🎐", "API3": "🔌",
    "STORJ": "💾", "SLP": "🍯", "ZRX": "0️⃣", "ATOM": "⚛️", "AVAX": "🔺",
    "AXS": "🐚", "NEAR": "Ⓝ", "GMT": "👟", "CHZ": "🌶️", "HBAR": "Ⓗ",
    "CRO": "💠", "ETC": "⟠", "DOT": "⚪", "AAVE": "👻", "FIL": "📁",
    "XRP": "✕", "BCH": "🟢", "IMX": "🛡️",  # replaced A
    "XLM": "✨", "RNDR": "🎨",  # added to reach 64
}
# Ensure we have exactly 64 coins
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

# Category weights (sum = 100)
WEIGHT_TREND = 25
WEIGHT_MOMENTUM = 25
WEIGHT_VOLUME = 15
WEIGHT_VOLATILITY = 15
WEIGHT_HTF = 20

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

# ---------- Binance Exchange ----------
exchange = ccxt.binance({
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
    direction: str          # "LONG" or "SHORT"
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
        self.prices = {}
        self.ohlcv = {tf: {} for tf in TIMEFRAMES}
        self.ohlcv_updated_at = {tf: {} for tf in TIMEFRAMES}
        self.valid_codes = []
        self.exchange_symbols = {}
        self.market_meta = {}
        self.market_status = {
            code: {"status": "NO SWAP", "symbol": None, "error": None}
            for code in COIN_CODES
        }
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
                self.market_status[code] = {
                    "status": "NO SWAP",
                    "symbol": None,
                    "error": None,
                }
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
                    logger.debug("No active USDT linear swap for %s on Binance", code)
                    continue
                candidates.sort(key=lambda x: x[0])
                symbol, market = candidates[0]
                selected[code] = symbol
                self.market_meta[code] = market
                self.market_status[code] = {
                    "status": "SWAP OK",
                    "symbol": symbol,
                    "error": None,
                }
            self.exchange_symbols = selected
            self.valid_codes = list(selected.keys())
            logger.info(
                "Binance swap markets: %s/%s selected (USDT linear perpetual)",
                len(self.valid_codes), len(COIN_CODES),
            )
            if not self.valid_codes:
                logger.error("No Binance USDT linear swap market was found.")
        except Exception as e:
            logger.exception("load_markets failed: %s", e)
            for code in COIN_CODES:
                self.market_status[code] = {
                    "status": "NO SWAP",
                    "symbol": None,
                    "error": f"{type(e).__name__}: {e}",
                }

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
        if df is None or len(df) < 2:
            return df
        now = pd.Timestamp.now(tz="UTC")
        latest = df["timestamp"].iloc[-1]
        timeframe_delta = None
        if len(df) >= 2:
            timeframe_delta = df["timestamp"].iloc[-1] - df["timestamp"].iloc[-2]
        if timeframe_delta is not None and timeframe_delta > pd.Timedelta(0):
            if latest + timeframe_delta > now:
                return df.iloc[:-1].copy().reset_index(drop=True)
        return df.iloc[:-1].copy().reset_index(drop=True)

    async def update_prices(self, force=False):
        if not self.exchange_symbols:
            self._load_markets()
        if (
            not force
            and self.last_price_update
            and time.time() - self.last_price_update < 60
        ):
            return self.prices

        async def fetch_one(code):
            symbol = self.symbol_for_code(code)
            if not symbol:
                return code, None
            async with self._price_sem:
                try:
                    ticker = await asyncio.to_thread(exchange.fetch_ticker, symbol)
                    price = (
                        ticker.get("last") or ticker.get("close")
                        or ticker.get("bid") or ticker.get("ask")
                    )
                    if price is None:
                        raise ValueError("ticker has no usable price")
                    self.market_status[code] = {
                        **self.market_status.get(code, {}),
                        "status": "SWAP OK",
                        "symbol": symbol,
                        "error": None,
                    }
                    return code, float(price)
                except Exception as e:
                    self.market_status[code] = {
                        **self.market_status.get(code, {}),
                        "status": "TICKER ERROR",
                        "symbol": symbol,
                        "error": f"{type(e).__name__}: {e}",
                    }
                    logger.warning(
                        "ticker failed | code=%s | type=%s | symbol=%s | error=%s",
                        code, type(e).__name__, symbol, e,
                    )
                    return code, None

        results = await asyncio.gather(*(fetch_one(c) for c in COIN_CODES))
        self.prices = {code: price for code, price in results if price is not None}
        self.last_price_update = time.time()
        logger.info("Live prices loaded: %s/%s", len(self.prices), len(COIN_CODES))
        return self.prices

    async def _fetch_ohlcv_symbol(self, code, timeframe, limit=250):
        symbol = self.symbol_for_code(code)
        if not symbol:
            logger.warning("OHLCV skipped | code=%s | reason=no_swap_symbol", code)
            return None
        async with self._sem:
            try:
                raw = await asyncio.to_thread(
                    exchange.fetch_ohlcv, symbol, timeframe, None, limit,
                )
                df = self._to_dataframe(raw)
                if df is None or len(df) < 10:
                    logger.warning(
                        "OHLCV insufficient | code=%s | symbol=%s | tf=%s | rows=%s",
                        code, symbol, timeframe, 0 if df is None else len(df),
                    )
                    return None
                closed = self._drop_forming_candle(df)
                if closed is None or len(closed) < 5:
                    logger.warning(
                        "OHLCV closed data insufficient | code=%s | symbol=%s | tf=%s | rows=%s",
                        code, symbol, timeframe, 0 if closed is None else len(closed),
                    )
                    return None
                return closed
            except Exception as e:
                logger.warning(
                    "OHLCV failed | code=%s | symbol=%s | tf=%s | error=%s",
                    code, symbol, timeframe, e,
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
                await self.ensure_symbol_data(code, TIMEFRAMES, force=force)
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
            logger.warning("Indicators insufficient | code=%s | rows=%s", code, 0 if df is None else len(df))
            await self.ensure_symbol_data(code, ("1h", "4h"), force=True)
            df = self.ohlcv["1h"].get(code)
            df4 = self.ohlcv["4h"].get(code)
            if df is None or len(df) < 210:
                return None

        try:
            close = df["close"]

            # ===================== Trend =====================
            ema20 = EMAIndicator(close, window=20).ema_indicator()
            ema50 = EMAIndicator(close, window=50).ema_indicator()
            ema200 = EMAIndicator(close, window=200).ema_indicator()

            # ===================== Momentum =====================
            rsi = RSIIndicator(close, window=14).rsi()
            stoch = StochRSIIndicator(close, window=14, smooth1=3, smooth2=3)
            stoch_k = stoch.stochrsi_k() * 100
            macd = MACD(close, window_slow=26, window_fast=12, window_sign=9)
            macd_line = macd.macd()
            macd_signal = macd.macd_signal()
            macd_hist = macd.macd_diff()
            roc = ROCIndicator(close, window=12).roc()
            cci = CCIIndicator(df["high"], df["low"], close, window=20).cci()
            williams = WilliamsRIndicator(df["high"], df["low"], close, lbp=14).williams_r()

            # ===================== Trend Strength =====================
            adx_ind = ADXIndicator(df["high"], df["low"], close, window=14)
            adx = adx_ind.adx()
            plus_di = adx_ind.adx_pos()
            minus_di = adx_ind.adx_neg()

            # ===================== Volatility =====================
            atr = AverageTrueRange(df["high"], df["low"], close, window=14).average_true_range()
            bb = BollingerBands(close, window=20, window_dev=2)
            bb_percent = bb.bollinger_pband()
            bb_width = bb.bollinger_wband()

            # ===================== Volume =====================
            volume_sma = df["volume"].rolling(20).mean()
            volume_ratio = df["volume"] / volume_sma
            volume_ma20 = df["volume"].rolling(20).mean()
            volume_ma50 = df["volume"].rolling(50).mean()

            # ===================== VWAP =====================
            vwap = VolumeWeightedAveragePrice(
                high=df["high"], low=df["low"], close=close, volume=df["volume"], window=20
            ).volume_weighted_average_price()

            # ===================== Current Values =====================
            price = float(close.iloc[-1])
            atr_value = float(atr.iloc[-1])
            atr_pct = (atr_value / price * 100) if price > 0 else 0
            ema20_value = float(ema20.iloc[-1])
            ema50_value = float(ema50.iloc[-1])
            ema200_value = float(ema200.iloc[-1])
            price_ema200_pct = ((price - ema200_value) / ema200_value * 100)
            price_ema50_pct = ((price - ema50_value) / ema50_value * 100)

            # ===================== EMA Cross =====================
            ema20_prev = float(ema20.iloc[-2]) if len(ema20) >= 2 else ema20_value
            ema50_prev = float(ema50.iloc[-2]) if len(ema50) >= 2 else ema50_value
            bullish_cross = (ema20_prev <= ema50_prev and ema20_value > ema50_value)
            bearish_cross = (ema20_prev >= ema50_prev and ema20_value < ema50_value)

            # ===================== Volume Spike =====================
            vr = float(volume_ratio.iloc[-1])
            volume_spike = vr >= 1.5
            volume_trend_up = (float(volume_ma20.iloc[-1]) > float(volume_ma50.iloc[-1]))

            # ===================== Higher Timeframe =====================
            higher_tf_up = None
            ema4_value = None
            if df4 is not None and len(df4) >= 205:
                ema4 = EMAIndicator(df4["close"], window=200).ema_indicator()
                ema4_value = ema4.iloc[-1]
                if pd.notna(ema4_value):
                    higher_tf_up = bool(df4["close"].iloc[-1] > ema4_value)

            values = {
                "price": price,
                "ema20": ema20_value,
                "ema50": ema50_value,
                "ema200": ema200_value,
                "price_above_ema20": price > ema20_value,
                "price_above_ema50": price > ema50_value,
                "price_above_trend": price > ema200_value,
                "price_ema50_pct": price_ema50_pct,
                "price_ema200_pct": price_ema200_pct,
                "ema20_above_ema50": ema20_value > ema50_value,
                "ema20_bullish_cross": bullish_cross,
                "ema20_bearish_cross": bearish_cross,
                "rsi": float(rsi.iloc[-1]),
                "stoch_k": float(stoch_k.iloc[-1]),
                "macd": float(macd_line.iloc[-1]),
                "macd_signal": float(macd_signal.iloc[-1]),
                "macd_hist": float(macd_hist.iloc[-1]),
                "roc": float(roc.iloc[-1]),
                "cci": float(cci.iloc[-1]),
                "williams_r": float(williams.iloc[-1]),
                "adx": float(adx.iloc[-1]),
                "plus_di": float(plus_di.iloc[-1]),
                "minus_di": float(minus_di.iloc[-1]),
                "atr": atr_value,
                "atr_pct": atr_pct,
                "bb_percent": float(bb_percent.iloc[-1]),
                "bb_width": float(bb_width.iloc[-1]),
                "volume_ratio": vr,
                "volume_spike": volume_spike,
                "volume_trend_up": volume_trend_up,
                "vwap": float(vwap.iloc[-1]),
                "price_above_vwap": price > float(vwap.iloc[-1]),
                "higher_tf_trend_up": higher_tf_up,
                "higher_tf_ema200": ema4_value,
                "trend_label": "صعودی 📈" if price > ema200_value else "نزولی 📉",
                "is_trending": bool(adx.iloc[-1] >= ADX_TREND_THRESHOLD),
            }
            if any(pd.isna(v) for v in values.values() if isinstance(v, (int, float))):
                return None
            return values
        except Exception as e:
            logger.exception("Indicator error | code=%s | error=%s", code, e)
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
                logger.debug("Funding failed | code=%s | error=%s", code, e)
                return 0.0

cache = MarketDataCache()

# ---------- Helper functions ----------
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
    for _ in range(3):
        try:
            r = requests.get("https://api.nobitex.ir/market/stats", params={"srcCurrency": "usdt", "dstCurrency": "rls"}, timeout=8)
            r.raise_for_status()
            rial = float(r.json()["stats"]["usdt-rls"]["latest"])
            return rial / 10
        except Exception:
            time.sleep(1)
    raise RuntimeError("Nobitex failed")

def fetch_irt_rate_wallex():
    r = requests.get("https://api.wallex.ir/v1/markets", timeout=8)
    r.raise_for_status()
    data = r.json()
    return float(data["result"]["symbols"]["USDTTMN"]["stats"]["lastPrice"])

def get_irt_rate():
    now = time.time()
    if _irt_rate_cache["value"] is not None and now - _irt_rate_cache["ts"] < IRT_RATE_TTL_SECONDS:
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

# ---------- New Scoring System ----------
def category_scores(direction, ind):
    long_side = direction == "LONG"

    # ============ TREND / 25 ============
    trend = 0
    if long_side:
        if ind["price_above_ema200"]:
            trend += 8
        if ind["ema20_above_ema50"]:
            trend += 7
        if ind["price_above_ema50"]:
            trend += 4
        if ind["ema20_bullish_cross"]:
            trend += 3
        if ind["adx"] >= 25:
            trend += 3
    else:
        if not ind["price_above_ema200"]:
            trend += 8
        if not ind["ema20_above_ema50"]:
            trend += 7
        if not ind["price_above_ema50"]:
            trend += 4
        if ind["ema20_bearish_cross"]:
            trend += 3
        if ind["adx"] >= 25:
            trend += 3
    trend = min(trend, 25)

    # ============ MOMENTUM / 25 ============
    momentum = 0
    macd_ok = ind["macd_hist"] > 0 if long_side else ind["macd_hist"] < 0
    di_ok = ind["plus_di"] > ind["minus_di"] if long_side else ind["minus_di"] > ind["plus_di"]
    roc_ok = ind["roc"] > 0 if long_side else ind["roc"] < 0
    cci_ok = ind["cci"] > 0 if long_side else ind["cci"] < 0
    williams_ok = ind["williams_r"] > -80 if long_side else ind["williams_r"] < -20

    if macd_ok:
        momentum += 7
    if di_ok:
        momentum += 5
    if roc_ok:
        momentum += 5
    if cci_ok:
        momentum += 4
    if williams_ok:
        momentum += 4
    momentum = min(momentum, 25)

    # ============ VOLUME / 15 ============
    volume = 0
    if ind["volume_ratio"] >= 1.5:
        volume += 8
    elif ind["volume_ratio"] >= 1.0:
        volume += 5
    elif ind["volume_ratio"] >= 0.7:
        volume += 2
    if ind["volume_trend_up"]:
        volume += 4
    if ind["volume_spike"]:
        volume += 3
    volume = min(volume, 15)

    # ============ VOLATILITY / 15 ============
    volatility = 0
    if 0.5 <= ind["atr_pct"] <= 5:
        volatility += 6
    elif ind["atr_pct"] <= 8:
        volatility += 4
    else:
        volatility += 1

    distance = abs(ind["price_ema200_pct"])
    if distance <= 5:
        volatility += 4
    elif distance <= 10:
        volatility += 2

    if 1 <= ind["bb_width"] <= 12:
        volatility += 5
    elif ind["bb_width"] <= 20:
        volatility += 3
    volatility = min(volatility, 15)

    # ============ HIGHER TIMEFRAME / 20 ============
    htf = 0
    if ind["higher_tf_trend_up"] is not None:
        if long_side and ind["higher_tf_trend_up"]:
            htf += 15
        elif not long_side and not ind["higher_tf_trend_up"]:
            htf += 15
    vwap_ok = ind["price_above_vwap"] if long_side else not ind["price_above_vwap"]
    if vwap_ok:
        htf += 5
    htf = min(htf, 20)

    return {
        "trend": trend,
        "momentum": momentum,
        "volume": volume,
        "volatility": volatility,
        "htf": htf,
    }

def score_direction(direction, ind):
    scores = category_scores(direction, ind)
    total = sum(scores.values())
    return round(max(0, min(100, total)), 1)

def decide_direction(ind):
    long_scores = category_scores("LONG", ind)
    short_scores = category_scores("SHORT", ind)
    long_score = sum(long_scores.values())
    short_score = sum(short_scores.values())

    long_base = ind["macd_hist"] > 0 and ind["plus_di"] >= ind["minus_di"]
    short_base = ind["macd_hist"] < 0 and ind["minus_di"] >= ind["plus_di"]

    if long_base and long_score >= MIN_SIGNAL_CONFIDENCE and long_score >= short_score + MIN_DIRECTION_GAP:
        return "LONG", long_score
    if short_base and short_score >= MIN_SIGNAL_CONFIDENCE and short_score >= long_score + MIN_DIRECTION_GAP:
        return "SHORT", short_score
    return None, max(long_score, short_score)

def signal_reasons(direction, ind):
    reasons = []
    warnings = []

    if direction == "LONG":
        if ind["price_above_ema200"]:
            reasons.append("قیمت بالای EMA200")
        if ind["ema20_above_ema50"]:
            reasons.append("EMA20 بالای EMA50")
        if ind["ema20_bullish_cross"]:
            reasons.append("کراس صعودی EMA20/EMA50")
        if ind["macd_hist"] > 0:
            reasons.append("MACD مثبت")
        if ind["plus_di"] > ind["minus_di"]:
            reasons.append("+DI > -DI")
        if ind["adx"] >= 25:
            reasons.append(f"ADX = {ind['adx']:.1f}")
        if ind["volume_ratio"] >= 1.5:
            reasons.append(f"حجم غیرعادی = {ind['volume_ratio']:.1f}×")
        elif ind["volume_ratio"] >= 1:
            reasons.append(f"حجم = {ind['volume_ratio']:.1f}× میانگین")
        if ind["higher_tf_trend_up"] is True:
            reasons.append("4H تأیید صعودی")
        if ind["price_above_vwap"]:
            reasons.append("قیمت بالای VWAP")
        if ind["roc"] > 0:
            reasons.append("ROC مثبت")
        if ind["cci"] > 0:
            reasons.append("CCI مثبت")
        if ind["rsi"] >= 68:
            warnings.append(f"RSI = {ind['rsi']:.1f} — نزدیک اشباع خرید")
        if ind["williams_r"] > -20:
            warnings.append(f"Williams %R = {ind['williams_r']:.1f} — اشباع خرید")
    else:
        if not ind["price_above_ema200"]:
            reasons.append("قیمت زیر EMA200")
        if not ind["ema20_above_ema50"]:
            reasons.append("EMA20 زیر EMA50")
        if ind["ema20_bearish_cross"]:
            reasons.append("کراس نزولی EMA20/EMA50")
        if ind["macd_hist"] < 0:
            reasons.append("MACD منفی")
        if ind["minus_di"] > ind["plus_di"]:
            reasons.append("-DI > +DI")
        if ind["adx"] >= 25:
            reasons.append(f"ADX = {ind['adx']:.1f}")
        if ind["volume_ratio"] >= 1.5:
            reasons.append(f"حجم غیرعادی = {ind['volume_ratio']:.1f}×")
        elif ind["volume_ratio"] >= 1:
            reasons.append(f"حجم = {ind['volume_ratio']:.1f}× میانگین")
        if ind["higher_tf_trend_up"] is False:
            reasons.append("4H تأیید نزولی")
        if not ind["price_above_vwap"]:
            reasons.append("قیمت زیر VWAP")
        if ind["roc"] < 0:
            reasons.append("ROC منفی")
        if ind["cci"] < 0:
            reasons.append("CCI منفی")
        if ind["rsi"] <= 32:
            warnings.append(f"RSI = {ind['rsi']:.1f} — نزدیک اشباع فروش")
        if ind["williams_r"] < -80:
            warnings.append(f"Williams %R = {ind['williams_r']:.1f} — اشباع فروش")

    return reasons, warnings

def format_quality(scores):
    def bar(value, maximum=100):
        ratio = max(0, min(1, value / maximum))
        filled = round(ratio * 10)
        return "█" * filled + "░" * (10 - filled)

    return (
        f"📊 *کیفیت سیگنال*\n"
        f"Trend {bar(scores['trend'], 25)} {scores['trend'] / 25 * 100:.0f}%\n"
        f"Momentum {bar(scores['momentum'], 25)} {scores['momentum'] / 25 * 100:.0f}%\n"
        f"Volume {bar(scores['volume'], 15)} {scores['volume'] / 15 * 100:.0f}%\n"
        f"Volatility {bar(scores['volatility'], 15)} {scores['volatility'] / 15 * 100:.0f}%\n"
        f"HTF Confirm {bar(scores['htf'], 20)} {scores['htf'] / 20 * 100:.0f}%"
    )

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

    risk = abs(avg_entry - stop)
    reward = abs(tp - avg_entry)
    rr = reward / risk if risk > 0 else 0
    entry_to_sl_pct = (risk / avg_entry * 100) if avg_entry > 0 else 0
    entry_to_tp_pct = (reward / avg_entry * 100) if avg_entry > 0 else 0
    sl_atr = risk / atr if atr > 0 else 0
    tp_atr = reward / atr if atr > 0 else 0

    return {
        "entries": entries,
        "stop_losses": [stop],
        "take_profits": [tp],
        "avg_entry": avg_entry,
        "risk": risk,
        "reward": reward,
        "rr": rr,
        "entry_to_sl_pct": entry_to_sl_pct,
        "entry_to_tp_pct": entry_to_tp_pct,
        "sl_atr": sl_atr,
        "tp_atr": tp_atr,
    }

def format_ladder_block(entries, take_profits, stop_losses, chat_id):
    nums = ["1️⃣", "2️⃣", "3️⃣"]
    entries_txt = "\n".join(f" {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(entries))
    tp_txt = "\n".join(f" {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(take_profits))
    sl_txt = "\n".join(f" {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(stop_losses))
    return (
        f"📥 ورود پله‌ای\n{entries_txt}\n\n"
        f"🎯 حد سود\n{tp_txt}\n\n"
        f"🛑 حد ضرر\n{sl_txt}"
    )

async def generate_trade_plan(code):
    ind = await cache.get_indicators(code)
    if not ind:
        return None

    direction, confidence = decide_direction(ind)
    if not direction:
        return None

    levels = build_ladder_weighted(ind, direction)
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
        entries=levels["entries"],
        stop_losses=levels["stop_losses"],
        take_profits=levels["take_profits"],
        funding_rate=funding,
        leverage=leverage,
    )

async def refresh_all_plans(force_data=False):
    if force_data or not cache.last_full_ohlcv_update or time.time() - cache.last_full_ohlcv_update > FULL_REFRESH_TTL_SECONDS:
        await cache.update_ohlcv(force=force_data)

    sem = asyncio.Semaphore(MAX_SIGNAL_CONCURRENCY)

    async def one(code):
        async with sem:
            try:
                return await generate_trade_plan(code)
            except Exception as e:
                logger.exception("Signal error | code=%s | error=%s", code, e)
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

    # Header
    header = (
        f"🧭 *وضعیت لحظه‌ای* {COIN_ICONS.get(code, '🔸')} *{sym(code)}*\n"
        f"🕒 {shamsi_now()}\n{DIVIDER}\n"
    )

    # Body with all indicators
    body = (
        f"💰 قیمت: {fmt_amount(ind['price'], chat_id)}\n"
        f"📊 روند EMA200: {ind['trend_label']}\n"
        f"📐 EMA20: {fmt_amount(ind['ema20'], chat_id)}\n"
        f"📐 EMA50: {fmt_amount(ind['ema50'], chat_id)}\n"
        f"📐 فاصله EMA50: {ind['price_ema50_pct']:+.2f}%\n"
        f"📐 فاصله EMA200: {ind['price_ema200_pct']:+.2f}%\n"
        f"🔄 EMA20/50: {'صعودی' if ind['ema20_above_ema50'] else 'نزولی'}\n"
        f"⚡ ADX: {ind['adx']:.1f} — {'روند قوی 💪' if ind['adx'] >= 25 else 'روند متوسط 🙂' if ind['adx'] >= ADX_TREND_THRESHOLD else 'بازار رنج 😐'}\n"
        f"📈 MACD: {'مثبت 📈' if ind['macd_hist'] > 0 else 'منفی 📉' if ind['macd_hist'] < 0 else 'خنثی ⚖️'}\n"
        f"🎯 RSI: {ind['rsi']:.1f} — {'اشباع خرید ⚠️' if ind['rsi'] > 70 else 'اشباع فروش ⚠️' if ind['rsi'] < 30 else 'نرمال'}\n"
        f"🌀 استوکاستیک RSI: {ind['stoch_k']:.1f} — {'نزدیک اشباع خرید' if ind['stoch_k'] > 80 else 'نزدیک اشباع فروش' if ind['stoch_k'] < 20 else 'نرمال'}\n"
        f"🚀 ROC: {ind['roc']:+.2f}%\n"
        f"📏 CCI: {ind['cci']:.1f}\n"
        f"〽️ Williams %R: {ind['williams_r']:.1f}\n"
        f"📏 Bollinger: {ind['bb_percent']:.2f} — {'نزدیک باند بالا' if ind['bb_percent'] >= 0.8 else 'نزدیک باند پایین' if ind['bb_percent'] <= 0.2 else 'داخل محدوده'}\n"
        f"📐 BB Width: {ind['bb_width']:.2f}\n"
        f"🔊 حجم: {ind['volume_ratio']:.2f}× میانگین\n"
        f"📡 VWAP: {fmt_amount(ind['vwap'], chat_id)}\n"
        f"🗺️ روند ۴ساعته: {'صعودی 📈' if ind['higher_tf_trend_up'] is True else 'نزولی 📉' if ind['higher_tf_trend_up'] is False else 'نامشخص'}\n"
        f"⚡ ATR: {fmt_amount(ind['atr'], chat_id)} ({ind['atr_pct']:.2f}%)\n"
        f"{DIVIDER}\n"
    )

    if direction and confidence >= MIN_SIGNAL_CONFIDENCE:
        scores = category_scores(direction, ind)
        levels = build_ladder_weighted(ind, direction)
        direction_text = "🟢 لانگ (خرید)" if direction == "LONG" else "🔴 شورت (فروش)"
        reasons, warnings = signal_reasons(direction, ind)

        reason_text = "\n".join(f" ✅ {x}" for x in reasons[:12])
        warning_text = "\n" + "\n".join(f" ⚠️ {x}" for x in warnings) if warnings else ""
        quality_text = format_quality(scores)

        footer = (
            f"📐 *سیگنال فعلی:* {direction_text}\n"
            f"🎯 امتیاز نهایی: *{confidence:.0f}٪* ({confidence_badge(confidence)})\n\n"
            f"🟢 *دلایل سیگنال*\n{reason_text}{warning_text}\n\n"
            f"{quality_text}\n\n"
            f"💰 *ریسک / بازده*\n"
            f"📊 R/R: *1:{levels['rr']:.2f}*\n"
            f"🛑 فاصله Entry → SL: *{levels['entry_to_sl_pct']:.2f}%* ({levels['sl_atr']:.2f} ATR)\n"
            f"🎯 فاصله Entry → TP: *{levels['entry_to_tp_pct']:.2f}%* ({levels['tp_atr']:.2f} ATR)\n\n"
            f"{format_ladder_block(levels['entries'], levels['take_profits'], levels['stop_losses'], chat_id)}\n"
        )
    else:
        footer = (
            f"💤 فعلاً سیگنال نهایی وجود ندارد.\n"
            f"امتیاز بهترین جهت: {confidence:.0f}٪\n"
            "برای جلوگیری از سیگنال ضعیف، جهت‌های متضاد باید اختلاف امتیاز کافی داشته باشند."
        )

    return rtl_lines(header + body + footer + f"\n{DIVIDER}\n⚠️ این تحلیل تکنیکال است و تضمین سود یا توصیه مالی نیست.")

async def generate_weekly_summary_async(code, chat_id):
    week_df = await cache.get_weekly_data(code)
    if week_df is None or len(week_df) < 2:
        return rtl_lines(
            f"{COIN_ICONS.get(code, '🔸')} *{code}*\n\n"
            "⚠️ حداقل داده‌ی لازم برای تحلیل ۷ روزه دریافت نشد."
        )

    week_df = week_df.sort_values("timestamp").reset_index(drop=True)
    close = week_df["close"]
    first_price = float(close.iloc[0])
    current_price = float(close.iloc[-1])
    if first_price <= 0:
        return "⚠️ قیمت تاریخی نامعتبر است."

    # ======== Returns ========
    cumulative_return = ((current_price / first_price) - 1) * 100
    returns = close.pct_change() * 100
    positive_days = int((returns > 0).sum())
    negative_days = int((returns < 0).sum())
    best_day = float(returns.max())
    worst_day = float(returns.min())
    best_idx = returns.idxmax()
    worst_idx = returns.idxmin()

    # ======== High / Low ========
    highest = float(week_df["high"].max())
    lowest = float(week_df["low"].min())
    range_pct = ((highest - lowest) / first_price * 100)
    high_row = week_df.loc[week_df["high"].idxmax()]
    low_row = week_df.loc[week_df["low"].idxmin()]

    # ======== Max Drawdown & Run-up ========
    running_max = close.cummax()
    drawdown = (close / running_max - 1) * 100
    max_drawdown = float(drawdown.min())

    running_min = close.cummin()
    runup = (close / running_min - 1) * 100
    max_runup = float(runup.max())

    # ======== Volatility ========
    volatility = float(returns.dropna().std() or 0)

    # ======== ATR Daily ========
    atr_series = AverageTrueRange(
        week_df["high"], week_df["low"], close,
        window=min(14, max(2, len(week_df) - 1))
    ).average_true_range()
    atr_daily = float(atr_series.iloc[-1]) if pd.notna(atr_series.iloc[-1]) else 0
    atr_pct = (atr_daily / current_price * 100) if current_price > 0 else 0

    # ======== Volume ========
    avg_volume = float(week_df["volume"].mean())
    first_volume = float(week_df["volume"].iloc[0])
    last_volume = float(week_df["volume"].iloc[-1])
    volume_trend_pct = ((last_volume / first_volume) - 1) * 100 if first_volume > 0 else 0
    volume_trend = "افزایشی 🔊" if volume_trend_pct > 10 else "کاهشی 🔇" if volume_trend_pct < -10 else "خنثی"

    # ======== Daily Indicators (using full daily data for accuracy) ========
    daily_all = cache.ohlcv["1d"].get(code)
    if daily_all is not None and len(daily_all) >= 50:
        d_close = daily_all["close"]
        rsi = RSIIndicator(d_close, window=14).rsi()
        ema20 = EMAIndicator(d_close, window=20).ema_indicator()
        ema50 = EMAIndicator(d_close, window=50).ema_indicator()
        macd = MACD(d_close, window_slow=26, window_fast=12, window_sign=9)
        adx_ind = ADXIndicator(daily_all["high"], daily_all["low"], d_close, window=14)
        bb = BollingerBands(d_close, window=20, window_dev=2)

        daily_rsi = float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else None
        daily_ema20 = float(ema20.iloc[-1]) if pd.notna(ema20.iloc[-1]) else None
        daily_ema50 = float(ema50.iloc[-1]) if pd.notna(ema50.iloc[-1]) else None
        daily_macd = float(macd.macd_diff().iloc[-1]) if pd.notna(macd.macd_diff().iloc[-1]) else None
        daily_adx = float(adx_ind.adx().iloc[-1]) if pd.notna(adx_ind.adx().iloc[-1]) else None
        bb_position = float(bb.bollinger_pband().iloc[-1]) if pd.notna(bb.bollinger_pband().iloc[-1]) else None
        bb_width = float(bb.bollinger_wband().iloc[-1]) if pd.notna(bb.bollinger_wband().iloc[-1]) else None
    else:
        daily_rsi = daily_ema20 = daily_ema50 = daily_macd = daily_adx = bb_position = bb_width = None

    # ======== Trend ========
    if daily_ema20 is not None and daily_ema50 is not None:
        if current_price > daily_ema20 and daily_ema20 > daily_ema50:
            trend = "صعودی قوی 📈"
        elif current_price > daily_ema50:
            trend = "صعودی ملایم 📈"
        elif current_price < daily_ema20 and daily_ema20 < daily_ema50:
            trend = "نزولی قوی 📉"
        else:
            trend = "نزولی ملایم 📉"
    else:
        trend = "نامشخص"

    # ======== Consecutive days ========
    returns_vals = returns.dropna().tolist()
    consecutive_up = 0
    for v in reversed(returns_vals):
        if v > 0:
            consecutive_up += 1
        else:
            break
    consecutive_down = 0
    for v in reversed(returns_vals):
        if v < 0:
            consecutive_down += 1
        else:
            break

    # ======== Momentum + Volume ========
    if daily_macd is not None and daily_macd > 0 and volume_trend_pct > 0:
        momentum_volume = "مومنتوم با حجم تأیید می‌شود 🟢"
    elif daily_macd is not None and daily_macd < 0 and volume_trend_pct < 0:
        momentum_volume = "ضعف مومنتوم با کاهش حجم 🔴"
    else:
        momentum_volume = "تأیید کامل وجود ندارد ⚠️"

    # ======== 3d & 24h returns ========
    ret_3d = ((current_price / float(close.iloc[max(0, len(close)-4)])) - 1) * 100 if len(close) >= 4 else 0
    ret_24h = float(returns.iloc[-1]) if not returns.empty else 0

    best_date = shamsi_date(week_df.loc[best_idx, "timestamp"]) if best_idx in week_df.index else "-"
    worst_date = shamsi_date(week_df.loc[worst_idx, "timestamp"]) if worst_idx in week_df.index else "-"

    # ======== Build Output ========
    text = (
        f"📊 *تحلیل ۷ روز اخیر* {COIN_ICONS.get(code, '🔸')} *{code}*\n"
        f"🕒 {shamsi_now()}\n{DIVIDER}\n"
        f"💰 قیمت فعلی: {fmt_amount(current_price, chat_id)}\n"
        f"📈 بازده ۷ روزه: *{cumulative_return:+.2f}%*\n"
        f"📈 بازده ۳ روزه: *{ret_3d:+.2f}%*\n"
        f"📈 بازده ۲۴h: *{ret_24h:+.2f}%*\n"
        f"{DIVIDER}\n"
        f"📈 بالاترین: {fmt_amount(highest, chat_id)} 📅 {shamsi_date(high_row['timestamp'])}\n"
        f"📉 پایین‌ترین: {fmt_amount(lowest, chat_id)} 📅 {shamsi_date(low_row['timestamp'])}\n"
        f"📏 محدوده ۷ روزه: *{range_pct:.2f}%*\n"
        f"🚀 بیشینه رشد (Max Run-up): *{max_runup:+.2f}%*\n"
        f"🛑 بیشینه کاهش (Max Drawdown): *{max_drawdown:.2f}%*\n"
        f"⚡ ATR روزانه: *{atr_pct:.2f}%*\n"
        f"📐 نوسان‌پذیری: *{volatility:.2f}%*\n"
        f"{DIVIDER}\n"
        f"🟢 روز مثبت: {positive_days} | 🔴 روز منفی: {negative_days}\n"
        f"🔥 بهترین روز: *{best_day:+.2f}%* ({best_date})\n"
        f"💥 بدترین روز: *{worst_day:+.2f}%* ({worst_date})\n"
        f"📈 پشت‌سرهم صعودی: {consecutive_up} روز\n"
        f"📉 پشت‌سرهم نزولی: {consecutive_down} روز\n"
        f"{DIVIDER}\n"
        f"📊 میانگین حجم: `{avg_volume:,.0f}`\n"
        f"🔊 روند حجم: {volume_trend} ({volume_trend_pct:+.1f}%)\n"
        f"🧠 {momentum_volume}\n"
        f"{DIVIDER}\n"
        f"📈 *روند روزانه:* {trend}\n"
        f"📐 قیمت نسبت به EMA20: {'بالای 📈' if daily_ema20 is not None and current_price > daily_ema20 else 'زیر 📉' if daily_ema20 is not None else 'نامشخص'}\n"
        f"📐 قیمت نسبت به EMA50: {'بالای 📈' if daily_ema50 is not None and current_price > daily_ema50 else 'زیر 📉' if daily_ema50 is not None else 'نامشخص'}\n"
        f"📈 MACD روزانه: {'مثبت 📈' if daily_macd is not None and daily_macd > 0 else 'منفی 📉' if daily_macd is not None else '-'}\n"
        f"💪 ADX روزانه: {daily_adx:.1f}" if daily_adx is not None else "💪 ADX روزانه: -"
    )
    text += f"\n🎯 RSI روزانه: {daily_rsi:.1f}" if daily_rsi is not None else "\n🎯 RSI روزانه: -"
    text += f"\n📏 موقعیت بولینگر: {bb_position*100:.1f}%" if bb_position is not None else "\n📏 موقعیت بولینگر: -"
    text += f"\n📐 پهنای بولینگر: {bb_width:.2f}" if bb_width is not None else "\n📐 پهنای بولینگر: -"
    text += f"\n{DIVIDER}\nℹ️ داده‌ها از قراردادهای USDT Linear Perpetual در بایننس محاسبه شده‌اند."

    return rtl_lines(text)

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
    lines = ["💰 قیمت لحظه‌ای قراردادها", f"🕒 {shamsi_now()}", DIVIDER]
    for code in COIN_CODES:
        status = cache.market_status.get(code, {}).get("status")
        if status == "SWAP OK" and code in prices and prices[code] is not None:
            lines.append(f"{COIN_ICONS.get(code, '🔸')} {code} {fmt_amount(prices[code], chat_id)}")
        elif status == "SWAP OK":
            lines.append(f"{COIN_ICONS.get(code, '🔸')} {code} ⚠️ در حال دریافت...")
        elif status == "TICKER ERROR":
            lines.append(f"{COIN_ICONS.get(code, '🔸')} {code} 🟠 خطا در دریافت قیمت")
        else:
            lines.append(f"{COIN_ICONS.get(code, '🔸')} {code} ⚪ در دسترس نیست")
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
        rows[-1].extend(InlineKeyboardButton("\u2063", callback_data="noop") for _ in range(columns - len(rows[-1])))
    return rows

def kb_currency():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💵 دلار (USDT)", callback_data="cur_USDT")],
        [InlineKeyboardButton("💴 تومان (IRT)", callback_data="cur_IRT")],
        [InlineKeyboardButton("💱 هر دو", callback_data="cur_BOTH")],
    ])

def kb_main(user_id):
    rows = [
        [InlineKeyboardButton("💰 قیمت لحظه‌ای", callback_data="menu_prices"), InlineKeyboardButton("🪙 انتخاب ارز", callback_data="menu_coins")],
        [InlineKeyboardButton("📊 همه پیشنهادات", callback_data="menu_all"), InlineKeyboardButton("🔄 شروع مجدد", callback_data="restart_currency")],
    ]
    if is_admin(user_id):
        rows.append([InlineKeyboardButton("⚙️ پنل مدیریت", callback_data="admin_panel"), InlineKeyboardButton("\u2063", callback_data="noop")])
    return InlineKeyboardMarkup(rows)

def kb_back_main():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")]])

def kb_coins():
    buttons = []
    for code in COIN_CODES:
        status = cache.market_status.get(code, {}).get("status")
        if status == "SWAP OK":
            label = f"{COIN_ICONS.get(code, '🔸')} {code} 🟢"
        elif status == "TICKER ERROR":
            label = f"{COIN_ICONS.get(code, '🔸')} {code} 🟠"
        else:
            label = f"{COIN_ICONS.get(code, '🔸')} {code} ⚪"
        buttons.append(InlineKeyboardButton(label, callback_data=f"coin_{code}"))
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

    await context.bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=chat_id))
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
        await query.edit_message_text(MAIN_MENU_HEADER, reply_markup=kb_main(user_id), parse_mode="Markdown")
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
        if code not in COIN_CODES:
            return
        status = cache.market_status.get(code, {}).get("status")
        if status != "SWAP OK":
            error = cache.market_status.get(code, {}).get("error")
            if status == "TICKER ERROR":
                text = (
                    f"{COIN_ICONS.get(code, '🔸')} *{sym(code)}*\n"
                    f"{DIVIDER}\n"
                    f"🟠 وضعیت: *TICKER ERROR*\n"
                    f"⚠️ دریافت قیمت لحظه‌ای ناموفق بود.\n"
                    f"نوع خطا: `{error or '-'}`"
                )
            else:
                text = (
                    f"{COIN_ICONS.get(code, '🔸')} *{code}*\n"
                    f"{DIVIDER}\n"
                    "⚪ وضعیت: *NO SWAP*\n"
                    "در حال حاضر قرارداد USDT Linear Perpetual فعال برای این ارز در بایننس پیدا نشد."
                )
            await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
            await query.edit_message_text(rtl_lines(text), reply_markup=kb_back_main(), parse_mode="Markdown")
            set_interactive_screen(chat_id, [query.message.message_id])
            return

        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text(
            rtl_lines(f"{COIN_ICONS.get(code, '🔸')} *{sym(code)}*\n{DIVIDER}\n🟢 وضعیت: *SWAP OK*\n{MENU_PROMPT}"),
            reply_markup=kb_coin_detail(code),
            parse_mode="Markdown",
        )
        set_interactive_screen(chat_id, [query.message.message_id])
        return

    if data.startswith("suggest_"):
        auto = data.endswith("_auto")
        code = data[len("suggest_"):-len("_auto")] if auto else data[len("suggest_"):]
        if code not in COIN_CODES:
            return
        status = cache.market_status.get(code, {}).get("status")
        if status != "SWAP OK":
            await query.edit_message_text(
                f"⚠️ قرارداد {code} در بایننس در دسترس نیست.\nوضعیت: {status}",
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
                await query.edit_message_text(split_long_message(text)[0], reply_markup=markup, parse_mode="Markdown")
                set_interactive_screen(chat_id, [query.message.message_id])
        except asyncio.TimeoutError:
            await query.edit_message_text("⏰ دریافت اطلاعات بیش از حد طول کشید.", reply_markup=kb_back_main())
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
        if code not in COIN_CODES:
            return
        status = cache.market_status.get(code, {}).get("status")
        if status != "SWAP OK":
            await query.edit_message_text(
                f"⚠️ قرارداد {code} در بایننس در دسترس نیست.\nوضعیت: {status}",
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
            await query.edit_message_text("⏰ دریافت داده‌های هفتگی طول کشید.", reply_markup=kb_back_main())
        except Exception as e:
            logger.exception("Weekly UI error | code=%s: %s", code, e)
            await query.edit_message_text(f"❌ خطا در تحلیل هفتگی {code}.", reply_markup=kb_back_main())
        return

    if data == "menu_all":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text("⏳ در حال تحلیل همه ارزها...")
        try:
            plans = await asyncio.wait_for(refresh_all_plans(force_data=False), timeout=120)
        except asyncio.TimeoutError:
            await query.edit_message_text("⏰ تحلیل همه ارزها طول کشید.", reply_markup=kb_back_main())
            return
        if not plans:
            text = f"📋 *نمایش همه پیشنهادات*\n🕒 {shamsi_now()}\n\n😴 فعلاً سیگنال نهایی نداریم."
            await query.edit_message_text(rtl_lines(text), reply_markup=kb_back_main(), parse_mode="Markdown")
            set_interactive_screen(chat_id, [query.message.message_id])
            return
        sorted_plans = sorted(plans.values(), key=lambda p: p.confidence, reverse=True)
        full_text = f"📋 *نمایش پیشنهادات*\n🕒 {shamsi_now()}\n\n" + f"\n\n{BIG_DIVIDER}\n\n".join(
            format_plan_pretty(p, p.symbol, chat_id) for p in sorted_plans
        )
        chunks = split_long_message(full_text)
        new_ids = []
        await query.edit_message_text(chunks[0], parse_mode="Markdown")
        new_ids.append(query.message.message_id)
        for chunk in chunks[1:]:
            m = await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")
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
        ok = sum(1 for c in COIN_CODES if cache.market_status.get(c, {}).get("status") == "SWAP OK")
        no_swap = sum(1 for c in COIN_CODES if cache.market_status.get(c, {}).get("status") == "NO SWAP")
        ticker_error = sum(1 for c in COIN_CODES if cache.market_status.get(c, {}).get("status") == "TICKER ERROR")
        await query.edit_message_text(
            rtl_lines(
                "🛠️ *پنل مدیریت*\n"
                f"{DIVIDER}\n"
                f"🕒 {shamsi_now()}\n"
                f"👥 اعضای فعال: {len(subscribed_chat_ids)}\n"
                f"⚡ سیگنال‌های فعال: {len(last_plans)}\n"
                f"🪙 کل ارزها: {len(COIN_CODES)}\n"
                f"🟢 SWAP OK: {ok}\n"
                f"⚪ NO SWAP: {no_swap}\n"
                f"🟠 TICKER ERROR: {ticker_error}\n"
                f"📊 داده 1h: {len(cache.ohlcv['1h'])}\n"
                f"📊 داده 4h: {len(cache.ohlcv['4h'])}\n"
                f"📊 داده 1d: {len(cache.ohlcv['1d'])}"
            ),
            reply_markup=kb_admin_panel(),
            parse_mode="Markdown",
        )

async def send_report_to_user(app, chat_id, top_plans):
    header = f"📢✨ پیشنهادات لحظه‌ای ✨📢\n🕒 {shamsi_now()}\n{BIG_DIVIDER}\n\n"
    if top_plans:
        body = f"\n\n{DIVIDER}\n\n".join(format_plan_compact(p, p.symbol, chat_id) for p in top_plans)
        footer = "\n\n⚠️ امتیاز اطمینان تخمینی است، نه تضمین."
        keyboard = kb_auto_report(top_plans)
    else:
        body = "😴 فعلاً سیگنال واضحی پیدا نشد."
        footer = "\n🔍 بازار ممکن است در حالت رنج باشد."
        keyboard = kb_back_main()

    try:
        chunks = split_long_message(rtl_lines(header + body + footer))
        for chunk in chunks[:-1]:
            msg = await app.bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")
            await track_auto_message(app, chat_id, msg.message_id)
        msg = await app.bot.send_message(chat_id=chat_id, text=chunks[-1], reply_markup=keyboard, parse_mode="Markdown")
        await track_auto_message(app, chat_id, msg.message_id)
    except Exception as e:
        logger.exception("Auto report failed | chat_id=%s | error=%s", chat_id, e)

async def auto_report_loop(app):
    await asyncio.sleep(10)
    while True:
        cycle_started = time.time()
        try:
            if subscribed_chat_ids:
                await cache.update_prices(force=True)
                await cache.update_ohlcv(force=True)
                plans = await refresh_all_plans(force_data=False)
                top = sorted(plans.values(), key=lambda p: p.confidence, reverse=True)[:TOP_SIGNALS_COUNT]
                await asyncio.gather(*(send_report_to_user(app, chat_id, top) for chat_id in list(subscribed_chat_ids)), return_exceptions=True)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Auto loop failed | error=%s", e)
        elapsed = time.time() - cycle_started
        await asyncio.sleep(max(5, CHECK_INTERVAL_SECONDS - elapsed))

async def start(update, context):
    if not await guard(update):
        return
    chat_id = update.effective_chat.id
    await clear_interactive_screen(context, chat_id)
    msg = await update.message.reply_text("👋 واحد پولی نمایش قیمت‌ها را انتخاب کن:", reply_markup=kb_currency())
    set_interactive_screen(chat_id, [msg.message_id])

async def stop(update, context):
    if not await guard(update):
        return
    subscribed_chat_ids.discard(update.effective_chat.id)
    save_state()
    await update.message.reply_text("❌ اشتراک قطع شد.\nبرای فعال‌سازی دوباره /start را بزن.")

async def menu_command(update, context):
    if not await guard(update):
        return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    subscribed_chat_ids.add(chat_id)
    save_state()
    await clear_interactive_screen(context, chat_id)
    msg = await update.message.reply_text(MAIN_MENU_HEADER, reply_markup=kb_main(user_id), parse_mode="Markdown")
    set_interactive_screen(chat_id, [msg.message_id])

async def status(update, context):
    if not await guard(update):
        return
    ok = sum(1 for c in COIN_CODES if cache.market_status.get(c, {}).get("status") == "SWAP OK")
    no_swap = sum(1 for c in COIN_CODES if cache.market_status.get(c, {}).get("status") == "NO SWAP")
    ticker_error = sum(1 for c in COIN_CODES if cache.market_status.get(c, {}).get("status") == "TICKER ERROR")
    await update.message.reply_text(
        f"🕒 {shamsi_now()}\n"
        f"🪙 کل ارزهای تعریف‌شده: {len(COIN_CODES)}\n"
        f"🟢 SWAP OK: {ok}\n"
        f"⚪ NO SWAP: {no_swap}\n"
        f"🟠 TICKER ERROR: {ticker_error}\n"
        f"📊 داده 1h: {len(cache.ohlcv['1h'])}\n"
        f"📊 داده 4h: {len(cache.ohlcv['4h'])}\n"
        f"📊 داده 1d: {len(cache.ohlcv['1d'])}\n"
        f"⚡ سیگنال‌ها: {len(last_plans)}\n"
        f"👥 اعضا: {len(subscribed_chat_ids)}"
    )

def save_state():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"subscribed_chat_ids": list(subscribed_chat_ids), "user_currency": user_currency}, f, ensure_ascii=False)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        logger.warning("State save failed: %s", e)

def load_state():
    global subscribed_chat_ids, user_currency
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        subscribed_chat_ids = {int(x) for x in data.get("subscribed_chat_ids", [])}
        user_currency = {int(k): v for k, v in data.get("user_currency", {}).items()}
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
    logger.info("Signal Bot V8 (Binance) started")

def main():
    if not BOT_TOKEN:
        raise RuntimeError("❌ BOT_TOKEN در .env تنظیم نشده است.")
    if not ALLOWED_USER_IDS:
        logger.warning("⚠️ ALLOWED_USER_IDS تنظیم نشده؛ ربات برای همه باز است.")
    load_state()
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stop", stop))
    app.add_handler(CommandHandler("menu", menu_command))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
