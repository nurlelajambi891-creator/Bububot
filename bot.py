import os
import time
import requests
from datetime import datetime
import telebot
from flask import Flask
import threading

BOT_TOKEN = os.getenv("BOT_TOKEN")
TD_KEY = os.getenv("TD_API_KEY")
TARGET_CHAT_ID = os.getenv("TARGET_CHAT_ID")

if not BOT_TOKEN:
    print("ERROR: BOT_TOKEN belum di set di Render ENV")
    # jangan crash, biar log keliatan
    BOT_TOKEN = "dummy"
if not TD_KEY:
    print("ERROR: TD_API_KEY belum di set di Render ENV")
    TD_KEY = "dummy"

bot = telebot.TeleBot(BOT_TOKEN, threaded=False)

CACHE = {"data": None, "time": 0}
CACHE_TTL = 90

def get_twelvedata():
    now = time.time()
    if CACHE["data"] and (now - CACHE["time"] < CACHE_TTL):
        return CACHE["data"]
    url_price = f"https://api.twelvedata.com/price?symbol=XAU/USD&apikey={TD_KEY}"
    url_quote = f"https://api.twelvedata.com/quote?symbol=XAU/USD&apikey={TD_KEY}"
    url_prev = f"https://api.twelvedata.com/time_series?symbol=XAU/USD&interval=1day&apikey={TD_KEY}&outputsize=2"
    try:
        p = requests.get(url_price, timeout=10).json()
        q = requests.get(url_quote, timeout=10).json()
        prev = requests.get(url_prev, timeout=10).json()
        live = float(p.get("price", 0) or q.get("close", 0))
        today_high = float(q.get("high", live))
        today_low = float(q.get("low", live))
        if "values" in prev and len(prev["values"]) >= 2:
            y_high = float(prev["values"][1]["high"])
            y_low = float(prev["values"][1]["low"])
        else:
            y_high = live
            y_low = live
        data = {
            "live": live, "today_high": today_high, "today_low": today_low,
            "y_high": y_high, "y_low": y_low,
            "time": datetime.now().strftime("%d %b %H:%M WIB")
        }
        CACHE["data"] = data
        CACHE["time"] = now
        return data
    except Exception as e:
        print("Error TD:", e)
        return CACHE["data"] if CACHE["data"] else None

def build_message(d, side="BUY"):
    if side == "BUY":
        setup = f"""BUY LIMIT - A+ SETUP
Entry : {d['today_low']+3:.1f}$ - S1 + FVG
SL    : {d['y_low']:.1f}$ - Low Kemarin
TP1   : {d['today_high']:.1f}$ - High Hari Ini
TP2   : {d['today_high']+10:.1f}$ - Bulat
RR    : 1 : 1.8"""
    else:
        setup = f"""SELL LIMIT - A+ SETUP
Entry : {d['today_high']-3:.1f}$ - R1 + FVG
SL    : {d['y_high']:.1f}$ - High Kemarin
TP1   : {d['today_low']:.1f}$ - Low Hari Ini
TP2   : {d['today_low']-10:.1f}$ - Bulat
RR    : 1 : 1.9"""

    return f"""```
XAUUSD LIVE | {d['time']}
------------------------------
Live          : {d['live']:.2f}$
Range Hari Ini: {d['today_high']:.1f}$ / {d['today_low']:.1f}$
Range Kemarin : {d['y_high']:.1f}$ / {d['y_low']:.1f}$
------------------------------
{setup}
------------------------------
status: waiting for entry
```"""

def main_keyboard():
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        telebot.types.KeyboardButton("XAU LIVE"),
        telebot.types.KeyboardButton("Range Hari Ini"),
        telebot.types.KeyboardButton("BUY"),
        telebot.types.KeyboardButton("SELL"),
        telebot.types.KeyboardButton("Aktifkan Auto 30m"),
        telebot.types.KeyboardButton("ID Saya")
    )
    return markup

def buy_sell_inline():
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        telebot.types.InlineKeyboardButton("BUY", callback_data="BUY"),
        telebot.types.InlineKeyboardButton("SELL", callback_data="SELL")
    )
    return markup

@bot.message_handler(commands=['start', 'myid', 'xau'])
def handle_start(message):
    bot.send_message(message.chat.id, "XAU Bot Ready. Pencet tombol di bawah:", reply_markup=main_keyboard())
    d = get_twelvedata()
    if d:
        bot.send_message(message.chat.id, build_message(d, "BUY"), parse_mode="Markdown", reply_markup=buy_sell_inline())

@bot.message_handler(func=lambda m: True)
def handle_all(message):
    text = (message.text or "").strip()
    d = get_twelvedata()
    if not d:
        bot.send_message(message.chat.id, "Loading harga, pencet lagi 5 detik...", reply_markup=main_keyboard())
        return

    if text == "XAU LIVE":
        bot.send_message(message.chat.id, build_message(d, "BUY"), parse_mode="Markdown", reply_markup=buy_sell_inline())
    elif text == "Range Hari Ini":
        txt = f"""```
Live          : {d['live']:.2f}$
Range Hari Ini: {d['today_high']:.1f}$ / {d['today_low']:.1f}$
Range Kemarin : {d['y_high']:.1f}$ / {d['y_low']:.1f}$
```"""
        bot.send_message(message.chat.id, txt, parse_mode="Markdown", reply_markup=main_keyboard())
    elif text == "BUY":
        bot.send_message(message.chat.id, build_message(d, "BUY"), parse_mode="Markdown", reply_markup=buy_sell_inline())
    elif text == "SELL":
        bot.send_message(message.chat.id, build_message(d, "SELL"), parse_mode="Markdown", reply_markup=buy_sell_inline())
    elif text == "ID Saya":
        bot.send_message(message.chat.id, f"ID lu: `{message.chat.id}`\nCopy angka ini ke Render ENV TARGET_CHAT_ID", parse_mode="Markdown", reply_markup=main_keyboard())
    elif text == "Aktifkan Auto 30m":
        if TARGET_CHAT_ID and TARGET_CHAT_ID != "dummy":
            bot.send_message(message.chat.id, f"Auto 30m aktif ke {TARGET_CHAT_ID}", reply_markup=main_keyboard())
        else:
            bot.send_message(message.chat.id, f"Set TARGET_CHAT_ID di Render dulu.\nID lu sekarang: {message.chat.id}", reply_markup=main_keyboard())

@bot.callback_query_handler(func=lambda call: call.data in ["BUY", "SELL"])
def callback_inline(call):
    d = get_twelvedata()
    if not d:
        bot.answer_callback_query(call.id, "Loading...")
        return
    bot.send_message(call.message.chat.id, build_message(d, call.data), parse_mode="Markdown", reply_markup=buy_sell_inline())
    bot.answer_callback_query(call.id, f"{call.data} dikirim")

def auto_push_loop():
    while True:
        time.sleep(1800)  # 30 menit = 144 credit/hari aman
        if not TARGET_CHAT_ID or TARGET_CHAT_ID == "dummy":
            continue
        d = get_twelvedata()
        if d:
            try:
                bot.send_message(int(TARGET_CHAT_ID), "AUTO 30 MENIT\n\n" + build_message(d, "BUY"), parse_mode="Markdown", reply_markup=buy_sell_inline())
                print(f"Auto push ke {TARGET_CHAT_ID}")
            except Exception as e:
                print("Push gagal:", e)

app = Flask(__name__)
@app.route('/')
def home():
    return "Bot XAU Final - Text Only - No Terminal - Ready"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=auto_push_loop, daemon=True).start()
    print("Bot final jalan...")
    bot.infinity_polling()
