import os
import telebot
import requests

# خواندن توکن‌ها از بخش Secrets
TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')

bot = telebot.TeleBot(TOKEN)

def get_signal():
    # شبیه‌ساز داده (اینجا بعداً به cTrader وصل می‌شود)
    # فعلاً برای تست سلامت ربات، یک سیگنال فرضی می‌فرستیم
    return {
        "symbol": "XAUUSD",
        "type": "BUY",
        "price": "2042.50",
        "imbalance": "48%"
    }

def run_bot():
    try:
        data = get_signal()
        message = (
            f"🔔 **سیگنال جدید Order Flow**\n\n"
            f"💎 نماد: {data['symbol']}\n"
            f"📈 نوع: {data['type']}\n"
            f"💰 قیمت ورود: {data['price']}\n"
            f"📊 قدرت فشار خرید: {data['imbalance']}\n"
            f"🛡 وضعیت: تست اکانت جدید"
        )
        bot.send_message(CHAT_ID, message, parse_mode="Markdown")
        print("Signal sent successfully!")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    run_bot()
