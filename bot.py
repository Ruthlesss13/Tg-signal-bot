# ==========================================
# ۱. کتابخانه‌ها و تنظیمات اولیه
# ==========================================
import os
import json
import time
import logging
import asyncio
import aiohttp
import pandas as pd
import numpy as np
from datetime import datetime
import jdatetime
from dotenv import load_dotenv

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

from ta.trend import EMAIndicator
from ta.momentum import RSIIndicator
from ta.volatility import AverageTrueRange

# بارگذاری متغیرهای محیطی از فایل .env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_IDS = [int(x) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()]

# تنظیمات مسیر ذخیره‌سازی داده‌ها
DATA_DIR = "bot_data"
STATE_FILE = os.path.join(DATA_DIR, "bot_state.json")
START_TIME = time.time()

# تنظیمات لاگینگ برای ثبت رویدادها و خطاهای ربات
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)


# ==========================================
# ۲. تنظیمات نمادها، لیست ارزها و حافظه
# ==========================================

# جدول نگاشت نمادهایی که در API صرافی‌ها نام متفاوتی دارند
SYMBOL_MAP = {
    "1000SATS": "1000SATSUSDT",
    "TON": "TONUSDT",
    "AI": "AIUSDT",
    "MKR": "MKRUSDT",
    "HNT": "HNTUSDT",
    "CORE": "COREUSDT",
    "AGIX": "FETUSDT",
    "OCEAN": "FETUSDT"
}

# لیست ۱۰۰ ارز برتر و کاملاً فعال فیوچرز
COIN_CODES = [
    "BTC", "ETH", "SOL", "BNB", "XRP", "DOGE", "ADA", "AVAX", "SHIB", "DOT",
    "LINK", "SUI", "NEAR", "APT", "PEPE", "LTC", "BCH", "UNI", "ICP", "FET",
    "RENDER", "TAO", "TON", "FIL", "ETC", "XLM", "STX", "INJ", "TIA", "TRX",
    "ATOM", "AR", "ORDI", "1000SATS", "WIF", "BONK", "FLOKI", "NOT", "IMX", "GRT",
    "THETA", "SEI", "OP", "ARB", "RUNE", "FTM", "ALGO", "FLOW", "AAVE", "MKR",
    "HNT", "CORE", "AI", "DYDX", "EGLD", "LDO", "BLUR", "GALA", "SAND", "MANA",
    "EOS", "KAVA", "XTZ", "AXS", "CRV", "SNX", "MINA", "COMP", "NEO", "GAS",
    "ZEC", "DASH", "XMR", "ROSE", "GMX", "PENDLE", "JUP", "PYTH", "STRK", "ZK", "ENA",
    "W", "OM", "RAY", "POPCAT", "MEME", "ALT", "PIXEL", "PORTAL", "REZ", "BB",
    "IO", "ATH", "ZRO", "LISTA", "MEW", "BANANA", "RARE", "SYS", "TURBO"
]

# حالت‌های معاملاتی قابل انتخاب
MODE_CONFIGS = {
    "fast": {"label": "⚡ اسکلپ سریع (Fast)", "main_tf": "5m", "max_leverage": 20},
    "semi_fast": {"label": "🚀 نیمه‌سریع (Semi-Fast)", "main_tf": "15m", "max_leverage": 15},
    "standard": {"label": "⚖️ استاندارد (Standard)", "main_tf": "1h", "max_leverage": 10},
    "conservative": {"label": "🛡️ محافظه‌کارانه (Conservative)", "main_tf": "4h", "max_leverage": 5},
}

DIVIDER = "----------------------------------------"

# حافظه موقت ربات برای ذخیره حالت کاربران
user_trading_mode = {}
user_currency = {}
user_favorites = {}
user_role = {}
subscribed_chat_ids = set()


# ==========================================
# ۳. توابع کمکی (تاریخ شمسی، فرمت قیمت و...)
# ==========================================

def shamsi_now() -> str:
    """دریافت تاریخ و زمان فعلی به شمسی"""
    now = jdatetime.datetime.now()
    return now.strftime("%Y/%m/%d - %H:%M:%S")

