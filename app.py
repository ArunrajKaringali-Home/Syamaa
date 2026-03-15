"""
Syamaa — Exquisite Indian Couture
Full-stack backend: Flask + SQLite3 (stdlib only, zero external deps beyond Flask)

Features:
  - Product catalog (CRUD)
  - Customer enquiry / order form
  - Newsletter subscriptions
  - Admin authentication (session-based, token in cookie)
  - WhatsApp enquiry logging
  - Admin dashboard (stats + management)
  - CORS headers (manual)
  - SQLite database (auto-created on first run)
"""

import sqlite3
import hashlib
import hmac
import secrets
import json
import os
import re
import smtplib
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
from functools import wraps
from flask import (
    Flask,
    request,
    jsonify,
    render_template_string,
    session,
    redirect,
    url_for,
    g,
    send_from_directory,
)

# ─── App Setup ───────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__, static_folder=str(BASE_DIR / "static"))
app.secret_key = secrets.token_hex(32)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)

DB_PATH = BASE_DIR / "instance" / "syamaa.db"
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@syamaa.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "Syamaa@2025")  # change in production


# ─── Database Helpers ─────────────────────────────────────────
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(str(DB_PATH))
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db:
        db.close()


def query(sql, params=(), one=False):
    db = get_db()
    cur = db.execute(sql, params)
    db.commit()
    if one:
        row = cur.fetchone()
        return dict(row) if row else None
    return [dict(r) for r in cur.fetchall()]


