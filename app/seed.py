"""Idempotent synthetic seed. Existing tickets are never reset."""
from app.db import connect


def seed(path=None):
    with connect(path) as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS employees(id TEXT PRIMARY KEY, name TEXT NOT NULL, department TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY, employee_id TEXT REFERENCES employees(id), kind TEXT, model TEXT, status TEXT);
        CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY, service TEXT, summary TEXT, status TEXT, severity TEXT);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, employee_id TEXT REFERENCES employees(id), context TEXT NOT NULL DEFAULT '{}');
        CREATE TABLE IF NOT EXISTS tickets(
            id TEXT PRIMARY KEY, employee_id TEXT REFERENCES employees(id), category TEXT NOT NULL,
            priority TEXT NOT NULL CHECK(priority IN ('P2','P3','P4')), summary TEXT NOT NULL,
            rationale TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'ouvert',
            session_token TEXT REFERENCES sessions(token), draft_id TEXT,
            UNIQUE(session_token, draft_id));
        """)
        con.executemany("INSERT OR IGNORE INTO employees VALUES (?,?,?)", [
            ("EMP-001", "Camille Exemple", "Commercial"), ("EMP-002", "Noah Démo", "Finance"),
            ("EMP-003", "Lina Fictive", "RH"), ("EMP-004", "Adam Test", "Opérations"),
            ("EMP-005", "Jade Modèle", "Communication"), ("EMP-006", "Alex Sandbox", "Support")])
        for i in range(1, 9):
            owner = (i - 1) % 6 + 1
            con.execute("INSERT OR IGNORE INTO assets VALUES (?,?,?,?,?)", (
                f"AST-{i:03}", f"EMP-{owner:03}", "portable" if i <= 6 else "écran",
                "DemoBook 14" if i <= 6 else "DemoView 24", "en service"))
        con.executemany("INSERT OR IGNORE INTO incidents VALUES (?,?,?,?,?)", [
            ("INC-001", "vpn", "VPN : connexions intermittentes, investigation en cours. Aucun délai de résolution confirmé.", "active", "major"),
            ("INC-002", "printer", "Imprimante du deuxième étage indisponible. Utiliser celle de l'accueil.", "active", "minor")])
        for i, category in enumerate(["vpn", "wifi", "mfa", "hardware", "access"], 1):
            con.execute("INSERT OR IGNORE INTO tickets(id,employee_id,category,priority,summary,rationale,status) VALUES (?,?,?,?,?,?,?)", (
                f"TKT-{i:03}", f"EMP-{i:03}", category, "P3", f"Demande fictive : {category}",
                "Demande individuelle sans impact collectif confirmé.", "en cours" if i == 1 else "ouvert"))


if __name__ == "__main__":
    seed()
    print("Données fictives initialisées ; données existantes préservées.")
