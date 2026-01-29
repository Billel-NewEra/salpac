import os
import argparse
import sqlite3
import pyodbc
import decimal  # ✅ Pour gérer les types Decimal retournés par Access
from datetime import datetime, timezone
from ftplib import FTP_TLS

# ⚠️Chemin exact de la base Access
ACCESS_DB = r"C:\Users\benza\OneDrive\Desktop\pal - Copie.accde"
SQLITE_DB = os.path.join(os.path.dirname(__file__), "instance", "local.sqlite")
SQLITE_TMP = os.path.join(os.path.dirname(__file__), "instance", "local_tmp.sqlite")  # ✅ Fichier temporaire local ajouté

# Infos serveur OVH (SFTP)
SERVER = "novoprint.dz"       # ou l'IP du serveur
USERNAME = "novoprintftp"  # ton login cPanel
PASSWORD = "novoprint1967" # ton mot de passe cPanel
REMOTE_PATH = "local.sqlite"  # chemin relatif depuis ton home
REMOTE_TMP_PATH = "local_tmp.sqlite"  # ✅ fichier temporaire distant ajouté

def to_utc_datetime(value):
    """
    Convertit une valeur datetime Access en texte UTC (YYYY-MM-DD HH:MM:SS).
    Si la valeur est None ou vide → retourne None.
    """
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
    dt_utc = dt.replace(tzinfo=timezone.utc)
    return dt_utc.strftime("%Y-%m-%d %H:%M:%S")

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
        row = list(row)
        row[5] = to_utc_datetime(row[5])  # 🕓 conversion UTC
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
        row = list(row)
        row[7] = to_utc_datetime(row[7])  # 🕓 conversion UTC
        # ✅ Conversion Decimal → float
        clean_row = tuple(float(x) if isinstance(x, decimal.Decimal) else x for x in row)
        cur_sql.execute("INSERT INTO delivery VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", clean_row)

    # ============================================
    # TABLE matérialisée "impressions_simplifiees"
    # ============================================
    cur_sql.execute("DROP TABLE IF EXISTS impressions_simplifiees")
    cur_sql.execute("""
        CREATE TABLE impressions_simplifiees (
            tirage TEXT,
            date_impression TEXT,
            commande TEXT,
            machine TEXT,
            article TEXT,
            longueur REAL,
            etiquettes INTEGER,
            chutes_ml REAL,
            utilisateur TEXT
        )
    """)
    rows = cur_acc.execute("""
        SELECT 
        IMPRESSION.NUM_IMPRESSION,
        IMPRESSION.DATE_IMPRESSION,
        IMPRESSION.NUM_COMMANDE,
        IMPRESSION.MACHINE_ID,
        MAQUETTE.DESCRIPTION,
        IMPRESSION.LONGUEUR,
        Int([IMPRESSION]![LONGUEUR]*1000*
            IIF(ISNULL([MAQUETTE]![OPERCULE]),1,[MAQUETTE]![OPERCULE])/
            [MAQUETTE]![HAUTEUR]) AS Etiquettes,
        SUM([IMPRESSION]![LONGUEUR]-[DECOUPE]![LONGUEUR]) AS Chutes_ml,
        UTILISATEUR.NOM
        FROM 
            ((UTILISATEUR 
                INNER JOIN IMPRESSION 
                    ON UTILISATEUR.[N°] = IMPRESSION.USER_ID)
                INNER JOIN MAQUETTE 
                    ON IMPRESSION.MAQUETTE_ID = MAQUETTE.CODE_MAQUETTE)
                INNER JOIN DECOUPE 
                    ON IMPRESSION.SN = DECOUPE.SN
                GROUP BY
                    IMPRESSION.NUM_IMPRESSION,
                    IMPRESSION.DATE_IMPRESSION,
                    IMPRESSION.NUM_COMMANDE,
                    IMPRESSION.MACHINE_ID,
                    MAQUETTE.DESCRIPTION,
                    IMPRESSION.LONGUEUR,
                    Int([IMPRESSION]![LONGUEUR]*1000*
                        IIF(ISNULL([MAQUETTE]![OPERCULE]),1,[MAQUETTE]![OPERCULE])/
                        [MAQUETTE]![HAUTEUR]),
                    UTILISATEUR.NOM
        ORDER BY IMPRESSION.NUM_IMPRESSION
    """)
    for row in rows:
        row = list(row)
        row[1] = to_utc_datetime(row[1])  # 🕓 conversion UTC
        clean_row = tuple(float(x) if isinstance(x, decimal.Decimal) else x for x in row)
        cur_sql.execute("""
            INSERT INTO impressions_simplifiees 
            (tirage, date_impression, commande, machine, article, longueur, etiquettes, chutes_ml, utilisateur)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, clean_row)

    print("✅ Table 'impressions_simplifiees' synchronized successfully.")

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
