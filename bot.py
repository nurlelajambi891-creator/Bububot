"""
BOT XAU 13 BAHAN KSA - VERSI FINAL CUMA ENTRY BUY/SELL
- Gak ada tombol
- Tampilan normal
- Khusus nerima sinyal entry BUY dan SELL
- 13 bahan tetap jalan di belakang buat ngitung BUY/SELL
Waktu KSA GMT+3 Madinah
"""
import os
import time
import requests
from datetime import datetime, timezone, timedelta
import telebot
from flask import Flask, jsonify
import threading

BOT_TOKEN = os.getenv("BOT_TOKEN")
TD_KEY = os.getenv("TD_API_KEY")

bot = telebot.TeleBot(BOT_TOKEN, threaded=False) if BOT_TOKEN else None

CACHE = {"data": None, "time": 0, "analisa": None}
CACHE_TTL = 60
KSA_TZ = timezone(timedelta(hours=3))

def td_get(symbol, endpoint="price", interval="1day", outputsize=30):
    try:
        if endpoint == "price":
            url = f"https://api.twelvedata.com/price?symbol={symbol}&apikey={TD_KEY}"
        elif endpoint == "quote":
            url = f"https://api.twelvedata.com/quote?symbol={symbol}&apikey={TD_KEY}"
        else:
            url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&apikey={TD_KEY}&outputsize={outputsize}"
        r = requests.get(url, timeout=15)
        j = r.json()
        if "code" in j and j.get("code") != 200 and "values" not in j:
            return {"error": j}
        return j
    except Exception as e:
        return {"error": str(e)}

def calc_mfi_volume(values, period=14):
    try:
        vals = list(reversed(values))
        if len(vals) < period + 2:
            return 50.0, 100.0, "VOLUME NO DATA"
        tps, flows, vols = [], [], []
        for v in vals:
            try:
                h = float(v.get("high",0)); l = float(v.get("low",0)); c = float(v.get("close",0))
                vol = float(v.get("volume",0) or 0)
                if vol == 0:
                    vol = (h-l)*1000 if h>l else 1000
                tp = (h+l+c)/3
                tps.append(tp); flows.append(tp*vol); vols.append(vol)
            except:
                continue
        pos_flow = neg_flow = 0
        for i in range(len(tps)-period, len(tps)):
            if i<=0: continue
            if tps[i] > tps[i-1]: pos_flow += flows[i]
            elif tps[i] < tps[i-1]: neg_flow += flows[i]
        mfi = 100 - (100/(1+pos_flow/neg_flow)) if neg_flow!=0 else 100.0
        avg_vol = sum(vols[-20:])/len(vols[-20:]) if len(vols)>=20 else sum(vols)/len(vols) if vols else 1
        curr_vol = vols[-1] if vols else 0
        ratio = curr_vol/avg_vol*100 if avg_vol>0 else 100
        if ratio>180: status=f"VOLUME TINGGI {ratio:.0f}% - Bandar Masuk"
        elif ratio>150: status=f"VOLUME TINGGI {ratio:.0f}%"
        elif ratio<70: status=f"VOLUME RENDAH {ratio:.0f}% - Sepi"
        else: status=f"VOLUME NORMAL {ratio:.0f}%"
        return mfi, ratio, status
    except:
        return 50.0, 100.0, "VOLUME NORMAL"

