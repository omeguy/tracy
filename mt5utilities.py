import MetaTrader5 as mt5
from datetime import datetime
import numpy as np
import pandas as pd
import requests
import json

import random
import schedule
import time
import logging


class MT5Connector:
    def __init__(self, account, password, server, logger=None):
        self.account = account
        self.password = password
        self.server = server
        self.is_connected = False
        self.logger = logger if logger else logging.getLogger()

    def connect(self, max_retries=3):
        for i in range(max_retries):
            try:
                is_initialized = mt5.initialize()
                if not is_initialized:
                    self.logger.error(f"Attempt {i+1}/{max_retries}: MT5 initialization failed.")
                    continue

                authorized = mt5.login(self.account, self.password, self.server)
                if not authorized:
                    error_code, error_message = mt5.last_error()
                    self.logger.error(f"Attempt {i+1}/{max_retries}: MT5 login failed. Error code: {error_code}, message: '{error_message}'")
                    continue

                self.is_connected = True
                self.logger.info("Connected to MT5 server successfully.")
                return True
            except Exception as e:
                self.logger.error(f"Attempt {i+1}/{max_retries}: Unexpected error during connection: {e}")

        self.is_connected = False
        self.logger.error("Failed to connect to MT5 server after all retries.")
        return False

    def disconnect(self):
        if self.is_connected:
            mt5.shutdown()
            self.is_connected = False
            self.logger.info("Disconnected from MT5")


class DataFetcher:
    def __init__(self, mt5_connector, symbol, timeframe, from_data, to_data, logger=None):
        self.mt5_connector = mt5_connector
        self.symbol = symbol
        self.timeframe = timeframe
        self.from_data = from_data
        self.to_data = to_data
        self.logger = logger if logger else logging.getLogger()

    def fetch(self):
        try:
            data = pd.DataFrame(mt5.copy_rates_from_pos(self.symbol, self.timeframe, self.from_data, self.to_data))
            if data.empty:
                # Using mt5.last_error() to log the reason for not returning data
                error_code, error_message = mt5.last_error()
                self.logger.warning(f"[{datetime.now()}] No data returned for {self.symbol}. Error code: {error_code}, message: '{error_message}'")
                return None  # Indicating no data was returned
            self.logger.info(f"[{datetime.now()}] Data fetched successfully for {self.symbol}.")
            return data  # Directly return the data
        except Exception as e:
            error_code, error_message = mt5.last_error()
            self.logger.error(f"[{datetime.now()}] Failed to fetch data for {self.symbol}: {e}, MT5 Error code: {error_code}, message: '{error_message}'")
            return None  # Indicating an exception occurred

    def get_current_price(self):
        try:
            # Fetch the last candle data
            # Adjust '0' to '1' if you want just the last candle
            data = pd.DataFrame(mt5.copy_rates_from_pos(self.symbol, self.timeframe, 0, 1))
            if not data.empty:
                # Extract the close price of the last candle
                current_price = data.iloc[-1]['close']
                self.logger.info(f"Current close price for {self.symbol}: {current_price}")
                return current_price
            else:
                # If no data is returned, log the issue and return None
                self.logger.warning(f"No data returned for the last candle of {self.symbol}.")
                return None
        except Exception as e:
            # If an exception occurs, log the error and return None
            error_code, error_message = mt5.last_error()
            self.logger.error(f"Failed to fetch the last candle for {self.symbol}: {e}, MT5 Error code: {error_code}, message: '{error_message}'")
            return None

    def get_tick(self):
            """
            Fetches the latest tick for the symbol and returns the ask price.
            """
            try:
                tick = mt5.symbol_info_tick(self.symbol)
                if tick is not None:
                    self.logger.info(f"Latest tick for {self.symbol} fetched successfully.")
                    return tick.ask  # Return the ask price from the latest tick
                else:
                    self.logger.warning(f"Failed to fetch latest tick for {self.symbol}.")
                    return None
            except Exception as e:
                self.logger.error(f"Exception occurred while fetching tick for {self.symbol}: {e}")
                return None


