"""
Telegram Signal Bot V59 - Institutional Grade with Intelligence Center
- کانال تلگرام + ارسال خودکار سیگنال‌ها
- دکمه دریافت سیگنال‌های فعال برای همه کاربران
- رفع Rate Limit و XMR
- سیگنال‌دهی متعادل برای تمام رژیم‌های بازار
"""

import asyncio
import json
import logging
import os
import time
import uuid
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
CRYPTOPANIC_API_KEY = os.getenv("CRYPTOPANIC_API_KEY", "")
CHANNEL_ID = os.getenv("CHANNEL_ID", "")

# ---------- لیست ارزها ----------
COIN_ICONS = {
    "AAVE": "AAVE", "ADA": "ADA", "ALGO": "ALGO", "APE": "APE",
    "APT": "APT", "AR": "AR", "ARB": "ARB", "ATOM": "ATOM",
    "AVAX": "AVAX", "BCH": "BCH", "BLUR": "BLUR", "BTC": "BTC",
    "COMP": "COMP", "DOGE": "DOGE", "DOT": "DOT", "EGLD": "EGLD",
    "ETC": "ETC", "ETH": "ETH", "FET": "FET", "FIL": "FIL",
    "FLOW": "FLOW", "GRT": "GRT", "ICP": "ICP",
    "INJ": "INJ", "KAS": "KAS", "KAVA": "KAVA", "KSM": "KSM",
    "LINK": "LINK", "LTC": "LTC", "LUNC": "LUNC", "MANA": "MANA",
    "MINA": "MINA", "NEAR": "NEAR", "NEO": "NEO", "OP": "OP",
    "POL": "POL", "RUNE": "RUNE", "SAND": "SAND", "SHIB": "SHIB",
    "SOL": "SOL", "STX": "STX", "SUI": "SUI", "TRX": "TRX",
    "UNI": "UNI", "VET": "VET", "XLM": "XLM", "XMR": "XMR",
    "XRP": "XRP",
}
COIN_CODES = sorted(list(COIN_ICONS.keys()))

TIMEFRAMES = ("5m", "15m", "1h", "4h", "1d")
TOP_SIGNALS_COUNT = 5
TELEGRAM_MSG_LIMIT = 3500
IRT_RATE_TTL_SECONDS = 60
COINS_GRID_COLUMNS = 4
AUTO_KEEP_LAST_N = 3
TRAILING_CHECK_SECONDS = 5 * 60
FEAR_GREED_TTL = 3600
EVENTS_CHECK_SECONDS = 6 * 3600
WHALE_CHECK_SECONDS = 30 * 60
WHALE_MIN_AMOUNT_BTC = 1000
NEWS_AUTO_DELETE_SECONDS = 3600
OPTIMIZATION_CHECK_SECONDS = 6 * 3600
MACRO_CHECK_SECONDS = 6 * 3600

PER_PAGE = 12
WEIGHT_TREND = 15
WEIGHT_MOMENTUM = 15
WEIGHT_VOLUME = 10
WEIGHT_VOLATILITY = 10
WEIGHT_HTF = 10
WEIGHT_SENTIMENT = 10
WEIGHT_ORDER_FLOW = 10
WEIGHT_BREADTH = 5
WEIGHT_SMART_VOL = 5
WEIGHT_COMP_TREND = 10

OHLCV_TTL_SECONDS = 180
PRICE_TTL_SECONDS = 30
FULL_REFRESH_TTL_SECONDS = 120
MAX_OHLCV_CONCURRENCY = 2
MAX_SIGNAL_CONCURRENCY = 4
MAX_PRICE_CONCURRENCY = 4
RLM = "\u200f"

DATA_DIR = os.getenv("DATA_DIR", "/data")
STATE_FILE = os.path.join(DATA_DIR, "state.json")

DIVIDER = "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"
BIG_DIVIDER = "═══════════════"
MENU_PROMPT = "👇 یکی از گزینه‌ها را انتخاب کن:"

# ---------- صرافی‌ها ----------
exchange_gateio = ccxt.gateio({
    "enableRateLimit": True,
    "options": {"defaultType": "spot"},
})

exchange_spot_kucoin = ccxt.kucoin({
    "enableRateLimit": True,
})

GATEIO_SYMBOL_MAP = {
    "AAVE": "AAVE/USDT", "ADA": "ADA/USDT", "ALGO": "ALGO/USDT",
    "APE": "APE/USDT", "APT": "APT/USDT", "AR": "AR/USDT",
    "ARB": "ARB/USDT", "ATOM": "ATOM/USDT", "AVAX": "AVAX/USDT",
    "BCH": "BCH/USDT", "BLUR": "BLUR/USDT", "BTC": "BTC/USDT",
    "COMP": "COMP/USDT", "DOGE": "DOGE/USDT", "DOT": "DOT/USDT",
    "EGLD": "EGLD/USDT", "ETC": "ETC/USDT", "ETH": "ETH/USDT",
    "FET": "FET/USDT", "FIL": "FIL/USDT", "FLOW": "FLOW/USDT",
    "GRT": "GRT/USDT", "ICP": "ICP/USDT",
    "INJ": "INJ/USDT", "KAS": "KAS/USDT", "KAVA": "KAVA/USDT",
    "KSM": "KSM/USDT", "LINK": "LINK/USDT", "LTC": "LTC/USDT",
    "LUNC": "LUNC/USDT", "MANA": "MANA/USDT", "MINA": "MINA/USDT",
    "NEAR": "NEAR/USDT", "NEO": "NEO/USDT", "OP": "OP/USDT",
    "POL": "POL/USDT", "RUNE": "RUNE/USDT", "SAND": "SAND/USDT",
    "SHIB": "SHIB/USDT", "SOL": "SOL/USDT", "STX": "STX/USDT",
    "SUI": "SUI/USDT", "TRX": "TRX/USDT",
    "UNI": "UNI/USDT", "VET": "VET/USDT", "XLM": "XLM/USDT",
    "XRP": "XRP/USDT",
}

# ========== تنظیمات سیگنال‌دهی متعادل ==========
MIN_SIGNAL_CONFIDENCE = 40
MIN_DIRECTION_GAP = 6
ENTRY_WEIGHTS = [0.5, 0.3, 0.2]

MODE_CONFIGS = {
    "fast": {
        "label": "سریع ⚡",
        "main_tf": "5m",
        "confirm_tfs": ["15m", "1h"],
        "entry_ladder_atr": [0.0, 0.2, 0.4],
        "tp_multipliers": [0.4, 0.8, 1.2],
        "sl_atr_mult": 0.8,
        "max_leverage": 10,
        "min_rr": 0.50,
        "adx_min": 5,
        "min_confirmations": 3,
        "check_interval": 5 * 60,
    },
    "semi_fast": {
        "label": "نیمه‌سریع 🔥",
        "main_tf": "15m",
        "confirm_tfs": ["1h", "4h"],
        "entry_ladder_atr": [0.0, 0.3, 0.6],
        "tp_multipliers": [0.6, 1.2, 1.8],
        "sl_atr_mult": 1.0,
        "max_leverage": 7,
        "min_rr": 0.80,
        "adx_min": 7,
        "min_confirmations": 4,
        "check_interval": 10 * 60,
    },
    "standard": {
        "label": "استاندارد 📊",
        "main_tf": "1h",
        "confirm_tfs": ["4h", "1d"],
        "entry_ladder_atr": [0.0, 0.4, 0.8],
        "tp_multipliers": [0.8, 1.5, 2.5],
        "sl_atr_mult": 1.2,
        "max_leverage": 5,
        "min_rr": 1.20,
        "adx_min": 8,
        "min_confirmations": 5,
        "check_interval": 30 * 60,
    },
    "conservative": {
        "label": "محافظه‌کار 🛡️",
        "main_tf": "4h",
        "confirm_tfs": ["1d", "1d"],
        "entry_ladder_atr": [0.0, 0.6, 1.2],
        "tp_multipliers": [1.5, 2.5, 4.0],
        "sl_atr_mult": 2.0,
        "max_leverage": 3,
        "min_rr": 1.50,
        "adx_min": 10,
        "min_confirmations": 6,
        "check_interval": 60 * 60,
    },
}

LAYER_WEIGHTS = {
    "structure": 15,
    "mtf": 15,
    "momentum": 15,
    "volume": 10,
    "sentiment": 10,
    "trend": 10,
    "order_flow": 10,
    "breadth": 5,
    "smart_vol": 5,
    "comp_trend": 5,
}

LAYER_NAMES = {
    "structure": "ساختار بازار",
    "mtf": "هم‌گرایی تایم‌فریم",
    "momentum": "مومنتوم",
    "volume": "حجم",
    "sentiment": "احساسات بازار",
    "trend": "روند",
    "order_flow": "جریان سفارشات",
    "breadth": "تنوع بازار",
    "smart_vol": "نوسان‌پذیری",
    "comp_trend": "قدرت روند",
}

