import os
import telebot
import requests

# تنظیمات از Secrets
TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
ACCESS_TOKEN = os.getenv('CTRADER_ACCESS_TOKEN')
ACCOUNT_ID = os.getenv('CTRADER_ACCOUNT_ID')

bot = telebot.TeleBot(TOKEN)

def check_ctrader_connection():
    # تست زنده بودن اتصال به حساب
    url = f"https://sandbox-tradeapi.ctrader.com/v2/symbols?oauth_token={ACCESS_TOKEN}"
    try:
        response = requests.get(url)
        return response.status_code == 200
    except:
        return False

def get_order_flow_analysis():
    # در این مرحله دیتای لایه ۲ شبیه‌سازی می‌شود تا تاییدیه نهایی بروکر برسد
    # فرض می‌کنیم بازار در حال نوسان است
    buy_pressure = 75  # درصد خریداران
    sell_pressure = 25 # درصد فروشندگان
    imbalance = (buy_pressure - sell_pressure) / 100
    return imbalance, 2040.50

def run_bot():
    connected = check_ctrader_connection()
    imbalance, price = get_order_flow_analysis()
    
    report = "📡 وضعیت ربات: آنلاین و در حال تحلیل...\n"
    if connected:
        report += "✅ اتصال به حساب cTrader: برقرار\n"
    else:
        report += "❌ اتصال به حساب cTrader: خطا (توکن را چک کنید)\n"

    # ارسال گزارش وضعیت (برای اینکه مطمئن شوی کار می‌کند)
    bot.send_message(CHAT_ID, report)

    # منطق سیگنال‌دهی
    if imbalance > 0.45:
        msg = (
            f"🔔 **سیگنال خرید (BUY)**\n"
            f"💎 نماد: XAUUSD (طلا)\n"
            f"📈 قدرت خریداران: {imbalance*100}%\n"
            f"💰 قیمت: {price}\n"
            f"🎯 حد سود: {price + 4}\n"
            f"🛑 حد ضرر: {price - 3}"
        )
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    
    elif imbalance < -0.45:
        msg = (
            f"🔔 **سیگنال فروش (SELL)**\n"
            f"💎 نماد: XAUUSD (طلا)\n"
            f"📉 قدرت فروشندگان: {abs(imbalance)*100}%\n"
            f"💰 قیمت: {price}\n"
            f"🎯 حد سود: {price - 4}\n"
            f"🛑 حد ضرر: {price + 3}"
        )
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown")

if __name__ == "__main__":
    run_bot()