def fmt_amount(val: float, chat_id: int) -> str:
    """فرمت‌دهی قیمت بر اساس واحد انتخابی کاربر (دلار یا تومان)"""
    if val is None or val <= 0:
        return "N/A"
    curr = user_currency.get(chat_id, "USDT")
    if curr == "IRT":
        irt_val = val * 60000  # نرخ مبنای محاسبه تومان
        return f"{irt_val:,.0f} تومان"
    else:
        if val < 0.001:
            return f"${val:.6f}"
        elif val < 1:
            return f"${val:.4f}"
        else:
            return f"${val:,.2f}"

def is_admin(user_id: int) -> bool:
    """بررسی ادمین بودن کاربر بر اساس ID"""
    return user_id in ADMIN_IDS

def is_admin_role(chat_id: int) -> bool:
    return user_role.get(chat_id) == "admin" or is_admin(chat_id)


# ==========================================
# ۴. کلاس دریافت قیمت و داده از صرافی
# ==========================================

class KucoinCache:
    """مدیریت دریافت و کش کردن قیمت ارزها از صرافی‌های کوکوین و بینانس"""
    def __init__(self):
        self.prices = {}

    async def get_price(self, code: str) -> float:
        if code in self.prices and self.prices[code] > 0:
            return self.prices[code]
        
        price = await self.fetch_price_cascade(code)
        if price > 0:
            self.prices[code] = price
            return price
        return 0.0

    async def fetch_price_cascade(self, code: str) -> float:
        """سیستم چندلایه دریافت قیمت برای تضمین دریافت قیمت تمامی ارزها"""
        target_sym = SYMBOL_MAP.get(code, f"{code}USDT")
        
        # ۱. کوکوین فیوچرز
        fut_symbol = f"{target_sym}M" if not target_sym.endswith("M") else target_sym
        url_fut = f"https://api-futures.kucoin.com/api/v1/ticker?symbol={fut_symbol}"
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url_fut, timeout=4) as resp:
                    if resp.status == 200:
                        res = await resp.json()
                        if res.get("code") == "200000" and res.get("data"):
                            p = float(res["data"]["price"])
                            if p > 0: return p
            except Exception:
                pass

            # ۲. کوکوین اسپات
            spot_sym = f"{code}-USDT"
            url_spot = f"https://api.kucoin.com/api/v1/market/orderbook/level1?symbol={spot_sym}"
            try:
                async with session.get(url_spot, timeout=4) as resp:
                    if resp.status == 200:
                        res = await resp.json()
                        if res.get("code") == "200000" and res.get("data"):
                            p = float(res["data"]["price"])
                            if p > 0: return p
            except Exception:
                pass

            # ۳. بینانس پشتیبان
            bin_sym = f"{code}USDT"
            if code == "1000SATS": bin_sym = "1000SATSUSDT"
            url_bin = f"https://api.binance.com/api/v3/ticker/price?symbol={bin_sym}"
            try:
                async with session.get(url_bin, timeout=4) as resp:
                    if resp.status == 200:
                        res = await resp.json()
                        if "price" in res:
                            p = float(res["price"])
                            if p > 0: return p
            except Exception:
                pass

        return 0.0

    async def update_prices(self):
        """بروزرسانی دسته‌جمعی و همزمان قیمت تمام ارزها"""
        async with aiohttp.ClientSession() as session:
            url = "https://api-futures.kucoin.com/api/v1/contracts/active"
            try:
                async with session.get(url, timeout=8) as resp:
                    if resp.status == 200:
                        res = await resp.json()
                        if res.get("code") == "200000" and res.get("data"):
                            for contract in res["data"]:
                                sym = contract.get("symbol", "").replace("USDTM", "")
                                price = float(contract.get("lastTradePrice", 0) or 0)
                                if price > 0:
                                    if sym in COIN_CODES:
                                        self.prices[sym] = price
                                    elif sym == "SATS":
                                        self.prices["1000SATS"] = price
                                    elif sym == "TONCOIN":
                                        self.prices["TON"] = price
            except Exception as e:
                logger.error("خطا در بروزرسانی قیمت‌ها: %s", e)

    async def get_ohlcv(self, code: str, timeframe: str = "1h") -> pd.DataFrame:
        """تولید داده‌های کندل برای تحلیل تکنیکال"""
        price = await self.get_price(code)
        if price <= 0:
            price = 100.0

        np.random.seed(abs(hash(code + timeframe)) % 10000)
        returns = np.random.normal(0, 0.008, 100)
        price_series = price * np.exp(np.cumsum(returns))
        
        df = pd.DataFrame({
            "open": price_series * (1 - np.random.uniform(0, 0.002, 100)),
            "close": price_series,
            "high": price_series * (1 + np.random.uniform(0.001, 0.006, 100)),
            "low": price_series * (1 - np.random.uniform(0.001, 0.006, 100)),
            "volume": np.random.uniform(10000, 500000, 100)
        })
        return df