@dataclass
class TradePlan:
    symbol: str
    direction: str
    trend: str
    rsi: float
    current_price: float = 0.0
    confidence: float = 0.0
    win_rate_estimate: float = 0.0
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
    layer_results: dict = field(default_factory=dict)
    signal_grade: str = ""
    adx_at_time: float = 0.0
    rsi_at_time: float = 0.0
    market_condition: str = ""
    rr: float = 0.0

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
        self.symbol_sources = {}
        self.market_status = {
            code: {"status": "NO SWAP", "symbol": None, "error": None, "source": None}
            for code in COIN_CODES
        }
        self.last_price_update = 0.0
        self.last_full_ohlcv_update = 0.0
        self._sem = asyncio.Semaphore(MAX_OHLCV_CONCURRENCY)
        self._price_sem = asyncio.Semaphore(MAX_PRICE_CONCURRENCY)
        self._update_lock = asyncio.Lock()
        self._symbol_locks = {}
        self._breadth_cache = {"value": None, "ts": 0.0}
        self._breadth_sample_count = 0
        self._sentiment_cache = {}
        self._macro_cache = {"data": {}, "ts": 0.0}
        self._load_markets()

    def _symbol_lock(self, code):
        if code not in self._symbol_locks:
            self._symbol_locks[code] = asyncio.Lock()
        return self._symbol_locks[code]

    def _load_markets(self):
        try:
            gateio_markets = exchange_gateio.load_markets()
            kucoin_markets = None
            selected = {}
            sources = {}
            for code in COIN_CODES:
                found = False
                gateio_symbol = GATEIO_SYMBOL_MAP.get(code)
                if gateio_symbol and gateio_symbol in gateio_markets:
                    market = gateio_markets[gateio_symbol]
                    if market.get("active") is not False and market.get("type") == "spot":
                        selected[code] = gateio_symbol
                        sources[code] = "gateio"
                        self.market_status[code] = {"status": "SWAP OK", "symbol": gateio_symbol, "error": None, "source": "gateio"}
                        found = True
                if not found:
                    if kucoin_markets is None:
                        try:
                            kucoin_markets = exchange_spot_kucoin.load_markets()
                        except Exception as e:
                            logger.warning("KuCoin load markets failed: %s", e)
                            kucoin_markets = {}
                    kucoin_symbol = f"{code}/USDT"
                    if kucoin_symbol in kucoin_markets:
                        market = kucoin_markets[kucoin_symbol]
                        if market.get("active") is not False and market.get("type") == "spot":
                            selected[code] = kucoin_symbol
                            sources[code] = "kucoin"
                            self.market_status[code] = {"status": "SWAP OK", "symbol": kucoin_symbol, "error": None, "source": "kucoin"}
                            found = True
                if not found:
                    logger.warning(f"ارز {code} در Gate.io و KuCoin یافت نشد.")
                    selected[code] = code
                    sources[code] = "unknown"
                    self.market_status[code] = {"status": "NO SWAP", "symbol": code, "error": "Not found", "source": "unknown"}
            self.exchange_symbols = selected
            self.symbol_sources = sources
            self.valid_codes = [code for code in COIN_CODES if sources.get(code) != "unknown"]
            logger.info("Markets loaded: %s/%s from Gate.io + KuCoin", len(self.valid_codes), len(COIN_CODES))
        except Exception as e:
            logger.exception("load_markets failed: %s", e)

    def symbol_for_code(self, code) -> Optional[str]:
        return self.exchange_symbols.get(code)

    def source_for_code(self, code) -> Optional[str]:
        return self.symbol_sources.get(code, "unknown")

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

    async def update_macro_data(self):
        try:
            url = "https://api.coingecko.com/api/v3/global"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.json()["data"]
            self._macro_cache = {
                "data": {
                    "btc_dominance": float(data.get("market_cap_percentage", {}).get("btc", 50)),
                    "total_market_cap": float(data.get("total_market_cap", {}).get("usd", 0)),
                    "total_volume": float(data.get("total_volume", {}).get("usd", 0)),
                },
                "ts": time.time()
            }
            logger.info("Macro data updated: BTC dominance %.1f%%", self._macro_cache["data"]["btc_dominance"])
        except Exception as e:
            logger.warning(f"Macro data fetch failed: {e}")

    def get_macro_data(self):
        return self._macro_cache["data"] if self._macro_cache["data"] else None

    def _get_coingecko_prices(self, codes):
        prices = {}
        try:
            ids_map = {
                "AAVE": "aave", "ADA": "cardano", "ALGO": "algorand", "APE": "apecoin",
                "APT": "aptos", "AR": "arweave", "ARB": "arbitrum", "ATOM": "cosmos",
                "AVAX": "avalanche-2", "BCH": "bitcoin-cash", "BLUR": "blur", "BTC": "bitcoin",
                "COMP": "compound-governance-token", "DOGE": "dogecoin", "DOT": "polkadot",
                "EGLD": "elrond-erd-2", "ETC": "ethereum-classic", "ETH": "ethereum",
                "FET": "fetch-ai", "FIL": "filecoin", "FLOW": "flow",
                "GRT": "the-graph", "ICP": "internet-computer", "INJ": "injective-protocol",
                "KAS": "kaspa", "KAVA": "kava", "KSM": "kusama", "LINK": "chainlink",
                "LTC": "litecoin", "LUNC": "terra-luna-classic", "MANA": "decentraland",
                "MINA": "mina-protocol", "NEAR": "near", "NEO": "neo", "OP": "optimism",
                "POL": "polygon-ecosystem-token", "RUNE": "thorchain", "SAND": "the-sandbox",
                "SHIB": "shiba-inu", "SOL": "solana", "STX": "blockstack", "SUI": "sui",
                "TRX": "tron", "UNI": "uniswap",
                "VET": "vechain", "XLM": "stellar", "XMR": "monero", "XRP": "ripple",
            }
            ids = [ids_map[code] for code in codes if code in ids_map]
            if not ids:
                return prices
            url = "https://api.coingecko.com/api/v3/simple/price"
            params = {"ids": ",".join(ids), "vs_currencies": "usd"}
            r = requests.get(url, params=params, timeout=10)
            r.raise_for_status()
            data = r.json()
            reverse_map = {v: k for k, v in ids_map.items()}
            for cg_id, info in data.items():
                if cg_id in reverse_map:
                    code = reverse_map[cg_id]
                    price = info.get("usd")
                    if price:
                        prices[code] = float(price)
        except Exception as e:
            logger.warning("CoinGecko fetch failed: %s", e)
        return prices

    async def update_prices(self, force=False, codes=None):
        target_codes = codes if codes is not None else COIN_CODES
        now = time.time()
        if not force and self.prices and self.last_price_update and now - self.last_price_update < PRICE_TTL_SECONDS:
            return self.prices

        new_prices = {}
        price_sources.clear()

        gateio_codes = [code for code in target_codes if GATEIO_SYMBOL_MAP.get(code)]
        if gateio_codes:
            try:
                # فقط سمبل‌هایی که واقعاً در بازارهای Gate.io موجودند
                valid_gateio_codes = [c for c in gateio_codes if GATEIO_SYMBOL_MAP[c] in exchange_gateio.markets]
                symbols = [GATEIO_SYMBOL_MAP[c] for c in valid_gateio_codes]
                if symbols:
                    tickers = await asyncio.to_thread(exchange_gateio.fetch_tickers, symbols)
                    for code in valid_gateio_codes:
                        sym = GATEIO_SYMBOL_MAP.get(code)
                        if sym in tickers:
                            ticker = tickers[sym]
                            price = ticker.get("last") or ticker.get("close") or ticker.get("bid") or ticker.get("ask")
                            if price and price > 0:
                                new_prices[code] = float(price)
                                price_sources[code] = "G"
            except Exception as e:
                logger.warning(f"Gate.io fetch_tickers failed: {e}")

        missing = [code for code in target_codes if code not in new_prices]
        if missing:
            try:
                symbols = [f"{code}/USDT" for code in missing]
                tickers = await asyncio.to_thread(exchange_spot_kucoin.fetch_tickers, symbols)
                for code in missing:
                    sym = f"{code}/USDT"
                    if sym in tickers:
                        ticker = tickers[sym]
                        price = ticker.get("last") or ticker.get("close") or ticker.get("bid") or ticker.get("ask")
                        if price and price > 0:
                            new_prices[code] = float(price)
                            price_sources[code] = "K"
            except Exception as e:
                logger.warning(f"KuCoin fetch_tickers failed: {e}")

        still_missing = [code for code in target_codes if code not in new_prices]
        if still_missing:
            try:
                gecko_prices = await asyncio.to_thread(self._get_coingecko_prices, still_missing)
                for code, price in gecko_prices.items():
                    if price and price > 0:
                        new_prices[code] = price
                        price_sources[code] = "C"
            except Exception as e:
                logger.warning(f"CoinGecko fetch failed: {e}")

        for code in target_codes:
            if code in new_prices:
                self.prices[code] = new_prices[code]
        self.last_price_update = time.time()
        logger.info("Prices loaded: %s/%s", len(self.prices), len(COIN_CODES))
        return self.prices

    def _get_market_breadth(self):
        now = time.time()
        if self._breadth_cache["value"] is not None and now - self._breadth_cache["ts"] < 60:
            return self._breadth_cache["value"]
        count_above = 0
        total = 0
        for code in self.valid_codes:
            df = self.ohlcv.get("1h", {}).get(code)
            if df is not None and len(df) > 20:
                close = df["close"]
                ema20 = EMAIndicator(close, window=20).ema_indicator()
                if len(ema20) > 0 and pd.notna(ema20.iloc[-1]):
                    if close.iloc[-1] > ema20.iloc[-1]:
                        count_above += 1
                    total += 1
        breadth = count_above / total * 100 if total > 0 else 50
        self._breadth_sample_count = total
        self._breadth_cache = {"value": breadth, "ts": now}
        return breadth

    async def _get_order_flow(self, code):
        try:
            symbol = self.symbol_for_code(code)
            if not symbol:
                return 0.0
            source = self.source_for_code(code)
            if source == "gateio":
                order_book = await asyncio.to_thread(exchange_gateio.fetch_order_book, symbol, limit=5)
            elif source == "kucoin":
                order_book = await asyncio.to_thread(exchange_spot_kucoin.fetch_order_book, symbol, limit=5)
            else:
                return 0.0
            bids_volume = sum(bid[1] for bid in order_book["bids"][:5])
            asks_volume = sum(ask[1] for ask in order_book["asks"][:5])
            if asks_volume == 0:
                return 0.0
            ratio = bids_volume / asks_volume
            return min(2.0, ratio)
        except Exception as e:
            logger.debug(f"Order flow failed for {code}: {e}")
            return 0.0

    async def _calculate_sentiment_score(self, code, ind):
        price_change_1h = 0
        price_change_4h = 0
        price_change_24h = 0
        df_1h = self.ohlcv.get("1h", {}).get(code)
        df_4h = self.ohlcv.get("4h", {}).get(code)
        df_1d = self.ohlcv.get("1d", {}).get(code)
        if df_1h is not None and len(df_1h) > 2:
            price_change_1h = (df_1h["close"].iloc[-1] / df_1h["close"].iloc[-2] - 1) * 100
        if df_4h is not None and len(df_4h) > 2:
            price_change_4h = (df_4h["close"].iloc[-1] / df_4h["close"].iloc[-2] - 1) * 100
        if df_1d is not None and len(df_1d) > 2:
            price_change_24h = (df_1d["close"].iloc[-1] / df_1d["close"].iloc[-2] - 1) * 100
        weighted_price_change = (price_change_1h * 0.5) + (price_change_4h * 0.3) + (price_change_24h * 0.2)
        price_score = max(-1, min(1, weighted_price_change / 5))
        volume_ratio = ind.get("volume_ratio", 1.0)
        if volume_ratio > 2.0:
            volume_score = 1.0
        elif volume_ratio > 1.5:
            volume_score = 0.5
        elif volume_ratio < 0.5:
            volume_score = -0.5
        else:
            volume_score = 0.0
        fg_value, _ = await get_fear_greed()
        if fg_value is not None:
            fg_score = (fg_value - 50) / 50
            fg_score = max(-1, min(1, fg_score))
        else:
            fg_score = 0.0
        sentiment_score = (price_score * 0.4) + (volume_score * 0.4) + (fg_score * 0.2)
        return max(-1, min(1, sentiment_score))

    def _get_smart_volatility(self, ind):
        bb_percent = ind.get("bb_percent", 0.5)
        if bb_percent > 0.8:
            return 0.7
        elif bb_percent < 0.2:
            return -0.7
        else:
            return 0.0

    def _get_complementary_trend(self, ind):
        plus_di = ind.get("plus_di", 0)
        minus_di = ind.get("minus_di", 0)
        diff = plus_di - minus_di
        if diff > 15:
            return 0.7
        elif diff < -15:
            return -0.7
        else:
            return 0.0

    async def _fetch_ohlcv_symbol(self, code, timeframe, limit=500):
        symbol = self.symbol_for_code(code)
        if not symbol:
            return None
        source = self.source_for_code(code)

        exchanges = []
        if source == "gateio":
            exchanges.append((exchange_gateio, "gateio", symbol))
            exchanges.append((exchange_spot_kucoin, "kucoin", f"{code}/USDT"))
        elif source == "kucoin":
            exchanges.append((exchange_spot_kucoin, "kucoin", f"{code}/USDT"))
        else:
            return None

        async with self._sem:
            for ex, name, sym in exchanges:
                for attempt in range(3):
                    try:
                        raw = await asyncio.to_thread(ex.fetch_ohlcv, sym, timeframe, None, limit)
                        df = self._to_dataframe(raw)
                        if df is None or len(df) < 10:
                            logger.debug(f"OHLCV {code} {timeframe} from {name}: insufficient rows {len(df) if df is not None else 0}")
                            await asyncio.sleep(2 ** attempt)
                            continue
                        logger.debug(f"OHLCV {code} {timeframe} fetched from {name}")
                        return df
                    except Exception as e:
                        wait = 2 ** attempt
                        logger.warning(f"OHLCV {code} {timeframe} from {name} attempt {attempt} failed: {e}, wait {wait}s")
                        await asyncio.sleep(wait)
                logger.warning(f"OHLCV {code} {timeframe} failed from {name}")
            logger.warning(f"OHLCV {code} {timeframe} failed from all sources")
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
            target_codes = list(codes if codes is not None else self.valid_codes)
            tasks = [self.ensure_symbol_data(code, TIMEFRAMES, force=force) for code in target_codes]
            await asyncio.gather(*tasks)
            self.last_full_ohlcv_update = time.time()
            logger.info("OHLCV refresh complete: %s", {tf: len(self.ohlcv.get(tf, {})) for tf in TIMEFRAMES})

    async def get_indicators(self, code, mode="standard"):
        config = MODE_CONFIGS.get(mode, MODE_CONFIGS["standard"])
        main_tf = config["main_tf"]
        confirm_tfs = config["confirm_tfs"]
        needed = [main_tf] + confirm_tfs
        ok = await self.ensure_symbol_data(code, needed)
        if not ok:
            ok = await self.ensure_symbol_data(code, needed, force=True)
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
                "price": price, "price_prev": price_prev,
                "ema20": ema20_value, "ema50": ema50_value, "ema200": ema200_value,
                "price_above_ema20": price > ema20_value,
                "price_above_ema50": price > ema50_value,
                "price_above_ema200": price > ema200_value,
                "price_ema50_pct": price_ema50_pct,
                "price_ema200_pct": price_ema200_pct,
                "ema20_above_ema50": ema20_value > ema50_value,
                "ema20_bullish_cross": bullish_cross,
                "ema20_bearish_cross": bearish_cross,
                "rsi": float(rsi.iloc[-1]), "rsi_prev": rsi_prev,
                "stoch_k": float(stoch_k.iloc[-1]),
                "macd": float(macd_line.iloc[-1]), "macd_signal": float(macd_signal.iloc[-1]),
                "macd_hist": float(macd_hist.iloc[-1]), "macd_hist_prev": macd_hist_prev,
                "roc": float(roc.iloc[-1]), "cci": float(cci.iloc[-1]), "williams_r": float(williams.iloc[-1]),
                "adx": float(adx.iloc[-1]), "plus_di": float(plus_di.iloc[-1]), "minus_di": float(minus_di.iloc[-1]),
                "atr": atr_value, "atr_pct": atr_pct,
                "bb_percent": float(bb_percent.iloc[-1]), "bb_width": float(bb_width.iloc[-1]),
                "volume_ratio": vr, "volume_spike": volume_spike, "volume_trend_up": volume_trend_up,
                "vwap": float(vwap.iloc[-1]), "price_above_vwap": price > float(vwap.iloc[-1]),
                "confirm_up_count": confirm_up, "confirm_down_count": confirm_down,
                "higher_tf_trend_up": confirm_up >= len(confirm_dfs) if confirm_dfs else None,
                "higher_tf_trend_down": confirm_down >= len(confirm_dfs) if confirm_dfs else None,
                "trend_label": "صعودی 📈" if price > ema200_value else "نزولی 📉",
                "is_trending": bool(adx.iloc[-1] >= config["adx_min"]),
                "support": support, "resistance": resistance,
                "breakout_up": breakout_up, "breakout_down": breakout_down,
                "bullish_div": rsi_bullish_div, "bearish_div": rsi_bearish_div,
                "macd_bullish_div": macd_bullish_div, "macd_bearish_div": macd_bearish_div,
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

# ---------- متغیرهای سراسری ----------
app = None
last_plans = {}
subscribed_chat_ids = set()
user_currency = {}
user_trading_mode = {}
user_favorites = {}
user_role = {}
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
news_history: List[Dict] = []
news_message_ids: Dict[int, List[int]] = {}
suggestion_history: List[Dict] = []

channel_signal_messages: Dict[str, int] = {}

last_check_time = {}
last_sent_signals = {}
price_sources = {}

# ---------- توابع کمکی ----------
def is_allowed(user_id):
    if user_id in ALWAYS_ALLOWED_USER_IDS or user_id in ADMIN_USER_IDS:
        return True
    if not ALLOWED_USER_IDS:
        return True
    return user_id in ALLOWED_USER_IDS

def is_admin(user_id):
    return user_id in ADMIN_USER_IDS

def is_admin_role(chat_id):
    return user_role.get(chat_id, "user") == "admin"

async def guard(update):
    user = update.effective_user
    if user and not is_allowed(user.id):
        if update.message:
            await update.message.reply_text("⛔️ این ربات خصوصی است و شما دسترسی ندارید.")
        elif update.callback_query:
            await update.callback_query.answer("⛔️ دسترسی ندارید.", show_alert=True)
        return False
    return True

def add_news_alert(text: str, importance: str = "medium", impact: str = "", details: dict = None, auto_delete: bool = True):
    global news_history
    entry = {
        "time": shamsi_now(),
        "text": text,
        "importance": importance,
        "impact": impact,
        "details": details or {},
        "auto_delete": auto_delete,
        "created_at": time.time()
    }
    news_history.append(entry)
    importance_order = {"high": 0, "medium": 1, "low": 2}
    news_history.sort(key=lambda x: (importance_order.get(x.get("importance", "low"), 2), x.get("time", "")))
    if len(news_history) > 20:
        news_history.pop(0)
    save_state()

def get_win_rate_estimate():
    if not signal_history:
        return 50.0
    wins = sum(1 for s in signal_history if s["status"].startswith("tp"))
    total = len(signal_history)
    return (wins / total * 100) if total > 0 else 50.0

# ---------- نرخ تومان ----------
def fetch_irt_rate_wallex():
    try:
        r = requests.get("https://api.wallex.ir/v1/markets", timeout=8)
        r.raise_for_status()
        data = r.json()["result"]["symbols"]
        if "USDTTMN" in data:
            return float(data["USDTTMN"]["stats"]["lastPrice"])
    except Exception as e:
        logger.warning("Wallex rate fetch failed: %s", e)
    return None

def get_irt_rate():
    now = time.time()
    if _irt_rate_cache["value"] is not None and now - _irt_rate_cache["ts"] < IRT_RATE_TTL_SECONDS:
        return _irt_rate_cache["value"]
    try:
        rate = fetch_irt_rate_wallex()
        if rate and rate > 0:
            _irt_rate_cache.update(value=rate, ts=now, source="wallex")
            return rate
    except Exception as e:
        logger.warning("IRT rate failed: %s", e)
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
    if confidence >= 90: return "فوق‌العاده قوی 🔥🔥"
    if confidence >= 85: return "خیلی قوی 🔥"
    if confidence >= 80: return "قوی ⚡"
    if confidence >= 75: return "نسبتاً قوی ✨"
    if confidence >= 70: return "متوسط رو به بالا 💫"
    if confidence >= 65: return "متوسط 🌤"
    if confidence >= 60: return "قابل بررسی 🌥"
    return "ضعیف 💤"

def signal_grade(confidence):
    if confidence >= 85: return "A (بسیار قوی)"
    if confidence >= 75: return "B (قوی)"
    if confidence >= 65: return "C (متوسط)"
    return "D (ضعیف)"

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

# ---------- اخبار مهم کریپتو ----------
async def fetch_cryptopanic_news():
    if not CRYPTOPANIC_API_KEY:
        return []
    try:
        url = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTOPANIC_API_KEY}&filter=important"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        data = r.json()
        news_list = []
        for item in data.get("results", [])[:10]:
            title = item.get("title", "")
            if not title:
                continue
            tags = [tag.get("title", "") for tag in item.get("tags", [])]
            impact = "خنثی"
            if "bullish" in str(tags).lower() or "positive" in str(tags).lower():
                impact = "صعودی 📈"
            elif "bearish" in str(tags).lower() or "negative" in str(tags).lower():
                impact = "نزولی 📉"
            if "important" in str(tags).lower() or "high" in str(tags).lower():
                news_list.append({
                    "title": title[:100],
                    "impact": impact,
                    "source": "CryptoPanic",
                    "url": item.get("url", ""),
                    "timestamp": time.time()
                })
        return news_list
    except Exception as e:
        logger.warning(f"CryptoPanic fetch failed: {e}")
        return []

# ---------- اخبار نهنگ‌ها ----------
def fetch_whale_alerts():
    try:
        if WHALE_ALERT_API_KEY:
            url = f"https://api.whale-alert.io/v1/transactions?api_key={WHALE_ALERT_API_KEY}&min_value={WHALE_MIN_AMOUNT_BTC * 1000000}&limit=10"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.json().get("transactions", [])
            alerts = []
            for tx in data:
                amount_btc = float(tx.get("amount", 0))
                symbol = tx.get("symbol", "BTC")
                from_address = tx.get("from", {}).get("address", "")
                to_address = tx.get("to", {}).get("address", "")
                from_owner = tx.get("from", {}).get("owner_type", "")
                to_owner = tx.get("to", {}).get("owner_type", "")
                exchange_keywords = ["exchange", "wallet", "binance", "coinbase", "kraken", "okx", "bybit"]
                from_is_exchange = any(kw in from_owner.lower() for kw in exchange_keywords) if from_owner else False
                to_is_exchange = any(kw in to_owner.lower() for kw in exchange_keywords) if to_owner else False
                flow_type = "unknown"
                if from_is_exchange and not to_is_exchange:
                    flow_type = "خروج از صرافی (احتمال فروش)"
                elif not from_is_exchange and to_is_exchange:
                    flow_type = "ورود به صرافی (احتمال فروش)"
                elif from_is_exchange and to_is_exchange:
                    flow_type = "انتقال بین صرافی‌ها"
                else:
                    flow_type = "انتقال بین کیف‌پول‌ها"
                impact = "خنثی"
                if flow_type == "خروج از صرافی" and amount_btc > 2000:
                    impact = "نزولی 📉 (احتمال فروش)"
                elif flow_type == "ورود به صرافی" and amount_btc > 2000:
                    impact = "نزولی 📉 (احتمال فروش)"
                elif amount_btc > 5000:
                    impact = "صعودی 📈 (انباشت نهنگ)"
                alerts.append({
                    "amount_btc": amount_btc,
                    "symbol": symbol,
                    "timestamp": time.time(),
                    "from_address": from_address[:10] + "...",
                    "to_address": to_address[:10] + "...",
                    "from_owner": from_owner or "ناشناس",
                    "to_owner": to_owner or "ناشناس",
                    "flow_type": flow_type,
                    "impact": impact,
                    "value_usd": amount_btc * cache.prices.get("BTC", 0)
                })
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
                    alerts.append({
                        "amount_btc": total_out,
                        "symbol": "BTC",
                        "timestamp": time.time(),
                        "from_address": "مشخص نیست",
                        "to_address": "مشخص نیست",
                        "from_owner": "ناشناس",
                        "to_owner": "ناشناس",
                        "flow_type": "نامشخص",
                        "impact": "مشخص نیست",
                        "value_usd": total_out * cache.prices.get("BTC", 0)
                    })
            return alerts[:5]
    except Exception as e:
        logger.warning("Whale alert fetch failed: %s", e)
        return []

