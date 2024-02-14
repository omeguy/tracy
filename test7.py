import MetaTrader5 as mt5
import db_manager


db_manager = db_manager.DatabaseManager('trades.db')

db_positions = db_manager.get_data('opened_trades')
print(db_positions)
