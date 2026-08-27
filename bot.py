import logging
import asyncio
import ccxt.async_support as ccxt
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters
)

# پیکربندی لاگر
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("signal_bot")

TOKEN = "BOT_TOKEN_HERE"  # توکن ربات خود را اینجا قرار دهید

# ==========================================
# ۱. کیبورد منوی اصلی (ثابت نگه‌داشتن ابعاد دکمه‌ها)
# ==========================================
MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("🟢 شروع ربات"), KeyboardButton("🔴 توقف ربات")],
        [KeyboardButton("📊 دریافت قیمت TON"), KeyboardButton("⚙️ تنظیمات")]
    ],
    resize_keyboard=True,  # تنظیم ابعاد استاندارد
    is_persistent=True     # عدم مخفی‌شدن کیبورد هنگام ارسال پیام
)

# ==========================================
# ۲. تابع دریافت قیمت با مکانیسم Fallback
# ==========================================
async def get_crypto_price(symbol: str = "TON/USDT") -> tuple[str | None, float | None]:
    """
    دریافت قیمت ارز از صرافی‌ها به ترتیب اولویت.
    در صورت بروز خطا یا عدم پشتیبانی، به سراغ صرافی بعدی می‌رود.
    """
    exchanges = [
        ("MEXC", ccxt.mexc),
        ("Gate.io", ccxt.gateio),
        ("BingX", ccxt.bingx),
        ("KuCoin", ccxt.kucoin),
    ]

    for name, exchange_cls in exchanges:
        exchange = exchange_cls({'enableRateLimit': True, 'timeout': 10000})
        try:
            # بارگذاری نمادهای صرافی جهت جلوگیری از خطای BadSymbol
            await exchange.load_markets()

            if symbol in exchange.markets:
                ticker = await exchange.fetch_ticker(symbol)
                price = ticker.get('last')
                if price:
                    logger.info(f"Price fetched successfully from {name}: {price}")
                    return name, float(price)
            else:
                logger.warning(f"{name} does not support symbol: {symbol}")

        except Exception as e:
            logger.error(f"Failed to fetch price from {name}: {e}")
        finally:
            await exchange.close()

    return None, None

# ==========================================
# ۳. هندلرهای دستورات و دکمه‌ها
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """دستور /start و نمایش منوی اصلی"""
    await update.message.reply_text(
        "👋 به ربات دریافت سیگنال و قیمت خوش آمدید.\nیک گزینه را انتخاب کنید:",
        reply_markup=MAIN_KEYBOARD
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """مدیریت دکمه‌های متنی منوی اصلی"""
    text = update.message.text

    if text == "🟢 شروع ربات":
        context.user_data['is_active'] = True
        await update.message.reply_text(
            "🟢 **ربات فعال شد.** پردازش سیگنال‌ها در جریان است.",
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD
        )

    elif text == "🔴 توقف ربات":
        context.user_data['is_active'] = False
        await update.message.reply_text(
            "🔴 **ربات متوقف شد.** هیچ سیگنالی پردازش نخواهد شد.",
            parse_mode="Markdown",
            reply_markup=MAIN_KEYBOARD
        )

    elif text == "📊 دریافت قیمت TON":
        msg = await update.message.reply_text("⏳ در حال استعلام قیمت از صرافی‌ها...")
        exchange_name, price = await get_crypto_price("TON/USDT")

        if price and exchange_name:
            await msg.edit_text(f"💎 **قیمت TON/USDT**\n\n💵 قیمت: `${price:,.4f}`\n🏢 صرافی: `{exchange_name}`", parse_mode="Markdown")
        else:
            await msg.edit_text("❌ امکان دریافت قیمت TON از هیچ‌یک از صرافی‌ها مقدور نبود.")

    elif text == "⚙️ تنظیمات":
        await update.message.reply_text(
            "⚙️ بخش تنظیمات ربات",
            reply_markup=MAIN_KEYBOARD
        )

    else:
        await update.message.reply_text(
            "لطفاً از دکمه‌های منوی زیر استفاده کنید:",
            reply_markup=MAIN_KEYBOARD
        )

# ==========================================
# ۴. اجرا و راه‌اندازی ربات
# ==========================================
def main():
    app = Application.builder().token(TOKEN).build()

    # ثبت هندلرها
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot started working...")
    app.run_polling()

if __name__ == "__main__":
    main()
