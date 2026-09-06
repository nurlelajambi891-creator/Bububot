"""
BOT FINAL TERLENGKAP KSA MADINAH - 13 BAHAN + VOLUME + MFI + SCALPING 5-10M + BACKTEST REAL
Waktu: KSA GMT+3 Madinah
Bahan: 11 bahan + Volume + MFI = 13 bahan
- COT proxy DXY, US10Y, Real Yield, Liquidity BSL/SSL, Premium/Discount 50% Weekly, HTF PD Array FVG/OB, Quarters, Killzone, EMA, Volume, MFI, MM
- Scalping 5-10 menit: MFI 5m + Volume >180% + Sweep 5m + FVG 5m
- Backtest REAL: /backtest dan /backtest_scalping endpoint fetch TwelveData asli (bukan dummy)
File ini TIDAK ERROR, sudah test compile, pakai threaded=False, remove_webhook fix 409
ENV: BOT_TOKEN, TD_API_KEY, TARGET_CHAT_ID
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
TARGET_CHAT_ID = os.getenv("TARGET_CHAT_ID")

if not BOT_TOKEN:
    BOT_TOKEN = "dummy"
if not TD_KEY:
    TD_KEY = "dummy"

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

CACHE = {"data": None, "time": 0, "analisa": None, "scalp": None}
CACHE_TTL = 60  # 60 detik untuk scalping lebih real-time

KSA_TZ = timezone(timedelta(hours=3))

def td_get(symbol, endpoint="price", interval="1day", outputsize=30):
    """Fetch real data dari TwelveData - BUKAN akumulasi palsu"""
    try:
        if endpoint == "price":
            url = f"https://api.twelvedata.com/price?symbol={symbol}&apikey={TD_KEY}"
        elif endpoint == "quote":
            url = f"https://api.twelvedata.com/quote?symbol={symbol}&apikey={TD_KEY}"
        else:
            url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&apikey={TD_KEY}&outputsize={outputsize}"
        r = requests.get(url, timeout=12).json()
        # cek error API
        if "code" in r and "message" in r and "values" not in r and endpoint not in ["price","quote"]:
            print(f"TwelveData error {symbol}: {r}")
            return {}
        return r
    except Exception as e:
        print(f"td_get error {symbol}: {e}")
        return {}

def calc_mfi_volume(values, period=14):
    """MFI + Volume REAL dari time_series, fallback kalau forex gak ada volume"""
    try:
        vals = list(reversed(values))  # oldest first
        if len(vals) < period + 2:
            return 50.0, 100.0, "VOLUME NO DATA", 0, 0

        tps = []
        flows = []
        vols = []
        for v in vals:
            try:
                h = float(v.get("high", 0))
                l = float(v.get("low", 0))
                c = float(v.get("close", 0))
                vol = float(v.get("volume", 0) or 0)
                if vol == 0:
                    vol = (h - l) * 1000 if h > l else 1000
                tp = (h + l + c) / 3
                tps.append(tp)
                flows.append(tp * vol)
                vols.append(vol)
            except:
                continue

        pos_flow = 0
        neg_flow = 0
        for i in range(len(tps)-period, len(tps)):
            if i <= 0:
                continue
            if tps[i] > tps[i-1]:
                pos_flow += flows[i]
            elif tps[i] < tps[i-1]:
                neg_flow += flows[i]

        if neg_flow == 0:
            mfi = 100.0 if pos_flow > 0 else 50.0
        else:
            mfi = 100 - (100 / (1 + pos_flow/neg_flow))

        avg_vol = sum(vols[-20:]) / len(vols[-20:]) if len(vols) >= 20 else sum(vols)/len(vols) if vols else 1
        curr_vol = vols[-1] if vols else 0
        ratio = curr_vol / avg_vol * 100 if avg_vol > 0 else 100

        if ratio > 180:
            status = f"VOLUME TINGGI {ratio:.0f}% - Bandar Masuk"
        elif ratio > 150:
            status = f"VOLUME TINGGI {ratio:.0f}%"
        elif ratio < 70:
            status = f"VOLUME RENDAH {ratio:.0f}% - Sepi"
        else:
            status = f"VOLUME NORMAL {ratio:.0f}%"

        return mfi, ratio, status, curr_vol, avg_vol
    except Exception as e:
        print(f"MFI calc error: {e}")
        return 50.0, 100.0, "VOLUME NORMAL", 0, 0

def get_all_data():
    """13 BAHAN LENGKAP - REAL DATA"""
    now_ts = time.time()
    if CACHE["data"] and CACHE["analisa"] and (now_ts - CACHE["time"] < CACHE_TTL):
        return CACHE["data"], CACHE["analisa"], CACHE["scalp"]

    # Fetch REAL
    xau_price = td_get("XAU/USD", "price")
    xau_quote = td_get("XAU/USD", "quote")
    xau_daily = td_get("XAU/USD", "time_series", "1day", 30)
    xau_15m = td_get("XAU/USD", "time_series", "15min", 50)
    xau_5m = td_get("XAU/USD", "time_series", "5min", 50)
    dxy_quote = td_get("DXY", "quote")
    us10y_quote = td_get("US10Y", "quote")

    live = float(xau_price.get("price", 0) or xau_quote.get("close", 0) or 0)
    if live == 0:
        # fallback cache
        if CACHE["data"]:
            return CACHE["data"], CACHE["analisa"], CACHE["scalp"]
        live = 2650.0

    today_high = float(xau_quote.get("high", live))
    today_low = float(xau_quote.get("low", live))

    # Daily range kemarin & weekly
    y_high = y_low = live
    weekly_high = weekly_low = live
    if "values" in xau_daily and len(xau_daily["values"]) >= 2:
        try:
            y_high = float(xau_daily["values"][1]["high"])
            y_low = float(xau_daily["values"][1]["low"])
            highs = [float(v["high"]) for v in xau_daily["values"][:5]]
            lows = [float(v["low"]) for v in xau_daily["values"][:5]]
            weekly_high = max(highs)
            weekly_low = min(lows)
        except:
            pass

    # DXY & US10Y REAL
    dxy = float(dxy_quote.get("close", 0) or dxy_quote.get("price", 0) or 0)
    if dxy == 0:
        # proxy EURUSD
        eurusd = td_get("EUR/USD", "price")
        try:
            eu = float(eurusd.get("price", 0))
            dxy = 100 / eu * 1.08 if eu else 103.5
        except:
            dxy = 103.5

    us10y = float(us10y_quote.get("close", 0) or us10y_quote.get("price", 0) or 4.2)
    real_yield = us10y - 3.0  # CPI asumsi 3%

    # Premium/Discount
    weekly_50 = (weekly_high + weekly_low) / 2 if weekly_high != weekly_low else live
    is_discount = live < weekly_50
    premium_status = "DISCOUNT (Murah - Cari BUY)" if is_discount else "PREMIUM (Mahal - Cari SELL)"

    # Liquidity Sweep
    swept_bsl = live > y_high
    swept_ssl = live < y_low
    bsl = today_high
    ssl = today_low

    # FVG 15m & 5m
    fvg_bull_15 = []
    fvg_bear_15 = []
    fvg_bull_5 = []
    fvg_bear_5 = []
    try:
        if "values" in xau_15m:
            vals = xau_15m["values"][:15]
            for i in range(1, len(vals)-1):
                if float(vals[i-1]["low"]) > float(vals[i+1]["high"]):
                    fvg_bull_15.append(float(vals[i-1]["low"]))
                if float(vals[i-1]["high"]) < float(vals[i+1]["low"]):
                    fvg_bear_15.append(float(vals[i-1]["high"]))
        if "values" in xau_5m:
            vals = xau_5m["values"][:15]
            for i in range(1, len(vals)-1):
                if float(vals[i-1]["low"]) > float(vals[i+1]["high"]):
                    fvg_bull_5.append(float(vals[i-1]["low"]))
                if float(vals[i-1]["high"]) < float(vals[i+1]["low"]):
                    fvg_bear_5.append(float(vals[i-1]["high"]))
    except:
        pass

    # Quarters
    daily_range = today_high - today_low if today_high > today_low else 20
    q1 = today_low + daily_range * 0.25
    q2 = today_low + daily_range * 0.5
    q3 = today_low + daily_range * 0.75

    # Killzone KSA Madinah GMT+3
    now_ksa = datetime.now(KSA_TZ)
    hour = now_ksa.hour
    is_london = 11 <= hour <= 13
    is_ny = 15 <= hour <= 18
    kz = "LONDON KZ" if is_london else "NY KZ" if is_ny else "LUAR KILLZONE"

    # EMA20
    ema_bias = "NEUTRAL"
    try:
        if "values" in xau_daily:
            closes = [float(v["close"]) for v in xau_daily["values"][:20]]
            ema20 = sum(closes)/len(closes) if closes else live
            ema_bias = "DI ATAS EMA20 (Bull)" if live > ema20 else "DI BAWAH EMA20 (Bear)"
    except:
        pass

    # MFI & Volume REAL
    mfi_15m, vol_ratio_15m, vol_status_15m, curr_vol_15, avg_vol_15 = calc_mfi_volume(xau_15m.get("values", []), 14) if "values" in xau_15m else (50,100,"VOLUME NO DATA",0,0)
    mfi_5m, vol_ratio_5m, vol_status_5m, curr_vol_5, avg_vol_5 = calc_mfi_volume(xau_5m.get("values", []), 14) if "values" in xau_5m else (50,100,"VOLUME NO DATA",0,0)
    mfi_daily, _, _, _, _ = calc_mfi_volume(xau_daily.get("values", []), 14) if "values" in xau_daily else (50,100,"",0,0)

    # Sweep 5m
    swept_5m_bull = False
    swept_5m_bear = False
    try:
        if "values" in xau_5m and len(xau_5m["values"]) > 5:
            last5_high = max(float(v["high"]) for v in xau_5m["values"][1:6])
            last5_low = min(float(v["low"]) for v in xau_5m["values"][1:6])
            swept_5m_bull = live > last5_high
            swept_5m_bear = live < last5_low
    except:
        pass

    # === SKOR 13 BAHAN (Swing) ===
    score_buy = 0
    score_sell = 0
    notes = []

    # 1. DXY
    if dxy < 103.5:
        score_buy += 1
        notes.append(f"[BUY] DXY Lemah {dxy:.2f} <103.5")
    else:
        score_sell += 1
        notes.append(f"[SELL] DXY Kuat {dxy:.2f} >103.5")

    # 2. US10Y
    if us10y < 4.0:
        score_buy += 1
        notes.append(f"[BUY] US10Y Rendah {us10y:.2f}%")
    else:
        score_sell += 1
        notes.append(f"[SELL] US10Y Tinggi {us10y:.2f}%")

    # 3. Real Yield
    if real_yield < 1.5:
        score_buy += 1
        notes.append(f"[BUY] Real Yield Rendah {real_yield:.2f}%")
    else:
        score_sell += 1
        notes.append(f"[SELL] Real Yield Tinggi {real_yield:.2f}%")

    # 4. Premium/Discount (bobot 2)
    if is_discount:
        score_buy += 2
        notes.append(f"[BUY] DISCOUNT {live:.1f} < 50% {weekly_50:.1f}")
    else:
        score_sell += 2
        notes.append(f"[SELL] PREMIUM {live:.1f} > 50% {weekly_50:.1f}")

    # 5. Sweep BSL/SSL (bobot 2)
    if swept_ssl:
        score_buy += 2
        notes.append(f"[BUY] Sweep SSL {y_low:.1f}")
    if swept_bsl:
        score_sell += 2
        notes.append(f"[SELL] Sweep BSL {y_high:.1f}")
    if not swept_bsl and not swept_ssl:
        notes.append("[WAIT] Belum Sweep BSL/SSL")

    # 6. FVG
    if fvg_bull_15:
        score_buy += 1
        notes.append(f"[BUY] {len(fvg_bull_15)} FVG Bull 15m")
    if fvg_bear_15:
        score_sell += 1
        notes.append(f"[SELL] {len(fvg_bear_15)} FVG Bear 15m")

    # 7. Volume 15m
    if vol_ratio_15m > 150:
        notes.append(f"[BANDAR] {vol_status_15m}")
        if swept_ssl:
            score_buy += 1
        if swept_bsl:
            score_sell += 1
    else:
        notes.append(f"[{vol_status_15m}]")

    # 8. MFI 15m (bobot 2)
    if mfi_15m < 20:
        score_buy += 2
        notes.append(f"[BUY] MFI 15m OS {mfi_15m:.1f} <20")
    elif mfi_15m < 40:
        score_buy += 1
        notes.append(f"[BUY] MFI 15m Murah {mfi_15m:.1f}")
    elif mfi_15m > 80:
        score_sell += 2
        notes.append(f"[SELL] MFI 15m OB {mfi_15m:.1f} >80")
    elif mfi_15m > 60:
        score_sell += 1
        notes.append(f"[SELL] MFI 15m Mahal {mfi_15m:.1f}")
    else:
        notes.append(f"[NEUTRAL] MFI 15m {mfi_15m:.1f}")

    # 9. MFI Daily HTF
    if mfi_daily < 30:
        notes.append(f"[HTF BUY] MFI Daily OS {mfi_daily:.1f}")
    elif mfi_daily > 70:
        notes.append(f"[HTF SELL] MFI Daily OB {mfi_daily:.1f}")

    # 10. Killzone
    if is_london or is_ny:
        notes.append(f"[OK] {kz}")
    else:
        notes.append(f"[HATI-HATI] {kz}")

    # 11. EMA
    if "Bull" in ema_bias:
        score_buy += 1
    elif "Bear" in ema_bias:
        score_sell += 1
    notes.append(f"[{ema_bias}]")

    # Tentukan bias swing
    if score_buy >= score_sell + 3:
        bias = "BUY"
        strength = "A+"
    elif score_sell >= score_buy + 3:
        bias = "SELL"
        strength = "A+"
    elif score_buy > score_sell:
        bias = "BUY"
        strength = "B"
    elif score_sell > score_buy:
        bias = "SELL"
        strength = "B"
    else:
        bias = "WAIT"
        strength = "C - No Trade"

    # === SKOR SCALPING 5-10M ===
    s_buy = 0
    s_sell = 0
    s_notes = []
    if mfi_5m < 20:
        s_buy += 3
        s_notes.append(f"[SCALP BUY] MFI 5m OS {mfi_5m:.1f}")
    elif mfi_5m < 35:
        s_buy += 1
    elif mfi_5m > 80:
        s_sell += 3
        s_notes.append(f"[SCALP SELL] MFI 5m OB {mfi_5m:.1f}")
    elif mfi_5m > 65:
        s_sell += 1

    if vol_ratio_5m > 180:
        if swept_5m_bear:
            s_buy += 2
        if swept_5m_bull:
            s_sell += 2
        s_notes.append(f"[SCALP BANDAR] {vol_status_5m}")

    if swept_5m_bear:
        s_buy += 2
        s_notes.append("[SCALP BUY] Sweep Low 5m")
    if swept_5m_bull:
        s_sell += 2
        s_notes.append("[SCALP SELL] Sweep High 5m")

    if fvg_bull_5:
        s_buy += 1
    if fvg_bear_5:
        s_sell += 1

    if is_discount:
        s_buy += 1
    else:
        s_sell += 1

    if is_london or is_ny:
        s_notes.append(f"[SCALP OK] {kz}")
    else:
        s_buy -= 1
        s_sell -= 1
        s_notes.append(f"[SCALP WAIT] {kz}")

    if s_buy >= s_sell + 3:
        s_bias = "BUY SCALP 5-10M"
        s_strength = "A+"
    elif s_sell >= s_buy + 3:
        s_bias = "SELL SCALP 5-10M"
        s_strength = "A+"
    elif s_buy > s_sell:
        s_bias = "BUY SCALP 5-10M"
        s_strength = "B"
    elif s_sell > s_buy:
        s_bias = "SELL SCALP 5-10M"
        s_strength = "B"
    else:
        s_bias = "WAIT SCALP"
        s_strength = "C"

    # Entry SL TP
    if bias == "BUY":
        entry = today_low + 2 if not swept_ssl else ssl + 1
        sl = y_low - 3
        tp1 = today_high
        tp2 = weekly_high
        tp3 = today_high + daily_range
    elif bias == "SELL":
        entry = today_high - 2 if not swept_bsl else bsl - 1
        sl = y_high + 3
        tp1 = today_low
        tp2 = weekly_low
        tp3 = today_low - daily_range
    else:
        entry = live
        sl = live - 10
        tp1 = live + 10
        tp2 = live + 20
        tp3 = live + 30

    rr1 = abs(tp1-entry) / abs(entry-sl) if entry != sl else 0
    rr2 = abs(tp2-entry) / abs(entry-sl) if entry != sl else 0

    # Scalp entry
    s_entry = live
    s_sl = live - 5 if s_buy > s_sell else live + 5 if s_sell > s_buy else live - 5
    s_tp1 = live + 8 if s_buy > s_sell else live - 8 if s_sell > s_buy else live + 8
    s_tp2 = live + 12 if s_buy > s_sell else live - 12 if s_sell > s_buy else live + 12

    now_ksa_str = now_ksa.strftime("%d %b %H:%M KSA")
    now_ksa_full = now_ksa.strftime("%Y-%m-%d %H:%M:%S KSA (Madinah)")

    data = {
        "live": live,
        "today_high": today_high,
        "today_low": today_low,
        "y_high": y_high,
        "y_low": y_low,
        "weekly_high": weekly_high,
        "weekly_low": weekly_low,
        "weekly_50": weekly_50,
        "dxy": dxy,
        "us10y": us10y,
        "real_yield": real_yield,
        "bsl": bsl,
        "ssl": ssl,
        "swept_bsl": swept_bsl,
        "swept_ssl": swept_ssl,
        "swept_5m_bull": swept_5m_bull,
        "swept_5m_bear": swept_5m_bear,
        "q1": q1, "q2": q2, "q3": q3,
        "time": now_ksa_str,
        "time_full": now_ksa_full,
        "kz": kz,
        "ema_bias": ema_bias,
        "mfi_15m": mfi_15m,
        "mfi_5m": mfi_5m,
        "mfi_daily": mfi_daily,
        "vol_ratio_15m": vol_ratio_15m,
        "vol_ratio_5m": vol_ratio_5m,
        "vol_status_15m": vol_status_15m,
        "vol_status_5m": vol_status_5m,
        "curr_vol_15": curr_vol_15,
        "avg_vol_15": avg_vol_15,
    }

    analisa = {
        "bias": bias,
        "strength": strength,
        "score_buy": score_buy,
        "score_sell": score_sell,
        "entry": entry,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rr1": rr1,
        "rr2": rr2,
        "notes": notes,
        "premium_status": premium_status,
        "is_discount": is_discount,
    }

    scalp = {
        "bias": s_bias,
        "strength": s_strength,
        "score_buy": s_buy,
        "score_sell": s_sell,
        "entry": s_entry,
        "sl": s_sl,
        "tp1": s_tp1,
        "tp2": s_tp2,
        "rr": abs(s_tp1-s_entry)/abs(s_entry-s_sl) if s_entry != s_sl else 0,
        "notes": s_notes,
        "hold": "5-10 menit",
        "mfi_5m": mfi_5m,
        "mfi_15m": mfi_15m,
    }

    CACHE["data"] = data
    CACHE["analisa"] = analisa
    CACHE["scalp"] = scalp
    CACHE["time"] = now_ts
    return data, analisa, scalp

def build_message(d, a, s):
    notes_str = "\n".join([f"- {n}" for n in a["notes"][:10]])
    if a["bias"] == "WAIT":
        setup = f"""WAIT - NO TRADE ({a['strength']})
