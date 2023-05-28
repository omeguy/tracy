import MetaTrader5 as mt5

# MetaTrader 5 credentials
account = 30539852
password = 'Omegatega360'
server = 'Deriv-Demo'
webhook_url = 'https://discordapp.com/api/webhooks/1080463096176443422/ikJK_aoZ__Dp9F6MBz5mXfAlLjJJdWJbUB-yA0X8PiyQTjjyIMjGAPZRCslpf6zF2CzL'


# User-defined variables
symbols = ['EURJPY', 'GBPJPY', 'AUDJPY', 'USDJPY']
timeframe = mt5.TIMEFRAME_M15
lot = 0.01
from_data = 1
to_data = 16
deviation = 10
magic1 = 360
magic2 = 361
tp_pips = 50
atr_sl_multiplier = 1.5
atr_period = 14
max_dist_atr_multiplier = 1.5
trail_atr_multiplier = 0.5
