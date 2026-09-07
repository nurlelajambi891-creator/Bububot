"""
BOT XAUUSD V2.1 - AUTO MONITOR + TELEGRAM ALERT + API CACHE
=============================================================
Tujuan:
- Ambil data XAUUSD dari Twelve Data
- Analisis multi-timeframe Daily / 15M / 5M
- Tetap bisa dipanggil manual via Telegram
- AUTO MONITOR: cek market berkala dan kirim alert BUY/SELL baru
- Tidak mengirim alert berulang untuk setup yang sama
- Hemat API credit dengan cache per timeframe
- Flask endpoint untuk Render + UptimeRobot

ENV WAJIB:
BOT_TOKEN
TD_API_KEY

ENV OPSIONAL:
TELEGRAM_CHAT_ID   -> chat ID tujuan alert otomatis
RENDER_EXTERNAL_URL
SYMBOL=XAU/USD
MONITOR_SECONDS=60
ALERT_COOLDOWN=900
"""

import os
import time
import threading
from datetime import datetime, timezone, timedelta

import requests
import telebot
from flask import Flask, jsonify

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
TD_KEY = os.getenv("TD_API_KEY", "").strip()
SYMBOL = os.getenv("SYMBOL", "XAU/USD").strip()
MONITOR_SECONDS = max(30, int(os.getenv("MONITOR_SECONDS", "60")))
ALERT_COOLDOWN = max(60, int(os.getenv("ALERT_COOLDOWN", "900")))
CACHE_TTL = 60

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN belum di-set di Render Environment.")
if not TD_KEY:
    raise RuntimeError("TD_API_KEY belum di-set di Render Environment.")

bot = telebot.TeleBot(BOT_TOKEN, threaded=True)
app = Flask(__name__)
KSA_TZ = timezone(timedelta(hours=3))

# ---------------------------------------------------------------------
# STATE
# ---------------------------------------------------------------------
CACHE = {
    "price": {"data": None, "time": 0},
    "quote": {"data": None, "time": 0},
    "daily": {"data": None, "time": 0},
    "15m": {"data": None, "time": 0},
    "5m": {"data": None, "time": 0},
    "dxy": {"data": None, "time": 0},
    "us10y": {"data": None, "time": 0},
}

CHAT_IDS = set()
try:
    env_chat = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if env_chat:
        for x in env_chat.split(","):
            if x.strip():
                CHAT_IDS.add(int(x.strip()))
except Exception:
    pass

STATE = {
    "last_alert_key": None,
    "last_alert_time": 0,
    "last_candle_5m": None,
    "last_check": 0,
    "last_error": None,
}

# ---------------------------------------------------------------------
# TWELVE DATA
# ---------------------------------------------------------------------
def td_get(symbol, endpoint="price", interval="1day", outputsize=30,
           ttl=CACHE_TTL, cache_key=None):
    """Cached Twelve Data request."""
    key = cache_key or f"{symbol}|{endpoint}|{interval}|{outputsize}"
    slot = CACHE.get(key)

    # Generic cache slot if not one of the predefined slots
    if slot is None:
        slot = {"data": None, "time": 0}
        CACHE[key] = slot

    now = time.time()
    if slot["data"] is not None and now - slot["time"] < ttl:
        return slot["data"]

    try:
        if endpoint == "price":
            url = "https://api.twelvedata.com/price"
            params = {"symbol": symbol, "apikey": TD_KEY}
        elif endpoint == "quote":
            url = "https://api.twelvedata.com/quote"
            params = {"symbol": symbol, "apikey": TD_KEY}
        else:
            url = "https://api.twelvedata.com/time_series"
            params = {
                "symbol": symbol,
                "interval": interval,
                "apikey": TD_KEY,
                "outputsize": outputsize,
            }

        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        data = r.json()

        # Twelve Data errors are JSON responses too.
        if data.get("status") == "error" or (
            "code" in data and data.get("code") != 200 and "values" not in data
        ):
            raise RuntimeError(str(data))

        slot["data"] = data
        slot["time"] = now
        return data

    except Exception as e:
        STATE["last_error"] = f"{symbol}/{endpoint}: {e}"
        # Keep stale cache if API temporarily fails.
        if slot["data"] is not None:
            return slot["data"]
        return {"error": str(e)}


