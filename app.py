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
from urllib.parse import quote
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
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id     TEXT    UNIQUE,
            name           TEXT    NOT NULL,
            category       TEXT    NOT NULL,
            short_desc     TEXT,
            description    TEXT,
            price          TEXT    DEFAULT 'Contact for Price',
            stock_qty      INTEGER DEFAULT 0,
            status         TEXT    DEFAULT 'active',
            tags           TEXT,
            featured       INTEGER DEFAULT 0,
            display_order  INTEGER DEFAULT 0,
            style          TEXT,
            fabric         TEXT,
            color          TEXT,
            features       TEXT,
            image_url      TEXT,
            tag            TEXT,
            is_active      INTEGER DEFAULT 1,
            created_at     TEXT    DEFAULT (datetime('now'))
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

        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            name          TEXT    NOT NULL,
            email         TEXT    UNIQUE NOT NULL,
            phone         TEXT,
            password_hash TEXT    NOT NULL,
            address       TEXT,
            payment_mode  TEXT,
            is_active     INTEGER DEFAULT 1,
            created_at    TEXT    DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS cart_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            product_id  INTEGER REFERENCES products(id),
            product_name TEXT   NOT NULL,
            price       TEXT    DEFAULT 'Contact for Price',
            image_url   TEXT,
            quantity    INTEGER DEFAULT 1,
            size        TEXT,
            notes       TEXT,
            added_at    TEXT    DEFAULT (datetime('now'))
        );
    """
    )
    try:
        db.execute("ALTER TABLE users ADD COLUMN payment_mode TEXT")
    except sqlite3.OperationalError:
        pass

    try:
        db.execute("ALTER TABLE products ADD COLUMN product_id TEXT")
    except sqlite3.OperationalError:
        pass
    for col, ddl in [
        ("short_desc", "ALTER TABLE products ADD COLUMN short_desc TEXT"),
        ("description", "ALTER TABLE products ADD COLUMN description TEXT"),
        ("stock_qty", "ALTER TABLE products ADD COLUMN stock_qty INTEGER DEFAULT 0"),
        ("status", "ALTER TABLE products ADD COLUMN status TEXT DEFAULT 'active'"),
        ("tags", "ALTER TABLE products ADD COLUMN tags TEXT"),
        ("featured", "ALTER TABLE products ADD COLUMN featured INTEGER DEFAULT 0"),
        (
            "display_order",
            "ALTER TABLE products ADD COLUMN display_order INTEGER DEFAULT 0",
        ),
    ]:
        try:
            db.execute(ddl)
        except sqlite3.OperationalError:
            pass

    rows = db.execute(
        "SELECT id, product_id, status, stock_qty FROM products"
    ).fetchall()
    for row in rows:
        if not row["product_id"]:
            code = f"SYA{row['id']:04d}"
            db.execute("UPDATE products SET product_id=? WHERE id=?", (code, row["id"]))
        if not row["status"]:
            db.execute("UPDATE products SET status='active' WHERE id=?", (row["id"],))
        if row["stock_qty"] is None:
            db.execute("UPDATE products SET stock_qty=0 WHERE id=?", (row["id"],))

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


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            return jsonify({"error": "Login required"}), 401
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


@app.route("/api/public/products", methods=["GET"])
def public_products():
    products, _ = build_products_from_images()

    def is_featured(value):
        return str(value).strip().lower() in ("1", "true", "yes", "on")

    featured = [p for p in products if is_featured(p.get("featured"))]
    return jsonify({"products": products, "featured": featured})


@app.route("/api/products/categories", methods=["GET"])
def get_categories():
    cats = query(
        "SELECT DISTINCT category, COUNT(*) as count FROM products WHERE is_active=1 AND status='active' GROUP BY category"
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

    wa_text = f"Hi! I enquired about {pname or 'your collection'}"
    return (
        jsonify(
            {
                "success": True,
                "message": "Thank you! We'll contact you on WhatsApp soon.",
                "wa_link": f"https://wa.me/916282201008?text={quote(wa_text)}",
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
                "wa_link": f"https://wa.me/916282201008?text={quote(wa_text)}",
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

    if not product_name:
        return jsonify({"error": "Product name is required"}), 400

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


# ─── API: User Registration & Auth ───────────────────────────
@app.route("/api/auth/register", methods=["POST"])
def user_register():
    data = request.get_json(silent=True) or request.form.to_dict()

    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    phone = re.sub(r"[\s\-\+()]", "", (data.get("phone") or ""))
    password = data.get("password") or ""
    address = (data.get("address") or "").strip()

    if not name:
        return jsonify({"error": "Name is required"}), 400
    if not email or not validate_email(email):
        return jsonify({"error": "A valid email is required"}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters"}), 400
    if phone and not validate_phone(phone):
        return jsonify({"error": "Please enter a valid 10-digit phone number"}), 400

    existing = query("SELECT id FROM users WHERE email=?", (email,), one=True)
    if existing:
        return jsonify({"error": "An account with this email already exists"}), 409

    pw_hash = hash_password(password)
    query(
        "INSERT INTO users (name,email,phone,password_hash,address) VALUES (?,?,?,?,?)",
        (name, email, phone or None, pw_hash, address or None),
    )
    user = query("SELECT * FROM users WHERE email=?", (email,), one=True)
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    session["user_email"] = user["email"]

    return (
        jsonify(
            {
                "success": True,
                "message": f"Welcome to Syamaa, {name}! ✦",
                "user": {
                    "id": user["id"],
                    "name": user["name"],
                    "email": user["email"],
                },
            }
        ),
        201,
    )


@app.route("/api/auth/login", methods=["POST"])
def user_login():
    data = request.get_json(silent=True) or request.form.to_dict()

    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    user = query(
        "SELECT * FROM users WHERE email=? AND is_active=1", (email,), one=True
    )
    if not user or not hmac.compare_digest(
        user["password_hash"], hash_password(password)
    ):
        return jsonify({"error": "Invalid email or password"}), 401

    session.permanent = True
    session["user_id"] = user["id"]
    session["user_name"] = user["name"]
    session["user_email"] = user["email"]

    return jsonify(
        {
            "success": True,
            "message": f"Welcome back, {user['name']}! ✦",
            "user": {"id": user["id"], "name": user["name"], "email": user["email"]},
        }
    )


@app.route("/api/auth/logout", methods=["POST"])
def user_logout():
    session.pop("user_id", None)
    session.pop("user_name", None)
    session.pop("user_email", None)
    return jsonify({"success": True, "message": "Logged out successfully"})


@app.route("/api/auth/me", methods=["GET"])
@login_required
def user_me():
    user = query(
        "SELECT id,name,email,phone,address,payment_mode,created_at FROM users WHERE id=?",
        (session["user_id"],),
        one=True,
    )
    if not user:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"user": user})


@app.route("/api/profile", methods=["GET", "POST"])
@login_required
def profile():
    user = query(
        "SELECT id,name,email,phone,address,payment_mode,created_at FROM users WHERE id=?",
        (session["user_id"],),
        one=True,
    )
    if not user:
        return jsonify({"error": "User not found"}), 404

    if request.method == "GET":
        return jsonify({"user": user})

    data = request.get_json(silent=True) or request.form.to_dict()
    name = (data.get("name") or "").strip() if "name" in data else user["name"]
    if "name" in data and not name:
        return jsonify({"error": "Name is required"}), 400

    phone_input = (
        (data.get("phone") or "").strip()
        if "phone" in data
        else (user.get("phone") or "")
    )
    address = (
        (data.get("address") or "").strip()
        if "address" in data
        else (user.get("address") or "")
    )
    payment_mode = (
        (data.get("payment_mode") or "").strip()
        if "payment_mode" in data
        else (user.get("payment_mode") or "")
    )

    if phone_input:
        clean_phone = re.sub(r"[\s\-\+()]", "", phone_input)
        if not validate_phone(clean_phone):
            return jsonify({"error": "Please enter a valid 10-digit phone number"}), 400
    else:
        clean_phone = None

    query(
        "UPDATE users SET name=?, phone=?, address=?, payment_mode=? WHERE id=?",
        (name, clean_phone, address or None, payment_mode or None, session["user_id"]),
    )
    user = query(
        "SELECT id,name,email,phone,address,payment_mode,created_at FROM users WHERE id=?",
        (session["user_id"],),
        one=True,
    )
    return jsonify({"success": True, "user": user})


@app.route("/api/orders/mine", methods=["GET"])
@login_required
def my_orders():
    user = query(
        "SELECT email,phone FROM users WHERE id=?",
        (session["user_id"],),
        one=True,
    )
    if not user:
        return jsonify({"error": "User not found"}), 404

    email = user.get("email") or ""
    phone = user.get("phone") or ""
    conditions = []
    params = []
    if email:
        conditions.append("email=?")
        params.append(email)
    if phone:
        conditions.append("phone=?")
        params.append(phone)

    if not conditions:
        return jsonify({"orders": [], "count": 0})

    sql = (
        "SELECT id,product_name,size,fabric_choice,color_choice,"
        "payment_method,total_amount,status,created_at "
        "FROM orders WHERE " + " OR ".join(conditions) + " ORDER BY created_at DESC"
    )
    rows = query(sql, tuple(params))
    return jsonify({"orders": rows, "count": len(rows)})


# ─── API: Cart ────────────────────────────────────────────────
@app.route("/api/cart", methods=["GET"])
@login_required
def get_cart():
    items = query(
        "SELECT * FROM cart_items WHERE user_id=? ORDER BY added_at DESC",
        (session["user_id"],),
    )
    return jsonify({"cart": items, "count": len(items)})


@app.route("/api/cart", methods=["POST"])
@login_required
def add_to_cart():
    data = request.get_json(silent=True) or request.form.to_dict()

    product_id_raw = data.get("product_id")
    product_name = (data.get("product_name") or "").strip()
    quantity = int(data.get("quantity") or 1)
    size = (data.get("size") or "").strip()
    notes = (data.get("notes") or "").strip()

    if quantity < 1:
        return jsonify({"error": "Quantity must be at least 1"}), 400

    # If product_id given, fetch latest details
    price = "Contact for Price"
    image_url = None
    product_id = None
    if product_id_raw:
        pid_str = str(product_id_raw).strip()
        if pid_str.isdigit():
            p = query(
                "SELECT id,product_id,name,price,image_url FROM products WHERE id=?",
                (int(pid_str),),
                one=True,
            )
        else:
            p = query(
                "SELECT id,product_id,name,price,image_url FROM products WHERE product_id=?",
                (product_code(pid_str),),
                one=True,
            )
        if p:
            product_id = p["id"]
            price = p["price"]
            image_url = p["image_url"]
            if not product_name:
                product_name = p["name"]

    if not product_name:
        return jsonify({"error": "Product name is required"}), 400

    # Check if same product+size already in cart → increment quantity
    existing = query(
        "SELECT id,quantity FROM cart_items WHERE user_id=? AND product_name=? AND (size=? OR (size IS NULL AND ?=''))",
        (session["user_id"], product_name, size, size),
        one=True,
    )
    if existing:
        new_qty = existing["quantity"] + quantity
        query("UPDATE cart_items SET quantity=? WHERE id=?", (new_qty, existing["id"]))
        return jsonify(
            {"success": True, "message": "Cart updated ✦", "action": "updated"}
        )

    query(
        "INSERT INTO cart_items (user_id,product_id,product_name,price,image_url,quantity,size,notes) VALUES (?,?,?,?,?,?,?,?)",
        (
            session["user_id"],
            product_id or None,
            product_name,
            price,
            image_url,
            quantity,
            size or None,
            notes or None,
        ),
    )
    return (
        jsonify(
            {
                "success": True,
                "message": f"'{product_name}' added to cart 🛍️",
                "action": "added",
            }
        ),
        201,
    )


@app.route("/api/cart/<int:item_id>", methods=["PATCH"])
@login_required
def update_cart_item(item_id):
    data = request.get_json(silent=True) or {}
    item = query(
        "SELECT id FROM cart_items WHERE id=? AND user_id=?",
        (item_id, session["user_id"]),
        one=True,
    )
    if not item:
        return jsonify({"error": "Cart item not found"}), 404

    quantity = data.get("quantity")
    size = data.get("size")
    notes = data.get("notes")

    if quantity is not None:
        if int(quantity) < 1:
            return jsonify({"error": "Quantity must be at least 1"}), 400
        query("UPDATE cart_items SET quantity=? WHERE id=?", (int(quantity), item_id))
    if size is not None:
        query("UPDATE cart_items SET size=? WHERE id=?", (size, item_id))
    if notes is not None:
        query("UPDATE cart_items SET notes=? WHERE id=?", (notes, item_id))

    return jsonify({"success": True, "message": "Cart item updated"})


@app.route("/api/cart/<int:item_id>", methods=["DELETE"])
@login_required
def remove_from_cart(item_id):
    item = query(
        "SELECT id FROM cart_items WHERE id=? AND user_id=?",
        (item_id, session["user_id"]),
        one=True,
    )
    if not item:
        return jsonify({"error": "Cart item not found"}), 404
    query("DELETE FROM cart_items WHERE id=?", (item_id,))
    return jsonify({"success": True, "message": "Item removed from cart"})


@app.route("/api/cart/clear", methods=["DELETE"])
@login_required
def clear_cart():
    query("DELETE FROM cart_items WHERE user_id=?", (session["user_id"],))
    return jsonify({"success": True, "message": "Cart cleared"})


@app.route("/api/checkout", methods=["POST"])
@login_required
def checkout_cart():
    data = request.get_json(silent=True) or {}

    user = query(
        "SELECT id,name,email,phone,address,payment_mode FROM users WHERE id=? AND is_active=1",
        (session["user_id"],),
        one=True,
    )
    if not user:
        return jsonify({"error": "User not found"}), 404

    if not user.get("phone"):
        return (
            jsonify(
                {
                    "error": "Please add your phone number in your account before checkout"
                }
            ),
            400,
        )

    address = (data.get("address") or "").strip() or (user.get("address") or "")
    payment = data.get("payment_method") or user.get("payment_mode") or "COD"

    items = query(
        "SELECT * FROM cart_items WHERE user_id=? ORDER BY added_at DESC",
        (session["user_id"],),
    )
    if not items:
        return jsonify({"error": "Your cart is empty"}), 400

    for item in items:
        product_name = item.get("product_name") or ""
        size = item.get("size") or ""
        notes = item.get("notes") or ""
        qty = item.get("quantity") or 1
        custom_notes = f"Qty: {qty}" + (f" | {notes}" if notes else "")
        total_amount = item.get("price") or "Contact for Price"

        query(
            """INSERT INTO orders
               (name,phone,email,address,product_name,size,custom_notes,
                fabric_choice,color_choice,payment_method,total_amount)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                user["name"],
                user["phone"],
                user.get("email"),
                address or None,
                product_name,
                size or None,
                custom_notes or None,
                None,
                None,
                payment,
                total_amount,
            ),
        )

    query("DELETE FROM cart_items WHERE user_id=?", (session["user_id"],))

    return jsonify(
        {"success": True, "message": f"Order placed for {len(items)} item(s)"}
    )


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
        "registered_users": query(
            "SELECT COUNT(*) as c FROM users WHERE is_active=1", one=True
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
    image_map = scan_image_library()
    products = []
    for row in rows:
        item = dict(row)
        pid = product_code(item.get("product_id")) or f"SYA{item['id']:04d}"
        item["product_id"] = pid
        images = image_map.get(pid, [])
        item["image_count"] = len(images)
        item["has_poster"] = any(
            img.split("/")[-1].lower().startswith("poster") for img in images
        )
        products.append(item)
    return jsonify({"products": products})


@app.route("/admin/api/products", methods=["POST"])
@admin_required
def admin_add_product():
    data = request.get_json(silent=True) or request.form.to_dict()
    product_id = (data.get("product_id") or "").strip().upper()
    if not data.get("name") or not data.get("category"):
        return jsonify({"error": "Name and category are required"}), 400
    if not re.match(r"^SYA\d{4}$", product_id):
        return jsonify({"error": "Product ID must be like SYA0001"}), 400
    existing = query(
        "SELECT id FROM products WHERE product_id=?", (product_id,), one=True
    )
    if existing:
        return jsonify({"error": "Product ID already exists"}), 400

    features = (
        "|".join(data.get("features", []))
        if isinstance(data.get("features"), list)
        else (data.get("features") or "")
    )

    status = (data.get("status") or "active").lower()
    if status not in ("active", "draft", "hidden"):
        return jsonify({"error": "Invalid status"}), 400
    featured = (
        1 if str(data.get("featured")).lower() in ("1", "true", "yes", "on") else 0
    )

    query(
        "INSERT INTO products (product_id,name,category,short_desc,description,price,stock_qty,status,tags,featured,display_order,style,fabric,color,features,tag)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            product_id,
            data["name"],
            data["category"],
            data.get("short_desc"),
            data.get("description"),
            data.get("price") or "Contact for Price",
            int(data.get("stock_qty") or 0),
            status,
            data.get("tags"),
            featured,
            int(data.get("display_order") or 0),
            data.get("style"),
            data.get("fabric"),
            data.get("color"),
            features,
            data.get("tag"),
        ),
    )
    ensure_product_folder(product_id)
    return jsonify({"success": True})


