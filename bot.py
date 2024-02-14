import MetaTrader5 as mt5
import mt5utilities as util
import config as cfg
from db_manager import DatabaseManager
from datetime import datetime, timedelta
import time
import logging
import traceback
import position as pos

class Bot:
    def __init__(self, mt5_connector, market_status, symbol, timeframe, from_data, to_data, lot, deviation, magic1, magic2, magic3, tp_pips, atr_sl_multiplier, atr_period, max_dist_atr_multiplier, trail_atr_multiplier, webhook_url, pip_range, logger=None):
        self.mt5_connector = mt5_connector
        self.market_status = market_status
        self.symbol = symbol
        self.timeframe = timeframe
        self.from_data = from_data
        self.to_data = to_data
        self.lot = lot
        self.deviation = deviation
        self.magic1 = magic1
        self.magic2 = magic2
        self.magic3 = magic3
        self.tp_pips = tp_pips
        self.atr_sl_multiplier = atr_sl_multiplier
        self.atr_period = atr_period
        self.max_dist_atr_multiplier = max_dist_atr_multiplier
        self.trail_atr_multiplier = trail_atr_multiplier
        self.webhook_url = webhook_url
        self.should_stop = False
        self.positions = {}
        self.retracement_trade_executed = False

        self.level_broken = False
        self.pip_range = pip_range


        self.username = 'Tracy'
        self.box = None
        self.daily_trade_info = None


        self.retracment_notice = False


        #initialize data fetcher
        self.data_fetcher = util.DataFetcher(mt5_connector, symbol, timeframe, from_data, to_data)

        #initialize position manager
        self.position_manager = util.OpenPositionManager(mt5_connector, self.symbol, self.timeframe, self.from_data, self.to_data, self.atr_period, self.max_dist_atr_multiplier, self.atr_sl_multiplier, self.trail_atr_multiplier)

        #initialize Messanger
        self.messanger = util.Messenger(self.webhook_url, self.username)

        self.trade_history = util.TradeHistory(mt5_connector, self.symbol)

        #initialize flags
        self.box_calculated = False
        self.levels_calculated = False
        self.trade_executed = False
        self.trading_notification = False
        self.trade_signal_notification = False
        self.position_manager_nofitication = False

        self.daily_data_reset = False

        self.db_manager = DatabaseManager('trades.db')

        self.positions_loaded = False

        # Configure the logger
        self.logger = logger if logger else logging.getLogger()

        # Define the schema for your opened_trades table, now with added fields
        opened_trade_schema = """
            date_time_open TEXT NOT NULL,
            ticket_id INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL,
            trade_type TEXT NOT NULL,
            open_price REAL NOT NULL,
            magic_number INTEGER NOT NULL,
            lot REAL NOT NULL,
            stop_loss REAL,  -- Added field for stop loss
            take_profit REAL,  -- Added field for take profit
            deviation REAL,  -- Added field for deviation
            status BOOLEAN NOT NULL,
            date_time_close TEXT,
            close_price REAL,
            profit_loss REAL
        """

        # Create the table in the database
        self.db_manager.create_table('opened_trade', opened_trade_schema)

        # Define the schema for your closed_trades table, now with added fields
        closed_trade_schema = """
            ticket_id INTEGER PRIMARY KEY,
            symbol TEXT NOT NULL,
            trade_type TEXT NOT NULL,
            open_price REAL NOT NULL,
            open_time TEXT NOT NULL,
            close_price REAL NOT NULL,
            close_time TEXT NOT NULL,
            profit_loss REAL NOT NULL,
            magic_number INTEGER NOT NULL,
            lot REAL NOT NULL,
            stop_loss REAL,  -- Added field for stop loss
            take_profit REAL,  -- Added field for take profit
            deviation REAL,  -- Added field for deviation
            status BOOLEAN NOT NULL
        """

        # Create the table in the database
        self.db_manager.create_table('closed_trade', closed_trade_schema)

        self.logger.info('initaallalalallalalalalalallalalalalala')

    def calculate_box(self):
        # Attempt to fetch historical data
        try:
            data = self.data_fetcher.fetch()  # Ensure this method returns the data directly
        except Exception as e:
            self.logger.error(f"Failed to fetch data: {self.symbol}: {e}")
            return

        # Validate the fetched data
        if data is None or data.empty:
            self.logger.info(f"No data fetched or data is empty: {self.symbol}")
            return
        if not {'high', 'low', 'open', 'close'}.issubset(data.columns):
            self.logger.error(f"Data does not contain required 'high', 'low', 'open', and 'close' columns for {self.symbol}")
            return

        # Calculate the effective high and low by considering the max/min of open/close
        effective_high = data['close'].max()
        effective_low = data['close'].min()
        box_height = effective_high - effective_low

        # Handle scenarios where box height is zero or data is not valid
        if box_height <= 0:
            self.logger.info(f"Box height is zero or negative: {self.symbol}, indicating no volatility or erroneous data.")
            return
        
        # Store the calculated levels in the box dictionary
        self.box = {
            'buy_level': effective_high,
            'sell_level': effective_low,
            'buy_stoploss': effective_low,
            'sell_stoploss': effective_high,
            'box_height': box_height
        }

        self.logger.info(f"Box levels calculated using effective high and low: {self.symbol}: {self.box}")



    def calculate_levels(self):
        # Check if the box has already been calculated
        if not self.box_calculated:
            self.logger.info("----------------------------------------------")
            self.logger.info(f"Initiating box level calculation: {self.symbol}.")

            # Directly call calculate_box to attempt box calculation
            self.calculate_box()

            # After attempting to calculate the box, check if it was successfully calculated
            if self.box:  # Assuming self.box is populated by calculate_box on success
                self.box_calculated = True
                self.logger.info(f"Box levels calculated successfully: {self.symbol}.")
            else:
                self.logger.warning(f"Box level calculation failed or returned empty: {self.symbol}. Box calculation may not proceed without valid data.")
        else:
            self.logger.info(f"Box levels already calculated: {self.symbol}, no need to recalculate.")

    
    def check_for_break(self):
        # Ensure the box has been calculated before checking for a breakout
        if not self.box or 'buy_level' not in self.box or 'sell_level' not in self.box:
            self.logger.error(f"Box levels not calculated or are incomplete: {self.symbol}. Cannot check for breakout.")
            return None, None

        # Fetch the current price using DataFetcher
        current_price = self.data_fetcher.get_current_price()

        # Check if the current price could be fetched
        if current_price is None:
            self.logger.error("Failed to fetch current price: {self.symbol}.")
            return None, None

        # Check if the price has broken out of the box
        if current_price > self.box['buy_level']:
            self.logger.info("----------------------------------------------")
            self.logger.info(f"Breakout detected: {self.symbol} - price has gone above the buy level ({self.box['buy_level']}).")
            return 0, current_price  # 0 for buy trade
        elif current_price < self.box['sell_level']:
            self.logger.info("----------------------------------------------")
            self.logger.info(f"Breakout detected: {self.symbol} - price has gone below the sell level ({self.box['sell_level']}).")
            return 1, current_price  # 1 for sell trade
        else:
            # Log when current price is within the box levels but no breakout occurred
            return None, current_price

    
    def should_trade(self, trade_type, current_price):
        # Ensure box has been calculated and pip_range is defined
        if not self.box or 'buy_level' not in self.box or 'sell_level' not in self.box:
            self.logger.error(f"Box levels not calculated or are incomplete: {self.symbol}. Cannot determine if should trade.")
            return False

        try:
            # Determine the relevant breakout level based on the trade type
            if trade_type == 0:  # For buy trades
                breakout_level = self.box['buy_level']
                # Check if the current price is within pip_range above the breakout level
                return breakout_level <= current_price <= breakout_level + cfg.pip_range

            elif trade_type == 1:  # For sell trades
                breakout_level = self.box['sell_level']
                # Check if the current price is within pip_range below the breakout level
                return breakout_level - self.pip_range <= current_price <= breakout_level

        except Exception as e:
            self.logger.error(f"Error evaluating should_trade: {self.symbol}: {e}")
            return False

        # Log if trade_type is not recognized
        self.logger.warning(f"Unrecognized trade type ({trade_type}): {self.symbol}.")
        return False



    def check_for_retracement(self):
        # Check if the initial breakout trade has been executed
        # and if the retracement trade has not been executed
        if not self.trade_executed or self.retracement_trade_executed:
            return
        
        if not self.retracment_notice:
            self.logger.info("-------------------------------------------------")
            self.logger.info(f"{self.symbol}: waiting for retracement!!!")
            self.retracment_notice = True

           # Check if the box levels are properly defined
        if not self.box or 'buy_level' not in self.box or 'sell_level' not in self.box:
            self.logger.error(f"Box levels not defined: {self.symbol}. Cannot check for retracement.")
            return
        
        # Calculate 50% retracement level
        retracement_level = (self.box['buy_level'] + self.box['sell_level']) / 2

        # Get the last candle's close price as the current price
        current_price = self.data_fetcher.get_current_price()

        # Validate that current price was successfully fetched
        if current_price is None:
            self.logger.error(f"Failed to fetch current price for retracement check on {self.symbol}.")
            return

        # Check if retracement has occurred
        trade_type = self.daily_trade_info['trade_type']
        if (trade_type == 0 and current_price < retracement_level) or \
        (trade_type == 1 and current_price > retracement_level):
            self.logger.info(f"Retracement detected: {self.symbol}, executing retracement trade.")
            self.execute_retracement_trade()
    

    def execute_retracement_trade(self):
        # Ensure that daily trade info is available and valid
        if not self.daily_trade_info or 'trade_type' not in self.daily_trade_info:
            self.logger.error("Daily trade info is missing or incomplete. Cannot execute retracement trade.")
            return
        
        try:
            # Extract necessary details from daily_trade_info
            trade_type = self.daily_trade_info['trade_type']
            stop_loss = self.daily_trade_info['stop_loss']
            box_size = self.daily_trade_info['box_size']

            # Fetch the current ask or bid price based on the trade type
            current_price = self.data_fetcher.get_tick()

            # Ensure the current price was successfully fetched
            if current_price is None:
                self.logger.error(f"Failed to fetch current tick for {self.symbol}. Cannot execute retracement trade.")
                return

            # Adjust take profit calculation based on the trade type
            take_profit = current_price + box_size if trade_type == 0 else current_price - box_size

            # Initialize and execute the trade using the Position class
            trade = pos.Position(symbol=self.symbol, trade_type=trade_type, lot=self.lot, magic_number=self.magic3,
                                stop_loss=stop_loss, take_profit=take_profit, deviation=self.deviation, logger=self.logger,
                                database_manager=self.database_manager)
            trade_result, position_instance = trade.execute_open()

            self.positions[trade_result] = position_instance


            if trade_result:
                self.logger.info(f"Retracement trade executed successfully: {self.symbol}, ticket ID: {ticket_id}")
                self.retracement_trade_executed = True

                # Now you can use position_instance for further actions, like updating or querying
                # For example, logging additional details about the position
                self.logger.info(f"Position opened with price: {position_instance.open_price} at {position_instance.open_time}")

                return trade_result, position_instance

            else:
                self.logger.error(f"Failed to execute retracement trade: {self.symbol}.")

        except Exception as e:
            self.logger.error(f"Exception occurred while executing retracement trade: {self.symbol}: {e}")

    
    def execute_retest_trade(self):

        if self.level_broken:
            pass


    def attempt_to_execute_trades(self):
            self.logger.info("------------------------------------------------------------------")
            self.logger.info("Waiting to execute trade.")
            self.trading_notification = True

            trade_signal, current_price = self.check_for_break()
            
            if trade_signal is not None:
                self.level_broken = True
                self.logger.info("------------------------------------------------------------------")
                self.logger.info(f'Time(GMT): {time.time()}')
                self.logger.info("----------------------------")
                self.handle_trade_execution(trade_signal, current_price)


    def handle_trade_execution(self, trade_signal, current_price):
            if not self.trade_signal_notification:
                self.logger.info("----------------------------------------------")
                self.logger.info(f'Buy_level broken' if trade_signal == 0 else 'Sell_level broken')
                self.messanger.send(f'Buy_level broken' if trade_signal == 0 else 'Sell_level broken')
                self.logger.info("-------------------------------------")
                self.logger.info("Executing Trade")  
                self.trade_signal_notification = True
                        
                yes_trade = self.should_trade(trade_signal, current_price)

                if yes_trade:
                    # Calculate the take profit based on the box height and trade signal
                    # Fetch the current market price based on trade direction
                    market_price = mt5.symbol_info_tick(self.symbol).ask if trade_signal == 0 else mt5.symbol_info_tick(self.symbol).bid
                    box_take_profit = market_price + self.box['box_height'] if trade_signal == 0 else market_price - self.box['box_height']

                    # Setup trade parameters
                    stop_loss = self.box['buy_stoploss'] if trade_signal == 0 else self.box['sell_stoploss']

                    # Initialize Position for trade execution
                    trade_1 = pos.Position(
                        symbol=self.symbol,
                        trade_type=trade_signal,
                        lot=self.lot,
                        magic_number=self.magic1,
                        stop_loss=stop_loss,
                        take_profit=box_take_profit,
                        deviation=self.deviation,
                        logger=self.logger,
                        database_manager=self.db_manager  # Assuming this is correctly initialized elsewhere
                    )
                    
                    # Execute the trade
                    trade1_result, position_instance1 = trade_1.execute_open()

                    self.positions[trade1_result] = position_instance1

                    trade_2 = pos.Position(
                        symbol=self.symbol,
                        trade_type=trade_signal,
                        lot=self.lot,
                        magic_number=self.magic2,
                        stop_loss=stop_loss,
                        take_profit=0.0,
                        deviation=self.deviation,
                        logger=self.logger,
                        database_manager=self.db_manager  # Assuming this is correctly initialized elsewhere
                    )
                    
                    # Execute the trade
                    trade2_result, position_instance2 = trade_2.execute_open()

                    self.positions[trade2_result] = position_instance2

                    self.trade_executed = True
                    self.logger.info("-------------------------------------")
                    self.logger.info(f'Trade executed: {self.symbol}: {self.trade_executed}')
                    
                    self.daily_trade_info = {
                        'symbol': self.symbol,
                        'trade_type': trade_signal, # 0 for Buy, 1 for Sell
                        'stop_loss': self.box['buy_stoploss'] if trade_signal == 0 else self.box['sell_stoploss'],
                        'box_size': self.box['box_height'],
                    }
                else:
                    # If conditions are not met, log the decision
                    self.logger.info("Trade conditions not met. No trade executed.")  
                    self.messanger.send('Trade condition not met, No trade executed')   

                    
    def manage_positions(self):

        self.reconcile_positions()
        # Loop over all Position instances managed by the bot
        for ticket_id, position in self.positions.items():
            try:
                # Assuming Position objects have attributes like magic_number, take_profit, and methods like calculate_manual_stop, box_trail_stop
                # Check if the magic number is not set
                # if not position.magic_number:
                #     # Directly call method on the Position instance to update the stop loss if needed
                #     update_stop = position.calculate_manual_stop()
                #     if update_stop:
                #         self.logger.info("-------------------------------------------------")
                #         self.logger.info(f"{position.symbol}: stop_loss set.")

                # # Check if take_profit is not zero
                # if position.take_profit != 0.0:
                #     # Directly call method on the Position instance to update the trailing stop
                #     update_result = position.calculate_atr_trailing_stop()
                #     if update_result:
                #         self.logger.info("-------------------------------------------------")
                #         self.logger.info(f"{position.symbol}: ATR-based Position Trailed.")

                # Check if the magic number matches self.magic2 for special trailing stop logic
                if position.magic_number == self.magic2:
                    # Use a specific method for trailing stop if matching a certain magic number
                    update_result = position.box_trail_stop()  # Ensure this method exists within your Position class
                    if update_result:
                        self.logger.info("-------------------------------------------------")
                        self.logger.info(f"{position.symbol}: Position Trailed with box method.")
            
            except Exception as e:
                # Log the exception for debugging
                self.logger.error(f"An error occurred while managing position for {position.symbol}: {e}", exc_info=True)


    def reconcile_positions(self):
        
        # Assuming self.position_manager.get_positions() returns a DataFrame of positions
        mt5_positions_df = self.position_manager.get_positions()

        # Convert the DataFrame to a dictionary with ticket as the key
        # Assuming 'ticket' is a column in your DataFrame
        mt5_positions = {row['ticket']: row for index, row in mt5_positions_df.iterrows()}
                
        # Fetch open positions from the database
        db_positions = self.db_manager.get_data('opened_trade')
        # Assuming the first element in each row is the ticket_id and it uniquely identifies a position
        db_positions_dict = {pos[0]: pos for pos in db_positions}
        
        # Reconcile positions in self.positions with MT5
        self._update_positions_from_mt5(mt5_positions)
        
        # Reconcile positions in self.positions with the database
        self._update_positions_from_db(db_positions_dict)
        

    def _update_positions_from_mt5(self, mt5_positions):
        """
        Reconcile positions based on current MT5 positions.
        """
        for ticket in list(self.positions.keys()):
            if ticket not in mt5_positions:
                # Position closed in MT5 but still in self.positions
                self.logger.info(f"Position {ticket} closed or missing in MT5, reconciling...")
                if ticket in self.positions:
                    # Ensure this position is a Position instance with a reconcile_position method
                    self.positions[ticket].reconcile_position()
                    # After reconciling, remove it from self.positions
                    del self.positions[ticket]


    def _update_positions_from_db(self, db_positions):
        """
        Add missing positions from DB to bot memory.
        """
        for ticket, db_pos in db_positions.items():
            if ticket not in self.positions:
                # Convert db_pos to a Position instance
                # Note: The exact implementation here will depend on how db_positions are structured
                # and how you're retrieving them. This is a conceptual example.
                position_instance = pos.Position.from_db_record(
                    db_pos,
                    logger=self.logger,
                    messanger=None,  # Assuming you have a way to pass a messenger instance if necessary
                    database_manager=self.db_manager
                )
                self.positions[ticket] = position_instance
                self.logger.info(f"Added missing position {ticket} from DB to bot memory.")


    def reset_data(self):
        try:
            if not self.daily_data_reset:
                # Reset the trading data
                self.box = None
                self.daily_trade_info = None

                # Reset flags
                self.data_fetched = False
                self.box_calculated = False
                self.levels_calculated = False
                self.trade_executed = False
                self.trading_notification = False
                self.trade_signal_notification = False
                self.position_manager_notification = False
                self.retracement_trade_executed = False
                self.level_broken = False

                self.daily_data_reset = True

                # Attempt to send a reset message via the messenger
                try:
                    self.messanger.send(f'{self.symbol}: Data reset for today.')
                except Exception as msg_error:
                    self.logger.error(f"Error sending reset message for {self.symbol}: {msg_error}")

                self.logger.info('------------------------------------------------------------')
                self.logger.info(f'{self.symbol}: Data reset for today.')

        except Exception as e:
            self.logger.error(f"An error occurred during data reset for {self.symbol}: {e}")
            # Consider whether to re-raise the exception or handle it to continue execution

    def stop(self):
        self.should_stop = True
        self.logger.info(f"{self.symbol}: Stopping the bot.")

        
    def run(self):
        while not self.should_stop:
            try:
                #-----------------------------------------------
                start_time = time.time()  # Save the start time
                #-----------------------------------------------

                open_positions = self.position_manager.get_positions()
                num_pos_symb = len(open_positions)

                # Update current time each iteration to stay current
                current_time = datetime.utcnow()
                current_hour = current_time.hour

                # Check for daily reset at a specific hour (e.g., 1:00 GMT)
                if current_hour == 1 and not self.daily_data_reset:
                    self.logger.info(f"Initiating daily data reset: {current_time}")
                    self.reset_data()
                    self.daily_data_reset = True  # Ensure this is set to True to prevent multiple resets in a day

                # Check if it's the right time to calculate levels (e.g., between 2:00 GMT and 2:59 GMT)
                if 2 <= current_hour < 3 and not self.levels_calculated:
                    self.logger.info("------------------------------------------------------------------")
                    self.logger.info(f"Time(GMT): {current_time}")
                    self.calculate_levels()
                    self.levels_calculated = True
                    self.logger.info(f"Levels Calculated: {self.symbol}: {self.levels_calculated}")

                if num_pos_symb > 0:
                    
                    if not self.position_manager_nofitication:
                        self.logger.info("----------------------------")
                        self.logger.info('Managing Opened Positions')
                        self.position_manager_nofitication = True
                    #Manage open position
                    self.manage_positions()
    

                # Only check for breakout if levels have been calculated and a trade hasn't been executed yet
                if self.levels_calculated and not self.trade_executed:
                    self.attempt_to_execute_trades()
                         

                # Check if the initial breakout trade has been executed
                # and if the retracement trade has not been executed
                if self.trade_executed and not self.retracement_trade_executed:
                    self.check_for_retracement()
                        
                        

                if current_time.hour == 22 and not self.daily_data_reset:
                    self.reset_data()

                
                
                elapsed_time = time.time() - start_time  # Calculate elapsed time
                if elapsed_time < 55:  # Check if elapsed_time is less than 55 seconds
                    sleep_time = 60 - elapsed_time  # Sleep for the remaining time
                else:  # If execution took longer than 55 seconds
                    sleep_time = 5  # Sleep for at least 5 seconds


                if num_pos_symb > 0:
                    time.sleep(10)  # Sleep for the determined time if theres an open position
                else:
                    time.sleep(sleep_time)

            except Exception as e:
                self.logger.error('An error occurred: %s', e)
                tb = traceback.format_exc()  # Get the traceback
                self.logger.error('An error occurred: %s\n%s', e, tb)  # Log the error and traceback
            # 
                # Optionally, you could re-raise the exception if you want the bot to stop
                # raise e