def get_cached_market():
    """
    API strategy:
    - price: 30 sec
    - quote: 60 sec
    - 5m/15m: 60 sec
    - daily: 15 min
    - DXY/US10Y: 5 min
    """
    return {
        "price": td_get(SYMBOL, "price", ttl=30, cache_key="price"),
        "quote": td_get(SYMBOL, "quote", ttl=60, cache_key="quote"),
        "daily": td_get(SYMBOL, "time_series", "1day", 30,
                         ttl=900, cache_key="daily"),
        "15m": td_get(SYMBOL, "time_series", "15min", 60,
                      ttl=60, cache_key="15m"),
        "5m": td_get(SYMBOL, "time_series", "5min", 60,
                      ttl=60, cache_key="5m"),
        "dxy": td_get("DXY", "quote", ttl=300, cache_key="dxy"),
        "us10y": td_get("US10Y", "quote", ttl=300, cache_key="us10y"),
    }


# ---------------------------------------------------------------------
# INDICATORS / STRUCTURE
# ---------------------------------------------------------------------
def closes(values):
    return [float(x["close"]) for x in reversed(values) if "close" in x]


def ema(values, period=20):
    vals = closes(values)
    if len(vals) < period:
        return None
    k = 2.0 / (period + 1.0)
    e = sum(vals[:period]) / period
    for price in vals[period:]:
        e = price * k + e * (1 - k)
    return e


def mfi(values, period=14):
    try:
        vals = list(reversed(values))
        if len(vals) < period + 2:
            return 50.0
        tps, flows = [], []
        for v in vals:
            h, l, c = float(v["high"]), float(v["low"]), float(v["close"])
            vol = float(v.get("volume", 0) or 0)
            if vol <= 0:
                vol = max(h - l, 0.01) * 1000
            tp = (h + l + c) / 3
            tps.append(tp)
            flows.append(tp * vol)

        pos = neg = 0.0
        for i in range(max(1, len(tps) - period), len(tps)):
            if tps[i] > tps[i - 1]:
                pos += flows[i]
            elif tps[i] < tps[i - 1]:
                neg += flows[i]

        if neg == 0:
            return 100.0 if pos else 50.0
        return 100 - 100 / (1 + pos / neg)
    except Exception:
        return 50.0


def volume_ratio(values, period=20):
    try:
        vals = list(reversed(values))
        vols = [float(v.get("volume", 0) or 0) for v in vals]
        if not vols:
            return 100.0
        avg = sum(vols[-period:]) / min(period, len(vols))
        return vols[-1] / avg * 100 if avg else 100.0
    except Exception:
        return 100.0


def fvg_zones(values, lookback=30):
    """
    Conventional 3-candle FVG:
    bullish: candle i-1 low > candle i+1 high
    bearish: candle i-1 high < candle i+1 low
    Values are newest first, so reverse to chronological order.
    """
    try:
        v = list(reversed(values))[-lookback:]
        bull, bear = [], []
        for i in range(1, len(v) - 1):
            a, c = v[i - 1], v[i + 1]
            if float(a["low"]) > float(c["high"]):
                bull.append((float(c["high"]), float(a["low"])))
            if float(a["high"]) < float(c["low"]):
                bear.append((float(a["high"]), float(c["low"])))
        return bull, bear
    except Exception:
        return [], []


def swing_levels(values, left=2, right=2, lookback=60):
    try:
        v = list(reversed(values))[-lookback:]
        highs, lows = [], []
        for i in range(left, len(v) - right):
            h = float(v[i]["high"])
            l = float(v[i]["low"])
            if all(h > float(v[j]["high"]) for j in range(i-left, i)) and \
               all(h >= float(v[j]["high"]) for j in range(i+1, i+right+1)):
                highs.append(h)
            if all(l < float(v[j]["low"]) for j in range(i-left, i)) and \
               all(l <= float(v[j]["low"]) for j in range(i+1, i+right+1)):
                lows.append(l)
        return highs, lows
    except Exception:
        return [], []


