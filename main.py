#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cTrader Level-2 Order-Flow Bot — نسخه اصلاح‌شده (سازگار با ctrader-open-api 0.9.2)

منطق استراتژی (بدون تغییر نسبت به نسخه شما):
  Imbalance = (حجم خرید - حجم فروش) / حجم کل  از روی دفتر سفارش‌های لحظه‌ای (Level 2)
  imbalance >= +40%  →  Normal BUY      |  > +60%  →  🔥 Golden BUY
  imbalance <= -40%  →  Normal SELL     |  < -60%  →  🔥 Golden SELL
  Entry = میانگین بهترین خرید/فروش لحظه‌ای | TP = 0.2% | SL = 0.1%
  نتایج در journal.json ذخیره و وین‌ریت محاسبه می‌شود.

باگ‌هایی که در نسخه قبلی باعث خطا (exit code 1) می‌شد و اینجا اصلاح شده:
  1) ایمپورت اشتباه پیام‌ها (ماژول‌های ProtoOAxxx_pb2 وجود ندارند؛ همه در OpenApiMessages_pb2 هستند)
  2) استفاده از ProtoOAGetDepthQuotesReq که اصلاً وجود ندارد → جایگزین با Subscribe + رویداد DepthEvent
  3) پاسخ‌ها به صورت ProtoMessage خام می‌آیند و باید با Protobuf.extract باز شوند
  4) symbolId در درخواست‌ها repeated است و باید با extend پر شود، نه انتساب مستقیم
  5) قیمت: مقیاس قیمت در Open API همیشه ثابت 100000 است (اثبات‌شده با دیتای واقعی بازار)؛
     digits فقط تعداد ارقام اعشار نمایشی است، نه مقیاس!
  6) نسخه ۲ (فیکس پایداری): رفرش توکن فقط روی ارورهای واقعاً مربوط به توکن انجام می‌شود
     (رفرش بی‌جا توکن سالم را باطل می‌کرد!) + پیام تمدید شامل هر دو توکن + ضداسپم پیام خطا.
  7) نسخه ۳ (عیب‌یابی): موقع خطای احراز هویت، لیست حساب‌های قابل‌دسترس با توکن در لاگ چاپ می‌شود.
