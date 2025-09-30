import sqlite3
import argparse
from werkzeug.security import generate_password_hash

DB_PATH = "instance/local.sqlite"

def add_client_user(username, password, client_name):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Vérifier que le client existe
    row = cur.execute("SELECT N, Entreprise FROM client WHERE Entreprise = ?", (client_name,)).fetchone()
    if not row:
        print(f"❌ Aucun client trouvé avec le nom: {client_name}")
        conn.close()
        return

    client_id = row["N"]

    # Vérifier si le user existe déjà
    existing = cur.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    if existing:
        print(f"⚠️ L'utilisateur '{username}' existe déjà")
        conn.close()
        return

    # Ajouter le user
    password_hash = generate_password_hash(password)
    cur.execute(
        "INSERT INTO users (username, password_hash, role, client_id) VALUES (?, ?, ?, ?)",
        (username, password_hash, "client", client_id),
    )
    conn.commit()
    conn.close()

    print(f"✅ Utilisateur client '{username}' ajouté avec succès, lié au client: {client_name} (ID={client_id})")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", required=True, help="Nom d'utilisateur du client")
    parser.add_argument("--password", required=True, help="Mot de passe du client")
    parser.add_argument("--client", required=True, help="Nom de l'entreprise client (doit exister dans la table client)")
    args = parser.parse_args()

    add_client_user(args.username, args.password, args.client)




"""
🚀 Comment l’utiliser

Exécute ce script en ligne de commande :

python add_client_user.py --username client1 --password secret123 --client "NomEntreprise"


--username → le login du client

--password → son mot de passe

--client → le champ Entreprise qui doit exister dans ta table client

✅ Résultat

Un nouvel utilisateur est créé dans la table users :

username = client1

password hashé (secret123)

role = client

lié au client_id correspondant à l’entreprise NomEntreprise

Ensuite, tu pourras tester la connexion avec ce compte sur /login.

"""