def last_candle_key(values):
    try:
        return values[0].get("datetime") or values[0].get("timestamp")
    except Exception:
        return None


def analyze(data):
    price_j = data["price"]
    quote = data["quote"]
    daily = data["daily"]
    m15 = data["15m"]
    m5 = data["5m"]

    live = float(
        price_j.get("price", 0) or quote.get("close", 0) or 0
    )
    if live <= 0:
        raise RuntimeError("Harga XAUUSD tidak tersedia.")

    dv = daily.get("values", [])
    v15 = m15.get("values", [])
    v5 = m5.get("values", [])

    if len(v15) < 20 or len(v5) < 20 or len(dv) < 5:
        raise RuntimeError("Data candle belum cukup untuk analisis.")

    # Daily liquidity
    y = dv[1] if len(dv) > 1 else dv[0]
    y_high, y_low = float(y["high"]), float(y["low"])

    daily_highs = [float(x["high"]) for x in dv[:5]]
    daily_lows = [float(x["low"]) for x in dv[:5]]
    range_high, range_low = max(daily_highs), min(daily_lows)
    mid = (range_high + range_low) / 2

    # MTF EMA
    e15 = ema(v15, 20)
    e5 = ema(v5, 20)
    ed = ema(dv, 20)

    # Structure
    h15, l15 = swing_levels(v15)
    h5, l5 = swing_levels(v5)

    last15_close = float(v15[0]["close"])
    last5_close = float(v5[0]["close"])

    h15_last = h15[-1] if h15 else last15_close
    l15_last = l15[-1] if l15 else last15_close
    h5_last = h5[-1] if h5 else last5_close
    l5_last = l5[-1] if l5 else last5_close

    bull15 = bool(e15 and last15_close > e15 and last15_close > l15_last)
    bear15 = bool(e15 and last15_close < e15 and last15_close < h15_last)
    bull5 = bool(e5 and last5_close > e5)
    bear5 = bool(e5 and last5_close < e5)

    # Liquidity sweep = wick beyond previous day liquidity + close back inside
    cur15 = v15[0]
    sweep_ssl = (
        float(cur15["low"]) < y_low and float(cur15["close"]) > y_low
    )
    sweep_bsl = (
        float(cur15["high"]) > y_high and float(cur15["close"]) < y_high
    )

    bull_fvg, bear_fvg = fvg_zones(v15)

    mfi15 = mfi(v15)
    mfi5 = mfi(v5)
    vr15 = volume_ratio(v15)
    vr5 = volume_ratio(v5)

    dxy = float(data["dxy"].get("close", 0) or data["dxy"].get("price", 0) or 0)
    us10y = float(
        data["us10y"].get("close", 0) or data["us10y"].get("price", 0) or 0
    )

    buy = sell = 0
    notes = []

    # Technical structure has highest weight
    if sweep_ssl:
        buy += 4
        notes.append("SSL sweep + close kembali di atas PDL")
    if sweep_bsl:
        sell += 4
        notes.append("BSL sweep + close kembali di bawah PDH")

    if bull15:
        buy += 3
        notes.append("15M bullish")
    if bear15:
        sell += 3
        notes.append("15M bearish")

    if bull5:
        buy += 2
        notes.append("5M bullish")
    if bear5:
        sell += 2
        notes.append("5M bearish")

    if bull_fvg:
        buy += 1
        notes.append(f"{len(bull_fvg)} bullish FVG 15M")
    if bear_fvg:
        sell += 1
        notes.append(f"{len(bear_fvg)} bearish FVG 15M")

    if live < mid:
        buy += 1
        notes.append("Discount 5D")
    else:
        sell += 1
        notes.append("Premium 5D")

    if mfi15 < 25:
        buy += 1
        notes.append(f"MFI 15M oversold {mfi15:.1f}")
    elif mfi15 > 75:
        sell += 1
        notes.append(f"MFI 15M overbought {mfi15:.1f}")

    if dxy:
        if dxy < 103.5:
            buy += 1
        else:
            sell += 1

    if us10y:
        if us10y < 4.0:
            buy += 1
        else:
            sell += 1

    # HARD GATES: no structure = no trade
    if sweep_ssl and bull15 and bull5 and buy > sell:
        bias = "BUY"
    elif sweep_bsl and bear15 and bear5 and sell > buy:
        bias = "SELL"
    else:
        bias = "WAIT"

    strength = "A+" if bias != "WAIT" and max(buy, sell) >= 10 else (
        "A" if bias != "WAIT" else "C"
    )

    # Entry zone around FVG; fallback to recent swing zone.
    entry_low = entry_high = live
    sl = tp1 = tp2 = tp3 = live

    if bias == "BUY":
        zone = bull_fvg[-1] if bull_fvg else (l5_last, min(l5_last + 2.0, live))
        entry_low, entry_high = sorted(zone)
        entry = (entry_low + entry_high) / 2
        sl_candidates = [y_low - 1.5, l5_last - 1.0, entry_low - 2.0]
        sl = min(sl_candidates)
        tp_candidates = sorted(set(
            [y_high, range_high] +
            [x for x in h15[-5:] if x > entry]
        ))
        tp1 = tp_candidates[0] if tp_candidates else entry + 10
        tp2 = tp_candidates[1] if len(tp_candidates) > 1 else entry + 20
        tp3 = tp_candidates[2] if len(tp_candidates) > 2 else entry + 30
    elif bias == "SELL":
        zone = bear_fvg[-1] if bear_fvg else (max(h5_last - 2.0, live), h5_last)
        entry_low, entry_high = sorted(zone)
        entry = (entry_low + entry_high) / 2
        sl_candidates = [y_high + 1.5, h5_last + 1.0, entry_high + 2.0]
        sl = max(sl_candidates)
        tp_candidates = sorted(set(
            [y_low, range_low] +
            [x for x in l15[-5:] if x < entry]
        ), reverse=True)
        tp1 = tp_candidates[0] if tp_candidates else entry - 10
        tp2 = tp_candidates[1] if len(tp_candidates) > 1 else entry - 20
        tp3 = tp_candidates[2] if len(tp_candidates) > 2 else entry - 30
    else:
        entry = live

    risk = abs(entry - sl) if bias != "WAIT" else 0
    rr1 = abs(tp1 - entry) / risk if risk else 0
    rr2 = abs(tp2 - entry) / risk if risk else 0
    rr3 = abs(tp3 - entry) / risk if risk else 0

    # Safety gate: reject bad RR
    if bias != "WAIT" and rr1 < 1.2:
        notes.append(f"TP1 RR terlalu kecil ({rr1:.2f}) -> WAIT")
        bias = "WAIT"
        strength = "C"

    now = datetime.now(KSA_TZ)
    kz = "LONDON KZ" if 11 <= now.hour <= 13 else (
        "NY KZ" if 15 <= now.hour <= 18 else "LUAR KILLZONE"
    )

    ema_bias = (
        "BULL" if ed and live > ed else
        "BEAR" if ed and live < ed else "NEUTRAL"
    )

    return {
        "time": now.strftime("%d %b %H:%M:%S KSA"),
        "live": live,
        "bias": bias,
        "strength": strength,
        "score_buy": buy,
        "score_sell": sell,
        "entry": entry,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
        "rr1": rr1,
        "rr2": rr2,
        "mfi15": mfi15,
        "mfi5": mfi5,
        "vol15": vr15,
        "vol5": vr5,
        "dxy": dxy,
        "us10y": us10y,
        "pdh": y_high,
        "pdl": y_low,
        "range_high": range_high,
        "range_low": range_low,
        "mid": mid,
        "kz": kz,
        "ema_bias": ema_bias,
        "sweep_ssl": sweep_ssl,
        "sweep_bsl": sweep_bsl,
        "candle5": last_candle_key(v5),
        "notes": notes,
    }


