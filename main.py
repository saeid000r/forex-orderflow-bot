import os
import telebot
import requests

TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
ACCESS_TOKEN = os.getenv('CTRADER_ACCESS_TOKEN')
ACCOUNT_ID = os.getenv('CTRADER_ACCOUNT_ID')

bot = telebot.TeleBot(TOKEN)

def test_connection():
    base_url = "https://sandbox-tradeapi.ctrader.com/v2"
    report = "🔍 **گزارش عیب‌یابی اتصال:**\n\n"
    
    # تست ۱: بررسی اعتبار توکن و دسترسی به حساب
    try:
        acc_url = f"{base_url}/symbols?oauth_token={ACCESS_TOKEN}&accountId={ACCOUNT_ID}"
        res = requests.get(acc_url, timeout=10).json()
        if "symbol" in res:
            report += "✅ ۱. توکن و Account ID معتبر هستند.\n"
        else:
            report += f"❌ ۱. توکن یا Account ID اشتباه است.\n(پیام سرور: {res.get('errorCode')})\n"
    except Exception as e:
        report += f"❌ ۱. خطای شبکه در اتصال به cTrader: {e}\n"

    # تست ۲: بررسی وضعیت بازار
    try:
        # درخواست دیتای قدیمی‌تر (برای وقتی بازار بسته است)
        bars_url = f"{base_url}/symbols/1/trendbars?oauth_token={ACCESS_TOKEN}&accountId={ACCOUNT_ID}&period=D1&from=1700000000000&to=1740000000000"
        res_bars = requests.get(bars_url, timeout=10).json()
        if "trendbar" in res_bars:
            report += "✅ ۲. دیتای تاریخی در دسترس است.\n"
        else:
            report += "⚠️ ۲. بازار بسته است یا دیتایی برای این نماد وجود ندارد.\n"
    except:
        report += "❌ ۲. خطا در بررسی وضعیت بازار.\n"

    report += "\n💡 **راهنمایی:** اگر گزینه ۱ سبز و گزینه ۲ زرد است، یعنی باید تا باز شدن بازار (دوشنبه) صبر کنید."
    bot.send_message(CHAT_ID, report, parse_mode="Markdown")

if __name__ == "__main__":
    test_connection()
