from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify, send_from_directory
import sqlite3
import os
from datetime import datetime, timedelta, date
import calendar
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import generate_password_hash
from werkzeug.security import check_password_hash

app = Flask(__name__)
app.secret_key = "change_this_to_a_real_secret_key"
app.config["REMEMBER_COOKIE_DURATION"] = timedelta(days=30)

app.config.update(
    REMEMBER_COOKIE_SECURE=True,
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SAMESITE="Lax"
)

# --- Flask-Login config ---
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"  # si accès non autorisé → /login
login_manager.login_message = None

# --- Connexion sqlite3 brut ---
def get_db_connection():
    conn = sqlite3.connect("instance/local.sqlite")
    conn.row_factory = sqlite3.Row
    return conn

# --- Connexion SQL pour authenti
def get_auth_connection():
    conn = sqlite3.connect("instance/auth.sqlite")
    conn.row_factory = sqlite3.Row
    return conn

# --- User class (Flask-Login) ---
class User(UserMixin):
    def __init__(self, id, username, password_hash, role, client_id):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.role = role
        self.client_id = client_id

def get_user_by_id(user_id):
    conn = get_auth_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if row:
        return User(row["id"], row["username"], row["password_hash"], row["role"], row["client_id"])
    return None

def get_user_by_username(username):
    conn = get_auth_connection()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    if row:
        return User(row["id"], row["username"], row["password_hash"], row["role"], row["client_id"])
    return None

def get_weekly_activity():
    conn = get_db_connection()

    # --- Sélection selon le rôle de l'utilisateur ---
    if current_user.role in ("superadmin", "admin"):
        query = """
            SELECT 
                strftime('%W', date_reservation) AS week,
                strftime('%w', date_reservation) AS weekday,
                COUNT(*) AS count
            FROM orders
            WHERE date_reservation IS NOT NULL
            GROUP BY week, weekday
            ORDER BY week ASC, weekday ASC
        """
        params = ()
    else:
        # Récupérer le nom de l’entreprise du client connecté
        row = conn.execute(
            "SELECT Entreprise FROM client WHERE N = ?", (current_user.client_id,)
        ).fetchone()
        if not row:
            conn.close()
            return {"weeks": [], "days": [], "data": []}
        client_name = row["Entreprise"]

        query = """
            SELECT 
                strftime('%W', date_reservation) AS week,
                strftime('%w', date_reservation) AS weekday,
                COUNT(*) AS count
            FROM orders
            WHERE client = ? AND date_reservation IS NOT NULL
            GROUP BY week, weekday
            ORDER BY week ASC, weekday ASC
        """
        params = (client_name,)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    if not rows:
        return {"weeks": [], "days": [], "data": []}

    # --- Conversion vers structure utilisable ---
    weeks = sorted(list({r["week"] for r in rows}))[-4:]  # ✅ seulement les 4 dernières semaines
    days = ['Dim', 'Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam']
    data = {w: [0] * 7 for w in weeks}

    for r in rows:
        w = r["week"]
        if w not in weeks:
            continue  # ignorer les plus anciennes
        d = int(r["weekday"])  # 0=Dimanche
        c = r["count"]
        data[w][d] = c

    return {
        "weeks": [f"S{int(w)}" for w in weeks],
        "days": days,
        "data": list(data.values())
    }


@login_manager.user_loader
def load_user(user_id):
    return get_user_by_id(user_id)

@app.template_filter("datetime_format")
def datetime_format(value):
    if not value:
        return ""

    # 1️⃣ Objet datetime
    if isinstance(value, datetime):
        return value.strftime("%d-%m-%Y %H:%M")

    # 2️⃣ String ISO (SQLite classique)
    if isinstance(value, str):
        try:
            # gère :
            # 2025-01-24 16:32:10
            # 2025-01-24T16:32:10
            # 2025-01-24 16:32:10.123456
            dt = datetime.fromisoformat(value.replace(" ", "T"))
            return dt.strftime("%d-%m-%Y %H:%M")
        except:
            return value

    return value

# ============================
#   ROUTES AUTHENTIFICATION
# ============================

@app.route("/login", methods=["GET", "POST"])
def login():
    # Si déjà connecté → dashboard direct
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form["username"].strip().lower()
        password = request.form["password"]
        user = get_user_by_username(username)

        if user and check_password_hash(user.password_hash, password):
            login_user(user, remember=True)
            return jsonify({"success": True, "redirect": url_for("index")})
        else:
            # ✅ On renvoie du JSON au lieu de recharger la page
            return jsonify({"success": False, "message": "Nom d'utilisateur ou mot de passe incorrect ❌"})

    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    #flash("Vous êtes déconnecté maintenant ✅", "info")
    return redirect(url_for("login"))

@app.route("/whoami")
@login_required
def whoami():
    return f"Utilisateur connecté : {current_user.username} | rôle = {current_user.role} | client_id = {current_user.client_id}"

# ============================
#   CONTEXT PROCESSOR
# ============================

@app.context_processor
def inject_now():
    from datetime import datetime
    return {'current_year': datetime.now().year}
@app.context_processor
def inject_client_name():
    client_name = None
    if current_user.is_authenticated and current_user.role == "client":
        conn = get_db_connection()
        row = conn.execute(
            "SELECT Entreprise FROM client WHERE N = ?", (current_user.client_id,)
        ).fetchone()
        conn.close()
        if row:
            client_name = row["Entreprise"]
    return dict(client_name=client_name)

# ============================
#   ROUTES PRINCIPALES
# ============================

@app.route('/service-worker.js')
def service_worker():
    return send_from_directory(
        directory=app.root_path,
        path="service-worker.js",
        mimetype="application/javascript"
    )

@app.route("/favicon.ico")
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, "static"),
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon"
    )

@app.route("/")
def home():
    #return render_template("home.html", current_year=datetime.now().year)
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    return redirect(url_for("login"))

