# راهنمای دیپلوی ربات روی سرور (اجرای ۲۴ ساعته)

با اجرای `python bot.py` روی سیستم خودت، به محض بستن ترمینال یا خاموش‌شدن سیستم، ربات هم متوقف می‌شه.
برای اجرای مداوم باید روی یک VPS (سرور مجازی) بذاریش. دو روش رو اینجا توضیح می‌دم؛ روش systemd ساده‌تره.

---

## پیش‌نیاز: یک VPS

- هر سروری با Ubuntu 22.04 یا 24.04 کافیه (ارزون‌ترین پلن هر ارائه‌دهنده‌ای مثل Hetzner، DigitalOcean، یا سرورهای داخلی کافیه — نیازی به منابع سنگین نیست، ۱ vCPU و ۱GB رم کفایت می‌کنه)
- دسترسی SSH به سرور

---

## روش ۱: systemd (پیشنهادی و ساده‌تر)

### ۱) اتصال به سرور و آماده‌سازی
```bash
ssh user@YOUR_SERVER_IP

sudo apt update && sudo apt install -y python3 python3-venv python3-pip git
```

### ۲) انتقال فایل‌های پروژه
از سیستم خودت (نه سرور)، فایل‌ها رو آپلود کن:
```bash
scp -r tg_signal_bot user@YOUR_SERVER_IP:~/tg_signal_bot
```

### ۳) ساخت محیط مجازی و نصب پکیج‌ها (روی سرور)
```bash
cd ~/tg_signal_bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### ۴) تنظیم توکن
```bash
cp .env.example .env
nano .env   # توکن بات رو اینجا بذار و ذخیره کن (Ctrl+O سپس Ctrl+X)
```

### ۵) ساخت سرویس systemd
```bash
sudo nano /etc/systemd/system/tg-signal-bot.service
```
این محتوا رو بذار توش (مسیر `/home/user/tg_signal_bot` رو با مسیر واقعی خودت جایگزین کن):
```ini
[Unit]
Description=Telegram Crypto Signal Bot
After=network.target

[Service]
Type=simple
User=user
WorkingDirectory=/home/user/tg_signal_bot
ExecStart=/home/user/tg_signal_bot/venv/bin/python bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### ۶) فعال‌سازی و اجرا
```bash
sudo systemctl daemon-reload
sudo systemctl enable tg-signal-bot
sudo systemctl start tg-signal-bot
```

### دستورات مفید بعد از راه‌اندازی
```bash
sudo systemctl status tg-signal-bot     # وضعیت فعلی
sudo systemctl restart tg-signal-bot    # ری‌استارت (بعد از تغییر کد)
journalctl -u tg-signal-bot -f          # مشاهده لاگ زنده
sudo systemctl stop tg-signal-bot       # توقف
```

با `Restart=always`، حتی اگه ربات کرش کنه یا سرور ری‌استارت بشه، خودش دوباره بالا میاد.

---

## روش ۲: Docker (اگه با Docker راحت‌تری)

### ۱) ساخت Dockerfile
توی پوشه پروژه یه فایل به اسم `Dockerfile` بساز:
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "bot.py"]
```

### ۲) ساخت و اجرای کانتینر
```bash
docker build -t tg-signal-bot .
docker run -d --name tg-signal-bot --restart always --env-file .env tg-signal-bot
```

### دستورات مفید
```bash
docker logs -f tg-signal-bot     # لاگ زنده
docker restart tg-signal-bot     # ری‌استارت
docker stop tg-signal-bot        # توقف
```

---

## نکات امنیتی مهم

- فایل `.env` رو هیچ‌وقت جایی عمومی (مثل گیت‌هاب پابلیک) آپلود نکن؛ توکن بات توشه.
- اگه توکن لو رفت، توی BotFather با دستور `/revoke` توکن قدیمی رو باطل کن و توکن جدید بگیر.
- سرور رو با یوزر غیر root اجرا کن و فایروال (`ufw`) رو فعال نگه دار.

---

## بعد از تغییر کد

اگه بعداً منطق سیگنال یا تنظیمات رو عوض کردی، فایل جدید رو جایگزین کن و سرویس رو ری‌استارت کن:
```bash
scp bot.py user@YOUR_SERVER_IP:~/tg_signal_bot/bot.py
ssh user@YOUR_SERVER_IP "sudo systemctl restart tg-signal-bot"
```