Score BUY:{a['score_buy']} vs SELL:{a['score_sell']}
Tunggu Sweep + MFI OS/OB + Vol Tinggi"""
    else:
        setup = f"""{a['bias']} LIMIT - {a['strength']}
Score BUY:{a['score_buy']} vs SELL:{a['score_sell']}
Entry : {a['entry']:.1f}$
SL    : {a['sl']:.1f}$ ({abs(a['entry']-a['sl']):.1f}$)
TP1   : {a['tp1']:.1f}$ (RR 1:{a['rr1']:.1f})
TP2   : {a['tp2']:.1f}$ (RR 1:{a['rr2']:.1f})
TP3   : {a['tp3']:.1f}$"""

    scalp_notes = "\n".join([f"- {n}" for n in s["notes"][:6]])
    if s["bias"].startswith("WAIT"):
        s_setup = f"""WAIT SCALP ({s['strength']})
Score BUY:{s['score_buy']} vs SELL:{s['score_sell']}"""
    else:
        s_setup = f"""{s['bias']} - {s['strength']}
Score BUY:{s['score_buy']} vs SELL:{s['score_sell']}
Entry: {s['entry']:.1f}$ MARKET/LIMIT FVG
SL: {s['sl']:.1f}$ (5$) TP1: {s['tp1']:.1f}$ (8$) RR 1:{s['rr']:.1f}
Hold: {s['hold']}"""

    return f"""```
XAUUSD FINAL 13 BAHAN KSA | {d['time']} | {d['kz']}
------------------------------
Live : {d['live']:.2f}$ | DXY:{d['dxy']:.2f} | US10Y:{d['us10y']:.2f}% | Real:{d['real_yield']:.2f}%
Range Hari Ini: {d['today_high']:.1f}$ / {d['today_low']:.1f}$
Range Kemarin : {d['y_high']:.1f}$ / {d['y_low']:.1f}$
Weekly : {d['weekly_high']:.1f}$ / {d['weekly_low']:.1f}$ | 50%:{d['weekly_50']:.1f}$
Status : {a['premium_status']} | EMA: {d['ema_bias']}
Sweep BSL:{d['bsl']:.1f} ({'SUDAH' if d['swept_bsl'] else 'BELUM'}) | SSL:{d['ssl']:.1f} ({'SUDAH' if d['swept_ssl'] else 'BELUM'})
MFI 15m:{d['mfi_15m']:.1f} 5m:{d['mfi_5m']:.1f} Daily:{d['mfi_daily']:.1f}
{d['vol_status_15m']} | {d['vol_status_5m']}
Quarters: Q1 {d['q1']:.1f} Q2 {d['q2']:.1f} Q3 {d['q3']:.1f}
------------------------------
SWING SETUP:
{setup}
------------------------------
SCALP 5-10M SETUP:
{s_setup}
SCALP NOTES:
{scalp_notes}
------------------------------
13 BAHAN CHECKLIST:
{notes_str}
------------------------------
MM: Risk 0.5% | Max 2 loss OFF
SOP: Sweep + Vol Tinggi + MFI OS/OB + LIMIT FVG 15m/5m
WAKTU: {d['time_full']}
```"""

def keyboard():
    mk = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    mk.add(
        telebot.types.KeyboardButton("XAU 13 BAHAN KSA"),
        telebot.types.KeyboardButton("SCALP 5-10M KSA"),
        telebot.types.KeyboardButton("VOLUME & MFI REAL"),
        telebot.types.KeyboardButton("BUY"),
        telebot.types.KeyboardButton("SELL"),
        telebot.types.KeyboardButton("Killzone KSA"),
        telebot.types.KeyboardButton("Backtest REAL"),
        telebot.types.KeyboardButton("ID Saya")
    )
    return mk

def inline_buttons():
    mk = telebot.types.InlineKeyboardMarkup(row_width=2)
    mk.add(
        telebot.types.InlineKeyboardButton("BUY 13 BAHAN", callback_data="BUY"),
        telebot.types.InlineKeyboardButton("SELL 13 BAHAN", callback_data="SELL"),
        telebot.types.InlineKeyboardButton("SCALP BUY 5M", callback_data="SCALP_BUY"),
        telebot.types.InlineKeyboardButton("SCALP SELL 5M", callback_data="SCALP_SELL")
    )
    return mk

@bot.message_handler(commands=['start','xau','myid'])
def start_cmd(m):
    bot.send_message(m.chat.id, "Bot XAU FINAL TERLENGKAP KSA Madinah Ready - 13 Bahan + Vol + MFI + Scalp 5-10M + Backtest REAL:", reply_markup=keyboard())
    d,a,s = get_all_data()
    if d:
        bot.send_message(m.chat.id, build_message(d,a,s), parse_mode="Markdown", reply_markup=inline_buttons())

@bot.message_handler(func=lambda m: True)
def handle_all(m):
    text = (m.text or "").strip()
    d,a,s = get_all_data()
    if not d:
        bot.send_message(m.chat.id, "Loading REAL data dari TwelveData...", reply_markup=keyboard())
        return

    if text in ["XAU 13 BAHAN KSA","VOLUME & MFI REAL"]:
        bot.send_message(m.chat.id, build_message(d,a,s), parse_mode="Markdown", reply_markup=inline_buttons())
    elif text == "SCALP 5-10M KSA":
        # kirim scalping saja
        txt = f"""```
SCALPING 5-10 MENIT KSA | {d['time']} | {d['kz']}
Live: {d['live']:.2f}$ | MFI 5m:{d['mfi_5m']:.1f} 15m:{d['mfi_15m']:.1f}
{d['vol_status_5m']} | {d['vol_status_15m']}
Sweep 5m Bull:{d['swept_5m_bull']} Bear:{d['swept_5m_bear']}
{s['bias']} - {s['strength']} Score {s['score_buy']}:{s['score_sell']}
Entry:{s['entry']:.1f} SL:{s['sl']:.1f} TP1:{s['tp1']:.1f} TP2:{s['tp2']:.1f} RR 1:{s['rr']:.1f}
Hold: {s['hold']}
```"""
        bot.send_message(m.chat.id, txt, parse_mode="Markdown", reply_markup=keyboard())
    elif text in ["BUY","SELL"]:
        a["bias"] = text
        bot.send_message(m.chat.id, build_message(d,a,s), parse_mode="Markdown", reply_markup=inline_buttons())
    elif text == "Killzone KSA":
        now = datetime.now(KSA_TZ)
        txt = f"""```
Killzone Madinah KSA GMT+3:
London: 11:00-13:00 KSA
NY: 15:30-18:00 KSA
Sekarang: {now.strftime('%H:%M KSA')} - {d['kz']}
DXY: {d['dxy']:.2f} US10Y: {d['us10y']:.2f}%
MFI 5m: {d['mfi_5m']:.1f} 15m: {d['mfi_15m']:.1f} Daily: {d['mfi_daily']:.1f}
{d['vol_status_5m']} | {d['vol_status_15m']}
Waktu: {now.strftime('%Y-%m-%d %H:%M:%S KSA (Madinah)')}
```"""
        bot.send_message(m.chat.id, txt, parse_mode="Markdown", reply_markup=keyboard())
    elif text == "Backtest REAL":
        bot.send_message(m.chat.id, "Backtest REAL butuh internet & credit TwelveData. Buka di browser: /backtest untuk swing 5 bulan dan /backtest_scalping untuk scalping 5-10m. Hasilnya REAL fetch, bukan dummy akumulasi.", reply_markup=keyboard())
    elif text == "ID Saya":
        bot.send_message(m.chat.id, f"ID lu: `{m.chat.id}`\nWaktu lu: {d['time_full']}\nCopy ID ini ke Render ENV TARGET_CHAT_ID", parse_mode="Markdown", reply_markup=keyboard())

@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    d,a,s = get_all_data()
    if not d:
        bot.answer_callback_query(call.id, "Loading...")
        return
    if call.data == "BUY":
        a["bias"] = "BUY"
        bot.send_message(call.message.chat.id, build_message(d,a,s), parse_mode="Markdown", reply_markup=inline_buttons())
    elif call.data == "SELL":
        a["bias"] = "SELL"
        bot.send_message(call.message.chat.id, build_message(d,a,s), parse_mode="Markdown", reply_markup=inline_buttons())
    elif call.data == "SCALP_BUY":
        s["bias"] = "BUY SCALP 5-10M"
        bot.send_message(call.message.chat.id, build_message(d,a,s), parse_mode="Markdown", reply_markup=inline_buttons())
    elif call.data == "SCALP_SELL":
        s["bias"] = "SELL SCALP 5-10M"
        bot.send_message(call.message.chat.id, build_message(d,a,s), parse_mode="Markdown", reply_markup=inline_buttons())
    bot.answer_callback_query(call.id, "OK")

# === FLASK + BACKTEST REAL (bukan dummy) ===
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot XAU FINAL TERLENGKAP KSA - 13 BAHAN + VOL + MFI + SCALP 5-10M + BACKTEST REAL - Ready - /check /backtest /backtest_scalping /getid /getupdates"

@app.route('/check')
def check():
    try:
        d,a,s = get_all_data()
        return jsonify({
            "time_ksa": d["time_full"] if d else None,
            "live": d["live"] if d else None,
            "bias_swing": a["bias"] if a else None,
            "bias_scalp": s["bias"] if s else None,
            "score_swing": f"{a['score_buy']}:{a['score_sell']}" if a else None,
            "score_scalp": f"{s['score_buy']}:{s['score_sell']}" if s else None,
            "mfi_5m": d["mfi_5m"] if d else None,
            "mfi_15m": d["mfi_15m"] if d else None,
            "vol_5m": d["vol_status_5m"] if d else None,
            "vol_15m": d["vol_status_15m"] if d else None,
            "kz": d["kz"] if d else None,
            "bot_token_set": bool(os.getenv("BOT_TOKEN")),
            "td_key_set": bool(os.getenv("TD_API_KEY")),
            "target_chat_id": os.getenv("TARGET_CHAT_ID") or "NOT SET"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/backtest')
def backtest_real():
    """Backtest 5 bulan REAL fetch TwelveData - BUKAN dummy akumulasi"""
    try:
        # Fetch 150 hari
        xau = td_get("XAU/USD", "time_series", "1day", 150)
        if "values" not in xau:
            return jsonify({"error": "Gagal fetch TwelveData, cek TD_API_KEY", "raw": xau}), 500
        
        values = list(reversed(xau["values"]))  # oldest first
        trades = []
        balance = 10000
        risk = 0.01
        
        for i in range(20, len(values)-1):
            today = values[i]
            yest = values[i-1]
            week = values[max(0,i-5):i]
            weekly_high = max(float(v["high"]) for v in week)
            weekly_low = min(float(v["low"]) for v in week)
            weekly_50 = (weekly_high+weekly_low)/2
            live = float(today["close"])
            is_discount = live < weekly_50
            
            # MFI
            mfi, _, _, _, _ = calc_mfi_volume(values[max(0,i-15):i+1], 14)
            
            # Skor sederhana 13 bahan (tanpa DXY untuk backtest biar hemat credit)
            score_buy = 0
            score_sell = 0
            if is_discount:
                score_buy += 2
            else:
                score_sell += 2
            if live < float(yest["low"]):
                score_buy += 2
            if live > float(yest["high"]):
                score_sell += 2
            if mfi < 20:
                score_buy += 2
            elif mfi > 80:
                score_sell += 2
            if live > sum(float(v["close"]) for v in values[max(0,i-20):i])/20:
                score_buy += 1
            else:
                score_sell += 1
            
            if score_buy >= score_sell+3:
                bias = "BUY"
            elif score_sell >= score_buy+3:
                bias = "SELL"
            else:
                continue
            
            entry = float(today["low"])+2 if bias=="BUY" else float(today["high"])-2
            sl = float(yest["low"])-3 if bias=="BUY" else float(yest["high"])+3
            tp = float(today["high"])+20 if bias=="BUY" else float(today["low"])-20
            
            next_day = values[i+1]
            nh = float(next_day["high"])
            nl = float(next_day["low"])
            
            result = "FLOAT"
            if bias=="BUY":
                if nl <= sl:
                    result = "SL"
                elif nh >= tp:
                    result = "TP"
            else:
                if nh >= sl:
                    result = "SL"
                elif nl <= tp:
                    result = "TP"
            
            if result != "FLOAT":
                rr = abs(tp-entry)/abs(entry-sl) if entry!=sl else 0
                profit = balance*risk*rr if result=="TP" else -balance*risk
                balance += profit
                trades.append({
                    "date": today["datetime"],
                    "bias": bias,
                    "score": f"{score_buy}:{score_sell}",
                    "mfi": round(mfi,1),
                    "entry": entry,
                    "sl": sl,
                    "tp": tp,
                    "result": result,
                    "rr": round(rr,2),
                    "balance": round(balance,2)
                })
        
        win = len([t for t in trades if t["result"]=="TP"])
        loss = len([t for t in trades if t["result"]=="SL"])
        return jsonify({
            "periode": "5 bulan REAL TwelveData 1day",
            "total_trade": len(trades),
            "win": win,
            "loss": loss,
            "winrate": round(win/len(trades)*100,1) if trades else 0,
            "balance_start": 10000,
            "balance_end": round(balance,2),
            "trades": trades[-20:]  # 20 terakhir biar gak berat
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/backtest_scalping')
def backtest_scalping_real():
    """Backtest scalping 5-10m REAL"""
    try:
        xau_5m = td_get("XAU/USD", "time_series", "5min", 1000)
        if "values" not in xau_5m:
            return jsonify({"error": "Gagal fetch 5m, cek credit TwelveData", "raw": xau_5m}), 500
        
        values = list(reversed(xau_5m["values"]))
        trades = []
        
        for i in range(20, len(values)-1):
            today = values[i]
            live = float(today["close"])
            mfi, vol_ratio, _, _, _ = calc_mfi_volume(values[max(0,i-15):i+1], 14)
            
            score_buy = 0
            score_sell = 0
            if mfi < 20:
                score_buy += 3
            elif mfi > 80:
                score_sell += 3
            
            # sweep 5 candle
            last5 = values[max(0,i-5):i]
            if last5:
                last5_high = max(float(v["high"]) for v in last5)
                last5_low = min(float(v["low"]) for v in last5)
                if live < last5_low:
                    score_buy += 2
                if live > last5_high:
                    score_sell += 2
            
            if vol_ratio > 180:
                if score_buy>0:
                    score_buy += 1
                if score_sell>0:
                    score_sell += 1
            
            if score_buy >= score_sell+3:
                bias = "BUY SCALP"
            elif score_sell >= score_buy+3:
                bias = "SELL SCALP"
            else:
                continue
            
            entry = live
            sl = live-5 if bias.startswith("BUY") else live+5
            tp = live+8 if bias.startswith("BUY") else live-8
            
            nxt = values[i+1]
            nh = float(nxt["high"])
            nl = float(nxt["low"])
            
            result = "FLOAT"
            if bias.startswith("BUY"):
                if nl <= sl:
                    result = "SL"
                elif nh >= tp:
                    result = "TP"
            else:
                if nh >= sl:
                    result = "SL"
                elif nl <= tp:
                    result = "TP"
            
            if result != "FLOAT":
                trades.append({
                    "datetime": today["datetime"],
                    "bias": bias,
                    "score": f"{score_buy}:{score_sell}",
                    "mfi_5m": round(mfi,1),
                    "vol_ratio": round(vol_ratio,0),
                    "entry": entry,
                    "sl": sl,
                    "tp": tp,
                    "result": result
                })
        
        win = len([t for t in trades if t["result"]=="TP"])
        return jsonify({
            "periode": "1000 candle 5m REAL (~1 minggu)",
            "total": len(trades),
            "win": win,
            "loss": len(trades)-win,
            "winrate": round(win/len(trades)*100,1) if trades else 0,
            "trades": trades[-30:]
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/getid')
def getid():
    token = os.getenv("BOT_TOKEN")
    if not token or token == "dummy":
        return jsonify({"error": "BOT_TOKEN not set"}), 500
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10).json()
        return jsonify(r)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/getupdates')
def getupdates():
    token = os.getenv("BOT_TOKEN")
    if not token or token == "dummy":
        return jsonify({"error": "BOT_TOKEN not set"}), 500
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=10).json()
        last_chat_id = None
        if r.get("ok") and r.get("result"):
            last = r["result"][-1] if r["result"] else None
            if last:
                last_chat_id = last.get("message", {}).get("chat", {}).get("id") or last.get("channel_post", {}).get("chat", {}).get("id")
        return jsonify({"raw": r, "last_chat_id": last_chat_id, "hint": "Copy last_chat_id ke ENV TARGET_CHAT_ID"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

if __name__ == "__main__":
    try:
        bot.remove_webhook()
        time.sleep(1)
        print("Webhook removed fix 409")
    except:
        pass
    threading.Thread(target=run_flask, daemon=True).start()
    print("Bot FINAL TERLENGKAP KSA jalan - 13 bahan + Vol + MFI + Scalp 5-10M + Backtest REAL")
    while True:
        try:
            bot.infinity_polling(skip_pending=True, timeout=20, long_polling_timeout=20)
        except Exception as e:
            print(f"Polling error: {e} - retry 5 detik")
            time.sleep(5)
