import sqlite3

conn = sqlite3.connect("memory.db", check_same_thread=False)

cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user TEXT,
    role TEXT,
    content TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()


def save_message(user, role, content):
    cursor.execute(
        """
        INSERT INTO memory
        (user, role, content)
        VALUES (?, ?, ?)
        """,
        (user, role, content)
    )

    conn.commit()


def get_last_messages(limit=30):
    cursor.execute(
        """
        SELECT role, content
        FROM memory
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,)
    )

    rows = cursor.fetchall()

    rows.reverse()

    return [
        {
            "role": role,
            "content": content
        }
        for role, content in rows
    ]
