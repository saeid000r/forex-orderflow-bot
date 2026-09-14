import os
import telebot
import requests

# دریافت توکن‌ها از Secrets
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
ACCESS_TOKEN = os.getenv('CTRADER_ACCESS_TOKEN')
CLIENT_ID = os.getenv('CTRADER_CLIENT_ID')
CLIENT_SECRET = os.getenv('CTRADER_CLIENT_SECRET')

bot = telebot.TeleBot(TELEGRAM_TOKEN)

def get_ctrader_account_info():
    # آدرس API برای دریافت لیست حساب‌ها
    url = f"https://sandbox-tradeapi.ctrader.com/v2/symbols?oauth_token={ACCESS_TOKEN}"
    # نکته: برای حساب واقعی آدرس متفاوت است، فعلاً برای تست لایه اتصال:
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return "✅ اتصال به cTrader برقرار شد!"
        else:
            return f"❌ خطا در اتصال: {response.status_code}"
    except Exception as e:
        return f"⚠️ خطای سیستمی: {str(e)}"

def run_task():
    status_msg = get_ctrader_account_info()
    
    # پیام به تلگرام برای اطمینان از کارکرد صحیح
    final_msg = (
        f"🤖 **گزارش وضعیت ربات**\n\n"
        f"📡 وضعیت اتصال: {status_msg}\n"
        f"📊 نماد تحت نظر: XAUUSD (Gold)\n"
        f"⏳ زمان چک بعدی: ۱۵ دقیقه دیگر"
    )
    bot.send_message(CHAT_ID, final_msg, parse_mode="Markdown")

if __name__ == "__main__":
    run_task()