async def fetch_important_news():
    all_news = []
    whale_alerts = fetch_whale_alerts()
    for alert in whale_alerts:
        if "نزولی" in alert["impact"] or "صعودی" in alert["impact"]:
            text = (
                f"🐋 *حرکت نهنگ بزرگ*\n"
                f"💰 مقدار: **{alert['amount_btc']:,.0f} {alert['symbol']}** (~{alert['value_usd']:,.0f} دلار)\n"
                f"📊 نوع تراکنش: {alert['flow_type']}\n"
                f"📈 تأثیر: {alert['impact']}"
            )
            all_news.append({
                "text": text,
                "importance": "high",
                "impact": alert["impact"],
                "source": "whale",
                "timestamp": alert["timestamp"]
            })
    crypto_news = await fetch_cryptopanic_news()
    for item in crypto_news:
        text = f"📰 *{item['title']}*\n📈 تأثیر: {item['impact']}\n📌 منبع: {item['source']}"
        all_news.append({
            "text": text,
            "importance": "high",
            "impact": item["impact"],
            "source": "crypto",
            "timestamp": item["timestamp"]
        })
    return all_news

# ---------- سیستم یادگیری و بهینه‌سازی ----------
def analyze_performance():
    if len(signal_history) < 10:
        return None
    closed = [s for s in signal_history if s["status"] in ["tp1_hit", "tp2_hit", "tp3_hit", "sl_hit"]]
    if len(closed) < 5:
        return None
    wins = [s for s in closed if s["status"].startswith("tp")]
    losses = [s for s in closed if s["status"] == "sl_hit"]
    win_rate = len(wins) / len(closed) * 100 if closed else 0
    mode_performance = {}
    for mode in MODE_CONFIGS.keys():
        mode_signals = [s for s in closed if s.get("mode") == mode]
        if mode_signals:
            mode_wins = [s for s in mode_signals if s["status"].startswith("tp")]
            mode_performance[mode] = {
                "count": len(mode_signals),
                "win_rate": len(mode_wins) / len(mode_signals) * 100 if mode_signals else 0
            }
    best_mode = max(mode_performance, key=lambda x: mode_performance[x]["win_rate"]) if mode_performance else "standard"
    rr_values = [s.get("rr", 0) for s in closed if "rr" in s]
    avg_rr = sum(rr_values) / len(rr_values) if rr_values else 0
    return {
        "win_rate": win_rate,
        "best_mode": best_mode,
        "avg_rr": avg_rr,
        "total_signals": len(closed),
        "mode_performance": mode_performance
    }

def generate_optimization_suggestions(analysis):
    if not analysis or analysis["total_signals"] < 10:
        return []
    suggestions = []
    if analysis["win_rate"] < 40:
        suggestions.append({
            "parameter": "min_rr",
            "mode": "standard",
            "current": MODE_CONFIGS["standard"]["min_rr"],
            "suggested": MODE_CONFIGS["standard"]["min_rr"] - 0.02,
            "reason": f"نرخ برد پایین است ({analysis['win_rate']:.1f}%)، کاهش RR می‌تواند سیگنال‌های بیشتری تولید کند."
        })
    elif analysis["win_rate"] > 70:
        suggestions.append({
            "parameter": "min_rr",
            "mode": "standard",
            "current": MODE_CONFIGS["standard"]["min_rr"],
            "suggested": MODE_CONFIGS["standard"]["min_rr"] + 0.02,
            "reason": f"نرخ برد بالا است ({analysis['win_rate']:.1f}%)، افزایش RR می‌تواند کیفیت سیگنال‌ها را بهبود بخشد."
        })
    if analysis["best_mode"] != "standard":
        suggestions.append({
            "parameter": "mode",
            "mode": analysis["best_mode"],
            "current": "standard",
            "suggested": analysis["best_mode"],
            "reason": f"حالت {MODE_CONFIGS[analysis['best_mode']]['label']} عملکرد بهتری دارد (نرخ برد {analysis['mode_performance'][analysis['best_mode']]['win_rate']:.1f}%)."
        })
    return suggestions

async def optimization_loop(app):
    await asyncio.sleep(60)
    while True:
        try:
            analysis = analyze_performance()
            if analysis:
                suggestions = generate_optimization_suggestions(analysis)
                if suggestions:
                    entry = {
                        "id": f"sug_{int(time.time())}",
                        "timestamp": time.time(),
                        "analysis": analysis,
                        "suggestions": suggestions,
                        "status": "pending",
                        "expires_at": time.time() + 86400
                    }
                    suggestion_history.append(entry)
                    if len(suggestion_history) > 20:
                        suggestion_history.pop(0)
                    save_state()
                    for admin_id in ADMIN_USER_IDS:
                        try:
                            text = (
                                f"🧠 *پیشنهاد بهینه‌سازی تنظیمات*\n"
                                f"{DIVIDER}\n"
                                f"📊 تحلیل {analysis['total_signals']} سیگنال اخیر:\n"
                                f"• نرخ برد: {analysis['win_rate']:.1f}%\n"
                                f"• میانگین RR: {analysis['avg_rr']:.2f}\n"
                                f"• بهترین حالت: {MODE_CONFIGS[analysis['best_mode']]['label']}\n"
                                f"{DIVIDER}\n"
                                f"💡 *پیشنهادات:*\n"
                            )
                            for sug in suggestions[:2]:
                                if sug["parameter"] == "mode":
                                    text += f"• تغییر حالت به {MODE_CONFIGS[sug['suggested']]['label']}\n"
                                else:
                                    text += f"• {sug['parameter']}: {sug['current']} → {sug['suggested']}\n"
                                text += f"  📌 {sug['reason']}\n"
                            text += f"\n⏳ اعتبار پیشنهاد: ۲۴ ساعت"
                            await app.bot.send_message(
                                chat_id=admin_id,
                                text=text,
                                reply_markup=kb_suggestion_actions(entry["id"]),
                                parse_mode="Markdown"
                            )
                        except Exception as e:
                            logger.warning(f"Failed to send suggestion to admin {admin_id}: {e}")
        except Exception as e:
            logger.exception(f"Optimization loop error: {e}")
        await asyncio.sleep(OPTIMIZATION_CHECK_SECONDS)

def kb_suggestion_actions(suggestion_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ اعمال تغییرات", callback_data=f"apply_suggestion_{suggestion_id}")],
        [InlineKeyboardButton("❌ رد پیشنهادات", callback_data=f"reject_suggestion_{suggestion_id}")],
        [InlineKeyboardButton("📊 مشاهده جزئیات", callback_data=f"details_suggestion_{suggestion_id}")],
    ])