def init_db():
    instance_dir = BASE_DIR / "instance"
    instance_dir.mkdir(parents=True, exist_ok=True)
    print(f"Initializing database at {DB_PATH}...")
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH))
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS products (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL,
            category    TEXT    NOT NULL,
            style       TEXT,
            fabric      TEXT,
            color       TEXT,
            features    TEXT,
            price       TEXT    DEFAULT 'Contact for Price',
            image_url   TEXT,
            tag         TEXT,
            is_active   INTEGER DEFAULT 1,
            created_at  TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS enquiries (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL,
            phone        TEXT NOT NULL,
            email        TEXT,
            message      TEXT,
            product_id   INTEGER REFERENCES products(id),
            product_name TEXT,
            type         TEXT DEFAULT 'general',
            status       TEXT DEFAULT 'new',
            created_at   TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS orders (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            enquiry_id      INTEGER REFERENCES enquiries(id),
            name            TEXT NOT NULL,
            phone           TEXT NOT NULL,
            email           TEXT,
            address         TEXT,
            product_name    TEXT NOT NULL,
            size            TEXT,
            custom_notes    TEXT,
            fabric_choice   TEXT,
            color_choice    TEXT,
            payment_method  TEXT DEFAULT 'COD',
            total_amount    TEXT,
            status          TEXT DEFAULT 'pending',
            created_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS newsletter (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT,
            email       TEXT UNIQUE NOT NULL,
            whatsapp    TEXT,
            is_active   INTEGER DEFAULT 1,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS admins (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            email         TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            name          TEXT DEFAULT 'Admin',
            created_at    TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS wa_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            phone       TEXT,
            message     TEXT,
            source      TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );
    """
    )
    db.commit()

    # Seed products from poster data
    existing = db.execute("SELECT COUNT(*) as c FROM products").fetchone()["c"]
    if existing == 0:
        products = [
            (
                "Vintage Rose Angrakha Style Kurta",
                "Angrakha",
                "Angrakha Overlap",
                "Cotton-Silk",
                "Light Pink",
                "V-neck with multi-colored patterned piping|Elegant angrakha style overlap closure|Three-quarter sleeves with patterned trim|Tassel tie detail",
                "Contact for Price",
                "/static/img/vintage-rose.jpg",
                "Best Seller",
            ),
            (
                "Lumina Floral Kurta",
                "Straight Kurta",
                "Collar Neck Sleeveless",
                "Jaipur Cotton",
                "White Floral",
                "Collar neck sleeveless kurta|Jaipur cotton with thread work|Simple and comfortable|Hand wash / Machine wash",
                "Contact for Price",
                "/static/img/lumina-floral.jpg",
                "New",
            ),
            (
                "Navy Floral Slitted Cotton Kurti Set",
                "Kurti Set",
                "Straight Slitted",
                "100% Cotton",
                "Navy Blue",
                "V collar neck with white lace|Three-quarter regular sleeves|Side slits for movement|With matching bottom",
                "Contact for Price",
                "/static/img/navy-floral.jpg",
                "Best Seller",
            ),
            (
                "Custom Stitch Kurta",
                "Custom",
                "Any Style",
                "Cotton / Cotton-Silk / Jaipur Cotton",
                "Your Choice",
                "Your design, your measurements|Any style: Angrakha, Straight, Anarkali|Premium natural fabrics|Perfect custom fit",
                "Contact for Price",
                "/static/img/custom.jpg",
                "Custom",
            ),
        ]
        db.executemany(
            "INSERT INTO products (name,category,style,fabric,color,features,price,image_url,tag) VALUES (?,?,?,?,?,?,?,?,?)",
            products,
        )

    # Seed admin
    existing_admin = db.execute("SELECT COUNT(*) as c FROM admins").fetchone()["c"]
    if existing_admin == 0:
        pw_hash = hashlib.sha256(ADMIN_PASSWORD.encode()).hexdigest()
        db.execute(
            "INSERT INTO admins (email, password_hash, name) VALUES (?,?,?)",
            (ADMIN_EMAIL, pw_hash, "Syamaa Admin"),
        )

    db.commit()
    db.close()


# ─── CORS Middleware ──────────────────────────────────────────
@app.after_request
def cors_headers(response):
    origin = request.headers.get("Origin", "*")
    response.headers["Access-Control-Allow-Origin"] = origin
    response.headers["Access-Control-Allow-Credentials"] = "true"
    response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = (
        "Content-Type, Authorization, X-Requested-With"
    )
    return response


@app.route("/", defaults={"path": ""}, methods=["OPTIONS"])
@app.route("/<path:path>", methods=["OPTIONS"])
def options_handler(path):
    return "", 204


# ─── Auth Decorator ───────────────────────────────────────────
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_id"):
            if request.is_json:
                return jsonify({"error": "Unauthorized"}), 401
            return redirect("/admin/login")
        return f(*args, **kwargs)

    return decorated


# ─── Helpers ─────────────────────────────────────────────────
def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()


def validate_phone(phone):
    return bool(re.match(r"^[6-9]\d{9}$", re.sub(r"[\s\-\+()]", "", phone)))


def validate_email(email):
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email))


# ─── API: Products ────────────────────────────────────────────
@app.route("/api/products", methods=["GET"])
def get_products():
    category = request.args.get("category")
    sql = "SELECT * FROM products WHERE is_active=1"
    params = []
    if category:
        sql += " AND category=?"
        params.append(category)
    sql += " ORDER BY id ASC"
    products = query(sql, params)
    for p in products:
        p["features"] = p["features"].split("|") if p.get("features") else []
    return jsonify({"products": products, "count": len(products)})


@app.route("/api/products/<int:pid>", methods=["GET"])
def get_product(pid):
    p = query("SELECT * FROM products WHERE id=? AND is_active=1", (pid,), one=True)
    if not p:
        return jsonify({"error": "Product not found"}), 404
    p["features"] = p["features"].split("|") if p.get("features") else []
    return jsonify(p)


@app.route("/api/products/categories", methods=["GET"])
def get_categories():
    cats = query(
        "SELECT DISTINCT category, COUNT(*) as count FROM products WHERE is_active=1 GROUP BY category"
    )
    return jsonify({"categories": cats})


# ─── API: Enquiries ───────────────────────────────────────────
@app.route("/api/enquiry", methods=["POST"])
def submit_enquiry():
    data = request.get_json(silent=True) or request.form.to_dict()

    name = (data.get("name") or "").strip()
    phone = (data.get("phone") or "").strip()
    email = (data.get("email") or "").strip()
    msg = (data.get("message") or "").strip()
    pid = data.get("product_id")
    pname = (data.get("product_name") or "").strip()
    etype = data.get("type", "general")

    if not name:
        return jsonify({"error": "Name is required"}), 400
    if not phone:
        return jsonify({"error": "Phone number is required"}), 400

    clean_phone = re.sub(r"[\s\-\+()]", "", phone)
    if len(clean_phone) < 10:
        return jsonify({"error": "Please enter a valid phone number"}), 400

    if email and not validate_email(email):
        return jsonify({"error": "Please enter a valid email"}), 400

    row = query(
        "INSERT INTO enquiries (name,phone,email,message,product_id,product_name,type) VALUES (?,?,?,?,?,?,?)",
        (
            name,
            clean_phone,
            email or None,
            msg or None,
            pid or None,
            pname or None,
            etype,
        ),
    )

    # Log to WA log
    wa_msg = f"New enquiry from {name} ({clean_phone})"
    if pname:
        wa_msg += f" about {pname}"
    query(
        "INSERT INTO wa_logs (phone,message,source) VALUES (?,?,?)",
        (clean_phone, wa_msg, "website_enquiry"),
    )

    return (
        jsonify(
            {
                "success": True,
                "message": "Thank you! We'll contact you on WhatsApp soon.",
                "wa_link": f"https://wa.me/916282201008?text=Hi! I enquired about {pname or 'your collection'}",
            }
        ),
        201,
    )


# ─── API: Orders ──────────────────────────────────────────────
@app.route("/api/order", methods=["POST"])
def place_order():
    data = request.get_json(silent=True) or request.form.to_dict()

    required = ["name", "phone", "product_name"]
    for field in required:
        if not (data.get(field) or "").strip():
            return (
                jsonify({"error": f"{field.replace('_',' ').title()} is required"}),
                400,
            )

    name = data["name"].strip()
    phone = re.sub(r"[\s\-\+()]", "", data["phone"])
    email = (data.get("email") or "").strip()
    address = (data.get("address") or "").strip()
    product_name = data["product_name"].strip()
    size = (data.get("size") or "").strip()
    custom_notes = (data.get("custom_notes") or "").strip()
    fabric = (data.get("fabric_choice") or "").strip()
    color = (data.get("color_choice") or "").strip()
    payment = data.get("payment_method", "COD")
    amount = (data.get("total_amount") or "Contact for Price").strip()

    query(
        """INSERT INTO orders
           (name,phone,email,address,product_name,size,custom_notes,
            fabric_choice,color_choice,payment_method,total_amount)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (
            name,
            phone,
            email or None,
            address or None,
            product_name,
            size or None,
            custom_notes or None,
            fabric or None,
            color or None,
            payment,
            amount,
        ),
    )

    wa_text = (
        f"Hi! I want to order {product_name} from Syamaa."
        + (f" Size: {size}." if size else "")
        + (f" Notes: {custom_notes}" if custom_notes else "")
    )

    return (
        jsonify(
            {
                "success": True,
                "message": "Order received! We'll confirm on WhatsApp shortly.",
                "wa_link": f"https://wa.me/916282201008?text={wa_text}",
            }
        ),
        201,
    )


# ─── API: Newsletter ──────────────────────────────────────────
@app.route("/api/newsletter", methods=["POST"])
def subscribe_newsletter():
    data = request.get_json(silent=True) or request.form.to_dict()

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    whatsapp = (data.get("whatsapp") or "").strip()

    if not email:
        return jsonify({"error": "Email is required"}), 400
    if not validate_email(email):
        return jsonify({"error": "Please enter a valid email address"}), 400

    existing = query("SELECT id FROM newsletter WHERE email=?", (email,), one=True)
    if existing:
        return (
            jsonify({"success": True, "message": "You're already subscribed! 🌸"}),
            200,
        )

    query(
        "INSERT INTO newsletter (name,email,whatsapp) VALUES (?,?,?)",
        (name or None, email, whatsapp or None),
    )

    return jsonify({"success": True, "message": "Welcome to the Syamaa circle! ✦"}), 201


# ─── Admin: Auth ──────────────────────────────────────────────
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")
        admin = query("SELECT * FROM admins WHERE email=?", (email,), one=True)
        if admin and hmac.compare_digest(
            admin["password_hash"], hash_password(password)
        ):
            session.permanent = True
            session["admin_id"] = admin["id"]
            session["admin_name"] = admin["name"]
            return redirect("/admin/dashboard")
        error = "Invalid email or password"
    return render_template_string(ADMIN_LOGIN_HTML, error=error)


@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect("/admin/login")


# ─── Admin: Dashboard ─────────────────────────────────────────
@app.route("/admin/dashboard")
@admin_required
def admin_dashboard():
    stats = {
        "products": query(
            "SELECT COUNT(*) as c FROM products WHERE is_active=1", one=True
        )["c"],
        "enquiries": query("SELECT COUNT(*) as c FROM enquiries", one=True)["c"],
        "new_enquiries": query(
            "SELECT COUNT(*) as c FROM enquiries WHERE status='new'", one=True
        )["c"],
        "orders": query("SELECT COUNT(*) as c FROM orders", one=True)["c"],
        "pending_orders": query(
            "SELECT COUNT(*) as c FROM orders WHERE status='pending'", one=True
        )["c"],
        "subscribers": query(
            "SELECT COUNT(*) as c FROM newsletter WHERE is_active=1", one=True
        )["c"],
    }
    recent_enquiries = query(
        "SELECT * FROM enquiries ORDER BY created_at DESC LIMIT 10"
    )
    recent_orders = query("SELECT * FROM orders ORDER BY created_at DESC LIMIT 10")
    return render_template_string(
        ADMIN_DASHBOARD_HTML,
        stats=stats,
        recent_enquiries=recent_enquiries,
        recent_orders=recent_orders,
        admin_name=session.get("admin_name", "Admin"),
    )


# ─── Admin: API (JSON) ────────────────────────────────────────
@app.route("/admin/api/enquiries")
@admin_required
def admin_enquiries():
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 20))
    status = request.args.get("status")
    offset = (page - 1) * limit
    sql = "SELECT * FROM enquiries"
    params = []
    if status:
        sql += " WHERE status=?"
        params.append(status)
    total = query(f"SELECT COUNT(*) as c FROM ({sql})", params, one=True)["c"]
    sql += f" ORDER BY created_at DESC LIMIT {limit} OFFSET {offset}"
    rows = query(sql, params)
    return jsonify({"enquiries": rows, "total": total, "page": page})


@app.route("/admin/api/enquiries/<int:eid>", methods=["PATCH"])
@admin_required
def update_enquiry(eid):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in ("new", "contacted", "closed"):
        return jsonify({"error": "Invalid status"}), 400
    query("UPDATE enquiries SET status=? WHERE id=?", (status, eid))
    return jsonify({"success": True})


@app.route("/admin/api/orders")
@admin_required
def admin_orders():
    page = int(request.args.get("page", 1))
    limit = int(request.args.get("limit", 20))
    status = request.args.get("status")
    offset = (page - 1) * limit
    sql = "SELECT * FROM orders"
    params = []
    if status:
        sql += " WHERE status=?"
        params.append(status)
    total = query(f"SELECT COUNT(*) as c FROM ({sql})", params, one=True)["c"]
    sql += f" ORDER BY created_at DESC LIMIT {limit} OFFSET {offset}"
    rows = query(sql, params)
    return jsonify({"orders": rows, "total": total, "page": page})


@app.route("/admin/api/orders/<int:oid>", methods=["PATCH"])
@admin_required
def update_order(oid):
    data = request.get_json(silent=True) or {}
    status = data.get("status")
    if status not in (
        "pending",
        "confirmed",
        "stitching",
        "ready",
        "shipped",
        "delivered",
        "cancelled",
    ):
        return jsonify({"error": "Invalid status"}), 400
    query("UPDATE orders SET status=? WHERE id=?", (status, oid))
    return jsonify({"success": True})


@app.route("/admin/api/products", methods=["GET"])
@admin_required
def admin_products():
    rows = query("SELECT * FROM products ORDER BY id DESC")
    return jsonify({"products": rows})


@app.route("/admin/api/products", methods=["POST"])
@admin_required
def admin_add_product():
    data = request.get_json(silent=True) or request.form.to_dict()
    if not data.get("name") or not data.get("category"):
        return jsonify({"error": "Name and category are required"}), 400
    features = (
        "|".join(data.get("features", []))
        if isinstance(data.get("features"), list)
        else (data.get("features") or "")
    )
    query(
        "INSERT INTO products (name,category,style,fabric,color,features,price,image_url,tag) VALUES (?,?,?,?,?,?,?,?,?)",
        (
            data["name"],
            data["category"],
            data.get("style"),
            data.get("fabric"),
            data.get("color"),
            features,
            data.get("price", "Contact for Price"),
            data.get("image_url"),
            data.get("tag"),
        ),
    )
    return jsonify({"success": True}), 201


@app.route("/admin/api/products/<int:pid>", methods=["PUT"])
@admin_required
def admin_update_product(pid):
    data = request.get_json(silent=True) or {}
    features = (
        "|".join(data.get("features", []))
        if isinstance(data.get("features"), list)
        else data.get("features", "")
    )
    query(
        """UPDATE products SET name=?,category=?,style=?,fabric=?,color=?,
           features=?,price=?,image_url=?,tag=?,is_active=? WHERE id=?""",
        (
            data.get("name"),
            data.get("category"),
            data.get("style"),
            data.get("fabric"),
            data.get("color"),
            features,
            data.get("price", "Contact for Price"),
            data.get("image_url"),
            data.get("tag"),
            int(data.get("is_active", 1)),
            pid,
        ),
    )
    return jsonify({"success": True})


@app.route("/admin/api/products/<int:pid>", methods=["DELETE"])
@admin_required
def admin_delete_product(pid):
    query("UPDATE products SET is_active=0 WHERE id=?", (pid,))
    return jsonify({"success": True})


@app.route("/admin/api/newsletter")
@admin_required
def admin_newsletter():
    rows = query("SELECT * FROM newsletter WHERE is_active=1 ORDER BY created_at DESC")
    return jsonify({"subscribers": rows, "count": len(rows)})


@app.route("/admin/api/stats")
@admin_required
def admin_stats():
    daily_enquiries = query(
        "SELECT DATE(created_at) as date, COUNT(*) as count FROM enquiries GROUP BY DATE(created_at) ORDER BY date DESC LIMIT 14"
    )
    order_statuses = query(
        "SELECT status, COUNT(*) as count FROM orders GROUP BY status"
    )
    top_products = query(
        "SELECT product_name, COUNT(*) as enquiries FROM enquiries WHERE product_name!='' GROUP BY product_name ORDER BY enquiries DESC LIMIT 5"
    )
    return jsonify(
        {
            "daily_enquiries": daily_enquiries,
            "order_statuses": order_statuses,
            "top_products": top_products,
        }
    )


# ─── Serve Frontend ───────────────────────────────────────────
@app.route("/")
def serve_frontend():
    """Serve the main Syamaa website."""
    return send_from_directory("static", "index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok", "app": "Syamaa Backend", "version": "1.0.0"})


