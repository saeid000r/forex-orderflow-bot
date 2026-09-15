import os
import json
import requests
import sys
from twisted.internet import reactor
from ctrader_open_api import Client, TcpProtocol

# --- راهکار نهایی برای حل مشکل ایمپورت در لینوکس ---
import ctrader_open_api.messages.ProtoOAApplicationAuthReq_pb2 as PB_AppAuth
import ctrader_open_api.messages.ProtoOAAccountAuthReq_pb2 as PB_AccAuth
import ctrader_open_api.messages.ProtoOASymbolsListReq_pb2 as PB_SymList
import ctrader_open_api.messages.ProtoOAGetDepthQuotesReq_pb2 as PB_Depth

ProtoOAApplicationAuthReq = PB_AppAuth.ProtoOAApplicationAuthReq
ProtoOAAccountAuthReq = PB_AccAuth.ProtoOAAccountAuthReq
ProtoOASymbolsListReq = PB_SymList.ProtoOASymbolsListReq
ProtoOAGetDepthQuotesReq = PB_Depth.ProtoOAGetDepthQuotesReq

# تنظیمات اتصال (آدرس‌ها دستی وارد شده تا ارور AttributeError ندهد)
HOST = "demo.ctraderapi.com" 
PORT = 5035

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
CLIENT_ID = os.getenv("CTRADER_CLIENT_ID")
CLIENT_SECRET = os.getenv("CTRADER_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("CTRADER_ACCESS_TOKEN")
ACCOUNT_ID = int(os.getenv("CTRADER_ACCOUNT_ID", "0"))

JOURNAL_FILE = "journal.json"
TARGET_SYMBOLS = ["XAUUSD", "US30", "BRENT", "USNDAQ100", "EURUSD"]

client = Client(HOST, PORT, TcpProtocol)
symbol_map, symbol_names, depth_results = {}, {}, {}

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text, "parse_mode": "HTML"}
    try: requests.post(url, data=payload, timeout=10)
    except: pass

def load_journal():
    if os.path.exists(JOURNAL_FILE):
        try:
            with open(JOURNAL_FILE, "r") as f: return json.load(f)
        except: pass
    return {"total": 0, "tp": 0, "sl": 0, "active": []}

def process_and_finish():
    journal = load_journal()
    active_signals, current_prices = [], {}

    for sym_id, res in depth_results.items():
        sym_name = symbol_names.get(sym_id, "")
        if not res.bids or not res.asks: continue

        v_bid = sum(b.volume for b in res.bids)
        v_ask = sum(a.volume for a in res.asks)
        
        # محاسبه قیمت لحظه‌ای از بهترین قیمت خرید و فروش
        p_bid = res.bids[0].price / 100000.0 if res.bids[0].price > 100000 else res.bids[0].price
        p_ask = res.asks[0].price / 100000.0 if res.asks[0].price > 100000 else res.asks[0].price
        price = (p_bid + p_ask) / 2.0
        current_prices[sym_name] = price
        
        total_v = v_bid + v_ask
        imbalance = (v_bid - v_ask) / total_v if total_v > 0 else 0
        
        signal = "BUY" if imbalance >= 0.40 else "SELL" if imbalance <= -0.40 else None
        
        if signal:
            is_dup = any(s["symbol"] == sym_name for s in journal["active"])
            if not is_dup:
                tp = price + (price * 0.002) if signal == "BUY" else price - (price * 0.002)
                sl = price - (price * 0.001) if signal == "BUY" else price + (price * 0.001)
                
                journal["active"].append({"symbol": sym_name, "type": signal, "tp": round(tp,5), "sl": round(sl,5)})
                journal["total"] += 1
                
                msg = f"{'🔥 Golden' if abs(imbalance) > 0.6 else '🟢 Normal'} <b>{signal}</b>\n"
                msg += f"Symbol: <b>{sym_name}</b>\nL2 Imbalance: <code>{round(imbalance*100)}%</code>\nPrice: {round(price,5)}"
                send_telegram(msg)

    for s in journal["active"]:
        if s["symbol"] in current_prices:
            cp = current_prices[s["symbol"]]
            if (s["type"]=="BUY" and cp>=s["tp"]) or (s["type"]=="SELL" and cp<=s["tp"]):
                journal["tp"]+=1
                send_telegram(f"✅ <b>TP HIT</b>: {s['symbol']}")
            elif (s["type"]=="BUY" and cp<=s["sl"]) or (s["type"]=="SELL" and cp>=s["sl"]):
                journal["sl"]+=1
                send_telegram(f"❌ <b>SL HIT</b>: {s['symbol']}")
            else: active_signals.append(s)
    
    journal["active"] = active_signals
    with open(JOURNAL_FILE, "w") as f: json.dump(journal, f, indent=4)
    print("Execution Finished Successfully.")
    if reactor.running: reactor.stop()

def on_connected(client):
    req = ProtoOAApplicationAuthReq()
    req.clientId = CLIENT_ID
    req.clientSecret = CLIENT_SECRET
    client.send(req).addCallback(lambda r: authenticate_account())

def authenticate_account():
    req = ProtoOAAccountAuthReq()
    req.accessToken = ACCESS_TOKEN
    req.ctidTraderAccountId = ACCOUNT_ID
    client.send(req).addCallback(lambda r: get_symbols())

def get_symbols():
    req = ProtoOASymbolsListReq()
    req.ctidTraderAccountId = ACCOUNT_ID
    client.send(req).addCallback(on_symbols_list)

def on_symbols_list(res):
    for s in res.symbol:
        name = s.symbolName.replace("#", "")
        for t in TARGET_SYMBOLS:
            if t in name: 
                symbol_map[t] = s.symbolId
                symbol_names[s.symbolId] = s.symbolName
    fetch_depths(list(symbol_map.values()))

def fetch_depths(ids):
    if not ids: process_and_finish(); return
    sid = ids.pop(0)
    req = ProtoOAGetDepthQuotesReq()
    req.ctidTraderAccountId = ACCOUNT_ID
    req.symbolId = sid
    client.send(req).addCallback(lambda r: (depth_results.update({sid: r}), fetch_depths(ids))).addErrback(lambda e: fetch_depths(ids))

client.setConnectedCallback(on_connected)
client.startService()
# جلوگیری از توقف ناگهانی گیت‌هاب (تایم اوت ۳۰ ثانیه‌ای)
reactor.callLater(30, lambda: reactor.stop() if reactor.running else None)
reactor.run()