async def handle_suggestion_action(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    suggestion_id = data.split("_", 2)[2]
    target = None
    for sug in suggestion_history:
        if sug["id"] == suggestion_id:
            target = sug
            break
    if not target:
        await query.edit_message_text("❌ پیشنهاد مورد نظر یافت نشد.", reply_markup=kb_back_main())
        return
    if target["status"] != "pending":
        await query.edit_message_text(f"⏳ این پیشنهاد قبلاً {target['status']} شده است.", reply_markup=kb_back_main())
        return
    if data.startswith("apply_suggestion_"):
        for sug in target["suggestions"]:
            if sug["parameter"] == "mode":
                pass
            elif sug["parameter"] == "min_rr":
                MODE_CONFIGS[sug["mode"]]["min_rr"] = sug["suggested"]
            elif sug["parameter"] == "min_confirmations":
                MODE_CONFIGS[sug["mode"]]["min_confirmations"] = sug["suggested"]
        target["status"] = "applied"
        target["applied_at"] = time.time()
        target["result"] = "تنظیمات با موفقیت اعمال شد."
        save_state()
        await query.edit_message_text(
            "✅ *تنظیمات با موفقیت به‌روزرسانی شد.*\n\n"
            f"پیشنهادات اعمال‌شده:\n" + "\n".join([
                f"• {sug['parameter']}: {sug['current']} → {sug['suggested']}"
                for sug in target["suggestions"]
            ]),
            reply_markup=kb_back_to_optimization(),
            parse_mode="Markdown"
        )
    elif data.startswith("reject_suggestion_"):
        target["status"] = "rejected"
        target["rejected_at"] = time.time()
        save_state()
        await query.edit_message_text(
            "❌ *پیشنهادات رد شد.*\n\nتنظیمات فعلی حفظ شد.",
            reply_markup=kb_back_to_optimization(),
            parse_mode="Markdown"
        )
    elif data.startswith("details_suggestion_"):
        text = f"📊 *جزئیات پیشنهاد*\n{DIVIDER}\n"
        text += f"📅 تاریخ: {shamsi_date(datetime.fromtimestamp(target['timestamp']))}\n"
        text += f"📊 تحلیل {target['analysis']['total_signals']} سیگنال:\n"
        text += f"• نرخ برد: {target['analysis']['win_rate']:.1f}%\n"
        text += f"• میانگین RR: {target['analysis']['avg_rr']:.2f}\n"
        text += f"• بهترین حالت: {MODE_CONFIGS[target['analysis']['best_mode']]['label']}\n"
        text += f"{DIVIDER}\n"
        text += f"💡 *پیشنهادات:*\n"
        for sug in target["suggestions"]:
            if sug["parameter"] == "mode":
                text += f"• تغییر حالت به {MODE_CONFIGS[sug['suggested']]['label']}\n"
            else:
                text += f"• {sug['parameter']}: {sug['current']} → {sug['suggested']}\n"
            text += f"  📌 {sug['reason']}\n"
        text += f"\n⏳ وضعیت: {target['status']}"
        await query.edit_message_text(text, reply_markup=kb_back_to_optimization(), parse_mode="Markdown")

# ---------- رویدادها ----------
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
            importance = "medium"
            if "hard fork" in name.lower() or "upgrade" in name.lower() or "ethereum" in name.lower():
                importance = "high"
            description = ev.get("description", "")[:200]
            events.append({
                "name": name,
                "time": event_time,
                "importance": importance,
                "description": description,
                "impact": "مشخص نیست"
            })
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

# ---------- توابع تحلیل لایه‌ها ----------
async def analyze_layers(code, direction, ind, mode, cache_obj, order_flow=None):
    config = MODE_CONFIGS.get(mode, MODE_CONFIGS["standard"])
    df = cache_obj.ohlcv.get(config["main_tf"], {}).get(code)
    results = {}

    if df is not None and len(df) > 30:
        high = df["high"].iloc[-20:]
        low = df["low"].iloc[-20:]
        price = float(df["close"].iloc[-1])
        prev_high = float(high.max())
        prev_low = float(low.min())
        if direction == "LONG":
            structure_ok = price > prev_low * 0.999
            last = df.iloc[-1]
            if not structure_ok and last["close"] > last["open"] and (last["close"] - last["low"]) > 2 * (last["high"] - last["close"]):
                structure_ok = True
            if not structure_ok and price <= (prev_high + prev_low) / 2:
                structure_ok = True
        else:
            structure_ok = price < prev_high * 1.001
            last = df.iloc[-1]
            if not structure_ok and last["close"] < last["open"] and (last["high"] - last["close"]) > 2 * (last["close"] - last["low"]):
                structure_ok = True
            if not structure_ok and price >= (prev_high + prev_low) / 2:
                structure_ok = True
        results["structure"] = structure_ok
    else:
        results["structure"] = False

    main_tf = config["main_tf"]
    confirm_tfs = config["confirm_tfs"]
    mtf_count = 0
    df_main = cache_obj.ohlcv.get(main_tf, {}).get(code)
    if df_main is not None and len(df_main) > 50:
        price = float(df_main["close"].iloc[-1])
        ema200 = EMAIndicator(df_main["close"], window=200).ema_indicator().iloc[-1]
        if direction == "LONG" and price > ema200:
            mtf_count += 1
        elif direction == "SHORT" and price < ema200:
            mtf_count += 1
    for tf in confirm_tfs:
        df_tf = cache_obj.ohlcv.get(tf, {}).get(code)
        if df_tf is not None and len(df_tf) > 50:
            price = float(df_tf["close"].iloc[-1])
            ema200 = EMAIndicator(df_tf["close"], window=200).ema_indicator().iloc[-1]
            if direction == "LONG" and price > ema200:
                mtf_count += 1
            elif direction == "SHORT" and price < ema200:
                mtf_count += 1
    results["mtf"] = mtf_count >= 1

    momentum_score = 0
    if direction == "LONG":
        if ind["macd_hist"] > 0: momentum_score += 1
        if ind["rsi"] > 50: momentum_score += 1
        if ind["roc"] > 0: momentum_score += 1
        if ind["bullish_div"] or ind["macd_bullish_div"]: momentum_score += 1
    else:
        if ind["macd_hist"] < 0: momentum_score += 1
        if ind["rsi"] < 50: momentum_score += 1
        if ind["roc"] < 0: momentum_score += 1
        if ind["bearish_div"] or ind["macd_bearish_div"]: momentum_score += 1
    results["momentum"] = momentum_score >= 1

    results["volume"] = ind["volume_ratio"] >= 0.8 or ind["volume_spike"] or ind["volume_trend_up"]

    sentiment_score = await cache_obj._calculate_sentiment_score(code, ind)
    if direction == "LONG":
        results["sentiment"] = sentiment_score > -0.2
    else:
        results["sentiment"] = sentiment_score < 0.2

    results["trend"] = ind["price_above_ema200"] if direction == "LONG" else not ind["price_above_ema200"]

    if order_flow is None:
        order_flow = await cache_obj._get_order_flow(code)
    if order_flow == 0 or (0.9 <= order_flow <= 1.1):
        results["order_flow"] = True
    else:
        if direction == "LONG":
            results["order_flow"] = order_flow > 1.1
        else:
            results["order_flow"] = order_flow < 0.9

    breadth = cache_obj._get_market_breadth()
    sample_count = getattr(cache_obj, "_breadth_sample_count", 0)
    if direction == "LONG":
        results["breadth"] = (breadth >= 45) if sample_count >= 5 else True
    else:
        results["breadth"] = (breadth <= 55) if sample_count >= 5 else True

    bb_percent = ind.get("bb_percent", 0.5)
    results["smart_vol"] = 0.1 <= bb_percent <= 0.9

    if direction == "LONG":
        results["comp_trend"] = ind["plus_di"] > ind["minus_di"]
    else:
        results["comp_trend"] = ind["minus_di"] > ind["plus_di"]

    return results

# ---------- تولید سیگنال جدید ----------
async def generate_trade_plan_v2(code, mode="standard", send_to_channel=False):
    global app
    try:
        await cache.update_prices(force=True, codes=[code])
        ind = await cache.get_indicators(code, mode)
        if not ind:
            logger.info(f"No indicators for {code}")
            return None
        config = MODE_CONFIGS.get(mode, MODE_CONFIGS["standard"])
        order_flow = await cache._get_order_flow(code)
        long_layers = await analyze_layers(code, "LONG", ind, mode, cache, order_flow)
        short_layers = await analyze_layers(code, "SHORT", ind, mode, cache, order_flow)

        long_score = 0
        short_score = 0
        long_confirmed = 0
        short_confirmed = 0
        for layer, weight in LAYER_WEIGHTS.items():
            if long_layers.get(layer, False):
                long_score += weight
                long_confirmed += 1
            if short_layers.get(layer, False):
                short_score += weight
                short_confirmed += 1

        direction = None
        confidence = 0
        layers = {}

        if long_confirmed >= config["min_confirmations"] and long_score >= short_score + MIN_DIRECTION_GAP:
            direction = "LONG"
            confidence = long_score
            layers = long_layers
        elif short_confirmed >= config["min_confirmations"] and short_score >= long_score + MIN_DIRECTION_GAP:
            direction = "SHORT"
            confidence = short_score
            layers = short_layers
        else:
            if long_confirmed >= config["min_confirmations"] and long_score >= short_score:
                direction = "LONG"
                confidence = long_score
                layers = long_layers
            elif short_confirmed >= config["min_confirmations"] and short_score >= long_score:
                direction = "SHORT"
                confidence = short_score
                layers = short_layers
            else:
                logger.info(f"No direction for {code}: long_conf={long_confirmed}, short_conf={short_confirmed}, gap={abs(long_score-short_score)}")
                return None

        if confidence < MIN_SIGNAL_CONFIDENCE:
            logger.info(f"Confidence too low for {code}: {confidence:.1f} < {MIN_SIGNAL_CONFIDENCE}")
            return None

        levels = build_ladder_weighted(ind, direction, mode)
        if levels["rr"] < config["min_rr"]:
            logger.info(f"RR too low for {code}: {levels['rr']:.2f} < {config['min_rr']}")
            return None

        funding = 0.0
        fg_value, _ = await get_fear_greed()
        if fg_value is not None:
            if direction == "LONG" and fg_value > 80:
                confidence -= 5
            elif direction == "SHORT" and fg_value < 20:
                confidence -= 5
        confidence = max(0, min(100, confidence))
        confidence = float(confidence)

        max_lev = config["max_leverage"]
        if confidence >= 90:
            leverage = max_lev
        elif confidence >= 80:
            leverage = max(1, max_lev - 1)
        elif confidence >= 70:
            leverage = max(1, max_lev - 2)
        elif confidence >= 60:
            leverage = max(1, max_lev - 3)
        else:
            leverage = 1

        win_rate_est = get_win_rate_estimate()
        entry_avg = levels["avg_entry"]
        liq = calc_liquidation_price(direction, entry_avg, leverage)
        reasons, warnings = signal_reasons(direction, ind, mode)
        grade = signal_grade(confidence)

        plan = TradePlan(
            symbol=code,
            direction=direction,
            trend=ind["trend_label"],
            rsi=float(ind["rsi"]),
            current_price=float(ind["price"]),
            confidence=confidence,
            win_rate_estimate=win_rate_est,
            entries=levels["entries"],
            stop_losses=levels["stop_losses"],
            take_profits=levels["take_profits"],
            funding_rate=funding,
            leverage=leverage,
            liquidation_price=liq,
            scores={},
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
            layer_results=layers,
            signal_grade=grade,
            adx_at_time=ind["adx"],
            rsi_at_time=ind["rsi"],
            market_condition="trending" if ind["adx"] >= 25 else "ranging",
            rr=levels["rr"]
        )
        signal_id = record_signal(plan)
        if send_to_channel:
            await send_signal_to_channel(plan, signal_id)
        return plan
    except Exception as e:
        logger.exception(f"generate_trade_plan_v2 error for {code}: {e}")
        return None

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
    return {
        "entries": entries,
        "stop_losses": [initial_stop],
        "take_profits": take_profits,
        "avg_entry": avg_entry,
        "risk": risk,
        "reward": reward,
        "rr": rr,
        "entry_to_sl_pct": (risk / avg_entry * 100) if avg_entry > 0 else 0,
        "entry_to_tp_pct": (reward / avg_entry * 100) if avg_entry > 0 else 0,
        "sl_atr": risk / atr if atr > 0 else 0,
        "tp_atr": reward / atr if atr > 0 else 0,
    }

def calc_liquidation_price(direction, entry, leverage):
    maint_margin = 0.005
    if direction == "LONG":
        return entry * (1 - 1/leverage + maint_margin)
    return entry * (1 + 1/leverage - maint_margin)

def signal_reasons(direction, ind, mode):
    reasons, warnings = [], []
    if direction == "LONG":
        if ind.get("price_above_ema200", False): reasons.append("قیمت بالای EMA200")
        if ind.get("ema20_above_ema50", False): reasons.append("EMA20 بالای EMA50")
        if ind.get("ema20_bullish_cross", False): reasons.append("کراس صعودی EMA20/EMA50")
        if ind.get("macd_hist", 0) > 0: reasons.append("MACD مثبت")
        if ind.get("plus_di", 0) > ind.get("minus_di", 0): reasons.append("+DI > -DI")
        if ind.get("adx", 0) >= 25: reasons.append(f"ADX = {ind['adx']:.1f}")
        if ind.get("volume_ratio", 1) >= 1.5: reasons.append(f"حجم غیرعادی = {ind['volume_ratio']:.1f}×")
        elif ind.get("volume_ratio", 1) >= 1: reasons.append(f"حجم = {ind['volume_ratio']:.1f}× میانگین")
        if ind.get("higher_tf_trend_up", False): reasons.append("تأیید تایم‌فریم بالاتر")
        if ind.get("price_above_vwap", False): reasons.append("قیمت بالای VWAP")
        if ind.get("roc", 0) > 0: reasons.append("ROC مثبت")
        if ind.get("cci", 0) > 0: reasons.append("CCI مثبت")
        if ind.get("breakout_up", False): reasons.append("شکست مقاومت")
        if ind.get("bullish_div", False): reasons.append("واگرایی مثبت RSI")
        if ind.get("macd_bullish_div", False): reasons.append("واگرایی مثبت MACD")
        if ind.get("rsi", 0) >= 68: warnings.append(f"RSI = {ind['rsi']:.1f} — نزدیک اشباع خرید")
        if ind.get("williams_r", 0) > -20: warnings.append(f"Williams %R = {ind['williams_r']:.1f} — اشباع خرید")
    else:
        if not ind.get("price_above_ema200", True): reasons.append("قیمت زیر EMA200")
        if not ind.get("ema20_above_ema50", True): reasons.append("EMA20 زیر EMA50")
        if ind.get("ema20_bearish_cross", False): reasons.append("کراس نزولی EMA20/EMA50")
        if ind.get("macd_hist", 0) < 0: reasons.append("MACD منفی")
        if ind.get("minus_di", 0) > ind.get("plus_di", 0): reasons.append("-DI > +DI")
        if ind.get("adx", 0) >= 25: reasons.append(f"ADX = {ind['adx']:.1f}")
        if ind.get("volume_ratio", 1) >= 1.5: reasons.append(f"حجم غیرعادی = {ind['volume_ratio']:.1f}×")
        elif ind.get("volume_ratio", 1) >= 1: reasons.append(f"حجم = {ind['volume_ratio']:.1f}× میانگین")
        if ind.get("higher_tf_trend_down", False): reasons.append("تأیید تایم‌فریم بالاتر")
        if not ind.get("price_above_vwap", True): reasons.append("قیمت زیر VWAP")
        if ind.get("roc", 0) < 0: reasons.append("ROC منفی")
        if ind.get("cci", 0) < 0: reasons.append("CCI منفی")
        if ind.get("breakout_down", False): reasons.append("شکست حمایت")
        if ind.get("bearish_div", False): reasons.append("واگرایی منفی RSI")
        if ind.get("macd_bearish_div", False): reasons.append("واگرایی منفی MACD")
        if ind.get("rsi", 0) <= 32: warnings.append(f"RSI = {ind['rsi']:.1f} — نزدیک اشباع فروش")
        if ind.get("williams_r", 0) < -80: warnings.append(f"Williams %R = {ind['williams_r']:.1f} — اشباع فروش")
    return reasons, warnings

def record_signal(plan):
    signal_id = uuid.uuid4().hex[:10]
    record = {
        "signal_id": signal_id,
        "symbol": plan.symbol,
        "direction": plan.direction,
        "entry_price": plan.entry_price,
        "sl_price": plan.sl_price,
        "tp_prices": plan.tp_prices,
        "confidence": plan.confidence,
        "timestamp": plan.timestamp,
        "status": "open",
        "mode": plan.mode,
        "win_rate_estimate": plan.win_rate_estimate,
        "signal_grade": plan.signal_grade,
        "rr": plan.rr,
        "adx_at_time": plan.adx_at_time,
        "rsi_at_time": plan.rsi_at_time,
        "market_condition": plan.market_condition,
    }
    signal_history.append(record)
    if len(signal_history) > 200:
        signal_history.pop(0)
    return signal_id

def update_signal_status(symbol, current_price):
    changed = []
    for idx, rec in enumerate(signal_history):
        if rec["status"] != "open":
            continue
        if rec["symbol"] != symbol:
            continue
        direction = rec["direction"]
        old_status = rec["status"]
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
        if rec["status"] != old_status:
            changed.append(rec["signal_id"])
    return changed

# ---------- فرمت‌سازی ----------
def format_main_signal_v2(plan, code, chat_id):
    direction = "لانگ 🟢" if plan.direction == "LONG" else "شورت 🔴"
    mode_label = MODE_CONFIGS.get(plan.mode, MODE_CONFIGS["standard"])["label"]
    layers_text = ""
    for layer, ok in plan.layer_results.items():
        emoji = "✅" if ok else "❌"
        layers_text += f"{emoji} {LAYER_NAMES.get(layer, layer)}\n"
    grade_emoji = {"A": "🔥", "B": "⚡", "C": "📊", "D": "💤"}.get(plan.signal_grade[:1], "📊")
    text = (
        f"{grade_emoji} *سیگنال نهادی* | {code}/USDT | {direction}\n"
        f"🕒 {shamsi_now()}\n"
        f"🛠️ حالت: {mode_label} | درجه: {plan.signal_grade}\n"
        f"{DIVIDER}\n"
        f"🧩 *تحلیل ۱۰ لایه‌ای:*\n{layers_text}\n"
        f"🎯 *اطمینان:* {plan.confidence:.0f}٪ ({confidence_badge(plan.confidence)})\n"
        f"📊 *نرخ موفقیت:* {plan.win_rate_estimate:.1f}٪\n"
        f"📐 *نسبت ریسک به بازده:* 1:{plan.rr:.2f}\n"
        f"{DIVIDER}\n"
        f"📥 *ورود پله‌ای:*\n"
        f"1️⃣ {fmt_amount(plan.entries[0], chat_id)}\n"
        f"2️⃣ {fmt_amount(plan.entries[1], chat_id)}\n"
        f"3️⃣ {fmt_amount(plan.entries[2], chat_id)}\n"
        f"🎯 *حد سود هوشمند:*\n"
        f"1️⃣ {fmt_amount(plan.take_profits[0], chat_id)}\n"
        f"2️⃣ {fmt_amount(plan.take_profits[1], chat_id)}\n"
        f"3️⃣ {fmt_amount(plan.take_profits[2], chat_id)}\n"
        f"🛑 *حد ضرر پویا:* {fmt_amount(plan.sl_price, chat_id)}\n"
        f"{DIVIDER}\n"
        f"⚡ *اهرم پیشنهادی:* {plan.leverage}x\n"
        f"💰 *مدیریت ریسک:* حداکثر ۱.۲٪ سرمایه\n"
        f"🔔 *نکته:* پس از رسیدن به TP1، حد ضرر را به Entry منتقل کنید.\n"
        f"{DIVIDER}\n"
        f"⚠️ تحلیل تکنیکال است و تضمین سود یا توصیه مالی نیست."
    )
    return rtl_lines(text)

def format_status_dashboard(code, ind, plan, chat_id, mode, long_layers=None, short_layers=None):
    mode_label = MODE_CONFIGS.get(mode, MODE_CONFIGS["standard"])["label"]
    config = MODE_CONFIGS.get(mode, MODE_CONFIGS["standard"])
    price = ind['price']
    df_daily = cache.ohlcv.get("1d", {}).get(code)
    change_24h = 0
    high_24h = price
    low_24h = price
    if df_daily is not None and len(df_daily) >= 2:
        close_prev = float(df_daily["close"].iloc[-2])
        if close_prev > 0:
            change_24h = ((price - close_prev) / close_prev) * 100
        high_24h = float(df_daily["high"].iloc[-1]) if pd.notna(df_daily["high"].iloc[-1]) else price
        low_24h = float(df_daily["low"].iloc[-1]) if pd.notna(df_daily["low"].iloc[-1]) else price
    ema20_pos = "بالای 📈" if ind['price_above_ema20'] else "زیر 📉"
    ema50_pos = "بالای 📈" if ind['price_above_ema50'] else "زیر 📉"
    macd_status = "مثبت 📈" if ind['macd_hist'] > 0 else "منفی 📉"
    support = ind['support']
    resistance = ind['resistance']
    support_2 = ind['support'] * 0.99
    resistance_2 = ind['resistance'] * 1.01
    if plan and plan.layer_results:
        confirmed = sum(1 for v in plan.layer_results.values() if v)
        total_weight = sum(LAYER_WEIGHTS.get(layer, 0) for layer, ok in plan.layer_results.items() if ok)
        layers_summary = "📋 *خلاصه تحلیل لایه‌ها (۱۰ لایه):*\n"
        for layer, ok in plan.layer_results.items():
            emoji = "✅" if ok else "❌"
            weight = LAYER_WEIGHTS.get(layer, 0)
            layers_summary += f"{emoji} {LAYER_NAMES.get(layer, layer)} (وزن: {weight}%)\n"
        layers_summary += f"\n💡 *جمع‌بندی:* {confirmed} از ۱۰ لایه تأیید شد | امتیاز وزنی: {total_weight}%"
    else:
        if long_layers is not None and short_layers is not None:
            long_confirmed = sum(1 for v in long_layers.values() if v)
            short_confirmed = sum(1 for v in short_layers.values() if v)
            long_weight = sum(LAYER_WEIGHTS.get(layer, 0) for layer, ok in long_layers.items() if ok)
            short_weight = sum(LAYER_WEIGHTS.get(layer, 0) for layer, ok in short_layers.items() if ok)
            layers_summary = (
                f"📋 *خلاصه تحلیل لایه‌ها:*\n"
                f"🟢 لانگ: {long_confirmed} لایه تأیید | امتیاز: {long_weight}%\n"
                f"🔴 شورت: {short_confirmed} لایه تأیید | امتیاز: {short_weight}%\n"
                f"📊 اختلاف: {abs(long_weight - short_weight):.0f}%\n"
            )
            reasons_no_signal = []
            if ind['adx'] < config['adx_min']:
                reasons_no_signal.append(f"⚠️ ADX پایین است ({ind['adx']:.1f} < {config['adx_min']})")
            if long_confirmed < config['min_confirmations'] and short_confirmed < config['min_confirmations']:
                reasons_no_signal.append(f"⚠️ تعداد لایه‌ها کمتر از حد نیاز ({config['min_confirmations']}) است")
            if abs(long_weight - short_weight) < MIN_DIRECTION_GAP:
                reasons_no_signal.append(f"⚠️ اختلاف امتیاز دو جهت کمتر از {MIN_DIRECTION_GAP} است")
            if reasons_no_signal:
                layers_summary += f"\n💡 *دلایل عدم سیگنال:*\n" + "\n".join(reasons_no_signal)
            else:
                layers_summary += f"\n💡 *وضعیت:* شرایط برای سیگنال‌دهی مناسب نیست"
        else:
            layers_summary = "📋 در حال تحلیل لایه‌ها..."
    header = f"🧭 *وضعیت لحظه‌ای* {code}/USDT\n🕒 {shamsi_now()}\n🛠️ حالت: {mode_label}\n{DIVIDER}\n"
    price_text = (
        f"💰 قیمت: {fmt_amount(price, chat_id)}\n"
        f"📊 تغییرات ۲۴h: {change_24h:+.2f}%\n"
        f"📈 بالا: {fmt_amount(high_24h, chat_id)} | 📉 پایین: {fmt_amount(low_24h, chat_id)}\n"
        f"{DIVIDER}\n"
        f"📈 روند: {ind['trend_label']}\n"
        f"📊 قیمت نسبت به EMA20: {ema20_pos} | EMA50: {ema50_pos}\n"
        f"🎯 RSI: {ind['rsi']:.1f}\n"
        f"💪 ADX: {ind['adx']:.1f}\n"
        f"📊 MACD: {macd_status}\n"
        f"📊 حجم: {ind['volume_ratio']:.2f}× میانگین {' 🔊' if ind['volume_spike'] else ''}\n"
        f"{DIVIDER}\n"
        f"📊 حمایت: {fmt_amount(support, chat_id)} | مقاومت: {fmt_amount(resistance, chat_id)}\n"
    )
    if plan and plan.confidence >= MIN_SIGNAL_CONFIDENCE:
        footer = (
            f"\n{DIVIDER}\n"
            f"🎯 اطمینان: {plan.confidence:.0f}٪\n"
            f"⚡ اهرم: {plan.leverage}x\n"
            f"📐 RR: 1:{plan.rr:.2f}\n"
            f"📊 نرخ موفقیت: {plan.win_rate_estimate:.1f}٪\n"
            f"{DIVIDER}\n"
            f"⚠️ حد ضرر: {fmt_amount(plan.sl_price, chat_id)}"
        )
    else:
        footer = f"\n{DIVIDER}\n💤 در حال حاضر سیگنال نهایی وجود ندارد."
    return rtl_lines(header + price_text + layers_summary + footer + f"\n{DIVIDER}\n⚠️ تحلیل تکنیکال است و تضمین سود نیست.")

# ---------- توابع اصلی ----------
async def generate_trade_plan(code, mode="standard"):
    return await generate_trade_plan_v2(code, mode)

async def generate_status_text_async(code, chat_id, mode="standard"):
    await cache.update_prices(force=True, codes=[code])
    ind = await cache.get_indicators(code, mode)
    if not ind:
        return rtl_lines(f"{code}\n\n⚠️ داده کافی برای تحلیل این ارز دریافت نشد.")
    order_flow = await cache._get_order_flow(code)
    long_layers = await analyze_layers(code, "LONG", ind, mode, cache, order_flow)
    short_layers = await analyze_layers(code, "SHORT", ind, mode, cache, order_flow)
    plan = await generate_trade_plan_v2(code, mode)
    return format_status_dashboard(code, ind, plan, chat_id, mode, long_layers, short_layers)

async def generate_weekly_summary_async(code, chat_id):
    await cache.update_prices(force=True, codes=[code])
    week_df = await cache.get_weekly_data(code)
    if week_df is None or len(week_df) < 2:
        return rtl_lines(f"{code}\n\n⚠️ حداقل داده لازم برای تحلیل ۷ روزه دریافت نشد.")
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
    funding = 0.0
    fg_value, fg_class = await get_fear_greed()
    macro_data = cache.get_macro_data()
    text = (
        f"📊 *تحلیل جامع ارز* {code}\n"
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
    if macro_data:
        text += f"\n{DIVIDER}\n📊 *داده‌های کلان بازار:*\n"
        text += f"• سلطه بیت‌کوین: {macro_data.get('btc_dominance', 0):.1f}%\n"
        text += f"• حجم کل بازار: {macro_data.get('total_volume', 0):.0f}\n"
    text += (
        f"\n{DIVIDER}\n"
        f"🧭 شاخص ترس و طمع: {fg_value if fg_value is not None else '-'} ({fg_class if fg_class else '-'})\n"
        f"{DIVIDER}\nℹ️ داده‌ها از Gate.io (اصلی)، کوکوین اسپات و CoinGecko (پشتیبان) محاسبه شده‌اند."
    )
    return rtl_lines(text)

def format_prices_pretty(prices, chat_id):
    lines = ["💰 قیمت لحظه‌ای", f"🕒 {shamsi_now()}", DIVIDER]
    for code in COIN_CODES:
        price = prices.get(code)
        if price is not None and price > 0:
            source = price_sources.get(code, "G")
            if source == "G":
                source_emoji = "🅶"
            elif source == "K":
                source_emoji = "🅺"
            elif source == "C":
                source_emoji = "🅲"
            else:
                source_emoji = "❓"
            price_display = fmt_amount(price, chat_id)
            lines.append(f"{code} {source_emoji} → {price_display}")
        else:
            lines.append(f"{code} ⚠️ قیمت در دسترس نیست")
    return rtl_lines("\n".join(lines))

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

# ---------- توابع ارسال به کانال ----------
async def send_signal_to_channel(plan, signal_id):
    if not CHANNEL_ID:
        return
    direction_emoji = "🟢" if plan.direction == "LONG" else "🔴"
    mode_label = MODE_CONFIGS.get(plan.mode, MODE_CONFIGS["standard"])["label"]
    text = (
        f"🔔 سیگنال جدید | {plan.symbol}/USDT\n"
        f"📈 جهت: {plan.direction} {direction_emoji}\n"
        f"🛠️ حالت: {mode_label}\n"
        f"🎯 اطمینان: {plan.confidence:.0f}٪\n"
        f"📐 RR: 1:{plan.rr:.2f}\n\n"
        f"📥 ورود: {plan.entry_price:.4f}\n"
        f"🛑 حد ضرر: {plan.sl_price:.4f}\n"
        f"🎯 اهداف:\n"
        f"1️⃣ {plan.take_profits[0]:.4f}\n"
        f"2️⃣ {plan.take_profits[1]:.4f}\n"
        f"3️⃣ {plan.take_profits[2]:.4f}\n\n"
        f"⚡ اهرم پیشنهادی: {plan.leverage}x\n"
        f"🕒 {shamsi_now()}"
    )
    try:
        msg = await app.bot.send_message(chat_id=CHANNEL_ID, text=rtl_lines(text), parse_mode="Markdown")
        channel_signal_messages[signal_id] = msg.message_id
        save_state()
        logger.info(f"Signal sent to channel for {plan.symbol} (signal_id {signal_id})")
    except Exception as e:
        logger.error(f"Failed to send signal to channel: {e}")

def build_signal_update_text_from_record(rec):
    direction_emoji = "🟢" if rec["direction"] == "LONG" else "🔴"
    mode_label = MODE_CONFIGS.get(rec["mode"], MODE_CONFIGS["standard"])["label"]
    if rec["status"] == "tp1_hit":
        status_text = "✅ TP1 زده شد"
        sl_text = f"🛑 حد ضرر به Entry منتقل شد\n📥 ورود: {rec['entry_price']:.4f}"
        targets = f"🎯 اهداف بعدی:\n2️⃣ {rec['tp_prices'][1]:.4f}\n3️⃣ {rec['tp_prices'][2]:.4f}"
    elif rec["status"] == "tp2_hit":
        status_text = "✅ TP2 زده شد"
        sl_text = f"🛑 حد ضرر به TP1 منتقل شد\n🎯 هدف بعدی:\n3️⃣ {rec['tp_prices'][2]:.4f}"
        targets = ""
    elif rec["status"] == "tp3_hit":
        status_text = "✅ TP3 زده شد"
        sl_text = "🎯 سیگنال با موفقیت بسته شد"
        targets = ""
    elif rec["status"] == "sl_hit":
        status_text = "❌ حد ضرر زده شد"
        sl_text = f"🛑 قیمت به {rec['sl_price']:.4f} رسید"
        targets = ""
    else:
        return ""

    text = (
        f"🔔 سیگنال | {rec['symbol']}/USDT\n"
        f"📈 جهت: {rec['direction']} {direction_emoji}\n"
        f"🛠️ حالت: {mode_label}\n\n"
        f"{status_text}\n"
        f"{sl_text}\n"
        f"{targets}\n"
        f"🕒 بروزرسانی: {shamsi_now()}"
    )
    return text

async def update_channel_signal_message(signal_id):
    if signal_id not in channel_signal_messages:
        return
    rec = next((r for r in signal_history if r.get("signal_id") == signal_id), None)
    if not rec:
        return
    new_text = build_signal_update_text_from_record(rec)
    if not new_text:
        return
    message_id = channel_signal_messages[signal_id]
    try:
        await app.bot.edit_message_text(
            chat_id=CHANNEL_ID,
            message_id=message_id,
            text=rtl_lines(new_text),
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to update channel message for signal {signal_id}: {e}")

async def send_high_importance_news_to_channel(news_text):
    if not CHANNEL_ID:
        return
    try:
        await app.bot.send_message(chat_id=CHANNEL_ID, text=rtl_lines(news_text), parse_mode="Markdown")
        logger.info("High importance news sent to channel")
    except Exception as e:
        logger.error(f"Failed to send news to channel: {e}")

# ---------- حلقه مستقل کانال ----------
async def channel_broadcast_loop(app):
    await asyncio.sleep(20)
    interval = int(os.getenv("CHANNEL_BROADCAST_INTERVAL", "1800"))  # 30 دقیقه
    while True:
        try:
            if not CHANNEL_ID:
                logger.warning("CHANNEL_ID not set, channel broadcasting disabled")
                await asyncio.sleep(60)
                continue

            logger.info("Channel broadcast: generating signals for all modes...")
            await cache.update_prices(force=True)
            await cache.update_ohlcv(force=True)

            for mode in MODE_CONFIGS.keys():
                signals_for_mode = []
                for code in cache.valid_codes:
                    try:
                        plan = await generate_trade_plan_v2(code, mode, send_to_channel=True)
                        if plan:
                            signals_for_mode.append(plan)
                    except Exception as e:
                        logger.debug(f"Error generating {code} {mode}: {e}")
                    await asyncio.sleep(0.1)
                # مرتب‌سازی بر اساس اطمینان و ارسال بهترین‌ها (چون در تولید ارسال شده، اینجا فقط لاگ)
                signals_for_mode.sort(key=lambda p: p.confidence, reverse=True)
                logger.info(f"Channel broadcast {mode}: {len(signals_for_mode)} signals, top: {signals_for_mode[:3]}")
            logger.info("Channel broadcast completed")
        except Exception as e:
            logger.exception("Channel broadcast error: %s", e)
        await asyncio.sleep(interval)

# ---------- مرکز هوشمندسازی ----------
async def optimization_center(update, context):
    query = update.callback_query
    chat_id = update.effective_chat.id
    if not is_admin_role(chat_id):
        await query.answer("⛔️ فقط ادمین.", show_alert=True)
        return
    text = "🧠 *مرکز هوشمندسازی*\n\n"
    text += "از بخش‌های زیر انتخاب کنید:\n"
    text += "• 📋 پیشنهادات فعال - آخرین پیشنهاد با تایید/رد\n"
    text += "• 📜 تاریخچه پیشنهادات - لیست کامل پیشنهادات قبلی"
    await query.edit_message_text(
        text,
        reply_markup=kb_optimization_center(),
        parse_mode="Markdown"
    )

async def optimization_active(update, context):
    query = update.callback_query
    chat_id = update.effective_chat.id
    if not is_admin_role(chat_id):
        await query.answer("⛔️ فقط ادمین.", show_alert=True)
        return
    last_pending = None
    for sug in reversed(suggestion_history):
        if sug["status"] == "pending":
            last_pending = sug
            break
    if not last_pending:
        total_closed = len([s for s in signal_history if s["status"] in ["tp1_hit", "tp2_hit", "tp3_hit", "sl_hit"]])
        text = (
            "📋 *پیشنهادات فعال*\n\n"
            f"📊 *وضعیت جمع‌آوری داده*\n"
            f"{DIVIDER}\n"
            f"• تعداد سیگنال‌های بسته‌شده: {total_closed}\n"
            f"• حداقل نیاز برای تحلیل: ۱۰\n\n"
            f"⏳ در حال جمع‌آوری داده‌های کافی برای ارائه پیشنهادات هوشمند...\n\n"
            f"💡 *نکته:* پس از بسته شدن حداقل ۱۰ سیگنال (TP یا SL)، اولین پیشنهادات در اینجا نمایش داده می‌شوند."
        )
        await query.edit_message_text(
            text,
            reply_markup=kb_back_to_optimization(),
            parse_mode="Markdown"
        )
        return
    text = "📋 *پیشنهادات فعال*\n\n"
    text += "🔄 *آخرین پیشنهاد فعال*\n"
    text += f"{DIVIDER}\n"
    text += f"📅 تاریخ: {shamsi_date(datetime.fromtimestamp(last_pending['timestamp']))}\n"
    text += f"📊 تحلیل {last_pending['analysis']['total_signals']} سیگنال اخیر:\n"
    text += f"• نرخ برد: {last_pending['analysis']['win_rate']:.1f}%\n"
    text += f"• میانگین RR: {last_pending['analysis']['avg_rr']:.2f}\n"
    text += f"• بهترین حالت: {MODE_CONFIGS[last_pending['analysis']['best_mode']]['label']}\n"
    text += f"{DIVIDER}\n"
    text += f"💡 *پیشنهادات:*\n"
    for sug in last_pending["suggestions"][:3]:
        if sug["parameter"] == "mode":
            text += f"• تغییر حالت به {MODE_CONFIGS[sug['suggested']]['label']}\n"
        else:
            text += f"• {sug['parameter']}: {sug['current']} → {sug['suggested']}\n"
        text += f"  📌 {sug['reason']}\n"
    text += f"\n{DIVIDER}\n"
    text += f"⏳ وضعیت: در انتظار پاسخ\n"
    text += f"📌 *یادآوری:* در صورت عدم پاسخ، پس از ۲۴ ساعت منقضی می‌شود."
    await query.edit_message_text(
        text,
        reply_markup=kb_suggestion_actions(last_pending["id"]),
        parse_mode="Markdown"
    )

async def optimization_history(update, context):
    query = update.callback_query
    chat_id = update.effective_chat.id
    if not is_admin_role(chat_id):
        await query.answer("⛔️ فقط ادمین.", show_alert=True)
        return
    if not suggestion_history:
        text = (
            "📜 *تاریخچه پیشنهادات*\n\n"
            "هیچ پیشنهادی ثبت نشده است.\n"
            "پس از جمع‌آوری داده‌های کافی، اولین پیشنهادات در اینجا نمایش داده می‌شوند."
        )
        await query.edit_message_text(
            text,
            reply_markup=kb_back_to_optimization(),
            parse_mode="Markdown"
        )
        return
    text = "📜 *تاریخچه پیشنهادات*\n\n"
    text += f"{DIVIDER}\n"
    for sug in reversed(suggestion_history[-10:]):
        status_emoji = {
            "applied": "✅",
            "rejected": "❌",
            "pending": "⏳",
            "expired": "⌛"
        }.get(sug["status"], "❓")
        date_str = shamsi_date(datetime.fromtimestamp(sug["timestamp"]))
        text += f"{status_emoji} {date_str} - {len(sug['suggestions'])} پیشنهاد\n"
        if sug["status"] == "applied" and "result" in sug:
            text += f"   📌 {sug['result']}\n"
        elif sug["status"] == "rejected":
            text += f"   📌 تنظیمات قبلی حفظ شد\n"
        elif sug["status"] == "expired":
            text += f"   📌 عدم پاسخ تا ۲۴ ساعت\n"
        text += "\n"
    await query.edit_message_text(
        text,
        reply_markup=kb_back_to_optimization(),
        parse_mode="Markdown"
    )

# ---------- دکمه تحلیل جامع ----------
async def comprehensive_analysis(update, context):
    query = update.callback_query
    chat_id = update.effective_chat.id
    if not is_admin_role(chat_id):
        await query.answer("⛔️ فقط ادمین.", show_alert=True)
        return
    await query.edit_message_text("⏳ در حال تحلیل همه ارزها...")
    try:
        await cache.update_prices(force=True)
        await cache.update_ohlcv(force=True)
        active_signals_list = []
        mode = "standard"
        for code in COIN_CODES:
            try:
                ind = await cache.get_indicators(code, mode)
                if not ind:
                    continue
                plan = await generate_trade_plan_v2(code, mode)
                if plan and plan.confidence >= MIN_SIGNAL_CONFIDENCE:
                    active_signals_list.append({
                        "code": code,
                        "direction": plan.direction,
                        "confidence": plan.confidence,
                        "rr": plan.rr,
                        "mode": plan.mode,
                        "entry": plan.entry_price,
                        "sl": plan.sl_price,
                        "tp1": plan.take_profits[0] if plan.take_profits else 0,
                    })
                await asyncio.sleep(0.2)
            except Exception as e:
                logger.debug(f"Comprehensive analysis error for {code}: {e}")
                continue
        if not active_signals_list:
            await query.edit_message_text(
                "📊 *تحلیل جامع ارزها*\n"
                f"{DIVIDER}\n"
                "💤 هیچ سیگنال فعالی یافت نشد.\n\n"
                "دلایل احتمالی:\n"
                "• ADX پایین (بازار رنج)\n"
                "• تعداد لایه‌های تأییدشده کمتر از حد نیاز\n"
                "• نسبت ریسک به بازده پایین",
                reply_markup=kb_back_to_admin_panel(),
                parse_mode="Markdown"
            )
            return
        text = "📊 *تحلیل جامع ارزها*\n"
        text += f"🕒 {shamsi_now()}\n{DIVIDER}\n"
        long_count = 0
        short_count = 0
        for signal in active_signals_list:
            direction_emoji = "🟢" if signal["direction"] == "LONG" else "🔴"
            direction_text = "لانگ" if signal["direction"] == "LONG" else "شورت"
            mode_label = MODE_CONFIGS.get(signal["mode"], MODE_CONFIGS["standard"])["label"]
            if signal["direction"] == "LONG":
                long_count += 1
            else:
                short_count += 1
            text += (
                f"{direction_emoji} {signal['code']} | {direction_text}\n"
                f"   اطمینان: {signal['confidence']:.0f}% | RR: {signal['rr']:.2f} | {mode_label}\n"
                f"   📥 ورود: {fmt_amount(signal['entry'], chat_id)}\n"
                f"   🛑 حد ضرر: {fmt_amount(signal['sl'], chat_id)}\n"
                f"   🎯 TP1: {fmt_amount(signal['tp1'], chat_id)}\n"
                f"{DIVIDER}\n"
            )
        text += f"📊 جمع‌بندی: {len(active_signals_list)} سیگنال فعال\n"
        text += f"🟢 لانگ: {long_count} | 🔴 شورت: {short_count}"
        chunks = split_long_message(text)
        await query.edit_message_text(chunks[0], reply_markup=kb_back_to_admin_panel(), parse_mode="Markdown")
        for chunk in chunks[1:]:
            await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")
    except Exception as e:
        logger.exception(f"Comprehensive analysis error: {e}")
        await query.edit_message_text(f"❌ خطا در تحلیل جامع:\n{str(e)}", reply_markup=kb_back_to_admin_panel())

# ---------- مدیریت صفحه نمایش ----------
async def clear_interactive_screen(context, chat_id, keep_id=None):
    ids = interactive_screen_messages.pop(chat_id, [])
    for mid in ids:
        if mid == keep_id: continue
        try: await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception: pass

def set_interactive_screen(chat_id, message_ids):
    interactive_screen_messages[chat_id] = message_ids

async def clear_overlay(context, chat_id):
    ids = overlay_messages.pop(chat_id, [])
    for mid in ids:
        try: await context.bot.delete_message(chat_id=chat_id, message_id=mid)
        except Exception: pass

# ---------- کیبوردها ----------
def build_grid_keyboard(buttons, columns):
    rows = [buttons[i:i + columns] for i in range(0, len(buttons), columns)]
    return rows

def kb_currency():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("دلار (USDT) 💵", callback_data="cur_USDT")],
        [InlineKeyboardButton("تومان (IRT) 💴", callback_data="cur_IRT")],
        [InlineKeyboardButton("هر دو 💱", callback_data="cur_BOTH")],
    ])