# ─── Admin HTML Templates ─────────────────────────────────────
ADMIN_LOGIN_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Syamaa Admin Login</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;1,400&family=Josefin+Sans:wght@300;400&display=swap" rel="stylesheet">
<style>
  :root { --dark:#1A0F0A; --gold:#C9900C; --gold-light:#F0C040; --cream:#FAF3E8; --blush:#F2D5B0; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { min-height:100vh; background:var(--dark); display:flex; align-items:center; justify-content:center; font-family:'Josefin Sans',sans-serif; }
  .login-box { width:420px; border:1px solid rgba(201,144,12,0.2); background:rgba(255,255,255,0.02); padding:52px 48px; }
  .logo { font-family:'Cormorant Garamond',serif; font-size:42px; font-weight:300; color:var(--gold-light); text-align:center; margin-bottom:4px; }
  .logo-sub { font-size:9px; letter-spacing:0.45em; text-transform:uppercase; color:var(--blush); opacity:0.5; text-align:center; margin-bottom:36px; display:block; }
  label { font-size:9px; letter-spacing:0.3em; text-transform:uppercase; color:var(--gold); display:block; margin-bottom:8px; }
  input { width:100%; background:transparent; border:1px solid rgba(201,144,12,0.2); padding:13px 16px; color:var(--cream); font-family:'Josefin Sans',sans-serif; font-size:12px; outline:none; margin-bottom:20px; transition:border-color 0.3s; }
  input:focus { border-color:var(--gold); }
  input::placeholder { color:rgba(242,213,176,0.3); }
  button { width:100%; background:var(--gold); border:none; color:var(--dark); padding:14px; font-family:'Josefin Sans',sans-serif; font-size:11px; letter-spacing:0.3em; text-transform:uppercase; cursor:pointer; transition:background 0.3s; margin-top:4px; }
  button:hover { background:var(--gold-light); }
  .error { background:rgba(139,26,26,0.3); border:1px solid rgba(139,26,26,0.4); color:#F2A0A0; font-size:11px; padding:10px 14px; margin-bottom:20px; text-align:center; letter-spacing:0.05em; }
  .hint { font-size:10px; color:var(--blush); opacity:0.35; text-align:center; margin-top:20px; letter-spacing:0.1em; }
</style>
</head>
<body>
<div class="login-box">
  <div class="logo">Syamaa</div>
  <span class="logo-sub">Admin Panel</span>
  {% if error %}<div class="error">{{ error }}</div>{% endif %}
  <form method="POST">
    <label>Email</label>
    <input type="email" name="email" placeholder="admin@syamaa.com" required autocomplete="username">
    <label>Password</label>
    <input type="password" name="password" placeholder="••••••••" required autocomplete="current-password">
    <button type="submit">Sign In</button>
  </form>
  <p class="hint">Syamaa — Exquisite Indian Couture</p>
</div>
</body>
</html>
"""

ADMIN_DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Syamaa Admin Dashboard</title>
<link href="https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,300;0,400;1,400&family=Josefin+Sans:wght@300;400&display=swap" rel="stylesheet">
<style>
  :root{--dark:#1A0F0A;--dark2:#120A05;--gold:#C9900C;--gold-light:#F0C040;--cream:#FAF3E8;--blush:#F2D5B0;--warm:#3D1F0F;--saffron:#C4722A;--red:#8B1A1A;--green:#1B6B3D;}
  *{margin:0;padding:0;box-sizing:border-box;}
  body{background:var(--dark);color:var(--cream);font-family:'Josefin Sans',sans-serif;font-weight:300;min-height:100vh;display:flex;}
  /* SIDEBAR */
  .sidebar{width:240px;min-height:100vh;background:var(--dark2);border-right:1px solid rgba(201,144,12,0.1);display:flex;flex-direction:column;flex-shrink:0;}
  .sidebar-logo{padding:28px 24px 20px;border-bottom:1px solid rgba(201,144,12,0.1);}
  .sidebar-logo .brand{font-family:'Cormorant Garamond',serif;font-size:28px;font-weight:300;color:var(--gold-light);}
  .sidebar-logo .sub{font-size:7px;letter-spacing:0.4em;text-transform:uppercase;color:var(--blush);opacity:0.4;display:block;margin-top:2px;}
  .sidebar-nav{padding:20px 0;flex:1;}
  .nav-item{display:flex;align-items:center;gap:12px;padding:12px 24px;color:var(--blush);opacity:0.55;font-size:11px;letter-spacing:0.2em;text-transform:uppercase;cursor:pointer;transition:all 0.2s;text-decoration:none;}
  .nav-item:hover,.nav-item.active{opacity:1;background:rgba(201,144,12,0.07);color:var(--gold-light);}
  .nav-item .icon{font-size:16px;width:20px;}
  .sidebar-footer{padding:20px 24px;border-top:1px solid rgba(201,144,12,0.1);}
  .admin-badge{font-size:10px;color:var(--blush);opacity:0.5;margin-bottom:12px;}
  .logout-btn{display:block;text-align:center;color:var(--blush);opacity:0.4;font-size:10px;letter-spacing:0.2em;text-transform:uppercase;text-decoration:none;transition:opacity 0.2s;}
  .logout-btn:hover{opacity:0.8;}
  /* MAIN */
  .main{flex:1;overflow:auto;}
  .topbar{padding:22px 40px;border-bottom:1px solid rgba(201,144,12,0.08);display:flex;justify-content:space-between;align-items:center;}
  .page-title{font-family:'Cormorant Garamond',serif;font-size:26px;font-weight:300;color:var(--ivory);}
  .topbar-right{font-size:10px;color:var(--blush);opacity:0.45;letter-spacing:0.1em;}
  .content{padding:36px 40px;}
  /* STAT CARDS */
  .stats-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:2px;margin-bottom:36px;}
  .stat-card{background:rgba(255,255,255,0.02);border:1px solid rgba(201,144,12,0.1);padding:28px;position:relative;transition:border-color 0.3s;}
  .stat-card:hover{border-color:rgba(201,144,12,0.3);}
  .stat-label{font-size:9px;letter-spacing:0.3em;text-transform:uppercase;color:var(--gold);display:block;margin-bottom:12px;}
  .stat-value{font-family:'Cormorant Garamond',serif;font-size:42px;font-weight:300;color:var(--gold-light);line-height:1;}
  .stat-sub{font-size:10px;color:var(--blush);opacity:0.5;margin-top:6px;letter-spacing:0.1em;}
  .stat-badge{position:absolute;top:16px;right:16px;font-size:8px;letter-spacing:0.2em;text-transform:uppercase;padding:3px 10px;border:1px solid;}
  .badge-new{color:#F2A080;border-color:rgba(242,160,128,0.3);background:rgba(242,160,128,0.08);}
  .badge-pending{color:#F0C040;border-color:rgba(240,192,64,0.3);background:rgba(240,192,64,0.06);}
  /* TABLES */
  .section-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;}
  .section-title{font-family:'Cormorant Garamond',serif;font-size:20px;font-weight:300;color:var(--ivory);}
  .section-tabs{display:flex;gap:2px;}
  .tab{font-size:9px;letter-spacing:0.2em;text-transform:uppercase;padding:8px 16px;background:transparent;border:1px solid rgba(201,144,12,0.15);color:var(--blush);opacity:0.5;cursor:pointer;transition:all 0.2s;}
  .tab.active,.tab:hover{opacity:1;border-color:var(--gold);color:var(--gold-light);}
  table{width:100%;border-collapse:collapse;font-size:11px;margin-bottom:40px;}
  th{font-size:8px;letter-spacing:0.3em;text-transform:uppercase;color:var(--gold);padding:10px 14px;text-align:left;border-bottom:1px solid rgba(201,144,12,0.15);}
  td{padding:12px 14px;border-bottom:1px solid rgba(255,255,255,0.04);color:var(--blush);opacity:0.8;vertical-align:top;}
  tr:hover td{background:rgba(201,144,12,0.04);}
  .status-badge{font-size:8px;letter-spacing:0.15em;text-transform:uppercase;padding:3px 10px;border:1px solid;}
  .status-new{color:#80C4F2;border-color:rgba(128,196,242,0.3);}
  .status-contacted{color:#80F2A0;border-color:rgba(128,242,160,0.3);}
  .status-closed{color:rgba(242,213,176,0.4);border-color:rgba(242,213,176,0.15);}
  .status-pending{color:#F0C040;border-color:rgba(240,192,64,0.3);}
  .status-confirmed{color:#80C4F2;border-color:rgba(128,196,242,0.3);}
  .status-delivered{color:#80F2A0;border-color:rgba(128,242,160,0.3);}
  .action-btn{font-size:9px;letter-spacing:0.15em;text-transform:uppercase;padding:4px 10px;border:1px solid rgba(201,144,12,0.3);color:var(--gold);background:transparent;cursor:pointer;transition:all 0.2s;}
  .action-btn:hover{background:var(--gold);color:var(--dark);}
  .wa-btn{background:rgba(37,211,102,0.1);border-color:rgba(37,211,102,0.3);color:#25D366;}
  .wa-btn:hover{background:#25D366;color:white;}
  .grid2{display:grid;grid-template-columns:1fr 1fr;gap:36px;}
  /* Toast */
  .toast{position:fixed;bottom:24px;right:24px;background:rgba(27,107,61,0.9);border:1px solid rgba(27,107,61,0.6);color:var(--cream);padding:12px 24px;font-size:11px;letter-spacing:0.1em;opacity:0;transition:opacity 0.3s;z-index:1000;pointer-events:none;}
  .toast.show{opacity:1;}
</style>
</head>
<body>

<aside class="sidebar">
  <div class="sidebar-logo">
    <div class="brand">Syamaa</div>
    <span class="sub">Admin Panel</span>
  </div>
  <nav class="sidebar-nav">
    <a class="nav-item active" href="/admin/dashboard"><span class="icon">📊</span> Dashboard</a>
    <a class="nav-item" href="#" onclick="loadSection('enquiries')"><span class="icon">💬</span> Enquiries</a>
    <a class="nav-item" href="#" onclick="loadSection('orders')"><span class="icon">📦</span> Orders</a>
    <a class="nav-item" href="#" onclick="loadSection('products')"><span class="icon">👗</span> Products</a>
    <a class="nav-item" href="#" onclick="loadSection('newsletter')"><span class="icon">✉️</span> Newsletter</a>
  </nav>
  <div class="sidebar-footer">
    <div class="admin-badge">Signed in as {{ admin_name }}</div>
    <a href="/admin/logout" class="logout-btn">Sign Out</a>
  </div>
</aside>

<main class="main">
  <div class="topbar">
    <div class="page-title" id="pageTitle">Dashboard</div>
    <div class="topbar-right" id="topbarDate"></div>
  </div>
  <div class="content" id="mainContent">

    <!-- STATS -->
    <div class="stats-grid">
      <div class="stat-card">
        <span class="stat-label">Total Products</span>
        <div class="stat-value">{{ stats.products }}</div>
        <div class="stat-sub">Active listings</div>
      </div>
      <div class="stat-card">
        <span class="stat-label">Enquiries</span>
        <div class="stat-value">{{ stats.enquiries }}</div>
        <div class="stat-sub">All time</div>
        {% if stats.new_enquiries > 0 %}
        <span class="stat-badge badge-new">{{ stats.new_enquiries }} New</span>
        {% endif %}
      </div>
      <div class="stat-card">
        <span class="stat-label">Orders</span>
        <div class="stat-value">{{ stats.orders }}</div>
        <div class="stat-sub">All time</div>
        {% if stats.pending_orders > 0 %}
        <span class="stat-badge badge-pending">{{ stats.pending_orders }} Pending</span>
        {% endif %}
      </div>
      <div class="stat-card">
        <span class="stat-label">Newsletter</span>
        <div class="stat-value">{{ stats.subscribers }}</div>
        <div class="stat-sub">Active subscribers</div>
      </div>
      <div class="stat-card">
        <span class="stat-label">WhatsApp</span>
        <div class="stat-value">6282</div>
        <div class="stat-sub">201 008 — primary contact</div>
      </div>
      <div class="stat-card">
        <span class="stat-label">Status</span>
        <div class="stat-value" style="font-size:24px;margin-top:4px;">🟢</div>
        <div class="stat-sub">Backend online</div>
      </div>
    </div>

    <!-- RECENT ENQUIRIES -->
    <div class="grid2">
      <div>
        <div class="section-header">
          <div class="section-title">Recent Enquiries</div>
          <button class="tab active" onclick="loadSection('enquiries')">View All</button>
        </div>
        <table>
          <thead><tr><th>Name</th><th>Phone</th><th>Product</th><th>Status</th><th>Action</th></tr></thead>
          <tbody>
          {% for e in recent_enquiries %}
          <tr>
            <td>{{ e.name }}</td>
            <td>{{ e.phone }}</td>
            <td>{{ e.product_name or '—' }}</td>
            <td><span class="status-badge status-{{ e.status }}">{{ e.status }}</span></td>
            <td>
              <a href="https://wa.me/91{{ e.phone }}?text=Hi {{ e.name }}! Thank you for your enquiry about {{ e.product_name or 'our collection' }}." target="_blank">
                <button class="action-btn wa-btn">WhatsApp</button>
              </a>
            </td>
          </tr>
          {% endfor %}
          </tbody>
        </table>
      </div>

      <div>
        <div class="section-header">
          <div class="section-title">Recent Orders</div>
          <button class="tab active" onclick="loadSection('orders')">View All</button>
        </div>
        <table>
          <thead><tr><th>Name</th><th>Product</th><th>Payment</th><th>Status</th></tr></thead>
          <tbody>
          {% for o in recent_orders %}
          <tr>
            <td>{{ o.name }}</td>
            <td>{{ o.product_name }}</td>
            <td>{{ o.payment_method }}</td>
            <td><span class="status-badge status-{{ o.status }}">{{ o.status }}</span></td>
          </tr>
          {% endfor %}
          </tbody>
        </table>
      </div>
    </div>

  </div><!-- /content -->
</main>

<div class="toast" id="toast"></div>

<script>
document.getElementById('topbarDate').textContent = new Date().toLocaleDateString('en-IN', {weekday:'long',year:'numeric',month:'long',day:'numeric'});

function showToast(msg, type='success') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.background = type === 'success' ? 'rgba(27,107,61,0.9)' : 'rgba(139,26,26,0.9)';
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 3000);
}

async function loadSection(section) {
  const main = document.getElementById('mainContent');
  const title = document.getElementById('pageTitle');
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

  if (section === 'enquiries') {
    title.textContent = 'Enquiries';
    const res = await fetch('/admin/api/enquiries?limit=50');
    const data = await res.json();
    main.innerHTML = renderEnquiries(data.enquiries);
  } else if (section === 'orders') {
    title.textContent = 'Orders';
    const res = await fetch('/admin/api/orders?limit=50');
    const data = await res.json();
    main.innerHTML = renderOrders(data.orders);
  } else if (section === 'products') {
    title.textContent = 'Products';
    const res = await fetch('/admin/api/products');
    const data = await res.json();
    main.innerHTML = renderProducts(data.products);
  } else if (section === 'newsletter') {
    title.textContent = 'Newsletter Subscribers';
    const res = await fetch('/admin/api/newsletter');
    const data = await res.json();
    main.innerHTML = renderNewsletter(data.subscribers);
  }
}

function statusBadge(s) {
  return `<span class="status-badge status-${s}">${s}</span>`;
}

function renderEnquiries(rows) {
  const statuses = ['new','contacted','closed'];
  let html = `<table><thead><tr><th>#</th><th>Date</th><th>Name</th><th>Phone</th><th>Email</th><th>Product</th><th>Message</th><th>Status</th><th>Actions</th></tr></thead><tbody>`;
  rows.forEach(e => {
    html += `<tr>
      <td>${e.id}</td>
      <td>${e.created_at.slice(0,16)}</td>
      <td>${e.name}</td>
      <td>${e.phone}</td>
      <td>${e.email||'—'}</td>
      <td>${e.product_name||'—'}</td>
      <td>${(e.message||'—').slice(0,40)}</td>
      <td>${statusBadge(e.status)}</td>
      <td style="display:flex;gap:6px;flex-wrap:wrap;">
        <a href="https://wa.me/91${e.phone}?text=Hi ${encodeURIComponent(e.name)}! Thank you for your enquiry." target="_blank">
          <button class="action-btn wa-btn">WA</button>
        </a>
        ${statuses.filter(s=>s!==e.status).map(s=>`<button class="action-btn" onclick="updateEnquiry(${e.id},'${s}')">${s}</button>`).join('')}
      </td>
    </tr>`;
  });
  return html + '</tbody></table>';
}

function renderOrders(rows) {
  let html = `<table><thead><tr><th>#</th><th>Date</th><th>Name</th><th>Phone</th><th>Product</th><th>Size</th><th>Payment</th><th>Notes</th><th>Status</th><th>Actions</th></tr></thead><tbody>`;
  const nextStatus = {pending:'confirmed',confirmed:'stitching',stitching:'ready',ready:'shipped',shipped:'delivered'};
  rows.forEach(o => {
    const next = nextStatus[o.status];
    html += `<tr>
      <td>${o.id}</td>
      <td>${o.created_at.slice(0,16)}</td>
      <td>${o.name}</td>
      <td>${o.phone}</td>
      <td>${o.product_name}</td>
      <td>${o.size||'—'}</td>
      <td>${o.payment_method}</td>
      <td>${(o.custom_notes||'—').slice(0,30)}</td>
      <td>${statusBadge(o.status)}</td>
      <td style="display:flex;gap:6px;flex-wrap:wrap;">
        <a href="https://wa.me/91${o.phone}?text=Hi ${encodeURIComponent(o.name)}! Your order update:" target="_blank">
          <button class="action-btn wa-btn">WA</button>
        </a>
        ${next ? `<button class="action-btn" onclick="updateOrder(${o.id},'${next}')">${next}</button>` : ''}
        <button class="action-btn" style="color:#F2A080;border-color:rgba(242,160,128,0.3);" onclick="updateOrder(${o.id},'cancelled')">Cancel</button>
      </td>
    </tr>`;
  });
  return html + '</tbody></table>';
}

function renderProducts(rows) {
  let html = `<div style="text-align:right;margin-bottom:16px;">
    <button class="tab active" onclick="showAddProduct()">+ Add Product</button>
  </div>
  <table><thead><tr><th>#</th><th>Name</th><th>Category</th><th>Fabric</th><th>Color</th><th>Tag</th><th>Active</th><th>Actions</th></tr></thead><tbody>`;
  rows.forEach(p => {
    html += `<tr>
      <td>${p.id}</td>
      <td>${p.name}</td>
      <td>${p.category}</td>
      <td>${p.fabric||'—'}</td>
      <td>${p.color||'—'}</td>
      <td>${p.tag||'—'}</td>
      <td>${p.is_active ? '✅' : '❌'}</td>
      <td>
        <button class="action-btn" style="color:#F2A080;border-color:rgba(242,160,128,0.3);" onclick="deleteProduct(${p.id})">Archive</button>
      </td>
    </tr>`;
  });
  return html + '</tbody></table>';
}

function renderNewsletter(rows) {
  let html = `<div style="margin-bottom:12px;font-size:11px;color:var(--gold);">${rows.length} active subscribers</div>
  <table><thead><tr><th>#</th><th>Name</th><th>Email</th><th>WhatsApp</th><th>Joined</th></tr></thead><tbody>`;
  rows.forEach(s => {
    html += `<tr>
      <td>${s.id}</td>
      <td>${s.name||'—'}</td>
      <td>${s.email}</td>
      <td>${s.whatsapp||'—'}</td>
      <td>${s.created_at.slice(0,10)}</td>
    </tr>`;
  });
  return html + '</tbody></table>';
}

async function updateEnquiry(id, status) {
  const res = await fetch(`/admin/api/enquiries/${id}`, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})});
  if (res.ok) { showToast(`Enquiry #${id} marked as ${status}`); loadSection('enquiries'); }
  else showToast('Update failed', 'error');
}

async function updateOrder(id, status) {
  const res = await fetch(`/admin/api/orders/${id}`, {method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})});
  if (res.ok) { showToast(`Order #${id} → ${status}`); loadSection('orders'); }
  else showToast('Update failed', 'error');
}

async function deleteProduct(id) {
  if (!confirm('Archive this product?')) return;
  const res = await fetch(`/admin/api/products/${id}`, {method:'DELETE'});
  if (res.ok) { showToast('Product archived'); loadSection('products'); }
  else showToast('Failed', 'error');
}

function showAddProduct() {
  const name = prompt('Product Name:');
  if (!name) return;
  const category = prompt('Category (e.g. Angrakha, Kurti Set):');
  if (!category) return;
  fetch('/admin/api/products', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name, category})
  }).then(r => r.json()).then(d => {
    if (d.success) { showToast('Product added!'); loadSection('products'); }
    else showToast(d.error || 'Failed', 'error');
  });
}
</script>
</body>
</html>
"""

# ─── Entry Point ──────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    print("\n✦ Syamaa Backend Starting ✦")
    print(f"  → Frontend :  http://127.0.0.1:5000/")
    print(f"  → Admin    :  http://127.0.0.1:5000/admin/dashboard")
    print(f"  → API      :  http://127.0.0.1:5000/api/products")
    print(f"  → Health   :  http://127.0.0.1:5000/health")
    print(f"  → Admin login: {ADMIN_EMAIL} / {ADMIN_PASSWORD}\n")
    app.run(debug=True, host="0.0.0.0", port=5000)
