import time
import requests
import hmac
import hashlib
from datetime import datetime, timedelta

# ===== YOUR PRIVATE DETAILS =====
API_KEY = "KzrOjgSzYNqkqeYZhWkPu4B9XfX8MW"
API_SECRET = "UO9tJTQb0FxTNjA8utrvpLzqPPow83YhH08E7Cc7jP9de1mQOetlvCjw3Ad"
TELEGRAM_BOT_TOKEN = "8688381932:A4Eaf866DqCMBEC1qou_PLz1YWbunZc46AY"
TELEGRAM_CHAT_ID = "2016548975"

# ===== TRADING CONFIG =====
BASE_URL = "https://api.delta.exchange"
SYMBOL = "BTCUSDT"
LEVERAGE = 10
STOP_LOSS_PERCENT = 0.25
TAKE_PROFIT_PERCENT = 0.5
CHECK_INTERVAL = 60
MAX_DAILY_LOSS_PERCENT = 20

# ===== GLOBAL STATE =====
trade_active = False
daily_trades = 0
daily_wins = 0
daily_losses = 0
last_reset = datetime.now()
day_start_capital = None

# ===== DELTA API HELPERS =====
def generate_signature(method, endpoint, timestamp, body=""):
    message = f"{timestamp}{method}{endpoint}{body}"
    signature = hmac.new(
        API_SECRET.encode('utf-8'),
        message.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature

def delta_request(method, endpoint, body=None):
    timestamp = str(int(time.time() * 1000))
    url = f"{BASE_URL}{endpoint}"
    headers = {
        "api-key": API_KEY,
        "timestamp": timestamp,
        "signature": generate_signature(method, endpoint, timestamp, body or ""),
        "Content-Type": "application/json"
    }
    if body:
        response = requests.request(method, url, headers=headers, json=body)
    else:
        response = requests.request(method, url, headers=headers)
    return response.json()

def get_btc_price():
    ticker = delta_request("GET", "/v2/ticker")
    for item in ticker['result']:
        if item['symbol'] == SYMBOL:
            return float(item['price'])
    return None

def get_open_positions():
    positions = delta_request("GET", "/v2/positions")
    for pos in positions.get('result', []):
        if pos['symbol'] == SYMBOL and float(pos['size']) != 0:
            return True
    return False

def get_account_balance():
    account = delta_request("GET", "/v2/wallets/balances")
    for item in account.get('result', []):
        if item['asset'] == 'USDT':
            return float(item['balance'])
    return None

def calculate_quantity(capital):
    trading_capital = capital * 0.9  # 10% buffer
    btc_price = get_btc_price()
    if not btc_price:
        return 0.0001
    position_size = trading_capital * LEVERAGE
    quantity = position_size / btc_price
    return round(quantity, 6)

def place_order(side):
    global trade_active, daily_trades
    capital = get_account_balance()
    if not capital:
        return
    quantity = calculate_quantity(capital)
    if quantity < 0.0001:
        send_telegram("⚠️ Quantity too small. Skipping trade.")
        return
    order_body = {
        "symbol": SYMBOL,
        "side": side,
        "order_type": "market",
        "quantity": quantity,
        "time_in_force": "ioc"
    }
    result = delta_request("POST", "/v2/orders", order_body)
    if 'result' in result:
        trade_active = True
        daily_trades += 1
        send_telegram(f"✅ {side.upper()} order placed for {quantity} BTC")
    return result

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        requests.post(url, json=payload)
    except:
        pass

def check_and_reset_daily():
    global last_reset, daily_wins, daily_losses, daily_trades, day_start_capital
    now = datetime.now()
    current_capital = get_account_balance()
    if current_capital is None:
        return
    if day_start_capital is None:
        day_start_capital = current_capital
    loss_percent = (day_start_capital - current_capital) / day_start_capital * 100
    if loss_percent >= MAX_DAILY_LOSS_PERCENT:
        send_telegram(f"⚠️ Daily loss limit reached ({loss_percent:.1f}%). Stopping for 24h.")
        time.sleep(86400)
        day_start_capital = current_capital
    if now - last_reset > timedelta(hours=24):
        win_rate = (daily_wins / daily_trades * 100) if daily_trades > 0 else 0
        report = (
            f"📈 Daily Report\n✅ Wins: {daily_wins}\n❌ Losses: {daily_losses}\n"
            f"🎯 Win Rate: {win_rate:.1f}%\n📊 Trades: {daily_trades}\n💰 Capital: ₹{current_capital:.2f}"
        )
        send_telegram(report)
        daily_wins = daily_losses = daily_trades = 0
        last_reset = now
        day_start_capital = current_capital

# ===== STRATEGY =====
def get_rsi(prices, period=14):
    if len(prices) < period + 1:
        return 50
    gains = losses = 0
    for i in range(-period, 0):
        diff = prices[i] - prices[i-1]
        if diff > 0:
            gains += diff
        else:
            losses -= diff
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def should_buy(prices):
    if len(prices) < 20:
        return False
    rsi = get_rsi(prices)
    return 40 < rsi < 50 and prices[-1] > prices[-2]

def should_sell(prices):
    if len(prices) < 20:
        return False
    rsi = get_rsi(prices)
    return 50 < rsi < 60 and prices[-1] < prices[-2]

# ===== MAIN LOOP =====
print("🚀 Bot started...")
send_telegram("🤖 Bot started — monitoring 24/7")

price_history = []
while True:
    try:
        check_and_reset_daily()
        trade_active = get_open_positions()
        price = get_btc_price()
        if price:
            price_history.append(price)
            if len(price_history) > 50:
                price_history.pop(0)
        if not trade_active and len(price_history) > 20:
            if should_buy(price_history):
                print("📈 Buy signal")
                place_order("buy")
                daily_wins += 1
            elif should_sell(price_history):
                print("📉 Sell signal")
                place_order("sell")
                daily_wins += 1
        time.sleep(CHECK_INTERVAL)
    except Exception as e:
        send_telegram(f"❌ Error: {str(e)}")
        time.sleep(60)
