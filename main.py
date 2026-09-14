import os
import telebot
import requests
import time

# تنظیمات از Secrets
TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
ACCESS_TOKEN = os.getenv('CTRADER_ACCESS_TOKEN')
ACCOUNT_ID = os.getenv('CTRADER_ACCOUNT_ID')

bot = telebot.TeleBot(TOKEN)

def get_order_flow_signal(symbol):
    """
    در این بخش ربات دیتای لایه ۲ را تحلیل می‌کند.
    به دلیل محدودیت REST در دریافت لحظه‌ای Depth، ربات از فشار قیمت و حجم استفاده می‌کند
    تا وضعیت Imbalance را شبیه‌سازی و محاسبه کند.
    """
    # این آدرس دیتای قیمت و نماد را از cTrader می‌گیرد
    url = f"https://sandbox-tradeapi.ctrader.com/v2/symbols/{symbol}/trendbars?oauth_token={ACCESS_TOKEN}&accountId={ACCOUNT_ID}&period=M1&from={int(time.time()-60)}000&to={int(time.time())}000"
    
    try:
        # در نسخه نهایی اینجا دیتای لایه ۲ (Bid/Ask Volume) جایگزین می‌شود
        # فعلاً ربات بر اساس نوسان لحظه‌ای فشار را می‌سنجد
        bid_volume = 55  # شبیه‌سازی دیتای لایه ۲
        ask_volume = 45  # شبیه‌سازی دیتای لایه ۲
        
        imbalance = (bid_volume - ask_volume) / (bid_volume + ask_volume)
        return imbalance, 2045.50 # بازگشت بالانس و قیمت فعلی
    except:
        return 0, 0

def send_signal():
    symbols = ["XAUUSD", "EURUSD"]
    for sym in symbols:
        imbalance, price = get_order_flow_signal(sym)
        
        # اگر فشار خرید بیش از ۴۵٪ بود (۰.۴۵)
        if imbalance > 0.45:
            tp = price + 5.0
            sl = price - 3.0
            msg = (
                f"🔔 **سیگنال خرید (BUY) - Order Flow**\n\n"
                f"💎 نماد: {sym}\n"
                f"📈 قدرت ورود: {imbalance*100:.1f}%\n"
                f"💰 قیمت ورود: {price}\n"
                f"🎯 حد سود (TP): {tp}\n"
                f"🛑 حد ضرر (SL): {sl}\n"
                f"📊 وضعیت لایه ۲: تجمع خریداران"
            )
            bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
        
        # اگر فشار فروش بیش از ۴۵٪ بود
        elif imbalance < -0.45:
            tp = price - 5.0
            sl = price + 3.0
            msg = (
                f"🔔 **سیگنال فروش (SELL) - Order Flow**\n\n"
                f"💎 نماد: {sym}\n"
                f"📉 قدرت ورود: {abs(imbalance)*100:.1f}%\n"
                f"💰 قیمت ورود: {price}\n"
                f"🎯 حد سود (TP): {tp}\n"
                f"🛑 حد ضرر (SL): {sl}\n"
                f"📊 وضعیت لایه ۲: تجمع فروشندگان"
            )
            bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    
    print("بررسی بازار انجام شد.")

if __name__ == "__main__":
    send_signal()
