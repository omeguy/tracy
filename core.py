import threading
import time
import keyboard
import config as cfg
import mt5utilities as util
from bot import Bot
import logging
from datetime import datetime
import json
import random
import schedule
import MetaTrader5 as mt5


class AppLogger:
    def __init__(self, logger_name, log_file, level=logging.INFO):
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(level)

        # Create formatter to include file name and line number
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s')

        # File handler
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        file_handler.setLevel(level)  # Set file handler level to INFO or as specified

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        console_handler.setLevel(level)  # Set console handler level to INFO or as specified

        # Add handlers to the logger
        if not self.logger.handlers:  # Avoid adding handlers multiple times
            self.logger.addHandler(file_handler)
            self.logger.addHandler(console_handler)

    def get_logger(self):
        return self.logger


class ConfigManager:
    def __init__(self, config_file, logger):
        self.config_file = config_file
        self.logger = logger
        self.config = self.load_config()
        self.prepare_config()

    def load_config(self):
        """Load the configuration file."""
        try:
            with open(self.config_file, "r") as file:
                config = json.load(file)
                self.logger.info("Successfully loaded configurations.")
                return config
        except Exception as e:
            self.logger.error(f"Failed to load configuration: {e}")
            return None

    def prepare_config(self):
        """Prepare and convert config fields as necessary."""
        if self.config:
            # Convert timeframe
            timeframe_str = self.config.get("trading_config", {}).get("timeframe")
            converted_timeframe = self.convert_timeframe(timeframe_str)
            if converted_timeframe is not None:
                self.config["trading_config"]["timeframe"] = converted_timeframe
            else:
                self.logger.error(f"Unknown timeframe specified: {timeframe_str}")

    def convert_timeframe(self, timeframe_str):
        """Convert a timeframe string to the corresponding MT5 constant."""
        timeframe_mapping = {
            "TIMEFRAME_M1": mt5.TIMEFRAME_M1,
            "TIMEFRAME_M5": mt5.TIMEFRAME_M5,
            "TIMEFRAME_M15": mt5.TIMEFRAME_M15,
            "TIMEFRAME_M30": mt5.TIMEFRAME_M30,
            "TIMEFRAME_H1": mt5.TIMEFRAME_H1,
            "TIMEFRAME_H4": mt5.TIMEFRAME_H4,
            "TIMEFRAME_D1": mt5.TIMEFRAME_D1,
            "TIMEFRAME_W1": mt5.TIMEFRAME_W1,
            "TIMEFRAME_MN1": mt5.TIMEFRAME_MN1,
        }

        return timeframe_mapping.get(timeframe_str)

    def get_config(self):
        """Return the prepared configuration."""
        return self.config

class KeyCapture:
    def __init__(self):
        self.esc_pressed = False
        self.listen_thread = threading.Thread(target=self.listen_for_esc, daemon=True)
        self.listen_thread.start()

    def listen_for_esc(self):
        """Thread function to listen for ESC key press."""
        keyboard.wait('esc')
        self.esc_pressed = True

    def esc_pressed_check(self):
        """Check if ESC has been pressed."""
        if self.esc_pressed:
            return True
        return False
    


class ThreadManager:
    def __init__(self, logger):
        self.threads = []
        self.logger = logger
        self.stop_signal = threading.Event()  # Shared stop signal for all threads


    def create_thread(self, target, args=(), name=None):
        """
        Create and start a new thread.
        :param target: The function that the thread will execute.
        :param args: The arguments to pass to the target function.
        :param name: Optional name for the thread.
        :return: The created thread object.
        """
        # Note: Ensure 'target' function checks 'self.stop_signal' periodically.

        try:
            thread_name = name or target.__name__ if hasattr(target, '__name__') else str(target)
            thread = threading.Thread(target=target, args=args, name=thread_name)
            self.logger.info('Starting thread')
            thread.start()
            self.threads.append(thread)
            self.logger.info("-------------------------------------------------")
            self.logger.info(f"Thread '{thread_name}' started successfully with args: {args}")
            return thread
        except Exception as e:
            self.logger.info("-------------------------------------------------")
            self.logger.error(f"Error creating or starting thread: {e}")
            return None

    def stop_threads(self):
        """
        Request all threads managed by this ThreadManager to stop.
        """
        self.stop_signal.set()  # Signal all threads to stop
        for thread in self.threads:
            thread.join()  # Wait for threads to finish
        self.logger.info("-------------------------------------------------")
        self.logger.info("All threads have been requested to stop.")

    def monitor_threads(self):
        """
        Monitor the status of threads and remove any that have completed.
        """
        active_threads = [thread for thread in self.threads if thread.is_alive()]
        if len(active_threads) < len(self.threads):
            completed_threads = len(self.threads) - len(active_threads)
            self.logger.info(f"Removed {completed_threads} completed thread(s) from management.")
        self.threads = active_threads