# ---- Dashboard ----
@app.route("/index")
@login_required
def index():
    conn = get_db_connection()
    now = datetime.now()
    #now = datetime(2026, 1, 15)    
    month_start = now.replace(day=1).strftime("%Y-%m-%d")

    if now.month == 12:
        next_month = now.replace(year=now.year+1, month=1, day=1)
    else:
        next_month = now.replace(month=now.month+1, day=1)
    
    month_end = next_month.strftime("%Y-%m-%d")

    current_month = f"{now.month:02d}"
    current_year = str(now.year)

    month_names = [
    "Janvier","Février","Mars","Avril","Mai","Juin",
    "Juillet","Août","Septembre","Octobre","Novembre","Décembre"
    ]

    month_label = month_names[now.month - 1]

    # Vue admin → totaux globaux
    if current_user.role in ("superadmin", "admin"):
        total_clients = conn.execute("SELECT COUNT(*) FROM client").fetchone()[0]
        total_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        orders_livree = conn.execute("SELECT COUNT(*) FROM orders WHERE situation = 'LIVREE'").fetchone()[0]
        orders_encours = conn.execute("SELECT COUNT(*) FROM orders WHERE situation = 'EN COURS'").fetchone()[0]
        orders_livraison = conn.execute("SELECT COUNT(*) FROM orders WHERE situation = 'LIVRAISON'").fetchone()[0]
        orders_bag = conn.execute("SELECT COUNT(*) FROM orders WHERE situation = 'BAG' COLLATE NOCASE").fetchone()[0]
        total_delivery = conn.execute("SELECT COUNT(*) FROM delivery").fetchone()[0]

        # ✅ NOUVEAU CLIENTS DU MOIS
        new_clients = conn.execute("""
            SELECT COUNT(*) FROM client
            WHERE date(date_creation) >= date(?)
              AND date(date_creation) < date(?)
        """, (month_start, month_end)).fetchone()[0]
        
        # ✳️ Livraisons du mois en cours
        new_deliveries = conn.execute("""
        SELECT COUNT(*) FROM delivery
        WHERE date(date_livraison) >= date(?)
          AND date(date_livraison) < date(?)
        """, (month_start, month_end)).fetchone()[0]

        # 📦 Produits les plus livrés (Top 6)
        top_products = conn.execute("""
            SELECT produit, COUNT(*) AS nb_livraisons
            FROM delivery
            WHERE date(date_livraison) >= date(?)
                AND date(date_livraison) <  date(?)
            GROUP BY produit
            ORDER BY nb_livraisons DESC
            LIMIT 10
        """, (month_start, month_end)).fetchall()

        products_labels = [row["produit"] for row in top_products]
        products_counts = [row["nb_livraisons"] for row in top_products]
        
        # 📊 Activité par jour de la semaine (commandes par jour)
        seven_days_ago = (now - timedelta(days=6)).strftime("%Y-%m-%d")
        orders_raw = conn.execute("""
            SELECT 
                CASE strftime('%w', date_reservation)
                    WHEN '0' THEN 'Dim'
                    WHEN '1' THEN 'Lun'
                    WHEN '2' THEN 'Mar'
                    WHEN '3' THEN 'Mer'
                    WHEN '4' THEN 'Jeu'
                    WHEN '5' THEN 'Ven'
                    WHEN '6' THEN 'Sam'
                END AS jour,
                COUNT(*) AS total
            FROM orders
            WHERE situation IS NOT NULL
                AND date_reservation >= ?
            GROUP BY jour
        """, (seven_days_ago,)).fetchall()

        # 📊 IMPRESSIONS — feuilles & étuis par commande (mois courant)
        rows_imp = conn.execute("""
            SELECT 
                num_commande,
                COALESCE(SUM(feuilles),0) AS total_feuilles,
                COALESCE(SUM(etuis),0) AS total_etuis
            FROM impressions
            WHERE strftime('%m', date_impression) = ?
              AND strftime('%Y', date_impression) = ?
              AND num_commande IS NOT NULL
            GROUP BY num_commande
            ORDER BY (SUM(feuilles)+SUM(etuis)) DESC
            LIMIT 10
        """, (current_month, current_year)).fetchall()

        imp_cmd_labels = [r["num_commande"] for r in rows_imp]
        imp_feuilles = [r["total_feuilles"] for r in rows_imp]
        imp_etuis = [r["total_etuis"] for r in rows_imp]


        # ✂️ Top découpes par commande (mois courant)
        top_decoupe = conn.execute("""
            SELECT 
                num_commande,
                SUM(feuilles) AS total_feuilles
            FROM decoupage
            WHERE num_commande IS NOT NULL
                AND strftime('%m', date_decoupage) = ?
                AND strftime('%Y', date_decoupage) = ?
            GROUP BY num_commande
            ORDER BY total_feuilles DESC
            LIMIT 10
        """, (current_month, current_year)).fetchall()

        decoupe_cmd_labels = [r["num_commande"] for r in top_decoupe]
        decoupe_feuilles = [r["total_feuilles"] for r in top_decoupe]

        # 📦 Pliage — Top commandes (mois courant)
        top_pliage = conn.execute("""
            SELECT 
                num_commande,
                SUM(qte_pli) AS total_qte
            FROM pliage
            WHERE num_commande IS NOT NULL
                AND strftime('%m', date_pliage) = ?
                AND strftime('%Y', date_pliage) = ?
            GROUP BY num_commande
            ORDER BY total_qte DESC
            LIMIT 10
        """, (current_month, current_year)).fetchall()

        pliage_cmd_labels = [r["num_commande"] for r in top_pliage]
        pliage_qte = [r["total_qte"] for r in top_pliage]
    else:
        # Vue client → totaux spécifiques à son entreprise
        client = conn.execute("SELECT Entreprise FROM client WHERE N = ?", (current_user.client_id,)).fetchone()
        if client:
            client_name = client["Entreprise"]

            total_clients = 1
            total_orders = conn.execute("SELECT COUNT(*) FROM orders WHERE client = ?", (client_name,)).fetchone()[0]
            orders_livree = conn.execute("SELECT COUNT(*) FROM orders WHERE client = ? AND situation = 'LIVREE'", (client_name,)).fetchone()[0]
            orders_encours = conn.execute("SELECT COUNT(*) FROM orders WHERE client = ? AND situation = 'EN COURS'", (client_name,)).fetchone()[0]
            orders_livraison = conn.execute("SELECT COUNT(*) FROM orders WHERE client = ? AND situation = 'LIVRAISON'", (client_name,)).fetchone()[0]
            orders_bag = conn.execute("SELECT COUNT(*) FROM orders WHERE client = ? AND situation = 'BAG' COLLATE NOCASE",(client_name,)).fetchone()[0]
            total_delivery = conn.execute("SELECT COUNT(*) FROM delivery WHERE client = ?", (client_name,)).fetchone()[0]
            # ✳️ Livraisons du mois pour ce client uniquement
            new_deliveries = conn.execute("""
                SELECT COUNT(*) FROM delivery
                WHERE client = ?
                  AND date(date_livraison) >= date(?)
                  AND date(date_livraison) < date(?)
                """, (client_name, month_start, month_end)).fetchone()[0]

            # 📦 Produits les plus livrés (pour ce client uniquement)
            top_products = conn.execute("""
                SELECT produit, COUNT(*) AS nb_livraisons
                FROM delivery
                WHERE client = ?
                    AND date(date_livraison) >= date(?)
                    AND date(date_livraison) <  date(?)
                GROUP BY produit
                ORDER BY nb_livraisons DESC
                LIMIT 6
            """, (client_name, month_start, month_end)).fetchall()

            products_labels = [row["produit"] for row in top_products]
            products_counts = [row["nb_livraisons"] for row in top_products]

            # 📊 Activité par jour de la semaine (commandes par jour)
            seven_days_ago = (now - timedelta(days=6)).strftime("%Y-%m-%d")
            orders_raw = conn.execute("""
                SELECT 
                    CASE strftime('%w', date_reservation)
                        WHEN '0' THEN 'Dim'
                        WHEN '1' THEN 'Lun'
                        WHEN '2' THEN 'Mar'
                        WHEN '3' THEN 'Mer'
                        WHEN '4' THEN 'Jeu'
                        WHEN '5' THEN 'Ven'
                        WHEN '6' THEN 'Sam'
                    END AS jour,
                    COUNT(*) AS total
                FROM orders
                WHERE client = ? 
                    AND situation IS NOT NULL
                    AND date_reservation >= ?
                GROUP BY jour
            """, (client_name,seven_days_ago)).fetchall()
        else:
            total_clients = 0
            new_clients = 0
            total_orders = 0
            orders_livree = 0
            orders_encours = 0
            orders_livraison = 0
            orders_bag = 0
            total_delivery = 0
            new_deliveries = 0
            products_labels = []
            products_counts = []
            orders_raw = []
            imp_cmd_labels = []
            imp_feuilles = []
            imp_etuis = []
            decoupe_cmd_labels = []
            decoupe_feuilles = []
            pliage_cmd_labels = []
            pliage_qte = []

    # ✅ 1️⃣ Nouveau bloc : nombre de commandes par mois
    if current_user.role in ("superadmin", "admin"):
        rows = conn.execute("""
            SELECT strftime('%m', date_reservation) AS mois, COUNT(*) AS total
            FROM orders
            WHERE date_reservation IS NOT NULL
                AND strftime('%Y', date_reservation) = ?
            GROUP BY mois
            ORDER BY mois
        """, (current_year,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT strftime('%m', date_reservation) AS mois, COUNT(*) AS total
            FROM orders
            WHERE client = ? AND date_reservation IS NOT NULL
                AND strftime('%Y', date_reservation) = ?
            GROUP BY mois
            ORDER BY mois
        """, (client_name, current_year)).fetchall()

    # ✅ 2️⃣ Convertir en tableau 12 mois
    months_labels = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Jun', 'Jul', 'Aoû', 'Sep', 'Oct', 'Nov', 'Déc']
    monthly_counts = [0] * 12
    for r in rows:
        month_index = int(r['mois']) - 1
        monthly_counts[month_index] = r['total']

    # ✅ 3️⃣ Commandes par client
    if current_user.role in ("superadmin", "admin"):
        rows_clients = conn.execute("""
            SELECT client, COUNT(*) as total
            FROM orders
            WHERE client IS NOT NULL
                AND strftime('%m', date_reservation) = ?
                AND strftime('%Y', date_reservation) = ?
            GROUP BY client
            ORDER BY total DESC
            LIMIT 10
        """, (current_month, current_year)).fetchall()
    else:
        # Si client, on montre ses produits ou rien
        rows_clients = conn.execute("""
            SELECT produit, COUNT(*) as total
            FROM orders
            WHERE client = ? 
                AND produit IS NOT NULL
                AND strftime('%m', date_reservation) = ?
                AND strftime('%Y', date_reservation) = ?
            GROUP BY produit
            ORDER BY total DESC
            LIMIT 10
        """, (client_name, current_month, current_year)).fetchall()

    clients_labels = [r['client'] if 'client' in r.keys() else r['produit'] for r in rows_clients]
    clients_counts = [r['total'] for r in rows_clients]
    # --- Fallback automatique pour garantir les 7 jours ---
    days_labels = []
    days_dates = []
    days_counts = []

    working_days = []

    d = now

    # on récupère 7 jours ouvrés
    while len(working_days) < 7:
        # weekday(): Lun=0 ... Dim=6
        if d.weekday() not in (4,5):  # 4=Vendredi, 5=Samedi
            working_days.append(d)
        d -= timedelta(days=1)

    # on inverse pour affichage chronologique
    working_days.reverse()

    jour_map = ["Lun","Mar","Mer","Jeu","Ven","Sam","Dim"]

    for d in working_days:
        jour_txt = jour_map[d.weekday()]
        date_sql = d.strftime("%Y-%m-%d")
        date_display = d.strftime("%d-%m-%Y")

        count = conn.execute("""
            SELECT COUNT(*) FROM orders
            WHERE date(date_reservation) = date(?)
              AND situation IS NOT NULL
        """, (date_sql,)).fetchone()[0]

        days_labels.append(jour_txt)
        days_dates.append(f"{jour_txt} {date_display}")
        days_counts.append(count)

    conn.close()

    return render_template(
        "index.html",
        total_clients=total_clients,
        new_clients=new_clients,
        total_orders=total_orders,
        total_delivery=total_delivery,
        orders_livree=orders_livree,
        orders_encours=orders_encours,
        orders_livraison=orders_livraison,
        orders_bag=orders_bag,
        new_deliveries=new_deliveries,
        months=months_labels,
        monthly_counts=monthly_counts,
        clients_labels=clients_labels,
        clients_counts=clients_counts,
        # ↓↓↓ ajoute ceci ↓↓↓
        products_labels=products_labels,
        products_counts=products_counts,
        days_labels=days_labels,
        days_counts=days_counts,
        days_dates=days_dates,
        month_label=month_label,
        current_year=current_year,
        imp_cmd_labels=imp_cmd_labels,
        imp_feuilles=imp_feuilles,
        imp_etuis=imp_etuis,
        decoupe_cmd_labels=decoupe_cmd_labels,
        decoupe_feuilles=decoupe_feuilles,
        pliage_cmd_labels=pliage_cmd_labels,
        pliage_qte=pliage_qte,
    )

# ---- Dashboard (graphs) ----
@app.route('/api/weekly_activity')
def weekly_activity():
    return jsonify(get_weekly_activity())


# ---- Clients (pagination) ----
@app.route("/clients")
@login_required
def clients():
    conn = get_db_connection()

    page = request.args.get("page", 1, type=int)
    per_page = 9

    company = (request.args.get("company") or "").strip()

    query = """
        SELECT 
            N AS id, 
            Entreprise AS company_name, 
            Contact AS contact_name, 
            Tel AS phone, 
            Email AS email
        FROM client
        WHERE 1=1
    """

    count_query = "SELECT COUNT(*) FROM client WHERE 1=1"

    params = []
    count_params = []

    # 🔎 filtre entreprise
    if company:
        pattern = "%" + "%".join(company.split()) + "%"
        query += " AND Entreprise LIKE ? COLLATE NOCASE"
        count_query += " AND Entreprise LIKE ? COLLATE NOCASE"
        params.append(pattern)
        count_params.append(pattern)

    query += " ORDER BY N ASC LIMIT ? OFFSET ?"
    params.extend([per_page, (page - 1) * per_page])

    clients_list = conn.execute(query, params).fetchall()

    total_clients = conn.execute(count_query, count_params).fetchone()[0]

    total_pages = (total_clients + per_page - 1) // per_page

    start = (page - 1) * per_page + 1 if total_clients > 0 else 0
    end = min(page * per_page, total_clients)

    # Liste pour Select2
    companies = [
        r["Entreprise"] for r in conn.execute(
            "SELECT DISTINCT Entreprise FROM client ORDER BY Entreprise"
        ).fetchall()
        if r["Entreprise"]
    ]

    conn.close()

    return render_template(
        "clients.html",
        clients=clients_list,
        page=page,
        total_pages=total_pages,
        start=start,
        end=end,
        total_clients=total_clients,
        companies=companies,
        company=company
    )


# ---- Orders (pagination + filtres) ----
@app.route("/orders")
@login_required
def orders():
    conn = get_db_connection()

    page = request.args.get("page", 1, type=int)
    per_page = 9
    period = request.args.get("period", "all")
    status = request.args.get("status", "all")
    client = request.args.get("client", "").strip()
    product = request.args.get("product", "").strip()
    cmdcl = request.args.get("cmdcl", "").strip()

    if status and status != "all":
        status = status.upper()

    query = """
        SELECT 
            num_reservation, cmdl, client, produit, qte,
            date_reservation, situation, reste, total_livre
        FROM orders
        WHERE 1=1
    """
    count_query = "SELECT COUNT(*) FROM orders WHERE 1=1"
    params, count_params = [], []

    today = datetime.today().date()
    start_date = request.args.get("start") or ""
    end_date = request.args.get("end") or ""

    # Restriction si client connecté
    if current_user.role == "client":
        client_name = conn.execute(
            "SELECT Entreprise FROM client WHERE N = ?", (current_user.client_id,)
        ).fetchone()["Entreprise"]
        query += " AND client = ?"
        count_query += " AND client = ?"
        params.append(client_name)
        count_params.append(client_name)

    # Filtres...
    if period == "today":
        query += " AND date(date_reservation) = ?"
        count_query += " AND date(date_reservation) = ?"
        params.append(today)
        count_params.append(today)
    elif period == "yesterday":
        y = today - timedelta(days=1)
        query += " AND date(date_reservation) = ?"
        count_query += " AND date(date_reservation) = ?"
        params.append(y)
        count_params.append(y)
    elif period == "week":
        start = today - timedelta(days=today.weekday())
        query += " AND date(date_reservation) >= ?"
        count_query += " AND date(date_reservation) >= ?"
        params.append(start)
        count_params.append(start)
    elif period == "month":
        start = today.replace(day=1)
        query += " AND date(date_reservation) >= ?"
        count_query += " AND date(date_reservation) >= ?"
        params.append(start)
        count_params.append(start)
    elif period == "year":
        start = today.replace(month=1, day=1)
        query += " AND date(date_reservation) >= ?"
        count_query += " AND date(date_reservation) >= ?"
        params.append(start)
        count_params.append(start)
    elif period == "custom" and start_date and end_date:
        query += " AND date(date_reservation) BETWEEN ? AND ?"
        count_query += " AND date(date_reservation) BETWEEN ? AND ?"
        params.extend([start_date, end_date])
        count_params.extend([start_date, end_date])

    if status != "all":
        query += " AND situation = ? COLLATE NOCASE"
        count_query += " AND situation = ? COLLATE NOCASE"
        params.append(status)
        count_params.append(status)

    if cmdcl:
        query += " AND TRIM(cmdl) = TRIM(?)"
        count_query += " AND TRIM(cmdl) = TRIM(?)"
        params.append(cmdcl)
        count_params.append(cmdcl)

    if client and current_user.role in ["superadmin","admin"]:
        tokens = [t for t in client.split() if t]
        pattern = "%" + "%".join(tokens) + "%"
        query += " AND client LIKE ? COLLATE NOCASE"
        count_query += " AND client LIKE ? COLLATE NOCASE"
        params.append(pattern)
        count_params.append(pattern)

    if product:
        tokens = [t for t in product.split() if t]
        pattern = "%" + "%".join(tokens) + "%"
        query += " AND produit LIKE ? COLLATE NOCASE"
        count_query += " AND produit LIKE ? COLLATE NOCASE"
        params.append(pattern)
        count_params.append(pattern)

    query += " ORDER BY date_reservation DESC LIMIT ? OFFSET ?"
    params.extend([per_page, (page - 1) * per_page])

    # --- Listes pour Select2 ---
    clients_list = conn.execute(
        "SELECT DISTINCT client FROM orders ORDER BY client"
    ).fetchall()

    products_list = conn.execute(
        "SELECT DISTINCT produit FROM orders ORDER BY produit"
    ).fetchall()

    cmdcl_list = conn.execute(
    "SELECT DISTINCT cmdl FROM orders ORDER BY cmdl DESC"
    ).fetchall()


    clients = [c["client"] for c in clients_list if c["client"]]
    products = [p["produit"] for p in products_list if p["produit"]]
    cmdcls = [c["cmdl"] for c in cmdcl_list if c["cmdl"]]

    orders_list = conn.execute(query, params).fetchall()
    total_orders = conn.execute(count_query, count_params).fetchone()[0]
    total_pages = (total_orders + per_page - 1) // per_page

    start_idx = (page - 1) * per_page + 1 if total_orders > 0 else 0
    end_idx = min(page * per_page, total_orders)

    conn.close()
    return render_template(
        "orders.html",
        orders=orders_list,
        page=page,
        total_pages=total_pages,
        start=start_date,
        end=end_date,
        total_orders=total_orders,
        start_idx=start_idx,
        end_idx=end_idx,
        period=period,
        status=status,
        client=client,
        product=product,
        clients = clients,
        products=products,
        cmdcl=cmdcl,
        cmdcls=cmdcls
    )

@app.route("/api/cmdcl-search")
@login_required
def cmdcl_search():
    term = request.args.get("term", "").strip()

    conn = get_db_connection()

    query = """
        SELECT DISTINCT cmdl 
        FROM orders
        WHERE cmdl LIKE ?
        ORDER BY cmdl DESC
        LIMIT 20
    """

    rows = conn.execute(query, (f"%{term}%",)).fetchall()
    conn.close()

    results = [{"id": r["cmdl"], "text": r["cmdl"]} for r in rows]

    return {"results": results}

# ---- Orders by client ----
@app.route("/clients/<int:client_id>/orders")
@login_required
def client_orders(client_id):
    conn = get_db_connection()

    client = conn.execute(
        "SELECT N AS id, Entreprise AS company_name FROM client WHERE N = ?",
        (client_id,)
    ).fetchone()
    if not client:
        conn.close()
        return "Client not found", 404

    if current_user.role == "client" and current_user.client_id != client_id:
        conn.close()
        flash("Accès refusé ❌", "danger")
        return redirect(url_for("orders"))

    page = request.args.get("page", 1, type=int)
    per_page = 9

    orders_list = conn.execute(
        """
        SELECT 
            num_reservation, cmdl, client, produit, qte,
            date_reservation, situation, reste, total_livre
        FROM orders
        WHERE client = ?
        ORDER BY date_reservation DESC
        LIMIT ? OFFSET ?
        """,
        (client["company_name"], per_page, (page - 1) * per_page),
    ).fetchall()

    total_orders = conn.execute(
        "SELECT COUNT(*) FROM orders WHERE client = ?",
        (client["company_name"],)
    ).fetchone()[0]
    total_pages = (total_orders + per_page - 1) // per_page

    start = (page - 1) * per_page + 1 if total_orders > 0 else 0
    end = min(page * per_page, total_orders)

    conn.close()
    return render_template(
        "client_orders.html",
        client=client,
        orders=orders_list,
        page=page,
        total_pages=total_pages,
        start=start,
        end=end,
        total_orders=total_orders
    )

# ---- Delivery (pagination + filtres) ----
@app.route("/delivery")
@login_required
def delivery():
    conn = get_db_connection()

    page = request.args.get("page", 1, type=int)
    per_page = 9
    period = request.args.get("period", "all")
    client = request.args.get("client", "").strip()
    product = request.args.get("product", "").strip()

    start_date = request.args.get("start") or ""
    end_date = request.args.get("end") or ""

    query = """
        SELECT 
            nl, code_client, client, qte, montant, num_reservation,
            utilisateur, date_livraison, facture, num_livraison,
            observation, produit
        FROM delivery
        WHERE 1=1
    """

    count_query = "SELECT COUNT(*) FROM delivery WHERE 1=1"
    params, count_params = [], []

    today = datetime.today().date()

    # --- Restriction client ---
    if current_user.role == "client":
        query += " AND code_client = ?"
        count_query += " AND code_client = ?"
        params.append(current_user.client_id)
        count_params.append(current_user.client_id)

    # --- Filtres période ---
    if period == "today":
        query += " AND date(date_livraison) = ?"
        count_query += " AND date(date_livraison) = ?"
        params.append(today)
        count_params.append(today)

    elif period == "yesterday":
        y = today - timedelta(days=1)
        query += " AND date(date_livraison) = ?"
        count_query += " AND date(date_livraison) = ?"
        params.append(y)
        count_params.append(y)

    elif period == "week":
        start = today - timedelta(days=today.weekday())
        query += " AND date(date_livraison) >= ?"
        count_query += " AND date(date_livraison) >= ?"
        params.append(start)
        count_params.append(start)

    elif period == "month":
        start = today.replace(day=1)
        query += " AND date(date_livraison) >= ?"
        count_query += " AND date(date_livraison) >= ?"
        params.append(start)
        count_params.append(start)

    elif period == "year":
        start = today.replace(month=1, day=1)
        query += " AND date(date_livraison) >= ?"
        count_query += " AND date(date_livraison) >= ?"
        params.append(start)
        count_params.append(start)

    elif period == "custom" and start_date and end_date:
        query += " AND date(date_livraison) BETWEEN ? AND ?"
        count_query += " AND date(date_livraison) BETWEEN ? AND ?"
        params.extend([start_date, end_date])
        count_params.extend([start_date, end_date])

    # --- Client filter ---
    if client and current_user.role in ["superadmin","admin"]:
        pattern = "%" + "%".join(client.split()) + "%"
        query += " AND client LIKE ? COLLATE NOCASE"
        count_query += " AND client LIKE ? COLLATE NOCASE"
        params.append(pattern)
        count_params.append(pattern)

    # --- Produit filter ---
    if product:
        pattern = "%" + "%".join(product.split()) + "%"
        query += " AND produit LIKE ? COLLATE NOCASE"
        count_query += " AND produit LIKE ? COLLATE NOCASE"
        params.append(pattern)
        count_params.append(pattern)

    query += " ORDER BY date_livraison DESC LIMIT ? OFFSET ?"
    params.extend([per_page, (page - 1) * per_page])

    # --- Listes Select2 ---
    clients = [c["client"] for c in conn.execute(
        "SELECT DISTINCT client FROM delivery ORDER BY client"
    ).fetchall() if c["client"]]

    products = [p["produit"] for p in conn.execute(
        "SELECT DISTINCT produit FROM delivery ORDER BY produit"
    ).fetchall() if p["produit"]]

    delivery_list = conn.execute(query, params).fetchall()
    total_delivery = conn.execute(count_query, count_params).fetchone()[0]

    start_idx = (page - 1) * per_page + 1 if total_delivery else 0
    end_idx = min(page * per_page, total_delivery)

    conn.close()

    return render_template(
        "delivery.html",
        delivery=delivery_list,
        page=page,
        total_pages=(total_delivery + per_page - 1)//per_page,
        start=start_date,
        end=end_date,
        start_idx=start_idx,
        end_idx=end_idx,
        total_delivery=total_delivery,
        period=period,
        client=client,
        product=product,
        clients=clients,
        products=products
    )

# ---- Delivery by client ----
@app.route("/clients/<int:client_id>/delivery")
@login_required
def client_delivery(client_id):
    conn = get_db_connection()

    client = conn.execute(
        "SELECT N AS id, Entreprise AS company_name FROM client WHERE N = ?",
        (client_id,)
    ).fetchone()
    if not client:
        conn.close()
        return "Client not found", 404

    if current_user.role == "client" and current_user.client_id != client_id:
        conn.close()
        flash("Accès refusé ❌", "danger")
        return redirect(url_for("delivery"))

    page = request.args.get("page", 1, type=int)
    per_page = 9

    delivery_list = conn.execute(
        """
        SELECT 
            nl, code_client, client, qte, montant, num_reservation,
            utilisateur, date_livraison, facture, num_livraison,
            observation, produit
        FROM delivery
        WHERE code_client = ?
        ORDER BY date_livraison DESC
        LIMIT ? OFFSET ?
        """,
        (client_id, per_page, (page - 1) * per_page),
    ).fetchall()

    total_delivery = conn.execute(
        "SELECT COUNT(*) FROM delivery WHERE code_client = ?",
        (client_id,)
    ).fetchone()[0]
    total_pages = (total_delivery + per_page - 1) // per_page

    start = (page - 1) * per_page + 1 if total_delivery > 0 else 0
    end = min(page * per_page, total_delivery)

    conn.close()
    return render_template(
        "client_delivery.html",
        client=client,
        delivery=delivery_list,
        page=page,
        total_pages=total_pages,
        start=start,
        end=end,
        total_delivery=total_delivery
    )

# ---- Delivery by order ----
@app.route("/orders/<int:order_id>/delivery")
@login_required
def order_delivery(order_id):
    conn = get_db_connection()

    page = request.args.get("page", 1, type=int)
    per_page = 9
    from_client = request.args.get("from_client")

    delivery_list = conn.execute(
        """
        SELECT 
            nl, code_client, client, qte, montant, num_reservation,
            utilisateur, date_livraison, facture, num_livraison,
            observation, produit
        FROM delivery
        WHERE num_reservation = ?
        ORDER BY date_livraison DESC
        LIMIT ? OFFSET ?
        """,
        (order_id, per_page, (page - 1) * per_page),
    ).fetchall()

    total_delivery = conn.execute(
        "SELECT COUNT(*) FROM delivery WHERE num_reservation = ?",
        (order_id,)
    ).fetchone()[0]
    total_pages = (total_delivery + per_page - 1) // per_page

    start = (page - 1) * per_page + 1 if total_delivery > 0 else 0
    end = min(page * per_page, total_delivery)

    conn.close()

    if current_user.role == "client":
        check = get_db_connection().execute(
            "SELECT client FROM orders WHERE num_reservation = ?", (order_id,)
        ).fetchone()
        if not check:
            flash("Commande introuvable ❌", "danger")
            return redirect(url_for("orders"))
        client_name = get_db_connection().execute(
            "SELECT Entreprise FROM client WHERE N = ?", (current_user.client_id,)
        ).fetchone()["Entreprise"]
        if check["client"] != client_name:
            flash("Accès refusé ❌", "danger")
            return redirect(url_for("orders"))

    return render_template(
        "order_delivery.html",
        order_id=order_id,
        delivery=delivery_list,
        page=page,
        total_pages=total_pages,
        start=start,
        end=end,
        total_delivery=total_delivery,
        from_client=from_client
    )

# ---- Créer un compte utilisateur pour un client ----
@app.route("/admin/create_user", methods=["GET", "POST"])
@login_required
def create_user():
    if current_user.role not in ("admin", "superadmin"):
        flash("Accès refusé : réservé aux administrateurs !", "danger")
        return redirect(url_for("index"))

    # --- Liste des clients depuis local.sqlite ---
    conn_local = get_db_connection()
    clients = conn_local.execute("SELECT N AS id, Entreprise AS company_name FROM client").fetchall()
    conn_local.close()

    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()
        role = request.form.get("role", "client")

        # Sécurité superadmin
        if role == "admin" and current_user.role != "superadmin":
            flash("Seul un superadmin peut créer un admin", "danger")
            return redirect(url_for("create_user"))
        
        if role == "admin":
            client_id = None
        else:
            client_id = int(request.form["client_id"])

        conn_auth = get_auth_connection()

        exists = conn_auth.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        
        if exists:
            flash("Username déjà existant", "danger")
            conn_auth.close()
            return redirect(url_for("create_user"))

        password_hash = generate_password_hash(password)
        conn_auth.execute(
            "INSERT INTO users (username, password_hash, role, client_id) VALUES (?, ?, ?, ?)",
            (username, password_hash, role, client_id)
        )
        conn_auth.commit()
        conn_auth.close()

        flash(f"✅ Compte '{username}' créé", "success")
        # Redirection vers la page des utilisateurs, pas celle des clients
        return redirect(url_for("list_users"))

    return render_template("create_user.html", clients=clients)

# ---- Liste et suppression des utilisateurs ----
@app.route("/admin/users")
@login_required
def list_users():

    print(current_user.role)

    if current_user.role not in ["superadmin", "admin"]:
        flash("Accès refusé ❌", "danger")
        return redirect(url_for("index"))

    page = request.args.get("page", 1, type=int)
    per_page = 9
    offset = (page - 1) * per_page

    # 🔹 Auth DB
    conn_auth = get_auth_connection()

    total_users = conn_auth.execute(
        "SELECT COUNT(*) as count FROM users"
    ).fetchone()["count"]

    users = conn_auth.execute("""
        SELECT id, username, role, client_id, is_active, created_at
        FROM users
        ORDER BY 
            CASE role WHEN 'superadmin' THEN 0 WHEN 'admin' THEN 1 ELSE 2 END,
            id ASC
        LIMIT ? OFFSET ?
    """, (per_page, offset)).fetchall()

    conn_auth.close()

    # 🔹 Clients DB
    conn_local = get_db_connection()
    clients = conn_local.execute(
        "SELECT N, Entreprise FROM client"
    ).fetchall()
    conn_local.close()

    clients_map = {c["N"]: c["Entreprise"] for c in clients}

    enriched_users = []
    for u in users:
        enriched_users.append({
            "id": u["id"],
            "username": u["username"],
            "role": u["role"],
            "client_name": clients_map.get(u["client_id"], "(aucun)"),
            "is_active": u["is_active"],
            "created_at": u["created_at"]
        })

    total_pages = (total_users + per_page - 1) // per_page

    start = offset + 1 if total_users > 0 else 0
    end = min(offset + per_page, total_users)

    return render_template(
        "list_users.html",
        users=enriched_users,
        page=page,
        total_pages=total_pages,
        total_users=total_users,
        start=start,
        end=end
    )

@app.route("/admin/users/delete/<int:user_id>", methods=["POST"])
@login_required
def delete_user(user_id):

    if current_user.role not in ["superadmin", "admin"]:
        flash("Accès refusé ❌", "danger")
        return redirect(url_for("index"))

    conn_auth = get_auth_connection()

    # Vérifier utilisateur cible
    user = conn_auth.execute(
        "SELECT id, role FROM users WHERE id = ?",
        (user_id,)
    ).fetchone()

    if not user:
        flash("Utilisateur introuvable ❌", "danger")
        conn_auth.close()
        return redirect(url_for("list_users"))

    # ❌ Interdire suppression superadmin
    if user["role"] == "superadmin":
        flash("Impossible de supprimer un superadmin ❌", "danger")
        conn_auth.close()
        return redirect(url_for("list_users"))
    
    # ❌ admin ne peut pas supprimer admin
    if current_user.role == "admin" and user["role"] == "admin":
        flash("Un admin ne peut pas supprimer un autre admin", "danger")
        return redirect(url_for("list_users"))

    # ❌ Empêcher auto-suppression
    if user["id"] == current_user.id:
        flash("Vous ne pouvez pas vous supprimer vous-même ❌", "danger")
        conn_auth.close()
        return redirect(url_for("list_users"))

    # ✅ Suppression autorisée
    conn_auth.execute(
        "DELETE FROM users WHERE id = ?",
        (user_id,)
    )
    conn_auth.commit()
    conn_auth.close()

    flash("✅ Utilisateur supprimé", "success")
    return redirect(url_for("list_users"))


@app.route("/impression")
@login_required
def impression():

    conn = get_db_connection()
    cur = conn.cursor()

    # ---- filtres ----
    period = request.args.get("period", "all")
    article = (request.args.get("article") or "").strip()
    commande = (request.args.get("commande") or "").strip()
    user = (request.args.get("user") or "").strip()
    start = request.args.get("start") or ""
    end = request.args.get("end") or ""

    # ---- pagination ----
    page = request.args.get("page", 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

    today = date.today()

    # =========================
    # 📅 Gestion périodes
    # =========================
    def period_bounds(period, start, end):
        if period == "all":
            return None, None
        if period == "today":
            return today, today
        if period == "yesterday":
            d = today - timedelta(days=1)
            return d, d
        if period == "week":
            monday = today - timedelta(days=today.weekday())
            return monday, monday + timedelta(days=6)
        if period == "month":
            first = today.replace(day=1)
            last = date(today.year, today.month,
                        calendar.monthrange(today.year, today.month)[1])
            return first, last
        if period == "year":
            return date(today.year,1,1), date(today.year,12,31)
        if period == "custom" and start and end:
            try:
                return date.fromisoformat(start), date.fromisoformat(end)
            except:
                return None, None
        return None, None

    start_date, end_date = period_bounds(period, start, end)

    # =========================
    # 🎯 WHERE dynamique
    # =========================
    where_clauses = []
    params = []

    # période
    if start_date and end_date:
        where_clauses.append(
            "date(date_impression) BETWEEN date(?) AND date(?)"
        )
        params.extend([start_date, end_date])

    # commande
    if commande:
        where_clauses.append("TRIM(o.cmdl) = TRIM(?)")
        params.append(commande)

    # article
    if article:
        pattern = "%" + "%".join(article.split()) + "%"
        where_clauses.append("article LIKE ?")
        params.append(pattern)

    # user
    if user:
        pattern = "%" + "%".join(user.split()) + "%"
        where_clauses.append("user LIKE ?")
        params.append(pattern)

    where_sql = ""
    if where_clauses:
        where_sql = " WHERE " + " AND ".join(where_clauses)

    # =========================
    # 📦 DATA QUERY
    # =========================
    data_query = f"""
        SELECT 
            i.num_impression,
            i.date_impression,
            i.hr,
            i.num_commande,
            o.cmdl AS cmdcl,
            i.machine,
            i.article,
            i.feuilles,
            i.etuis,
            i.user,
            datetime(date(i.date_impression) || ' ' || IFNULL(i.hr,'00:00')) AS datetime_full
        FROM impressions i
        INNER JOIN orders o 
            ON i.num_commande = o.num_reservation
        {where_sql}
        ORDER BY i.date_impression DESC
        LIMIT ? OFFSET ?
    """

    rows = cur.execute(
        data_query,
        params + [per_page, offset]
    ).fetchall()

    # =========================
    # 🔢 COUNT QUERY
    # =========================
    count_query = f"""
        SELECT COUNT(*)
        FROM impressions i
        INNER JOIN orders o
            ON i.num_commande = o.num_reservation
        {where_sql}
    """

    total = cur.execute(count_query, params).fetchone()[0]

    # =========================
    # 📊 TOTALS QUERY
    # =========================
    totals_query = f"""
        SELECT 
            COALESCE(SUM(i.feuilles),0),
            COALESCE(SUM(i.etuis),0)
        FROM impressions i
        INNER JOIN orders o
            ON i.num_commande = o.num_reservation
        {where_sql}
    """

    total_feuilles, total_etuis = cur.execute(
        totals_query,
        params
    ).fetchone()

    # =========================
    # 📋 listes filtres
    # =========================
    users = [r[0] for r in cur.execute(
        "SELECT DISTINCT user FROM impressions ORDER BY user"
    ).fetchall()]

    articles = [r[0] for r in cur.execute(
        "SELECT DISTINCT article FROM impressions ORDER BY article"
    ).fetchall()]

    conn.close()

    # pagination info
    total_pages = (total + per_page - 1) // per_page
    start_idx = offset + 1 if total else 0
    end_idx = min(offset + per_page, total)

    return render_template(
        "impression.html",
        impression=rows,
        period=period,
        article=article,
        user=user,
        start=start,
        end=end,
        page=page,
        total_pages=total_pages,
        start_idx=start_idx,
        end_idx=end_idx,
        total=total,
        total_feuilles=total_feuilles,
        total_etuis=total_etuis,
        users=users,
        articles=articles,
        commande=commande
    )

@app.route("/api/commandes-search")
@login_required
def commandes_search():

    term = request.args.get("term","").strip()

    conn = get_db_connection()

    rows = conn.execute("""
        SELECT DISTINCT o.cmdl
        FROM orders o
        WHERE o.cmdl LIKE ?
          AND EXISTS (
            SELECT 1
            FROM impressions i
            WHERE i.num_commande = o.num_reservation
          )
        ORDER BY o.cmdl DESC
        LIMIT 20
    """, (f"%{term}%",)).fetchall()

    conn.close()

    return jsonify({
        "results":[
            {"id":r["cmdl"],"text":r["cmdl"]}
            for r in rows if r["cmdl"]
        ]
    })


@app.route("/decoupe")
@login_required
def decoupe():

    conn = get_db_connection()
    cur = conn.cursor()

    # ---- filtres ----
    period = request.args.get("period", "all")
    user = (request.args.get("user") or "").strip()
    article = (request.args.get("article") or "").strip()
    commande = (request.args.get("commande") or "").strip()
    start = request.args.get("start") or ""
    end = request.args.get("end") or ""

    # ---- pagination ----
    page = request.args.get("page", 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

    today = date.today()

    # =========================
    # 📅 Gestion périodes
    # =========================
    def get_bounds(period, start, end):
        if period == "all": return None, None
        if period == "today": return today, today
        if period == "yesterday":
            d = today - timedelta(days=1)
            return d, d
        if period == "week":
            mon = today - timedelta(days=today.weekday())
            return mon, mon + timedelta(days=6)
        if period == "month":
            first = today.replace(day=1)
            last = date(today.year, today.month,
                        calendar.monthrange(today.year, today.month)[1])
            return first, last
        if period == "year":
            return date(today.year,1,1), date(today.year,12,31)
        if period == "custom" and start and end:
            try:
                return date.fromisoformat(start), date.fromisoformat(end)
            except:
                return None, None
        return None, None

    start_date, end_date = get_bounds(period, start, end)

    # =========================
    # 🎯 WHERE dynamique
    # =========================
    where_clauses = []
    params = []

    # période
    if start_date and end_date:
        where_clauses.append(
            "date(date_decoupage) BETWEEN date(?) AND date(?)"
        )
        params.extend([start_date, end_date])

    # commande
    if commande:
        where_clauses.append("TRIM(o.cmdl) = TRIM(?)")
        params.append(commande)

    # article (description)
    if article:
        pattern = "%" + "%".join(article.split()) + "%"
        where_clauses.append("description LIKE ?")
        params.append(pattern)

    # user
    if user:
        pattern = "%" + "%".join(user.split()) + "%"
        where_clauses.append("user LIKE ?")
        params.append(pattern)

    where_sql = ""
    if where_clauses:
        where_sql = " WHERE " + " AND ".join(where_clauses)

    # =========================
    # 📦 DATA QUERY
    # =========================
    data_query = f"""
        SELECT 
            d.num_decoupage,
            d.num_impression,
            d.date_decoupage,
            d.hr,
            d.num_commande,
            o.cmdl AS cmdcl,
            d.maquette_id,
            d.description,
            d.feuilles,
            d.user,
            datetime(date(d.date_decoupage) || ' ' || IFNULL(d.hr,'00:00')) AS datetime_full
        FROM decoupage d
        INNER JOIN orders o
            ON d.num_commande = o.num_reservation
        {where_sql}
        ORDER BY d.num_decoupage DESC
        LIMIT ? OFFSET ?
    """

    rows = cur.execute(
        data_query,
        params + [per_page, offset]
    ).fetchall()

    # =========================
    # 🔢 COUNT
    # =========================
    count_query = f"""
        SELECT COUNT(*)
        FROM decoupage d
        INNER JOIN orders o
            ON d.num_commande = o.num_reservation
        {where_sql}
    """

    total = cur.execute(count_query, params).fetchone()[0]

    # =========================
    # 📊 TOTALS FILTRÉS
    # =========================
    totals_query = f"""
        SELECT COALESCE(SUM(feuilles),0)
        FROM decoupage d
        INNER JOIN orders o
            ON d.num_commande = o.num_reservation
        {where_sql}
    """

    total_feuilles = cur.execute(
        totals_query,
        params
    ).fetchone()[0]

    # =========================
    # 📋 Listes filtres
    # =========================
    users = [r[0] for r in cur.execute(
        "SELECT DISTINCT user FROM decoupage ORDER BY user"
    ).fetchall()]

    articles = [r[0] for r in cur.execute(
        "SELECT DISTINCT description FROM decoupage ORDER BY description"
    ).fetchall()]

    conn.close()

    # pagination info
    total_pages = (total + per_page - 1) // per_page
    start_idx = offset + 1 if total else 0
    end_idx = min(offset + per_page, total)

    return render_template(
        "decoupe.html",
        decoupage=rows,
        period=period,
        user=user,
        article=article,
        start=start,
        end=end,
        page=page,
        total_pages=total_pages,
        start_idx=start_idx,
        end_idx=end_idx,
        total=total,
        total_feuilles=total_feuilles,
        users=users,
        articles=articles,
        commande=commande
    )

@app.route("/pliage")
@login_required
def pliage():

    conn = get_db_connection()
    cur = conn.cursor()

    # =========================
    # 🔎 Filtres
    # =========================
    period = request.args.get("period", "all")
    user = (request.args.get("user") or "").strip()
    article = (request.args.get("article") or "").strip()
    commande = (request.args.get("commande") or "").strip()
    start = request.args.get("start") or ""
    end = request.args.get("end") or ""

    # =========================
    # 📄 Pagination
    # =========================
    page = request.args.get("page", 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

    today = date.today()

    # =========================
    # 📅 Périodes
    # =========================
    def period_bounds(period, start, end):
        if period == "all": return None, None
        if period == "today": return today, today
        if period == "yesterday":
            d = today - timedelta(days=1)
            return d, d
        if period == "week":
            mon = today - timedelta(days=today.weekday())
            return mon, mon + timedelta(days=6)
        if period == "month":
            first = today.replace(day=1)
            last = date(today.year, today.month,
                        calendar.monthrange(today.year, today.month)[1])
            return first, last
        if period == "year":
            return date(today.year,1,1), date(today.year,12,31)
        if period == "custom" and start and end:
            try:
                return date.fromisoformat(start), date.fromisoformat(end)
            except:
                return None, None
        return None, None

    start_date, end_date = period_bounds(period, start, end)

    # =========================
    # 🎯 WHERE dynamique
    # =========================
    where_clauses = []
    params = []

    # Date
    if start_date and end_date:
        where_clauses.append(
            "date(date_pliage) BETWEEN date(?) AND date(?)"
        )
        params.extend([start_date, end_date])

    # commande
    if commande:
        where_clauses.append("TRIM(o.cmdl) = TRIM(?)")
        params.append(commande)
    
    # User
    if user:
        pattern = "%" + "%".join(user.split()) + "%"
        where_clauses.append("user LIKE ?")
        params.append(pattern)

    # Article
    if article:
        pattern = "%" + "%".join(article.split()) + "%"
        where_clauses.append("description LIKE ?")
        params.append(pattern)

    where_sql = ""
    if where_clauses:
        where_sql = " WHERE " + " AND ".join(where_clauses)

    # =========================
    # 📦 DATA QUERY
    # =========================
    data_query = f"""
        SELECT 
            p.*,
            o.cmdl AS cmdcl,
            datetime(date(p.date_pliage) || ' ' || IFNULL(p.hr,'00:00')) AS datetime_full
        FROM pliage p
        INNER JOIN orders o
            ON p.num_commande = o.num_reservation
        {where_sql}
        ORDER BY p.date_pliage DESC
        LIMIT ? OFFSET ?
    """

    rows = cur.execute(
        data_query,
        params + [per_page, offset]
    ).fetchall()

    # =========================
    # 🔢 COUNT
    # =========================
    count_query = f"""
        SELECT COUNT(*)
        FROM pliage p
        INNER JOIN orders o
            ON p.num_commande = o.num_reservation
        {where_sql}
    """

    total = cur.execute(count_query, params).fetchone()[0]

    # =========================
    # 📊 TOTALS FILTRÉS
    # =========================
    totals_query = f"""
        SELECT COALESCE(SUM(qte_pli),0)
        FROM pliage p
        INNER JOIN orders o
            ON p.num_commande = o.num_reservation
        {where_sql}
    """

    total_qte = cur.execute(
        totals_query,
        params
    ).fetchone()[0]

    # =========================
    # 📋 Listes filtres
    # =========================
    users = [r[0] for r in cur.execute(
        "SELECT DISTINCT user FROM pliage ORDER BY user"
    ).fetchall()]

    articles = [r[0] for r in cur.execute(
        "SELECT DISTINCT description FROM pliage ORDER BY description"
    ).fetchall()]

    conn.close()

    # =========================
    # 📄 Pagination info
    # =========================
    total_pages = (total + per_page - 1) // per_page
    start_idx = offset + 1 if total else 0
    end_idx = min(offset + per_page, total)

    return render_template(
        "pliage.html",
        pliage=rows,
        period=period,
        user=user,
        article=article,
        start=start,
        end=end,
        page=page,
        total_pages=total_pages,
        start_idx=start_idx,
        end_idx=end_idx,
        total=total,
        total_qte=total_qte,
        users=users,
        articles=articles,
        commande=commande
    )


if __name__ == "__main__":
    #app.run(debug=True, port=8888)
    app.run(host="0.0.0.0", port=8888, debug=True)
