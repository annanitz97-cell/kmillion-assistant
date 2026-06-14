import sqlite3

conn = sqlite3.connect("clients.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    phone TEXT DEFAULT '',
    budget TEXT DEFAULT '',
    mortgage TEXT DEFAULT '',
    location TEXT DEFAULT '',
    status TEXT DEFAULT 'active',
    comment TEXT DEFAULT '',
    created_by TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()


def ensure_column(column_name, column_type):
    cursor.execute("PRAGMA table_info(clients)")
    columns = [row[1] for row in cursor.fetchall()]

    if column_name not in columns:
        cursor.execute(f"ALTER TABLE clients ADD COLUMN {column_name} {column_type}")
        conn.commit()


ensure_column("phone", "TEXT DEFAULT ''")
ensure_column("budget", "TEXT DEFAULT ''")
ensure_column("mortgage", "TEXT DEFAULT ''")
ensure_column("location", "TEXT DEFAULT ''")
ensure_column("comment", "TEXT DEFAULT ''")


def add_client(name, phone="", budget="", mortgage="", location="", status="active", comment="", created_by=""):
    cursor.execute(
        """
        INSERT INTO clients
        (name, phone, budget, mortgage, location, status, comment, created_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (name, phone, budget, mortgage, location, status, comment, created_by)
    )
    conn.commit()


def get_clients():
    cursor.execute(
        """
        SELECT id, name, phone, budget, mortgage, location, status, comment, created_by
        FROM clients
        WHERE status != 'archived'
        ORDER BY id DESC
        """
    )
    return cursor.fetchall()


def find_clients(query):
    query = query.lower()

    cursor.execute(
        """
        SELECT id, name, phone, budget, mortgage, location, status, comment, created_by
        FROM clients
        WHERE status != 'archived'
        AND (
            lower(name) LIKE ?
            OR lower(phone) LIKE ?
            OR lower(budget) LIKE ?
            OR lower(mortgage) LIKE ?
            OR lower(location) LIKE ?
            OR lower(status) LIKE ?
            OR lower(comment) LIKE ?
        )
        ORDER BY id DESC
        """,
        (
            f"%{query}%",
            f"%{query}%",
            f"%{query}%",
            f"%{query}%",
            f"%{query}%",
            f"%{query}%",
            f"%{query}%"
        )
    )
    return cursor.fetchall()


def get_client_by_id(client_id):
    cursor.execute(
        """
        SELECT id, name, phone, budget, mortgage, location, status, comment, created_by
        FROM clients
        WHERE id = ?
        """,
        (client_id,)
    )
    return cursor.fetchone()


def update_client_fields(client_id, fields):
    allowed = ["name", "phone", "budget", "mortgage", "location", "status", "comment"]
    updates = []
    values = []

    for key, value in fields.items():
        if key in allowed and value:
            updates.append(f"{key} = ?")
            values.append(value)

    if not updates:
        return

    values.append(client_id)

    cursor.execute(
        f"""
        UPDATE clients
        SET {", ".join(updates)}
        WHERE id = ?
        """,
        values
    )

    conn.commit()


def archive_client(client_id):
    cursor.execute(
        "UPDATE clients SET status = 'archived' WHERE id = ?",
        (client_id,)
    )
    conn.commit()