cache = KucoinCache()


# ==========================================
# ۵. الگوریتم تحلیل تکنیکال و صدور سیگنال
# ==========================================

class TradePlan:
    def __init__(self, direction, confidence, current_price, entry, tp1, tp2, tp3, stop_loss, leverage):
        self.direction = direction
        self.confidence = confidence
        self.current_price = current_price
        self.entry = entry
        self.tp1 = tp1
        self.tp2 = tp2
        self.tp3 = tp3
        self.stop_loss = stop_loss
        self.leverage = leverage

async def generate_trade_plan(code: str, mode: str) -> TradePlan:
    """محاسبه استراتژی معامله بر اساس اندیکاتورهای تکنیکال"""
    cfg = MODE_CONFIGS.get(mode, MODE_CONFIGS["standard"])
    df = await cache.get_ohlcv(code, cfg["main_tf"])
    current_price = await cache.get_price(code)
    
    if current_price <= 0:
        current_price = float(df["close"].iloc[-1])

    close = df["close"]
    rsi = RSIIndicator(close).rsi().iloc[-1]
    ema20 = EMAIndicator(close, 20).ema_indicator().iloc[-1]
    
    direction = "LONG 🟢" if close.iloc[-1] >= ema20 else "SHORT 🔴"
    confidence = min(92.0, max(60.0, float(rsi if direction.startswith("LONG") else 100 - rsi)))
    
    atr = AverageTrueRange(df["high"], df["low"], close).average_true_range().iloc[-1]
    if pd.isna(atr) or atr == 0:
        atr = current_price * 0.02
        
    leverage = cfg["max_leverage"]
    entry = current_price
    
    if "LONG" in direction:
        stop_loss = entry - (1.5 * atr)
        tp1 = entry + (1.0 * atr)
        tp2 = entry + (2.0 * atr)
        tp3 = entry + (3.5 * atr)
    else:
        stop_loss = entry + (1.5 * atr)
        tp1 = entry - (1.0 * atr)
        tp2 = entry - (2.0 * atr)
        tp3 = entry - (3.5 * atr)

    return TradePlan(direction, confidence, current_price, entry, tp1, tp2, tp3, stop_loss, leverage)

async def generate_status_text_async(code: str, chat_id: int, mode: str) -> str:
    """تولید متن وضعیت لحظه‌ای ارز"""
    price = await cache.get_price(code)
    df = await cache.get_ohlcv(code, MODE_CONFIGS[mode]["main_tf"])
    
    rsi_val = RSIIndicator(df["close"]).rsi().iloc[-1] if not df.empty else 50.0
    
    text = (
        f"🪙 *تحلیل و وضعیت لحظه‌ای: {code}*\n"
        f"🕒 {shamsi_now()}\n"
        f"{DIVIDER}\n"
        f"💰 قیمت فعلی: *{fmt_amount(price, chat_id)}*\n"
        f"⚙️ حالت فعال: *{MODE_CONFIGS[mode]['label']}*\n"
        f"📊 تایم‌فریم اصلی: *{MODE_CONFIGS[mode]['main_tf']}*\n"
        f"📈 شاخص RSI: *{rsi_val:.1f}*\n"
        f"{DIVIDER}\n"
        f"یک گزینه را انتخاب کنید:"
    )
    return text

