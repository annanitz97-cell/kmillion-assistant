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
        SELECT id, name, info, created_by, status
        FROM clients
        WHERE status != 'archived'
        ORDER BY id DESC
        """
    )
    return cursor.fetchall()


def find_clients(query):
    cursor.execute(
        """
        SELECT id, name, info, created_by, status
        FROM clients
        WHERE status != 'archived'
        AND (
            lower(name) LIKE ?
            OR lower(info) LIKE ?
            OR lower(status) LIKE ?
        )
        ORDER BY id DESC
        """,
        (f"%{query.lower()}%", f"%{query.lower()}%", f"%{query.lower()}%")
    )
    return cursor.fetchall()


def update_client(client_id, new_info):
    cursor.execute(
        """
        UPDATE clients
        SET info = info || char(10) || ?
        WHERE id = ?
        """,
        (new_info, client_id)
    )
    conn.commit()


def update_client_status(client_id, status):
    cursor.execute(
        """
        UPDATE clients
        SET status = ?
        WHERE id = ?
        """,
        (status, client_id)
    )
    conn.commit()


def archive_client(client_id):
    cursor.execute(
        "UPDATE clients SET status = 'archived' WHERE id = ?",
        (client_id,)
    )
    conn.commit()
