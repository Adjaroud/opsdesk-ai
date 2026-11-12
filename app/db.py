import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def db_path():
    return Path(os.environ.get("OPSDESK_DB", "data/opsdesk.db"))


@contextmanager
def connect(path=None):
    path = Path(path or db_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=5)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        with con:
            yield con
    finally:
        con.close()


def rows(con, query, args=()):
    return [dict(row) for row in con.execute(query, args)]


def assets(con, employee_id):
    return rows(con, "SELECT id, kind, model, status FROM assets WHERE employee_id=?", (employee_id,))


def ticket(con, employee_id, ticket_id):
    found = rows(con, "SELECT id, category, priority, summary, status FROM tickets WHERE id=? AND employee_id=?", (ticket_id, employee_id))
    if not found:
        raise PermissionError("Ticket inaccessible ou inexistant pour ce salarié.")
    return found[0]


def incidents(con, service):
    return rows(con, "SELECT id, service, summary, status, severity FROM incidents WHERE service=? AND status='active'", (service,))
