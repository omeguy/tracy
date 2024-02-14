import sqlite3
from sqlite3 import Error
import logging  # Import the logging module

class DatabaseManager:
    def __init__(self, db_name=None, logger=None):
        self.db_name = db_name
        self.conn = None
        self.cursor = None
        self.logger = logger if logger else logging.getLogger(__name__)  # Use provided logger or default

    def open(self):
        try:
            self.conn = sqlite3.connect(self.db_name)
            self.cursor = self.conn.cursor()
        except Error as e:
            self.logger.error(f"Database connection error: {e}")

    def close(self):
        if self.conn:
            self.conn.close()
        self.conn = None
        self.cursor = None

    def create_table(self, table_name, schema):
        try:
            self.open()
            self.execute_sql(f'CREATE TABLE IF NOT EXISTS {table_name}({schema})')
            self.commit()
            self.logger.info(f"Table {table_name} created or already exists.")
        except Error as e:
            self.logger.error(f"Error creating table {table_name}: {e}")
        finally:
            self.close()

    def insert_item(self, table_name, columns, values):
        try:
            self.open()
            columns_str = ', '.join(columns)
            placeholders = ', '.join('?' * len(values))
            self.execute_sql(f'INSERT OR IGNORE INTO {table_name}({columns_str}) VALUES({placeholders})', values)
            self.commit()
            self.logger.info(f"Item inserted into {table_name}.")
        except Error as e:
            self.logger.error(f"Error inserting item into {table_name}: {e}")
        finally:
            self.close()

    def remove_item(self, table_name, condition):
        try:
            self.open()
            self.execute_sql(f'DELETE FROM {table_name} WHERE {condition}')
            self.commit()
            self.logger.info(f"Item removed from {table_name} where {condition}.")
        except Error as e:
            self.logger.error(f"Error removing item from {table_name}: {e}")
        finally:
            self.close()

    def update_item(self, table_name, column_values, condition):
        try:
            self.open()
            set_clause = ', '.join([f'{col} = ?' for col in column_values.keys()])
            sql = f'UPDATE {table_name} SET {set_clause} WHERE {condition}'
            self.execute_sql(sql, list(column_values.values()))
            self.commit()
            self.logger.info(f"Item in {table_name} updated where {condition}.")
        except Error as e:
            self.logger.error(f"Error updating item in {table_name}: {e}")
        finally:
            self.close()

    def get_data(self, table_name, where=None):
        try:
            self.open()
            sql = f"SELECT * FROM {table_name} WHERE {where}" if where else f"SELECT * FROM {table_name}"
            self.execute_sql(sql)
            data = self.fetchall()
            self.logger.info(f"Data retrieved from {table_name}.")
            return data
        except Error as e:
            self.logger.error(f"Error getting data from {table_name}: {e}")
            return []
        finally:
            self.close()

    def execute_sql(self, sql, params=None):
        try:
            self.cursor.execute(sql, params or [])
        except Error as e:
            self.logger.error(f"SQL execution error: {sql}, Error: {e}")

    def commit(self):
        if self.conn:
            self.conn.commit()

    def fetchall(self):
        return self.cursor.fetchall() if self.cursor else []