@app.route("/admin/api/products/<int:pid>", methods=["PUT"])
@admin_required
def admin_update_product(pid):
    data = request.get_json(silent=True) or {}
    existing = query("SELECT id, product_id FROM products WHERE id=?", (pid,), one=True)
    if not existing:
        return jsonify({"error": "Product not found"}), 404
    existing_pid = product_code(existing.get("product_id"))
    product_id = (data.get("product_id") or "").strip().upper()

    if existing_pid:
        if product_id and product_id != existing_pid:
            return jsonify({"error": "Product ID is immutable once set"}), 400
        product_id = None
    else:
        if product_id and not re.match(r"^SYA\d{4}$", product_id):
            return jsonify({"error": "Product ID must be like SYA0001"}), 400
        if product_id:
            existing_check = query(
                "SELECT id FROM products WHERE product_id=? AND id!=?",
                (product_id, pid),
                one=True,
            )
            if existing_check:
                return jsonify({"error": "Product ID already exists"}), 400

    features = (
        "|".join(data.get("features", []))
        if isinstance(data.get("features"), list)
        else data.get("features", "")
    )
    status = (data.get("status") or "active").lower()
    if status not in ("active", "draft", "hidden"):
        return jsonify({"error": "Invalid status"}), 400
    featured = (
        1 if str(data.get("featured")).lower() in ("1", "true", "yes", "on") else 0
    )
    query(
        """UPDATE products SET
           product_id=COALESCE(?, product_id),
           name=?,
           category=?,
           short_desc=?,
           description=?,
           price=?,
           stock_qty=?,
           status=?,
           tags=?,
           featured=?,
           display_order=?,
           style=?,
           fabric=?,
           color=?,
           features=?,
           tag=?,
           is_active=?
           WHERE id=?""",
        (
            product_id or None,
            data.get("name"),
            data.get("category"),
            data.get("short_desc"),
            data.get("description"),
            data.get("price", "Contact for Price"),
            int(data.get("stock_qty") or 0),
            status,
            data.get("tags"),
            featured,
            int(data.get("display_order") or 0),
            data.get("style"),
            data.get("fabric"),
            data.get("color"),
            features,
            data.get("tag"),
            int(data.get("is_active", 1)),
            pid,
        ),
    )
    if product_id:
        ensure_product_folder(product_id)
    return jsonify({"success": True})


