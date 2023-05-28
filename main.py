import threading
from config import account, password, server, symbols, timeframe, lot, from_data, to_data, deviation, magic1, magic2, tp_pips, atr_sl_multiplier, atr_period, max_dist_atr_multiplier, trail_atr_multiplier, webhook_url
from meta_bot import MT5Connector, MarketStatus, Messenger
from bot import Bot
import time
import keyboard

# Create an instance of MT5Connector and MarketStatus
connector = MT5Connector(account=account, password=password, server=server)
market_status = MarketStatus(connector)

messenger = Messenger(webhook_url)

# Variable to check if the "Market is closed" message was already printed
market_closed_message_printed = False

# Variable to keep track if threads should be killed
kill_threads = False

# Function to capture key presses
def key_capture_thread():
    global kill_threads
    keyboard.wait('esc')
    kill_threads = True

# Start key capture thread
key_thread = threading.Thread(target=key_capture_thread)
key_thread.start()
print('Press ESC to Terminate Tracy..')

# Keep checking until the market is open and connection is successful
while True:
    if market_status.is_market_open:
        print("--------------------")
        connector.connect()
        if connector.is_connected:
            print("----------------------------------")
            print("Successfully initialized to MT5.")
            break
        else:
            print("----------------------------")
            print("Failed to initialize to MT5. Retrying in 10 seconds.")
            time.sleep(10)
    else:
        if not market_closed_message_printed:
            print("--------------------")
            print('Market is closed')
            messenger.send('Market is closed')
            market_closed_message_printed = True
        time.sleep(10)

    if kill_threads:
        print("--------------------")
        print("Tracy Terminated...")
        exit()

# Create Bots instance
bots = [Bot(connector, market_status, symbol, timeframe, from_data, to_data, lot, deviation, magic1, magic2, tp_pips, atr_sl_multiplier, atr_period, max_dist_atr_multiplier, trail_atr_multiplier, webhook_url) for symbol in symbols]

print("----------------------------------")
print('Running.........')
print('Strategy: London Break ')

# Create and start a new thread for each bot
threads = []
for bot in bots:
    bot_thread = threading.Thread(target=bot.run)
    bot_thread.start()
    threads.append(bot_thread)

# Join the threads
for thread in threads:
    thread.join()