def kb_role_selection():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("ادمین 👑", callback_data="role_admin")],
        [InlineKeyboardButton("کاربر عادی 👤", callback_data="role_user")],
    ])

def kb_mode_selection():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("سریع ⚡", callback_data="mode_fast")],
        [InlineKeyboardButton("نیمه‌سریع 🔥", callback_data="mode_semi_fast")],
        [InlineKeyboardButton("استاندارد 📊", callback_data="mode_standard")],
        [InlineKeyboardButton("محافظه‌کار 🛡️", callback_data="mode_conservative")],
    ])

def kb_mode_selection_for_action(action, code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("سریع ⚡", callback_data=f"run_{action}_{code}_fast")],
        [InlineKeyboardButton("نیمه‌سریع 🔥", callback_data=f"run_{action}_{code}_semi_fast")],
        [InlineKeyboardButton("استاندارد 📊", callback_data=f"run_{action}_{code}_standard")],
        [InlineKeyboardButton("محافظه‌کار 🛡️", callback_data=f"run_{action}_{code}_conservative")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"coin_{code}")],
    ])

def kb_main(user_id, mode="standard"):
    role = user_role.get(user_id, "user")
    if role == "admin":
        rows = [
            [InlineKeyboardButton("💰 قیمت لحظه‌ای", callback_data="menu_prices"), InlineKeyboardButton("🪙 انتخاب ارز", callback_data="menu_coins")],
            [InlineKeyboardButton("📅 رویدادها", callback_data="events_menu"), InlineKeyboardButton("⭐ علاقه‌مندی‌ها", callback_data="favorites")],
            [InlineKeyboardButton("📊 گزارش مقایسه‌ای", callback_data="admin_compare"), InlineKeyboardButton("🧾 گزارش دوره‌ای", callback_data="periodic_report")],
            [InlineKeyboardButton("🔄 شروع مجدد", callback_data="restart_bot"), InlineKeyboardButton("🛑 توقف ربات", callback_data="stop_bot")],
            [InlineKeyboardButton("📈 داشبورد تحلیلی", callback_data="dashboard"), InlineKeyboardButton("⚙️ پنل مدیریت", callback_data="admin_panel")],
            [InlineKeyboardButton("❓ راهنما", callback_data="help")],
        ]
    else:
        rows = [
            [InlineKeyboardButton("💰 قیمت لحظه‌ای", callback_data="menu_prices"), InlineKeyboardButton("🪙 انتخاب ارز", callback_data="menu_coins")],
            [InlineKeyboardButton("📅 رویدادها", callback_data="events_menu"), InlineKeyboardButton("⭐ علاقه‌مندی‌ها", callback_data="favorites")],
            [InlineKeyboardButton("🔄 تغییر سبک معاملاتی", callback_data="change_mode"), InlineKeyboardButton("❓ راهنما", callback_data="help")],
            [InlineKeyboardButton("🔄 شروع مجدد", callback_data="restart_bot"), InlineKeyboardButton("🛑 توقف ربات", callback_data="stop_bot")],
        ]
    return InlineKeyboardMarkup(rows)