class MarketStatus:
    def __init__(self):
        self.is_market_open = False  # Initially set to False
        self.update_market_status()  # Update the market status immediately

    def check_market_open(self):
        # Check if the market is open
        current_time = datetime.utcnow()
        current_day_of_week = current_time.weekday()
        current_hour = current_time.hour

        # if friday and time is past 10pm
        if current_day_of_week == 4 and current_hour > 22:
            return False
        
        # If it's Saturday (5) or Sunday (6), the market is closed
        if current_day_of_week == 5 or (current_day_of_week == 6 and current_hour < 23):
            return False

        # Otherwise, the market is open
        return True

    def update_market_status(self):
        # Update the market status
        self.is_market_open = self.check_market_open()
       


class TradeEngine:
    def __init__(self, mt5_connector, market_status, config, messenger, inspirer, logger, thread_manager):
        self.connector = mt5_connector
        self.market_status = market_status
        self.config = config  
        self.messenger = messenger
        self.inspirer = inspirer
        self.logger = logger
        self.thread_manager = thread_manager
        self.market_open_message_printed = False
        self.market_closed_message_printed = False
        self.bots = []

        self.key_capture = KeyCapture()
        self.kill_threads = False  # Flag to control the main loop

        # Retry parameters
        self.max_retries = 3  # Maximum number of retries
        self.retry_delay = 10  # Delay between retries in seconds
        self.logger.info("-------------------------------------------------")
        self.logger.info(f"TradeEngine initialized")


    
    def start(self):
        # Start the market monitoring in a separate thread
        self.thread_manager.create_thread(target=self.monitor_and_update_market_status)
        self.logger.info("-------------------------------------------------")
        self.logger.info(f"TradeEngine Started")


    def monitor_and_update_market_status(self):
        try:
            while not self.kill_threads:
                self.market_status.update_market_status()
                if self.market_status.is_market_open:
                    self.handle_market_open()
                else:
                    self.handle_market_close()
                time.sleep(10)  # Check market status every 10 seconds
        except Exception as e:
            self.logger.info("-------------------------------------------------")
            self.logger.error(f"Error in monitor_and_update_market_status: {e}")
            # Handle the error or decide to retry, log, etc.

    def handle_market_open(self):
        if not self.market_open_message_printed:
            self.messenger.send('Market is open.. 🎉')
            self.inspirer.send_message('open')
            self.logger.info("-------------------------------------------------")
            self.logger.info("Market is open")
            self.market_open_message_printed = True
            self.market_closed_message_printed = False
            self.connect_to_market()

    def connect_to_market(self):
        self.logger.info("-------------------------------------------------")
        self.logger.info("Attempting to connect to MT5.")
        for attempt in range(self.max_retries):
            try:
                self.connector.connect()
                if self.connector.is_connected:
                    self.logger.info("-------------------------------------------------")
                    self.logger.info("Successfully initialized to MT5.")
                    self.create_bots()
                    return True
            except Exception as e:
                self.logger.info("-------------------------------------------------")
                self.logger.info(f"Failed to initialize to MT5 on attempt {attempt + 1}: {e}. Retrying in {self.retry_delay} seconds.")
                time.sleep(self.retry_delay)
        self.logger.info("-------------------------------------------------")
        self.logger.error("Failed to initialize to MT5 after all retries.")
        return False
    
    def disconnect_from_market(self):
        if self.connector.is_connected:
            self.connector.disconnect()
            self.logger.info("-------------------------------------------------")
            self.logger.info("Disconnected from MT5.")

    def handle_market_close(self):
        if not self.market_closed_message_printed:
            self.logger.info("-------------------------------------------------")
            self.logger.info('Market is closed.')
            self.messenger.send('Market is closed 😴')
            self.inspirer.send_message('close')
            self.market_closed_message_printed = True
            self.market_open_message_printed = False
            self.stop_bots()
            self.disconnect_from_market()

    def create_bots(self):
        """Create and start bot instances for each trading symbol specified in the configuration, using the ThreadManager for thread handling and tracking."""
        if not self.connector.is_connected:
            self.logger.info("-------------------------------------------------")
            self.logger.error("MT5 connector is not connected. Cannot create bots.")
            return
        
        self.logger.info("-------------------------------------------------")
        self.logger.info("Creating trading bots for each symbol...")

        # Clear existing bots list to avoid duplicates if method is called again
        self.bots = []
        self.threads = []  # Initialize or clear the threads list

        for symbol in self.config['trading_config']['symbols']:
            try:
                bot = Bot(
                    mt5_connector=self.connector,
                    market_status=self.market_status,
                    symbol=symbol, 
                    timeframe=self.config['trading_config']['timeframe'], 
                    from_data=self.config['date_range']['from_data'], 
                    to_data=self.config['date_range']['to_data'], 
                    lot=self.config['trading_config']['lot'], 
                    deviation=self.config['trading_config']['deviation'], 
                    magic1=self.config['strategy_params']['magic_numbers']['magic1'], 
                    magic2=self.config['strategy_params']['magic_numbers']['magic2'], 
                    magic3=self.config['strategy_params']['magic_numbers']['magic3'], 
                    tp_pips=self.config['strategy_params']['tp_pips'], 
                    atr_sl_multiplier=self.config['strategy_params']['atr_sl_multiplier'], 
                    atr_period=self.config['strategy_params']['atr_period'], 
                    max_dist_atr_multiplier=self.config['strategy_params']['max_dist_atr_multiplier'], 
                    trail_atr_multiplier=self.config['strategy_params']['trail_atr_multiplier'], 
                    pip_range=self.config['trading_config']['pip_range'],
                    webhook_url=self.config['details']['webhook_url']
                )
                self.bots.append(bot)
                self.logger.info("-------------------------------------------------")
                self.logger.info(f"Created bot for {symbol}.")

                # Use ThreadManager to manage the bot's thread and append the thread reference to the list
                thread = self.thread_manager.create_thread(target=bot.run, name=f"BotThread-{symbol}")
                if thread is not None:
                    self.logger.info("-------------------------------------------------")
                    self.logger.info(f"{thread.name}: Trading.....")
                else:
                    self.logger.info("-------------------------------------------------")
                    self.logger.error(f"Failed to start thread for bot {symbol}.")
            except Exception as e:
                self.logger.info("-------------------------------------------------")
                self.logger.error(f"Failed to create bot for {symbol}: {str(e)}")



    def stop_bots(self):
        """Signals all bots to stop and waits for their threads to finish."""
        self.logger.info("-------------------------------------------------")
        self.logger.info("Stopping all bots...")

        # Check if bots and threads lists are initialized and not empty
        if not hasattr(self, 'bots') or not self.bots:
            self.logger.info("No bots was initialized.")
        else:
            # Signal each bot to stop, safely checking for initialization
            for bot in self.bots:
                if bot:  # Assuming 'None' or similar checks are adequate to determine initialization
                    bot.stop()

        if not hasattr(self, 'threads') or not self.threads:
            self.logger.info("No bot threads have been initialized.")
        else:
            # Wait for all threads to finish, safely checking for initialization
            for thread in self.threads:
                if thread:  # Similarly, ensure the thread is properly initialized
                    thread.join()  # Assuming these are threading.Thread objects or have a similar join method
                else:
                    self.logger.info("A thread was not initialized. Skipping join.")
            
        self.logger.info("-------------------------------------------------")
        self.logger.info("System deinitialized.")
        self.logger.info("Waiting for market to open.....")


    
    
class InspireTraders:
    def __init__(self, messenger, json_file, schedules=None):
  
        self.messenger = messenger
        self.kill_threads = False
        self.json_file = json_file
        self.schedules = schedules

    def get_random_message(self, key):
        with open(self.json_file, 'r', encoding='utf-8') as file:  # add encoding parameter here
            data = json.load(file)
        return random.choice(data[key])

    def send_message(self, key):
        message = self.get_random_message(key)
        self.messenger.send(message)
        print(f"{message} (Inspiring message sent!)")

    def run(self):
        self.logger.info("-------------------------------------------------")
        self.logger.info("InspireTraders thread started...")
        for schedule_time, key in self.schedules:
            schedule.every().day.at(schedule_time).do(self.send_message, key)
        while not self.kill_threads[0]:
            schedule.run_pending()
            time.sleep(1)
        self.logger.info("-------------------------------------------------")
        self.logger.info("InspireTraders thread stopped.")