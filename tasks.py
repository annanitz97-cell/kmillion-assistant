import sqlite3

conn = sqlite3.connect("tasks.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person TEXT,
    task TEXT,
    status TEXT DEFAULT 'open',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
""")

conn.commit()


def add_task(person, task):
    cursor.execute(
        "INSERT INTO tasks (person, task) VALUES (?, ?)",
        (person, task)
    )
    conn.commit()


def get_open_tasks():
    cursor.execute(
        "SELECT id, person, task FROM tasks WHERE status = 'open' ORDER BY id DESC"
    )
    return cursor.fetchall()


def close_task(task_id):
    cursor.execute(
        "UPDATE tasks SET status = 'closed' WHERE id = ?",
        (task_id,)
    )
    conn.commit()