def get_all_data():
    now_ts = time.time()
    if CACHE["data"] and CACHE["analisa"] and (now_ts - CACHE["time"] < CACHE_TTL):
        return CACHE["data"], CACHE["analisa"]
    xau_price = td_get("XAU/USD", "price")
    xau_quote = td_get("XAU/USD", "quote")
    xau_daily = td_get("XAU/USD", "time_series", "1day", 30)
    xau_15m = td_get("XAU/USD", "time_series", "15min", 50)
    xau_5m = td_get("XAU/USD", "time_series", "5min", 50)
    dxy_quote = td_get("DXY", "quote")
    us10y_quote = td_get("US10Y", "quote")
    live = float(xau_price.get("price",0) or xau_quote.get("close",0) or 0)
    if live==0:
        if CACHE["data"]: return CACHE["data"], CACHE["analisa"]
        live=2650.0
    today_high = float(xau_quote.get("high", live))
    today_low = float(xau_quote.get("low", live))
    y_high = y_low = live
    weekly_high = weekly_low = live
    if "values" in xau_daily and len(xau_daily["values"])>=2:
        try:
            y_high = float(xau_daily["values"][1]["high"])
            y_low = float(xau_daily["values"][1]["low"])
            highs = [float(v["high"]) for v in xau_daily["values"][:5]]
            lows = [float(v["low"]) for v in xau_daily["values"][:5]]
            weekly_high = max(highs); weekly_low = min(lows)
        except: pass
    dxy = float(dxy_quote.get("close",0) or dxy_quote.get("price",0) or 0)
    if dxy==0:
        try:
            eu = td_get("EUR/USD", "price")
            dxy = 100/float(eu.get("price",0))*1.08 if float(eu.get("price",0)) else 103.5
        except: dxy=103.5
    us10y = float(us10y_quote.get("close",0) or us10y_quote.get("price",0) or 4.2)
    real_yield = us10y - 3.0
    weekly_50 = (weekly_high+weekly_low)/2 if weekly_high!=weekly_low else live
    is_discount = live < weekly_50
    premium_status = "DISCOUNT (Murah - Cari BUY)" if is_discount else "PREMIUM (Mahal - Cari SELL)"
    bsl = today_high; ssl = today_low
    swept_bsl = live > y_high; swept_ssl = live < y_low
    fvg_bull_15=[]; fvg_bear_15=[]
    try:
        if "values" in xau_15m:
            vals=xau_15m["values"][:15]
            for i in range(1,len(vals)-1):
                if float(vals[i-1]["low"]) > float(vals[i+1]["high"]): fvg_bull_15.append(1)
                if float(vals[i-1]["high"]) < float(vals[i+1]["low"]): fvg_bear_15.append(1)
    except: pass
    daily_range = today_high - today_low if today_high>today_low else 20
    now_ksa = datetime.now(KSA_TZ)
    hour=now_ksa.hour
    is_london=11<=hour<=13; is_ny=15<=hour<=18
    kz="LONDON KZ" if is_london else "NY KZ" if is_ny else "LUAR KILLZONE"
    ema_bias="NEUTRAL"
    try:
        closes=[float(v["close"]) for v in xau_daily["values"][:20]]
        ema20=sum(closes)/len(closes)
        ema_bias="DI ATAS EMA20 (Bull)" if live>ema20 else "DI BAWAH EMA20 (Bear)"
    except: pass
    mfi_15m, vol_ratio_15m, vol_status_15m = calc_mfi_volume(xau_15m.get("values",[]),14) if "values" in xau_15m else (50,100,"VOLUME NO DATA")
    mfi_5m, vol_ratio_5m, vol_status_5m = calc_mfi_volume(xau_5m.get("values",[]),14) if "values" in xau_5m else (50,100,"VOLUME NO DATA")
    mfi_daily, _, _ = calc_mfi_volume(xau_daily.get("values",[]),14) if "values" in xau_daily else (50,100,"")
    score_buy=0; score_sell=0; notes=[]
    if dxy<103.5: score_buy+=1; notes.append(f"[BUY] DXY Lemah {dxy:.2f}")
    else: score_sell+=1; notes.append(f"[SELL] DXY Kuat {dxy:.2f}")
    if us10y<4.0: score_buy+=1; notes.append(f"[BUY] US10Y Rendah {us10y:.2f}%")
    else: score_sell+=1; notes.append(f"[SELL] US10Y Tinggi {us10y:.2f}%")
    if real_yield<1.5: score_buy+=1; notes.append(f"[BUY] Real Yield {real_yield:.2f}%")
    else: score_sell+=1; notes.append(f"[SELL] Real Yield {real_yield:.2f}%")
    if is_discount: score_buy+=2; notes.append(f"[BUY] DISCOUNT {live:.1f} < 50% {weekly_50:.1f}")
    else: score_sell+=2; notes.append(f"[SELL] PREMIUM {live:.1f} > 50% {weekly_50:.1f}")
    if swept_ssl: score_buy+=2; notes.append(f"[BUY] Sweep SSL {y_low:.1f}")
    if swept_bsl: score_sell+=2; notes.append(f"[SELL] Sweep BSL {y_high:.1f}")
    if fvg_bull_15: score_buy+=1; notes.append(f"[BUY] {len(fvg_bull_15)} FVG Bull 15m")
    if fvg_bear_15: score_sell+=1; notes.append(f"[SELL] {len(fvg_bear_15)} FVG Bear 15m")
    notes.append(vol_status_15m)
    if mfi_15m<20: score_buy+=2; notes.append(f"[BUY] MFI 15m OS {mfi_15m:.1f}")
    elif mfi_15m>80: score_sell+=2; notes.append(f"[SELL] MFI 15m OB {mfi_15m:.1f}")
    notes.append(kz); notes.append(ema_bias)
    if score_buy>=score_sell+3: bias="BUY"; strength="A+"
    elif score_sell>=score_buy+3: bias="SELL"; strength="A+"
    elif score_buy>score_sell: bias="BUY"; strength="B"
    elif score_sell>score_buy: bias="SELL"; strength="B"
    else: bias="WAIT"; strength="C"
    if bias=="BUY":
        entry=today_low+2 if not swept_ssl else ssl+1
        sl=y_low-3; tp1=today_high; tp2=weekly_high; tp3=today_high+daily_range
    elif bias=="SELL":
        entry=today_high-2 if not swept_bsl else bsl-1
        sl=y_high+3; tp1=today_low; tp2=weekly_low; tp3=today_low-daily_range
    else:
        entry=live; sl=live-10; tp1=live+10; tp2=live+20; tp3=live+30
    rr1=abs(tp1-entry)/abs(entry-sl) if entry!=sl else 0
    rr2=abs(tp2-entry)/abs(entry-sl) if entry!=sl else 0
    now_str=now_ksa.strftime("%d %b %H:%M KSA")
    full_str=now_ksa.strftime("%Y-%m-%d %H:%M:%S KSA (Madinah)")
    data={"live":live,"today_high":today_high,"today_low":today_low,"y_high":y_high,"y_low":y_low,"weekly_high":weekly_high,"weekly_low":weekly_low,"weekly_50":weekly_50,"dxy":dxy,"us10y":us10y,"kz":kz,"time":now_str,"time_full":full_str,"mfi_15m":mfi_15m,"mfi_5m":mfi_5m,"vol_status_15m":vol_status_15m,"vol_status_5m":vol_status_5m,"premium_status":premium_status,"ema_bias":ema_bias}
    analisa={"bias":bias,"strength":strength,"score_buy":score_buy,"score_sell":score_sell,"entry":entry,"sl":sl,"tp1":tp1,"tp2":tp2,"tp3":tp3,"rr1":rr1,"rr2":rr2,"notes":notes}
    CACHE["data"]=data; CACHE["analisa"]=analisa; CACHE["time"]=now_ts
    return data, analisa

