import sqlite3

conn = sqlite3.connect("clients.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    info TEXT,
    created_by TEXT,
    status TEXT DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()


def add_client(name, info, created_by):
    cursor.execute(
        "INSERT INTO clients (name, info, created_by) VALUES (?, ?, ?)",
        (name, info, created_by)
    )
    conn.commit()


def get_clients():
    cursor.execute(
        """
        SELECT id, name, info, created_by
        FROM clients
        WHERE status = 'active'
        ORDER BY id DESC
        """
    )
    return cursor.fetchall()


def find_clients(query):
    cursor.execute(
        """
        SELECT id, name, info, created_by
        FROM clients
        WHERE status = 'active'
        AND (
            lower(name) LIKE ?
            OR lower(info) LIKE ?
        )
        ORDER BY id DESC
        """,
        (f"%{query.lower()}%", f"%{query.lower()}%")
    )
    return cursor.fetchall()


def archive_client(client_id):
    cursor.execute(
        "UPDATE clients SET status = 'archived' WHERE id = ?",
        (client_id,)
    )
    conn.commit()
