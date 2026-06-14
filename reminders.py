import sqlite3
from datetime import datetime

conn = sqlite3.connect("reminders.db", check_same_thread=False)

cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id INTEGER,
    text TEXT,
    remind_at TEXT,
    sent INTEGER DEFAULT 0
)
""")

conn.commit()


def add_reminder(chat_id, text, remind_at):
    cursor.execute(
        """
        INSERT INTO reminders
        (chat_id, text, remind_at)
        VALUES (?, ?, ?)
        """,
        (chat_id, text, remind_at)
    )

    conn.commit()


def get_due_reminders():
    now = datetime.utcnow().isoformat()

    cursor.execute(
        """
        SELECT id, chat_id, text
        FROM reminders
        WHERE sent = 0
        AND remind_at <= ?
        """,
        (now,)
    )

    return cursor.fetchall()


def mark_sent(reminder_id):
    cursor.execute(
        """
        UPDATE reminders
        SET sent = 1
        WHERE id = ?
        """,
        (reminder_id,)
    )

    conn.commit()