@app.route("/admin/api/products/<int:pid>", methods=["DELETE"])
@admin_required
def admin_delete_product(pid):
    hard = request.args.get("hard") in {"1", "true", "yes"}
    if hard:
        query("DELETE FROM cart_items WHERE product_id=?", (pid,))
        query("UPDATE enquiries SET product_id=NULL WHERE product_id=?", (pid,))
        query("DELETE FROM products WHERE id=?", (pid,))
        return jsonify({"success": True, "deleted": True})
    query("UPDATE products SET is_active=0,status='hidden' WHERE id=?", (pid,))
    return jsonify({"success": True, "deleted": False})


@app.route("/admin/api/product-images/<pid>")
@admin_required
def admin_product_images(pid):
    normalized = product_id_from_code(pid) or (pid or "").strip().upper()
    if not re.match(r"^SYA\d{4}$", normalized):
        return jsonify({"error": "Invalid product ID"}), 400
    image_map = scan_image_library()
    images = image_map.get(normalized, [])
    return jsonify(
        {
            "product_id": normalized,
            "images": images,
            "poster": images[0] if images else None,
        }
    )


@app.route("/admin/api/newsletter")
@admin_required
def admin_newsletter():
    rows = query("SELECT * FROM newsletter WHERE is_active=1 ORDER BY created_at DESC")
    return jsonify({"subscribers": rows, "count": len(rows)})


@app.route("/admin/api/users")
@admin_required
def admin_users():
    rows = query(
        "SELECT id,name,email,phone,address,is_active,created_at FROM users ORDER BY created_at DESC"
    )
    return jsonify({"users": rows, "count": len(rows)})


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


def product_code(product_id):
    if not product_id:
        return None
    return str(product_id).strip().upper()


def product_id_from_code(code):
    if not code:
        return None
    if code.isdigit():
        return f"SYA{int(code):04d}"
    m = re.match(r"^SYA(\d{4})$", code.upper())
    if not m:
        return None
    return code.upper()


IMAGE_ROOT = BASE_DIR / "instance" / "images"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
_image_cache = {"mtime": 0, "file_count": 0, "by_id": {}}


def ensure_product_folder(product_id):
    if not product_id:
        return
    try:
        (IMAGE_ROOT / product_id).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def scan_image_library():
    root = IMAGE_ROOT
    if not root.exists():
        return {}

    latest_mtime = 0
    file_count = 0
    for dirpath, _, filenames in os.walk(root):
        try:
            latest_mtime = max(latest_mtime, Path(dirpath).stat().st_mtime)
        except OSError:
            pass
        for fname in filenames:
            if fname.endswith(".Zone.Identifier") or fname.startswith("."):
                continue
            ext = Path(fname).suffix.lower()
            if ext not in IMAGE_EXTS:
                continue
            file_count += 1
            try:
                mtime = (Path(dirpath) / fname).stat().st_mtime
                latest_mtime = max(latest_mtime, mtime)
            except OSError:
                continue

    if (
        latest_mtime
        and latest_mtime == _image_cache["mtime"]
        and file_count == _image_cache["file_count"]
    ):
        return _image_cache["by_id"]

    by_id = {}
    for dirpath, _, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        parts = [p for p in rel.parts if p]
        if not parts:
            continue
        pid = None
        for part in parts:
            if re.match(r"^SYA\d{4}$", part.upper()):
                pid = part.upper()
                break
        if not pid:
            continue
        images = []
        for fname in sorted(filenames):
            if fname.endswith(".Zone.Identifier") or fname.startswith("."):
                continue
            ext = Path(fname).suffix.lower()
            if ext not in IMAGE_EXTS:
                continue
            rel_file = (Path(dirpath).relative_to(root) / fname).as_posix()
            images.append("/media/" + rel_file)
        if not images:
            continue
        poster = [img for img in images if Path(img).name.lower().startswith("poster")]
        others = [img for img in images if img not in poster]
        images = poster + others
        existing = by_id.get(pid, [])
        for img in images:
            if img not in existing:
                existing.append(img)
        by_id[pid] = existing

    _image_cache["mtime"] = latest_mtime
    _image_cache["file_count"] = file_count
    _image_cache["by_id"] = by_id
    return by_id


def svg_placeholder(title, subtitle="Syamaa Couture"):
    svg = f"""
<svg xmlns='http://www.w3.org/2000/svg' width='900' height='1200' viewBox='0 0 900 1200'>
  <defs>
    <linearGradient id='g' x1='0' x2='1' y1='0' y2='1'>
      <stop offset='0%' stop-color='#25120B'/>
      <stop offset='100%' stop-color='#5B2B1B'/>
    </linearGradient>
  </defs>
  <rect width='900' height='1200' fill='url(#g)'/>
  <rect x='60' y='80' width='780' height='1040' rx='36' fill='rgba(255,255,255,0.03)' stroke='rgba(201,144,12,0.3)'/>
  <text x='90' y='180' fill='#F0C040' font-family='Cormorant Garamond, serif' font-size='48'>{title}</text>
  <text x='90' y='240' fill='rgba(242,213,176,0.7)' font-family='Josefin Sans, sans-serif' font-size='20' letter-spacing='4'>{subtitle}</text>
  <text x='90' y='1060' fill='rgba(242,213,176,0.6)' font-family='Josefin Sans, sans-serif' font-size='14' letter-spacing='3'>SYAMAA SIGNATURE</text>
</svg>
"""
    return "data:image/svg+xml;utf8," + quote(svg)


def product_description(product):
    if product.get("features"):
        return product["features"].replace("|", ", ")
    return "Boutique-crafted silhouette with artisanal finishing."


def build_products_from_images():
    image_map = scan_image_library()
    rows = query(
        "SELECT * FROM products WHERE is_active=1 OR is_active IS NULL ORDER BY display_order ASC, id DESC"
    )
    products = []
    by_pid = {}

    for p in rows:
        item = dict(p)
        status = str(item.get("status") or "active").strip().lower()
        item["status"] = status
        if status != "active":
            continue
        # Treat NULL is_active as active to preserve legacy rows
        is_active = item.get("is_active")
        if is_active in (0, "0", False):
            continue
        pid = product_code(item.get("product_id")) or f"SYA{item['id']:04d}"
        item["product_id"] = pid
        images = image_map.get(pid, [])
        if images:
            item["image"] = images[0]
            item["images"] = images
        else:
            item["image"] = svg_placeholder(item.get("name", "Syamaa"))
            item["images"] = [item["image"]]
        products.append(item)
        by_pid[pid] = item

    return products, by_pid


