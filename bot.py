import os
import sys
import logging
import asyncio
import aiosqlite
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any

import pandas as pd
import numpy as np
import ccxt.async_support as ccxt

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import TelegramError, BadRequest

# ==========================================
# 1. CONFIGURATION & ENVIRONMENT SETUP
# ==========================================

class Config:
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")
    CHANNEL_ID: str = os.getenv("CHANNEL_ID", "@your_channel_username")
    ADMIN_IDS: List[int] = [int(x) for x in os.getenv("ADMIN_IDS", "123456789").split(",") if x.strip()]
    
    EXCHANGE_NAME: str = os.getenv("EXCHANGE_NAME", "mexc")
    PRIMARY_TIMEFRAME: str = os.getenv("PRIMARY_TIMEFRAME", "1h")
    HIGHER_TIMEFRAME: str = os.getenv("HIGHER_TIMEFRAME", "4h")
    POLL_INTERVAL: int = int(os.getenv("POLL_INTERVAL", "60"))
    COOLDOWN_HOURS: int = int(os.getenv("COOLDOWN_HOURS", "2"))
    DB_FILE: str = os.getenv("DB_FILE", "bot_database.db")
    
    # اندیکاتورها
    EMA_PERIOD: int = 200
    RSI_PERIOD: int = 14
    ATR_PERIOD: int = 14
    VOL_SMA_PERIOD: int = 20

    DEFAULT_SYMBOLS: List[str] = [
        "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
        "XRP/USDT", "ADA/USDT", "DOGE/USDT", "AVAX/USDT",
        "LINK/USDT", "DOT/USDT", "NEAR/USDT", "PEPE/USDT",
        "SHIB/USDT", "FLOKI/USDT", "BONK/USDT", "TON/USDT",
        "SUI/USDT", "APT/USDT", "ARBITRUM/USDT", "1000SATS/USDT"
    ]

# ==========================================
# 2. LOGGING CONFIGURATION
# ==========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(name)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("SignalBotEngine")

# ==========================================
# 3. DATABASE MANAGER (SQLITE ASYNC)
# ==========================================

