from meta_bot import OpenPositionManager, MT5Connector, MarketStatus
from config import account, password, server, symbols, timeframe, lot, from_data, to_data, deviation, magic1, magic2, tp_pips, atr_sl_multiplier, atr_period, max_dist_atr_multiplier, trail_atr_multiplier, webhook_url
import time

connector = MT5Connector(account=account, password=password, server=server)
market_status = MarketStatus(connector)

# Start the connection if the market is open
connector.connect()

# Check if the connection was successful
if connector.is_connected:
    print("----------------------------------")
    print("Successfully initialized to MT5.")

    position_manager = [OpenPositionManager(connector, symbol, timeframe, from_data, to_data, atr_period, max_dist_atr_multiplier, atr_sl_multiplier) for symbol in symbols]

    

    while True:


        for pm in position_manager:
            
            open_positions = position_manager.get_positions()
            num_pos_symb = len(open_positions)

            pm.manage_positions(open_positions)

        time.sleep(10)

else:
    print('not _con')