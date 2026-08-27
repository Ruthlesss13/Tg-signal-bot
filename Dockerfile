FROM python:3.11-slim

WORKDIR /app

# نصب وابستگی‌های سیستمی برای mplfinance و matplotlib
RUN apt-get update && apt-get install -y \
    build-essential \
    libfreetype6-dev \
    libpng-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

# کپی requirements و نصب کتابخانه‌های Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# کپی بقیه فایل‌های پروژه
COPY . .

# اجرای ربات
CMD ["python", "bot.py"]