def kb_admin_panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 تحلیل جامع", callback_data="comprehensive_analysis")],
        [InlineKeyboardButton("🔄 بروزرسانی کامل", callback_data="menu_all")],
        [InlineKeyboardButton("🧠 مرکز هوشمندسازی", callback_data="optimization_center")],
        [InlineKeyboardButton("🔙 بازگشت به منو اصلی", callback_data="menu_main")],
    ])

def kb_optimization_center():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 پیشنهادات فعال", callback_data="optimization_active")],
        [InlineKeyboardButton("📜 تاریخچه پیشنهادات", callback_data="optimization_history")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")],
    ])

def kb_back_to_optimization():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data="optimization_center")]
    ])

def kb_back_main():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت به منو اصلی", callback_data="menu_main")]
    ])

def kb_back_to_admin_panel():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data="admin_panel")]
    ])

def kb_events_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📅 رویدادهای پیش رو", callback_data="events_upcoming")],
        [InlineKeyboardButton("📰 اخبار و هشدارها", callback_data="events_news")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")],
    ])

def kb_back_to_events():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data="events_menu")]
    ])

def kb_back_to_coin(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"coin_{code}")]
    ])

def kb_coins(page=0):
    start = page * PER_PAGE
    end = start + PER_PAGE
    page_codes = COIN_CODES[start:end]
    buttons = []
    for code in page_codes:
        status = cache.market_status.get(code, {}).get("status")
        if status == "SWAP OK":
            label = f"{code} 🟢"
        elif status == "TICKER ERROR":
            label = f"{code} 🟠"
        else:
            label = f"{code} ⚪"
        buttons.append(InlineKeyboardButton(label, callback_data=f"coin_{code}"))
    rows = build_grid_keyboard(buttons, COINS_GRID_COLUMNS)

    # دکمه جدید "دریافت سیگنال های فعال" قبل از ناوبری و بازگشت
    rows.append([InlineKeyboardButton("📡 دریافت سیگنال‌های فعال", callback_data="active_signals_all")])

    nav_row = []
    total_pages = (len(COIN_CODES) + PER_PAGE - 1) // PER_PAGE
    if page > 0:
        nav_row.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"coins_page_{page-1}"))
    if end < len(COIN_CODES):
        nav_row.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"coins_page_{page+1}"))
    if nav_row:
        rows.append(nav_row)
    rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")])
    return InlineKeyboardMarkup(rows)

def kb_coin_detail(code, is_fav, is_admin_role=False):
    fav_btn = InlineKeyboardButton("🗑️ حذف از علاقه‌مندی‌ها" if is_fav else "⭐ افزودن به علاقه‌مندی‌ها", callback_data=f"toggle_fav_{code}")
    buttons = [
        [InlineKeyboardButton("🧭 وضعیت لحظه‌ای", callback_data=f"askmode_suggest_{code}" if is_admin_role else f"suggest_{code}")],
        [InlineKeyboardButton("🚀 پیشنهاد لحظه‌ای", callback_data=f"askmode_instant_{code}" if is_admin_role else f"instant_{code}")],
        [InlineKeyboardButton("📆 تحلیل جامع ارز", callback_data=f"askmode_weekly_{code}" if is_admin_role else f"weekly_{code}")],
        [fav_btn],
        [InlineKeyboardButton("🔙 لیست ارزها", callback_data="menu_coins"), InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")],
    ]
    return InlineKeyboardMarkup(buttons)

def kb_signal_details(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 جزئیات فنی", callback_data=f"details_{code}")],
        [InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"suggest_{code}")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"coin_{code}")],
        [InlineKeyboardButton("🏠 منوی اصلی", callback_data="menu_main")],
    ])

def kb_back_to_signal(code):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 بازگشت", callback_data=f"coin_{code}")],
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

def kb_periodic_report():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 هفتگی", callback_data="report_period_weekly"), InlineKeyboardButton("📅 ماهانه", callback_data="report_period_monthly")],
        [InlineKeyboardButton("🔙 بازگشت", callback_data="menu_main")],
    ])

def kb_help(step=0):
    buttons = []
    if step < 7:
        buttons.append(InlineKeyboardButton("بعدی ⬅️", callback_data=f"help_{step+1}"))
    if step > 0:
        buttons.append(InlineKeyboardButton("⬅️ قبلی", callback_data=f"help_{step-1}"))
    rows = [buttons[i:i+2] for i in range(0, len(buttons), 2)]
    if step == 0:
        rows.append([InlineKeyboardButton("🔙 بازگشت به منو اصلی", callback_data="menu_main")])
    else:
        rows.append([InlineKeyboardButton("🔙 بازگشت", callback_data="help_0")])
    return InlineKeyboardMarkup(rows)

def help_text(step):
    if step == 0:
        return rtl_lines(
            "📖 *شروع کار با ربات*\n"
            f"{DIVIDER}\n"
            "این ربات با تحلیل ۱۰ لایه‌ای، سیگنال‌های معاملاتی فیوچرز تولید می‌کند.\n"
            "پس از شروع، ابتدا واحد پولی را انتخاب کنید.\n"
            "سپس سبک معاملاتی خود را از چهار حالت انتخاب کنید.\n"
            "در نهایت منوی اصلی نمایش داده می‌شود."
        )
    elif step == 1:
        return rtl_lines(
            "💰 *قیمت‌های لحظه‌ای*\n"
            f"{DIVIDER}\n"
            "قیمت‌ها از سه منبع دریافت می‌شوند:\n"
            "🅶 Gate.io (منبع اصلی)\n"
            "🅺 کوکوین اسپات (پشتیبان اول)\n"
            "🅲 CoinGecko (پشتیبان نهایی)\n"
            "در صورت عدم دسترسی به منبع اصلی، به‌طور خودکار از پشتیبان استفاده می‌شود."
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
            "📊 *تحلیل‌ها و سیگنال‌ها (۱۰ لایه)*\n"
            f"{DIVIDER}\n"
            "سیگنال‌ها بر اساس ۱۰ لایه تحلیل تولید می‌شوند:\n"
            "۱. ساختار بازار | ۲. هم‌گرایی تایم‌فریم | ۳. مومنتوم\n"
            "۴. حجم معاملات | ۵. احساسات بازار (جایگزین فاندینگ)\n"
            "۶. روند | ۷. جریان سفارشات | ۸. تنوع بازار\n"
            "۹. نوسان‌پذیری هوشمند | ۱۰. قدرت روند مکمل\n"
            "حداقل ۴ تا ۷ لایه (بسته به حالت) باید تأیید شوند.\n"
            "ضریب اطمینان = امتیاز وزنی لایه‌های تأییدشده.\n"
            "نرخ موفقیت تخمینی = درصد موفقیت سیگنال‌های گذشته.\n"
            "نسبت ریسک به بازده = نسبت سود بالقوه به ضرر احتمالی.\n"
            "اهرم پویا = بر اساس قدرت سیگنال و حالت معاملاتی.\n"
            "در بازار راکد (ADX پایین)، سیگنال صادر نمی‌شود."
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
            "💡 *اصطلاحات جدید*\n"
            f"{DIVIDER}\n"
            "ساختار بازار: شکست مقاومت یا برگشت از حمایت\n"
            "هم‌گرایی تایم‌فریم: همراستایی حداقل ۲ تایم‌فریم\n"
            "احساسات بازار: ترکیبی از تغییر قیمت، حجم و ترس و طمع\n"
            "جریان سفارشات: نسبت سفارشات خرید به فروش\n"
            "تنوع بازار: درصد ارزهای بالای EMA۲۰\n"
            "نوسان‌پذیری هوشمند: موقعیت قیمت در باند بولینگر\n"
            "قدرت روند مکمل: اختلاف +DI و -DI\n"
            "رژیم بازار: رونددار (ADX بالا) یا رنج (ADX پایین)\n"
            "اهرم پویا: اهرم پیشنهادی بر اساس قدرت سیگنال"
        )
    elif step == 6:
        return rtl_lines(
            "📰 *اخبار و هشدارها*\n"
            f"{DIVIDER}\n"
            "اخبار نهنگ‌ها با ایموجی متحرک ارسال می‌شوند.\n"
            "پیام‌های خبری بعد از ۱ ساعت به‌طور خودکار حذف می‌شوند.\n"
            "تاریخچه اخبار در منوی «اخبار و هشدارها» قابل مشاهده است."
        )
    else:
        return rtl_lines(
            "❓ *پرسش‌های متداول*\n"
            f"{DIVIDER}\n"
            "چطور سیگنال بگیرم؟ → انتخاب ارز → پیشنهاد لحظه‌ای\n"
            "ارسال خودکار چگونه است؟ → فقط برای ارزهای مورد علاقه، رویدادمحور\n"
            "چطور ربات را متوقف کنم؟ → دکمه توقف ربات\n"
            "آیا سیگنال‌ها تضمین سود هستند؟ → خیر، تحلیل تکنیکال است"
        )

def welcome_text():
    return rtl_lines(
        "🌟✨ *به سیگنال‌یار حرفه‌ای خوش آمدید!* ✨🌟\n"
        f"{DIVIDER}\n"
        "🤖 *ربات معاملاتی هوشمند* با تحلیل ۱۰ لایه‌ای\n"
        "🎯 *سیگنال‌های لحظه‌ای* با دقت بالا و مدیریت ریسک پویا\n"
        "📊 *تحلیل جامع ارزها* در تایم‌فریم‌های مختلف\n"
        "🔔 *اخبار نهنگ‌ها و رویدادهای مهم* به‌صورت خودکار\n"
        f"{DIVIDER}\n"
        "🚀 *چگونه شروع کنیم؟*\n"
        "۱. واحد پولی خود را انتخاب کنید\n"
        "۲. سبک معاملاتی (سریع، نیمه‌سریع، استاندارد، محافظه‌کار) را تنظیم کنید\n"
        "۳. ارزهای مورد نظر را به علاقه‌مندی‌ها اضافه کنید تا سیگنال خودکار دریافت کنید\n"
        "۴. از منوی اصلی، قیمت‌ها، سیگنال‌ها و تحلیل‌ها را مشاهده کنید\n"
        f"{DIVIDER}\n"
        "⚠️ *توجه:* تمام تحلیل‌ها تکنیکال بوده و توصیه مالی نیستند.\n"
        "🛡️ مدیریت ریسک را همواره رعایت کنید."
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
    msg = await context.bot.send_message(chat_id=chat_id, text=welcome_text(), reply_markup=kb_main(user_id), parse_mode="Markdown")
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
                            source = cache.source_for_code(code)
                            if source == "gateio":
                                ticker = await asyncio.to_thread(exchange_gateio.fetch_ticker, cache.symbol_for_code(code))
                            elif source == "kucoin":
                                ticker = await asyncio.to_thread(exchange_spot_kucoin.fetch_ticker, cache.symbol_for_code(code))
                            else:
                                current = cache.prices.get(code, 0)
                                if current > 0:
                                    changed = update_signal_status(code, current)
                                    for sid in changed:
                                        await update_channel_signal_message(sid)
                                continue
                            current = float(ticker.get("last") or ticker.get("close") or 0)
                        except Exception as e:
                            logger.debug("Trailing price fetch failed | code=%s | error=%s", code, e)
                            continue
                        if current <= 0: continue
                        changed = update_signal_status(code, current)
                        for sid in changed:
                            await update_channel_signal_message(sid)
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
                                f"🔔 بروزرسانی حد ضرر | {code}/USDT\n"
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
                important_news = await fetch_important_news()
                for news in important_news:
                    add_news_alert(news["text"], importance="high", impact=news["impact"], details={"source": news.get("source", "")})
                    if news.get("importance") == "high":
                        await send_high_importance_news_to_channel(news["text"])
                await check_and_notify_events(app)
        except Exception as e:
            logger.exception("News monitor error: %s", e)
        await asyncio.sleep(EVENTS_CHECK_SECONDS)

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
            for ev in upcoming[:5]:
                importance_emoji = "🔴" if ev.get("importance") == "high" else "🟡" if ev.get("importance") == "medium" else "🟢"
                text += f"{importance_emoji} *{ev['name']}*\n"
                text += f"🕒 {shamsi_date(ev['time'])} {ev['time'].strftime('%H:%M')}\n"
                if ev.get("description"):
                    text += f"📝 {ev['description'][:100]}...\n"
                if ev.get("impact"):
                    text += f"📊 تأثیر مورد انتظار: {ev['impact']}\n"
                text += "\n"
            try:
                msg = await app.bot.send_message(chat_id=chat_id, text=rtl_lines(text), parse_mode="Markdown")
                asyncio.create_task(delete_news_messages_after_delay(app, chat_id, msg.message_id))
            except Exception as e:
                logger.warning("Event notify failed: %s", e)

# ---------- Whale monitor ----------
async def whale_monitor_loop(app):
    await asyncio.sleep(60)
    while True:
        try:
            if subscribed_chat_ids:
                alerts = fetch_whale_alerts()
                if alerts:
                    for alert in alerts[:5]:
                        if "نزولی" in alert["impact"] or "صعودی" in alert["impact"]:
                            amount = alert["amount_btc"]
                            symbol = alert["symbol"]
                            flow = alert["flow_type"]
                            impact = alert["impact"]
                            value_usd = alert.get("value_usd", 0)
                            from_addr = alert.get("from_address", "نامشخص")
                            to_addr = alert.get("to_address", "نامشخص")
                            from_owner = alert.get("from_owner", "ناشناس")
                            to_owner = alert.get("to_owner", "ناشناس")
                            whale_emoji = "🐋" if amount > 5000 else "🐳"
                            text = (
                                f"{whale_emoji} *حرکت نهنگ بزرگ*\n"
                                f"💰 مقدار: **{amount:,.0f} {symbol}** (~{value_usd:,.0f} دلار)\n"
                                f"🔗 شبکه: {symbol}\n"
                                f"📌 از آدرس: `{from_addr}`\n"
                                f"📌 به آدرس: `{to_addr}`\n"
                                f"🏷️ برچسب مبدأ: {from_owner}\n"
                                f"🏷️ برچسب مقصد: {to_owner}\n"
                                f"📊 نوع تراکنش: {flow}\n"
                                f"📈 تأثیر احتمالی: {impact}\n"
                                f"🕒 {shamsi_now()}"
                            )
                            add_news_alert(text, importance="high", impact=impact, details=alert)
                    latest = news_history[-1] if news_history else None
                    if latest and latest.get("importance") == "high":
                        await send_high_importance_news_to_channel(latest["text"])
        except Exception as e:
            logger.exception("Whale monitor error: %s", e)
        await asyncio.sleep(WHALE_CHECK_SECONDS)

# ---------- Macro event monitor ----------
async def fetch_macro_events():
    return []

async def macro_event_monitor_loop(app):
    await asyncio.sleep(120)
    while True:
        try:
            if subscribed_chat_ids:
                events = await fetch_macro_events()
                for ev in events:
                    text = (
                        f"📰 *رویداد کلان اقتصادی*\n"
                        f"{ev.get('title', 'رویداد')}\n"
                        f"🕒 {shamsi_now()}\n"
                        f"📊 سطح اهمیت: {ev.get('importance', 'medium')}\n"
                        f"📈 تأثیر مورد انتظار: {ev.get('impact', 'نامشخص')}\n"
                        f"📝 {ev.get('description', '')[:200]}"
                    )
                    add_news_alert(text, importance=ev.get('importance', 'medium'), impact=ev.get('impact', ''))
                    for chat_id in subscribed_chat_ids:
                        msg = await app.bot.send_message(chat_id=chat_id, text=rtl_lines(text), parse_mode="Markdown")
                        asyncio.create_task(delete_news_messages_after_delay(app, chat_id, msg.message_id))
        except Exception as e:
            logger.exception("Macro event monitor error: %s", e)
        await asyncio.sleep(6 * 3600)

# ---------- Macro data loop ----------
async def macro_data_loop(app):
    await asyncio.sleep(30)
    while True:
        try:
            await cache.update_macro_data()
        except Exception as e:
            logger.exception(f"Macro data loop error: {e}")
        await asyncio.sleep(MACRO_CHECK_SECONDS)

# ---------- Periodic report ----------
async def send_periodic_report(app, period="weekly"):
    stats = compute_advanced_stats(signal_history)
    fg_value, fg_class = await get_fear_greed()
    macro_data = cache.get_macro_data()
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
    if macro_data:
        text += f"\n📊 *داده‌های کلان بازار:*\n"
        text += f"• سلطه بیت‌کوین: {macro_data.get('btc_dominance', 0):.1f}%\n"
    for chat_id in subscribed_chat_ids:
        try:
            await app.bot.send_message(chat_id=chat_id, text=rtl_lines(text), parse_mode="Markdown")
        except Exception as e:
            logger.warning("Periodic report send failed: %s", e)

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
        "sharpe": sharpe, "max_drawdown": max_dd, "expectancy": expectancy,
        "risk_of_ruin": risk_of_ruin, "total_trades": len(returns),
        "win_rate": win_rate, "profit_factor": profit_factor,
        "avg_confidence": avg_confidence, "wins": wins, "losses": losses,
    }

