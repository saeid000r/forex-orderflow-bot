import os
import telebot
import requests

TOKEN = os.getenv('TELEGRAM_TOKEN')
CHAT_ID = os.getenv('CHAT_ID')
ACCESS_TOKEN = os.getenv('CTRADER_ACCESS_TOKEN')
ACCOUNT_ID = os.getenv('CTRADER_ACCOUNT_ID')

bot = telebot.TeleBot(TOKEN)

def debug_ctrader():
    report = "🔍 **گزارش عیب‌یابی سیستم:**\n\n"
    
    # تست ۱: بررسی اعتبار توکن و حساب
    try:
        url = f"https://live.ctraderapi.com/v2/symbols?oauth_token={ACCESS_TOKEN}&accountId={ACCOUNT_ID}"
        res = requests.get(url, timeout=10)
        
        if res.status_code == 200:
            report += "✅ ۱. اتصال موفقیت‌آمیز بود! (توکن و آیدی درست هستند)\n"
        elif res.status_code == 401:
            report += "❌ ۱. خطای ۴۰۱: توکن شما منقضی شده یا اشتباه است.\n"
        elif res.status_code == 403:
            report += "❌ ۱. خطای ۴۰3: این حساب اجازه دسترسی به این اپلیکیشن را ندارد.\n"
        else:
            report += f"❓ ۱. وضعیت غیرمنتظره: {res.status_code}\nپیام سرور: {res.text[:100]}\n"
    except Exception as e:
        report += f"❌ ۱. خطای شبکه: {str(e)}\n"

    # تست ۲: بررسی برای سرور Sandbox
    try:
        url_sb = f"https://sandbox-tradeapi.ctrader.com/v2/symbols?oauth_token={ACCESS_TOKEN}&accountId={ACCOUNT_ID}"
        res_sb = requests.get(url_sb, timeout=10)
        if res_sb.status_code == 200:
            report += "✅ ۲. اتصال به سرور تست (Sandbox) موفق بود!\n"
    except: pass

    bot.send_message(CHAT_ID, report)

if __name__ == "__main__":
    debug_ctrader()
