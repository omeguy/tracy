import core
import mt5utilities as util
import MetaTrader5 as mt5
import time
import json


def main():
    # Initialize AppLogger from the core module
    
    logger = core.AppLogger("main", "main.log").get_logger()

    config_manager = core.ConfigManager("config.json", logger)

    # Load configuration
    config = config_manager.get_config()

    # Extract MT5 connection details
    details = config.get("details", {})
    mt5_connector = util.MT5Connector(account=details["account"],
                                      password=details["password"],
                                      server=details["server"])
    
    messenger = util.Messenger(details['webhook_url'])

    # Initialize Market Status, Thread Manager, and KeyCapture from the core module
    market_status = core.MarketStatus()
    thread_manager = core.ThreadManager(logger)
    key_capture = core.KeyCapture()

    # Assuming  Inspirer are to be properly initialized with webhook_url
    # For now, placeholders are used and should be replaced with actual initializations
    inspirer1 = core.InspireTraders(messenger, 'tracy\inspirer1.json', None) # No schedule needed


    # Initialize Trade Engine with the connected MT5 connector and loaded configuration
    trade_engine = core.TradeEngine(mt5_connector=mt5_connector,
                                    market_status=market_status,
                                    config=config,
                                    messenger=messenger,
                                    inspirer=inspirer1,
                                    logger=logger,
                                    thread_manager=thread_manager)

    # Start the trade engine
    trade_engine.start()

    # Main loop to keep the application running until ESC is pressed or a shutdown signal is received
    try:
        while not key_capture.esc_pressed_check():
            time.sleep(1)  # Sleep to reduce CPU usage
    except KeyboardInterrupt:
        logger.info("-------------------------------------------------")
        logger.info("Shutdown requested...exiting")
    finally:
        # Perform any cleanup here
        trade_engine.stop_bots()
        if mt5_connector.is_connected:
            mt5_connector.disconnect()
        logger.info("-------------------------------------------------")
        logger.info("Application shutdown successfully.")

if __name__ == "__main__":
    main()