class DatabaseManager:
    def __init__(self, db_path: str = Config.DB_FILE):
        self.db_path = db_path

    async def init_db(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS symbols (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT UNIQUE NOT NULL,
                    is_active INTEGER DEFAULT 1
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    signal_type TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    tp1 REAL NOT NULL,
                    tp2 REAL NOT NULL,
                    sl REAL NOT NULL,
                    status TEXT DEFAULT 'OPEN',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS cooldowns (
                    symbol TEXT PRIMARY KEY,
                    expire_at TIMESTAMP NOT NULL
                )
            """)
            await db.commit()

            cursor = await db.execute("SELECT COUNT(*) FROM symbols")
            count = await cursor.fetchone()
            if count and count[0] == 0:
                for sym in Config.DEFAULT_SYMBOLS:
                    await db.execute("INSERT OR IGNORE INTO symbols (symbol, is_active) VALUES (?, 1)", (sym,))
                await db.commit()

    async def get_active_symbols(self) -> List[str]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT symbol FROM symbols WHERE is_active = 1") as cursor:
                rows = await cursor.fetchall()
                return [row[0] for row in rows]

    async def add_symbol(self, symbol: str) -> bool:
        formatted = symbol.upper().strip()
        if "/" not in formatted:
            formatted += "/USDT"
        async with aiosqlite.connect(self.db_path) as db:
            try:
                await db.execute("INSERT INTO symbols (symbol, is_active) VALUES (?, 1) ON CONFLICT(symbol) DO UPDATE SET is_active=1", (formatted,))
                await db.commit()
                return True
            except Exception as e:
                logger.error(f"Error adding symbol to DB: {e}")
                return False

    async def remove_symbol(self, symbol: str) -> bool:
        formatted = symbol.upper().strip()
        if "/" not in formatted:
            formatted += "/USDT"
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE symbols SET is_active = 0 WHERE symbol = ?", (formatted,))
            await db.commit()
            return True

    async def save_signal(self, symbol: str, signal_type: str, entry: float, tp1: float, tp2: float, sl: float) -> int:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "INSERT INTO signals (symbol, signal_type, entry_price, tp1, tp2, sl) VALUES (?, ?, ?, ?, ?, ?)",
                (symbol, signal_type, entry, tp1, tp2, sl)
            )
            await db.commit()
            return cursor.lastrowid

    async def get_open_signals(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM signals WHERE status = 'OPEN'") as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]

    async def update_signal_status(self, signal_id: int, status: str):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("UPDATE signals SET status = ? WHERE id = ?", (status, signal_id))
            await db.commit()

    async def set_cooldown(self, symbol: str, hours: int):
        expire_at = datetime.now() + timedelta(hours=hours)
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO cooldowns (symbol, expire_at) VALUES (?, ?)",
                (symbol, expire_at.isoformat())
            )
            await db.commit()

    async def is_in_cooldown(self, symbol: str) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT expire_at FROM cooldowns WHERE symbol = ?", (symbol,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    expire_at = datetime.fromisoformat(row[0])
                    if datetime.now() < expire_at:
                        return True
                    else:
                        await db.execute("DELETE FROM cooldowns WHERE symbol = ?", (symbol,))
                        await db.commit()
                return False

    async def clear_all_cooldowns(self):
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("DELETE FROM cooldowns")
            await db.commit()

    async def get_stats(self) -> Dict[str, int]:
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute("SELECT COUNT(*) FROM signals") as c1:
                total = (await c1.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM signals WHERE status = 'TP1_HIT' OR status = 'TP2_HIT'") as c2:
                won = (await c2.fetchone())[0]
            async with db.execute("SELECT COUNT(*) FROM signals WHERE status = 'SL_HIT'") as c3:
                lost = (await c3.fetchone())[0]
            return {"total": total, "won": won, "lost": lost}

db_manager = DatabaseManager()

# ==========================================
# 4. TECHNICAL INDICATOR CALCULATOR
# ==========================================

class TechnicalAnalysisEngine:
    @staticmethod
    def calculate_all(ohlcv_data: List[List[Any]]) -> Tuple[float, float, float, float, bool]:
        df = pd.DataFrame(
            ohlcv_data, 
            columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
        )
        
        df['ema200'] = df['close'].ewm(span=Config.EMA_PERIOD, adjust=False).mean()
        
        delta = df['close'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=Config.RSI_PERIOD).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=Config.RSI_PERIOD).mean()
        rs = gain / loss
        df['rsi'] = 100 - (100 / (1 + rs))

        tr1 = df['high'] - df['low']
        tr2 = np.abs(df['high'] - df['close'].shift())
        tr3 = np.abs(df['low'] - df['close'].shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        df['atr'] = tr.rolling(window=Config.ATR_PERIOD).mean()

        df['vol_sma20'] = df['volume'].rolling(window=Config.VOL_SMA_PERIOD).mean()

        last = df.iloc[-1]
        is_high_volume = float(last['volume']) > float(last['vol_sma20'])

        return (
            float(last['close']),
            float(last['ema200']),
            float(last['rsi']),
            float(last['atr']),
            bool(is_high_volume)
        )

# ==========================================
# 5. STRATEGY & MULTI-TIMEFRAME ENGINE
# ==========================================

class StrategyEngine:
    @staticmethod
    def evaluate(
        symbol: str, 
        price: float, 
        ema200_1h: float, 
        rsi_1h: float, 
        atr_1h: float, 
        is_vol_high: float,
        price_4h: float,
        ema200_4h: float
    ) -> Tuple[bool, Optional[str], Optional[InlineKeyboardMarkup], Optional[Dict[str, float]]]:
        
        if price <= 0 or ema200_1h <= 0 or atr_1h <= 0 or not is_vol_high:
            return False, None, None, None

        higher_trend_bullish = price_4h > ema200_4h
        diff_pct = abs(price - ema200_1h) / ema200_1h * 100

        signal_type = None
        is_long = None
        confidence = 0
        leverage = "1x"
        matched = False

        # ۱. تحلیل رنج (Range)
        if diff_pct <= 2.0:
            if rsi_1h <= 30 and higher_trend_bullish:
                signal_type = "BUY / LONG (Range Low + 4H Bullish)"
                is_long = True
                confidence = 82
                leverage = "2x - 5x"
                matched = True
            elif rsi_1h >= 70 and not higher_trend_bullish:
                signal_type = "SELL / SHORT (Range High + 4H Bearish)"
                is_long = False
                confidence = 82
                leverage = "2x - 5x"
                matched = True

        # ۲. تحلیل صعودی (Bullish Trend)
        elif price > ema200_1h and higher_trend_bullish:
            if rsi_1h <= 35:
                signal_type = "BUY / LONG (Strong Dip)"
                is_long = True
                confidence = 94
                leverage = "5x - 10x"
                matched = True
            elif 40 <= rsi_1h <= 48:
                signal_type = "BUY / LONG (Trend Continuation)"
                is_long = True
                confidence = 88
                leverage = "3x - 5x"
                matched = True

        # ۳. تحلیل نزولی (Bearish Trend)
        elif price < ema200_1h and not higher_trend_bullish:
            if rsi_1h >= 68:
                signal_type = "SELL / SHORT (Strong Rejection)"
                is_long = False
                confidence = 91
                leverage = "5x - 10x"
                matched = True
            elif 52 <= rsi_1h <= 60:
                signal_type = "SELL / SHORT (Trend Continuation)"
                is_long = False
                confidence = 84
                leverage = "3x - 5x"
                matched = True

        if not matched:
            return False, None, None, None

        if is_long:
            sl = price - (1.5 * atr_1h)
            tp1 = price + (1.5 * atr_1h)
            tp2 = price + (3.0 * atr_1h)
        else:
            sl = price + (1.5 * atr_1h)
            tp1 = price - (1.5 * atr_1h)
            tp2 = price - (3.0 * atr_1h)

        tp1_pct = abs(tp1 - price) / price * 100
        tp2_pct = abs(tp2 - price) / price * 100
        sl_pct = abs(price - sl) / price * 100
        rr = round(tp2_pct / sl_pct, 2) if sl_pct > 0 else 2.0

        fmt = lambda v: f"{v:.8f}" if price < 0.01 else f"{v:.4f}"
        clean_symbol = symbol.replace("/", "")

        message = (
            f"🚨 **سیگنال تحلیلی هوشمند (تایم‌فریم دوگانه)** 🚨\n\n"
            f"💎 **نماد:** #{clean_symbol}\n"
            f"📊 **نوع پوزیشن:** {signal_type}\n"
            f"📌 **قیمت ورود:** `{fmt(price)}`\n"
            f"📉 **شاخص RSI (1h):** `{rsi_1h:.2f}`\n\n"
            f"🎯 **حد سود اول (TP1):** `{fmt(tp1)}` (`+{tp1_pct:.2f}%`)\n"
            f"🚀 **حد سود دوم (TP2):** `{fmt(tp2)}` (`+{tp2_pct:.2f}%`)\n"
            f"🛑 **حد ضرر (SL):** `{fmt(sl)}` (`-{sl_pct:.2f}%`)\n\n"
            f"⚖️ **نسبت ریسک به ریوارد:** 1:{rr}\n"
            f"🔥 **ضریب اطمینان:** %{confidence}\n"
            f"⚡ **اهرم پیشنهادی:** {leverage}"
        )

        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("📈 TradingView", url=f"https://www.tradingview.com/symbols/{clean_symbol}/"),
                InlineKeyboardButton("📊 MEXC Exchange", url=f"https://www.mexc.com/exchange/{symbol.replace('/', '_')}")
            ]
        ])

        signal_data = {
            "entry": price,
            "tp1": tp1,
            "tp2": tp2,
            "sl": sl,
            "is_long": is_long
        }

        return True, message, keyboard, signal_data

# ==========================================
# 6. TELEGRAM COMMAND HANDLERS & UI
# ==========================================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    is_admin = user_id in Config.ADMIN_IDS

    reply_keyboard = [
        [KeyboardButton("📊 وضعیت سیستم"), KeyboardButton("📋 لیست نمادها")],
        [KeyboardButton("📈 آمار عملکرد"), KeyboardButton("⚙️ راهنما")]
    ]
    if is_admin:
        reply_keyboard.append([KeyboardButton("🔑 پنل مدیریت")])

    markup = ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    
    welcome_text = (
        "👋 **به ربات تحلیلگر و سیگنال‌دهی پیشرفته خوش آمدید.**\n\n"
        "این ربات بازار کریپتو را در تایم‌فریم‌های 1h و 4h تحلیل کرده، "
        "نقاط ورود، TP/SL را محاسبه کرده و پوزیشن‌های فعال را پایش می‌کند."
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=markup)

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    active_symbols = await db_manager.get_active_symbols()
    cooldown_count = 0
    for sym in active_symbols:
        if await db_manager.is_in_cooldown(sym):
            cooldown_count += 1

    stats = await db_manager.get_stats()
    
    status_text = (
        f"⚙️ **وضعیت سیستم:** ✅ فعال\n"
        f"📊 **تعداد نمادهای در حال پایش:** {len(active_symbols)}\n"
        f"⏳ **نمادهای در حال Cooldown:** {cooldown_count}\n"
        f"📢 **کل سیگنال‌های صادر شده:** {stats['total']}\n"
        f"⏱ **تایم‌فریم اصلی:** {Config.PRIMARY_TIMEFRAME} | **تایم‌فریم بالادستی:** {Config.HIGHER_TIMEFRAME}"
    )
    await update.message.reply_text(status_text, parse_mode="Markdown")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stats = await db_manager.get_stats()
    total = stats['total']
    won = stats['won']
    lost = stats['lost']
    win_rate = (won / total * 100) if total > 0 else 0.0

    text = (
        f"📈 **گزارش عملکرد سیگنال‌های ربات:**\n\n"
        f"🔹 **کل سیگنال‌ها:** {total}\n"
        f"✅ **سیگنال‌های موفق (TP Hit):** {won}\n"
        f"❌ **سیگنال‌های ناموفق (SL Hit):** {lost}\n"
        f"🎯 **وین‌ریت (Win Rate):** `{win_rate:.1f}%`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def list_symbols_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    symbols = await db_manager.get_active_symbols()
    symbols_str = "\n".join([f"• `{s}`" for s in symbols])
    text = f"📋 **لیست ارزهای تحت پایش:**\n\n{symbols_str}"
    await update.message.reply_text(text, parse_mode="Markdown")

async def admin_panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in Config.ADMIN_IDS:
        await update.message.reply_text("❌ شما دسترسی به پنل مدیریت را ندارید.")
        return

    keyboard = [
        [InlineKeyboardButton("➕ افزودن نماد", callback_data="admin_add"), InlineKeyboardButton("➖ حذف نماد", callback_data="admin_remove")],
        [InlineKeyboardButton("🔄 ریست Cooldowns", callback_data="admin_reset_cd")]
    ]
    await update.message.reply_text("🔑 **پنل مدیریت ربات:**", reply_markup=InlineKeyboardMarkup(keyboard))

async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, BadRequest) and "Message is not modified" in str(context.error):
        return
    logger.error("Global Error Handler caught exception:", exc_info=context.error)

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    try:
        if data == "admin_reset_cd":
            await db_manager.clear_all_cooldowns()
            await query.edit_message_text("✅ تمام کوئلدون‌ها بازنشانی شدند.")
        elif data == "admin_add":
            await query.edit_message_text("دستور افزودن نماد:\n`/add BTC/USDT`", parse_mode="Markdown")
        elif data == "admin_remove":
            await query.edit_message_text("دستور حذف نماد:\n`/remove BTC/USDT`", parse_mode="Markdown")
    except BadRequest as e:
        if "Message is not modified" in str(e):
            pass
        else:
            raise e

async def add_symbol_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in Config.ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("فرمت صحیح: `/add ETH/USDT`", parse_mode="Markdown")
        return
    sym = context.args[0]
    if await db_manager.add_symbol(sym):
        await update.message.reply_text(f"✅ نماد `{sym}` اضافه شد.", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ خطا در ثبت نماد.")

async def remove_symbol_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in Config.ADMIN_IDS:
        return
    if not context.args:
        await update.message.reply_text("فرمت صحیح: `/remove ETH/USDT`", parse_mode="Markdown")
        return
    sym = context.args[0]
    if await db_manager.remove_symbol(sym):
        await update.message.reply_text(f"✅ نماد `{sym}` حذف شد.", parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ نماد یافت نشد.")

async def text_messages_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "📊 وضعیت سیستم":
        await status_command(update, context)
    elif text == "📋 لیست نمادها":
        await list_symbols_command(update, context)
    elif text == "📈 آمار عملکرد":
        await stats_command(update, context)
    elif text == "🔑 پنل مدیریت":
        await admin_panel_command(update, context)
    elif text == "⚙️ راهنما":
        await update.message.reply_text("راهنما: ربات با تحلیل همزمان تایم‌فریم 1h و 4h اقدام به صدور سیگنال می‌کند.")

# ==========================================
# 7. POSITION MONITORING LOOP (TP / SL TRACKER)
# ==========================================

async def position_tracker_loop(app: Application, exchange: ccxt.Exchange):
    """پایش پوزیشن‌های باز و ارسال گزارش لمس TP/SL به کانال"""
    while True:
        try:
            open_signals = await db_manager.get_open_signals()
            for sig in open_signals:
                symbol = sig['symbol']
                try:
                    ticker = await exchange.fetch_ticker(symbol)
                    current_price = ticker['last']

                    is_long = "BUY" in sig['signal_type']
                    tp1, tp2, sl = sig['tp1'], sig['tp2'], sig['sl']

                    if is_long:
                        if current_price >= tp2:
                            await db_manager.update_signal_status(sig['id'], "TP2_HIT")
                            await app.bot.send_message(
                                chat_id=Config.CHANNEL_ID,
                                text=f"🎯🎯 **تارگت دوم لمس شد!**\n\n💎 نماد: #{symbol.replace('/', '')}\n📌 قیمت تارگت: `{tp2}`"
                            )
                        elif current_price >= tp1:
                            await db_manager.update_signal_status(sig['id'], "TP1_HIT")
                            await app.bot.send_message(
                                chat_id=Config.CHANNEL_ID,
                                text=f"🎯 **تارگت اول لمس شد!**\n\n💎 نماد: #{symbol.replace('/', '')}\n📌 قیمت تارگت: `{tp1}`"
                            )
                        elif current_price <= sl:
                            await db_manager.update_signal_status(sig['id'], "SL_HIT")
                            await app.bot.send_message(
                                chat_id=Config.CHANNEL_ID,
                                text=f"🛑 **حد ضرر لمس شد.**\n\n💎 نماد: #{symbol.replace('/', '')}\n📌 قیمت حد ضرر: `{sl}`"
                            )
                    else: # Short Position
                        if current_price <= tp2:
                            await db_manager.update_signal_status(sig['id'], "TP2_HIT")
                            await app.bot.send_message(
                                chat_id=Config.CHANNEL_ID,
                                text=f"🎯🎯 **تارگت دوم لمس شد!**\n\n💎 نماد: #{symbol.replace('/', '')}\n📌 قیمت تارگت: `{tp2}`"
                            )
                        elif current_price <= tp1:
                            await db_manager.update_signal_status(sig['id'], "TP1_HIT")
                            await app.bot.send_message(
                                chat_id=Config.CHANNEL_ID,
                                text=f"🎯 **تارگت اول لمس شد!**\n\n💎 نماد: #{symbol.replace('/', '')}\n📌 قیمت تارگت: `{tp1}`"
                            )
                        elif current_price >= sl:
                            await db_manager.update_signal_status(sig['id'], "SL_HIT")
                            await app.bot.send_message(
                                chat_id=Config.CHANNEL_ID,
                                text=f"🛑 **حد ضرر لمس شد.**\n\n💎 نماد: #{symbol.replace('/', '')}\n📌 قیمت حد ضرر: `{sl}`"
                            )
                except Exception as track_err:
                    logger.error(f"Error tracking signal ID {sig['id']} for {symbol}: {track_err}")

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Error in position tracker loop: {e}")

        await asyncio.sleep(30)

# ==========================================
# 8. ASYNC BACKGROUND MONITORING LOOP
# ==========================================

async def channel_signal_monitor_loop(app: Application):
    exchange = getattr(ccxt, Config.EXCHANGE_NAME)({'enableRateLimit': True})
    logger.info(f"Connected to exchange: {Config.EXCHANGE_NAME.upper()}")

    # اجرای همزمان تراکر تارگت‌ها
    asyncio.create_task(position_tracker_loop(app, exchange))

    while True:
        try:
            active_symbols = await db_manager.get_active_symbols()
            logger.info("🔍 Checking market symbols for signals...")
            
            for symbol in active_symbols:
                if await db_manager.is_in_cooldown(symbol):
                    continue

                try:
                    # دریافت کندل‌های تایم‌فریم 1h و 4h
                    ohlcv_1h = await exchange.fetch_ohlcv(symbol, timeframe=Config.PRIMARY_TIMEFRAME, limit=210)
                    ohlcv_4h = await exchange.fetch_ohlcv(symbol, timeframe=Config.HIGHER_TIMEFRAME, limit=210)

                    if not ohlcv_1h or len(ohlcv_1h) < 200 or not ohlcv_4h or len(ohlcv_4h) < 200:
                        continue

                    price_1h, ema200_1h, rsi_1h, atr_1h, is_vol_high = TechnicalAnalysisEngine.calculate_all(ohlcv_1h)
                    price_4h, ema200_4h, _, _, _ = TechnicalAnalysisEngine.calculate_all(ohlcv_4h)

                    condition, signal_msg, reply_markup, sig_data = StrategyEngine.evaluate(
                        symbol, price_1h, ema200_1h, rsi_1h, atr_1h, is_vol_high, price_4h, ema200_4h
                    )

                    p_fmt = f"{price_1h:.8f}" if price_1h < 0.01 else f"{price_1h:.4f}"
                    logger.info(f"📊 {symbol}: Price={p_fmt}, RSI_1H={rsi_1h:.2f} -> Signal: {condition}")

                    if condition and signal_msg and sig_data:
                        await app.bot.send_message(
                            chat_id=Config.CHANNEL_ID,
                            text=signal_msg,
                            parse_mode="Markdown",
                            reply_markup=reply_markup
                        )

                        await db_manager.save_signal(
                            symbol, "LONG" if sig_data['is_long'] else "SHORT",
                            sig_data['entry'], sig_data['tp1'], sig_data['tp2'], sig_data['sl']
                        )

                        await db_manager.set_cooldown(symbol, Config.COOLDOWN_HOURS)
                        logger.info(f"📣 Signal published & saved for {symbol}")

                except Exception as sym_err:
                    logger.error(f"Error processing symbol {symbol}: {sym_err}")

        except asyncio.CancelledError:
            logger.info("Signal monitor loop cancelled.")
            await exchange.close()
            break
        except Exception as global_loop_err:
            logger.error(f"Error in signal loop: {global_loop_err}")

        await asyncio.sleep(Config.POLL_INTERVAL)

# ==========================================
# 9. MAIN APPLICATION ENTRY POINT
# ==========================================

def main():
    logger.info("Initializing Database...")
    loop = asyncio.get_event_loop()
    loop.run_until_complete(db_manager.init_db())

    logger.info("Starting Telegram Bot Application...")
    app = Application.builder().token(Config.BOT_TOKEN).build()

    app.add_error_handler(global_error_handler)

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("list", list_symbols_command))
    app.add_handler(CommandHandler("add", add_symbol_handler))
    app.add_handler(CommandHandler("remove", remove_symbol_handler))
    
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_messages_handler))

    loop.create_task(channel_signal_monitor_loop(app))

    logger.info("🚀 Signal Bot with DB & Tracker is operational...")
    app.run_polling()

if __name__ == "__main__":
    main()
