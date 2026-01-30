import os
import argparse
import sqlite3
import pyodbc
import decimal  # ✅ Pour gérer les types Decimal retournés par Access
from datetime import datetime, timezone
from ftplib import FTP_TLS

# ⚠️Chemin exact de la base Access
ACCESS_DB = r"D:\SALPAC\MP-SALPAC.accdb"
SQLITE_DB = os.path.join(os.path.dirname(__file__), "instance", "local.sqlite")
SQLITE_TMP = os.path.join(os.path.dirname(__file__), "instance", "local_tmp.sqlite")  # ✅ Fichier temporaire local ajouté

# Infos serveur OVH (SFTP)
SERVER = "mobibenz.com"       # ou l'IP du serveur
USERNAME = "salpac"  # ton login cPanel
PASSWORD = "Mobi@2026" # ton mot de passe cPanel
REMOTE_PATH = "local.sqlite"  # chemin relatif depuis ton home
REMOTE_TMP_PATH = "local_tmp.sqlite"  # ✅ fichier temporaire distant ajouté


def sync(access_path, sqlite_path):
    if not os.path.exists(access_path):
        raise FileNotFoundError(f"Fichier Access introuvable: {access_path}")

    # ✅ On écrit dans le fichier temporaire au lieu du fichier final
    target_path = SQLITE_TMP  # <-- modifié ici

    # Connexion Access
    conn_acc = pyodbc.connect(
        r"DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=" + access_path + ";"
    )
    cur_acc = conn_acc.cursor()

    # Connexion SQLite
    os.makedirs(os.path.dirname(sqlite_path), exist_ok=True)
    conn_sql = sqlite3.connect(target_path)  # <-- modifié ici
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
        RESERVATION_TABLE.QTE AS QTE_CMD,
        RESERVATION.DATE_RESERVATION,
        RESERVATION.SITUATION,
        (RESERVATION_TABLE.QTE - IIF(SUM(LIVRAISON_TABLE.QTE) IS NULL, 0, SUM(LIVRAISON_TABLE.QTE))) AS Reste,
        IIF(SUM(LIVRAISON_TABLE.QTE) IS NULL, 0, SUM(LIVRAISON_TABLE.QTE)) AS Total_livre
    FROM
        (
            (
                (
                    CLIENT
                    INNER JOIN RESERVATION
                        ON CLIENT.NUM_CLIENT = RESERVATION.CODE_CLIENT
                )
                INNER JOIN RESERVATION_TABLE
                    ON RESERVATION.NUM_RESERVATION = RESERVATION_TABLE.NUM_RESERVATION
            )
            INNER JOIN MAQUETTE
                ON MAQUETTE.CODE_MAQUETTE = RESERVATION_TABLE.CODE_PIECE
        )
        LEFT JOIN (
            LIVRAISON
            LEFT JOIN LIVRAISON_TABLE
                ON LIVRAISON.NUM_LIVRAISON = LIVRAISON_TABLE.NUM_LIVRAISON
        )
        ON RESERVATION.NUM_RESERVATION = LIVRAISON.NUM_RESERVATION
    GROUP BY
        RESERVATION.NUM_RESERVATION,
        RESERVATION.NUM_COMMANDE,
        CLIENT.ENTREPRISE,
        MAQUETTE.DESCRIPTION,
        RESERVATION_TABLE.QTE,
        RESERVATION.DATE_RESERVATION,
        RESERVATION.SITUATION
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
    # TABLE impression (matérialisée)
    # ==============================
    cur_sql.execute("DROP TABLE IF EXISTS impressions")
    cur_sql.execute("""
        CREATE TABLE impressions (
            num_impression INTEGER,
            date_impression TEXT,
            hr TEXT,
            num_commande INTEGER,
            machine TEXT,
            article TEXT,
            feuilles INTEGER,
            etuis INTEGER,
            user TEXT
        )
    """)

    rows = cur_acc.execute("""
        SELECT
            IMPRESSION.NUM_IMPRESSION,
            IMPRESSION.DATE_IMPRESSION,
            FORMAT(IMPRESSION.DATE_IMPRESSION, 'hh:nn') AS HR,
            IMPRESSION.NUM_COMMANDE,
            IMPRESSION.MACHINE_ID,
            MAQUETTE.DESCRIPTION,
            IMPRESSION.NBR_F AS FEUILLES,
            (IMPRESSION.NBR_F * MAQUETTE.POSE) AS ETUIS,
            UTILISATEUR.NOM
        FROM 
            ((IMPRESSION 
              INNER JOIN MAQUETTE ON IMPRESSION.MAQUETTE_ID = MAQUETTE.CODE_MAQUETTE)
              INNER JOIN UTILISATEUR ON IMPRESSION.USER_ID = UTILISATEUR.[N°])
        ORDER BY IMPRESSION.NUM_IMPRESSION DESC
    """)

    for row in rows:
        clean_row = []
        for x in row:
            if isinstance(x, decimal.Decimal):
                clean_row.append(float(x))
            else:
                clean_row.append(x)
        cur_sql.execute("INSERT INTO impressions VALUES (?,?,?,?,?,?,?,?,?)", clean_row)


    # ==============================
    # TABLE matérialisée "decoupage"
    # ==============================
    cur_sql.execute("DROP TABLE IF EXISTS decoupage")
    cur_sql.execute("""
        CREATE TABLE decoupage (
            num_decoupage INTEGER,
            num_impression INTEGER,
            date_decoupage TEXT,
            hr TEXT,
            num_commande INTEGER,
            maquette_id INTEGER,
            description TEXT,
            feuilles INTEGER,
            user TEXT
        )
    """)

    rows = cur_acc.execute("""
        SELECT 
            D.NUM_DECOUPAGE,
            I.NUM_IMPRESSION,
            D.DATE_DECOUPAGE,
            FORMAT(D.DATE_DECOUPAGE, 'hh:nn') AS HR,
            I.NUM_COMMANDE,
            I.MAQUETTE_ID,
            M.DESCRIPTION,
            D.NBR_FL_DCP,
            U.NOM
        FROM 
            ((DECOUPAGE AS D
            INNER JOIN (RESERVATION AS R
                INNER JOIN IMPRESSION AS I
                    ON R.NUM_RESERVATION = I.NUM_COMMANDE)
                ON D.IMPRESSION_ID = I.NUM_IMPRESSION)
            INNER JOIN MAQUETTE AS M
                ON I.MAQUETTE_ID = M.CODE_MAQUETTE)
            INNER JOIN UTILISATEUR AS U
                ON D.USER_ID = U.[N°]
    """)

    for row in rows:
        clean = tuple(row)
        cur_sql.execute("INSERT INTO decoupage VALUES (?,?,?,?,?,?,?,?,?)", clean)


    # ==============================
    # TABLE matérialisée "pliage"
    # ==============================
    cur_sql.execute("DROP TABLE IF EXISTS pliage")
    cur_sql.execute("""
        CREATE TABLE pliage (
            num_pliage INTEGER,
            date_pliage TEXT,
            hr TEXT,
            num_decoupage INTEGER,
            num_commande INTEGER,
            maquette_id INTEGER,
            description TEXT,
            qte_pli INTEGER,
            user TEXT
        )
    """)
    
    rows = cur_acc.execute("""
        SELECT
            PLIAGE.NUM_PLIAGE,
            PLIAGE.DATE_PLIAGE,
            FORMAT(PLIAGE.DATE_PLIAGE,'hh:nn') AS HR,
            DECOUPAGE.NUM_DECOUPAGE,
            IMPRESSION.NUM_COMMANDE,
            IMPRESSION.MAQUETTE_ID,
            MAQUETTE.DESCRIPTION,
            PLIAGE.QTE_PLI,
            UTILISATEUR.NOM
        FROM UTILISATEUR
        INNER JOIN (
            PLIAGE
            INNER JOIN (
                (DECOUPAGE
                INNER JOIN (RESERVATION
                    INNER JOIN IMPRESSION
                    ON RESERVATION.NUM_RESERVATION = IMPRESSION.NUM_COMMANDE)
                ON DECOUPAGE.IMPRESSION_ID = IMPRESSION.NUM_IMPRESSION)
                INNER JOIN MAQUETTE
                ON IMPRESSION.MAQUETTE_ID = MAQUETTE.CODE_MAQUETTE)
            ON PLIAGE.NUM_DECOUPAGE = DECOUPAGE.NUM_DECOUPAGE
        )
        ON UTILISATEUR.[N°] = PLIAGE.USER_ID
    """)
    
    for row in rows:
        clean = []
        for x in row:
            clean.append(float(x) if isinstance(x, decimal.Decimal) else x)
        cur_sql.execute("INSERT INTO pliage VALUES (?,?,?,?,?,?,?,?,?)", clean)

    # ==============================
    # COMMIT & CLOSE
    # ==============================
    conn_sql.commit()
    conn_sql.close()
    conn_acc.close()
    print(f"✅ Synchronisation terminée depuis {access_path} vers {target_path}")

    # ✅ Remplacement atomique du fichier temporaire par le fichier final
    os.replace(SQLITE_TMP, SQLITE_DB)  # <-- ajouté ici
    print(f"✅ Remplacement du fichier temporaire terminé : {SQLITE_DB}")

def upload_ovh(local_path, remote_path):
    ftps = FTP_TLS(SERVER)
    ftps.login(USERNAME+'@'+SERVER, PASSWORD)
    ftps.prot_p()  # Active la protection des données

    # ✅ Upload d'abord vers un fichier temporaire distant
    with open(local_path, "rb") as f:
        ftps.storbinary(f"STOR " + REMOTE_TMP_PATH, f)  # <-- modifié ici

    # ✅ Puis rename distant atomique
    ftps.rename(REMOTE_TMP_PATH, remote_path)  # <-- ajouté ici

    ftps.quit()
    print("✅ Upload terminé avec FTPS et renommage distant")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--access", default=ACCESS_DB, help="Chemin du fichier Access (.accdb ou .accde)")
    parser.add_argument("--sqlite", default=SQLITE_DB, help="Chemin du fichier SQLite cible")
    parser.add_argument("--upload", action="store_true", help="Uploader vers OVH après synchronisation")
    args = parser.parse_args()
    sync(args.access, args.sqlite)
    # Upload seulement si l'argument --upload est présent
    if args.upload:
        upload_ovh(SQLITE_DB, REMOTE_PATH)
