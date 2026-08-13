"""
Telegram Signal Bot V28 - KuCoin Futures (Final Text-Based)
- صرافی تحلیل: KuCoin Futures
- حذف کامل Open Interest و Long/Short Ratio
- حذف نمودارهای عکس و جایگزینی با تحلیل متنی کامل
- قیمت‌گیری چندمنبعی: بیت‌پین، ولکس، کوکوین، MEXC
- منوی مرتب، راهنما، علاقه‌مندی‌ها، حالت‌های معاملاتی
- ارسال خودکار رویدادمحور
- دکمه‌های بازگشت صحیح در همه بخش‌ها
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Set, Tuple

import ccxt
import jdatetime
import numpy as np
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
WHALE_ALERT_API_KEY = os.getenv("WHALE_ALERT_API_KEY", "")

COIN_ICONS = {
    "BTC": "₿", "ETH": "Ξ", "BNB": "🔶", "SOL": "◎", "XRP": "✕",
    "DOGE": "🐕", "ADA": "🔷", "AVAX": "🔺", "DOT": "⚪", "LINK": "🔗",
    "LTC": "Ł", "BCH": "🟢", "ETC": "⟠", "XLM": "✨", "ATOM": "⚛️",
    "FIL": "📁", "UNI": "🦄", "AAVE": "👻", "TRX": "⚡", "NEAR": "Ⓝ",
    "ARB": "🔵", "APT": "🅰️", "SUI": "💧", "PEPE": "🐸", "WIF": "🧢",
    "BONK": "🐕", "FLOKI": "🐕‍🦺", "SHIB": "🦴", "TIA": "🛰️", "SEI": "🌊",
    "INJ": "💉", "KAS": "🐍", "OP": "🔴", "RUNE": "🪙", "JUP": "🪐",
    "PYTH": "🔮", "STX": "📚", "GRT": "📊", "SAND": "⏳", "MANA": "🌐",
    "GALA": "🎮", "APE": "🦧", "MINA": "🌐", "LUNC": "🟤", "COMP": "💠",
    "AXL": "🌉", "BLUR": "👁️", "AR": "🗂️", "FLOW": "🌊", "EOS": "⚙️",
    "XTZ": "🪙", "THETA": "🌀", "CHZ": "🌶️", "ZEC": "🛡️", "DASH": "⚡",
    "SUSHI": "🍣", "CRV": "🥄", "1INCH": "1️⃣", "ENJ": "🎮", "GMT": "👟",
    "IMX": "🛡️", "LDO": "🌊", "DYDX": "📉", "API3": "🔌", "SNX": "🧪",
    "VET": "🌿", "CAKE": "🥞", "PENDLE": "📐", "TAO": "🧠", "RENDER": "🖥️",
    "POL": "🟣", "FTM": "🔥", "MAGIC": "🪄", "CFX": "🌲", "WLD": "👁️",
    "ENS": "🏷️", "ONE": "🎐", "ZRX": "0️⃣", "AXS": "🐚", "HBAR": "Ⓗ",
    "CRO": "💠", "HMSTR": "🐹", "NOT": "💎", "DOGS": "🐾", "BABYDOGE": "🐶",
    "PUMP": "🚀", "S": "💨", "DEXE": "🗳️", "SKY": "☁️", "HYPE": "🌊",
    "ONDO": "🏦", "XAUT": "🥇", "ENA": "🌐", "STORJ": "💾", "SLP": "🍯"
}
COIN_CODES = list(COIN_ICONS.keys())

TIMEFRAMES = ("5m", "15m", "1h", "4h", "1d")
TOP_SIGNALS_COUNT = 5
TELEGRAM_MSG_LIMIT = 3500
IRT_RATE_TTL_SECONDS = 300
COINS_GRID_COLUMNS = 4
AUTO_KEEP_LAST_N = 3
TRAILING_CHECK_SECONDS = 5 * 60
FEAR_GREED_TTL = 3600
EVENTS_CHECK_SECONDS = 6 * 3600
WHALE_CHECK_SECONDS = 30 * 60
WHALE_MIN_AMOUNT_BTC = 1000

WEIGHT_TREND = 25
WEIGHT_MOMENTUM = 25
WEIGHT_VOLUME = 15
WEIGHT_VOLATILITY = 15
WEIGHT_HTF = 20

OHLCV_TTL_SECONDS = 90
FULL_REFRESH_TTL_SECONDS = 300
FUNDING_TTL_SECONDS = 120
MAX_OHLCV_CONCURRENCY = 4
MAX_SIGNAL_CONCURRENCY = 3
MAX_PRICE_CONCURRENCY = 3
RLM = "\u200f"

DATA_DIR = os.getenv("DATA_DIR", "/data")
STATE_FILE = os.path.join(DATA_DIR, "state.json")

DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
BIG_DIVIDER = "═══════════════"
MENU_PROMPT = "👇 یکی از گزینه‌ها را انتخاب کن:"

# صرافی اصلی تحلیل: KuCoin Futures
exchange = ccxt.kucoinfutures({
    "enableRateLimit": True,
    "options": {
        "defaultType": "swap",
        "adjustForTimeDifference": True,
    },
})

# صرافی کمکی برای قیمت
exchange_mexc = ccxt.mexc({
    "enableRateLimit": True,
    "options": {
        "defaultType": "swap",
        "adjustForTimeDifference": True,
    },
})

last_plans = {}
subscribed_chat_ids = set()
user_currency = {}
user_trading_mode = {}
user_favorites = {}
auto_message_history = {}
overlay_messages = {}
interactive_screen_messages = {}
_irt_rate_cache = {"value": None, "ts": 0.0, "source": None}
active_signals = {}
START_TIME = time.time()
TOTAL_SIGNALS_GENERATED = 0
LAST_REPORT_TIME = None

signal_history: List[Dict] = []
fear_greed_cache = {"value": None, "ts": 0.0, "classification": ""}
upcoming_events_cache = {"events": [], "ts": 0.0}
whale_alert_cache = {"last_id": None, "ts": 0.0}

last_check_time = {}
last_sent_signals = {}
price_sources = {}  # code -> str: 'B', 'W', 'K', 'M'

MODE_CONFIGS = {
    "fast": {
        "label": "⚡ سریع",
        "main_tf": "5m",
        "confirm_tfs": ["15m", "1h"],
        "entry_ladder_atr": [0.0, 0.2, 0.4],
        "tp_multipliers": [0.4, 0.8, 1.2],
        "sl_atr_mult": 0.8,
        "max_leverage": 10,
        "min_rr": 1.0,
        "adx_min": 12,
        "check_interval": 5 * 60,
    },
    "semi_fast": {
        "label": "🔥 نیمه‌سریع",
        "main_tf": "15m",
        "confirm_tfs": ["1h", "4h"],
        "entry_ladder_atr": [0.0, 0.3, 0.6],
        "tp_multipliers": [0.6, 1.2, 1.8],
        "sl_atr_mult": 1.0,
        "max_leverage": 7,
        "min_rr": 1.1,
        "adx_min": 13,
        "check_interval": 10 * 60,
    },
    "standard": {
        "label": "📊 استاندارد",
        "main_tf": "1h",
        "confirm_tfs": ["4h", "1d"],
        "entry_ladder_atr": [0.0, 0.4, 0.8],
        "tp_multipliers": [0.8, 1.5, 2.5],
        "sl_atr_mult": 1.2,
        "max_leverage": 5,
        "min_rr": 1.2,
        "adx_min": 15,
        "check_interval": 30 * 60,
    },
    "conservative": {
        "label": "🛡️ محافظه‌کار",
        "main_tf": "4h",
        "confirm_tfs": ["1d", "1d"],
        "entry_ladder_atr": [0.0, 0.6, 1.2],
        "tp_multipliers": [1.5, 2.5, 4.0],
        "sl_atr_mult": 2.0,
        "max_leverage": 3,
        "min_rr": 1.5,
        "adx_min": 20,
        "check_interval": 60 * 60,
    },
}

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
    liquidation_price: float = 0.0
    scores: dict = field(default_factory=dict)
    reasons: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    support: float = 0.0
    resistance: float = 0.0
    breakout_up: bool = False
    breakout_down: bool = False
    bullish_div: bool = False
    bearish_div: bool = False
    macd_bullish_div: bool = False
    macd_bearish_div: bool = False
    entry_price: float = 0.0
    sl_price: float = 0.0
    tp_prices: list = field(default_factory=list)
    timestamp: float = 0.0
    status: str = "open"
    mode: str = "standard"

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
        self._sem = asyncio.Semaphore(MAX_OHLCV_CONCURRENCY)
        self._price_sem = asyncio.Semaphore(MAX_PRICE_CONCURRENCY)
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
                self.market_status[code] = {"status": "NO SWAP", "symbol": None, "error": None}
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
                    if market.get("active") is False:
                        continue
                    candidates.append((symbol, market))
                if not candidates:
                    continue
                candidates.sort(key=lambda x: x[0])
                symbol, market = candidates[0]
                selected[code] = symbol
                self.market_meta[code] = market
                self.market_status[code] = {"status": "SWAP OK", "symbol": symbol, "error": None}
            self.exchange_symbols = selected
            self.valid_codes = list(selected.keys())
            logger.info("KuCoin swap markets: %s/%s selected", len(self.valid_codes), len(COIN_CODES))
        except Exception as e:
            logger.exception("load_markets failed: %s", e)

    def symbol_for_code(self, code) -> Optional[str]:
        return self.exchange_symbols.get(code)

    @staticmethod
    def _to_dataframe(raw):
        if raw is None:
            return None
        if isinstance(raw, pd.DataFrame):
            df = raw.copy()
        else:
            if not isinstance(raw, (list, tuple)) or not raw:
                return None
            df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
        required = ["timestamp", "open", "high", "low", "close", "volume"]
        if any(col not in df.columns for col in required):
            return None
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        if pd.api.types.is_numeric_dtype(df["timestamp"]):
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True, errors="coerce")
        else:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=required).drop_duplicates(subset=["timestamp"]).sort_values("timestamp").reset_index(drop=True)
        return df if not df.empty else None

    @staticmethod
    def _drop_forming_candle(df):
        if df is None or len(df) < 2:
            return df
        now = pd.Timestamp.now(tz="UTC")
        latest = df["timestamp"].iloc[-1]
        timeframe_delta = df["timestamp"].iloc[-1] - df["timestamp"].iloc[-2] if len(df) >= 2 else None
        if timeframe_delta and timeframe_delta > pd.Timedelta(0):
            if latest + timeframe_delta > now:
                return df.iloc[:-1].copy().reset_index(drop=True)
        return df.copy().reset_index(drop=True)

    async def update_prices(self, force=False):
        if not self.exchange_symbols:
            self._load_markets()
        now = time.time()
        if not force and self.prices and self.last_price_update and now - self.last_price_update < 60:
            return self.prices

        new_prices = {}
        price_sources.clear()

        # 1) بیت‌پین
        try:
            bitpin_prices = await asyncio.to_thread(self._get_bitpin_prices)
            for code, price in bitpin_prices.items():
                new_prices[code] = price
                price_sources[code] = "B"
        except Exception as e:
            logger.warning("Bitpin fetch failed: %s", e)

        # 2) ولکس
        try:
            wallex_prices = await asyncio.to_thread(self._get_wallex_prices)
            for code, price in wallex_prices.items():
                if code not in new_prices and price > 0:
                    new_prices[code] = price
                    price_sources[code] = "W"
        except Exception as e:
            logger.warning("Wallex fetch failed: %s", e)

        # 3) کوکوین
        try:
            kucoin_prices = await asyncio.to_thread(self._get_kucoin_prices)
            for code, price in kucoin_prices.items():
                if code not in new_prices and price > 0:
                    new_prices[code] = price
                    price_sources[code] = "K"
        except Exception as e:
            logger.warning("KuCoin fetch failed: %s", e)

        # 4) MEXC
        try:
            mexc_prices = await asyncio.to_thread(self._get_mexc_prices)
            for code, price in mexc_prices.items():
                if code not in new_prices and price > 0:
                    new_prices[code] = price
                    price_sources[code] = "M"
        except Exception as e:
            logger.warning("MEXC fetch failed: %s", e)

        # fallback به آخرین کندل کوکوین
        for code in COIN_CODES:
            if code not in new_prices:
                df = self.ohlcv.get("1h", {}).get(code)
                if df is not None and not df.empty:
                    new_prices[code] = float(df["close"].iloc[-1])
                    price_sources[code] = "K"

        self.prices = new_prices
        self.last_price_update = time.time()
        logger.info("Live prices loaded: %s/%s", len(self.prices), len(COIN_CODES))
        return self.prices

    def _get_bitpin_prices(self):
        # بیت‌پین API عمومی – پیاده‌سازی فرضی
        # این بخش باید بر اساس مستندات رسمی بیت‌پین تکمیل شود
        # چون API بیت‌پین در دسترس نیست، دیکشنری خالی برمی‌گردانیم
        return {}

    def _get_wallex_prices(self):
        r = requests.get("https://api.wallex.ir/v1/markets", timeout=8)
        r.raise_for_status()
        data = r.json()["result"]["symbols"]
        mapping = {
            "BTC": "BTCTMN", "ETH": "ETHTMN", "USDT": "USDTTMN",
            "DOGE": "DOGETMN", "ADA": "ADATMN", "SHIB": "SHIBTMN",
            "XRP": "XRPTMN", "SOL": "SOLTMN", "LTC": "LTCTMN",
            "BCH": "BCHTMN", "DOT": "DOTTMN", "LINK": "LINKTMN",
        }
        prices = {}
        usdt_rate = get_irt_rate()
        if not usdt_rate:
            return prices
        for code, symbol in mapping.items():
            if symbol in data:
                last = float(data[symbol]["stats"].get("lastPrice", 0))
                if last > 0:
                    prices[code] = last / usdt_rate
        return prices

    def _get_kucoin_prices(self):
        try:
            tickers = exchange.fetch_tickers(list(self.exchange_symbols.values()))
            prices = {}
            for code, symbol in self.exchange_symbols.items():
                ticker = tickers.get(symbol)
                if ticker:
                    price = ticker.get("last") or ticker.get("close") or ticker.get("bid") or ticker.get("ask")
                    if price:
                        prices[code] = float(price)
            return prices
        except Exception as e:
            logger.warning("KuCoin tickers failed: %s", e)
            return {}

    def _get_mexc_prices(self):
        try:
            symbols = [code + "/USDT:USDT" for code in COIN_CODES]
            tickers = exchange_mexc.fetch_tickers(symbols)
            prices = {}
            for code in COIN_CODES:
                sym = code + "/USDT:USDT"
                ticker = tickers.get(sym)
                if ticker:
                    price = ticker.get("last") or ticker.get("close") or ticker.get("bid") or ticker.get("ask")
                    if price:
                        prices[code] = float(price)
            return prices
        except Exception as e:
            logger.warning("MEXC tickers failed: %s", e)
            return {}

    async def _fetch_ohlcv_symbol(self, code, timeframe, limit=1000):
        symbol = self.symbol_for_code(code)
        if not symbol:
            return None
        async with self._sem:
            for attempt in range(3):
                try:
                    raw = await asyncio.to_thread(exchange.fetch_ohlcv, symbol, timeframe, None, limit)
                    df = self._to_dataframe(raw)
                    if df is None or len(df) < 10:
                        return None
                    closed = self._drop_forming_candle(df)
                    if closed is None or len(closed) < 5:
                        return None
                    return closed
                except Exception as e:
                    logger.warning("OHLCV failed | code=%s | tf=%s | attempt=%s | error=%s", code, timeframe, attempt, e)
                    await asyncio.sleep(1)
            return None

    async def ensure_symbol_data(self, code, timeframes=None, force=False):
        if timeframes is None:
            timeframes = TIMEFRAMES
        missing = [tf for tf in timeframes if force or code not in self.ohlcv.get(tf, {}) or time.time() - self.ohlcv_updated_at.get(tf, {}).get(code, 0) > OHLCV_TTL_SECONDS]
        if not missing:
            return True
        async with self._symbol_lock(code):
            missing = [tf for tf in timeframes if force or code not in self.ohlcv.get(tf, {}) or time.time() - self.ohlcv_updated_at.get(tf, {}).get(code, 0) > OHLCV_TTL_SECONDS]
            for tf in missing:
                df = await self._fetch_ohlcv_symbol(code, tf)
                if df is not None:
                    self.ohlcv.setdefault(tf, {})[code] = df
                    self.ohlcv_updated_at.setdefault(tf, {})[code] = time.time()
            return all(code in self.ohlcv.get(tf, {}) for tf in timeframes)

    async def update_ohlcv(self, force=False, codes=None):
        async with self._update_lock:
            now = time.time()
            if not force and self.last_full_ohlcv_update and now - self.last_full_ohlcv_update < FULL_REFRESH_TTL_SECONDS:
                return
            if not self.valid_codes:
                self._load_markets()
            if not self.valid_codes:
                return
            target_codes = list(codes or self.valid_codes)
            await asyncio.gather(*(self.ensure_symbol_data(c, TIMEFRAMES, force=force) for c in target_codes))
            self.last_full_ohlcv_update = time.time()
            logger.info("OHLCV refresh complete: %s", {tf: len(self.ohlcv.get(tf, {})) for tf in TIMEFRAMES})

    async def get_funding_rate(self, code):
        symbol = self.symbol_for_code(code)
        if not symbol:
            return 0.0
        cached = self._funding_cache.get(code)
        if cached is not None and time.time() - cached["ts"] < FUNDING_TTL_SECONDS:
            return cached["value"]
        async with self._funding_lock:
            cached = self._funding_cache.get(code)
            if cached is not None and time.time() - cached["ts"] < FUNDING_TTL_SECONDS:
                return cached["value"]
            try:
                funding = await asyncio.to_thread(exchange.fetch_funding_rate, symbol)
                value = float(funding.get("fundingRate") or 0) * 100
                self._funding_cache[code] = {"value": value, "ts": time.time()}
                return value
            except Exception as e:
                logger.debug("Funding failed | code=%s | error=%s", code, e)
                if cached is not None:
                    return cached["value"]
                return 0.0

    async def get_indicators(self, code, mode="standard"):
        config = MODE_CONFIGS.get(mode, MODE_CONFIGS["standard"])
        main_tf = config["main_tf"]
        confirm_tfs = config["confirm_tfs"]
        needed = [main_tf] + confirm_tfs
        ok = await self.ensure_symbol_data(code, needed)
        if not ok:
            return None
        df = self.ohlcv.get(main_tf, {}).get(code)
        if df is None or len(df) < 210:
            await self.ensure_symbol_data(code, [main_tf], force=True)
            df = self.ohlcv.get(main_tf, {}).get(code)
            if df is None or len(df) < 210:
                return None
        confirm_dfs = []
        for tf in confirm_tfs:
            cdf = self.ohlcv.get(tf, {}).get(code)
            if cdf is not None and len(cdf) >= 200:
                confirm_dfs.append(cdf)
            else:
                confirm_dfs.append(None)

        try:
            close = df["close"]
            ema20 = EMAIndicator(close, window=20).ema_indicator()
            ema50 = EMAIndicator(close, window=50).ema_indicator()
            ema200 = EMAIndicator(close, window=200).ema_indicator()
            rsi = RSIIndicator(close, window=14).rsi()
            stoch = StochRSIIndicator(close, window=14, smooth1=3, smooth2=3)
            stoch_k = stoch.stochrsi_k() * 100
            macd = MACD(close, window_slow=26, window_fast=12, window_sign=9)
            macd_hist = macd.macd_diff()
            macd_line = macd.macd()
            macd_signal = macd.macd_signal()
            roc = ROCIndicator(close, window=12).roc()
            cci = CCIIndicator(df["high"], df["low"], close, window=20).cci()
            williams = WilliamsRIndicator(df["high"], df["low"], close, lbp=14).williams_r()
            adx_ind = ADXIndicator(df["high"], df["low"], close, window=14)
            adx = adx_ind.adx()
            plus_di = adx_ind.adx_pos()
            minus_di = adx_ind.adx_neg()
            atr = AverageTrueRange(df["high"], df["low"], close, window=14).average_true_range()
            bb = BollingerBands(close, window=20, window_dev=2)
            bb_percent = bb.bollinger_pband()
            bb_width = bb.bollinger_wband()
            volume_ratio = df["volume"] / df["volume"].rolling(20).mean()
            volume_ma20 = df["volume"].rolling(20).mean()
            volume_ma50 = df["volume"].rolling(50).mean()
            vwap = VolumeWeightedAveragePrice(high=df["high"], low=df["low"], close=close, volume=df["volume"], window=20).volume_weighted_average_price()

            price = float(close.iloc[-1])
            price_prev = float(close.iloc[-2])
            atr_value = float(atr.iloc[-1])
            atr_pct = (atr_value / price * 100) if price > 0 else 0
            ema20_value = float(ema20.iloc[-1])
            ema50_value = float(ema50.iloc[-1])
            ema200_value = float(ema200.iloc[-1])
            price_ema200_pct = ((price - ema200_value) / ema200_value * 100)
            price_ema50_pct = ((price - ema50_value) / ema50_value * 100)

            ema20_prev = float(ema20.iloc[-2]) if len(ema20) >= 2 else ema20_value
            ema50_prev = float(ema50.iloc[-2]) if len(ema50) >= 2 else ema50_value
            bullish_cross = (ema20_prev <= ema50_prev and ema20_value > ema50_value)
            bearish_cross = (ema20_prev >= ema50_prev and ema20_value < ema50_value)

            rsi_prev = float(rsi.iloc[-2]) if len(rsi) >= 2 else float(rsi.iloc[-1])
            macd_hist_prev = float(macd_hist.iloc[-2]) if len(macd_hist) >= 2 else float(macd_hist.iloc[-1])

            vr = float(volume_ratio.iloc[-1])
            volume_spike = vr >= 1.5
            volume_trend_up = (float(volume_ma20.iloc[-1]) > float(volume_ma50.iloc[-1]))

            confirm_up = 0
            confirm_down = 0
            for cdf in confirm_dfs:
                if cdf is not None:
                    c_close = cdf["close"]
                    c_ema200 = EMAIndicator(c_close, window=200).ema_indicator()
                    c_ema200_val = c_ema200.iloc[-1]
                    if pd.notna(c_ema200_val):
                        if c_close.iloc[-1] > c_ema200_val:
                            confirm_up += 1
                        else:
                            confirm_down += 1

            support = float(df["low"].iloc[-20:].min())
            resistance = float(df["high"].iloc[-20:].max())
            breakout_up = price > resistance * 1.001
            breakout_down = price < support * 0.999

            rsi_bullish_div = (price < price_prev and rsi.iloc[-1] > rsi_prev)
            rsi_bearish_div = (price > price_prev and rsi.iloc[-1] < rsi_prev)
            macd_bullish_div = (price < price_prev and macd_hist.iloc[-1] > macd_hist_prev)
            macd_bearish_div = (price > price_prev and macd_hist.iloc[-1] < macd_hist_prev)

            values = {
                "price": price,
                "price_prev": price_prev,
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
                "rsi_prev": rsi_prev,
                "stoch_k": float(stoch_k.iloc[-1]),
                "macd": float(macd_line.iloc[-1]),
                "macd_signal": float(macd_signal.iloc[-1]),
                "macd_hist": float(macd_hist.iloc[-1]),
                "macd_hist_prev": macd_hist_prev,
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
                "confirm_up_count": confirm_up,
                "confirm_down_count": confirm_down,
                "higher_tf_trend_up": confirm_up >= len(confirm_dfs) if confirm_dfs else None,
                "higher_tf_trend_down": confirm_down >= len(confirm_dfs) if confirm_dfs else None,
                "trend_label": "صعودی 📈" if price > ema200_value else "نزولی 📉",
                "is_trending": bool(adx.iloc[-1] >= config["adx_min"]),
                "support": support,
                "resistance": resistance,
                "breakout_up": breakout_up,
                "breakout_down": breakout_down,
                "bullish_div": rsi_bullish_div,
                "bearish_div": rsi_bearish_div,
                "macd_bullish_div": macd_bullish_div,
                "macd_bearish_div": macd_bearish_div,
            }
            if any(pd.isna(v) for v in values.values() if isinstance(v, (int, float))):
                return None
            return values
        except Exception as e:
            logger.exception("Indicator error | code=%s | mode=%s | error=%s", code, mode, e)
            return None

    async def get_weekly_data(self, code):
        ok = await self.ensure_symbol_data(code, ("1d",))
        if not ok:
            await self.ensure_symbol_data(code, ("1d",), force=True)
        df = self.ohlcv.get("1d", {}).get(code)
        if df is None or df.empty:
            return None
        end = df["timestamp"].iloc[-1]
        start = end - pd.Timedelta(days=7)
        week = df[df["timestamp"] >= start].copy()
        if len(week) < 2:
            week = df.tail(min(8, len(df))).copy()
        return week if len(week) >= 2 else None

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
            return float(r.json()["stats"]["usdt-rls"]["latest"]) / 10
        except Exception:
            time.sleep(1)
    raise RuntimeError("Nobitex failed")

def fetch_irt_rate_wallex():
    r = requests.get("https://api.wallex.ir/v1/markets", timeout=8)
    r.raise_for_status()
    return float(r.json()["result"]["symbols"]["USDTTMN"]["stats"]["lastPrice"])

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

# ---------- Fear & Greed ----------
def fetch_fear_greed_index():
    try:
        r = requests.get("https://api.alternative.me/fng/", timeout=10)
        r.raise_for_status()
        data = r.json()["data"][0]
        return int(data["value"]), data.get("value_classification", "")
    except Exception as e:
        logger.warning("Fear&Greed fetch failed: %s", e)
        return None, None

async def get_fear_greed():
    now = time.time()
    if fear_greed_cache["value"] is not None and now - fear_greed_cache["ts"] < FEAR_GREED_TTL:
        return fear_greed_cache["value"], fear_greed_cache["classification"]
    value, classification = fetch_fear_greed_index()
    if value is not None:
        fear_greed_cache.update(value=value, classification=classification, ts=now)
    return value, classification

# ---------- Events ----------
def fetch_upcoming_events():
    try:
        r = requests.get("https://api.coingecko.com/api/v3/events?upcoming=true", timeout=10)
        r.raise_for_status()
        data = r.json().get("data", [])
        events = []
        for ev in data:
            name = ev.get("title") or ev.get("name", "رویداد")
            date_str = ev.get("date", "")
            if not date_str:
                continue
            try:
                event_time = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except:
                continue
            events.append({"name": name, "time": event_time})
        return events
    except Exception as e:
        logger.warning("Events fetch failed: %s", e)
        return []

async def get_upcoming_events(force=False):
    now = time.time()
    if not force and upcoming_events_cache["events"] and now - upcoming_events_cache["ts"] < EVENTS_CHECK_SECONDS:
        return upcoming_events_cache["events"]
    events = fetch_upcoming_events()
    if events:
        upcoming_events_cache.update(events=events, ts=now)
    return events

async def check_and_notify_events(app):
    events = await get_upcoming_events(force=True)
    now_utc = datetime.now(tz=TEHRAN_TZ) if TEHRAN_TZ else datetime.now()
    upcoming = []
    for ev in events:
        event_time = ev["time"]
        if event_time.tzinfo is None:
            event_time = event_time.replace(tzinfo=TEHRAN_TZ)
        delta = event_time - now_utc
        if timedelta(0) <= delta <= timedelta(hours=24):
            upcoming.append(ev)
    if upcoming:
        for chat_id in subscribed_chat_ids:
            text = "📅 *رویدادهای مهم کریپتو در ۲۴ ساعت آینده:*\n" + DIVIDER + "\n"
            for ev in upcoming:
                text += f"• {ev['name']} — {shamsi_date(ev['time'])} {ev['time'].strftime('%H:%M')}\n"
            try:
                await app.bot.send_message(chat_id=chat_id, text=rtl_lines(text), parse_mode="Markdown")
            except Exception as e:
                logger.warning("Event notify failed: %s", e)

# ---------- Whale Alerts ----------
def fetch_whale_alerts():
    try:
        if WHALE_ALERT_API_KEY:
            url = f"https://api.whale-alert.io/v1/transactions?api_key={WHALE_ALERT_API_KEY}&min_value={WHALE_MIN_AMOUNT_BTC * 1000000}&limit=10"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.json().get("transactions", [])
            alerts = []
            for tx in data:
                alerts.append({"amount_btc": float(tx.get("amount", 0)), "symbol": tx.get("symbol", "BTC"), "timestamp": time.time()})
            return alerts
        else:
            url = "https://blockchain.info/unconfirmed-transactions?format=json"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            txs = r.json().get("txs", [])
            alerts = []
            for tx in txs:
                total_out = sum(out.get("value", 0) for out in tx.get("out", [])) / 1e8
                if total_out >= WHALE_MIN_AMOUNT_BTC:
                    alerts.append({"amount_btc": total_out, "symbol": "BTC", "timestamp": time.time()})
            return alerts[:5]
    except Exception as e:
        logger.warning("Whale alert fetch failed: %s", e)
        return []

async def whale_monitor_loop(app):
    await asyncio.sleep(60)
    while True:
        try:
            if subscribed_chat_ids:
                alerts = fetch_whale_alerts()
                if alerts:
                    for chat_id in subscribed_chat_ids:
                        text = "🐋 *هشدار حرکت نهنگ‌ها*\n" + DIVIDER + "\n"
                        for alert in alerts[:5]:
                            text += f"• {alert['amount_btc']:.0f} {alert['symbol']} جابه‌جا شد\n"
                        try:
                            await app.bot.send_message(chat_id=chat_id, text=rtl_lines(text), parse_mode="Markdown")
                        except Exception as e:
                            logger.warning("Whale notify failed: %s", e)
        except Exception as e:
            logger.exception("Whale monitor error: %s", e)
        await asyncio.sleep(WHALE_CHECK_SECONDS)

# ---------- Advanced Reporting ----------
def compute_advanced_stats(signal_history, mode=None):
    filtered = [r for r in signal_history if mode is None or r.get("mode") == mode]
    if not filtered:
        return {
            "sharpe": 0, "max_drawdown": 0, "expectancy": 0,
            "risk_of_ruin": 0, "total_trades": 0, "win_rate": 0,
            "profit_factor": 0, "avg_confidence": 0,
            "wins": 0, "losses": 0
        }
    returns = []
    wins = 0
    losses = 0
    for rec in filtered:
        if rec["status"] == "tp3_hit":
            returns.append(3 * (rec["tp_prices"][2] - rec["entry_price"]))
            wins += 1
        elif rec["status"] == "tp2_hit":
            returns.append(2 * (rec["tp_prices"][1] - rec["entry_price"]))
            wins += 1
        elif rec["status"] == "tp1_hit":
            returns.append(1 * (rec["tp_prices"][0] - rec["entry_price"]))
            wins += 1
        elif rec["status"] == "sl_hit":
            returns.append(rec["entry_price"] - rec["sl_price"])
            losses += 1
    if not returns:
        return {
            "sharpe": 0, "max_drawdown": 0, "expectancy": 0,
            "risk_of_ruin": 0, "total_trades": 0, "win_rate": 0,
            "profit_factor": 0, "avg_confidence": 0,
            "wins": 0, "losses": 0
        }
    returns = np.array(returns)
    win_rate = wins / len(returns) * 100
    avg_return = np.mean(returns)
    std_return = np.std(returns) if len(returns) > 1 else 1e-9
    sharpe = (avg_return / std_return) * np.sqrt(365) if std_return != 0 else 0
    cumulative = np.cumsum(returns)
    max_dd = 0
    peak = cumulative[0]
    for val in cumulative:
        if val > peak:
            peak = val
        dd = peak - val
        if dd > max_dd:
            max_dd = dd
    expectancy = avg_return
    risk_of_ruin = (1 - (wins / len(returns))) ** 10 * 100
    profit_factor = (sum(r for r in returns if r > 0) / abs(sum(r for r in returns if r <= 0))) if losses else 999
    avg_confidence = np.mean([rec["confidence"] for rec in filtered]) if filtered else 0
    return {
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "expectancy": expectancy,
        "risk_of_ruin": risk_of_ruin,
        "total_trades": len(returns),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "avg_confidence": avg_confidence,
        "wins": wins,
        "losses": losses,
    }

# ---------- Scoring ----------
def category_scores(direction, ind, mode):
    config = MODE_CONFIGS[mode]
    long_side = direction == "LONG"
    trend = 0
    if long_side:
        if ind["price_above_ema200"]: trend += 8
        if ind["ema20_above_ema50"]: trend += 7
        if ind["price_above_ema50"]: trend += 4
        if ind["ema20_bullish_cross"]: trend += 3
        if ind["adx"] >= 25: trend += 3
    else:
        if not ind["price_above_ema200"]: trend += 8
        if not ind["ema20_above_ema50"]: trend += 7
        if not ind["price_above_ema50"]: trend += 4
        if ind["ema20_bearish_cross"]: trend += 3
        if ind["adx"] >= 25: trend += 3
    trend = min(trend, 25)

    momentum = 0
    macd_ok = ind["macd_hist"] > 0 if long_side else ind["macd_hist"] < 0
    di_ok = ind["plus_di"] > ind["minus_di"] if long_side else ind["minus_di"] > ind["plus_di"]
    roc_ok = ind["roc"] > 0 if long_side else ind["roc"] < 0
    cci_ok = ind["cci"] > 0 if long_side else ind["cci"] < 0
    williams_ok = ind["williams_r"] > -80 if long_side else ind["williams_r"] < -20
    if macd_ok: momentum += 7
    if di_ok: momentum += 5
    if roc_ok: momentum += 5
    if cci_ok: momentum += 4
    if williams_ok: momentum += 4
    if long_side and (ind["bullish_div"] or ind["macd_bullish_div"]):
        momentum += 3
    elif not long_side and (ind["bearish_div"] or ind["macd_bearish_div"]):
        momentum += 3
    momentum = min(momentum, 25)

    volume = 0
    if ind["volume_ratio"] >= 1.5: volume += 8
    elif ind["volume_ratio"] >= 1.0: volume += 5
    elif ind["volume_ratio"] >= 0.7: volume += 2
    if ind["volume_trend_up"]: volume += 4
    if ind["volume_spike"]: volume += 3
    volume = min(volume, 15)

    volatility = 0
    if 0.5 <= ind["atr_pct"] <= 5: volatility += 6
    elif ind["atr_pct"] <= 8: volatility += 4
    else: volatility += 1
    distance = abs(ind["price_ema200_pct"])
    if distance <= 5: volatility += 4
    elif distance <= 10: volatility += 2
    if 1 <= ind["bb_width"] <= 12: volatility += 5
    elif ind["bb_width"] <= 20: volatility += 3
    volatility = min(volatility, 15)

    htf = 0
    total_confirms = len(config["confirm_tfs"])
    if total_confirms > 0:
        if long_side:
            if ind["confirm_up_count"] == total_confirms:
                htf += 15
            elif ind["confirm_up_count"] >= 1:
                htf += 5
        else:
            if ind["confirm_down_count"] == total_confirms:
                htf += 15
            elif ind["confirm_down_count"] >= 1:
                htf += 5
    vwap_ok = ind["price_above_vwap"] if long_side else not ind["price_above_vwap"]
    if vwap_ok: htf += 5
    htf = min(htf, 20)

    return {"trend": trend, "momentum": momentum, "volume": volume, "volatility": volatility, "htf": htf}

def decide_direction(ind, mode):
    config = MODE_CONFIGS[mode]
    long_scores = category_scores("LONG", ind, mode)
    short_scores = category_scores("SHORT", ind, mode)
    long_score = sum(long_scores.values())
    short_score = sum(short_scores.values())
    long_base = ind["macd_hist"] > 0 and ind["plus_di"] >= ind["minus_di"]
    short_base = ind["macd_hist"] < 0 and ind["minus_di"] >= ind["plus_di"]

    adx_ok = ind["adx"] >= config["adx_min"]
    if not adx_ok:
        return None, max(long_score, short_score), None

    if long_base and long_score >= MIN_SIGNAL_CONFIDENCE and long_score >= short_score + MIN_DIRECTION_GAP:
        return "LONG", long_score, long_scores
    if short_base and short_score >= MIN_SIGNAL_CONFIDENCE and short_score >= long_score + MIN_DIRECTION_GAP:
        return "SHORT", short_score, short_scores
    return None, max(long_score, short_score), None

def signal_reasons(direction, ind, mode):
    reasons, warnings = [], []
    if direction == "LONG":
        if ind["price_above_ema200"]: reasons.append("قیمت بالای EMA200")
        if ind["ema20_above_ema50"]: reasons.append("EMA20 بالای EMA50")
        if ind["ema20_bullish_cross"]: reasons.append("کراس صعودی EMA20/EMA50")
        if ind["macd_hist"] > 0: reasons.append("MACD مثبت")
        if ind["plus_di"] > ind["minus_di"]: reasons.append("+DI > -DI")
        if ind["adx"] >= 25: reasons.append(f"ADX = {ind['adx']:.1f}")
        if ind["volume_ratio"] >= 1.5: reasons.append(f"حجم غیرعادی = {ind['volume_ratio']:.1f}×")
        elif ind["volume_ratio"] >= 1: reasons.append(f"حجم = {ind['volume_ratio']:.1f}× میانگین")
        if ind["higher_tf_trend_up"]: reasons.append("تأیید تایم‌فریم بالاتر")
        if ind["price_above_vwap"]: reasons.append("قیمت بالای VWAP")
        if ind["roc"] > 0: reasons.append("ROC مثبت")
        if ind["cci"] > 0: reasons.append("CCI مثبت")
        if ind["breakout_up"]: reasons.append("شکست مقاومت (Breakout)")
        if ind["bullish_div"]: reasons.append("واگرایی مثبت RSI")
        if ind["macd_bullish_div"]: reasons.append("واگرایی مثبت MACD")
        if ind["rsi"] >= 68: warnings.append(f"RSI = {ind['rsi']:.1f} — نزدیک اشباع خرید")
        if ind["williams_r"] > -20: warnings.append(f"Williams %R = {ind['williams_r']:.1f} — اشباع خرید")
    else:
        if not ind["price_above_ema200"]: reasons.append("قیمت زیر EMA200")
        if not ind["ema20_above_ema50"]: reasons.append("EMA20 زیر EMA50")
        if ind["ema20_bearish_cross"]: reasons.append("کراس نزولی EMA20/EMA50")
        if ind["macd_hist"] < 0: reasons.append("MACD منفی")
        if ind["minus_di"] > ind["plus_di"]: reasons.append("-DI > +DI")
        if ind["adx"] >= 25: reasons.append(f"ADX = {ind['adx']:.1f}")
        if ind["volume_ratio"] >= 1.5: reasons.append(f"حجم غیرعادی = {ind['volume_ratio']:.1f}×")
        elif ind["volume_ratio"] >= 1: reasons.append(f"حجم = {ind['volume_ratio']:.1f}× میانگین")
        if ind["higher_tf_trend_down"]: reasons.append("تأیید تایم‌فریم بالاتر")
        if not ind["price_above_vwap"]: reasons.append("قیمت زیر VWAP")
        if ind["roc"] < 0: reasons.append("ROC منفی")
        if ind["cci"] < 0: reasons.append("CCI منفی")
        if ind["breakout_down"]: reasons.append("شکست حمایت (Breakdown)")
        if ind["bearish_div"]: reasons.append("واگرایی منفی RSI")
        if ind["macd_bearish_div"]: reasons.append("واگرایی منفی MACD")
        if ind["rsi"] <= 32: warnings.append(f"RSI = {ind['rsi']:.1f} — نزدیک اشباع فروش")
        if ind["williams_r"] < -80: warnings.append(f"Williams %R = {ind['williams_r']:.1f} — اشباع فروش")

    return reasons, warnings

def build_ladder_weighted(ind, direction, mode):
    config = MODE_CONFIGS[mode]
    price = float(ind["price"])
    atr = float(ind["atr"])
    if atr <= 0: atr = price * 0.01
    entries = [price - atr * m if direction == "LONG" else price + atr * m for m in config["entry_ladder_atr"]]
    avg_entry = sum(e * w for e, w in zip(entries, ENTRY_WEIGHTS))
    take_profits = [avg_entry + atr * m if direction == "LONG" else avg_entry - atr * m for m in config["tp_multipliers"]]
    if direction == "LONG":
        initial_stop = min(avg_entry - config["sl_atr_mult"] * atr, ind["support"] * 0.995)
    else:
        initial_stop = max(avg_entry + config["sl_atr_mult"] * atr, ind["resistance"] * 1.005)
    risk = abs(avg_entry - initial_stop)
    reward = abs(take_profits[-1] - avg_entry)
    rr = reward / risk if risk > 0 else 0
    entry_to_sl_pct = (risk / avg_entry * 100) if avg_entry > 0 else 0
    entry_to_tp_pct = (reward / avg_entry * 100) if avg_entry > 0 else 0
    return {
        "entries": entries,
        "stop_losses": [initial_stop],
        "take_profits": take_profits,
        "avg_entry": avg_entry,
        "risk": risk,
        "reward": reward,
        "rr": rr,
        "entry_to_sl_pct": entry_to_sl_pct,
        "entry_to_tp_pct": entry_to_tp_pct,
        "sl_atr": risk / atr if atr > 0 else 0,
        "tp_atr": reward / atr if atr > 0 else 0,
    }

def calc_liquidation_price(direction, entry, leverage):
    maint_margin = 0.005
    if direction == "LONG":
        return entry * (1 - 1/leverage + maint_margin)
    return entry * (1 + 1/leverage - maint_margin)

def determine_leverage(confidence, mode):
    config = MODE_CONFIGS[mode]
    if confidence >= 90:
        return config["max_leverage"]
    if confidence >= 80:
        return max(1, config["max_leverage"] - 2)
    if confidence >= 70:
        return max(1, config["max_leverage"] - 3)
    return 1

async def generate_trade_plan(code, mode="standard"):
    ind = await cache.get_indicators(code, mode)
    if not ind:
        return None
    config = MODE_CONFIGS[mode]
    direction, confidence, scores = decide_direction(ind, mode)
    if not direction:
        return None
    levels = build_ladder_weighted(ind, direction, mode)
    if levels["rr"] < config["min_rr"]:
        return None
    funding = await cache.get_funding_rate(code)

    fg_value, _ = await get_fear_greed()
    if fg_value is not None:
        if direction == "LONG" and fg_value > 80:
            confidence -= 5
        elif direction == "SHORT" and fg_value < 20:
            confidence -= 5

    if direction == "LONG" and funding > 0.05:
        confidence -= 5
    elif direction == "LONG" and funding > 0.1:
        confidence -= 10
    elif direction == "SHORT" and funding < -0.05:
        confidence -= 5
    elif direction == "SHORT" and funding < -0.1:
        confidence -= 10

    confidence = max(0, min(100, confidence))
    leverage = determine_leverage(confidence, mode)
    entry_avg = levels["avg_entry"]
    liq = calc_liquidation_price(direction, entry_avg, leverage)

    reasons, warnings = signal_reasons(direction, ind, mode)

    plan = TradePlan(
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
        liquidation_price=liq,
        scores=scores,
        reasons=reasons,
        warnings=warnings,
        support=ind["support"],
        resistance=ind["resistance"],
        breakout_up=ind["breakout_up"],
        breakout_down=ind["breakout_down"],
        bullish_div=ind["bullish_div"],
        bearish_div=ind["bearish_div"],
        macd_bullish_div=ind["macd_bullish_div"],
        macd_bearish_div=ind["macd_bearish_div"],
        entry_price=entry_avg,
        sl_price=levels["stop_losses"][0],
        tp_prices=levels["take_profits"],
        timestamp=time.time(),
        mode=mode,
    )
    record_signal(plan)
    return plan

def record_signal(plan):
    record = {
        "symbol": plan.symbol,
        "direction": plan.direction,
        "entry_price": plan.entry_price,
        "sl_price": plan.sl_price,
        "tp_prices": plan.tp_prices,
        "confidence": plan.confidence,
        "timestamp": plan.timestamp,
        "status": "open",
        "mode": plan.mode,
    }
    signal_history.append(record)
    if len(signal_history) > 200:
        signal_history.pop(0)

def update_signal_status(symbol, current_price):
    for rec in signal_history:
        if rec["status"] != "open":
            continue
        if rec["symbol"] != symbol:
            continue
        direction = rec["direction"]
        if direction == "LONG":
            if current_price <= rec["sl_price"]:
                rec["status"] = "sl_hit"
            elif current_price >= rec["tp_prices"][2]:
                rec["status"] = "tp3_hit"
            elif current_price >= rec["tp_prices"][1]:
                rec["status"] = "tp2_hit"
            elif current_price >= rec["tp_prices"][0]:
                rec["status"] = "tp1_hit"
        else:
            if current_price >= rec["sl_price"]:
                rec["status"] = "sl_hit"
            elif current_price <= rec["tp_prices"][2]:
                rec["status"] = "tp3_hit"
            elif current_price <= rec["tp_prices"][1]:
                rec["status"] = "tp2_hit"
            elif current_price <= rec["tp_prices"][0]:
                rec["status"] = "tp1_hit"

# ---------- Formatting ----------
def format_main_signal(plan, code, chat_id):
    direction = "🟢 لانگ (خرید)" if plan.direction == "LONG" else "🔴 شورت (فروش)"
    funding = f"\n💰 فاندینگ: {plan.funding_rate:+.3f}%" if plan.funding_rate else ""
    liq = f"\n🧯 لیکوئیدیشن تقریبی: {fmt_amount(plan.liquidation_price, chat_id)}" if plan.liquidation_price else ""
    mode_label = MODE_CONFIGS.get(plan.mode, MODE_CONFIGS["standard"])["label"]
    text = (
        f"{mood_emoji(plan)} سیگنال {direction} | {COIN_ICONS.get(code, '🔸')} {sym(code)}\n"
        f"🕒 {shamsi_now()}\n"
        f"🛠️ حالت: {mode_label}\n{DIVIDER}\n"
        f"🎯 اطمینان: {plan.confidence:.0f}٪ ({confidence_badge(plan.confidence)})\n"
        f"⚡ اهرم پیشنهادی: {plan.leverage}x{funding}{liq}\n"
        f"📊 روند: {plan.trend} | RSI: {plan.rsi:.1f}\n"
        f"💰 قیمت فعلی: {fmt_amount(plan.current_price, chat_id)}\n\n"
        f"{format_ladder_block(plan.entries, plan.take_profits, plan.stop_losses, chat_id)}\n"
        f"{DIVIDER}\n"
        f"📐 نسبت ریسک به بازده تا TP3: 1:{plan.rr:.2f}\n"
        f"⚠️ مدیریت ریسک: حداکثر ۱٪ سرمایه در این معامله.\n"
        f"برای جزئیات فنی روی دکمه زیر بزنید."
    )
    return rtl_lines(text)

def format_technical_details(code, plan, ind, chat_id):
    direction = "🟢 لانگ (خرید)" if plan.direction == "LONG" else "🔴 شورت (فروش)"
    reasons_text = "\n".join(f" ✅ {x}" for x in plan.reasons[:15])
    warnings_text = "\n" + "\n".join(f" ⚠️ {x}" for x in plan.warnings) if plan.warnings else ""
    quality = format_quality(plan.scores)
    text = (
        f"📊 *جزئیات فنی* {COIN_ICONS.get(code, '🔸')} {sym(code)}\n"
        f"🕒 {shamsi_now()}\n{DIVIDER}\n"
        f"جهت: {direction}\n"
        f"امتیاز نهایی: {plan.confidence:.0f}٪\n"
        f"{DIVIDER}\n"
        f"📈 *دلایل سیگنال*\n{reasons_text}{warnings_text}\n\n"
        f"{quality}\n\n"
        f"📐 *اندیکاتورها*\n"
        f"EMA20: {fmt_amount(ind['ema20'], chat_id)}\n"
        f"EMA50: {fmt_amount(ind['ema50'], chat_id)}\n"
        f"EMA200: {fmt_amount(ind['ema200'], chat_id)}\n"
        f"فاصله EMA50: {ind['price_ema50_pct']:+.2f}%\n"
        f"فاصله EMA200: {ind['price_ema200_pct']:+.2f}%\n"
        f"ADX: {ind['adx']:.1f} (DI+ {ind['plus_di']:.1f} / DI- {ind['minus_di']:.1f})\n"
        f"MACD Hist: {ind['macd_hist']:.4f}\n"
        f"RSI: {ind['rsi']:.1f}\n"
        f"Stoch RSI: {ind['stoch_k']:.1f}\n"
        f"ROC: {ind['roc']:+.2f}%\n"
        f"CCI: {ind['cci']:.1f}\n"
        f"Williams %R: {ind['williams_r']:.1f}\n"
        f"BB %: {ind['bb_percent']:.2f} | BB Width: {ind['bb_width']:.2f}\n"
        f"Volume Ratio: {ind['volume_ratio']:.2f}×\n"
        f"VWAP: {fmt_amount(ind['vwap'], chat_id)}\n"
        f"ATR: {fmt_amount(ind['atr'], chat_id)} ({ind['atr_pct']:.2f}%)\n"
        f"تأیید تایم‌فریم بالاتر: {ind['confirm_up_count']} صعودی / {ind['confirm_down_count']} نزولی\n"
        f"حمایت: {fmt_amount(ind['support'], chat_id)} | مقاومت: {fmt_amount(ind['resistance'], chat_id)}\n"
        f"{DIVIDER}\n"
        f"💰 فاندینگ: {plan.funding_rate:+.3f}%\n"
        f"{DIVIDER}\n"
        f"⚠️ این تحلیل تکنیکال است و تضمین سود نیست."
    )
    return rtl_lines(text)

def format_quality(scores):
    def bar(value, maximum=100):
        ratio = max(0, min(1, value / maximum))
        filled = round(ratio * 10)
        return "█" * filled + "░" * (10 - filled)
    return (
        f"📊 *کیفیت سیگنال*\n"
        f"روند {bar(scores['trend'], 25)} {scores['trend'] / 25 * 100:.0f}%\n"
        f"مومنتوم {bar(scores['momentum'], 25)} {scores['momentum'] / 25 * 100:.0f}%\n"
        f"حجم {bar(scores['volume'], 15)} {scores['volume'] / 15 * 100:.0f}%\n"
        f"نوسان {bar(scores['volatility'], 15)} {scores['volatility'] / 15 * 100:.0f}%\n"
        f"تأیید تایم‌فریم بالا {bar(scores['htf'], 20)} {scores['htf'] / 20 * 100:.0f}%"
    )

def format_ladder_block(entries, take_profits, stop_losses, chat_id):
    nums = ["1️⃣", "2️⃣", "3️⃣"]
    entries_txt = "\n".join(f" {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(entries))
    tp_txt = "\n".join(f" {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(take_profits))
    sl_txt = "\n".join(f" {nums[i]} {fmt_amount(p, chat_id)}" for i, p in enumerate(stop_losses))
    return (
        f"📥 ورود پله‌ای\n{entries_txt}\n\n"
        f"🎯 حد سود سه‌پله‌ای\n{tp_txt}\n\n"
        f"🛑 حد ضرر اولیه (تریلینگ)\n{sl_txt}"
    )

# ---------- Instant status ----------
async def generate_status_text_async(code, chat_id, mode="standard"):
    ind = await cache.get_indicators(code, mode)
    if not ind:
        return rtl_lines(f"{COIN_ICONS.get(code, '🔸')} *{code}*\n\n⚠️ داده کافی برای تحلیل این ارز دریافت نشد.")
    plan = await generate_trade_plan(code, mode)
    mode_label = MODE_CONFIGS.get(mode, MODE_CONFIGS["standard"])["label"]
    header = (
        f"🧭 *وضعیت لحظه‌ای* {COIN_ICONS.get(code, '🔸')} *{sym(code)}*\n"
        f"🕒 {shamsi_now()}\n"
        f"🛠️ حالت: {mode_label}\n{DIVIDER}\n"
    )
    # خلاصه ۵ کندل اخیر
    last_candles = cache.ohlcv[mode]["main_tf"].get(code)
    candles_text = ""
    if last_candles is not None and len(last_candles) >= 5:
        for i in range(-5, 0):
            row = last_candles.iloc[i]
            change = "🟢" if row["close"] >= row["open"] else "🔴"
            candles_text += f"{shamsi_date(row['timestamp'])} {row['timestamp'].strftime('%H:%M')}  {change}  {fmt_amount(row['close'], chat_id)}\n"
    else:
        candles_text = "داده کافی برای نمایش ۵ کندل اخیر نیست.\n"

    body = (
        f"💰 قیمت: {fmt_amount(ind['price'], chat_id)}\n"
        f"📊 روند EMA200: {ind['trend_label']}\n"
        f"📐 EMA20: {fmt_amount(ind['ema20'], chat_id)}\n"
        f"📐 EMA50: {fmt_amount(ind['ema50'], chat_id)}\n"
        f"📐 فاصله EMA50: {ind['price_ema50_pct']:+.2f}%\n"
        f"📐 فاصله EMA200: {ind['price_ema200_pct']:+.2f}%\n"
        f"🔄 EMA20/50: {'صعودی' if ind['ema20_above_ema50'] else 'نزولی'}\n"
        f"⚡ ADX: {ind['adx']:.1f} — {'روند قوی 💪' if ind['adx'] >= MODE_CONFIGS[mode]['adx_min'] else 'بازار رنج 😐'}\n"
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
        f"🗺️ تأیید تایم‌فریم بالاتر: {ind['confirm_up_count']} صعودی / {ind['confirm_down_count']} نزولی\n"
        f"⚡ ATR: {fmt_amount(ind['atr'], chat_id)} ({ind['atr_pct']:.2f}%)\n"
        f"🏔️ حمایت: {fmt_amount(ind['support'], chat_id)} | مقاومت: {fmt_amount(ind['resistance'], chat_id)}\n"
        f"{DIVIDER}\n"
        f"🕯 *۵ کندل اخیر:*\n{candles_text}\n"
        f"{DIVIDER}\n"
    )
    if plan and plan.confidence >= MIN_SIGNAL_CONFIDENCE:
        direction_text = "🟢 لانگ (خرید)" if plan.direction == "LONG" else "🔴 شورت (فروش)"
        reasons, warnings = signal_reasons(plan.direction, ind, mode)
        reason_text = "\n".join(f" ✅ {x}" for x in reasons[:12])
        warning_text = "\n" + "\n".join(f" ⚠️ {x}" for x in warnings) if warnings else ""
        quality_text = format_quality(plan.scores)
        footer = (
            f"📐 *سیگنال فعلی:* {direction_text}\n"
            f"🎯 امتیاز نهایی: *{plan.confidence:.0f}٪* ({confidence_badge(plan.confidence)})\n\n"
            f"🟢 *دلایل سیگنال*\n{reason_text}{warning_text}\n\n"
            f"{quality_text}\n\n"
            f"💰 *ریسک / بازده*\n"
            f"📊 R/R: *1:{plan.rr:.2f}*\n"
            f"🛑 فاصله Entry → SL: *{plan.entry_to_sl_pct:.2f}%* ({plan.sl_atr:.2f} ATR)\n"
            f"🎯 فاصله Entry → TP: *{plan.entry_to_tp_pct:.2f}%* ({plan.tp_atr:.2f} ATR)\n\n"
            f"{format_ladder_block(plan.entries, plan.take_profits, plan.stop_losses, chat_id)}\n"
        )
    else:
        footer = (
            f"💤 فعلاً سیگنال نهایی وجود ندارد.\n"
            f"امتیاز بهترین جهت: {plan.confidence if plan else 0:.0f}٪\n"
            "برای جلوگیری از سیگنال ضعیف، جهت‌های متضاد باید اختلاف امتیاز کافی داشته باشند."
        )
    return rtl_lines(header + body + footer + f"\n{DIVIDER}\n⚠️ این تحلیل تکنیکال است و تضمین سود یا توصیه مالی نیست.")

# ---------- Weekly summary ----------
async def generate_weekly_summary_async(code, chat_id):
    week_df = await cache.get_weekly_data(code)
    if week_df is None or len(week_df) < 2:
        return rtl_lines(f"{COIN_ICONS.get(code, '🔸')} *{code}*\n\n⚠️ حداقل داده لازم برای تحلیل ۷ روزه دریافت نشد.")
    week_df = week_df.sort_values("timestamp").reset_index(drop=True)
    close = week_df["close"]
    first_price = float(close.iloc[0]); current_price = float(close.iloc[-1])
    if first_price <= 0: return "⚠️ قیمت تاریخی نامعتبر است."
    cumulative_return = ((current_price / first_price) - 1) * 100
    returns = close.pct_change() * 100
    positive_days = int((returns > 0).sum()); negative_days = int((returns < 0).sum())
    best_day = float(returns.max()); worst_day = float(returns.min())
    best_idx = returns.idxmax(); worst_idx = returns.idxmin()
    highest = float(week_df["high"].max()); lowest = float(week_df["low"].min())
    range_pct = ((highest - lowest) / first_price * 100)
    high_row = week_df.loc[week_df["high"].idxmax()]; low_row = week_df.loc[week_df["low"].idxmin()]
    running_max = close.cummax(); drawdown = (close / running_max - 1) * 100; max_drawdown = float(drawdown.min())
    running_min = close.cummin(); runup = (close / running_min - 1) * 100; max_runup = float(runup.max())
    volatility = float(returns.dropna().std() or 0)
    atr_series = AverageTrueRange(week_df["high"], week_df["low"], close, window=min(14, max(2, len(week_df)-1))).average_true_range()
    atr_daily = float(atr_series.iloc[-1]) if pd.notna(atr_series.iloc[-1]) else 0
    atr_pct = (atr_daily / current_price * 100) if current_price > 0 else 0
    avg_volume = float(week_df["volume"].mean()); first_volume = float(week_df["volume"].iloc[0]); last_volume = float(week_df["volume"].iloc[-1])
    volume_trend_pct = ((last_volume / first_volume) - 1) * 100 if first_volume > 0 else 0
    volume_trend = "افزایشی 🔊" if volume_trend_pct > 10 else "کاهشی 🔇" if volume_trend_pct < -10 else "خنثی"
    daily_all = cache.ohlcv.get("1d", {}).get(code)
    daily_rsi = daily_ema20 = daily_ema50 = daily_macd = daily_adx = bb_position = bb_width = None
    if daily_all is not None and len(daily_all) >= 50:
        d_close = daily_all["close"]
        rsi = RSIIndicator(d_close, window=14).rsi()
        ema20 = EMAIndicator(d_close, window=20).ema_indicator(); ema50 = EMAIndicator(d_close, window=50).ema_indicator()
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
    if daily_ema20 is not None and daily_ema50 is not None:
        if current_price > daily_ema20 and daily_ema20 > daily_ema50: trend = "صعودی قوی 📈"
        elif current_price > daily_ema50: trend = "صعودی ملایم 📈"
        elif current_price < daily_ema20 and daily_ema20 < daily_ema50: trend = "نزولی قوی 📉"
        else: trend = "نزولی ملایم 📉"
    else: trend = "نامشخص"
    returns_vals = returns.dropna().tolist(); consecutive_up = 0
    for v in reversed(returns_vals):
        if v > 0: consecutive_up += 1
        else: break
    consecutive_down = 0
    for v in reversed(returns_vals):
        if v < 0: consecutive_down += 1
        else: break
    if daily_macd is not None and daily_macd > 0 and volume_trend_pct > 0: momentum_volume = "مومنتوم با حجم تأیید می‌شود 🟢"
    elif daily_macd is not None and daily_macd < 0 and volume_trend_pct < 0: momentum_volume = "ضعف مومنتوم با کاهش حجم 🔴"
    else: momentum_volume = "تأیید کامل وجود ندارد ⚠️"
    ret_3d = ((current_price / float(close.iloc[max(0, len(close)-4)])) - 1) * 100 if len(close) >= 4 else 0
    ret_24h = float(returns.iloc[-1]) if not returns.empty else 0
    best_date = shamsi_date(week_df.loc[best_idx, "timestamp"]) if best_idx in week_df.index else "-"
    worst_date = shamsi_date(week_df.loc[worst_idx, "timestamp"]) if worst_idx in week_df.index else "-"
    funding = await cache.get_funding_rate(code)
    fg_value, fg_class = await get_fear_greed()
    text = (
        f"📊 *تحلیل جامع ارز* {COIN_ICONS.get(code, '🔸')} *{code}*\n"
        f"🕒 {shamsi_now()}\n{DIVIDER}\n"
        f"💰 قیمت فعلی: {fmt_amount(current_price, chat_id)}\n"
        f"📈 بازده ۷ روزه: *{cumulative_return:+.2f}%*\n"
        f"📈 بازده ۳ روزه: *{ret_3d:+.2f}%*\n"
        f"📈 بازده ۲۴h: *{ret_24h:+.2f}%*\n"
        f"{DIVIDER}\n"
        f"📈 بالاترین: {fmt_amount(highest, chat_id)} 📅 {shamsi_date(high_row['timestamp'])}\n"
        f"📉 پایین‌ترین: {fmt_amount(lowest, chat_id)} 📅 {shamsi_date(low_row['timestamp'])}\n"
        f"📏 محدوده ۷ روزه: *{range_pct:.2f}%*\n"
        f"🚀 بیشینه رشد: *{max_runup:+.2f}%*\n"
        f"🛑 بیشینه کاهش: *{max_drawdown:.2f}%*\n"
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
    text += (
        f"\n{DIVIDER}\n"
        f"💰 فاندینگ: {funding:+.3f}%\n"
        f"🧭 شاخص ترس و طمع: {fg_value if fg_value is not None else '-'} ({fg_class if fg_class else '-'})\n"
        f"{DIVIDER}\nℹ️ داده‌ها از قراردادهای USDT Perpetual در KuCoin محاسبه شده‌اند."
    )
    return rtl_lines(text)

# ---------- Prices formatting ----------
def format_prices_pretty(prices, chat_id):
    lines = ["💰 قیمت لحظه‌ای قراردادها", f"🕒 {shamsi_now()}", DIVIDER]
    for code in COIN_CODES:
        status = cache.market_status.get(code, {}).get("status")
        if status == "SWAP OK" and code in prices and prices[code] is not None:
            source_symbol = price_sources.get(code, "K")
            source_emoji = {
                "B": "🅑", "W": "🅦", "K": "🅚", "M": "🅜"
            }.get(source_symbol, "🅚")
            lines.append(f"{COIN_ICONS.get(code, '🔸')} {code}  →  {fmt_amount(prices[code], chat_id)}  {source_emoji}")
        elif status == "SWAP OK":
            lines.append(f"{COIN_ICONS.get(code, '🔸')} {code}  ⚠️ در حال دریافت...")
        elif status == "TICKER ERROR":
            lines.append(f"{COIN_ICONS.get(code, '🔸')} {code}  🟠 خطا در دریافت قیمت")
        else:
            lines.append(f"{COIN_ICONS.get(code, '🔸')} {code}  ⚪ در دسترس نیست")
    return rtl_lines("\n".join(lines))

# ---------- Split message ----------
def split_long_message(text, limit=TELEGRAM_MSG_LIMIT):
    if len(text) <= limit:
        return [text]
    parts, current = [], ""
    for block in text.split("\n\n"):
        if len(block) > limit:
            if current:
                parts.append(current.strip()); current = ""
            for i in range(0, len(block), limit):
                parts.append(block[i:i + limit])
            continue
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) > limit:
            parts.append(current.strip()); current = block
        else:
            current = candidate
    if current:
        parts.append(current.strip())
    return parts

# ---------- Screen management ----------
async def clear_interactive_screen(context, chat_id, keep_id=None):
    ids = interactive_screen_messages.pop(chat_id, [])
    for mid in ids:
        if mid == keep_id: continue
        try: await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception: pass

def set_interactive_screen(chat_id, message_ids):
    interactive_screen_messages[chat_id] = message_ids

def add_to_interactive_screen(chat_id, message_id):
    if chat_id not in interactive_screen_messages:
        interactive_screen_messages[chat_id] = []
    interactive_screen_messages[chat_id].append(message_id)

async def clear_overlay(context, chat_id):
    ids = overlay_messages.pop(chat_id, [])
    for mid in ids:
        try: await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception: pass

async def track_auto_message(app, chat_id, message_id):
    history = auto_message_history.setdefault(chat_id, [])
    history.append(message_id)
    while len(history) > AUTO_KEEP_LAST_N:
        old = history.pop(0)
        try: await app.bot.delete_message(chat_id=chat_id, message_id=old)
        except Exception: pass

# ---------- Keyboards ----------
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

def kb_mode_selection():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("⚡ سریع", callback_data="mode_fast")],
        [InlineKeyboardButton("🔥 نیمه‌سریع", callback_data="mode_semi_fast")],
        [InlineKeyboardButton("📊 استاندارد", callback_data="mode_standard")],
        [InlineKeyboardButton("🛡️ محافظه‌کار", callback_data="mode_conservative")],
    ])

def kb_main(user_id, mode="standard"):
    rows = [
        [InlineKeyboardButton("💰 قیمت لحظه‌ای", callback_data="menu_prices"), InlineKeyboardButton("🪙 انتخاب ارز", callback_data="menu_coins")],
        [InlineKeyboardButton("🧾 گزارش دوره‌ای", callback_data="periodic_report"), InlineKeyboardButton("📈 داشبورد تحلیلی", callback_data="dashboard")],
        [InlineKeyboardButton("📅 رویدادها", callback_data="events"), InlineKeyboardButton("⭐ علاقه‌مندی‌ها", callback_data="favorites")],
        [InlineKeyboardButton("🔄 تغییر سبک معاملاتی", callback_data="change_mode"), InlineKeyboardButton("🔄 شروع مجدد", callback_data="restart_bot")],
        [InlineKeyboardButton("🛑 توقف ربات", callback_data="stop_bot"), InlineKeyboardButton("❓ راهنما", callback_data="help")],
    ]
    if is_admin(user_id):
        rows.append([
            InlineKeyboardButton("⚙️ پنل مدیریت", callback_data="admin_panel"),
            InlineKeyboardButton("📊 گزارش مقایسه‌ای", callback_data="admin_compare"),
        ])
    return InlineKeyboardMarkup(rows)

def kb_admin_panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی کامل", callback_data="menu_all")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")],
    ])

def kb_back_main():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")]])

def kb_coins():
    buttons = []
    for code in COIN_CODES:
        status = cache.market_status.get(code, {}).get("status")
        if status == "SWAP OK": label = f"{COIN_ICONS.get(code, '🔸')} {code} 🟢"
        elif status == "TICKER ERROR": label = f"{COIN_ICONS.get(code, '🔸')} {code} 🟠"
        else: label = f"{COIN_ICONS.get(code, '🔸')} {code} ⚪"
        buttons.append(InlineKeyboardButton(label, callback_data=f"coin_{code}"))
    rows = build_grid_keyboard(buttons, COINS_GRID_COLUMNS)
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")])
    return InlineKeyboardMarkup(rows)

def kb_coin_detail(code, is_fav):
    fav_btn = InlineKeyboardButton("🗑️ حذف از علاقه‌مندی‌ها" if is_fav else "⭐ افزودن به علاقه‌مندی‌ها", callback_data=f"toggle_fav_{code}")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧭 وضعیت لحظه‌ای", callback_data=f"suggest_{code}")],
        [InlineKeyboardButton("📆 تحلیل جامع ارز", callback_data=f"weekly_{code}")],
        [InlineKeyboardButton("🚀 پیشنهاد لحظه‌ای", callback_data=f"instant_{code}")],
        [fav_btn],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_coins")],
    ])

def kb_signal_details(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 جزئیات فنی", callback_data=f"details_{code}")],
        [InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"suggest_{code}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"coin_{code}")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")],
    ])

def kb_back_to_signal(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت به سیگنال", callback_data=f"suggest_{code}")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")],
    ])

def kb_weekly(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"coin_{code}")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")],
    ])

def kb_suggestion(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"suggest_{code}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"coin_{code}")],
        [InlineKeyboardButton("📋 لیست ارزها", callback_data="menu_coins")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")],
    ])

def kb_auto_report(top_plans):
    buttons = [
        InlineKeyboardButton(f"{COIN_ICONS.get(p.symbol, '🔸')} {p.symbol}", callback_data=f"suggest_{p.symbol}_auto")
        for p in top_plans
    ]
    rows = build_grid_keyboard(buttons, 3)
    rows.append([InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")])
    return InlineKeyboardMarkup(rows)

def kb_periodic_report():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 هفتگی", callback_data="report_weekly"), InlineKeyboardButton("📅 ماهانه", callback_data="report_monthly")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")],
    ])

def kb_help(step=0):
    buttons = []
    if step < 7:
        buttons.append(InlineKeyboardButton("بعدی ⬅️", callback_data=f"help_{step+1}"))
    if step > 0:
        buttons.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"help_{step-1}"))
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("بازگشت", callback_data="menu_main")])
    return InlineKeyboardMarkup(rows)

def help_text(step):
    if step == 0:
        return rtl_lines(
            "📖 *شروع کار با ربات*\n"
            f"{DIVIDER}\n"
            "برای شروع /start را بزنید.\n"
            "ابتدا واحد پولی (دلار/تومان/هر دو) را انتخاب کنید.\n"
            "سپس سبک معاملاتی خود را از چهار حالت انتخاب کنید.\n"
            "در نهایت منوی اصلی نمایش داده می‌شود."
        )
    elif step == 1:
        return rtl_lines(
            "💰 *قیمت‌های لحظه‌ای و منابع*\n"
            f"{DIVIDER}\n"
            "قیمت‌ها از چند صرافی دریافت می‌شوند:\n"
            "🅑 بیت‌پین\n"
            "🅦 ولکس\n"
            "🅚 کوکوین\n"
            "🅜 MEXC\n"
            "منبع قیمت در انتهای هر خط نمایش داده می‌شود."
        )
    elif step == 2:
        return rtl_lines(
            "🪙 *ارزها و علاقه‌مندی‌ها*\n"
            f"{DIVIDER}\n"
            "از منوی «انتخاب ارز» می‌توانید وارد صفحه هر ارز شوید.\n"
            "در آن‌جا می‌توانید ارز را به علاقه‌مندی‌ها اضافه یا حذف کنید.\n"
            "علاقه‌مندی‌ها برای دریافت خودکار سیگنال استفاده می‌شوند."
        )
    elif step == 3:
        return rtl_lines(
            "📊 *تحلیل‌ها و سیگنال‌ها*\n"
            f"{DIVIDER}\n"
            "وضعیت لحظه‌ای: اندیکاتورها، نوارهای کیفیت، سطوح حمایت/مقاومت، خلاصه کندل‌ها\n"
            "پیشنهاد لحظه‌ای: سیگنال ورود/حد سود/حد ضرر\n"
            "تحلیل جامع ارز: گزارش هفتگی + وضعیت تکنیکال + داده‌های فیوچرز\n"
            "ارسال خودکار رویدادمحور است (فقط سیگنال جدید/تغییر جهت/بسته‌شدن)"
        )
    elif step == 4:
        return rtl_lines(
            "📈 *داشبورد و گزارش‌ها*\n"
            f"{DIVIDER}\n"
            "داشبورد تحلیلی: نرخ برد، فاکتور سود، Expectancy، Max Drawdown، Sharpe، Risk of Ruin\n"
            "گزارش دوره‌ای: هفتگی/ماهانه"
        )
    elif step == 5:
        return rtl_lines(
            "💡 *اصطلاحات و داده‌های فیوچرز*\n"
            f"{DIVIDER}\n"
            "لانگ: خرید با انتظار افزایش\n"
            "شورت: فروش با انتظار کاهش\n"
            "اهرم: چند برابر کردن سرمایه\n"
            "حد ضرر: خروج از ضرر\n"
            "حد سود: برداشت سود\n"
            "R/R: نسبت ریسک به بازده"
        )
    else:
        return rtl_lines(
            "❓ *پرسش‌های متداول*\n"
            f"{DIVIDER}\n"
            "چطور سیگنال بگیرم؟ → انتخاب ارز → پیشنهاد لحظه‌ای\n"
            "ارسال خودکار چگونه است؟ → فقط برای ارزهای مورد علاقه، رویدادمحور\n"
            "چطور ربات را متوقف کنم؟ → دکمه توقف ربات یا /stop\n"
            "آیا سیگنال‌ها تضمین سود هستند؟ → خیر، تحلیل تکنیکال است"
        )

def welcome_text():
    return rtl_lines(
        "🌟✨ *به سیگنال‌یار حرفه‌ای خوش اومدی!* ✨🌟\n"
        f"{DIVIDER}\n"
        f"🛰️ در حال رصد {len(cache.valid_codes)} قرارداد Perpetual هستم\n"
        "🔔 ارسال سیگنال‌ها رویدادمحور است؛ فقط هنگام سیگنال جدید، تغییر جهت یا بسته‌شدن پیام می‌فرستم\n"
        "👇 برای بررسی دستی از منوی زیر استفاده کن\n\n"
        "برای توقف ربات: /stop\n\n"
        "⚠️ تحلیل تکنیکال است، نه توصیه مالی."
    )

MAIN_MENU_HEADER = "✨ *سیگنال‌یار حرفه‌ای* ✨\n" + DIVIDER + "\n" + MENU_PROMPT

async def finish_start(context, chat_id, user_id):
    commands = [
        BotCommand("start", "شروع ربات"),
        BotCommand("menu", "منوی اصلی"),
        BotCommand("status", "وضعیت سیستم"),
        BotCommand("dashboard", "داشبورد تحلیلی"),
        BotCommand("news", "رویدادهای پیش رو"),
        BotCommand("report", "گزارش دوره‌ای"),
        BotCommand("stop", "توقف ربات"),
    ] if is_admin(user_id) else [BotCommand("menu", "منوی اصلی")]
    await context.bot.set_my_commands(commands, scope=BotCommandScopeChat(chat_id=chat_id))
    await clear_interactive_screen(context, chat_id)
    mode = user_trading_mode.get(chat_id, "standard")
    msg = await context.bot.send_message(chat_id=chat_id, text=welcome_text(), reply_markup=kb_main(user_id, mode), parse_mode="Markdown")
    set_interactive_screen(chat_id, [msg.message_id])

# ---------- Trailing monitor ----------
async def trailing_monitor_loop(app):
    await asyncio.sleep(20)
    while True:
        try:
            if active_signals:
                for chat_id, signals in list(active_signals.items()):
                    for code, data in list(signals.items()):
                        plan = data["plan"]; stage = data["stage"]
                        try:
                            ticker = await asyncio.to_thread(exchange.fetch_ticker, cache.symbol_for_code(code))
                            current = float(ticker.get("last") or ticker.get("close") or 0)
                        except Exception as e:
                            logger.debug("Trailing price fetch failed | code=%s | error=%s", code, e)
                            continue
                        if current <= 0: continue
                        update_signal_status(code, current)
                        tp1, tp2, tp3 = plan.take_profits[0], plan.take_profits[1], plan.take_profits[2]
                        if plan.direction == "LONG":
                            hit_tp1, hit_tp2, hit_tp3 = current >= tp1, current >= tp2, current >= tp3
                        else:
                            hit_tp1, hit_tp2, hit_tp3 = current <= tp1, current <= tp2, current <= tp3
                        new_stage = stage
                        if hit_tp3 and stage < 3: new_stage = 3
                        elif hit_tp2 and stage < 2: new_stage = 2
                        elif hit_tp1 and stage < 1: new_stage = 1
                        if new_stage > stage:
                            if new_stage == 1: new_sl = plan.entries[0]
                            elif new_stage == 2: new_sl = tp1
                            else: new_sl = tp2
                            data["stage"] = new_stage; data["last_notified"] = new_stage
                            text = (
                                f"🔔 بروزرسانی حد ضرر | {COIN_ICONS.get(code,'🔸')} {sym(code)}\n"
                                f"🕒 {shamsi_now()}\n{DIVIDER}\n"
                                f"✅ قیمت به TP{new_stage} رسید.\n"
                                f"🛑 حد ضرر به {fmt_amount(new_sl, chat_id)} منتقل شد.\n{DIVIDER}\n"
                                f"⚠️ این یک اطلاع‌رسانی خودکار است."
                            )
                            try:
                                await app.bot.send_message(chat_id=chat_id, text=rtl_lines(text), parse_mode="Markdown")
                            except Exception as e:
                                logger.warning("Trailing notify failed | chat_id=%s | code=%s | error=%s", chat_id, code, e)
        except Exception as e:
            logger.exception("Trailing loop error | error=%s", e)
        await asyncio.sleep(TRAILING_CHECK_SECONDS)

# ---------- Event/News monitor ----------
async def news_monitor_loop(app):
    await asyncio.sleep(30)
    while True:
        try:
            if subscribed_chat_ids:
                await check_and_notify_events(app)
        except Exception as e:
            logger.exception("News monitor error: %s", e)
        await asyncio.sleep(EVENTS_CHECK_SECONDS)

# ---------- Periodic report generation ----------
async def send_periodic_report(app, period="weekly"):
    stats = compute_advanced_stats(signal_history)
    fg_value, fg_class = await get_fear_greed()
    text = (
        f"📊 *گزارش { 'هفتگی' if period == 'weekly' else 'ماهانه' }*\n"
        f"🕒 {shamsi_now()}\n{DIVIDER}\n"
        f"🔢 تعداد کل سیگنال‌ها: {stats['total_trades']}\n"
        f"✅ نرخ برد: {stats['win_rate']:.1f}%\n"
        f"💰 فاکتور سود: {stats['profit_factor']:.2f}\n"
        f"📈 میانگین سود هر معامله (Expectancy): {stats['expectancy']:.2f} USDT\n"
        f"📉 بیشترین افت سرمایه (Max Drawdown): {stats['max_drawdown']:.2f} USDT\n"
        f"📊 نسبت شارپ: {stats['sharpe']:.2f}\n"
        f"⚠️ ریسک ورشکستگی: {stats['risk_of_ruin']:.1f}%\n"
        f"🎯 میانگین اطمینان سیگنال‌ها: {stats['avg_confidence']:.1f}%\n"
        f"🧭 شاخص ترس و طمع: {fg_value if fg_value is not None else '-'} ({fg_class if fg_class else '-'})\n"
    )
    for chat_id in subscribed_chat_ids:
        try:
            await app.bot.send_message(chat_id=chat_id, text=rtl_lines(text), parse_mode="Markdown")
        except Exception as e:
            logger.warning("Periodic report send failed: %s", e)

# ---------- Command handlers ----------
async def start(update, context):
    if not await guard(update): return
    chat_id = update.effective_chat.id
    await clear_interactive_screen(context, chat_id)
    msg = await update.message.reply_text("👋 واحد پولی نمایش قیمت‌ها را انتخاب کن:", reply_markup=kb_currency())
    set_interactive_screen(chat_id, [msg.message_id])

async def stop(update, context):
    if not await guard(update): return
    subscribed_chat_ids.discard(update.effective_chat.id)
    active_signals.pop(update.effective_chat.id, None)
    save_state()
    await update.message.reply_text("🛑 ربات متوقف شد.\nبرای فعال‌سازی دوباره /start را بزن.")

async def menu_command(update, context):
    if not await guard(update): return
    chat_id = update.effective_chat.id; user_id = update.effective_user.id
    subscribed_chat_ids.add(chat_id); save_state()
    mode = user_trading_mode.get(chat_id, "standard")
    await clear_interactive_screen(context, chat_id)
    msg = await update.message.reply_text(MAIN_MENU_HEADER, reply_markup=kb_main(user_id, mode), parse_mode="Markdown")
    set_interactive_screen(chat_id, [msg.message_id])

async def status(update, context):
    if not await guard(update): return
    ok = sum(1 for c in COIN_CODES if cache.market_status.get(c, {}).get("status") == "SWAP OK")
    no_swap = sum(1 for c in COIN_CODES if cache.market_status.get(c, {}).get("status") == "NO SWAP")
    ticker_error = sum(1 for c in COIN_CODES if cache.market_status.get(c, {}).get("status") == "TICKER ERROR")
    uptime_sec = time.time() - START_TIME
    hours, remainder = divmod(uptime_sec, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{int(hours)}:{int(minutes):02d}:{int(seconds):02d}"
    last_update_str = shamsi_now()
    if LAST_REPORT_TIME:
        last_update_str = shamsi_date(datetime.fromtimestamp(LAST_REPORT_TIME, TEHRAN_TZ))
    active_trailing_count = sum(len(signals) for signals in active_signals.values())
    fg_value, fg_class = await get_fear_greed()
    text = (
        f"📊 *وضعیت سیستم*\n🕒 {shamsi_now()}\n{DIVIDER}\n"
        f"⏳ مدت زمان اجرا: `{uptime_str}`\n"
        f"👥 اعضای فعال: {len(subscribed_chat_ids)}\n"
        f"⚡ سیگنال‌های فعال: {len(last_plans)}\n"
        f"🔁 سیگنال‌های دنبال‌شده (تریلینگ): {active_trailing_count}\n"
        f"📊 کل سیگنال‌های تولیدشده: {TOTAL_SIGNALS_GENERATED}\n"
        f"🕒 آخرین بروزرسانی سیگنال: {last_update_str}\n"
        f"🧭 شاخص ترس و طمع: {fg_value if fg_value is not None else '-'} ({fg_class if fg_class else '-'})\n"
        f"{DIVIDER}\n"
        f"🪙 کل ارزهای تعریف‌شده: {len(COIN_CODES)}\n"
        f"🟢 SWAP OK: {ok}\n"
        f"⚪ NO SWAP: {no_swap}\n"
        f"🟠 TICKER ERROR: {ticker_error}\n"
        f"📊 قیمت‌های لحظه‌ای دریافت‌شده: {len(cache.prices)} ارز\n"
        f"{DIVIDER}\n"
        f"📊 داده‌های ذخیره‌شده:\n"
        f"5m: {len(cache.ohlcv.get('5m', {}))} ارز\n"
        f"15m: {len(cache.ohlcv.get('15m', {}))} ارز\n"
        f"1h: {len(cache.ohlcv.get('1h', {}))} ارز\n"
        f"4h: {len(cache.ohlcv.get('4h', {}))} ارز\n"
        f"1d: {len(cache.ohlcv.get('1d', {}))} ارز\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def dashboard(update, context):
    if not await guard(update): return
    chat_id = update.effective_chat.id
    mode = user_trading_mode.get(chat_id, "standard")
    stats = compute_advanced_stats(signal_history, mode)
    fg_value, fg_class = await get_fear_greed()
    mode_label = MODE_CONFIGS[mode]["label"]
    text = (
        f"📈 *داشبورد تحلیلی* ({mode_label})\n🕒 {shamsi_now()}\n{DIVIDER}\n"
        f"🔢 کل سیگنال‌ها: {stats['total_trades']}\n"
        f"✅ بردها: {stats['wins']}\n"
        f"❌ باخت‌ها: {stats['losses']}\n"
        f"📊 نرخ برد: {stats['win_rate']:.1f}%\n"
        f"💰 فاکتور سود: {stats['profit_factor']:.2f}\n"
        f"📈 Expectancy: {stats['expectancy']:.2f} USDT\n"
        f"📉 Max Drawdown: {stats['max_drawdown']:.2f} USDT\n"
        f"📊 Sharpe Ratio: {stats['sharpe']:.2f}\n"
        f"⚠️ Risk of Ruin: {stats['risk_of_ruin']:.1f}%\n"
        f"🎯 میانگین اطمینان: {stats['avg_confidence']:.1f}%\n"
        f"🧭 شاخص ترس و طمع: {fg_value if fg_value is not None else '-'} ({fg_class if fg_class else '-'})\n"
        f"{DIVIDER}\n"
        f"🕒 آخرین سیگنال‌ها:\n"
    )
    for rec in signal_history[-5:]:
        if rec.get("mode") != mode:
            continue
        status_emoji = "🟢" if rec["status"].startswith("tp") else "🔴" if rec["status"] == "sl_hit" else "⏳"
        text += f"{status_emoji} {COIN_ICONS.get(rec['symbol'],'🔸')} {rec['symbol']} {rec['direction']} @ {rec['entry_price']:.4f} — {rec['status']}\n"
    await update.message.reply_text(rtl_lines(text), parse_mode="Markdown")

async def news(update, context):
    if not await guard(update): return
    events = await get_upcoming_events(force=True)
    now_utc = datetime.now(tz=TEHRAN_TZ) if TEHRAN_TZ else datetime.now()
    upcoming = [ev for ev in events if ev["time"].tzinfo is None or (ev["time"] - now_utc) >= timedelta(0)]
    if not upcoming:
        await update.message.reply_text("📅 رویداد مهمی در آینده نزدیک یافت نشد.")
        return
    text = "📅 *رویدادهای کریپتویی پیش رو:*\n" + DIVIDER + "\n"
    for ev in upcoming[:10]:
        text += f"• {ev['name']} — {shamsi_date(ev['time'])} {ev['time'].strftime('%H:%M')}\n"
    await update.message.reply_text(rtl_lines(text), parse_mode="Markdown")

async def periodic_report_command(update, context):
    if not await guard(update): return
    await update.message.reply_text("📊 لطفاً دوره‌ی گزارش را انتخاب کنید:", reply_markup=kb_periodic_report())

def save_state():
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({
                "subscribed_chat_ids": list(subscribed_chat_ids),
                "user_currency": user_currency,
                "user_trading_mode": user_trading_mode,
                "user_favorites": {str(k): list(v) for k, v in user_favorites.items()},
            }, f, ensure_ascii=False)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        logger.warning("State save failed: %s", e)

def load_state():
    global subscribed_chat_ids, user_currency, user_trading_mode, user_favorites
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        subscribed_chat_ids = {int(x) for x in data.get("subscribed_chat_ids", [])}
        user_currency = {int(k): v for k, v in data.get("user_currency", {}).items()}
        user_trading_mode = {int(k): v for k, v in data.get("user_trading_mode", {}).items()}
        user_favorites = {int(k): set(v) for k, v in data.get("user_favorites", {}).items()}
        logger.info("State restored: %s users", len(subscribed_chat_ids))
    except FileNotFoundError:
        logger.info("No state file; starting fresh.")
    except Exception as e:
        logger.warning("State load failed: %s", e)

# ---------- Button handler ----------
async def button_handler(update, context):
    if not await guard(update): return
    query = update.callback_query; await query.answer()
    data = query.data; chat_id = update.effective_chat.id; user_id = update.effective_user.id
    if data == "noop": return

    if data.startswith("cur_"):
        user_currency[chat_id] = data.split("_", 1)[1]
        subscribed_chat_ids.add(chat_id)
        save_state()
        await query.edit_message_text("🛠️ حالا سبک معاملاتی خود را انتخاب کن:", reply_markup=kb_mode_selection())
        return

    if data.startswith("mode_"):
        mode = data.split("_", 1)[1]
        user_trading_mode[chat_id] = mode
        save_state()
        await query.edit_message_text(f"✅ حالت {MODE_CONFIGS[mode]['label']} انتخاب شد.")
        await finish_start(context, chat_id, user_id)
        return

    if data == "change_mode":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text("🛠️ سبک معاملاتی جدید را انتخاب کن:", reply_markup=kb_mode_selection())
        return

    if data == "restart_bot":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text("👋 واحد پولی نمایش قیمت‌ها را انتخاب کن:", reply_markup=kb_currency())
        return

    if data == "stop_bot":
        subscribed_chat_ids.discard(chat_id)
        active_signals.pop(chat_id, None)
        save_state()
        await query.edit_message_text("🛑 ربات برای شما متوقف شد.\nبرای فعال‌سازی دوباره /start را بزن.")
        return

    if data == "help":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text(help_text(0), reply_markup=kb_help(0), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id])
        return

    if data.startswith("help_"):
        step = int(data.split("_")[1])
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text(help_text(step), reply_markup=kb_help(step), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id])
        return

    if data == "close_temp":
        await clear_overlay(context, chat_id); return

    if data == "menu_main":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        mode = user_trading_mode.get(chat_id, "standard")
        await query.edit_message_text(MAIN_MENU_HEADER, reply_markup=kb_main(user_id, mode), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id]); return

    if data == "dashboard":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        mode = user_trading_mode.get(chat_id, "standard")
        stats = compute_advanced_stats(signal_history, mode)
        fg_value, fg_class = await get_fear_greed()
        mode_label = MODE_CONFIGS[mode]["label"]
        text = (
            f"📈 *داشبورد تحلیلی* ({mode_label})\n🕒 {shamsi_now()}\n{DIVIDER}\n"
            f"🔢 کل سیگنال‌ها: {stats['total_trades']}\n"
            f"✅ بردها: {stats['wins']}\n"
            f"❌ باخت‌ها: {stats['losses']}\n"
            f"📊 نرخ برد: {stats['win_rate']:.1f}%\n"
            f"💰 فاکتور سود: {stats['profit_factor']:.2f}\n"
            f"📈 Expectancy: {stats['expectancy']:.2f} USDT\n"
            f"📉 Max Drawdown: {stats['max_drawdown']:.2f} USDT\n"
            f"📊 Sharpe Ratio: {stats['sharpe']:.2f}\n"
            f"⚠️ Risk of Ruin: {stats['risk_of_ruin']:.1f}%\n"
            f"🎯 میانگین اطمینان: {stats['avg_confidence']:.1f}%\n"
            f"🧭 شاخص ترس و طمع: {fg_value if fg_value is not None else '-'} ({fg_class if fg_class else '-'})\n"
            f"{DIVIDER}\n"
            f"🕒 آخرین سیگنال‌ها:\n"
        )
        for rec in signal_history[-5:]:
            if rec.get("mode") != mode:
                continue
            status_emoji = "🟢" if rec["status"].startswith("tp") else "🔴" if rec["status"] == "sl_hit" else "⏳"
            text += f"{status_emoji} {COIN_ICONS.get(rec['symbol'],'🔸')} {rec['symbol']} {rec['direction']} @ {rec['entry_price']:.4f} — {rec['status']}\n"
        await query.edit_message_text(rtl_lines(text), reply_markup=kb_back_main(), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id])
        return

    if data == "events":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        events = await get_upcoming_events(force=True)
        now_utc = datetime.now(tz=TEHRAN_TZ) if TEHRAN_TZ else datetime.now()
        upcoming = [ev for ev in events if ev["time"].tzinfo is None or (ev["time"] - now_utc) >= timedelta(0)]
        if not upcoming:
            text = "📅 رویداد مهمی در آینده نزدیک یافت نشد."
        else:
            text = "📅 *رویدادهای کریپتویی پیش رو:*\n" + DIVIDER + "\n"
            for ev in upcoming[:10]:
                text += f"• {ev['name']} — {shamsi_date(ev['time'])} {ev['time'].strftime('%H:%M')}\n"
        await query.edit_message_text(rtl_lines(text), reply_markup=kb_back_main(), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id])
        return

    if data == "favorites":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        favs = user_favorites.get(chat_id, set())
        if not favs:
            text = "⭐ *علاقه‌مندی‌ها*\n\nشما هنوز ارزی به علاقه‌مندی‌ها اضافه نکرده‌اید."
            await query.edit_message_text(rtl_lines(text), reply_markup=kb_back_main(), parse_mode="Markdown")
        else:
            buttons = []
            for code in favs:
                status = cache.market_status.get(code, {}).get("status")
                if status == "SWAP OK": label = f"{COIN_ICONS.get(code, '🔸')} {code} 🟢"
                elif status == "TICKER ERROR": label = f"{COIN_ICONS.get(code, '🔸')} {code} 🟠"
                else: label = f"{COIN_ICONS.get(code, '🔸')} {code} ⚪"
                buttons.append(InlineKeyboardButton(label, callback_data=f"coin_{code}"))
            rows = build_grid_keyboard(buttons, 2)
            rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")])
            await query.edit_message_text(
                rtl_lines(f"⭐ *علاقه‌مندی‌ها*\n{DIVIDER}\n{MENU_PROMPT}"),
                reply_markup=InlineKeyboardMarkup(rows),
                parse_mode="Markdown",
            )
        set_interactive_screen(chat_id, [query.message.message_id])
        return

    if data.startswith("toggle_fav_"):
        code = data.split("toggle_fav_", 1)[1]
        favs = user_favorites.setdefault(chat_id, set())
        if code in favs:
            favs.discard(code)
            await query.answer(f"❌ {code} از علاقه‌مندی‌ها حذف شد.")
        else:
            favs.add(code)
            await query.answer(f"⭐ {code} به علاقه‌مندی‌ها اضافه شد.")
        save_state()
        try:
            await query.edit_message_reply_markup(reply_markup=kb_coin_detail(code, code in favs))
        except Exception:
            pass
        return

    if data == "periodic_report":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text("📊 لطفاً دوره‌ی گزارش را انتخاب کنید:", reply_markup=kb_periodic_report())
        set_interactive_screen(chat_id, [query.message.message_id])
        return

    if data in ("report_weekly", "report_monthly"):
        period = "weekly" if data == "report_weekly" else "monthly"
        mode = user_trading_mode.get(chat_id, "standard")
        stats = compute_advanced_stats(signal_history, mode)
        fg_value, fg_class = await get_fear_greed()
        mode_label = MODE_CONFIGS[mode]["label"]
        text = (
            f"📊 *گزارش { 'هفتگی' if period == 'weekly' else 'ماهانه' } ({mode_label})*\n"
            f"🕒 {shamsi_now()}\n{DIVIDER}\n"
            f"🔢 تعداد کل سیگنال‌ها: {stats['total_trades']}\n"
            f"✅ نرخ برد: {stats['win_rate']:.1f}%\n"
            f"💰 فاکتور سود: {stats['profit_factor']:.2f}\n"
            f"📈 میانگین سود هر معامله (Expectancy): {stats['expectancy']:.2f} USDT\n"
            f"📉 بیشترین افت سرمایه (Max Drawdown): {stats['max_drawdown']:.2f} USDT\n"
            f"📊 نسبت شارپ: {stats['sharpe']:.2f}\n"
            f"⚠️ ریسک ورشکستگی: {stats['risk_of_ruin']:.1f}%\n"
            f"🎯 میانگین اطمینان سیگنال‌ها: {stats['avg_confidence']:.1f}%\n"
            f"🧭 شاخص ترس و طمع: {fg_value if fg_value is not None else '-'} ({fg_class if fg_class else '-'})\n"
        )
        await query.edit_message_text(rtl_lines(text), reply_markup=kb_back_main(), parse_mode="Markdown")
        return

    if data == "menu_prices":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text("⏳ در حال دریافت قیمت‌ها...")
        try:
            prices = await asyncio.wait_for(cache.update_prices(), timeout=90)
            await query.edit_message_text(format_prices_pretty(prices, chat_id), reply_markup=kb_back_main(), parse_mode="Markdown")
            set_interactive_screen(chat_id, [query.message.message_id])
        except Exception as e:
            logger.exception("Prices UI error: %s", e)
            await query.edit_message_text(f"❌ خطا در دریافت قیمت‌ها.\nنوع خطا: `{type(e).__name__}`", reply_markup=kb_back_main(), parse_mode="Markdown")
        return

    if data == "menu_coins":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text(rtl_lines(f"🪙 *انتخاب ارز مورد نظر*\n{DIVIDER}\n{MENU_PROMPT}"), reply_markup=kb_coins(), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id]); return

    if data.startswith("coin_"):
        code = data.split("_", 1)[1]
        if code not in COIN_CODES: return
        if code in cache.exchange_symbols:
            status = cache.market_status.get(code, {}).get("status")
            warning = ""
            if status == "TICKER ERROR":
                warning = "⚠️ قیمت لحظه‌ای در دسترس نیست، اما تحلیل‌های دیگر کار می‌کنند.\n\n"
            favs = user_favorites.get(chat_id, set())
            is_fav = code in favs
            await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
            await query.edit_message_text(
                rtl_lines(f"{COIN_ICONS.get(code, '🔸')} *{sym(code)}*\n{DIVIDER}\n{warning}🟢 وضعیت بازار: *SWAP OK*\n{MENU_PROMPT}"),
                reply_markup=kb_coin_detail(code, is_fav),
                parse_mode="Markdown",
            )
            set_interactive_screen(chat_id, [query.message.message_id])
        else:
            text = f"{COIN_ICONS.get(code, '🔸')} *{code}*\n{DIVIDER}\n⚪ وضعیت: *NO SWAP*\nدر حال حاضر قرارداد USDT Perpetual فعال برای این ارز در KuCoin پیدا نشد."
            await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
            await query.edit_message_text(rtl_lines(text), reply_markup=kb_back_main(), parse_mode="Markdown")
            set_interactive_screen(chat_id, [query.message.message_id])
        return

    if data.startswith("instant_"):
        code = data.split("instant_", 1)[1]
        if code not in COIN_CODES: return
        status = cache.market_status.get(code, {}).get("status")
        if status != "SWAP OK":
            await query.edit_message_text(f"⚠️ قرارداد {code} در KuCoin در دسترس نیست.\nوضعیت: {status}", reply_markup=kb_back_main())
            return
        mode = user_trading_mode.get(chat_id, "standard")
        await query.edit_message_text("⏳ در حال تحلیل و تولید پیشنهاد لحظه‌ای...")
        try:
            plan = await asyncio.wait_for(generate_trade_plan(code, mode), timeout=30)
            if plan is None:
                await query.edit_message_text(f"💤 فعلاً سیگنال نهایی برای {code} وجود ندارد.\nدلایل احتمالی: ADX پایین، عدم تأیید تایم‌فریم بالاتر، نسبت R/R کمتر از حد مجاز.", reply_markup=kb_back_main(), parse_mode="Markdown")
                return
            main_text = format_main_signal(plan, code, chat_id)
            await query.edit_message_text(main_text, reply_markup=kb_signal_details(code), parse_mode="Markdown")
            active_signals.setdefault(chat_id, {})[code] = {"plan": plan, "stage": 0, "last_notified": 0}
        except asyncio.TimeoutError:
            await query.edit_message_text("⏰ دریافت اطلاعات بیش از حد طول کشید.", reply_markup=kb_back_main())
        except Exception as e:
            logger.exception("Signal UI error | code=%s: %s", code, e)
            await query.edit_message_text(f"❌ خطا در دریافت اطلاعات {code}.", reply_markup=kb_back_main())
        return

    if data.startswith("suggest_"):
        auto = data.endswith("_auto")
        code = data[len("suggest_"):-len("_auto")] if auto else data[len("suggest_"):]
        if code not in COIN_CODES: return
        status = cache.market_status.get(code, {}).get("status")
        if status != "SWAP OK":
            await query.edit_message_text(f"⚠️ قرارداد {code} در KuCoin در دسترس نیست.\nوضعیت: {status}", reply_markup=kb_back_main())
            return
        mode = user_trading_mode.get(chat_id, "standard")
        await query.edit_message_text("⏳ در حال دریافت وضعیت لحظه‌ای...")
        try:
            text = await asyncio.wait_for(generate_status_text_async(code, chat_id, mode), timeout=30)
            await query.edit_message_text(split_long_message(text)[0], reply_markup=kb_suggestion(code), parse_mode="Markdown")
            set_interactive_screen(chat_id, [query.message.message_id])
        except asyncio.TimeoutError:
            await query.edit_message_text("⏰ دریافت اطلاعات بیش از حد طول کشید.", reply_markup=kb_back_main())
        except Exception as e:
            logger.exception("Signal UI error | code=%s: %s", code, e)
            await query.edit_message_text(f"❌ خطا در دریافت اطلاعات {code}.", reply_markup=kb_back_main())
        return

    if data.startswith("details_"):
        code = data.split("_", 1)[1]
        if code not in COIN_CODES: return
        mode = user_trading_mode.get(chat_id, "standard")
        try:
            ind = await cache.get_indicators(code, mode)
            if not ind: await query.edit_message_text("⚠️ داده کافی نیست.", reply_markup=kb_back_main()); return
            plan = await generate_trade_plan(code, mode)
            if not plan: await query.edit_message_text("💤 سیگنال فعلی موجود نیست.\nدلایل احتمالی: ADX پایین، عدم تأیید تایم‌فریم بالا، نسبت R/R کمتر از حد مجاز.", reply_markup=kb_back_main()); return
            details_text = format_technical_details(code, plan, ind, chat_id)
            await query.edit_message_text(split_long_message(details_text)[0], reply_markup=kb_back_to_signal(code), parse_mode="Markdown")
        except Exception as e:
            logger.exception("Details UI error | code=%s: %s", code, e)
            await query.edit_message_text(f"❌ خطا در نمایش جزئیات {code}.", reply_markup=kb_back_main())
        return

    if data.startswith("weekly_"):
        code = data.split("_", 1)[1]
        if code not in COIN_CODES: return
        status = cache.market_status.get(code, {}).get("status")
        if status != "SWAP OK":
            await query.edit_message_text(f"⚠️ قرارداد {code} در KuCoin در دسترس نیست.\nوضعیت: {status}", reply_markup=kb_back_main())
            return
        await query.edit_message_text("⏳ در حال دریافت تحلیل جامع ارز...")
        try:
            summary = await asyncio.wait_for(generate_weekly_summary_async(code, chat_id), timeout=30)
            await query.edit_message_text(split_long_message(summary)[0], reply_markup=kb_weekly(code), parse_mode="Markdown")
            set_interactive_screen(chat_id, [query.message.message_id])
        except asyncio.TimeoutError:
            await query.edit_message_text("⏰ دریافت داده‌های هفتگی طول کشید.", reply_markup=kb_back_main())
        except Exception as e:
            logger.exception("Weekly UI error | code=%s: %s", code, e)
            await query.edit_message_text(f"❌ خطا در تحلیل جامع ارز {code}.", reply_markup=kb_back_main())
        return

    if data == "menu_all":   # only admin refresh
        if not is_admin(user_id):
            await query.answer("⛔️ فقط ادمین.", show_alert=True); return
        await query.edit_message_text("⏳ در حال تحلیل همه ارزها (برای ادمین)...")
        try:
            mode = user_trading_mode.get(chat_id, "standard")
            plans = await asyncio.wait_for(refresh_all_plans(force_data=False, mode=mode), timeout=300)
        except asyncio.TimeoutError:
            await query.edit_message_text("⏰ تحلیل همه ارزها طول کشید.", reply_markup=kb_back_main()); return
        if not plans:
            text = "📋 فعلاً سیگنال نهایی نداریم."
        else:
            sorted_plans = sorted(plans.values(), key=lambda p: p.confidence, reverse=True)
            full_text = "📋 *نمایش پیشنهادات*\n\n" + "\n\n".join(format_main_signal(p, p.symbol, chat_id) for p in sorted_plans)
            chunks = split_long_message(full_text)
            new_ids = []
            await query.edit_message_text(chunks[0], parse_mode="Markdown"); new_ids.append(query.message.message_id)
            for chunk in chunks[1:]:
                m = await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")
                new_ids.append(m.message_id)
            set_interactive_screen(chat_id, new_ids)
            return

    if data == "admin_panel":
        if not is_admin(user_id):
            await query.answer("⛔️ فقط ادمین.", show_alert=True); return
        ok = sum(1 for c in COIN_CODES if cache.market_status.get(c, {}).get("status") == "SWAP OK")
        no_swap = sum(1 for c in COIN_CODES if cache.market_status.get(c, {}).get("status") == "NO SWAP")
        ticker_error = sum(1 for c in COIN_CODES if cache.market_status.get(c, {}).get("status") == "TICKER ERROR")
        await query.edit_message_text(
            rtl_lines(
                f"🛠️ *پنل مدیریت*\n{DIVIDER}\n🕒 {shamsi_now()}\n"
                f"👥 اعضای فعال: {len(subscribed_chat_ids)}\n"
                f"⚡ سیگنال‌های فعال: {len(last_plans)}\n"
                f"🪙 کل ارزها: {len(COIN_CODES)}\n"
                f"🟢 SWAP OK: {ok}\n⚪ NO SWAP: {no_swap}\n🟠 TICKER ERROR: {ticker_error}\n"
                f"📊 داده‌ها: 5m={len(cache.ohlcv.get('5m',{}))}, 15m={len(cache.ohlcv.get('15m',{}))}, 1h={len(cache.ohlcv.get('1h',{}))}, 4h={len(cache.ohlcv.get('4h',{}))}, 1d={len(cache.ohlcv.get('1d',{}))}"
            ),
            reply_markup=kb_admin_panel(), parse_mode="Markdown"
        )

    if data == "admin_compare":
        if not is_admin(user_id):
            await query.answer("⛔️ فقط ادمین.", show_alert=True); return
        text = "📊 *گزارش مقایسه‌ای حالت‌های معاملاتی*\n" + DIVIDER + "\n"
        for mode, config in MODE_CONFIGS.items():
            stats = compute_advanced_stats(signal_history, mode)
            text += (
                f"{config['label']}\n"
                f"تعداد سیگنال‌ها: {stats['total_trades']} | برد: {stats['wins']} | باخت: {stats['losses']} | نرخ برد: {stats['win_rate']:.1f}%\n"
                f"فاکتور سود: {stats['profit_factor']:.2f} | Expectancy: {stats['expectancy']:.2f} | MaxDD: {stats['max_drawdown']:.2f}\n"
                f"Sharpe: {stats['sharpe']:.2f} | میانگین اطمینان: {stats['avg_confidence']:.1f}%\n\n"
            )
        await query.edit_message_text(rtl_lines(text), reply_markup=kb_back_main(), parse_mode="Markdown")

# ---------- Auto report (event-driven) ----------
async def auto_report_loop(app):
    await asyncio.sleep(10)
    while True:
        try:
            if subscribed_chat_ids:
                await cache.update_prices(force=True)
                await cache.update_ohlcv(force=True)
                now = time.time()
                for chat_id in list(subscribed_chat_ids):
                    mode = user_trading_mode.get(chat_id, "standard")
                    interval = MODE_CONFIGS[mode]["check_interval"]
                    last_ts = last_check_time.get(chat_id, 0)
                    if now - last_ts < interval:
                        continue

                    favs = user_favorites.get(chat_id, set())
                    if not favs:
                        continue

                    current_signals = {}
                    for code in favs:
                        plan = await generate_trade_plan(code, mode)
                        if plan:
                            current_signals[code] = plan.direction

                    prev_signals = last_sent_signals.get(chat_id, {})

                    # New signals or direction change
                    for code, direction in current_signals.items():
                        prev = prev_signals.get(code)
                        if prev is None or prev["direction"] != direction:
                            plan = await generate_trade_plan(code, mode)
                            if plan:
                                main_text = format_main_signal(plan, code, chat_id)
                                await app.bot.send_message(chat_id=chat_id, text=main_text, reply_markup=kb_signal_details(code), parse_mode="Markdown")
                                active_signals.setdefault(chat_id, {})[code] = {"plan": plan, "stage": 0, "last_notified": 0}
                                prev_signals[code] = {"direction": direction, "timestamp": time.time()}

                    # Closed signals
                    for code in list(prev_signals.keys()):
                        if code not in current_signals:
                            await app.bot.send_message(chat_id=chat_id, text=f"🔴 سیگنال {code} بسته شد.")
                            del prev_signals[code]

                    last_sent_signals[chat_id] = prev_signals
                    last_check_time[chat_id] = now
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.exception("Auto loop failed | error=%s", e)
        await asyncio.sleep(60)

async def post_init(app):
    await app.bot.set_my_commands([
        BotCommand("start", "شروع ربات"),
        BotCommand("menu", "منوی اصلی"),
        BotCommand("status", "وضعیت سیستم"),
        BotCommand("dashboard", "داشبورد تحلیلی"),
        BotCommand("news", "رویدادهای پیش رو"),
        BotCommand("report", "گزارش دوره‌ای"),
        BotCommand("stop", "توقف ربات"),
    ])
    app.create_task(auto_report_loop(app))
    app.create_task(trailing_monitor_loop(app))
    app.create_task(news_monitor_loop(app))
    app.create_task(whale_monitor_loop(app))
    logger.info("Signal Bot V28 (KuCoin Text-Based) started")

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
    app.add_handler(CommandHandler("dashboard", dashboard))
    app.add_handler(CommandHandler("news", news))
    app.add_handler(CommandHandler("report", periodic_report_command))
    app.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
