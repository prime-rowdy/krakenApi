import time
import base64
import hashlib
import hmac
import requests
import urllib.parse
import json
import pandas as pd
from openpyxl import load_workbook

# Replace these with your Kraken API credentials
API_KEY = 'API_KEY'
API_SECRET = 'API_SECRET'

API_URL = 'https://api.kraken.com'

# Define the Excel file to store transactions
EXCEL_FILE = "trading_log.xlsx"

# Initialize the Excel file if it doesn't exist
def initialize_excel():
    try:
        pd.read_excel(EXCEL_FILE)  # Check if the file exists
    except FileNotFoundError:
        # Create a new DataFrame with the required columns
        df = pd.DataFrame(columns=["Buy Price", "Sell Price", "Percentage Change"])
        df.to_excel(EXCEL_FILE, index=False)
        print(f"Initialized Excel file: {EXCEL_FILE}")

def log_transaction(buy_price, sell_price, percentage_change):
    # Load the existing Excel file
    try:
        df = pd.read_excel(EXCEL_FILE)
    except FileNotFoundError:
        df = pd.DataFrame(columns=["Buy Price", "Sell Price", "Percentage Change"])

    # Add the new transaction
    new_row = {"Buy Price": buy_price, "Sell Price": sell_price, "Percentage Change": percentage_change}
    df = df.append(new_row, ignore_index=True)

    # Save back to the Excel file
    df.to_excel(EXCEL_FILE, index=False)
    print(f"Logged transaction to {EXCEL_FILE}: {new_row}")

def get_kraken_signature(urlpath, data, secret):
    postdata = urllib.parse.urlencode(data)
    encoded = (str(data['nonce']) + postdata).encode('utf-8')
    message = urlpath.encode('utf-8') + hashlib.sha256(encoded).digest()
    mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    sigdigest = base64.b64encode(mac.digest())
    return sigdigest.decode()

def kraken_request(uri_path, data, api_key, api_sec):
    headers = {}
    data['nonce'] = str(int(1000 * time.time()))
    urlpath = f'/{uri_path}'
    headers['API-Key'] = api_key
    headers['API-Sign'] = get_kraken_signature(urlpath, data, api_sec)
    response = requests.post((API_URL + urlpath), headers=headers, data=data)
    return response.json()

def get_balance():
    data = {}
    response = kraken_request('0/private/Balance', data, API_KEY, API_SECRET)
    if response.get('error'):
        print(f"Error fetching balance: {response['error']}")
        return None
    return response.get('result')

def load_action_from_file():
    try:
        with open("test.json", "r") as file:
            data = json.load(file)
            action = data.get("action")
            price = data.get("price")
            if not action or not price:
                raise ValueError("Invalid or missing 'action' or 'price' in test.json.")
            return action.lower(), float(price)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as e:
        print(f"Error loading test.json: {e}")
        return None, None

def place_limit_order(pair, type, price, volume):
    data = {
        'pair': pair,
        'type': type,
        'ordertype': 'limit',
        'price': price,
        'volume': volume
    }
    response = kraken_request('0/private/AddOrder', data, API_KEY, API_SECRET)
    print(f"Order response: {response}")
    return response

def fetch_current_price(pair):
    response = requests.get(f'{API_URL}/0/public/Ticker', params={'pair': pair})
    result = response.json()
    if result.get('error'):
        print(f"Error fetching price: {result['error']}")
        return None
    current_price = float(result['result'][list(result['result'].keys())[0]]['c'][0])
    print(f"Current market price for {pair}: {current_price}")
    return current_price

def monitor_position_and_sell(buy_price, pair, volume):
    while True:
        # Fetch the current market price
        current_price = fetch_current_price(pair)
        if not current_price:
            time.sleep(2)
            continue

        # Calculate the percentage change
        percentage_change = ((current_price - buy_price) / buy_price) * 100
        print(f"Percentage change: {percentage_change:.2f}%")

        # Check for "sell" action in test.json
        action, _ = load_action_from_file()
        if action == "sell":
            print(f"Action in test.json updated to 'sell'. Selling position at {current_price}")
            response = place_limit_order(pair, "sell", current_price, volume)
            print(f"Sell order response: {response}")

            # Log the transaction
            log_transaction(buy_price, current_price, percentage_change)
            return

        # Execute sell if the percentage change condition is met
        if percentage_change >= 0.72:
            print(f"Target reached! Selling position at {current_price}")
            response = place_limit_order(pair, "sell", current_price, volume)
            print(f"Sell order response: {response}")

            # Log the transaction
            log_transaction(buy_price, current_price, percentage_change)
            return

        # Wait for 2 seconds before the next check
        time.sleep(2)

def monitor_and_execute():
    last_action = None

    # Initialize the Excel sheet
    initialize_excel()

    while True:
        action, limit_price = load_action_from_file()
        if action is None or limit_price is None:
            print("Waiting for valid action in test.json...")
            time.sleep(2)
            continue

        if action != last_action:
            print(f"New action detected: {action}")
            last_action = action

            balance = get_balance()
            if not balance:
                time.sleep(2)
                continue

            usd_balance = float(balance.get('ZUSD', 0))
            eth_balance = float(balance.get('XETH', 0))

            print(f"Available USD balance: {usd_balance}")
            print(f"Available ETH balance: {eth_balance}")

            fee_rate = 0.0  # Example: 0.06% fee
            if action == "buy":
                usable_balance = usd_balance * (1 - fee_rate)
                volume = round(usable_balance / limit_price, 8)
                print(f"Placing buy order for {volume} ETH at a limit price of {limit_price} USD")
                response = place_limit_order('XETHZUSD', action, limit_price, volume)
                if not response.get('error'):
                    print(f"Buy order successful. Monitoring position for a 0.75% gain...")
                    monitor_position_and_sell(limit_price, 'XETHZUSD', volume)
            elif action == "sell":
                usable_eth = eth_balance * (1 - fee_rate)
                volume = round(usable_eth, 8)
                print(f"Placing sell order for {volume} ETH at a limit price of {limit_price} USD")
                response = place_limit_order('XETHZUSD', action, limit_price, volume)
                print(f"Sell order response: {response}")

        time.sleep(2)

if __name__ == "__main__":
    monitor_and_execute()