def build_message(d,a):
    if a["bias"]=="WAIT":
        setup=f"""WAIT - NO TRADE ({a['strength']})
Score BUY:{a['score_buy']} vs SELL:{a['score_sell']}
Tunggu Sweep SSL/BSL + MFI OS/OB"""
    else:
        setup=f"""{a['bias']} LIMIT - {a['strength']}
Score BUY:{a['score_buy']} vs SELL:{a['score_sell']}
Entry : {a['entry']:.1f}$
SL    : {a['sl']:.1f}$ ({abs(a['entry']-a['sl']):.1f}$)
TP1   : {a['tp1']:.1f}$ (RR 1:{a['rr1']:.1f})
TP2   : {a['tp2']:.1f}$ (RR 1:{a['rr2']:.1f})
TP3   : {a['tp3']:.1f}$"""
    notes_str="\n".join([f"- {n}" for n in a["notes"]])
    return f"""XAUUSD 13 BAHAN - SINYAL ENTRY BUY/SELL | {d['time']} | {d['kz']}
Live : {d['live']:.2f}$ | DXY:{d['dxy']:.2f} | US10Y:{d['us10y']:.2f}%
Range Hari Ini: {d['today_high']:.1f} / {d['today_low']:.1f}
Range Kemarin: {d['y_high']:.1f} / {d['y_low']:.1f}
50%: {d['weekly_50']:.1f} | {d['premium_status']} | {d['ema_bias']}
MFI 15m:{d['mfi_15m']:.1f} 5m:{d['mfi_5m']:.1f}
{d['vol_status_15m']} | {d['vol_status_5m']}
------------------------------
{setup}
------------------------------
13 BAHAN CHECKLIST:
{notes_str}
------------------------------
WAKTU: {d['time_full']}
BOT KHUSUS NERIMA SINYAL ENTRY BUY/SELL - 13 BAHAN LIVE"""