def get_analysis():
    return analyze(get_cached_market())


# ---------------------------------------------------------------------
# TELEGRAM MESSAGE
# ---------------------------------------------------------------------
def build_message(a, automatic=False):
    title = "🔔 AUTO SIGNAL XAUUSD" if automatic else "📊 XAUUSD ANALYSIS"

    if a["bias"] == "WAIT":
        setup = (
            f"WAIT / NO TRADE ({a['strength']})\n"
            f"Score BUY {a['score_buy']} : SELL {a['score_sell']}\n"
            f"Menunggu sweep + konfirmasi struktur."
        )
    else:
        setup = (
            f"🚨 {a['bias']} LIMIT — {a['strength']}\n"
            f"Entry Zone : {a['entry_low']:.2f} - {a['entry_high']:.2f}\n"
            f"Entry Mid  : {a['entry']:.2f}\n"
            f"SL         : {a['sl']:.2f}\n"
            f"TP1        : {a['tp1']:.2f}  RR 1:{a['rr1']:.2f}\n"
            f"TP2        : {a['tp2']:.2f}  RR 1:{a['rr2']:.2f}\n"
            f"TP3        : {a['tp3']:.2f}  RR 1:{a['rr3']:.2f}"
        )

    notes = "\n".join(f"• {x}" for x in a["notes"][-10:]) or "• Tidak ada"

    return (
        f"{title}\n"
        f"Waktu: {a['time']}\n\n"
        f"Live: {a['live']:.2f}\n"
        f"Bias EMA Daily: {a['ema_bias']}\n"
        f"Premium/Discount: "
        f"{'DISCOUNT' if a['live'] < a['mid'] else 'PREMIUM'}\n"
        f"PDH/PDL: {a['pdh']:.2f} / {a['pdl']:.2f}\n"
        f"5D High/Low: {a['range_high']:.2f} / {a['range_low']:.2f}\n\n"
        f"15M MFI: {a['mfi15']:.1f} | Vol {a['vol15']:.0f}%\n"
        f"5M MFI : {a['mfi5']:.1f} | Vol {a['vol5']:.0f}%\n"
        f"DXY: {a['dxy']:.2f} | US10Y: {a['us10y']:.2f}%\n"
        f"Killzone: {a['kz']}\n\n"
        f"{setup}\n\n"
        f"CHECKLIST:\n{notes}\n"
    )