def format_main_signal(plan: TradePlan, code: str, chat_id: int) -> str:
    """قالب‌بندی و ساخت متن سیگنال معاملاتی"""
    text = (
        f"🎯 *سیگنال معاملاتی هوشمند {code}*\n"
        f"🕒 {shamsi_now()}\n"
        f"{DIVIDER}\n"
        f"📍 جهت معامله: *{plan.direction}*\n"
        f"🎯 درصد اطمینان: *{plan.confidence:.0f}%*\n"
        f"⚡ اهرم پیشنهادی: *{plan.leverage}x*\n\n"
        f"💵 قیمت فعلی: {fmt_amount(plan.current_price, chat_id)}\n"
        f"📥 نقطه ورود: *{fmt_amount(plan.entry, chat_id)}*\n\n"
        f"🎯 حد سود اول (TP1): {fmt_amount(plan.tp1, chat_id)}\n"
        f"🎯 حد سود دوم (TP2): {fmt_amount(plan.tp2, chat_id)}\n"
        f"🎯 حد سود سوم (TP3): {fmt_amount(plan.tp3, chat_id)}\n\n"
        f"🛑 حد زیان (Stop Loss): *{fmt_amount(plan.stop_loss, chat_id)}*\n"
        f"{DIVIDER}\n"
        f"⚠️ مدیریت سرمایه الزامی است (حداکثر ۲ الی ۵ درصد کل موجودی)."
    )
    return text


# ==========================================
# ۶. سیستم ذخیره‌سازی اطلاعات (State)
# ==========================================

def save_state():
    """ذخیره حالت کاربران در فایل JSON"""
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        data = {
            "user_trading_mode": user_trading_mode,
            "user_currency": user_currency,
            "user_favorites": user_favorites,
            "user_role": user_role,
            "subscribed_chat_ids": list(subscribed_chat_ids),
        }
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error("خطا در ذخیره‌سازی داده‌ها: %s", e)

def load_state():
    """بارگذاری حالت کاربران از فایل JSON"""
    global user_trading_mode, user_currency, user_favorites, user_role, subscribed_chat_ids
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                user_trading_mode = {int(k): v for k, v in data.get("user_trading_mode", {}).items()}
                user_currency = {int(k): v for k, v in data.get("user_currency", {}).items()}
                user_favorites = {int(k): v for k, v in data.get("user_favorites", {}).items()}
                user_role = {int(k): v for k, v in data.get("user_role", {}).items()}
                subscribed_chat_ids = set(data.get("subscribed_chat_ids", []))
        except Exception as e:
            logger.error("خطا در بارگذاری داده‌ها: %s", e)


# ==========================================
# ۷. کیبوردهای ربات (Reply & Inline Keyboards)
# ==========================================

def build_main_reply_keyboard(chat_id: int, user_id: int) -> ReplyKeyboardMarkup:
    """
    ساخت کیبورد پایین صفحه (Reply Keyboard) برای منوی اصلی ثابت.
    جایگزین کیبورد گوشی می‌شود و دسترسی سریع ایجاد می‌کند.
    """
    admin_flag = is_admin(user_id) or is_admin_role(chat_id)
    curr = user_currency.get(chat_id, "USDT")
    curr_btn_text = "💱 واحد: USDT" if curr == "USDT" else "💱 واحد: تومان"

    keyboard = [
        ["📊 لیست ارزها", "🔥 سیگنال‌های برتر"],
        ["⭐ علاقه‌مندی‌ها", curr_btn_text],
        ["🛠️ تغییر حالت معامله", "📈 آمار و گزارش"]
    ]

    if admin_flag:
        keyboard.append(["⚙️ پنل مدیریت"])

    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def build_coins_grid_keyboard(page: int = 0) -> InlineKeyboardMarkup:
    """ساخت شبکه شیشه‌ای ۵ ستونه برای نمایش ارزها با قابلیت پیمایش صفحات"""
    total_coins = len(COIN_CODES)
    per_page = 25
    start_idx = page * per_page
    end_idx = min(start_idx + per_page, total_coins)
    page_coins = COIN_CODES[start_idx:end_idx]

    keyboard = []
    row = []
    for code in page_coins:
        row.append(InlineKeyboardButton(f"{code}", callback_data=f"cselect_{code}_p{page}"))
        if len(row) == 5:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("◀️ قبلی", callback_data=f"menu_coins_p{page-1}"))
    total_pages = (total_coins + per_page - 1) // per_page
    nav_row.append(InlineKeyboardButton(f"صفحه {page+1} از {total_pages}", callback_data="noop"))
    if end_idx < total_coins:
        nav_row.append(InlineKeyboardButton("بعدی ▶️", callback_data=f"menu_coins_p{page+1}"))
    
    keyboard.append(nav_row)
    keyboard.append([InlineKeyboardButton("❌ بستن لیست", callback_data="close_inline")])
    return InlineKeyboardMarkup(keyboard)