# HANDLER TANPA TOMBOL
@bot.message_handler(commands=['start','sinyal','xau'])
def start_cmd(m):
    d,a = get_all_data()
    if d:
        bot.send_message(m.chat.id, build_message(d,a))

@bot.message_handler(func=lambda m: True)
def handle_all(m):
    d,a = get_all_data()
    if d:
        bot.send_message(m.chat.id, build_message(d,a))

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot XAU 13 Bahan - Cuma Entry BUY/SELL - Tanpa Tombol - Ready - Auto-Ping 24 Jam ON"

@app.route('/check')
def check():
    try:
        d,a = get_all_data()
        return jsonify({"live":d["live"],"bias":a["bias"],"strength":a["strength"],"entry":a["entry"],"sl":a["sl"],"tp1":a["tp1"],"tp2":a["tp2"],"score":f"{a['score_buy']}:{a['score_sell']}"})
    except Exception as e:
        return jsonify({"error":str(e)}),500

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))

def auto_ping():
    """Thread auto-ping biar Render gak sleep - Online 24 jam"""
    while True:
        time.sleep(600)  # 10 menit
        try:
            # URL Render lu - SET ENV RENDER_EXTERNAL_URL di Render
            # Contoh: https://bot-xau-ksa.onrender.com
            self_url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("SELF_URL") or ""
            if not self_url:
                # fallback ping localhost biar Flask tetap aktif
                port = os.getenv("PORT", "10000")
                self_url = f"http://127.0.0.1:{port}/"
            # ping
            r = requests.get(self_url, timeout=10)
            print(f"[AUTO-PING] {self_url} -> {r.status_code} - Bot tetap online 24 jam")
        except Exception as e:
            print(f"[AUTO-PING] Gagal ping: {e}")
            # tetap coba ping localhost biar thread gak mati
            try:
                port = os.getenv("PORT", "10000")
                requests.get(f"http://127.0.0.1:{port}/", timeout=5)
            except:
                pass


if __name__=="__main__":
    try:
        bot.remove_webhook()
        time.sleep(1)
    except: pass
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=auto_ping, daemon=True).start()
    print("Bot Normal Tanpa Tombol - Cuma BUY/SELL Entry + Auto-Ping 24 Jam Aktif")
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
        except Exception as e:
            print(f"Polling error {e}")
            time.sleep(5)
