import sqlite3

conn = sqlite3.connect("tasks.db", check_same_thread=False)

cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person TEXT,
    task TEXT,
    status TEXT DEFAULT 'open'
)
""")

conn.commit()


def add_task(person, task):
    cursor.execute(
        """
        INSERT INTO tasks
        (person, task)
        VALUES (?, ?)
        """,
        (person, task)
    )

    conn.commit()


def get_tasks(person):
    cursor.execute(
        """
        SELECT id, task
        FROM tasks
        WHERE person = ?
        AND status='open'
        """,
        (person,)
    )

    return cursor.fetchall()