# ---------------------------------------------------------------------
# AUTO MONITOR
# ---------------------------------------------------------------------
def register_chat(chat_id):
    if chat_id:
        CHAT_IDS.add(int(chat_id))


def send_to_all(text):
    dead = []
    sent = 0
    for chat_id in list(CHAT_IDS):
        try:
            bot.send_message(chat_id, text)
            sent += 1
        except Exception as e:
            print(f"[TELEGRAM] gagal kirim ke {chat_id}: {e}")
            # Do not remove permanently; user may temporarily block/network fail.
    return sent


def monitor_loop():
    print(
        f"[MONITOR] aktif | interval={MONITOR_SECONDS}s | "
        f"chat_ids={len(CHAT_IDS)}"
    )

    while True:
        started = time.time()
        try:
            a = get_analysis()
            STATE["last_check"] = time.time()

            # Only evaluate a fresh 5M candle once.
            candle = a["candle5"]
            if candle and candle == STATE["last_candle_5m"]:
                time.sleep(max(1, MONITOR_SECONDS - (time.time() - started)))
                continue

            if candle:
                STATE["last_candle_5m"] = candle

            if a["bias"] in ("BUY", "SELL"):
                # Key uses direction + entry zone + SL + TP1.
                key = (
                    a["bias"],
                    round(a["entry_low"], 1),
                    round(a["entry_high"], 1),
                    round(a["sl"], 1),
                    round(a["tp1"], 1),
                )

                now = time.time()
                cooldown_ok = now - STATE["last_alert_time"] >= ALERT_COOLDOWN
                new_setup = key != STATE["last_alert_key"]

                if (new_setup or cooldown_ok) and CHAT_IDS:
                    text = build_message(a, automatic=True)
                    sent = send_to_all(text)
                    if sent:
                        STATE["last_alert_key"] = key
                        STATE["last_alert_time"] = now
                        print(f"[ALERT] {a['bias']} dikirim ke {sent} chat.")
                elif not CHAT_IDS:
                    print(
                        "[ALERT] ada signal tetapi belum ada chat ID. "
                        "Set TELEGRAM_CHAT_ID atau kirim /start ke bot."
                    )

        except Exception as e:
            STATE["last_error"] = str(e)
            print(f"[MONITOR] error: {e}")

        elapsed = time.time() - started
        time.sleep(max(1, MONITOR_SECONDS - elapsed))


