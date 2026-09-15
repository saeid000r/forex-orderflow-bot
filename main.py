import os
import json
import requests
import sys
import importlib
from twisted.internet import reactor
from ctrader_open_api import Client, EndPoints, TcpProtocol

# سیستم چندمسیره هوشمند برای لود کردن ماژول‌های cTrader
def get_ctrader_message(msg_name):
    possible_paths = [
        f"ctrader_open_api.messages.{msg_name}_pb2",
        f"ctrader_open_api.messages.{msg_name}",
        "ctrader_open_api.messages",
        f"ctrader_open_api.{msg_name}_pb2",
        f"ctrader_open_api.{msg_name}"
    ]
    for path in possible_paths:
        try:
            mod = importlib.import_module(path)
            if hasattr(mod, msg_name):
                return getattr(mod, msg_name)
        except Exception:
            continue
    return None

# دریافت کلاس‌های پیام cTrader
ProtoOAApplicationAuthReq = get_ctrader_message("ProtoOAApplicationAuthReq")
ProtoOAAccountAuthReq = get_ctrader_message("ProtoOAAccountAuthReq")
ProtoOASymbolsListReq = get_ctrader_message("ProtoOASymbolsListReq")
ProtoOAGetDepthQuotesReq = get_ctrader_message("ProtoOAGetDepthQuotesReq")

# بررسی صحت بارگذاری
if not ProtoOAApplicationAuthReq:
    try:
        import ctrader_open_api.messages as msgs
        ProtoOAApplicationAuthReq = getattr(msgs, "ProtoOAApplicationAuthReq", None)
        ProtoOAAccountAuthReq = getattr(msgs, "ProtoOAAccountAuthReq", None)
        ProtoOASymbolsListReq = getattr(msgs, "ProtoOASymbolsListReq", None)
        ProtoOAGetDepthQuotesReq = getattr(msgs, "ProtoOAGetDepthQuotesReq", None)
    except Exception as e:
        print(f"Failed to load cTrader modules: {e}")
        sys.exit(1)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
CLIENT_ID = os.getenv("CTRADER_CLIENT_ID")
CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
ACCOUNT_ID = int(os.getenv("CTRADER_ACCOUNT_ID", "0"))

JOURNAL_FILE = "journal.json"
TARGET_SYMBOLS = ["XAUUSD", "US30", "BRENT", "USNDAQ100", "EURUSD"]

HOST = EndPoints.PROTOBUF_SANDBOX_HOST
PORT = EndPoints.PROTOBUF_PORT

client = Client(HOST, PORT, TcpProtocol)
symbol_map = {}
symbol_names = {}
depth_results = {}

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, data=payload, timeout=10)
    except Exception as e:
        print(f"Telegram error: {e}")

def load_journal():
    if os.path.exists(JOURNAL_FILE):
        try:
            with open(JOURNAL_FILE, "r") as f:
                return json.load(f)
        except:
            pass
    return {"total": 0, "tp": 0, "sl": 0, "active": []}

def save_journal(data):
    with open(JOURNAL_FILE, "w") as f:
        json.dump(data, f, indent=4)