class MarketOrder:
    def __init__(self, symbol, lot, deviation, magic, trade_type, stop_loss, take_profit=None, logger=None):
        self.symbol = symbol
        self.lot = lot
        self.deviation = deviation
        self.magic = magic
        self.trade_type = trade_type  # For opening, 0 for buy, 1 for sell
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.logger = logger if logger else logging.getLogger()

    def execute_open(self):
        trade_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": self.lot,
            "type": self.trade_type,
            "price": mt5.symbol_info_tick(self.symbol).ask if self.trade_type == 0 else mt5.symbol_info_tick(self.symbol).bid,
            "sl": self.stop_loss,
            "tp": self.take_profit,
            "deviation": self.deviation,
            "magic": self.magic,
            "comment": "Buy" if self.trade_type == 0 else "Sell",
            "type_time": mt5.ORDER_TIME_GTC,
            "filling_type": mt5.ORDER_FILLING_IOC,
        }
        
        return self._send_order(trade_request)

    def execute_close(self, ticket):
        # For closing, the type should be opposite to the opening type
        close_type = mt5.ORDER_TYPE_SELL if self.trade_type == 0 else mt5.ORDER_TYPE_BUY
        trade_request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": self.lot,
            "type": close_type,
            "position": ticket,
            "deviation": self.deviation,
            "magic": self.magic,
            "comment": "Close",
            "type_time": mt5.ORDER_TIME_GTC,
            "filling_type": mt5.ORDER_FILLING_IOC,
        }

        return self._send_order(trade_request)
    
    def update_position(self, ticket, new_stop_loss=None, new_take_profit=None):
        """
        Updates the stop loss and/or take profit levels for an existing position.
        """
        trade_request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "ticket": ticket,
            "symbol": self.symbol,
            "sl": new_stop_loss,
            "tp": new_take_profit,
            "magic": self.magic,
            "comment": "Update SL/TP",
        }

        # Use the _send_order utility function to send the update request
        return self._send_order(trade_request)

    def _send_order(self, trade_request):
        try:
            result = mt5.order_send(trade_request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                self.logger.error(f"[{datetime.now()}] Failed to send order for {self.symbol}. Retcode: {result.retcode}, Comment: '{result.comment}', Request: {trade_request}")
                return None  # Indicate failure
            self.logger.info(f"[{datetime.now()}] Order sent successfully for {self.symbol}, ticket: {result.order}")
            return result  # Return the result on success
        except Exception as e:
            self.logger.error(f"[{datetime.now()}] Exception while sending order for {self.symbol} - {e}")
            return None


class IndicatorCalculator:
    def __init__(self, data_fetcher):
        self.data_fetcher = data_fetcher

    def calculate_atr(self, period):
        # Fetch the data
        self.data_fetcher.fetch()
        data = self.data_fetcher.data
        # Calculate the true range
        data['high_low'] = data['high'] - data['low']
        data['high_close'] = np.abs(data['high'] - data['close'].shift())
        data['low_close'] = np.abs(data['low'] - data['close'].shift())
        data['tr'] = data[['high_low', 'high_close', 'low_close']].max(axis=1)

        # Calculate the ATR
        data['atr'] = data['tr'].rolling(period).mean()

        return data['atr'].iloc[-1]

    # Add other indicator calculation methods here


class OpenPositionManager:
    def __init__(self, connector, symbol, timeframe, from_data, to_data, atr_period, max_dist_atr_multiplier, atr_sl_multiplier, trail_atr_multiplier, logger=None):
        self.connector = connector
        self.symbol = symbol
        self.timeframe = timeframe
        self.from_data = from_data
        self.to_data = to_data
        self.atr_period = atr_period
        self.max_dist_atr_multiplier = max_dist_atr_multiplier
        self.atr_sl_multiplier = atr_sl_multiplier
        self.trail_atr_multiplier = trail_atr_multiplier
        self.indicator_calculator = IndicatorCalculator(DataFetcher(connector, symbol, timeframe, from_data, to_data))
        self.logger = logger if logger else logging.getLogger(__name__)

    def get_positions(self):
        try:
            positions_raw = mt5.positions_get(symbol=self.symbol)
            if positions_raw is None or len(positions_raw) == 0:
                self.logger.info(f"No open positions found for symbol: {self.symbol}")
                return pd.DataFrame()  # Return an empty DataFrame if no positions are found

            # Convert the obtained data to a pandas DataFrame
            positions_df = pd.DataFrame(list(positions_raw), columns=positions_raw[0]._asdict().keys())
            self.logger.info(f"Retrieved {len(positions_df)} open positions for symbol: {self.symbol}")
            return positions_df
        except Exception as e:
            self.logger.error(f"Failed to retrieve open positions for symbol: {self.symbol}. Error: {e}")
            return pd.DataFrame()  # Return an empty DataFrame in case of an error

    def calculate_atr_trailing_stop(self, position):
        try:
            # Extract position data
            order_type = position[5]
            price_current = position[13]
            sl = position[11]
            ticket = position[7]

            dist_from_sl = abs(round(price_current - sl, 6))
            if dist_from_sl > self.max_dist_atr_multiplier:
                new_sl = sl + self.trail_atr_multiplier if order_type == 0 else sl - self.trail_atr_multiplier
                request = {
                    'action': mt5.TRADE_ACTION_SLTP,
                    'position': ticket,
                    'sl': new_sl,
                }
                result = mt5.order_send(request)
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    self.logger.info(f"Successfully updated trailing stop for position {ticket}.")
                else:
                    self.logger.error(f"Failed to update trailing stop for position {ticket}. Error code: {result.retcode}")
                return result
            else:
                self.logger.info(f"No trailing stop update needed for position {ticket}.")
                return None
        except Exception as e:
            self.logger.error(f"Exception in calculate_atr_trailing_stop: {e}")
            return None

    def calculate_manual_stop(self, position):
        try:
            # Extract position data
            order_type = position[5]
            price_open = position[10]
            sl = position[11]
            ticket = position[7]

            if sl == 0.0:  # Check if there's no SL already set
                new_sl = price_open - self.atr_sl_multiplier if order_type == 0 else price_open + self.atr_sl_multiplier
                request = {
                    'action': mt5.TRADE_ACTION_SLTP,
                    'position': ticket,
                    'sl': new_sl,
                }
                result = mt5.order_send(request)
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    self.logger.info(f"Successfully set manual stop for position {ticket}.")
                else:
                    self.logger.error(f"Failed to set manual stop for position {ticket}. Error code: {result.retcode}")
                return result
            else:
                self.logger.info(f"Manual stop already set for position {ticket}.")
                return None
        except Exception as e:
            self.logger.error(f"Exception in calculate_manual_stop: {e}")
            return None


class TradeHistory:
    def __init__(self, mt5_connector, symbol, logger=None):
        self.mt5_connector = mt5_connector
        self.symbol = symbol
        self.logger = logger if logger else logging.getLogger(__name__)

    def get_history(self, ticket):
        try:
            # Get the history orders within the specified interval
            history_orders = mt5.history_orders_get(ticket=ticket, group=self.symbol)
            
            if history_orders is None or len(history_orders) == 0:
                self.logger.info(f"No history orders are found for {self.symbol} within the specified interval")
                return pd.DataFrame()  # return empty dataframe
            else:
                # Convert the obtained data to pandas dataframe
                df = pd.DataFrame(list(history_orders), columns=history_orders[0]._asdict().keys())
                df.sort_values(by=['time_done'], inplace=True, ascending=True)
                self.logger.info(f"Successfully retrieved history orders for {self.symbol}.")
                return df
        except Exception as e:
            self.logger.error(f"Exception when retrieving history orders for {self.symbol}: {e}")
            return pd.DataFrame()  # return empty dataframe in case of exception


class Messenger:
    def __init__(self, webhook_url, username='Tracy', logger=None):
        self.webhook_url = webhook_url
        self.username = username
        self.logger = logger if logger else logging.getLogger(__name__)

    def send(self, content):
        data = {
            "content": content,
            "username": self.username
        }
        try:
            response = requests.post(
                self.webhook_url, data=json.dumps(data),
                headers={'Content-Type': 'application/json'}
            )
            if response.status_code == 204:
                self.logger.info(f"Message successfully sent to {self.webhook_url}.")
            else:
                self.logger.error(f"Failed to send message to {self.webhook_url}. "
                                  f"Status code: {response.status_code}, "
                                  f"Response: {response.text}")
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Exception occurred when sending message to {self.webhook_url}: {e}")
     

