import MetaTrader5 as mt5
from meta_bot import DataFetcher, MarketOrder, OpenPositionManager, Messenger
from datetime import datetime
import time


class Bot:
    def __init__(self, mt5_connector, market_status, symbol, timeframe, from_data, to_data, lot, deviation, magic1, magic2, tp_pips, atr_sl_multiplier, atr_period, max_dist_atr_multiplier, trail_atr_multiplier, webhook_url):
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
        self.tp_pips = tp_pips
        self.atr_sl_multiplier = atr_sl_multiplier
        self.atr_period = atr_period
        self.max_dist_atr_multiplier = max_dist_atr_multiplier
        self.trail_atr_multiplier = trail_atr_multiplier
        self.webhook_url = webhook_url
        self.username = 'Tracy'
        self.box = None


        #initialize data fetcher
        self.data_fetcher = DataFetcher(mt5_connector, symbol, timeframe, from_data, to_data)

        #initialize position manager
        self.position_manager = OpenPositionManager(mt5_connector, self.symbol, self.timeframe, self.from_data, self.to_data, self.atr_period, self.max_dist_atr_multiplier, self.atr_sl_multiplier)

        #initialize Messanger
        self.messanger = Messenger(self.webhook_url, self.username)

        #initialize flags
        self.data_fetched = False
        self.box_calculated = False
        self.levels_calculated = False
        self.trade_executed = False
        self.trading_notification = False
        self.trade_signal_notification = False
        self.position_manager_nofitication = False

        self.daily_data_reset = False

    def calculate_box(self):
        # Get the historical data
        data = self.data_fetcher.data

        # Check if data is None
        if data is None:
            print("-------------------------------------")
            print(f"No data fetched: {self.symbol}")
            return

        # Calculate the high and low of the box
        high = max(data['high'])
        low = min(data['low'])
        box_height = high - low

        # Store the levels in a dictionary
        self.box = {
            'buy_level': high,
            'sell_level': low,
            'buy_stoploss': low,
            'sell_stoploss': high,
            'box_height': box_height
        }
        print("-------------------------------------")
        print(f"Box_levels: {self.symbol}: {self.box}")

    def calculate_levels(self):  
        # Fetch data
        if not self.data_fetched:
            self.data_fetcher.fetch()
            self.data_fetched = True
            print("----------------------------------------------")
            print(f"Data fetched successfully: {self.symbol}.")
        if self.data_fetched and not self.box_calculated:
            print("----------------------------------------------")
            print(f"calculating box levels: {self.symbol}.")
            # Calculate the box            
            self.calculate_box()
            self.box_calculated = True
    
    def check_for_break(self):

        # Get the current bid and ask prices
        current_bid = mt5.symbol_info_tick(self.symbol).bid
        current_ask = mt5.symbol_info_tick(self.symbol).ask
        # Check if the price has broken out of the box
        if current_ask > self.box['buy_level']:
            print("----------------------------------------------")
            print(f"Breakout detected: {self.symbol} - price has gone above the buy level.")
            return 0
        elif current_bid < self.box['sell_level']:
            print("----------------------------------------------")
            print(f"Breakout detected: {self.symbol} - price has gone below the sell level.")
            return 1
        # Return None if no breakout has occurred
        else:
            return None



    def manage_positions(self, open_positions):

        # Loop over all open positions
        for position in open_positions:

            if position[6] == self.magic2:
                #trail position
                update_result = self.position_manager.calculate_atr_trailing_stop(position)
                if update_result is not None:
                    print(f"Trailing stop loss updated: {update_result}")


    def reset_data(self):
            # Reset the trading data
            self.box = None

            # Reset flags
            self.data_fetched = False
            self.box_calculated = False
            self.levels_calculated = False
            self.trade_executed = False
            self.trading_notification = False
            self.trade_signal_notification = False
            self.position_manager_notification = False

            self.daily_data_reset = True
            # Send a reset message
            self.messanger.send(f'Today data reset:{self.daily_data_reset}')
           


    def run(self):
        while True:
            open_positions = self.position_manager.get_positions()
            num_pos_symb = len(open_positions)


            # Check if it's the right time to calculate levels (2:00 GMT)
            current_time = datetime.utcnow().time()
            if current_time == 1 and not self.daily_data_reset:
                self.reset_data()

            if current_time.hour >= 2 and not self.levels_calculated:
                print("------------------------------------------------------------------")
                print(f'Time(GMT): {current_time}')
                print("----------------------------")        
                self.calculate_levels()
                self.levels_calculated = True
                print("----------------------------")
                print(f'Levels Calculated: {self.symbol}: {self.levels_calculated}')
                self.daily_data_reset = False


            if num_pos_symb > 0:
                self.manage_positions(open_positions)
                if not self.position_manager_nofitication:
                    print("----------------------------")
                    print('Managing Opened Positions')
                    self.position_manager_nofitication = True
 

             # Only check for breakout if levels have been calculated and a trade hasn't been executed yet
            if self.levels_calculated and not self.trade_executed:
                if not self.trading_notification:
                    print("----------------------------")
                    print('Waiting to execute trade')
                    self.trading_notification = True

                trade_signal = self.check_for_break()
                #trade_signal = 0

                if trade_signal is not None:
                    if not self.trade_signal_notification:
                        print("----------------------------------------------")
                        print(f'Buy_level broken' if trade_signal == 0 else 'Sell_level broken')
                        self.messanger.send(f'Buy_level broken' if trade_signal == 0 else 'Sell_level broken')
                        print("-------------------------------------")
                        print("Executing Trade")  
                        self.trade_signal_notification = True

                     # Calculate the take profit based on the box height and trade signal
                    box_take_profit = self.box['buy_level'] + self.box['box_height'] if trade_signal == 0 else self.box['sell_level'] - self.box['box_height']

                    # Execute the trades
                    trade1 = MarketOrder(self.symbol, self.lot, self.deviation, self.magic1, trade_signal, self.box['buy_stoploss'] if trade_signal == 0 else self.box['sell_stoploss'], box_take_profit)
                    trade1.execute()
                    trade2 = MarketOrder(self.symbol, self.lot, self.deviation, self.magic2, trade_signal, self.box['buy_stoploss'] if trade_signal == 0 else self.box['sell_stoploss'])
                    trade2.execute()

                    self.trade_executed = True
                    print("-------------------------------------")
                    print(f'Trade executed: {self.symbol}: {self.trade_executed}')
                
                if current_time.hour == 22 and not self.daily_data_reset:
                    self.reset_data()
            
            time.sleep(60)
