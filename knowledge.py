import sqlite3

conn = sqlite3.connect("knowledge.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()


def remember(text):
    cursor.execute(
        "INSERT INTO knowledge (text) VALUES (?)",
        (text,)
    )
    conn.commit()


def get_knowledge():
    cursor.execute(
        "SELECT id, text FROM knowledge ORDER BY id DESC LIMIT 30"
    )
    return cursor.fetchall()


def forget_item(item_id):
    cursor.execute(
        "DELETE FROM knowledge WHERE id = ?",
        (item_id,)
    )
    conn.commit()
