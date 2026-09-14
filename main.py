import os
import telebot
import requests

# دریافت توکن‌ها از Secrets
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
ACCESS_TOKEN = os.getenv('CTRADER_ACCESS_TOKEN')

bot = telebot.TeleBot(TELEGRAM_TOKEN)

def get_ctrader_account_info():
    # استفاده از API برای تست اتصال
    url = f"https://sandbox-tradeapi.ctrader.com/v2/symbols?oauth_token={ACCESS_TOKEN}"
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return "اتصال موفق"
        else:
            return f"خطا در اتصال: {response.status_code}"
    except Exception as e:
        return "خطای ارتباطی"

def run_task():
    status = get_ctrader_account_info()
    
    # ساخت پیام ساده بدون کاراکترهای خاص برای جلوگیری از ارور
    final_msg = (
        "🤖 گزارش وضعیت ربات\n\n"
        f"📡 وضعیت اتصال به سی‌تریدر: {status}\n"
        "📊 نماد: XAUUSD\n"
        "✅ ربات آماده دریافت سیگنال است"
    )
    
    # ارسال پیام بدون parse_mode برای امنیت بیشتر
    bot.send_message(CHAT_ID, final_msg)
    print("Message sent to Telegram!")

if __name__ == "__main__":
    run_task()
