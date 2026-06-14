import sqlite3
from datetime import datetime, timedelta

conn = sqlite3.connect("calendar.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    event_at TEXT,
    created_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()


def add_event(title, event_at, created_by):
    cursor.execute(
        "INSERT INTO events (title, event_at, created_by) VALUES (?, ?, ?)",
        (title, event_at, created_by)
    )
    conn.commit()


def get_events_for_day(date_str):
    start = f"{date_str} 00:00"
    end = f"{date_str} 23:59"

    cursor.execute(
        """
        SELECT id, title, event_at, created_by
        FROM events
        WHERE event_at >= ?
        AND event_at <= ?
        ORDER BY event_at ASC
        """,
        (start, end)
    )

    return cursor.fetchall()


def get_events_for_next_days(days=7):
    now = datetime.now()
    end = now + timedelta(days=days)

    cursor.execute(
        """
        SELECT id, title, event_at, created_by
        FROM events
        WHERE event_at >= ?
        AND event_at <= ?
        ORDER BY event_at ASC
        """,
        (
            now.strftime("%Y-%m-%d %H:%M"),
            end.strftime("%Y-%m-%d %H:%M")
        )
    )

    return cursor.fetchall()


def delete_event(event_id):
    cursor.execute(
        "DELETE FROM events WHERE id = ?",
        (event_id,)
    )
    conn.commit()