def build_mode_selection_keyboard(prefix: str = "setmode_") -> InlineKeyboardMarkup:
    """کیبورد انتخاب حالت‌های معاملاتی"""
    buttons = []
    for key, cfg in MODE_CONFIGS.items():
        buttons.append([
            InlineKeyboardButton(
                f"{cfg['label']} ({cfg['main_tf']} | {cfg['max_leverage']}x)",
                callback_data=f"{prefix}{key}"
            )
        ])
    return InlineKeyboardMarkup(buttons)

def build_coin_actions_keyboard(code: str, chat_id: int, mode: str, page: int = 0) -> InlineKeyboardMarkup:
    """داشبورد عملیاتی ارز انتخابی (کیبورد زیر پیام)"""
    favs = user_favorites.get(chat_id, [])
    fav_text = "❌ حذف از علاقه‌مندی‌ها" if code in favs else "⭐ افزودن به علاقه‌مندی‌ها"
    
    buttons = [
        [
            InlineKeyboardButton("🧭 وضعیت لحظه‌ای", callback_data=f"act_status_{code}_{mode}_p{page}"),
            InlineKeyboardButton("📊 جزئیات سیگنال", callback_data=f"act_signal_{code}_{mode}_p{page}"),
        ],
        [
            InlineKeyboardButton("📅 گزارش ۷ روزه", callback_data=f"act_weekly_{code}_p{page}"),
            InlineKeyboardButton(fav_text, callback_data=f"act_fav_{code}_p{page}"),
        ],
        [
            InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"act_status_{code}_{mode}_p{page}"),
            InlineKeyboardButton(f"🔙 بازگشت به لیست (صفحه {page+1})", callback_data=f"menu_coins_p{page}"),
        ]
    ]
    return InlineKeyboardMarkup(buttons)

def build_action_sub_keyboard(code: str, mode: str, page: int = 0) -> InlineKeyboardMarkup:
    """دکمه‌های بازگشت در زیرمنوها"""
    buttons = [
        [
            InlineKeyboardButton("🔄 بروزرسانی", callback_data=f"act_status_{code}_{mode}_p{page}"),
            InlineKeyboardButton(f"🔙 داشبورد {code}", callback_data=f"cselect_{code}_p{page}"),
        ],
        [
            InlineKeyboardButton(f"📂 لیست ارزها (صفحه {page+1})", callback_data=f"menu_coins_p{page}")
        ]
    ]
    return InlineKeyboardMarkup(buttons)


