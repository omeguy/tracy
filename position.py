import logging
import mt5utilities as util
from datetime import datetime
import MetaTrader5 as mt5

class Position:
    def __init__(self, symbol, trade_type, lot, magic_number, stop_loss, take_profit, deviation, logger=None, messanger=None, database_manager=None):
        self.symbol = symbol
        self.trade_type = trade_type
        self.lot = lot
        self.magic_number = magic_number
        self.stop_loss = stop_loss
        self.take_profit = take_profit
        self.deviation = deviation
        self.logger = logger if logger else logging.getLogger()
        self.messanger = messanger
        self.database_manager = database_manager  # Handles DB operations

        # Additional attributes
        self.ticket_id = None
        self.open_price = None
        self.open_time = None
        # Initialize other necessary attributes

        self.market_order = util.MarketOrder(self.symbol, self.lot, self.deviation, self.magic_number, self.trade_type, self.stop_loss, logger=self.logger)


    def execute_open(self):
        # Initializing MarketOrder with necessary parameters
        result = self.market_order.execute_open()
        
        # Check if result is successful
        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
            # Update position attributes based on the result
            self.ticket_id = result.order
            self.open_price = result.price
            self.open_time = datetime.now()
            self.status = "open"  # Update position status
            
            # Logging success
            self.logger.info("-------------------------------------------------")
            self.logger.info(f"Request executed: Ticket ID {self.ticket_id}, {self.symbol}: {result.comment}")

            if self.messanger:
                self.messanger.send(f"✅ Trade opened for {self.symbol} with Ticket ID {self.ticket_id}: {result.comment}")
            

            # Insert position details into the database if applicable
            if self.database_manager:
                self.database_manager.insert_position_details(self)

            return self.ticket_id, self  # Returning self and ticket_id
        
        else:
            # Handling failure
            error_message = result.comment if result else "Unknown error"
            self.logger.info("-------------------------------------------------")
            self.logger.error(f"Failed to execute trade {self.symbol}. Error: {error_message}")
            if self.messanger:
                self.messanger.send(f"❌ Failed to open trade for {self.symbol}. Error: {error_message}")
            return None, False


    def execute_close(self):
        if self.status != "open":
            self.logger.info("-------------------------------------------------")
            self.logger.error("Attempted to close a position that is not open.")
            return None, False  # Return None for ticket_id and False for success

        result = self.market_order.execute_close(self.ticket_id)
        
        if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
            self.close_time = datetime.now()
            self.close_price = result.price  # Assume result includes the closing price
            self.status = "closed"
            # Calculate profit or loss based on trade type
            self.profit_loss = self.calculate_return()
            self.logger.info("-------------------------------------------------")
            self.logger.info(f"Position {self.ticket_id} closed successfully with profit/loss: {self.profit_loss}.")

            if self.messanger:
                self.messanger.send(f"✅ Position: {self.symbol} closed with Ticket ID {self.ticket_id}. Profit/Loss: {self.profit_loss}.")

            # Update position details in the database if applicable
            if self.database_manager:
                # Assuming there's a method update_position_db similar to insert_position_details
                # that updates the position's closing details in the database
                self.database_manager.update_position_db(self)

            return self.ticket_id, True  # Return ticket_id and True for success
        else:
            error_message = result.comment if result else "Unknown error"
            self.logger.info("-------------------------------------------------")
            self.logger.error(f"Failed to close position {self.ticket_id}. Error: {error_message}")

            if self.messanger:
                self.messanger.send(f"❌ Failed to close position for {self.symbol} with Ticket ID {self.ticket_id}. Error: {error_message}")
            return None, False  # Return None for ticket_id and False for success


    def calculate_return(self):
        """
        Calculates the return of the closed position.
        The method assumes that profit or loss for a buy trade is calculated as:
            (close_price - open_price) * lot_size
        And for a sell trade as:
            (open_price - close_price) * lot_size
        Adjust the formula as necessary to match your trading strategy.
        """
        if not self.open_price or not self.close_price or not self.lot:
            self.logger.info("-------------------------------------------------")
            self.logger.error("Missing data for return calculation.")
            return None

        if self.trade_type == 0:  # Buy position
            self.profit_loss = (self.close_price - self.open_price) * self.lot
        elif self.trade_type == 1:  # Sell position
            self.profit_loss = (self.open_price - self.close_price) * self.lot
        else:
            self.logger.info("-------------------------------------------------")
            self.logger.error("Invalid trade type for return calculation.")
            return None

        # Optionally, you can adjust the return calculation here if your strategy requires
        return self.profit_loss

    def insert_position_db(self):
        # Method to insert a new open position into the opened_positions table
        columns = ['ticket_id', 'symbol', 'trade_type', 'open_price', 'open_time', 
               'stop_loss', 'take_profit', 'deviation', 'magic_number', 'lot', 'status']
        values = [self.ticket_id, self.symbol, self.trade_type, self.open_price, self.open_time, 
                self.stop_loss, self.take_profit, self.deviation, self.magic_number, self.lot, self.status]
        self.database_manager.insert_item("opened_trade", columns, values)

    def update_open_position_db(self):
        # Method to update an open position in the opened_positions table
        column_values = {
            'stop_loss': self.stop_loss,
            'take_profit': self.take_profit,
            'status': self.status
            # Add other columns as necessary
        }
        condition = f"ticket_id = {self.ticket_id}"
        self.database_manager.update_item("opened_trade", column_values, condition)

    def move_to_closed_positions(self):
        # Calculate profit or loss
        self.profit_loss = self.calculate_return()

        # Remove the position from opened_positions table
        self.database_manager.remove_item("opened_trade", f"ticket_id = {self.ticket_id}")
        
        # Insert the position into the closed_positions table, including profit_loss
        columns = ['ticket_id', 'symbol', 'trade_type', 'open_price', 'open_time', 'close_price', 
               'close_time', 'profit_loss', 'magic_number', 'lot', 'stop_loss', 'take_profit', 
               'deviation', 'status']
        values = [self.ticket_id, self.symbol, self.trade_type, self.open_price, self.open_time, 
                self.close_price, self.close_time, self.profit_loss, self.magic_number, self.lot, 
                self.stop_loss, self.take_profit, self.deviation, 'closed']  # Assuming status 'closed' is represented as such
        self.database_manager.insert_item("closed_trade", columns, values)

        self.logger.info(f"Position {self.ticket_id} moved to 'closed_positions' table with profit/loss: {self.profit_loss}.")

    def reconcile_position(self):
        """
        Handles the transition of this position from open to closed,
        updates the database accordingly, and then signals to remove
        this position from the bot's memory.
        """
        if self.database_manager and self.ticket_id:
            # Move the position from 'opened_positions' to 'closed_positions'
            self.move_to_closed_positions()  # Assuming this method correctly moves the position in the database

            # Additionally, perform any other necessary cleanup or logging
            self.logger.info(f"Position {self.ticket_id} reconciled and moved to closed positions in database.")
        else:
            self.logger.error(f"Cannot reconcile position {self.ticket_id}. Database manager or ticket ID is missing.")


    @classmethod
    def from_db_record(cls, record, logger=None, messanger=None, database_manager=None):
        """
        Creates a Position instance from a database record tuple, now including stop_loss, take_profit, and deviation.
        """
        # Extract data from the tuple by index based on the updated schema definition
        # The order here must match the order of fields in your updated database schema
        date_time_open = record[0]
        ticket_id = record[1]
        symbol = record[2]
        trade_type = record[3]
        open_price = record[4]
        magic_number = record[5]
        lot = record[6]  # Assuming lot is now correctly placed according to the updated schema
        stop_loss = record[7]  # Extract stop_loss from the record
        take_profit = record[8]  # Extract take_profit from the record
        deviation = record[9]  # Extract deviation from the record
        # Assuming status and other fields follow after deviation in the schema if needed

        return cls(
            symbol=symbol,
            trade_type=trade_type,
            lot=lot,
            magic_number=magic_number,
            stop_loss=stop_loss,
            take_profit=take_profit,
            deviation=deviation,
            logger=logger,
            messanger=messanger,
            database_manager=database_manager
        )



    def box_trail_stop(self):
        """
        Trail the stop loss of the position based on the box size.
        """

        # Fetch the current price for the symbol
        current_price = self.data_fetcher.get_current_price()

        if current_price is None:
            self.logger.error(f"Failed to fetch current price for {self.symbol}. Cannot trail stop loss.")
            if self.messanger:
                self.messanger.send(f"❌ Failed to update trailing stop: {self.symbol}. Could not fetch current price.")
            return None

    
    
        # Calculate the distance from the current price to the stop loss
        dist_from_sl = abs(current_price - self.stop_loss)

        # Define the maximum distance the stop loss should trail behind the current price
        max_dist_sl = self.box['box_height']
        
        # Define the trailing amount as half the box height
        trail_amount = 0.5 * self.box['box_height']

        # Check if the stop loss needs to be updated
        if dist_from_sl >= max_dist_sl:
            # Calculate the new stop loss based on the trade type
            new_sl = current_price - trail_amount if self.trade_type == 0 else current_price + trail_amount

            # Utilize the MarketOrder's update_position method to update the stop loss
            result = self.market_order.update_position(self.ticket_id, new_stop_loss=new_sl)

            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                # Successfully updated stop loss
                self.logger.info(f"Trailing stop for {self.symbol}, ticket {self.ticket_id} updated to {new_sl}.")
                if self.messanger:
                    self.messanger.send(f"🔼 Trailing stop: {self.symbol}, ticket {self.ticket_id} updated. New SL: {new_sl}.")
                self.stop_loss = new_sl  # Update the position's stop loss attribute
                return True
            else:
                # Failed to update stop loss
                self.logger.error(f"Failed to update trailing stop for {self.symbol}, ticket {self.ticket_id}. Error code: {result.retcode if result else 'No result'}")
                if self.messanger:
                    self.messanger.send(f"❌ Failed to update trailing stop: {self.symbol}.")

                return False
        else:
            # No update required for trailing stop
            self.logger.info(f"No update required for trailing stop of {self.symbol}, ticket {self.ticket_id}.")
            return False
