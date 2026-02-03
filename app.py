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
    if current_user.role == "admin":
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
    if request.method == "POST":
        username = request.form["username"].strip().lower()
        password = request.form["password"]
        user = get_user_by_username(username)

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            session["welcome"] = True
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
    return render_template("home.html", current_year=datetime.now().year)

# ---- Dashboard ----
@app.route("/index")
@login_required
def index():
    conn = get_db_connection()
    now = datetime.now()
    current_month = f"{now.month:02d}"
    current_year = str(now.year)

    # Vue admin → totaux globaux
    if current_user.role == "admin":
        total_clients = conn.execute("SELECT COUNT(*) FROM client").fetchone()[0]
        total_orders = conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
        orders_livree = conn.execute("SELECT COUNT(*) FROM orders WHERE situation = 'LIVREE'").fetchone()[0]
        orders_encours = conn.execute("SELECT COUNT(*) FROM orders WHERE situation = 'EN COURS'").fetchone()[0]
        orders_livraison = conn.execute("SELECT COUNT(*) FROM orders WHERE situation = 'LIVRAISON'").fetchone()[0]
        total_delivery = conn.execute("SELECT COUNT(*) FROM delivery").fetchone()[0]

        # ✳️ Livraisons du mois en cours
        new_deliveries = conn.execute("""
            SELECT COUNT(*) FROM delivery
            WHERE strftime('%m', date_livraison) = ? AND strftime('%Y', date_livraison) = ?
        """, (current_month, current_year)).fetchone()[0]

        # 📦 Produits les plus livrés (Top 6)
        top_products = conn.execute("""
            SELECT produit, COUNT(*) AS nb_livraisons
            FROM delivery
            GROUP BY produit
            ORDER BY nb_livraisons DESC
            LIMIT 6
        """).fetchall()

        products_labels = [row["produit"] for row in top_products]
        products_counts = [row["nb_livraisons"] for row in top_products]
        
        # 📊 Activité par jour de la semaine (commandes par jour)
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
            GROUP BY jour
        """).fetchall()
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
            total_delivery = conn.execute("SELECT COUNT(*) FROM delivery WHERE client = ?", (client_name,)).fetchone()[0]
            # ✳️ Livraisons du mois pour ce client uniquement
            new_deliveries = conn.execute("""
                SELECT COUNT(*) FROM delivery
                WHERE client = ? AND strftime('%m', date_livraison) = ? AND strftime('%Y', date_livraison) = ?
            """, (client_name, current_month, current_year)).fetchone()[0]

            # 📦 Produits les plus livrés (pour ce client uniquement)
            top_products = conn.execute("""
                SELECT produit, COUNT(*) AS nb_livraisons
                FROM delivery
                WHERE client = ?
                GROUP BY produit
                ORDER BY nb_livraisons DESC
                LIMIT 6
            """, (client_name,)).fetchall()

            products_labels = [row["produit"] for row in top_products]
            products_counts = [row["nb_livraisons"] for row in top_products]

            # 📊 Activité par jour de la semaine (commandes par jour)
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
                WHERE client = ? AND situation IS NOT NULL
                GROUP BY jour
            """, (client_name,)).fetchall()
        else:
            total_clients = 0
            total_orders = 0
            orders_livree = 0
            orders_encours = 0
            orders_livraison = 0
            total_delivery = 0
            new_deliveries = 0
            products_labels = []
            products_counts = []
            orders_raw = []

    # ✅ 1️⃣ Nouveau bloc : nombre de commandes par mois
    if current_user.role == "admin":
        rows = conn.execute("""
            SELECT strftime('%m', date_reservation) AS mois, COUNT(*) AS total
            FROM orders
            WHERE date_reservation IS NOT NULL
            GROUP BY mois
            ORDER BY mois
        """).fetchall()
    else:
        rows = conn.execute("""
            SELECT strftime('%m', date_reservation) AS mois, COUNT(*) AS total
            FROM orders
            WHERE client = ? AND date_reservation IS NOT NULL
            GROUP BY mois
            ORDER BY mois
        """, (client_name,)).fetchall()

    # ✅ 2️⃣ Convertir en tableau 12 mois
    months_labels = ['Jan', 'Fév', 'Mar', 'Avr', 'Mai', 'Jun', 'Jul', 'Aoû', 'Sep', 'Oct', 'Nov', 'Déc']
    monthly_counts = [0] * 12
    for r in rows:
        month_index = int(r['mois']) - 1
        monthly_counts[month_index] = r['total']

    # ✅ 3️⃣ Commandes par client
    if current_user.role == "admin":
        rows_clients = conn.execute("""
            SELECT client, COUNT(*) as total
            FROM orders
            WHERE client IS NOT NULL
            GROUP BY client
            ORDER BY total DESC
            LIMIT 6
        """).fetchall()
    else:
        # Si client, on montre ses produits ou rien
        rows_clients = conn.execute("""
            SELECT produit, COUNT(*) as total
            FROM orders
            WHERE client = ? AND produit IS NOT NULL
            GROUP BY produit
            ORDER BY total DESC
            LIMIT 6
        """, (client_name,)).fetchall()

    clients_labels = [r['client'] if 'client' in r.keys() else r['produit'] for r in rows_clients]
    clients_counts = [r['total'] for r in rows_clients]
    # --- Fallback automatique pour garantir les 7 jours ---
    orders_dict = {row["jour"]: row["total"] for row in orders_raw}
    jours_fixes = ["Dim", "Lun", "Mar", "Mer", "Jeu", "Ven", "Sam"]
    days_labels = jours_fixes
    days_counts = [orders_dict.get(jour, 0) for jour in jours_fixes]

    

    conn.close()

    return render_template(
        "index.html",
        total_clients=total_clients,
        total_orders=total_orders,
        total_delivery=total_delivery,
        orders_livree=orders_livree,
        orders_encours=orders_encours,
        orders_livraison=orders_livraison,
        new_deliveries=new_deliveries,
        months=months_labels,
        monthly_counts=monthly_counts,
        clients_labels=clients_labels,
        clients_counts=clients_counts,
        # ↓↓↓ ajoute ceci ↓↓↓
        products_labels=products_labels,
        products_counts=products_counts,
        days_labels=days_labels,
        days_counts=days_counts
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

    clients_list = conn.execute(
        """
        SELECT N AS id, Entreprise AS company_name, Contact AS contact_name, 
               Tel AS phone, Email AS email
        FROM client
        ORDER BY N ASC
        LIMIT ? OFFSET ?
        """,
        (per_page, (page - 1) * per_page),
    ).fetchall()

    total_clients = conn.execute("SELECT COUNT(*) FROM client").fetchone()[0]
    total_pages = (total_clients + per_page - 1) // per_page

    start = (page - 1) * per_page + 1 if total_clients > 0 else 0
    end = min(page * per_page, total_clients)

    conn.close()

    return render_template(
        "clients.html",
        clients=clients_list,
        page=page,
        total_pages=total_pages,
        start=start,
        end=end,
        total_clients=total_clients
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
        query += " AND situation = ?"
        count_query += " AND situation = ?"
        params.append(status)
        count_params.append(status)

    if client and current_user.role == "admin":
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

    clients = [c["client"] for c in clients_list if c["client"]]
    products = [p["produit"] for p in products_list if p["produit"]]

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
        products=products
    )

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
    if client and current_user.role == "admin":
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
    if current_user.role != "admin":
        flash("Accès refusé : réservé aux administrateurs ❌", "danger")
        return redirect(url_for("index"))

    # --- Liste des clients depuis local.sqlite ---
    conn_local = get_db_connection()
    clients = conn_local.execute("SELECT N AS id, Entreprise AS company_name FROM client").fetchall()
    conn_local.close()

    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()
        client_id = int(request.form["client_id"])

        conn_auth = get_auth_connection()

        exists = conn_auth.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        
        if exists:
            flash("❌ Ce nom d'utilisateur existe déjà", "danger")
            conn_auth.close()
            return redirect(url_for("create_user"))

        password_hash = generate_password_hash(password)
        conn_auth.execute(
            "INSERT INTO users (username, password_hash, role, client_id) VALUES (?, ?, ?, ?)",
            (username, password_hash, "client", client_id)
        )
        conn_auth.commit()
        conn_auth.close()

        flash(f"✅ Compte '{username}' créé avec succès", "success")
        # Redirection vers la page des utilisateurs, pas celle des clients
        return redirect(url_for("list_users"))

    return render_template("create_user.html", clients=clients)

# ---- Liste et suppression des utilisateurs ----
@app.route("/admin/users")
@login_required
def list_users():

    if current_user.role != "admin":
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
        ORDER BY id DESC
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
    if current_user.role != "admin":
        flash("Accès refusé ❌", "danger")
        return redirect(url_for("index"))

    conn_auth = get_auth_connection()
    conn_auth.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn_auth.commit()
    conn_auth.close()

    flash("✅ Utilisateur supprimé avec succès", "success")
    return redirect(url_for("list_users"))


@app.route("/impression")
@login_required
def impression():
    conn = get_db_connection()
    cur = conn.cursor()

    # ---- récup filtres ----
    period = request.args.get("period", "all")
    article = (request.args.get("article") or "").strip()
    user = (request.args.get("user") or "").strip()
    start = request.args.get("start") or ""
    end = request.args.get("end") or ""

    # ---- pagination ----
    page = request.args.get("page", 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

    today = date.today()

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
            sunday = monday + timedelta(days=6)
            return monday, sunday
        if period == "month":
            first = today.replace(day=1)
            last = today.replace(day=calendar.monthrange(today.year, today.month)[1])
            return first, last
        if period == "year":
            first = date(today.year, 1, 1)
            last = date(today.year, 12, 31)
            return first, last
        if period == "custom" and start and end:
            try:
                return date.fromisoformat(start), date.fromisoformat(end)
            except:
                return None, None
        return None, None

    start_date, end_date = period_bounds(period, start, end)

    # ---- requête ----
    query = "SELECT num_impression, date_impression, hr, num_commande, machine, article, feuilles, etuis, user, datetime(date(date_impression) || ' ' || IFNULL(hr,'00:00')) AS datetime_full FROM impressions WHERE 1=1"
    count_query = "SELECT COUNT(*) FROM impressions WHERE 1=1"
    params = []
    count_params = []

    # filtre période
    if start_date and end_date:
        query += " AND date(date_impression) BETWEEN date(?) AND date(?)"
        count_query += " AND date(date_impression) BETWEEN date(?) AND date(?)"
        params.extend([start_date, end_date])
        count_params.extend([start_date, end_date])

    # filtre article
    if article:
        pattern = "%" + "%".join(article.split()) + "%"
        query += " AND article LIKE ?"
        count_query += " AND article LIKE ?"
        params.append(pattern)
        count_params.append(pattern)

    # filtre utilisateur
    if user:
        pattern = "%" + "%".join(user.split()) + "%"
        query += " AND user LIKE ?"
        count_query += " AND user LIKE ?"
        params.append(pattern)
        count_params.append(pattern)

    # tri + pagination
    query += " ORDER BY date_impression DESC LIMIT ? OFFSET ?"
    params.extend([per_page, offset])

    rows = cur.execute(query, params).fetchall()
    total = cur.execute(count_query, count_params).fetchone()[0]

    # totals
    total_feuilles = cur.execute("SELECT SUM(feuilles) FROM impressions").fetchone()[0] or 0
    total_etuis = cur.execute("SELECT SUM(etuis) FROM impressions").fetchone()[0] or 0

    # --- Récup listes uniques pour filtres ---
    users = [r[0] for r in cur.execute("SELECT DISTINCT user FROM impressions ORDER BY user").fetchall()]
    articles = [r[0] for r in cur.execute("SELECT DISTINCT article FROM impressions ORDER BY article").fetchall()]

    conn.close()

    total_pages = (total + per_page - 1) // per_page
    start_idx = offset + 1 if total > 0 else 0
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
    )


@app.route("/decoupe")
@login_required
def decoupe():
    conn = get_db_connection()
    cur = conn.cursor()

    # ---- récup filtres ----
    period = request.args.get("period", "all")
    user = (request.args.get("user") or "").strip()
    article = (request.args.get("article") or "").strip()
    start = request.args.get("start") or ""
    end = request.args.get("end") or ""

    # ---- pagination ----
    page = request.args.get("page", 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

    today = date.today()

    # ---- période ----
    def get_bounds(period, start, end):
        if period == "all": return None, None
        if period == "today": return today, today
        if period == "yesterday":
            d = today - timedelta(days=1)
            return d, d
        if period == "week":
            mon = today - timedelta(days=today.weekday())
            sun = mon + timedelta(days=6)
            return mon, sun
        if period == "month":
            first = today.replace(day=1)
            last = today.replace(day=calendar.monthrange(today.year, today.month)[1])
            return first, last
        if period == "year":
            first = date(today.year, 1, 1)
            last = date(today.year, 12, 31)
            return first, last
        if period == "custom" and start and end:
            try:
                return date.fromisoformat(start), date.fromisoformat(end)
            except:
                return None, None
        return None, None

    start_date, end_date = get_bounds(period, start, end)

    # ---- construction requêtes ----
    query = """
        SELECT num_decoupage, num_impression, date_decoupage, hr,
               num_commande, maquette_id, description, feuilles, user,
               datetime(date(date_decoupage) || ' ' || IFNULL(hr,'00:00')) AS datetime_full
        FROM decoupage WHERE 1=1
    """
    count_query = "SELECT COUNT(*) FROM decoupage WHERE 1=1"
    params = []
    count_params = []

    # période
    if start_date and end_date:
        query += " AND date(date_decoupage) BETWEEN date(?) AND date(?)"
        count_query += " AND date(date_decoupage) BETWEEN date(?) AND date(?)"
        params.extend([start_date, end_date])
        count_params.extend([start_date, end_date])

    # article
    if article:
        pattern = "%" + "%".join(article.split()) + "%"
        query += " AND description LIKE ?"
        count_query += " AND description LIKE ?"
        params.append(pattern)
        count_params.append(pattern)

    # utilisateur
    if user:
        pattern = "%" + "%".join(user.split()) + "%"
        query += " AND user LIKE ?"
        count_query += " AND user LIKE ?"
        params.append(pattern)
        count_params.append(pattern)

    # tri + pagination
    query += " ORDER BY num_decoupage DESC LIMIT ? OFFSET ?"
    params.extend([per_page, offset])

    rows = cur.execute(query, params).fetchall()
    total = cur.execute(count_query, count_params).fetchone()[0]

    # total feuilles découpées
    total_feuilles = cur.execute("SELECT SUM(feuilles) FROM decoupage").fetchone()[0] or 0

    # listes distinctes pour Select2
    users = [r[0] for r in cur.execute("SELECT DISTINCT user FROM decoupage ORDER BY user").fetchall()]
    articles = [r[0] for r in cur.execute("SELECT DISTINCT description FROM decoupage ORDER BY description").fetchall()]

    conn.close()

    total_pages = (total + per_page - 1) // per_page
    start_idx = offset + 1 if total > 0 else 0
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
        articles=articles
    )

@app.route("/pliage")
@login_required
def pliage():
    conn = get_db_connection()
    cur = conn.cursor()

    # Filtres
    period = request.args.get("period", "all")
    user = (request.args.get("user") or "").strip()
    article = (request.args.get("article") or "").strip()
    start = request.args.get("start") or ""
    end = request.args.get("end") or ""

    # Pagination
    page = request.args.get("page", 1, type=int)
    per_page = 20
    offset = (page - 1) * per_page

    today = date.today()

    def period_bounds(period, start, end):
        if period == "all": return None, None
        if period == "today": return today, today
        if period == "yesterday":
            d = today - timedelta(days=1)
            return d, d
        if period == "week":
            mon = today - timedelta(days=today.weekday())
            sun = mon + timedelta(days=6)
            return mon, sun
        if period == "month":
            first = today.replace(day=1)
            last = today.replace(day=calendar.monthrange(today.year, today.month)[1])
            return first, last
        if period == "year":
            first = date(today.year, 1, 1)
            last = date(today.year, 12, 31)
            return first, last
        if period == "custom" and start and end:
            try:
                return date.fromisoformat(start), date.fromisoformat(end)
            except:
                return None, None
        return None, None

    start_date, end_date = period_bounds(period, start, end)

    # Base query
    query = "SELECT *, datetime(date(date_pliage) || ' ' || IFNULL(hr,'00:00')) AS datetime_full FROM pliage WHERE 1=1"
    params = []

    # Date filter
    if start_date and end_date:
        query += " AND date(date_pliage) BETWEEN date(?) AND date(?)"
        params += [start_date, end_date]

    # User filter
    if user:
        pattern = "%" + "%".join(user.split()) + "%"
        query += " AND user LIKE ?"
        params.append(pattern)

    # Article filter
    if article:
        pattern = "%" + "%".join(article.split()) + "%"
        query += " AND description LIKE ?"
        params.append(pattern)

    # Count
    count_q = "SELECT COUNT(*) FROM (" + query + ")"
    total = cur.execute(count_q, params).fetchone()[0]

    # Pagination
    query += " ORDER BY date_pliage DESC LIMIT ? OFFSET ?"
    params += [per_page, offset]

    rows = cur.execute(query, params).fetchall()

    # Totaux
    total_qte = cur.execute("SELECT SUM(qte_pli) FROM pliage").fetchone()[0] or 0

    # Filtres distincts
    users = [r[0] for r in cur.execute("SELECT DISTINCT user FROM pliage ORDER BY user").fetchall()]
    articles = [r[0] for r in cur.execute("SELECT DISTINCT description FROM pliage ORDER BY description").fetchall()]

    conn.close()

    total_pages = (total + per_page - 1) // per_page
    start_idx = offset + 1 if total > 0 else 0
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
        articles=articles
    )

if __name__ == "__main__":
    #app.run(debug=True, port=8888)
    app.run(host="0.0.0.0", port=8888, debug=True)
