import sqlite3
import os
import datetime

class EventLogger:
    def __init__(self, db_file='db/events.db'):
        """
        Initialize SQLite connection and create table if it doesn't exist.
        """
        self.db_file = db_file
        
        # Ensure db directory exists
        db_dir = os.path.dirname(self.db_file)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir, exist_ok=True)
            
        self.conn = sqlite3.connect(self.db_file, check_same_thread=False)
        self.cursor = self.conn.cursor()
        self.create_table()

    def create_table(self):
        query = """
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            event_type TEXT,
            user_name TEXT,
            confidence REAL
        )
        """
        self.cursor.execute(query)
        self.conn.commit()

    def log_event(self, user_name, event_type, confidence=0.0):
        """
        Insert a new event record.
        """
        timestamp = datetime.datetime.now().isoformat()
        query = "INSERT INTO events (timestamp, event_type, user_name, confidence) VALUES (?, ?, ?, ?)"
        self.cursor.execute(query, (timestamp, event_type, user_name, confidence))
        self.conn.commit()
        # print(f"[DB] Logged: {user_name} - {event_type} ({confidence:.4f})")

    def close(self):
        self.conn.close()