# ---------------------------------------------------------------------
# TELEGRAM HANDLERS
# ---------------------------------------------------------------------
@bot.message_handler(commands=["start"])
def start_cmd(message):
    register_chat(message.chat.id)
    bot.send_message(
        message.chat.id,
        "✅ Bot XAUUSD V2.1 aktif.\n"
        "Chat ini sudah didaftarkan untuk AUTO SIGNAL.\n\n"
        "Command:\n"
        "/sinyal — analisis sekarang\n"
        "/xau — analisis sekarang\n"
        "/status — status monitor"
    )


@bot.message_handler(commands=["sinyal", "xau", "signal"])
def signal_cmd(message):
    register_chat(message.chat.id)
    try:
        a = get_analysis()
        bot.send_message(message.chat.id, build_message(a))
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Gagal analisis: {e}")


@bot.message_handler(commands=["status"])
def status_cmd(message):
    register_chat(message.chat.id)
    bot.send_message(
        message.chat.id,
        "🟢 BOT STATUS\n"
        f"Monitor: ON\n"
        f"Interval: {MONITOR_SECONDS}s\n"
        f"Alert cooldown: {ALERT_COOLDOWN}s\n"
        f"Registered chat: {len(CHAT_IDS)}\n"
        f"Last check: {datetime.fromtimestamp(STATE['last_check'], KSA_TZ).strftime('%Y-%m-%d %H:%M:%S') if STATE['last_check'] else '-'}\n"
        f"Last error: {STATE['last_error'] or '-'}"
    )


@bot.message_handler(func=lambda m: True)
def handle_all(message):
    register_chat(message.chat.id)
    try:
        a = get_analysis()
        bot.send_message(message.chat.id, build_message(a))
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Gagal analisis: {e}")


# ---------------------------------------------------------------------
# FLASK / RENDER
# ---------------------------------------------------------------------
@app.route("/")
def home():
    return (
        "XAUUSD V2.1 ONLINE | AUTO MONITOR ON | "
        "Telegram Alert + Twelve Data Cache"
    )


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "monitor": "on",
        "chat_ids": len(CHAT_IDS),
        "last_check": STATE["last_check"],
        "last_error": STATE["last_error"],
    })


@app.route("/check")
def check():
    try:
        a = get_analysis()
        return jsonify({
            "status": "ok",
            "live": a["live"],
            "bias": a["bias"],
            "strength": a["strength"],
            "entry_low": a["entry_low"],
            "entry_high": a["entry_high"],
            "sl": a["sl"],
            "tp1": a["tp1"],
            "tp2": a["tp2"],
            "tp3": a["tp3"],
            "rr1": a["rr1"],
            "rr2": a["rr2"],
            "rr3": a["rr3"],
            "score": f"{a['score_buy']}:{a['score_sell']}",
            "sweep_ssl": a["sweep_ssl"],
            "sweep_bsl": a["sweep_bsl"],
            "dxy": a["dxy"],
            "us10y": a["us10y"],
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


def run_flask():
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)


# ---------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------
if __name__ == "__main__":
    print("==============================================")
    print("XAUUSD V2.1 START")
    print(f"SYMBOL          : {SYMBOL}")
    print(f"MONITOR_SECONDS : {MONITOR_SECONDS}")
    print(f"ALERT_COOLDOWN  : {ALERT_COOLDOWN}")
    print(f"CHAT IDS        : {len(CHAT_IDS)}")
    print("==============================================")

    try:
        bot.remove_webhook()
        time.sleep(1)
    except Exception as e:
        print(f"Webhook cleanup: {e}")

    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=monitor_loop, daemon=True).start()

    while True:
        try:
            bot.infinity_polling(
                skip_pending=True,
                timeout=20,
                long_polling_timeout=20
            )
        except Exception as e:
            print(f"[TELEGRAM POLLING] error: {e}")
            time.sleep(5)