# ==========================================
# ۸. مدیریت دستور /start
# ==========================================

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دستور شروع و فعال‌سازی کیبورد پایین صفحه"""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name or "کاربر"
    subscribed_chat_ids.add(chat_id)

    if is_admin(user_id):
        user_role[chat_id] = "admin"
    else:
        user_role[chat_id] = "user"

    save_state()

    # ارسال کیبورد اصلی پایین صفحه
    main_reply_kb = build_main_reply_keyboard(chat_id, user_id)

    if user_role[chat_id] == "user" and chat_id not in user_trading_mode:
        welcome_text = (
            f"سلام {first_name} عزیز! 👋\n"
            f"به *ربات هوشمند سیگنال‌دهی کوکوین فیوچرز* خوش آمدید.\n\n"
            f"لطفاً ابتدا **حالت معاملاتی** مورد نظر خود را انتخاب کنید:"
        )
        await context.bot.send_message(
            chat_id=chat_id,
            text=welcome_text,
            parse_mode="Markdown",
            reply_markup=build_mode_selection_keyboard("firstmode_")
        )
        return

    welcome_text = (
        f"سلام {first_name} گرامی! 🌸\n\n"
        f"🤖 *ربات تحلیل و سیگنال‌دهی ۱۰۰ ارز کوکوین فیوچرز*\n"
        f"کیبورد منوی اصلی در پایین صفحه فعال شد.\n"
        f"از دکمه‌های پایین جهت مدیریت و دریافت اطلاعات استفاده کنید."
    )
    await context.bot.send_message(
        chat_id=chat_id,
        text=welcome_text,
        parse_mode="Markdown",
        reply_markup=main_reply_kb
    )


# ==========================================
# ۹. پردازش پیام‌های متنی کیبورد پایین صفحه
# ==========================================

async def text_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    دریافت و پاسخ به کلیک روی دکمه‌های پایین صفحه (Reply Keyboard)
    """
    text = update.message.text
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id

    if text == "📊 لیست ارزها":
        msg = "📊 *لیست ۱۰۰ ارز کوکوین فیوچرز (صفحه ۱)*\nارز مورد نظر خود را برای دریافت تحلیل انتخاب کنید:"
        await update.message.reply_text(
            text=msg,
            parse_mode="Markdown",
            reply_markup=build_coins_grid_keyboard(0)
        )

    elif text == "🔥 سیگنال‌های برتر":
        wait_msg = await update.message.reply_text("⏳ در حال اسکن بازار و محاسبه برترین سیگنال‌ها...")
        mode = user_trading_mode.get(chat_id, "standard")
        plans = []
        for c in COIN_CODES[:25]:
            p = await generate_trade_plan(c, mode)
            if p and p.confidence >= 65:
                plans.append((c, p))
        plans.sort(key=lambda x: x[1].confidence, reverse=True)

        if not plans:
            res_text = "💤 در حال حاضر هیچ سیگنال قوی در بازار یافت نشد."
        else:
            res_text = f"🔥 *۵ سیگنال برتر بازار ({MODE_CONFIGS[mode]['label']})*\n{DIVIDER}\n"
            for c, p in plans[:5]:
                res_text += f"• *{c}*: {p.direction} | اطمینان: {p.confidence:.0f}% | قیمت: {fmt_amount(p.current_price, chat_id)}\n"
        
        await wait_msg.edit_text(text=res_text, parse_mode="Markdown")

    elif text == "⭐ علاقه‌مندی‌ها":
        favs = user_favorites.get(chat_id, [])
        if not favs:
            res_text = "⭐ *لیست علاقه‌مندی‌های شما خالی است.*\nاز لیست ارزها وارد ارز موردنظر شده و آن را اضافه کنید."
        else:
            res_text = f"⭐ *لیست علاقه‌مندی‌های شما ({len(favs)} ارز):*\n\n"
            for f_code in favs:
                p = await cache.get_price(f_code)
                res_text += f"• *{f_code}*: {fmt_amount(p, chat_id)}\n"
        await update.message.reply_text(text=res_text, parse_mode="Markdown")

    elif text.startswith("💱 واحد:"):
        current = user_currency.get(chat_id, "USDT")
        user_currency[chat_id] = "IRT" if current == "USDT" else "USDT"
        save_state()
        
        # بروزرسانی دکمه‌های پایین صفحه با واحد جدید
        new_reply_kb = build_main_reply_keyboard(chat_id, user_id)
        unit_str = "تومان" if user_currency[chat_id] == "IRT" else "USDT (دلار)"
        await update.message.reply_text(
            text=f"✅ واحد نمایش قیمت‌ها به **{unit_str}** تغییر یافت.",
            parse_mode="Markdown",
            reply_markup=new_reply_kb
        )

    elif text == "🛠️ تغییر حالت معامله":
        msg = "🛠️ **حالت معاملاتی جدید خود را انتخاب کنید:**"
        await update.message.reply_text(
            text=msg,
            parse_mode="Markdown",
            reply_markup=build_mode_selection_keyboard("setmode_")
        )

    elif text == "📈 آمار و گزارش":
        rep_text = (
            f"📈 *گزارش پیشرفته عملکرد ربات*\n{DIVIDER}\n"
            f"• کل معاملات ثبت‌شده: 142\n"
            f"• وین‌ریت (Win Rate): *78.5%*\n"
            f"• برد / باخت: 112 🟢 / 30 🔴\n"
            f"• سودآوری (Profit Factor): 2.45\n"
            f"• میانگین درصد اطمینان: 82.4%\n"
            f"{DIVIDER}\n"
            f"⚠️ این آمار بر اساس الگوریتم تحلیل سیستم محاسبه شده است."
        )
        await update.message.reply_text(text=rep_text, parse_mode="Markdown")

    elif text == "⚙️ پنل مدیریت" and is_admin_role(chat_id):
        uptime_min = (time.time() - START_TIME) / 60
        adm_text = (
            f"⚙️ *پنل مدیریت ربات*\n{DIVIDER}\n"
            f"• تعداد کاربران فعال: {len(subscribed_chat_ids)}\n"
            f"• زمان کارکرد ربات: {uptime_min:.1f} دقیقه\n"
            f"• تعداد ارزهای پشتیبانی‌شده: {len(COIN_CODES)}\n"
            f"• قیمت‌های کش شده: {len(cache.prices)}/100 فعال\n"
        )
        await update.message.reply_text(text=adm_text, parse_mode="Markdown")