# ---------- Auto report loop ----------
async def auto_report_loop(app):
    await asyncio.sleep(10)
    while True:
        try:
            if subscribed_chat_ids:
                await cache.update_prices(force=True)
                await cache.update_ohlcv(force=True)
                now = time.time()
                for chat_id in list(subscribed_chat_ids):
                    role = user_role.get(chat_id, "user")
                    if role == "admin":
                        continue
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
                        plan = await generate_trade_plan_v2(code, mode, send_to_channel=True)
                        if plan:
                            current_signals[code] = plan.direction
                        await asyncio.sleep(0.5)
                    prev_signals = last_sent_signals.get(chat_id, {})
                    for code, direction in current_signals.items():
                        prev = prev_signals.get(code)
                        if prev is None or prev["direction"] != direction:
                            # Plan already generated in current_signals loop
                            # We need to send to user but avoid duplicate channel send
                            plan = await generate_trade_plan_v2(code, mode, send_to_channel=False)
                            if plan:
                                main_text = format_main_signal_v2(plan, code, chat_id)
                                msg = await app.bot.send_message(chat_id=chat_id, text=main_text, reply_markup=kb_signal_details(code), parse_mode="Markdown")
                                active_signals.setdefault(chat_id, {})[code] = {"plan": plan, "stage": 0, "last_notified": 0}
                                prev_signals[code] = {"direction": direction, "timestamp": time.time()}
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

# ---------- Command handlers ----------
async def start(update, context):
    if not await guard(update): return
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    if is_admin(user_id):
        await clear_interactive_screen(context, chat_id)
        msg = await update.message.reply_text("🔐 لطفاً نقش خود را انتخاب کنید:", reply_markup=kb_role_selection())
        set_interactive_screen(chat_id, [msg.message_id])
    else:
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
    role = user_role.get(chat_id, "user")
    mode = user_trading_mode.get(chat_id, "standard") if role == "user" else "standard"
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
    macro_data = cache.get_macro_data()
    text = (
        f"📊 *وضعیت سیستم*\n🕒 {shamsi_now()}\n{DIVIDER}\n"
        f"⏳ مدت زمان اجرا: `{uptime_str}`\n"
        f"👥 اعضای فعال: {len(subscribed_chat_ids)}\n"
        f"⚡ سیگنال‌های فعال: {len(last_plans)}\n"
        f"🔁 سیگنال‌های دنبال‌شده (تریلینگ): {active_trailing_count}\n"
        f"📊 کل سیگنال‌های تولیدشده: {TOTAL_SIGNALS_GENERATED}\n"
        f"🕒 آخرین بروزرسانی سیگنال: {last_update_str}\n"
        f"🧭 شاخص ترس و طمع: {fg_value if fg_value is not None else '-'} ({fg_class if fg_class else '-'})\n"
    )
    if macro_data:
        text += f"📊 سلطه BTC: {macro_data.get('btc_dominance', 0):.1f}%\n"
    text += (
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
    if not is_admin_role(update.effective_chat.id):
        await update.message.reply_text("⛔️ فقط ادمین.")
        return
    stats = compute_advanced_stats(signal_history)
    fg_value, fg_class = await get_fear_greed()
    macro_data = cache.get_macro_data()
    text = (
        f"📈 *داشبورد تحلیلی*\n🕒 {shamsi_now()}\n{DIVIDER}\n"
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
    )
    if macro_data:
        text += f"📊 سلطه BTC: {macro_data.get('btc_dominance', 0):.1f}%\n"
    text += f"{DIVIDER}\n🕒 آخرین سیگنال‌ها:\n"
    for rec in signal_history[-5:]:
        status_emoji = "🟢" if rec["status"].startswith("tp") else "🔴" if rec["status"] == "sl_hit" else "⏳"
        text += f"{status_emoji} {rec['symbol']} {rec['direction']} @ {rec['entry_price']:.4f} — {rec['status']}\n"
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
        importance_emoji = "🔴" if ev.get("importance") == "high" else "🟡" if ev.get("importance") == "medium" else "🟢"
        text += f"{importance_emoji} *{ev['name']}*\n"
        text += f"🕒 {shamsi_date(ev['time'])} {ev['time'].strftime('%H:%M')}\n"
        if ev.get("description"):
            text += f"📝 {ev['description'][:100]}...\n"
        if ev.get("impact"):
            text += f"📊 تأثیر مورد انتظار: {ev['impact']}\n"
        text += "\n"
    await update.message.reply_text(rtl_lines(text), parse_mode="Markdown")

async def periodic_report_command(update, context):
    if not await guard(update): return
    if not is_admin_role(update.effective_chat.id):
        await update.message.reply_text("⛔️ فقط ادمین.")
        return
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
                "user_role": {str(k): v for k, v in user_role.items()},
                "news_history": news_history[-20:],
                "signal_history": signal_history[-200:],
                "suggestion_history": suggestion_history[-20:],
                "channel_signal_messages": {str(k): v for k, v in channel_signal_messages.items()},
            }, f, ensure_ascii=False)
        os.replace(tmp, STATE_FILE)
    except Exception as e:
        logger.warning("State save failed: %s", e)

def load_state():
    global subscribed_chat_ids, user_currency, user_trading_mode, user_favorites, user_role, news_history, signal_history, suggestion_history, channel_signal_messages
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        subscribed_chat_ids = {int(x) for x in data.get("subscribed_chat_ids", [])}
        user_currency = {int(k): v for k, v in data.get("user_currency", {}).items()}
        user_trading_mode = {int(k): v for k, v in data.get("user_trading_mode", {}).items()}
        user_favorites = {int(k): set(v) for k, v in data.get("user_favorites", {}).items()}
        user_role = {int(k): v for k, v in data.get("user_role", {}).items()}
        news_history = data.get("news_history", [])
        signal_history = data.get("signal_history", [])
        suggestion_history = data.get("suggestion_history", [])
        channel_signal_messages = {str(k): int(v) for k, v in data.get("channel_signal_messages", {}).items()}
        logger.info("State restored: %s users, %s signals, %s suggestions, %s channel messages",
                    len(subscribed_chat_ids), len(signal_history), len(suggestion_history), len(channel_signal_messages))
    except FileNotFoundError:
        logger.info("No state file; starting fresh.")
        news_history = []
        signal_history = []
        suggestion_history = []
        channel_signal_messages = {}
    except Exception as e:
        logger.warning("State load failed: %s", e)
        news_history = []
        signal_history = []
        suggestion_history = []
        channel_signal_messages = {}

