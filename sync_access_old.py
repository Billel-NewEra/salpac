import os
import argparse
import sqlite3
import pyodbc
import decimal  # ✅ Pour gérer les types Decimal retournés par Access

# ⚠️ Mets ici le chemin exact de ta base Access
ACCESS_DB = r"C:\Users\benza\OneDrive\Desktop\pal - Copie.accde"
SQLITE_DB = os.path.join(os.path.dirname(__file__), "instance", "local.sqlite")

def sync(access_path, sqlite_path):
    if not os.path.exists(access_path):
        raise FileNotFoundError(f"Fichier Access introuvable: {access_path}")

    # Connexion Access
    conn_acc = pyodbc.connect(
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=" + access_path + ";"
    )
    cur_acc = conn_acc.cursor()

    # Connexion SQLite
    os.makedirs(os.path.dirname(sqlite_path), exist_ok=True)
    conn_sql = sqlite3.connect(sqlite_path)
    cur_sql = conn_sql.cursor()

    # ==============================
    # TABLE client
    # ==============================
    cur_sql.execute("DROP TABLE IF EXISTS client")
    cur_sql.execute("""
        CREATE TABLE client (
            N INTEGER PRIMARY KEY,
            Entreprise TEXT,
            Contact TEXT,
            Tel TEXT,
            Email TEXT
        )
    """)
    rows = cur_acc.execute("SELECT NUM_CLIENT, ENTREPRISE, CONTACT, TELEPHONE, EMAIL FROM client")
    for row in rows:
        cur_sql.execute("INSERT INTO client VALUES (?, ?, ?, ?, ?)", row)

    # ==============================
    # TABLE matérialisée "orders"
    # ==============================
    cur_sql.execute("DROP TABLE IF EXISTS orders")
    cur_sql.execute("""
        CREATE TABLE orders (
            num_reservation INTEGER,   -- N Cmnd
            cmdl TEXT,
            client TEXT,               -- Client
            produit TEXT,              -- Produit
            qte INTEGER,               -- Cmnde
            date_reservation TXT,      -- Date
            situation TEXT,            -- Situation
            reste REAL,                -- Reste
            total_livre REAL           -- Total livré
        )
    """)

    rows = cur_acc.execute("""
        SELECT 
            RESERVATION.NUM_RESERVATION,
            RESERVATION.NUM_COMMANDE,
            CLIENT.ENTREPRISE,
            MAQUETTE.DESCRIPTION,
            RESERVATION_TABLE.QTE,
            RESERVATION.DATE_RESERVATION,
            RESERVATION.SITUATION,
            RESERVATION_TABLE.QTE - IIF(ISNULL(Total_livre_cmd.QT),0,Total_livre_cmd.QT) AS Reste,
            IIF(ISNULL(Total_livre_cmd.QT),0,Total_livre_cmd.QT) AS Total_livre
        FROM 
            (CLIENT 
                INNER JOIN (
                    (((RESERVATION 
                        LEFT JOIN CHUTE_IMP 
                            ON RESERVATION.NUM_RESERVATION = CHUTE_IMP.NUM_RESERVATION) 
                        LEFT JOIN CHUTE_CTL 
                            ON RESERVATION.NUM_RESERVATION = CHUTE_CTL.NUM_COMMANDE) 
                        LEFT JOIN CHUTE_SLV 
                            ON RESERVATION.NUM_RESERVATION = CHUTE_SLV.NUM_COMMANDE) 
                        LEFT JOIN Total_livre_cmd 
                            ON RESERVATION.NUM_RESERVATION = Total_livre_cmd.NUM_RESERVATION
                ) ON CLIENT.NUM_CLIENT = RESERVATION.CODE_CLIENT
            ) 
            INNER JOIN (
                MAQUETTE 
                INNER JOIN RESERVATION_TABLE 
                    ON MAQUETTE.CODE_MAQUETTE = RESERVATION_TABLE.CODE_PIECE
            ) 
            ON RESERVATION.NUM_RESERVATION = RESERVATION_TABLE.NUM_RESERVATION
    """)
    for row in rows:
        cur_sql.execute("INSERT INTO orders VALUES (?,?,?,?,?,?,?,?,?)", row)

    # ==============================
    # TABLE matérialisée "delivery"
    # ==============================
    cur_sql.execute("DROP TABLE IF EXISTS delivery")
    cur_sql.execute("""
        CREATE TABLE delivery (
            nl INTEGER,               -- Numéro de livraison
            code_client INTEGER,      -- Code client
            client TEXT,              -- Nom du client
            qte INTEGER,              -- Quantité livrée
            montant REAL,             -- Montant total
            num_reservation INTEGER,  -- Numéro réservation
            utilisateur TEXT,         -- Utilisateur
            date_livraison TEXT,      -- Date de livraison
            facture TEXT,             -- Facture
            num_livraison INTEGER,    -- Numéro livraison (bis)
            observation TEXT,         -- Observation
            produit TEXT              -- Description produit
        )
    """)

    rows = cur_acc.execute("""
        SELECT 
            LIVRAISON.NUM_LIVRAISON AS NL,
            RESERVATION.CODE_CLIENT,
            CLIENT.ENTREPRISE,
            LIVRAISON_TABLE.QTE,
            SUM(LIVRAISON_TABLE.PRIX_GROS * LIVRAISON_TABLE.QTE) AS MONTANT,
            LIVRAISON.NUM_RESERVATION,
            UTILISATEUR.NOM,
            LIVRAISON.DATE_LIVRAISON,
            LIVRAISON.FACTURE,
            LIVRAISON.NUM_LIVRAISON,
            LIVRAISON.OBSERVATION,
            MAQUETTE.DESCRIPTION
        FROM 
            UTILISATEUR 
            INNER JOIN (
                (CLIENT 
                    INNER JOIN RESERVATION 
                        ON CLIENT.NUM_CLIENT = RESERVATION.CODE_CLIENT
                ) 
                INNER JOIN (
                    LIVRAISON 
                    INNER JOIN (
                        LIVRAISON_TABLE 
                        INNER JOIN MAQUETTE 
                            ON LIVRAISON_TABLE.CODE_PIECE = MAQUETTE.CODE_MAQUETTE
                    ) 
                    ON LIVRAISON.NUM_LIVRAISON = LIVRAISON_TABLE.NUM_LIVRAISON
                ) 
                ON RESERVATION.NUM_RESERVATION = LIVRAISON.NUM_RESERVATION
            ) 
            ON UTILISATEUR.[N°] = LIVRAISON.NUM_UTILISATEUR
        GROUP BY 
            RESERVATION.CODE_CLIENT, 
            CLIENT.ENTREPRISE, 
            LIVRAISON_TABLE.QTE, 
            LIVRAISON.NUM_RESERVATION, 
            UTILISATEUR.NOM, 
            LIVRAISON.DATE_LIVRAISON, 
            LIVRAISON.FACTURE, 
            LIVRAISON.NUM_LIVRAISON, 
            LIVRAISON.OBSERVATION, 
            MAQUETTE.DESCRIPTION, 
            LIVRAISON.NUM_LIVRAISON
        ORDER BY LIVRAISON.NUM_LIVRAISON
    """)
    for row in rows:
        # ✅ Conversion Decimal → float
        clean_row = tuple(float(x) if isinstance(x, decimal.Decimal) else x for x in row)
        cur_sql.execute("INSERT INTO delivery VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", clean_row)

    # ==============================
    # COMMIT & CLOSE
    # ==============================
    conn_sql.commit()
    conn_sql.close()
    conn_acc.close()
    print(f"✅ Synchronisation terminée depuis {access_path} vers {sqlite_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--access", default=ACCESS_DB, help="Chemin du fichier Access (.accdb ou .accde)")
    parser.add_argument("--sqlite", default=SQLITE_DB, help="Chemin du fichier SQLite cible")
    args = parser.parse_args()
    sync(args.access, args.sqlite)