"""

import os
import sys
import json
import time
import traceback
from datetime import datetime, timezone

import requests

from twisted.internet import reactor, threads, defer
from ctrader_open_api import Client, TcpProtocol
from ctrader_open_api.protobuf import Protobuf
from ctrader_open_api.messages import OpenApiMessages_pb2 as Msg


# ---------------------------------------------------------------- تنظیمات
def env(name, default=""):
    v = os.getenv(name, default)
    return v.strip() if isinstance(v, str) else v


def env_int(name, default):
    try:
        return int(env(name, "") or default)
    except ValueError:
        return default


TELEGRAM_TOKEN = env("TELEGRAM_TOKEN")
CHAT_ID = env("CHAT_ID")
CLIENT_ID = env("CTRADER_CLIENT_ID")
CLIENT_SECRET = env("CTRADER_CLIENT_SECRET")
REFRESH_TOKEN = env("CTRADER_REFRESH_TOKEN")
ACCOUNT_ID_RAW = env("CTRADER_ACCOUNT_ID", "0")

ACCESS_TOKEN_HOLDER = {"value": env("CTRADER_ACCESS_TOKEN")}

# اگر حسابتان Live است، در گیت‌هاب یک Secret به نام CTRADER_HOST با مقدار
# live.ctraderapi.com بسازید. در غیر این صورت (Demo) نیازی به این کار نیست.
CTRADER_HOST = env("CTRADER_HOST") or "demo.ctraderapi.com"
CTRADER_PORT = env_int("CTRADER_PORT", 5035)
COLLECT_SECONDS = env_int("COLLECT_SECONDS", 15)     # مدت جمع‌آوری دیتای L2
FAILSAFE_SECONDS = env_int("FAILSAFE_SECONDS", 100)  # سقف امنیتی کل اجرا
ERROR_COOLDOWN_SECONDS = env_int("ERROR_COOLDOWN_SECONDS", 3600)  # ضداسپم پیام خطای تکراری

JOURNAL_FILE = "journal.json"

# مقیاس ثابت قیمت در cTrader Open API (با مقایسه با قیمت واقعی بازار تایید شد)
PRICE_SCALE = 100000

# سیمبل‌های هدف + نام‌های جایگزین رایج در بروکرهای مختلف
TARGETS = {
    "XAUUSD": ["XAUUSD", "GOLD"],
    "US30": ["US30", "DJ30", "DJI30", "DOW"],
    "BRENT": ["BRENT", "UKOIL", "XBRUSD", "BRN"],
    "USNDAQ100": ["USNDAQ100", "NAS100", "USTEC", "NDX", "NQ100", "NASDAQ"],
    "EURUSD": ["EURUSD"],
}

FALLBACK_DIGITS = {"XAUUSD": 2, "US30": 2, "BRENT": 2, "USNDAQ100": 2, "EURUSD": 5}

BUY_THRESHOLD = 0.40
GOLD_THRESHOLD = 0.60
TP_PCT = 0.002
SL_PCT = 0.001

SPOT_PT = Msg.ProtoOASpotEvent().payloadType
DEPTH_PT = Msg.ProtoOADepthEvent().payloadType

# ---------------------------------------------------------------- وضعیت سراسری
client = None
exit_code = 0
started = False
finished = False
ACCOUNT_ID = 0

symbol_ids = {}    # target -> symbolId
id_to_target = {}  # symbolId -> target
digits_map = {}    # symbolId -> digits (فقط برای تعداد ارقام اعشار نمایشی)
book = {}          # symbolId -> {quoteId: (side, size, priceRaw)}
spots = {}         # symbolId -> (bidRaw, askRaw)


# ---------------------------------------------------------------- ابزارها
def log(message):
    print(message, flush=True)
    return message


def send_telegram(text):
    """ارسال پیام تلگرام. True/False برمی‌گرداند و خطا را لاگ می‌کند."""
    if not TELEGRAM_TOKEN or not CHAT_ID:
        log("⚠️ TELEGRAM_TOKEN/CHAT_ID تنظیم نشده؛ پیام ارسال نشد.")
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
        if r.status_code != 200:
            log(f"⚠️ Telegram error {r.status_code}: {r.text[:200]}")
            return False
        return True
    except Exception as e:
        log(f"⚠️ Telegram send failed: {e}")
        return False


def load_journal():
    default = {"total": 0, "tp": 0, "sl": 0, "active": []}
    if os.path.exists(JOURNAL_FILE):
        try:
            with open(JOURNAL_FILE, "r") as f:
                data = json.load(f)
            for k in default:
                data.setdefault(k, default[k])
            return data
        except Exception as e:
            log(f"⚠️ journal.json خراب بود، از نو ساخته شد: {e}")
    return default


def save_journal(journal):
    with open(JOURNAL_FILE, "w") as f:
        json.dump(journal, f, indent=4)


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def normalize(name):
    return "".join(c for c in name.upper() if c.isalnum())


def win_rate_text(journal):
    closed = journal["tp"] + journal["sl"]
    if closed == 0:
        return "—"
    return f"{journal['tp'] * 100.0 / closed:.1f}% ({journal['tp']}W/{journal['sl']}L)"


def fmt_vol(units):
    if units >= 1_000_000:
        return f"{units / 1e6:.2f}M"
    if units >= 1_000:
        return f"{units / 1e3:.1f}K"
    return f"{units:.0f}"


def fmt_price(price, decimals):
    return f"{price:.{decimals}f}"


def is_token_error(fail):
    """آیا این خطا واقعاً مربوط به توکن است؟ فقط در این صورت رفرش مجاز است.

    نکته مهم: رفرش کردن روی ارورهای غیرتوکن (مثل مشکل حساب)، توکن سالم را
    باطل و رفرش‌توکن را می‌سوزاند و قطعی موقت را دائمی می‌کند!
    """
    try:
        msg = (fail.getErrorMessage() or "").lower()
    except Exception:
        return False
    hints = (
        "access_token_invalid",
        "access token",
        "invalid token",
        "token expired",
        "token_expired",
        "expired token",
        "unauthorized",
        "unauthorised",
    )
    return any(h in msg for h in hints)


def is_auth_error(err_text):
    """آیا این خطا از جنس احراز هویت است؟ (برای اجرای عیب‌یابی حساب‌ها)"""
    t = (err_text or "").lower()
    return any(k in t for k in ("auth", "token", "account", "disabled", "forbidden", "denied"))


def should_send_error(journal, err_text):
    """ضداسپم: ارور تکراری فقط بعد از cooldown دوباره به تلگرام ارسال می‌شود."""
    now = time.time()
    short = (err_text or "")[:300]
    last_t = journal.get("last_error_ts", 0)
    last_e = journal.get("last_error_text", "")
    if short != last_e or (now - last_t) >= ERROR_COOLDOWN_SECONDS:
        journal["last_error_ts"] = now
        journal["last_error_text"] = short
        return True
    return False


# ---------------------------------------------------------------- لایه cTrader
def api_send(req, timeout=10):
    """ارسال درخواست و باز کردن پاسخTyped با Protobuf.extract."""
    d = client.send(req, responseTimeoutInSeconds=timeout)
    d.addCallback(Protobuf.extract)
    return d


def check_not_error(res):
    name = type(res).__name__
    if "ErrorRes" in name:
        raise Exception(
            f"cTrader {name}: code={getattr(res, 'errorCode', '?')} "
            f"desc={getattr(res, 'description', '')}"
        )
    return res


def on_message_received(client_obj, message):
    """دریافت رویدادهای لحظه‌ای (Spot و Depth)."""
    try:
        if message.payloadType == SPOT_PT:
            ev = Protobuf.extract(message)
            if ev.symbolId in id_to_target:
                spots[ev.symbolId] = (ev.bid, ev.ask)
        elif message.payloadType == DEPTH_PT:
            ev = Protobuf.extract(message)
            if ev.symbolId not in id_to_target:
                return
            order_book = book.setdefault(ev.symbolId, {})
            for qid in ev.deletedQuotes:
                order_book.pop(qid, None)
            for q in ev.newQuotes:
                # هر کوت یا سمت خرید است (bid) یا سمت فروش (ask)
                if q.bid:
                    order_book[q.id] = ("bid", q.size, q.bid)
                elif q.ask:
                    order_book[q.id] = ("ask", q.size, q.ask)
    except Exception:
        log(f"⚠️ on_message error:\n{traceback.format_exc()}")


def on_disconnected(client_obj, reason):
    log(f"⚠️ Disconnected: {reason} (تلاش مجدد خودکار انجام می‌شود)")


def handle_account_list(res):
    """لاگ کردن لیست حساب‌های قابل‌دسترس با توکن فعلی (عیب‌یابی). هیچ‌وقت exception نمی‌دهد."""
    try:
        res = check_not_error(res)
    except Exception as e:
        log(f"🔍 گرفتن لیست حساب‌ها ناموفق بود: {e}")
        return
    try:
        accs = list(res.ctidTraderAccount)
    except Exception as e:
        log(f"🔍 پاسخ لیست حساب‌ها غیرمنتظره بود: {e}")
        return
    scope = getattr(res, "permissionScope", "")
    log(f"🔍 دسترسی توکن (scope): {scope or '—'}")
    if not accs:
        log("🔍 این توکن به هیچ حساب معاملاتی دسترسی ندارد! توکن را با authorize درست بگیرید.")
        return
    log(f"🔍 حساب‌های قابل‌دسترس با این توکن ({len(accs)}):")
    found = False
    for a in accs:
        try:
            aid = a.ctidTraderAccountId
            if aid == ACCOUNT_ID:
                found = True
                mark = "✅ ← همین حساب بات"
            else:
                mark = ""
            log(f"   • ID={aid} login={a.traderLogin} live={a.isLive} {mark}")
        except Exception:
            continue
    if not found:
        log(f"🔍 حساب بات (ID={ACCOUNT_ID}) در این لیست نیست! ID سکرت اشتباه است یا توکن به آن دسترسی ندارد.")


def try_diagnose_accounts():
    """گرفتن لیست حساب‌های توکن برای عیب‌یابی. همیشه با None تمام می‌شود."""
    log("🔍 در حال گرفتن لیست حساب‌های قابل‌دسترس با این توکن...")
    try:
        req = Msg.ProtoOAGetAccountListByAccessTokenReq()
        req.accessToken = ACCESS_TOKEN_HOLDER["value"]
        d = api_send(req, timeout=8)
    except Exception as e:
        log(f"🔍 امکان ارسال درخواست عیب‌یابی نیست: {e}")
        return defer.succeed(None)

    def on_res(res):
        handle_account_list(res)
        return None

    def on_err(f):
        log(f"🔍 گرفتن لیست حساب‌ها ناموفق بود: {f.getErrorMessage()}")
        return None

    d.addCallbacks(on_res, on_err)
    return d


def send_app_auth():
    req = Msg.ProtoOAApplicationAuthReq()
    req.clientId = CLIENT_ID
    req.clientSecret = CLIENT_SECRET
    d = api_send(req)
    d.addCallback(check_not_error)
    return d


def try_refresh_token():
    """تمدید اکسس‌توکن با رفرش‌توکن. (access, refresh) یا None."""
    try:
        r = requests.post(
            "https://openapi.ctrader.com/apps/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": REFRESH_TOKEN,
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
            },
            timeout=15,
        )
        if r.status_code == 200:
            data = r.json()
            if data.get("access_token"):
                return data.get("access_token"), data.get("refresh_token")
        log(f"⚠️ Refresh token rejected: {r.status_code} {r.text[:200]}")
    except Exception as e:
        log(f"⚠️ Refresh request failed: {e}")
    return None


def send_account_auth(attempt=1):
    req = Msg.ProtoOAAccountAuthReq()
    req.ctidTraderAccountId = ACCOUNT_ID
    req.accessToken = ACCESS_TOKEN_HOLDER["value"]
    d = api_send(req)
    d.addCallback(check_not_error)
    if attempt == 1 and REFRESH_TOKEN:
        d.addErrback(try_refresh_then_retry)
    return d


def try_refresh_then_retry(fail):
    # فقط اگر ارور واقعاً مربوط به توکن است رفرش کن؛ وگرنه توکن سالم می‌سوزد!
    if not is_token_error(fail):
        log("⏭️ این خطا مربوط به توکن نیست؛ رفرش انجام نشد تا توکن‌های سالم باطل نشوند.")
        return fail
    log(f"⚠️ Account auth failed (token): {fail.getErrorMessage()} — تلاش برای تمدید توکن...")
    d2 = threads.deferToThread(try_refresh_token)

    def after_refresh(new):
        if new and new[0]:
            ACCESS_TOKEN_HOLDER["value"] = new[0]
            log("✅ توکن با موفقیت تمدید شد؛ تلاش مجدد برای احراز هویت...")
            send_telegram(
                "⚠️ <b>توکن cTrader منقضی شده بود و خودکار تمدید شد.</b>\n"
                "این ران با توکن جدید ادامه پیدا کرد. برای ران‌های بعدی، هر دو سکرت را به‌روز کنید:\n\n"
                "CTRADER_ACCESS_TOKEN:\n"
                f"<code>{new[0]}</code>\n\n"
                "CTRADER_REFRESH_TOKEN:\n"
                f"<code>{new[1] or '—'}</code>\n\n"
                "⚠️ این پیام حاوی توکن است؛ بعد از کپی، آن را از تلگرام پاک کنید."
            )
            return send_account_auth(attempt=2)
        log("❌ تمدید توکن ناموفق بود.")
        return fail

    d2.addCallback(after_refresh)
    return d2


def fetch_symbols():
    req = Msg.ProtoOASymbolsListReq()
    req.ctidTraderAccountId = ACCOUNT_ID
    req.includeArchivedSymbols = False
    d = api_send(req)
    d.addCallback(check_not_error)
    d.addCallback(on_symbols_list)
    return d


def on_symbols_list(res):
    available = []
    for s in res.symbol:
        available.append(s.symbolName)
        norm = normalize(s.symbolName)
        for target, aliases in TARGETS.items():
            if target in symbol_ids:
                continue
            for alias in aliases:
                if alias in norm:
                    symbol_ids[target] = s.symbolId
                    id_to_target[s.symbolId] = target
                    book[s.symbolId] = {}
                    break
    log(f"ℹ️ سیمبل‌های حساب ({len(available)}): {', '.join(sorted(available)[:50])}")
    if not symbol_ids:
        raise Exception(
            "هیچ‌کدام از سیمبل‌های هدف روی این حساب پیدا نشد. "
            f"هدف‌ها: {list(TARGETS)} — نام دقیق سیمبل بروکرتان را از لاگ بالا چک کنید."
        )
    log(f"✅ سیمبل‌های مچ‌شده: {symbol_ids}")
    return None


def fetch_digits():
    """گرفتن digits هر سیمبل برای تعداد ارقام اعشار نمایشی."""
    req = Msg.ProtoOASymbolByIdReq()
    req.ctidTraderAccountId = ACCOUNT_ID
    req.symbolId.extend(list(symbol_ids.values()))
    d = api_send(req)

    def on_res(res):
        try:
            res = check_not_error(res)
            for s in res.symbol:
                digits_map[s.symbolId] = s.digits
            log(f"ℹ️ digits سیمبل‌ها: {digits_map}")
        except Exception as e:
            log(f"⚠️ گرفتن digits ناموفق بود، از مقادیر پیش‌فرض استفاده می‌شود: {e}")
        return None

    def on_err(fail):
        log(f"⚠️ گرفتن digits ناموفق بود، از مقادیر پیش‌فرض استفاده می‌شود: {fail.getErrorMessage()}")
        return None

    d.addCallback(on_res)
    d.addErrback(on_err)
    return d


def subscribe_all():
    ids = list(symbol_ids.values())

    def sub_spots(_=None):
        req = Msg.ProtoOASubscribeSpotsReq()
        req.ctidTraderAccountId = ACCOUNT_ID
        req.symbolId.extend(ids)
        d = api_send(req)
        d.addCallback(check_not_error)
        return d

    def sub_depth(_=None):
        req = Msg.ProtoOASubscribeDepthQuotesReq()
        req.ctidTraderAccountId = ACCOUNT_ID
        req.symbolId.extend(ids)
        d = api_send(req)
        d.addCallback(check_not_error)
        return d

    d = sub_spots()
    d.addCallback(sub_depth)
    return d


# ---------------------------------------------------------------- تحلیل و ژورنال
def analyze_symbol(target, sym_id):
    """تحلیل دفتر سفارش یک سیمبل. dict نتیجه یا None اگر دیتا کافی نباشد."""
    order_book = book.get(sym_id, {})
    bid_vol = sum(size for (side, size, _) in order_book.values() if side == "bid")
    ask_vol = sum(size for (side, size, _) in order_book.values() if side == "ask")
    total = bid_vol + ask_vol
    if total <= 0:
        return None

    imbalance = (bid_vol - ask_vol) / total
    decimals = digits_map.get(sym_id, FALLBACK_DIGITS.get(target, 5))

    price = None
    if sym_id in spots and spots[sym_id][0] and spots[sym_id][1]:
        b, a = spots[sym_id]
        price = ((b + a) / 2.0) / PRICE_SCALE
    else:
        bids = [p for (s, _, p) in order_book.values() if s == "bid"]
        asks = [p for (s, _, p) in order_book.values() if s == "ask"]
        if bids and asks:
            price = ((max(bids) + min(asks)) / 2.0) / PRICE_SCALE
    if price is None or price <= 0:
        return None

    signal = None
    if imbalance >= BUY_THRESHOLD:
        signal = "BUY"
    elif imbalance <= -BUY_THRESHOLD:
        signal = "SELL"

    return {
        "target": target,
        "imbalance": imbalance,
        "signal": signal,
        "golden": abs(imbalance) > GOLD_THRESHOLD,
        "price": price,
        "decimals": decimals,
        "bid_vol": bid_vol / 100.0,   # size بر حسب سنت است
        "ask_vol": ask_vol / 100.0,
        "levels": len(order_book),
    }


def finish():
    global finished, exit_code
    if finished:
        return
    finished = True
    try:
        journal = load_journal()
        current_prices = {}
        new_count = 0

        for target, sym_id in symbol_ids.items():
            result = analyze_symbol(target, sym_id)
            if result is None:
                log(f"⏭️ {target}: دیتای L2 نرسید (مارکت بسته است یا بروکر DOM نمی‌دهد).")
                continue
            current_prices[target] = result["price"]
            dec = result["decimals"]
            log(
                f"📊 {target}: imb={result['imbalance']*100:+.0f}% "
                f"bid={fmt_vol(result['bid_vol'])} ask={fmt_vol(result['ask_vol'])} "
                f"levels={result['levels']} price={fmt_price(result['price'], dec)}"
            )

            if not result["signal"]:
                continue
            if any(s.get("symbol") == target for s in journal["active"]):
                log(f"⏭️ {target}: سیگنال باز قبلی هنوز فعال است؛ سیگنال تکراری رد شد.")
                continue

            sig = result["signal"]
            price = result["price"]
            if sig == "BUY":
                tp = price * (1 + TP_PCT)
                sl = price * (1 - SL_PCT)
            else:
                tp = price * (1 - TP_PCT)
                sl = price * (1 + SL_PCT)

            journal["active"].append({
                "symbol": target,
                "type": sig,
                "entry": round(price, dec),
                "tp": round(tp, dec),
                "sl": round(sl, dec),
                "decimals": dec,
                "imbalance": round(result["imbalance"] * 100, 1),
                "time": now_iso(),
            })
            journal["total"] += 1
            new_count += 1

            tag = "🔥 Golden" if result["golden"] else ("🟢 Normal" if sig == "BUY" else "🔴 Normal")
            send_telegram(
                f"{tag} <b>{sig}</b>\n"
                f"Symbol: <b>{target}</b>\n"
                f"L2 Imbalance: <code>{result['imbalance']*100:+.0f}%</code> "
                f"(Bid {fmt_vol(result['bid_vol'])} / Ask {fmt_vol(result['ask_vol'])})\n"
                f"Entry: <code>{fmt_price(price, dec)}</code>\n"
                f"TP: <code>{fmt_price(tp, dec)}</code> | SL: <code>{fmt_price(sl, dec)}</code>"
            )

        # بررسی پوزیشن‌های باز قبلی با قیمت‌های فعلی
        still_active = []
        for s in journal["active"]:
            cp = current_prices.get(s.get("symbol"))
            if cp is None:
                still_active.append(s)
                continue
            sdec = s.get("decimals", 5)
            hit_tp = (s["type"] == "BUY" and cp >= s["tp"]) or (s["type"] == "SELL" and cp <= s["tp"])
            hit_sl = (s["type"] == "BUY" and cp <= s["sl"]) or (s["type"] == "SELL" and cp >= s["sl"])
            if hit_tp:
                journal["tp"] += 1
                send_telegram(f"✅ <b>TP HIT</b>: {s['symbol']} {s['type']} @ {fmt_price(cp, sdec)}\nWinRate: {win_rate_text(journal)}")
            elif hit_sl:
                journal["sl"] += 1
                send_telegram(f"❌ <b>SL HIT</b>: {s['symbol']} {s['type']} @ {fmt_price(cp, sdec)}\nWinRate: {win_rate_text(journal)}")
            else:
                still_active.append(s)

        journal["active"] = still_active
        journal["updated"] = now_iso()
        save_journal(journal)
        log(f"🏁 تمام شد. سیگنال جدید: {new_count} | فعال: {len(still_active)} | وین‌ریت: {win_rate_text(journal)}")
    except Exception:
        exit_code = 1
        log(f"❌ خطا در finish:\n{traceback.format_exc()}")
    finally:
        try:
            reactor.stop()
        except Exception:
            pass


def on_fatal(fail):
    global finished
    if finished:
        return
    finished = True
    err = fail.getErrorMessage()
    log(f"❌ اجرای بات ناموفق بود: {err}\n{fail.getTraceback()}")
    if is_auth_error(err):
        # قبل از پایان، لیست حساب‌های قابل‌دسترس را برای عیب‌یابی می‌گیریم
        d = try_diagnose_accounts()
        d.addBoth(lambda _: finish_fatal(err))
    else:
        finish_fatal(err)


def finish_fatal(err):
    global exit_code
    exit_code = 1
    journal = load_journal()
    try:
        if should_send_error(journal, err):
            send_telegram(
                "❌ <b>خطا در اجرای بات cTrader</b>\n"
                f"<code>{err[:300]}</code>\n"
                "لاگ کامل را در تب Actions گیت‌هاب ببینید.\n"
                "اگر حسابتان Live است، سکرت <code>CTRADER_HOST=live.ctraderapi.com</code> را چک کنید."
            )
        else:
            log("🔕 خطای تکراری؛ پیام تلگرام ارسال نشد (ضداسپم).")
    except Exception:
        pass
    try:
        save_journal(journal)
    except Exception:
        pass
    try:
        reactor.stop()
    except Exception:
        pass
    return None


def failsafe():
    global finished, exit_code
    if finished:
        return
    finished = True
    exit_code = 1
    log(f"⏰ تایم‌اوت امنیتی ({FAILSAFE_SECONDS}s)؛ اتصال به cTrader برقرار/کامل نشد.")
    journal = load_journal()
    try:
        if should_send_error(journal, "TIMEOUT"):
            send_telegram(
                "⏰ <b>تایم‌اوت بات cTrader</b>\n"
                "اتصال به سرور cTrader کامل نشد. اینترنت/هاست/توکن‌ها را چک کنید."
            )
        else:
            log("🔕 خطای تکراری؛ پیام تلگرام ارسال نشد (ضداسپم).")
    except Exception:
        pass
    try:
        save_journal(journal)
    except Exception:
        pass
    try:
        reactor.stop()
    except Exception:
        pass


def on_connected(client_obj):
    global started
    if started:
        return
    started = True
    log(f"🔌 متصل شد به {CTRADER_HOST}:{CTRADER_PORT}")
    d = send_app_auth()
    d.addCallback(lambda _: log("✅ Application auth OK"))
    d.addCallback(lambda _: send_account_auth())
    d.addCallback(lambda _: log("✅ Account auth OK"))
    d.addCallback(lambda _: fetch_symbols())
    d.addCallback(lambda _: fetch_digits())
    d.addCallback(lambda _: subscribe_all())
    d.addCallback(lambda _: log(f"📡 اشتراک فعال شد. جمع‌آوری دیتای L2 به مدت {COLLECT_SECONDS} ثانیه..."))
    d.addCallback(lambda _: reactor.callLater(COLLECT_SECONDS, finish))
    d.addErrback(on_fatal)


# ---------------------------------------------------------------- اجرا
def main():
    global client, exit_code, ACCOUNT_ID

    missing = [n for n, v in {
        "TELEGRAM_TOKEN": TELEGRAM_TOKEN,
        "CHAT_ID": CHAT_ID,
        "CTRADER_CLIENT_ID": CLIENT_ID,
        "CTRADER_CLIENT_SECRET": CLIENT_SECRET,
        "CTRADER_ACCESS_TOKEN": ACCESS_TOKEN_HOLDER["value"],
        "CTRADER_ACCOUNT_ID": ACCOUNT_ID_RAW,
    }.items() if not v]
    if missing:
        log(f"❌ سکرت‌های گیت‌هاب ناقص است: {', '.join(missing)}")
        sys.exit(1)

    try:
        ACCOUNT_ID = int(ACCOUNT_ID_RAW)
    except ValueError:
        log("❌ مقدار CTRADER_ACCOUNT_ID باید عدد باشد.")
        sys.exit(1)

    log(f"🚀 شروع بات | host={CTRADER_HOST}:{CTRADER_PORT} account={ACCOUNT_ID}")
    client = Client(CTRADER_HOST, CTRADER_PORT, TcpProtocol)
    client.setConnectedCallback(on_connected)
    client.setDisconnectedCallback(on_disconnected)
    client.setMessageReceivedCallback(on_message_received)
    client.startService()
    reactor.callLater(FAILSAFE_SECONDS, failsafe)
    reactor.run()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