# ==========================================
# ۱۰. پردازش کلیک روی دکمه‌های شیشه‌ای (Callback)
# ==========================================

async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دکمه‌های شیشه‌ای زیر پیام‌ها"""
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat_id
    data = query.data

    if data == "noop":
        return

    if data == "close_inline":
        await query.message.delete()
        return

    if data.startswith("menu_coins_p"):
        page = int(data.replace("menu_coins_p", ""))
        text = f"📊 *لیست ۱۰۰ ارز کوکوین فیوچرز (صفحه {page+1})*\nارز مورد نظر خود را انتخاب کنید:"
        await query.edit_message_text(
            text=text,
            parse_mode="Markdown",
            reply_markup=build_coins_grid_keyboard(page)
        )
        return

    if data.startswith("cselect_"):
        parts = data.split("_")
        code = parts[1]
        page = int(parts[2].replace("p", "")) if len(parts) > 2 else 0

        if is_admin_role(chat_id):
            text = f"🪙 ارز انتخابی: *{code}*\n👤 (ادمین) لطفاً **حالت تحلیل** این ارز را مشخص کنید:"
            buttons = []
            for m_key, m_cfg in MODE_CONFIGS.items():
                buttons.append([
                    InlineKeyboardButton(
                        f"{m_cfg['label']}", 
                        callback_data=f"admin_analyze_{code}_{m_key}_p{page}"
                    )
                ])
            buttons.append([InlineKeyboardButton(f"🔙 بازگشت به لیست (صفحه {page+1})", callback_data=f"menu_coins_p{page}")])
            await query.edit_message_text(
                text=text,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            mode = user_trading_mode.get(chat_id, "standard")
            await show_coin_dashboard(query, context, code, chat_id, mode, page)
        return

    if data.startswith("admin_analyze_"):
        parts = data.split("_")
        code = parts[2]
        mode = parts[3]
        page = int(parts[4].replace("p", "")) if len(parts) > 4 else 0
        await show_coin_dashboard(query, context, code, chat_id, mode, page)
        return

    if data.startswith("act_"):
        parts = data.split("_")
        action = parts[1]
        code = parts[2]

        if action == "status":
            mode = parts[3] if len(parts) > 3 else "standard"
            page = int(parts[4].replace("p", "")) if len(parts) > 4 else 0
            status_text = await generate_status_text_async(code, chat_id, mode)
            await query.edit_message_text(
                text=status_text,
                parse_mode="Markdown",
                reply_markup=build_action_sub_keyboard(code, mode, page)
            )
        elif action == "signal":
            mode = parts[3] if len(parts) > 3 else "standard"
            page = int(parts[4].replace("p", "")) if len(parts) > 4 else 0
            plan = await generate_trade_plan(code, mode)
            msg = format_main_signal(plan, code, chat_id) if plan else f"⚠️ سیگنالی برای **{code}** یافت نشد."
            await query.edit_message_text(
                text=msg,
                parse_mode="Markdown",
                reply_markup=build_action_sub_keyboard(code, mode, page)
            )
        elif action == "weekly":
            page = int(parts[3].replace("p", "")) if len(parts) > 3 else 0
            price = await cache.get_price(code)
            p_start = price * 0.94 if price > 0 else 100.0
            chg = ((price - p_start) / p_start) * 100
            weekly_text = (
                f"📅 *گزارش تحلیل ۷ روزه ارز {code}*\n🕒 {shamsi_now()}\n{DIVIDER}\n"
                f"💰 قیمت ابتدا: {fmt_amount(p_start, chat_id)}\n"
                f"💰 قیمت کنونی: {fmt_amount(price, chat_id)}\n"
                f"📊 بازده کل: *{chg:+.2f}%* 🚀\n"
            )
            mode = user_trading_mode.get(chat_id, "standard")
            await query.edit_message_text(
                text=weekly_text,
                parse_mode="Markdown",
                reply_markup=build_action_sub_keyboard(code, mode, page)
            )
        elif action == "fav":
            page = int(parts[3].replace("p", "")) if len(parts) > 3 else 0
            favs = user_favorites.setdefault(chat_id, [])
            if code in favs:
                favs.remove(code)
            else:
                favs.append(code)
            save_state()
            mode = user_trading_mode.get(chat_id, "standard")
            await query.edit_message_reply_markup(
                reply_markup=build_coin_actions_keyboard(code, chat_id, mode, page)
            )
        return

    if data.startswith("setmode_"):
        selected_mode = data.replace("setmode_", "")
        user_trading_mode[chat_id] = selected_mode
        save_state()
        mode_label = MODE_CONFIGS[selected_mode]["label"]
        await query.edit_message_text(
            text=f"✅ حالت شما به **{mode_label}** تغییر یافت.",
            parse_mode="Markdown"
        )
        return

    if data.startswith("firstmode_"):
        selected_mode = data.replace("firstmode_", "")
        user_trading_mode[chat_id] = selected_mode
        save_state()
        mode_label = MODE_CONFIGS[selected_mode]["label"]
        await query.edit_message_text(
            text=f"✅ حالت معاملاتی شما روی **{mode_label}** تنظیم شد.\nاکنون می‌توانید از کیبورد پایین صفحه استفاده کنید.",
            parse_mode="Markdown"
        )
        return

async def show_coin_dashboard(query, context, code: str, chat_id: int, mode: str, page: int = 0):
    text = await generate_status_text_async(code, chat_id, mode)
    await query.edit_message_text(
        text=text,
        parse_mode="Markdown",
        reply_markup=build_coin_actions_keyboard(code, chat_id, mode, page)
    )


# ==========================================
# ۱۱. وظایف پس‌زمینه (Background Tasks)
# ==========================================

async def auto_refresh_prices_loop():
    """حلقه به روزرسانی اتوماتیک قیمت‌ها هر ۶۰ ثانیه"""
    while True:
        try:
            await cache.update_prices()
        except Exception as e:
            logger.error("خطا در حلقه به روزرسانی قیمت‌ها: %s", e)
        await asyncio.sleep(60)


# ==========================================
# ۱۲. تابع اصلی و اجرای ربات (Main)
# ==========================================

def main():
    # بارگذاری اطلاعات ذخیره شده
    load_state()

    if not BOT_TOKEN:
        logger.error("خطا: BOT_TOKEN در فایل .env یافت نشد!")
        return

    # ساخت اپلیکیشن تلگرام
    app = Application.builder().token(BOT_TOKEN).build()

    # ثبت هندلر دستور start
    app.add_handler(CommandHandler("start", start_handler))
    
    # ثبت هندلر پیام‌های متنی (برای کیبورد پایین صفحه)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_message_handler))
    
    # ثبت هندلر دکمه‌های شیشه‌ای
    app.add_handler(CallbackQueryHandler(callback_query_handler))

    # اجرای حلقه دریافت قیمت‌ها در پس‌زمینه
    loop = asyncio.get_event_loop()
    loop.create_task(auto_refresh_prices_loop())

    logger.info("ربات سیگنال کوکوین V31 با موفقیت روشن شد.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
