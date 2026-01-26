from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
import sqlite3
from datetime import datetime, timedelta
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

# --- User class (Flask-Login) ---
class User(UserMixin):
    def __init__(self, id, username, password_hash, role, client_id):
        self.id = id
        self.username = username
        self.password_hash = password_hash
        self.role = role
        self.client_id = client_id

def get_user_by_id(user_id):
    conn = get_db_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    if row:
        return User(row["id"], row["username"], row["password_hash"], row["role"], row["client_id"])
    return None

def get_user_by_username(username):
    conn = get_db_connection()
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

# ============================
#   ROUTES AUTHENTIFICATION
# ============================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
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

    orders_list = conn.execute(query, params).fetchall()
    total_orders = conn.execute(count_query, count_params).fetchone()[0]
    total_pages = (total_orders + per_page - 1) // per_page

    start = (page - 1) * per_page + 1 if total_orders > 0 else 0
    end = min(page * per_page, total_orders)

    conn.close()
    return render_template(
        "orders.html",
        orders=orders_list,
        page=page,
        total_pages=total_pages,
        start=start,
        end=end,
        total_orders=total_orders,
        period=period,
        status=status,
        client=client,
        product=product
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

    if current_user.role == "client":
        query += " AND code_client = ?"
        count_query += " AND code_client = ?"
        params.append(current_user.client_id)
        count_params.append(current_user.client_id)

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

    query += " ORDER BY date_livraison DESC LIMIT ? OFFSET ?"
    params.extend([per_page, (page - 1) * per_page])

    delivery_list = conn.execute(query, params).fetchall()
    total_delivery = conn.execute(count_query, count_params).fetchone()[0]
    total_pages = (total_delivery + per_page - 1) // per_page

    start = (page - 1) * per_page + 1 if total_delivery > 0 else 0
    end = min(page * per_page, total_delivery)

    conn.close()

    return render_template(
        "delivery.html",
        delivery=delivery_list,
        page=page,
        total_pages=total_pages,
        start=start,
        end=end,
        total_delivery=total_delivery,
        period=period,
        client=client,
        product=product
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

    conn = get_db_connection()
    clients = conn.execute("SELECT N AS id, Entreprise AS company_name FROM client").fetchall()

    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"].strip()
        client_id = request.form["client_id"]

        exists = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        if exists:
            flash("❌ Ce nom d'utilisateur existe déjà", "danger")
            conn.close()
            return redirect(url_for("create_user"))

        password_hash = generate_password_hash(password)
        conn.execute(
            "INSERT INTO users (username, password_hash, role, client_id) VALUES (?, ?, ?, ?)",
            (username, password_hash, "client", client_id)
        )
        conn.commit()
        conn.close()

        flash(f"✅ Compte '{username}' créé avec succès", "success")
        return redirect(url_for("clients"))

    conn.close()
    return render_template("create_user.html", clients=clients)

# ---- Liste et suppression des utilisateurs ----
@app.route("/admin/users")
@login_required
def list_users():
    if current_user.role != "admin":
        flash("Accès refusé ❌", "danger")
        return redirect(url_for("index"))

    conn = get_db_connection()
    users = conn.execute("""
        SELECT u.id, u.username, u.role, u.client_id, c.Entreprise AS client_name
        FROM users u
        LEFT JOIN client c ON u.client_id = c.N
        ORDER BY u.id ASC
    """).fetchall()
    conn.close()

    return render_template("list_users.html", users=users)

@app.route("/admin/users/delete/<int:user_id>", methods=["POST"])
@login_required
def delete_user(user_id):
    if current_user.role != "admin":
        flash("Accès refusé ❌", "danger")
        return redirect(url_for("index"))

    conn = get_db_connection()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()

    flash("✅ Utilisateur supprimé avec succès", "success")
    return redirect(url_for("list_users"))

@app.route('/impressions')
@login_required
def impressions():
    return render_template('impressions.html')

@app.route('/decoupes')
@login_required
def decoupes():
    return render_template('decoupes.html')

if __name__ == "__main__":
    app.run(debug=True, port=8888)