def process_and_finish():
    journal = load_journal()
    new_signals = []
    active_signals = []
    current_prices = {}

    for sym_id, depth in depth_results.items():
        sym_name = symbol_names.get(sym_id, "")
        if not sym_name: continue

        bids = depth.bids
        asks = depth.asks

        if not bids or not asks:
            continue

        total_bid_vol = sum(b.volume for b in bids)
        total_ask_vol = sum(a.volume for a in asks)
        total_vol = total_bid_vol + total_ask_vol

        if total_vol == 0: continue

        top_bid = bids[0].price / 100000.0 if bids[0].price > 100000 else bids[0].price
        top_ask = asks[0].price / 100000.0 if asks[0].price > 100000 else asks[0].price
        mid_price = (top_bid + top_ask) / 2.0
        current_prices[sym_name] = mid_price

        imbalance = (total_bid_vol - total_ask_vol) / total_vol

        signal_type = None
        strength = ""

        if imbalance >= 0.60:
            signal_type = "BUY"
            strength = "🔥 <b>Golden (cTrader L2)</b> 🔥"
        elif imbalance >= 0.40:
            signal_type = "BUY"
            strength = "🟢 <b>Normal (cTrader L2)</b>"
        elif imbalance <= -0.60:
            signal_type = "SELL"
            strength = "🔥 <b>Golden (cTrader L2)</b> 🔥"
        elif imbalance <= -0.40:
            signal_type = "SELL"
            strength = "🔴 <b>Normal (cTrader L2)</b>"

        if signal_type:
            spread = abs(top_ask - top_bid)
            delta = spread * 4 if spread > 0 else mid_price * 0.001
            entry = mid_price

            if signal_type == "BUY":
                tp = entry + (delta * 2.5)
                sl = entry - (delta * 1.5)
            else:
                tp = entry - (delta * 2.5)
                sl = entry + (delta * 1.5)

            new_signals.append({
                "symbol": sym_name,
                "type": signal_type,
                "strength": strength,
                "entry": round(entry, 4),
                "tp": round(tp, 4),
                "sl": round(sl, 4),
                "imbalance": round(imbalance * 100, 1)
            })

    for sig in journal.get("active", []):
        sym = sig["symbol"]
        if sym not in current_prices:
            active_signals.append(sig)
            continue

        cp = current_prices[sym]
        if sig["type"] == "BUY":
            if cp >= sig["tp"]:
                journal["tp"] += 1
                send_telegram(f"✅ <b>TP HIT!</b>\nSymbol: <b>{sym}</b>\nPrice: {cp}")
            elif cp <= sig["sl"]:
                journal["sl"] += 1
                send_telegram(f"❌ <b>SL HIT!</b>\nSymbol: <b>{sym}</b>\nPrice: {cp}")
            else:
                active_signals.append(sig)
        else:
            if cp <= sig["tp"]:
                journal["tp"] += 1
                send_telegram(f"✅ <b>TP HIT!</b>\nSymbol: <b>{sym}</b>\nPrice: {cp}")
            elif cp >= sig["sl"]:
                journal["sl"] += 1
                send_telegram(f"❌ <b>SL HIT!</b>\nSymbol: <b>{sym}</b>\nPrice: {cp}")
            else:
                active_signals.append(sig)

    for sig in new_signals:
        is_dup = any(s["symbol"] == sig["symbol"] for s in active_signals)
        if is_dup: continue

        active_signals.append(sig)
        journal["total"] += 1

        closed = journal["tp"] + journal["sl"]
        wr = (journal["tp"] / closed * 100) if closed > 0 else 0.0

        msg = f"{sig['strength']} SIGNAL\n\n"
        msg += f"Symbol: <b>{sig['symbol']}</b>\n"
        msg += f"Action: <b>{sig['type']}</b>\n"
        msg += f"L2 Imbalance: <b>{sig['imbalance']}%</b>\n"
        msg += f"Entry: <code>{sig['entry']}</code>\n"
        msg += f"TP: <code>{sig['tp']}</code>\n"
        msg += f"SL: <code>{sig['sl']}</code>\n\n"
        msg += f"📊 Win Rate: <b>{wr:.1f}%</b> (Trades: {closed})"

        send_telegram(msg)

    journal["active"] = active_signals
    save_journal(journal)
    print("cTrader L2 Scan Completed.")
    if reactor.running:
        reactor.stop()

def on_connected(client):
    req = ProtoOAApplicationAuthReq()
    req.clientId = CLIENT_ID
    req.clientSecret = CLIENT_SECRET
    d = client.send(req)
    d.addCallback(on_app_auth)
    d.addErrback(on_error)

def on_app_auth(response):
    req = ProtoOAAccountAuthReq()
    req.accessToken = ACCESS_TOKEN
    req.ctidTraderAccountId = ACCOUNT_ID
    d = client.send(req)
    d.addCallback(on_account_auth)
    d.addErrback(on_error)

def on_account_auth(response):
    req = ProtoOASymbolsListReq()
    req.ctidTraderAccountId = ACCOUNT_ID
    d = client.send(req)
    d.addCallback(on_symbols_list)
    d.addErrback(on_error)

def on_symbols_list(response):
    for symbol in response.symbol:
        clean_name = symbol.symbolName.replace("#", "")
        for target in TARGET_SYMBOLS:
            if target in clean_name:
                symbol_map[target] = symbol.symbolId
                symbol_names[symbol.symbolId] = symbol.symbolName

    if not symbol_map:
        process_and_finish()
        return

    fetch_depth_quotes(list(symbol_map.values()))

def fetch_depth_quotes(symbol_ids):
    if not symbol_ids:
        process_and_finish()
        return

    sym_id = symbol_ids.pop(0)
    req = ProtoOAGetDepthQuotesReq()
    req.ctidTraderAccountId = ACCOUNT_ID
    req.symbolId = sym_id

    d = client.send(req)
    def on_depth(res):
        depth_results[sym_id] = res
        fetch_depth_quotes(symbol_ids)

    d.addCallback(on_depth)
    d.addErrback(lambda err: fetch_depth_quotes(symbol_ids))

def on_error(failure):
    print(f"cTrader Error: {failure}")
    if reactor.running:
        reactor.stop()

if __name__ == "__main__":
    client.setConnectedCallback(on_connected)
    client.startService()
    reactor.run()
