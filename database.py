import sqlite3
import os
from datetime import datetime

DATABASE_FILE = "bytewatch.db"

def get_db_connection(db_path=DATABASE_FILE):
    """Establish connection to the SQLite database."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_db(db_path=DATABASE_FILE):
    """Initialize the SQLite database and create necessary tables."""
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    # Create the telemetry metrics table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS telemetry_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            cpu_percent REAL NOT NULL,
            memory_percent REAL NOT NULL
        )
    """)
    
    # Index on timestamp for faster cleanup and queries
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON telemetry_history (timestamp)")
    
    conn.commit()
    conn.close()

def log_metrics(cpu_percent, memory_percent, db_path=DATABASE_FILE):
    """
    Log current CPU and Memory usage percent to the database,
    and automatically prune records older than 30 minutes.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    try:
        # Log the current metrics
        cursor.execute(
            "INSERT INTO telemetry_history (cpu_percent, memory_percent) VALUES (?, ?)",
            (cpu_percent, memory_percent)
        )
        
        # Clean up records older than 30 minutes
        # SQLite's CURRENT_TIMESTAMP uses UTC, so we compare with datetime('now', '-30 minutes')
        cursor.execute(
            "DELETE FROM telemetry_history WHERE timestamp < datetime('now', '-30 minutes')"
        )
        
        conn.commit()
    except sqlite3.Error as e:
        print(f"Database error during logging/pruning: {e}")
        conn.rollback()
    finally:
        conn.close()

def get_recent_history(db_path=DATABASE_FILE, limit_minutes=30):
    """
    Retrieve historical CPU and Memory percentage logs for the last X minutes.
    Returns a list of dicts with timestamp, cpu, and memory values.
    """
    conn = get_db_connection(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            """
            SELECT strftime('%H:%M:%S', datetime(timestamp, 'localtime')) as time_label, 
                   cpu_percent, 
                   memory_percent 
            FROM telemetry_history 
            WHERE timestamp >= datetime('now', ?)
            ORDER BY timestamp ASC
            """,
            (f"-{limit_minutes} minutes",)
        )
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except sqlite3.Error as e:
        print(f"Database error during history retrieval: {e}")
        return []
    finally:
        conn.close()