PRODUCTS_PAGE_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Syamaa | All Products</title>
<link href="https://fonts.googleapis.com/css2...family=Cormorant+Garamond:ital,wght@0,300;0,400;1,400&family=Josefin+Sans:wght@300;400&display=swap" rel="stylesheet">
<style>
  :root { --dark:#1A0F0A; --gold:#C9900C; --gold-light:#F0C040; --cream:#FAF3E8; --blush:#F2D5B0; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { min-height:100vh; background:#120906; color:var(--cream); font-family:'Josefin Sans',sans-serif; }
  a { color:inherit; text-decoration:none; }
  .page { max-width:1200px; margin:0 auto; padding:48px 24px 80px; }
  .topbar { display:flex; align-items:center; justify-content:space-between; margin-bottom:32px; }
  .brand { font-family:'Cormorant Garamond',serif; font-size:36px; color:var(--gold-light); letter-spacing:1px; }
  .back-link { font-size:12px; letter-spacing:0.3em; text-transform:uppercase; color:rgba(242,213,176,0.7); }
  .hero { display:flex; align-items:flex-end; justify-content:space-between; gap:24px; margin-bottom:28px; }
  .hero h1 { font-family:'Cormorant Garamond',serif; font-size:42px; font-weight:300; }
  .hero p { max-width:520px; line-height:1.6; color:rgba(242,213,176,0.7); }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(240px,1fr)); gap:24px; }
  .card { position:relative; border:1px solid rgba(201,144,12,0.2); background:rgba(255,255,255,0.02); padding:16px; border-radius:18px; transition:transform 0.3s, border-color 0.3s, box-shadow 0.3s; }
  .card:hover { transform:translateY(-6px); border-color:rgba(201,144,12,0.5); box-shadow:0 20px 40px rgba(0,0,0,0.25); }
  .card img { width:100%; border-radius:14px; aspect-ratio:3/4; object-fit:cover; }
  .wishlist { position:absolute; top:18px; right:18px; border:1px solid rgba(201,144,12,0.4); background:rgba(20,10,6,0.8); color:var(--gold-light); width:36px; height:36px; border-radius:50%; display:flex; align-items:center; justify-content:center; font-size:16px; }
  .card .meta { display:flex; justify-content:space-between; margin-top:12px; font-size:11px; letter-spacing:0.2em; text-transform:uppercase; color:rgba(242,213,176,0.7); }
  .card h3 { margin-top:8px; font-family:'Cormorant Garamond',serif; font-size:20px; font-weight:300; }
  .price { margin-top:6px; font-size:14px; color:var(--gold-light); letter-spacing:0.12em; text-transform:uppercase; }
  .card-actions { margin-top:12px; display:flex; gap:10px; }
  .btn { padding:10px 14px; border-radius:999px; text-transform:uppercase; letter-spacing:0.2em; font-size:10px; border:1px solid rgba(201,144,12,0.4); }
  .btn-primary { background:var(--gold); color:#120906; border:none; }
</style>
</head>
<body>
  <div class="page">
    <div class="topbar">
      <div class="brand">Syamaa</div>
      <a class="back-link" href="/">Back to Home</a>
    </div>
    <div class="hero">
      <div>
        <h1>All Products</h1>
        <p>Explore every silhouette in our atelier. Each product has a dedicated ID, price, and a full detail page with multiple views.</p>
      </div>
      <div class="price">{{ products|length }} Styles</div>
    </div>

    <div class="grid">
      {% for p in products %}
      <a class="card" href="/product/{{ p.product_id }}">
        <span class="wishlist">...</span>
        <img src="{{ p.image }}" alt="{{ p.name }}" loading="lazy">
        <div class="meta">
          <span>{{ p.product_id }}</span>
          <span>{{ p.category }}</span>
        </div>
        <h3>{{ p.name }}</h3>
        <div class="price">{{ p.price or 'Contact for Price' }}</div>
        <div class="card-actions">
          <span class="btn">Quick View</span>
          <span class="btn btn-primary">View Details</span>
        </div>
      </a>
      {% endfor %}
    </div>
  </div>
</body>
</html>
"""

PRODUCT_DETAIL_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{{ product.name }} | Syamaa</title>
<link href="https://fonts.googleapis.com/css2...family=Cormorant+Garamond:ital,wght@0,300;0,400;1,400&family=Josefin+Sans:wght@300;400&display=swap" rel="stylesheet">
<style>
  :root { --dark:#1A0F0A; --gold:#C9900C; --gold-light:#F0C040; --cream:#FAF3E8; --blush:#F2D5B0; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { min-height:100vh; background:#120906; color:var(--cream); font-family:'Josefin Sans',sans-serif; }
  a { color:inherit; text-decoration:none; }
  .page { max-width:1100px; margin:0 auto; padding:48px 24px 80px; }
  .topbar { display:flex; align-items:center; justify-content:space-between; margin-bottom:24px; }
  .brand { font-family:'Cormorant Garamond',serif; font-size:36px; color:var(--gold-light); letter-spacing:1px; }
  .breadcrumbs { font-size:11px; letter-spacing:0.2em; text-transform:uppercase; color:rgba(242,213,176,0.7); }
  .content { display:grid; grid-template-columns:1.1fr 0.9fr; gap:36px; }
  .gallery-main { width:100%; border-radius:22px; border:1px solid rgba(201,144,12,0.3); aspect-ratio:unset; max-height:600px; object-fit:contain; background:#1A0F0A; transition:opacity 0.25s ease; }
  .thumbs { display:flex !important; flex-wrap:wrap; gap:12px; margin-top:14px; align-items:flex-start; }
  .thumbs img { max-height:100px; width:auto !important; max-width:none !important; min-width:0 !important; height:100px; display:block; border-radius:14px; cursor:pointer; border:1px solid transparent; flex:0 0 auto; object-fit:contain; background:#1A0F0A; }
  .thumbs img.active { border-color:rgba(201,144,12,0.7); }
  .zoom { overflow:hidden; border-radius:22px; }
  .zoom img { transition:transform 0.4s ease; }
  .zoom:hover img { transform:scale(1.05); }
  .info h1 { font-family:'Cormorant Garamond',serif; font-size:38px; font-weight:300; }
  .info .meta { margin-top:12px; font-size:12px; letter-spacing:0.2em; text-transform:uppercase; color:rgba(242,213,176,0.7); display:flex; gap:18px; flex-wrap:wrap; }
  .price { margin-top:14px; font-size:16px; color:var(--gold-light); letter-spacing:0.15em; text-transform:uppercase; }
  .chips { margin-top:18px; display:flex; gap:10px; flex-wrap:wrap; }
  .chip { border:1px solid rgba(201,144,12,0.3); padding:6px 10px; border-radius:999px; font-size:11px; letter-spacing:0.15em; text-transform:uppercase; }
  .stock-badge { padding:6px 12px; border-radius:4px; font-size:11px; letter-spacing:0.15em; text-transform:uppercase; font-weight:600; flex-basis:100%; max-width:fit-content; }
  .stock-badge.in-stock { background:#22C55E; color:#FFFFFF; }
  .stock-badge.out-of-stock { background:#DC2626; color:#FFFFFF; }
  .desc { margin-top:18px; line-height:1.7; color:rgba(242,213,176,0.7); }
  .actions { margin-top:22px; display:flex; gap:12px; flex-wrap:wrap; }
  .btn { padding:12px 18px; border-radius:999px; text-transform:uppercase; letter-spacing:0.2em; font-size:11px; border:1px solid rgba(201,144,12,0.4); }
  .btn-primary { background:var(--gold); color:#120906; border:none; }
  .related { margin-top:46px; }
  .related h2 { font-family:'Cormorant Garamond',serif; font-size:28px; font-weight:300; margin-bottom:16px; }
  .related-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:16px; }
  .related-card { border:1px solid rgba(201,144,12,0.2); background:rgba(255,255,255,0.02); padding:12px; border-radius:16px; }
  .related-card img { width:100%; border-radius:12px; aspect-ratio:3/4; object-fit:cover; }
  .toast { position:fixed; bottom:24px; right:24px; background:#1A0F0A; border:1px solid rgba(201,144,12,0.4); color:var(--cream); padding:12px 16px; border-radius:12px; display:none; }

  .modal-overlay { position:fixed; inset:0; background:rgba(10,6,4,0.75); backdrop-filter: blur(6px); display:flex; align-items:center; justify-content:center; opacity:0; pointer-events:none; transition:opacity 0.3s ease; z-index:2000; padding:24px 16px; }
  .modal-overlay.open { opacity:1; pointer-events:auto; }
  .modal { width:min(720px, 92vw); background:#120906; border:1px solid rgba(201,144,12,0.35); padding:30px; border-radius:22px; position:relative; max-height:92vh; overflow:visible; box-shadow:0 40px 100px rgba(0,0,0,0.5); transform:translateY(22px) scale(0.98); transition:transform 0.35s ease, box-shadow 0.35s ease; }
  .modal-overlay.open .modal { transform:translateY(0) scale(1); }
  .modal-scroll { max-height:min(70vh, 520px); overflow-y:auto; padding-right:6px; -webkit-overflow-scrolling: touch; }
  .modal-scroll::-webkit-scrollbar { width:6px; }
  .modal-scroll::-webkit-scrollbar-thumb { background: rgba(201,144,12,0.35); border-radius:999px; }
  .modal-close { position:absolute; top:14px; right:14px; background:none; border:1px solid rgba(201,144,12,0.4); color:var(--gold-light); width:32px; height:32px; border-radius:50%; cursor:pointer; }
  .modal-title { font-family:'Cormorant Garamond',serif; font-size:26px; font-weight:300; }
  .modal-product-name { margin-top:6px; font-size:12px; letter-spacing:0.2em; text-transform:uppercase; color:rgba(242,213,176,0.7); }
  .modal-tabs { display:flex; gap:10px; margin-top:18px; }
  .modal-tab { flex:1; padding:10px; border:1px solid rgba(201,144,12,0.3); background:transparent; color:var(--blush); text-transform:uppercase; letter-spacing:0.2em; font-size:10px; cursor:pointer; }
  .modal-tab.active { background:var(--gold); color:#120906; border-color:var(--gold); }
  .modal-form { margin-top:16px; display:flex; flex-direction:column; gap:14px; }
  .field { display:flex; flex-direction:column; gap:6px; }
  .field-label { font-size:10px; letter-spacing:0.24em; text-transform:uppercase; color:rgba(242,213,176,0.6); }
  .field-hint { font-size:11px; color:rgba(242,213,176,0.45); }
  .modal-form input, .modal-form textarea, .modal-form select { background:rgba(255,255,255,0.02); border:1px solid rgba(201,144,12,0.25); padding:12px 14px; color:var(--cream); font-family:'Josefin Sans'; font-size:12px; outline:none; border-radius:12px; transition:border-color 0.2s, box-shadow 0.2s, background 0.2s; }
  .modal-form input:hover, .modal-form textarea:hover, .modal-form select:hover { border-color: rgba(201,144,12,0.45); }
  .modal-form input:focus, .modal-form textarea:focus, .modal-form select:focus { border-color:var(--gold); box-shadow:0 0 0 2px rgba(201,144,12,0.15); background:rgba(255,255,255,0.03); }
  .select-field { position:relative; }
  .modal-form select { appearance:none; background-image: linear-gradient(45deg, transparent 50%, rgba(240,192,64,0.85) 50%), linear-gradient(135deg, rgba(240,192,64,0.85) 50%, transparent 50%); background-position: calc(100% - 18px) 50%, calc(100% - 12px) 50%; background-size:6px 6px; background-repeat:no-repeat; padding-right:34px; cursor:pointer; }
  .modal-form select option { background:#120906; color:var(--cream); }
  .modal-form textarea { min-height:90px; resize:vertical; }
  .form-row { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
  .modal-submit { margin-top:4px; background:var(--gold); color:#120906; border:none; padding:12px 16px; text-transform:uppercase; letter-spacing:0.2em; font-size:10px; border-radius:999px; cursor:pointer; }
  .modal-feedback { font-size:11px; color:var(--blush); opacity:0.8; }
  .wa-followup { font-size:11px; color:#80F2A0; }
  @media (prefers-reduced-motion: reduce) {
    .modal, .modal-overlay { transition:none; }
  }
  @media (max-width: 640px) {
    .form-row { grid-template-columns:1fr; }
  }

  @media (max-width: 900px) {
    .content { grid-template-columns:1fr; }
    .thumbs { grid-template-columns:repeat(3, minmax(140px,1fr)); }
  }
</style>
</head>
<body>
  <div class="page">
    <div class="topbar">
      <div class="brand">Syamaa</div>
      <div class="breadcrumbs">
        <a href="/">Home</a> / <a href="/products">Collection</a> / {{ display_id }}
      </div>
    </div>
    <div class="content">
      <div>
        <div class="zoom">
          <img id="mainImage" class="gallery-main" src="{{ gallery[0] }}" alt="{{ product.name }}">
        </div>
        <div class="thumbs">
          {% for img in gallery %}
          <img src="{{ img }}" alt="{{ product.name }} view" onclick="setImage('{{ img }}', this)" class="{% if loop.index0 == 0 %}active{% endif %}">
          {% endfor %}
        </div>
      </div>
      <div class="info">
        <h1>{{ product.name }}</h1>
        <div class="meta">
          <span>ID: {{ display_id }}</span>
          <span>{{ product.category }}</span>
          <span>{{ product.style }}</span>
          <div><span class="stock-badge{% if (product.stock_qty or 0) > 0 %} in-stock{% else %} out-of-stock{% endif %}">{{ 'In Stock' if (product.stock_qty or 0) > 0 else 'Out of Stock' }}</span></div></div>
        <div class="price">{{ product.price or 'Contact for Price' }}</div>
        <div class="chips">
          {% if product.fabric %}<span class="chip">{{ product.fabric }}</span>{% endif %}
          {% if product.color %}<span class="chip">{{ product.color }}</span>{% endif %}
          {% if product.tag %}<span class="chip">{{ product.tag }}</span>{% endif %}
        </div>
        {% if product.short_desc %}<div class="desc">{{ product.short_desc }}</div>{% endif %}
        <div class="desc">{{ description }}</div>
        <div class="actions">
          <button class="btn" onclick="openEnquiry('{{ product.name }}','{{ display_id }}')">Enquire or Order</button>
          <button class="btn btn-primary" onclick="openOrder('{{ product.name }}','{{ display_id }}')">Place Order</button>
          <button class="btn" onclick="addToCart('{{ product.name }}','{{ display_id }}')">Add to Cart</button>
          <a class="btn" href="/products">View All Products</a>
        </div>
      </div>
    </div>

    <div class="related">
      <h2>Related Products</h2>
      <div class="related-grid">
        {% for r in related %}
        <a class="related-card" href="/product/{{ r.product_id }}">
          <img src="{{ r.image }}" alt="{{ r.name }}" loading="lazy">
          <div class="meta" style="margin-top:8px; font-size:10px; letter-spacing:0.2em; text-transform:uppercase; color:rgba(242,213,176,0.7);">{{ r.product_id }}</div>
          <div style="margin-top:6px; font-family:'Cormorant Garamond',serif; font-size:16px;">{{ r.name }}</div>
        </a>
        {% endfor %}
      </div>
    </div>
  </div>

  <div class="modal-overlay" id="modalOverlay" onclick="handleOverlayClick(event)">
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="modalTitle">
      <button class="modal-close" onclick="closeModal()" aria-label="Close">X</button>
      <h2 class="modal-title" id="modalTitle">Enquire or <em style="color:var(--gold-light,#F0C040);font-style:italic;">Order</em></h2>
      <div class="modal-product-name" id="modalProductDisplay"></div>

      <div class="modal-tabs">
        <button class="modal-tab active" id="tabEnquiry" onclick="switchTab('enquiry')">Quick Enquiry</button>
        <button class="modal-tab" id="tabOrder" onclick="switchTab('order')">Place Order</button>
        <button class="modal-tab" id="tabCart" onclick="switchTab('cart')">Add to Cart</button>
      </div>

      <div class="modal-scroll">
        <div id="formEnquiry" class="modal-form">
          <div class="field">
            <label class="field-label" for="enq-name">Name</label>
            <input type="text" id="enq-name" placeholder="Your Name *" required>
          </div>
          <div class="field">
            <label class="field-label" for="enq-phone">WhatsApp Number</label>
            <input type="tel" id="enq-phone" placeholder="WhatsApp Number * (e.g. 9876543210)" required>
          </div>
          <div class="field">
            <label class="field-label" for="enq-email">Email</label>
            <input type="email" id="enq-email" placeholder="Email (optional)">
          </div>
          <div class="field">
            <label class="field-label" for="enq-msg">Message</label>
            <textarea id="enq-msg" placeholder="What would you like to know..."></textarea>
          </div>
          <button class="modal-submit" onclick="submitEnquiry()">Send Enquiry</button>
          <div class="modal-feedback" id="enq-feedback" role="status" aria-live="polite"></div>
          <div class="wa-followup" id="enq-wa"></div>
        </div>

        <div id="formOrder" class="modal-form" style="display:none;">
          <div class="form-row">
            <div class="field">
              <label class="field-label" for="ord-name">Name</label>
              <input type="text" id="ord-name" placeholder="Your Name *" required>
            </div>
            <div class="field">
              <label class="field-label" for="ord-phone">WhatsApp Number</label>
              <input type="tel" id="ord-phone" placeholder="WhatsApp Number *" required>
            </div>
          </div>
          <div class="field">
            <label class="field-label" for="ord-email">Email</label>
            <input type="email" id="ord-email" placeholder="Email (optional)">
          </div>
          <div class="field">
            <label class="field-label" for="ord-address">Delivery Address</label>
            <input type="text" id="ord-address" placeholder="Delivery Address">
          </div>
          <div class="form-row">
            <div class="field">
              <label class="field-label" for="ord-size">Size</label>
              <div class="select-field">
                <select id="ord-size" required>
                  <option value="">Select Size</option>
                  <option>XS (32)</option>
                  <option>S (34)</option>
                  <option>M (36)</option>
                  <option>L (38)</option>
                  <option>XL (40)</option>
                  <option>XXL (42)</option>
                  <option>Custom</option>
                </select>
              </div>
            </div>
            <div class="field">
              <label class="field-label" for="ord-fabric">Fabric</label>
              <div class="select-field">
                <select id="ord-fabric" required>
                  <option value="">Fabric Preference</option>
                  <option>Cotton</option>
                  <option>Cotton-Silk</option>
                  <option>Jaipur Cotton</option>
                  <option>Linen Blend</option>
                  <option>Silk</option>
                  <option>Custom</option>
                </select>
              </div>
            </div>
          </div>
          <div class="form-row">
            <div class="field">
              <label class="field-label" for="ord-color">Color Preference</label>
              <div class="select-field">
                <select id="ord-color">
                  <option value="">Color Preference</option>
                  <option>Rose</option>
                  <option>Ivory</option>
                  <option>Navy</option>
                  <option>Maroon</option>
                  <option>Teal</option>
                  <option>Mustard</option>
                  <option>Custom</option>
                </select>
              </div>
            </div>
            <div class="field">
              <label class="field-label" for="ord-pay">Payment Method</label>
              <div class="select-field">
                <select id="ord-pay">
                  <option value="COD">Cash on Delivery (COD)</option>
                  <option value="UPI">UPI / GPay / PhonePe</option>
                  <option value="Bank Transfer">Bank Transfer</option>
                  <option value="Card">Credit / Debit Card</option>
                </select>
              </div>
            </div>
          </div>
          <div class="field">
            <label class="field-label" for="ord-notes">Stitch Notes</label>
            <textarea id="ord-notes" placeholder="Custom notes (measurements, neck, sleeve, etc.)"></textarea>
          </div>
          <button class="modal-submit" onclick="submitOrder()">Place Order</button>
          <div class="modal-feedback" id="ord-feedback" role="status" aria-live="polite"></div>
          <div class="wa-followup" id="ord-wa"></div>
        </div>

        <div id="formCart" class="modal-form" style="display:none;">
          <div class="form-row">
            <div class="field">
              <label class="field-label" for="cart-size">Size</label>
              <div class="select-field">
                <select id="cart-size" required>
                  <option value="">Select Size</option>
                  <option>XS</option>
                  <option>S</option>
                  <option>M</option>
                  <option>L</option>
                  <option>XL</option>
                  <option>XXL</option>
                  <option>Custom</option>
                </select>
              </div>
            </div>
            <div class="field">
              <label class="field-label" for="cart-qty">Quantity</label>
              <input type="number" id="cart-qty" min="1" value="1" placeholder="Qty">
            </div>
          </div>
          <div class="form-row">
            <div class="field">
              <label class="field-label" for="cart-fabric">Fabric</label>
              <div class="select-field">
                <select id="cart-fabric" required>
                  <option value="">Fabric Preference</option>
                  <option>Cotton</option>
                  <option>Cotton-Silk</option>
                  <option>Jaipur Cotton</option>
                  <option>Linen Blend</option>
                  <option>Silk</option>
                  <option>Custom</option>
                </select>
              </div>
            </div>
            <div class="field">
              <label class="field-label" for="cart-color">Color Preference</label>
              <div class="select-field">
                <select id="cart-color">
                  <option value="">Color Preference</option>
                  <option>Rose</option>
                  <option>Ivory</option>
                  <option>Navy</option>
                  <option>Maroon</option>
                  <option>Teal</option>
                  <option>Mustard</option>
                  <option>Custom</option>
                </select>
              </div>
            </div>
          </div>
          <div class="field">
            <label class="field-label" for="cart-notes">Notes</label>
            <textarea id="cart-notes" placeholder="Custom notes or special requests..."></textarea>
          </div>
          <button class="modal-submit" onclick="submitAddToCart()">Add to Cart</button>
          <div class="modal-feedback" id="cart-feedback" role="status" aria-live="polite"></div>
        </div>
      </div>
    </div>
  </div>

  <div class="toast" id="toast"></div>
<script>
function setImage(src, el) {
  const main = document.getElementById('mainImage');
  if (main) {
    main.style.opacity = '0.4';
    setTimeout(() => {
      main.src = src;
      main.style.opacity = '1';
    }, 120);
  }
  document.querySelectorAll('.thumbs img').forEach(img => img.classList.remove('active'));
  if (el) el.classList.add('active');
}

function addToCart(name, pid) {
  openCartForProduct(name, pid);
}


function showToast(msg) {
  const el = document.getElementById('toast');
  if (!el) return;
  el.textContent = msg;
  el.style.display = 'block';
  setTimeout(() => { el.style.display = 'none'; }, 2200);
}

let currentProduct = '{{ product.name }}';
let currentProductId = '{{ display_id }}';

let profileCache = null;

async function loadProfile() {
  if (profileCache !== null) return profileCache;
  try {
    const res = await fetch('/api/auth/me');
    if (!res.ok) { profileCache = null; return null; }
    const data = await res.json();
    profileCache = data.user || null;
    return profileCache;
  } catch (e) {
    profileCache = null;
    return null;
  }
}

function fillIfEmpty(id, value) {
  if (!value) return;
  const el = document.getElementById(id);
  if (el && !el.value) el.value = value;
}

async function autofillProfile() {
  const user = await loadProfile();
  if (!user) return;
  fillIfEmpty('enq-name', user.name);
  fillIfEmpty('enq-phone', user.phone);
  fillIfEmpty('enq-email', user.email);
  fillIfEmpty('ord-name', user.name);
  fillIfEmpty('ord-phone', user.phone);
  fillIfEmpty('ord-email', user.email);
  fillIfEmpty('ord-address', user.address);
  const pay = document.getElementById('ord-pay');
  if (pay && !pay.value && user.payment_mode) pay.value = user.payment_mode;
}


function updateBodyLock() {
  const el = document.getElementById('modalOverlay');
  document.body.style.overflow = (el && el.classList.contains('open')) ? 'hidden' : '';
}

function openEnquiry(name, pid) {
  currentProduct = name || currentProduct;
  currentProductId = pid || currentProductId;
  const label = currentProduct ? '* ' + currentProduct : '';
  const display = document.getElementById('modalProductDisplay');
  if (display) display.textContent = label;
  document.getElementById('modalOverlay').classList.add('open');
  updateBodyLock();
  clearForms();
  autofillProfile();
  switchTab('enquiry');
}

function openOrder(name, pid) {
  openEnquiry(name, pid);
  switchTab('order');
}

function openCartForProduct(name, pid) {
  openEnquiry(name, pid);
  switchTab('cart');
}

function closeModal() {
  document.getElementById('modalOverlay').classList.remove('open');
  updateBodyLock();
}

function handleOverlayClick(e) {
  if (e.target === document.getElementById('modalOverlay')) closeModal();
}

function switchTab(tab) {
  document.getElementById('tabEnquiry').classList.toggle('active', tab === 'enquiry');
  document.getElementById('tabOrder').classList.toggle('active', tab === 'order');
  document.getElementById('tabCart').classList.toggle('active', tab === 'cart');
  document.getElementById('formEnquiry').style.display = tab === 'enquiry' ? 'flex' : 'none';
  document.getElementById('formOrder').style.display   = tab === 'order'   ? 'flex' : 'none';
  document.getElementById('formCart').style.display    = tab === 'cart'    ? 'flex' : 'none';
}

function clearForms() {
  ['enq-name','enq-phone','enq-email','enq-msg','ord-name','ord-phone','ord-email','ord-address','ord-size','ord-fabric','ord-color','ord-notes','cart-size','cart-fabric','cart-color','cart-notes']
    .forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  const qty = document.getElementById('cart-qty');
  if (qty) qty.value = 1;
  const pay = document.getElementById('ord-pay');
  if (pay) pay.value = 'COD';
  ['enq-feedback','ord-feedback','cart-feedback','enq-wa','ord-wa'].forEach(id => {
    const el = document.getElementById(id);
    if (el) { el.textContent = ''; el.style.display = 'none'; }
  });
}

function setFeedback(id, msg) {
  const el = document.getElementById(id);
  if (el) { el.textContent = msg; }
}

async function submitEnquiry() {
  const name  = document.getElementById('enq-name').value.trim();
  const phone = document.getElementById('enq-phone').value.trim();
  const email = document.getElementById('enq-email').value.trim();
  const message = document.getElementById('enq-msg').value.trim();
  if (!name || !phone) { setFeedback('enq-feedback', 'Name and WhatsApp number are required.'); return; }
  const btn = document.querySelector('#formEnquiry .modal-submit');
  btn.disabled = true; btn.textContent = 'Sending...';
  try {
    const res = await fetch('/api/enquiry', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name,
        phone,
        email,
        message,
        product_id: currentProductId,
        product_name: currentProduct,
        type: 'product'
      })
    });
    const data = await res.json();
    if (res.ok) {
      setFeedback('enq-feedback', data.message || 'Enquiry submitted.');
      const wa = document.getElementById('enq-wa');
      if (wa && data.whatsapp) { wa.style.display = 'block'; wa.innerHTML = `WhatsApp: <a href="${data.whatsapp}" target="_blank">Send now</a>`; }
    } else {
      setFeedback('enq-feedback', data.error || 'Unable to send enquiry.');
    }
  } catch (e) {
    setFeedback('enq-feedback', 'Network error. Please try again.');
  } finally {
    btn.disabled = false; btn.textContent = 'Send Enquiry';
  }
}

async function submitOrder() {
  const name  = document.getElementById('ord-name').value.trim();
  const phone = document.getElementById('ord-phone').value.trim();
  const size = document.getElementById('ord-size').value;
  const fabric = document.getElementById('ord-fabric').value;
  const color = document.getElementById('ord-color').value;
  const notes = document.getElementById('ord-notes').value.trim();
  if (!name || !phone) { setFeedback('ord-feedback', 'Name and WhatsApp number are required.'); return; }
  if (!size) { setFeedback('ord-feedback', 'Please select a size.'); return; }
  if (!fabric) { setFeedback('ord-feedback', 'Please select a fabric.'); return; }
  if (color === 'Custom' && !notes) { setFeedback('ord-feedback', 'Please add your custom colour in the notes.'); return; }
  const btn = document.querySelector('#formOrder .modal-submit');
  btn.disabled = true; btn.textContent = 'Placing Order...';
  const payload = {
    name,
    phone,
    email: document.getElementById('ord-email').value.trim(),
    address: document.getElementById('ord-address').value.trim(),
    product_id: currentProductId,
    product_name: currentProduct,
    size: size,
    fabric_choice: fabric,
    color_choice: color,
    payment_method: document.getElementById('ord-pay').value,
    custom_notes: notes,
    total_amount: ''
  };
  try {
    const res = await fetch('/api/order', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (res.ok) {
      setFeedback('ord-feedback', data.message || 'Order placed. We will confirm on WhatsApp.');
      const wa = document.getElementById('ord-wa');
      if (wa && data.whatsapp) { wa.style.display = 'block'; wa.innerHTML = `WhatsApp: <a href="${data.whatsapp}" target="_blank">Send now</a>`; }
    } else {
      setFeedback('ord-feedback', data.error || 'Unable to place order.');
    }
  } catch (e) {
    setFeedback('ord-feedback', 'Network error. Please try again.');
  } finally {
    btn.disabled = false; btn.textContent = 'Place Order';
  }
}

async function submitAddToCart() {
  const qtyEl = document.getElementById('cart-qty');
  const quantity = parseInt((qtyEl && qtyEl.value) || '1', 10);
  if (!quantity || quantity < 1) { setFeedback('cart-feedback', 'Please enter a valid quantity.'); return; }
  const size = document.getElementById('cart-size').value;
  const fabric = document.getElementById('cart-fabric').value;
  const color = document.getElementById('cart-color').value;
  const notesRaw = document.getElementById('cart-notes').value.trim();
  if (!size) { setFeedback('cart-feedback', 'Please select a size.'); return; }
  if (!fabric) { setFeedback('cart-feedback', 'Please select a fabric.'); return; }
  if (color === 'Custom' && !notesRaw) { setFeedback('cart-feedback', 'Please add your custom colour in the notes.'); return; }

  const notesParts = [];
  if (fabric) notesParts.push('Fabric: ' + fabric);
  if (color) notesParts.push('Color: ' + color);
  if (notesRaw) notesParts.push('Notes: ' + notesRaw);

  const payload = {
    product_name: currentProduct,
    product_id: currentProductId,
    quantity: quantity,
    size: size,
    notes: notesParts.join(' | ')
  };

  const btn = document.querySelector('#formCart .modal-submit');
  btn.disabled = true; btn.textContent = 'Adding...';
  try {
    const res = await fetch('/api/cart', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (res.status === 401) {
      window.location.href = '/';
      return;
    }
    const data = await res.json();
    if (res.ok && data.success) {
      setFeedback('cart-feedback', data.message || 'Added to cart.');
      showToast(data.message || 'Added to cart');
    } else {
      setFeedback('cart-feedback', data.error || 'Unable to add to cart.');
    }
  } catch (e) {
    setFeedback('cart-feedback', 'Network error. Please try again.');
  } finally {
    btn.disabled = false; btn.textContent = 'Add to Cart';
  }
}

</script>
</body>
</html>
"""


@app.route("/products")
def products_page():
    products, _ = build_products_from_images()
    return render_template_string(PRODUCTS_PAGE_HTML, products=products)


@app.route("/product/<code>")
def product_detail_page(code):
    pid = product_id_from_code(code)
    if not pid:
        return ("Product not found", 404)
    products, by_pid = build_products_from_images()
    product = by_pid.get(pid)
    if not product:
        return ("Product not found", 404)
    display_id = product["product_id"]
    description = product_description(product)
    related = [p for p in products if p["product_id"] != pid][:4]
    return render_template_string(
        PRODUCT_DETAIL_HTML,
        product=product,
        gallery=product.get("images", []),
        display_id=display_id,
        description=description,
        related=related,
    )


@app.route("/media/<path:filename>")
def serve_media(filename):
    return send_from_directory(str(BASE_DIR / "instance" / "images"), filename)


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
<link href="https://fonts.googleapis.com/css2...family=Cormorant+Garamond:ital,wght@0,300;0,400;1,400&family=Josefin+Sans:wght@300;400&display=swap" rel="stylesheet">
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
<link href="https://fonts.googleapis.com/css2...family=Cormorant+Garamond:ital,wght@0,300;0,400;1,400&family=Josefin+Sans:wght@300;400&display=swap" rel="stylesheet">
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
  .product-admin{display:flex;flex-direction:column;gap:18px;}
  .product-form{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:18px;}
  .form-card{background:rgba(255,255,255,0.02);border:1px solid rgba(201,144,12,0.15);padding:18px;border-radius:16px;}
  .form-card.preview{background:rgba(18,10,5,0.9);}  
  .form-title{font-size:10px;letter-spacing:0.3em;text-transform:uppercase;color:var(--gold);margin-bottom:12px;}
  .form-card label{font-size:9px;letter-spacing:0.25em;text-transform:uppercase;color:var(--blush);opacity:0.8;margin-top:12px;display:block;}
  .form-card input,.form-card textarea,.form-card select{width:100%;margin-top:6px;background:transparent;border:1px solid rgba(201,144,12,0.2);padding:10px 12px;border-radius:10px;color:var(--cream);font-family:'Josefin Sans',sans-serif;font-size:12px;}
  .form-card input:focus,.form-card textarea:focus,.form-card select:focus{outline:none;border-color:var(--gold);}
  .form-card textarea{resize:vertical;min-height:90px;}
  .form-card .hint{font-size:10px;color:rgba(242,213,176,0.5);display:block;margin-top:6px;}
  .toggle-row{display:flex;align-items:center;gap:10px;font-size:11px;color:var(--blush);opacity:0.75;margin:8px 0 4px;}
  .action-btn.primary{background:var(--gold);color:var(--dark);border-color:var(--gold);width:100%;padding:10px 14px;border-radius:999px;margin-top:12px;}
  .section-actions{font-size:10px;color:rgba(242,213,176,0.6);}
  .preview-card{border:1px solid rgba(201,144,12,0.25);border-radius:16px;overflow:hidden;}
  .preview-image{height:180px;background:linear-gradient(120deg,rgba(201,144,12,0.2),rgba(61,31,15,0.4));background-size:cover;background-position:center;}
  .preview-meta{display:flex;justify-content:space-between;font-size:9px;letter-spacing:0.2em;text-transform:uppercase;color:rgba(242,213,176,0.7);padding:12px 14px 0;}
  .preview-name{padding:8px 14px 0;font-family:'Cormorant Garamond',serif;font-size:20px;font-weight:300;}
  .preview-price{padding:6px 14px 14px;color:var(--gold-light);font-size:12px;letter-spacing:0.18em;text-transform:uppercase;}
  .preview-status{padding:0 14px 14px;font-size:9px;letter-spacing:0.2em;text-transform:uppercase;color:rgba(240,192,64,0.8);}  
  .image-strip{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;}
  .image-strip img{width:60px;height:80px;object-fit:cover;border-radius:10px;border:1px solid rgba(201,144,12,0.2);}  
  .image-strip .empty{font-size:10px;color:rgba(242,213,176,0.5);border:1px dashed rgba(201,144,12,0.2);padding:10px;border-radius:10px;}
    .image-meta{font-size:9px;letter-spacing:0.2em;text-transform:uppercase;color:rgba(242,213,176,0.6);margin-top:8px;}
  .image-meta .ok{color:#80F2A0;}
  .image-meta .warn{color:#F2A080;}
.status-active{color:#80F2A0;border-color:rgba(128,242,160,0.3);}
  .status-draft{color:#F0C040;border-color:rgba(240,192,64,0.3);}  
  .status-hidden{color:rgba(242,213,176,0.5);border-color:rgba(242,213,176,0.2);}  
  @media (max-width: 900px){.grid2{grid-template-columns:1fr;}.topbar{padding:18px 20px;}.content{padding:24px 20px;}}

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
    <a class="nav-item" href="#" onclick="loadSection('users')"><span class="icon">👤</span> Users</a>
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
        <span class="stat-label">Registered Users</span>
        <div class="stat-value">{{ stats.registered_users }}</div>
        <div class="stat-sub">Accounts created</div>
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
              <a href="https://wa.me/91{{ e.phone }}?text={{ ('Hi ' ~ e.name ~ '! Thank you for your enquiry about ' ~ (e.product_name or 'our collection') ~ '.') | urlencode }}" target="_blank">
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
    setTimeout(() => updateProductPreview(), 0);
  } else if (section === 'newsletter') {
    title.textContent = 'Newsletter Subscribers';
    const res = await fetch('/admin/api/newsletter');
    const data = await res.json();
    main.innerHTML = renderNewsletter(data.subscribers);
  } else if (section === 'users') {
    title.textContent = 'Registered Users';
    const res = await fetch('/admin/api/users');
    const data = await res.json();
    main.innerHTML = renderUsers(data.users);
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
  productCache = rows || [];
  let html = `
  <div class="product-admin">
    <div class="section-header" style="margin-bottom:16px;">
      <div class="section-title" id="productFormTitle">Add Product</div>
      <div class="section-actions">Admin catalog is the single source of truth.</div>
    </div>

    <div class="product-form">
      <div class="form-card">
        <div class="form-title">General</div>
        <label>Product ID</label>
        <input id="prod-id" placeholder="SYA0001" oninput="updateProductPreview()">
        <small class="hint">Images should be stored in /instance/images/SYA0001/. Product ID is immutable after save.</small>
        <label>Product Name</label>
        <input id="prod-name" placeholder="Product name" oninput="updateProductPreview()">
        <label>Short Description</label>
        <input id="prod-short" placeholder="Short description" oninput="updateProductPreview()">
        <label>Full Description</label>
        <textarea id="prod-desc" rows="4" placeholder="Detailed description" oninput="updateProductPreview()"></textarea>
        <label>Category</label>
        <input id="prod-category" placeholder="Kurta, Kurti Set, Saree" oninput="updateProductPreview()">
        <label>Tags / Collections</label>
        <input id="prod-tags" placeholder="Festive, Signature, Summer" oninput="updateProductPreview()">
      </div>

      <div class="form-card">
        <div class="form-title">Pricing & Stock</div>
        <label>Price</label>
        <input id="prod-price" type="number" min="0" step="1" placeholder="1499" oninput="updateProductPreview()">
        <label>Stock Quantity</label>
        <input id="prod-stock" type="number" min="0" value="0" oninput="updateProductPreview()">
        <label>Status</label>
        <select id="prod-status" onchange="updateProductPreview()">
          <option value="active">Active</option>
          <option value="draft">Draft</option>
          <option value="hidden">Hidden</option>
        </select>
        <label>Style (Optional)</label>
        <input id="prod-style" placeholder="Straight, Angrakha" oninput="updateProductPreview()">
        <label>Fabric (Optional)</label>
        <input id="prod-fabric" placeholder="Cotton, Silk" oninput="updateProductPreview()">
        <label>Color (Optional)</label>
        <input id="prod-color" placeholder="Rose, Ivory" oninput="updateProductPreview()">
      </div>

      <div class="form-card">
        <div class="form-title">Images</div>
        <div class="image-strip" id="imageStrip">
          <span class="empty">Add poster.jpg and gallery images inside /instance/images/{ID}/</span>
        </div>
        <div class="image-meta" id="imageMeta">Waiting for a valid Product ID.</div>
        <button class="action-btn" style="margin-top:10px;" onclick="rescanImages()">Rescan images</button>
        <small class="hint">Poster image will be used on the home featured collection.</small>
      </div>

      <div class="form-card">
        <div class="form-title">Display</div>
        <label>Featured</label>
        <div class="toggle-row">
          <input id="prod-featured" type="checkbox" onchange="updateProductPreview()">
          <span>Show in Featured Collection</span>
        </div>
        <label>Display Order</label>
        <input id="prod-order" type="number" value="0" oninput="updateProductPreview()">
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <button class="action-btn primary" id="productSaveBtn" onclick="submitProductForm()">Save Product</button>
          <button class="action-btn" id="productCancelBtn" style="display:none;" onclick="resetProductForm()">Cancel Edit</button>
        </div>
      </div>

      <div class="form-card preview">
        <div class="form-title">Live Preview</div>
        <div class="preview-card" id="productPreview">
          <div class="preview-image" id="previewImage"></div>
          <div class="preview-meta">
            <span id="previewId">SYA0001</span>
            <span id="previewCategory">Category</span>
          </div>
          <div class="preview-name" id="previewName">Product Name</div>
          <div class="preview-price" id="previewPrice">Contact for Price</div>
          <div class="preview-status" id="previewStatus">Active</div>
        </div>
      </div>
    </div>

    <div class="section-header" style="margin-top:28px;">
      <div class="section-title">Products</div>
      <div class="section-actions">Only Active products appear on the storefront.</div>
    </div>

    <table><thead><tr><th>#</th><th>Product ID</th><th>Name</th><th>Status</th><th>Stock</th><th>Featured</th><th>Images</th><th>Price</th><th>Category</th><th>Actions</th></tr></thead><tbody>`;

  rows.forEach(p => {
    const featuredBadge = p.featured ? '<span class=\"status-badge status-confirmed\">Yes</span>' : '<span class=\"status-badge status-closed\">No</span>';
    const status = p.status || 'active';
    const imageCount = Number(p.image_count || 0);
    const hasPoster = !!p.has_poster;
    const posterBadge = hasPoster ? '<span class=\"status-badge status-confirmed\">poster</span>' : '<span class=\"status-badge status-pending\">no poster</span>';
    html += `<tr>
      <td>${p.id}</td>
      <td>${p.product_id || '?'}</td>
      <td>${p.name}</td>
      <td>${statusBadge(status)}</td>
      <td>${p.stock_qty||0}</td>
      <td>${featuredBadge}</td>
      <td>${imageCount} ${imageCount === 1 ? 'img' : 'imgs'}<div style="margin-top:6px;">${posterBadge}</div></td>
      <td>${p.price||'Contact for Price'}</td>
      <td>${p.category}</td>
      <td style="display:flex;gap:6px;flex-wrap:wrap;">
        <button class="action-btn" onclick="editProductById(${p.id})">Edit</button>
        <button class="action-btn" onclick="deleteProduct(${p.id}, false)">Archive</button>
        <button class="action-btn" style="color:#E37070;border-color:rgba(227,112,112,0.4);" onclick="deleteProduct(${p.id}, true)">Delete</button>
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

function renderUsers(rows) {
  let html = `<div style="margin-bottom:12px;font-size:11px;color:var(--gold);">${rows.length} registered users</div>
  <table><thead><tr><th>#</th><th>Name</th><th>Email</th><th>Phone</th><th>Address</th><th>Status</th><th>Joined</th></tr></thead><tbody>`;
  rows.forEach(u => {
    html += `<tr>
      <td>${u.id}</td>
      <td>${u.name}</td>
      <td>${u.email}</td>
      <td>${u.phone||'—'}</td>
      <td>${u.address ? u.address.slice(0,40) : '—'}</td>
      <td>${u.is_active ? '<span class=\"status-badge status-contacted\">active</span>' : '<span class=\"status-badge status-closed\">inactive</span>'}</td>
      <td>${u.created_at.slice(0,10)}</td>
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

async function deleteProduct(id, permanent) {
  if (permanent) {
    if (!confirm('Delete this product permanently? This cannot be undone.')) return;
  } else {
    if (!confirm('Archive this product (hide from storefront)?')) return;
  }
  const url = permanent ? `/admin/api/products/${id}?hard=1` : `/admin/api/products/${id}`;
  const res = await fetch(url, {method:'DELETE'});
  if (res.ok) {
    showToast(permanent ? 'Product deleted' : 'Product archived');
    loadSection('products');
  } else {
    showToast('Failed', 'error');
  }
}

let previewImageCache = {};

async function fetchProductImages(pid) {
  if (!pid) return [];
  const normalized = pid.toUpperCase();
  if (previewImageCache[normalized]) {
    return previewImageCache[normalized];
  }
  try {
    const res = await fetch(`/admin/api/product-images/${normalized}`);
    if (!res.ok) return [];
    const data = await res.json();
    previewImageCache[normalized] = data.images || [];
    return previewImageCache[normalized];
  } catch (err) {
    return [];
  }
}

function renderImageStrip(images) {
  const strip = document.getElementById('imageStrip');
  const meta = document.getElementById('imageMeta');
  if (!strip) return;
  if (!images || !images.length) {
    strip.innerHTML = '<span class="empty">No images found yet. Add poster.jpg and gallery images.</span>';
    if (meta) meta.innerHTML = '<span class="warn">No images found</span> for this Product ID.';
    return;
  }
  const hasPoster = images.some(img => (img.split('/').pop() || '').toLowerCase().startsWith('poster'));
  if (meta) {
    const countLabel = `${images.length} ${images.length === 1 ? 'image' : 'images'}`;
    meta.innerHTML = `<span class="${hasPoster ? 'ok' : 'warn'}">${countLabel}</span> - ${hasPoster ? 'Poster detected' : 'Poster missing'}`;
  }
  strip.innerHTML = images.map(img => `<img src="${img}" loading="lazy" alt="Product image">`).join('');
}


async function rescanImages() {
  const pid = (document.getElementById('prod-id').value || '').trim().toUpperCase();
  if (!/^SYA\\d{4}$/.test(pid)) {
    showToast('Enter a valid Product ID first', 'error');
    return;
  }
  delete previewImageCache[pid];
  updateProductPreview();
  showToast('Image scan refreshed');
}

async function updateProductPreview() {
  const idEl = document.getElementById('prod-id');
  if (!idEl) return;
  const pid = (idEl.value || 'SYA0001').trim().toUpperCase();
  const name = (document.getElementById('prod-name')?.value || 'Product Name').trim();
  const category = (document.getElementById('prod-category')?.value || 'Category').trim();
  const priceRaw = (document.getElementById('prod-price')?.value || '').trim();
  const status = (document.getElementById('prod-status')?.value || 'active').trim();

  document.getElementById('previewId').textContent = pid || 'SYA0001';
  document.getElementById('previewCategory').textContent = category || 'Category';
  document.getElementById('previewName').textContent = name || 'Product Name';
  const priceText = priceRaw ? (isNaN(Number(priceRaw)) ? priceRaw : `INR ${priceRaw}`) : 'Contact for Price';
  document.getElementById('previewPrice').textContent = priceText;
  document.getElementById('previewStatus').textContent = status;

  const previewImage = document.getElementById('previewImage');
  if (!/^SYA\\d{4}$/.test(pid)) {
    previewImage.style.backgroundImage = 'linear-gradient(120deg,rgba(201,144,12,0.2),rgba(61,31,15,0.4))';
    renderImageStrip([]);
    return;
  }

  const images = await fetchProductImages(pid);
  if (images.length) {
    previewImage.style.backgroundImage = `url('${images[0]}')`;
  } else {
    previewImage.style.backgroundImage = 'linear-gradient(120deg,rgba(201,144,12,0.2),rgba(61,31,15,0.4))';
  }
  renderImageStrip(images);
}

let editingProductId = null;
let productCache = [];

function resetProductForm() {
  editingProductId = null;
  document.getElementById('prod-id').disabled = false;
  document.getElementById('prod-id').value = '';
  document.getElementById('prod-name').value = '';
  document.getElementById('prod-short').value = '';
  document.getElementById('prod-desc').value = '';
  document.getElementById('prod-category').value = '';
  document.getElementById('prod-tags').value = '';
  document.getElementById('prod-price').value = '';
  document.getElementById('prod-stock').value = 0;
  document.getElementById('prod-status').value = 'active';
  document.getElementById('prod-style').value = '';
  document.getElementById('prod-fabric').value = '';
  document.getElementById('prod-color').value = '';
  document.getElementById('prod-featured').checked = false;
  document.getElementById('prod-order').value = 0;
  const title = document.getElementById('productFormTitle');
  if (title) title.textContent = 'Add Product';
  const saveBtn = document.getElementById('productSaveBtn');
  if (saveBtn) saveBtn.textContent = 'Save Product';
  const cancelBtn = document.getElementById('productCancelBtn');
  if (cancelBtn) cancelBtn.style.display = 'none';
  updateProductPreview();
}

function editProductById(id) {
  const p = (productCache || []).find(x => Number(x.id) === Number(id));
  if (!p) {
    showToast('Product not found', 'error');
    return;
  }
  const pid = (p.product_id || ('SYA' + String(p.id).padStart(4, '0'))).toUpperCase();
  editingProductId = p.id;
  document.getElementById('prod-id').value = pid;
  document.getElementById('prod-id').disabled = true;
  document.getElementById('prod-name').value = p.name || '';
  document.getElementById('prod-short').value = p.short_desc || '';
  document.getElementById('prod-desc').value = p.description || '';
  document.getElementById('prod-category').value = p.category || '';
  document.getElementById('prod-tags').value = p.tags || '';
  document.getElementById('prod-price').value = p.price || '';
  document.getElementById('prod-stock').value = p.stock_qty || 0;
  document.getElementById('prod-status').value = p.status || 'active';
  document.getElementById('prod-style').value = p.style || '';
  document.getElementById('prod-fabric').value = p.fabric || '';
  document.getElementById('prod-color').value = p.color || '';
  document.getElementById('prod-featured').checked = !!p.featured;
  document.getElementById('prod-order').value = p.display_order || 0;
  const title = document.getElementById('productFormTitle');
  if (title) title.textContent = 'Edit Product';
  const saveBtn = document.getElementById('productSaveBtn');
  if (saveBtn) saveBtn.textContent = 'Update Product';
  const cancelBtn = document.getElementById('productCancelBtn');
  if (cancelBtn) cancelBtn.style.display = 'inline-flex';
  updateProductPreview();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

async function submitProductForm() {
  const product_id = (document.getElementById('prod-id').value || '').trim().toUpperCase();
  const name = (document.getElementById('prod-name').value || '').trim();
  const category = (document.getElementById('prod-category').value || '').trim();
  if (!/^SYA\d{4}$/.test(product_id)) {
    showToast('Product ID must be like SYA0001', 'error');
    return;
  }
  if (!name || !category) {
    showToast('Name and category are required', 'error');
    return;
  }

  const payload = {
    product_id,
    name,
    category,
    short_desc: (document.getElementById('prod-short').value || '').trim(),
    description: (document.getElementById('prod-desc').value || '').trim(),
    tags: (document.getElementById('prod-tags').value || '').trim(),
    price: (document.getElementById('prod-price').value || '').trim(),
    stock_qty: document.getElementById('prod-stock').value,
    status: document.getElementById('prod-status').value,
    style: (document.getElementById('prod-style').value || '').trim(),
    fabric: (document.getElementById('prod-fabric').value || '').trim(),
    color: (document.getElementById('prod-color').value || '').trim(),
    featured: document.getElementById('prod-featured').checked,
    display_order: document.getElementById('prod-order').value,
  };

  const url = editingProductId ? `/admin/api/products/${editingProductId}` : '/admin/api/products';
  const method = editingProductId ? 'PUT' : 'POST';
  const res = await fetch(url, {
    method,
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify(payload)
  });
  const data = await res.json();
  if (res.ok && data.success) {
    showToast(editingProductId ? 'Product updated!' : 'Product added!');
    resetProductForm();
    loadSection('products');
  } else {
    showToast(data.error || 'Failed to save product', 'error');
  }
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