# ---------- Button handler ----------
async def button_handler(update, context):
    if not await guard(update): return
    query = update.callback_query; await query.answer()
    data = query.data; chat_id = update.effective_chat.id; user_id = update.effective_user.id
    if data == "noop": return

    if data == "optimization_center":
        await optimization_center(update, context)
        return
    if data == "optimization_active":
        await optimization_active(update, context)
        return
    if data == "optimization_history":
        await optimization_history(update, context)
        return

    if data.startswith("apply_suggestion_") or data.startswith("reject_suggestion_") or data.startswith("details_suggestion_"):
        await handle_suggestion_action(update, context)
        return

    if data == "comprehensive_analysis":
        await comprehensive_analysis(update, context)
        return

    if data == "role_admin":
        user_role[chat_id] = "admin"
        save_state()
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text("👑 وارد حالت ادمین شدید.\nحالا واحد پولی را انتخاب کنید:", reply_markup=kb_currency())
        return
    if data == "role_user":
        user_role[chat_id] = "user"
        save_state()
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text("👤 وارد حالت کاربر عادی شدید. واحد پولی را انتخاب کنید:", reply_markup=kb_currency())
        return

    if data.startswith("cur_"):
        user_currency[chat_id] = data.split("_", 1)[1]
        subscribed_chat_ids.add(chat_id)
        save_state()
        if user_role.get(chat_id, "user") == "admin":
            await query.edit_message_text("✅ واحد پولی انتخاب شد. منوی اصلی:")
            await finish_start(context, chat_id, user_id)
        else:
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
        if user_role.get(chat_id, "user") == "admin":
            await query.answer("ادمین حالت ثابت ندارد.", show_alert=True)
            return
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text("🛠️ سبک معاملاتی جدید را انتخاب کن:", reply_markup=kb_mode_selection())
        return

    if data == "restart_bot":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        if is_admin(user_id):
            await query.edit_message_text("🔐 لطفاً نقش خود را انتخاب کنید:", reply_markup=kb_role_selection())
        else:
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
        role = user_role.get(chat_id, "user")
        mode = user_trading_mode.get(chat_id, "standard") if role == "user" else "standard"
        await query.edit_message_text(MAIN_MENU_HEADER, reply_markup=kb_main(user_id, mode), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id]); return

    if data == "events_menu":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        await query.edit_message_text("📋 *منوی رویدادها*\n" + DIVIDER + "\n" + MENU_PROMPT, reply_markup=kb_events_menu(), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id]); return

    if data == "events_upcoming":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        events = await get_upcoming_events(force=True)
        now_utc = datetime.now(tz=TEHRAN_TZ) if TEHRAN_TZ else datetime.now()
        upcoming = [ev for ev in events if ev["time"].tzinfo is None or (ev["time"] - now_utc) >= timedelta(0)]
        if not upcoming:
            text = "📅 رویداد مهمی در آینده نزدیک یافت نشد."
        else:
            text = "📅 *رویدادهای کریپتویی پیش رو:*\n" + DIVIDER + "\n"
            for ev in upcoming[:10]:
                importance_emoji = "🔴" if ev.get("importance") == "high" else "🟡" if ev.get("importance") == "medium" else "🟢"
                text += f"{importance_emoji} *{ev['name']}*\n"
                text += f"🕒 {shamsi_date(ev['time'])} {ev['time'].strftime('%H:%M')}\n"
                if ev.get("description"):
                    text += f"📝 {ev['description'][:100]}...\n"
                if ev.get("impact"):
                    text += f"📊 تأثیر مورد انتظار: {ev['impact']}\n"
                text += "\n"
        await query.edit_message_text(rtl_lines(text), reply_markup=kb_back_to_events(), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id])
        return

    if data == "events_news":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        if not news_history:
            text = "📰 *تاریخچه اخبار و هشدارها*\n" + DIVIDER + "\n\nهیچ خبری ثبت نشده است."
        else:
            text = "📰 *تاریخچه اخبار و هشدارها*\n" + DIVIDER + "\n"
            for item in reversed(news_history[-20:]):
                importance_emoji = "🔴" if item.get("importance") == "high" else "🟡" if item.get("importance") == "medium" else "🟢"
                text += f"{importance_emoji} {item['time']}\n{item['text']}\n\n"
        await query.edit_message_text(rtl_lines(text), reply_markup=kb_back_to_events(), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id])
        return

    if data == "dashboard":
        if not is_admin_role(chat_id):
            await query.answer("⛔️ فقط ادمین.", show_alert=True); return
        stats = compute_advanced_stats(signal_history)
        fg_value, fg_class = await get_fear_greed()
        macro_data = cache.get_macro_data()
        text = (
            f"📈 *داشبورد تحلیلی*\n🕒 {shamsi_now()}\n{DIVIDER}\n"
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
        )
        if macro_data:
            text += f"📊 سلطه BTC: {macro_data.get('btc_dominance', 0):.1f}%\n"
        text += f"{DIVIDER}\n🕒 آخرین سیگنال‌ها:\n"
        for rec in signal_history[-5:]:
            status_emoji = "🟢" if rec["status"].startswith("tp") else "🔴" if rec["status"] == "sl_hit" else "⏳"
            text += f"{status_emoji} {rec['symbol']} {rec['direction']} @ {rec['entry_price']:.4f} — {rec['status']}\n"
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
                if status == "SWAP OK": label = f"{code} 🟢"
                elif status == "TICKER ERROR": label = f"{code} 🟠"
                else: label = f"{code} ⚪"
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
            await query.edit_message_reply_markup(reply_markup=kb_coin_detail(code, code in favs, is_admin_role=is_admin_role(chat_id)))
        except Exception:
            pass
        return

    if data == "periodic_report":
        if not is_admin_role(chat_id):
            await query.answer("⛔️ فقط ادمین.", show_alert=True); return
        await query.edit_message_text("📊 لطفاً دوره‌ی گزارش را انتخاب کنید:", reply_markup=kb_periodic_report())
        return

    if data.startswith("report_period_"):
        if not is_admin_role(chat_id):
            await query.answer("⛔️ فقط ادمین.", show_alert=True); return
        period = data.split("report_period_", 1)[1]
        text = f"📊 *گزارش {'هفتگی' if period == 'weekly' else 'ماهانه'}*\n" + DIVIDER + "\n"
        for mode, config in MODE_CONFIGS.items():
            stats = compute_advanced_stats(signal_history, mode)
            text += (
                f"{config['label']}\n"
                f"تعداد سیگنال‌ها: {stats['total_trades']} | برد: {stats['wins']} | باخت: {stats['losses']} | نرخ برد: {stats['win_rate']:.1f}%\n"
                f"فاکتور سود: {stats['profit_factor']:.2f} | Expectancy: {stats['expectancy']:.2f} | MaxDD: {stats['max_drawdown']:.2f}\n"
                f"Sharpe: {stats['sharpe']:.2f} | میانگین اطمینان: {stats['avg_confidence']:.1f}%\n\n"
            )
        await query.edit_message_text(rtl_lines(text), reply_markup=kb_back_main(), parse_mode="Markdown")
        return

    if data == "admin_compare":
        if not is_admin_role(chat_id):
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
        return

    if data.startswith("coins_page_"):
        page = int(data.split("_")[2])
        await query.edit_message_reply_markup(reply_markup=kb_coins(page))
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
        await query.edit_message_text(rtl_lines(f"🪙 *انتخاب ارز مورد نظر*\n{DIVIDER}\n{MENU_PROMPT}"), reply_markup=kb_coins(0), parse_mode="Markdown")
        set_interactive_screen(chat_id, [query.message.message_id]); return

    if data.startswith("coin_"):
        code = data.split("_", 1)[1]
        if code not in COIN_CODES: return
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        if code in cache.exchange_symbols:
            status = cache.market_status.get(code, {}).get("status")
            warning = ""
            if status == "TICKER ERROR":
                warning = "⚠️ قیمت لحظه‌ای در دسترس نیست، اما تحلیل‌های دیگر کار می‌کنند.\n\n"
            favs = user_favorites.get(chat_id, set())
            is_fav = code in favs
            admin = is_admin_role(chat_id)
            await query.edit_message_text(
                rtl_lines(f"{code}\n{DIVIDER}\n{warning}🟢 وضعیت بازار: *SWAP OK*\n{MENU_PROMPT}"),
                reply_markup=kb_coin_detail(code, is_fav, is_admin_role=admin),
                parse_mode="Markdown",
            )
            set_interactive_screen(chat_id, [query.message.message_id])
        else:
            text = f"{code}\n{DIVIDER}\n⚪ وضعیت: *NO SWAP*\nدر حال حاضر قرارداد USDT Perpetual فعال برای این ارز در KuCoin پیدا نشد."
            await query.edit_message_text(rtl_lines(text), reply_markup=kb_back_main(), parse_mode="Markdown")
            set_interactive_screen(chat_id, [query.message.message_id])
        return

    # ----- بخش ادمین -----
    if data.startswith("askmode_"):
        if not is_admin_role(chat_id):
            await query.answer("⛔️ فقط ادمین.", show_alert=True); return
        parts = data.split("_", 2)
        action = parts[1]
        code = parts[2]
        if action == "weekly":
            try:
                summary = await asyncio.wait_for(generate_weekly_summary_async(code, chat_id), timeout=30)
                await query.edit_message_text(split_long_message(summary)[0], reply_markup=kb_weekly(code), parse_mode="Markdown")
                set_interactive_screen(chat_id, [query.message.message_id])
            except Exception as e:
                logger.exception("Weekly UI error | code=%s: %s", code, e)
                await query.edit_message_text(f"❌ خطا در تحلیل جامع ارز {code}.", reply_markup=kb_back_main())
            return
        else:
            await query.edit_message_text(
                f"🛠️ حالت معاملاتی برای {action} {code} را انتخاب کن:",
                reply_markup=kb_mode_selection_for_action(action, code),
            )
            return

    if data.startswith("run_"):
        parts = data.split("_", 3)
        action = parts[1]
        code = parts[2]
        mode = parts[3]
        if code not in COIN_CODES: return
        status = cache.market_status.get(code, {}).get("status")
        if status != "SWAP OK":
            await query.edit_message_text(f"⚠️ قرارداد {code} در KuCoin در دسترس نیست.\nوضعیت: {status}", reply_markup=kb_back_main())
            return
        if action == "suggest":
            try:
                text = await asyncio.wait_for(generate_status_text_async(code, chat_id, mode), timeout=30)
                await query.edit_message_text(split_long_message(text)[0], reply_markup=kb_suggestion(code), parse_mode="Markdown")
                set_interactive_screen(chat_id, [query.message.message_id])
            except Exception as e:
                logger.exception("Signal UI error | code=%s: %s", code, e)
                await query.edit_message_text(f"❌ خطا در دریافت اطلاعات {code}.", reply_markup=kb_back_main())
        elif action == "instant":
            try:
                plan = await asyncio.wait_for(generate_trade_plan_v2(code, mode), timeout=30)
                if plan is None:
                    await query.edit_message_text(
                        f"💤 فعلاً سیگنال نهایی برای {code} وجود ندارد.\nدلایل احتمالی: ADX پایین، عدم تأیید کافی لایه‌ها، یا نسبت R/R نامناسب.",
                        reply_markup=kb_back_to_coin(code),
                        parse_mode="Markdown"
                    )
                    return
                main_text = format_main_signal_v2(plan, code, chat_id)
                await query.edit_message_text(main_text, reply_markup=kb_signal_details(code), parse_mode="Markdown")
                active_signals.setdefault(chat_id, {})[code] = {"plan": plan, "stage": 0, "last_notified": 0}
            except Exception as e:
                logger.exception("Signal UI error | code=%s: %s", code, e)
                await query.edit_message_text(f"❌ خطا در دریافت اطلاعات {code}.", reply_markup=kb_back_to_coin(code))
        elif action == "weekly":
            try:
                summary = await asyncio.wait_for(generate_weekly_summary_async(code, chat_id), timeout=30)
                await query.edit_message_text(split_long_message(summary)[0], reply_markup=kb_weekly(code), parse_mode="Markdown")
                set_interactive_screen(chat_id, [query.message.message_id])
            except Exception as e:
                logger.exception("Weekly UI error | code=%s: %s", code, e)
                await query.edit_message_text(f"❌ خطا در تحلیل جامع ارز {code}.", reply_markup=kb_back_main())
        return

    # ----- کاربر عادی -----
    if data.startswith("suggest_"):
        if is_admin_role(chat_id):
            return
        code = data.split("suggest_", 1)[1]
        if code not in COIN_CODES: return
        mode = user_trading_mode.get(chat_id, "standard")
        try:
            text = await asyncio.wait_for(generate_status_text_async(code, chat_id, mode), timeout=30)
            await query.edit_message_text(split_long_message(text)[0], reply_markup=kb_suggestion(code), parse_mode="Markdown")
            set_interactive_screen(chat_id, [query.message.message_id])
        except Exception as e:
            logger.exception("Signal UI error | code=%s: %s", code, e)
            await query.edit_message_text(f"❌ خطا در دریافت اطلاعات {code}.", reply_markup=kb_back_main())
        return

    if data.startswith("instant_"):
        if is_admin_role(chat_id):
            return
        code = data.split("instant_", 1)[1]
        if code not in COIN_CODES: return
        mode = user_trading_mode.get(chat_id, "standard")
        try:
            plan = await asyncio.wait_for(generate_trade_plan_v2(code, mode), timeout=30)
            if plan is None:
                await query.edit_message_text(
                    f"💤 فعلاً سیگنال نهایی برای {code} وجود ندارد.\nدلایل احتمالی: ADX پایین، عدم تأیید کافی لایه‌ها، یا نسبت R/R نامناسب.",
                    reply_markup=kb_back_to_coin(code),
                    parse_mode="Markdown"
                )
                return
            main_text = format_main_signal_v2(plan, code, chat_id)
            await query.edit_message_text(main_text, reply_markup=kb_signal_details(code), parse_mode="Markdown")
            active_signals.setdefault(chat_id, {})[code] = {"plan": plan, "stage": 0, "last_notified": 0}
        except Exception as e:
            logger.exception("Signal UI error | code=%s: %s", code, e)
            await query.edit_message_text(f"❌ خطا در دریافت اطلاعات {code}.", reply_markup=kb_back_to_coin(code))
        return

    if data.startswith("weekly_"):
        if is_admin_role(chat_id):
            return
        code = data.split("weekly_", 1)[1]
        if code not in COIN_CODES: return
        try:
            summary = await asyncio.wait_for(generate_weekly_summary_async(code, chat_id), timeout=30)
            await query.edit_message_text(split_long_message(summary)[0], reply_markup=kb_weekly(code), parse_mode="Markdown")
            set_interactive_screen(chat_id, [query.message.message_id])
        except Exception as e:
            logger.exception("Weekly UI error | code=%s: %s", code, e)
            await query.edit_message_text(f"❌ خطا در تحلیل جامع ارز {code}.", reply_markup=kb_back_main())
        return

    if data.startswith("details_"):
        code = data.split("_", 1)[1]
        mode = user_trading_mode.get(chat_id, "standard")
        try:
            ind = await cache.get_indicators(code, mode)
            if not ind:
                await query.edit_message_text("⚠️ داده کافی نیست.", reply_markup=kb_back_main())
                return
            plan = await generate_trade_plan_v2(code, mode)
            if not plan:
                await query.edit_message_text("💤 سیگنال فعلی موجود نیست.\nدلایل احتمالی: ADX پایین یا عدم تأیید کافی لایه‌ها.", reply_markup=kb_back_main())
                return
            details_text = format_technical_details(code, plan, ind, chat_id)
            await query.edit_message_text(split_long_message(details_text)[0], reply_markup=kb_back_to_signal(code), parse_mode="Markdown")
        except Exception as e:
            logger.exception("Details UI error | code=%s: %s", code, e)
            await query.edit_message_text(f"❌ خطا در نمایش جزئیات {code}.", reply_markup=kb_back_main())
        return

    if data == "admin_panel":
        if not is_admin_role(chat_id):
            await query.answer("⛔️ فقط ادمین.", show_alert=True); return
        ok = sum(1 for c in COIN_CODES if cache.market_status.get(c, {}).get("status") == "SWAP OK")
        no_swap = sum(1 for c in COIN_CODES if cache.market_status.get(c, {}).get("status") == "NO SWAP")
        ticker_error = sum(1 for c in COIN_CODES if cache.market_status.get(c, {}).get("status") == "TICKER ERROR")
        uptime_sec = time.time() - START_TIME
        hours, remainder = divmod(uptime_sec, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{int(hours)}:{int(minutes):02d}:{int(seconds):02d}"
        fg_value, fg_class = await get_fear_greed()
        macro_data = cache.get_macro_data()
        text = (
            f"🛠️ *پنل مدیریت*\n{DIVIDER}\n🕒 {shamsi_now()}\n"
            f"⏳ مدت اجرا: `{uptime_str}`\n"
            f"👥 اعضای فعال: {len(subscribed_chat_ids)}\n"
            f"⚡ سیگنال‌های فعال: {len(last_plans)}\n"
            f"🔁 سیگنال‌های دنبال‌شده: {sum(len(s) for s in active_signals.values())}\n"
            f"📊 کل سیگنال‌ها: {len(signal_history)}\n"
            f"🧭 شاخص ترس و طمع: {fg_value if fg_value is not None else '-'} ({fg_class if fg_class else '-'})\n"
        )
        if macro_data:
            text += f"📊 سلطه BTC: {macro_data.get('btc_dominance', 0):.1f}%\n"
        text += (
            f"{DIVIDER}\n"
            f"🪙 کل ارزها: {len(COIN_CODES)}\n"
            f"🟢 SWAP OK: {ok}\n⚪ NO SWAP: {no_swap}\n🟠 TICKER ERROR: {ticker_error}\n"
            f"📊 قیمت‌های دریافت‌شده: {len(cache.prices)} ارز\n"
            f"📦 داده‌ها: 5m={len(cache.ohlcv.get('5m',{}))} 15m={len(cache.ohlcv.get('15m',{}))} 1h={len(cache.ohlcv.get('1h',{}))} 4h={len(cache.ohlcv.get('4h',{}))} 1d={len(cache.ohlcv.get('1d',{}))}\n"
            f"{DIVIDER}\n"
            f"📋 *آمار حالت‌ها:*\n"
        )
        for mode, config in MODE_CONFIGS.items():
            stats = compute_advanced_stats(signal_history, mode)
            text += f"{config['label']}: {stats['total_trades']} سیگنال | برد {stats['wins']} | باخت {stats['losses']} | نرخ برد {stats['win_rate']:.1f}%\n"
        text += f"\n🕒 آخرین سیگنال‌ها:\n"
        for rec in signal_history[-5:]:
            status_emoji = "🟢" if rec["status"].startswith("tp") else "🔴" if rec["status"] == "sl_hit" else "⏳"
            text += f"{status_emoji} {rec['symbol']} {rec['direction']} @ {rec['entry_price']:.4f} ({MODE_CONFIGS.get(rec['mode'],{}).get('label','')})\n"
        await query.edit_message_text(rtl_lines(text), reply_markup=kb_admin_panel(), parse_mode="Markdown")
        return

    if data == "menu_all":
        if not is_admin_role(chat_id):
            await query.answer("⛔️ فقط ادمین.", show_alert=True); return
        await query.edit_message_text("⏳ در حال تحلیل همه ارزها (برای ادمین)...")
        try:
            mode = "standard"
            plans = {}
            for code in COIN_CODES[:20]:
                plan = await generate_trade_plan_v2(code, mode)
                if plan:
                    plans[code] = plan
                await asyncio.sleep(0.5)
        except Exception as e:
            logger.exception("menu_all error: %s", e)
            await query.edit_message_text(f"❌ خطا: {e}", reply_markup=kb_back_main()); return
        if not plans:
            text = "📋 فعلاً سیگنال نهایی نداریم."
        else:
            sorted_plans = sorted(plans.values(), key=lambda p: p.confidence, reverse=True)
            full_text = "📋 *نمایش پیشنهادات*\n\n" + "\n\n".join(format_main_signal_v2(p, p.symbol, chat_id) for p in sorted_plans)
            chunks = split_long_message(full_text)
            new_ids = []
            await query.edit_message_text(chunks[0], parse_mode="Markdown"); new_ids.append(query.message.message_id)
            for chunk in chunks[1:]:
                m = await context.bot.send_message(chat_id=chat_id, text=chunk, parse_mode="Markdown")
                new_ids.append(m.message_id)
            set_interactive_screen(chat_id, new_ids)
        return

    # دکمه جدید: نمایش همه سیگنال‌های فعال
    if data == "active_signals_all":
        await clear_interactive_screen(context, chat_id, keep_id=query.message.message_id)
        # دریافت آخرین سیگنال‌ها از signal_history (تا ۲۰ مورد)
        recent_signals = signal_history[-20:]
        if not recent_signals:
            text = "📡 *سیگنال‌های فعال*\n\nهنوز سیگنالی ثبت نشده است."
        else:
            text = "📡 *سیگنال‌های فعال (آخرین ۲۰)*\n" + DIVIDER + "\n"
            for rec in reversed(recent_signals):
                direction_emoji = "🟢" if rec["direction"] == "LONG" else "🔴"
                mode_label = MODE_CONFIGS.get(rec["mode"], MODE_CONFIGS["standard"])["label"]
                status_text = "باز" if rec["status"] == "open" else rec["status"]
                text += (
                    f"{rec['symbol']} | {rec['direction']} {direction_emoji} | {mode_label}\n"
                    f"   اطمینان: {rec['confidence']:.0f}٪ | RR: {rec['rr']:.2f} | وضعیت: {status_text}\n"
                    f"   ورود: {rec['entry_price']:.4f} | SL: {rec['sl_price']:.4f}\n"
                    f"   TP1: {rec['tp_prices'][0]:.4f} | TP2: {rec['tp_prices'][1]:.4f} | TP3: {rec['tp_prices'][2]:.4f}\n"
                    f"{DIVIDER}\n"
                )
        await query.edit_message_text(
            rtl_lines(text),
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 بازگشت", callback_data="menu_coins")]]),
            parse_mode="Markdown"
        )
        set_interactive_screen(chat_id, [query.message.message_id])
        return

def format_technical_details(code, plan, ind, chat_id):
    direction = "لانگ 🟢" if plan.direction == "LONG" else "شورت 🔴"
    reasons_text = "\n".join(f" ✅ {x}" for x in plan.reasons[:15])
    warnings_text = "\n" + "\n".join(f" ⚠️ {x}" for x in plan.warnings) if plan.warnings else ""
    text = (
        f"📊 *جزئیات فنی* {code}/USDT\n"
        f"🕒 {shamsi_now()}\n{DIVIDER}\n"
        f"جهت: {direction}\n"
        f"امتیاز نهایی: {plan.confidence:.0f}٪\n"
        f"{DIVIDER}\n"
        f"📈 *دلایل سیگنال*\n{reasons_text}{warnings_text}\n\n"
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
        f"حمایت: {fmt_amount(ind['support'], chat_id)} | مقاومت: {fmt_amount(ind['resistance'], chat_id)}\n"
        f"{DIVIDER}\n"
        f"⚠️ تحلیل تکنیکال است و تضمین سود نیست."
    )
    return rtl_lines(text)

async def delete_news_messages_after_delay(app, chat_id, message_id, delay=NEWS_AUTO_DELETE_SECONDS):
    await asyncio.sleep(delay)
    try:
        await app.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception:
        pass

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
    app.create_task(macro_event_monitor_loop(app))
    app.create_task(macro_data_loop(app))
    app.create_task(optimization_loop(app))
    app.create_task(channel_broadcast_loop(app))
    logger.info("Signal Bot V59 (Channel + Active Signals) started")

def main():
    global app
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
