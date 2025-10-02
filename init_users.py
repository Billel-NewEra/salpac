import os
import sqlite3
import argparse
import getpass
from werkzeug.security import generate_password_hash

DEFAULT_DB = os.path.join(os.path.dirname(__file__), "instance", "local.sqlite")

DDL = """
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT    NOT NULL UNIQUE,
  password_hash TEXT    NOT NULL,
  role          TEXT    NOT NULL CHECK (role IN ('Admin','client')),
  client_id     INTEGER,
  is_active     INTEGER NOT NULL DEFAULT 1,
  created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (client_id) REFERENCES clients(id)
);
CREATE INDEX IF NOT EXISTS idx_users_client_id ON users(client_id);
"""

def ensure_schema(conn):
    for statement in DDL.strip().split(";"):
        s = statement.strip()
        if s:
            conn.execute(s + ";")

def upsert_admin(conn, username, password):
    cur = conn.execute("SELECT id FROM users WHERE username = ?", (username,))
    if cur.fetchone():
        print(f"[OK] L'utilisateur Admin '{username}' existe déjà.")
        return
    pwd_hash = generate_password_hash(password)
    conn.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, 'Admin')",
        (username, pwd_hash),
    )
    conn.commit()
    print(f"[OK] Admin '{username}' créé.")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB, help="Chemin vers la base SQLite")
    ap.add_argument("--username", default="MobiBenz", help="Nom d'utilisateur admin")
    ap.add_argument("--password", help="Mot de passe admin (sinon, demande interactive)")
    args = ap.parse_args()

    if not args.password:
        args.password = getpass.getpass(f"Mot de passe pour {args.username}: ")

    os.makedirs(os.path.dirname(args.db), exist_ok=True)
    conn = sqlite3.connect(args.db)
    try:
        ensure_schema(conn)
        upsert_admin(conn, args.username, args.password)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
