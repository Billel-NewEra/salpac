import os
import sqlite3
import argparse
import getpass
from datetime import datetime
from werkzeug.security import generate_password_hash

# ==============================
# Configuration de la base cible
# ==============================
AUTH_DB = os.path.join(os.path.dirname(__file__), "instance", "auth.sqlite")

DDL = """
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT    NOT NULL UNIQUE,
  password_hash TEXT    NOT NULL,
  role          TEXT    NOT NULL CHECK (role IN ('superadmin', 'admin', 'planning' , 'client')),
  client_id     INTEGER,
  is_active     INTEGER NOT NULL DEFAULT 1,
  created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_users_client_id ON users(client_id);

CREATE TABLE IF NOT EXISTS webauthn_credentials (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  credential_id BLOB NOT NULL UNIQUE,
  public_key BLOB NOT NULL,
  sign_count INTEGER NOT NULL DEFAULT 0,
  transports TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  last_used_at TEXT,
  FOREIGN KEY(user_id) REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_webauthn_user_id
ON webauthn_credentials(user_id);
"""

# ==============================
# Fonctions principales
# ==============================
def ensure_schema(conn):
    """Crée la table users si elle n'existe pas déjà"""
    for statement in DDL.strip().split(";"):
        s = statement.strip()
        if s:
            conn.execute(s + ";")


def upsert_admin(conn, username, password, role):
    """Crée l’utilisateur admin s’il n’existe pas"""
    cur = conn.execute("SELECT id FROM users WHERE username = ?", (username,))
    if cur.fetchone():
        print(f"[OK] ✅ L'utilisateur admin '{username}' existe déjà.")
        return
    if role not in ['superadmin', 'admin', 'planning' , 'client']:
        print(f"Le role doit être ('superadmin', 'admin', 'planning', 'client')")
        return
    pwd_hash = generate_password_hash(password)
    conn.execute(
        "INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
        (username, pwd_hash, role),
    )
    conn.commit()
    print(f"[✅] Administrateur '{username}' créé avec succès.")


def list_existing_users(conn):
    """Affiche la liste des utilisateurs existants"""
    rows = conn.execute(
        "SELECT id, username, role, is_active, created_at FROM users ORDER BY id ASC"
    ).fetchall()

    if not rows:
        print("\nℹ️ Aucun utilisateur enregistré pour l’instant.")
        return

    print("\n📋 Utilisateurs existants :")
    print("-" * 60)
    for r in rows:
        active = "✅" if r[3] else "⛔"
        print(f"ID {r[0]:<3} | {r[1]:<15} | {r[2]:<8} | Actif {active} | Créé le {r[4]}")
    print("-" * 60)


# ==============================
# Main
# ==============================
def main():
    ap = argparse.ArgumentParser(description="Créer ou vérifier l'utilisateur admin dans auth.sqlite")
    ap.add_argument("--db", default=AUTH_DB, help="Chemin vers la base SQLite d'authentification")
    ap.add_argument("--username", default="superadmin", help="Nom d'utilisateur superadmin")
    ap.add_argument("--password", help="Mot de passe superadmin (sinon, demande interactive)")
    ap.add_argument("--role", default="superadmin", help="Role(superadmin, admin, planning)")
    args = ap.parse_args()

    # Si aucun mot de passe fourni → on le demande à l’écran
    if not args.password:
        args.password = getpass.getpass(f"Mot de passe pour {args.username}: ")

    # Vérifie le dossier
    os.makedirs(os.path.dirname(args.db), exist_ok=True)
    print(f"\n📦 Base d'authentification : {args.db}")

    # Connexion
    conn = sqlite3.connect(args.db)
    try:
        ensure_schema(conn)
        upsert_admin(conn, args.username, args.password, args.role)
        list_existing_users(conn)
    finally:
        conn.close()

    #print(f"🕒 Exécution terminée le {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

# ==============================
# Entrée principale
# ==============================
if __name__ == "__main__":
    main()
