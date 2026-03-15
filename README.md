# Syamaa — Backend Server
**Exquisite Indian Couture · Full-Stack Web Application**

---

## Tech Stack
| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12 + Flask 3.x |
| Database | SQLite3 (zero-config, file-based) |
| Auth | Session-based (Flask sessions + SHA-256) |
| Frontend | Embedded HTML/CSS/JS (served as static file) |
| Dependencies | **Flask only** — zero other packages |

---

## Quick Start

```bash
# 1. Install Flask
pip3 install flask

# 2. Run
python3 app.py
```

That's it. The database is auto-created on first run.

**URLs:**
| URL | Description |
|-----|-------------|
| `http://localhost:5000/` | Syamaa Website (frontend) |
| `http://localhost:5000/admin/login` | Admin login |
| `http://localhost:5000/admin/dashboard` | Admin dashboard |
| `http://localhost:5000/health` | Health check |

**Default Admin Credentials:**
```
Email:    admin@syamaa.com
Password: Syamaa@2025
```
Change via environment variables (see below).

---

## Project Structure

```
syamaa-backend/
├── app.py                  ← Main Flask app (all routes + DB logic)
├── requirements.txt        ← Flask only
├── run.sh                  ← Startup script
├── Dockerfile              ← Docker deployment
├── README.md               ← This file
├── instance/
│   └── syamaa.db           ← SQLite database (auto-created)
└── static/
    └── index.html          ← Syamaa frontend (self-contained)
```

---

## Database Schema

### `products`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| name | TEXT | Product name |
| category | TEXT | Angrakha, Kurti Set, etc. |
| style | TEXT | Sub-style |
| fabric | TEXT | Cotton, Cotton-Silk, etc. |
| color | TEXT | Colour name |
| features | TEXT | Pipe-separated feature list |
| price | TEXT | Price or "Contact for Price" |
| image_url | TEXT | Image path |
| tag | TEXT | Best Seller, New, Custom, etc. |
| is_active | INTEGER | 1 = active, 0 = archived |

### `enquiries`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| name | TEXT | Customer name |
| phone | TEXT | WhatsApp number |
| email | TEXT | Optional email |
| message | TEXT | Enquiry message |
| product_name | TEXT | Product they asked about |
| type | TEXT | general / product / custom |
| status | TEXT | new / contacted / closed |

### `orders`
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER PK | Auto-increment |
| name | TEXT | Customer name |
| phone | TEXT | WhatsApp number |
| product_name | TEXT | Ordered product |
| size | TEXT | Size / measurements |
| fabric_choice | TEXT | Chosen fabric |
| color_choice | TEXT | Chosen colour |
| custom_notes | TEXT | Special instructions |
| payment_method | TEXT | COD / UPI / Card |
| status | TEXT | pending → confirmed → stitching → ready → shipped → delivered |

### `newsletter`
| Column | Type | Description |
|--------|------|-------------|
| email | TEXT UNIQUE | Subscriber email |
| name | TEXT | Optional name |
| whatsapp | TEXT | Optional WhatsApp |

---

## REST API Reference

### Products

```
GET  /api/products              → List all active products
GET  /api/products?category=X   → Filter by category
GET  /api/products/:id          → Single product
GET  /api/products/categories   → Category list with counts
```

**Response example:**
```json
{
  "products": [
    {
      "id": 1,
      "name": "Vintage Rose Angrakha Style Kurta",
      "category": "Angrakha",
      "fabric": "Cotton-Silk",
      "color": "Light Pink",
      "features": ["V-neck with multi-colored patterned piping", "Elegant angrakha overlap"],
      "price": "Contact for Price",
      "tag": "Best Seller"
    }
  ],
  "count": 4
}
```

### Enquiries

```
POST /api/enquiry
```
**Body:**
```json
{
  "name": "Priya Sharma",
  "phone": "9876543210",
  "email": "priya@example.com",
  "message": "Interested in the Angrakha kurta",
  "product_name": "Vintage Rose Angrakha",
  "type": "product"
}
```
**Response:**
```json
{
  "success": true,
  "message": "Thank you! We'll contact you on WhatsApp soon.",
  "wa_link": "https://wa.me/916282201008?text=..."
}
```

### Orders

```
POST /api/order
```
**Body:**
```json
{
  "name": "Meera Iyer",
  "phone": "9876543210",
  "product_name": "Vintage Rose Angrakha",
  "size": "M (36)",
  "fabric_choice": "Cotton-Silk",
  "color_choice": "Light Pink",
  "custom_notes": "Please add extra length",
  "payment_method": "COD"
}
```

### Newsletter

```
POST /api/newsletter
```
**Body:**
```json
{
  "name": "Anjali",
  "email": "anjali@example.com",
  "whatsapp": "9876543210"
}
```

---

## Admin Panel

Login at `/admin/login` with your credentials.

### Dashboard Features
- 📊 **Stats cards** — Products, Enquiries (with new count), Orders (with pending count), Subscribers
- 💬 **Enquiries table** — Update status (new → contacted → closed), direct WhatsApp link
- 📦 **Orders table** — Progress orders through workflow, direct WhatsApp link
- 👗 **Products** — View, add, archive products
- ✉️ **Newsletter** — View all subscribers

### Admin API (requires session)

```
GET   /admin/api/enquiries          → List enquiries (paginated)
PATCH /admin/api/enquiries/:id      → Update status
GET   /admin/api/orders             → List orders (paginated)
PATCH /admin/api/orders/:id         → Update status
GET   /admin/api/products           → All products (including archived)
POST  /admin/api/products           → Add product
PUT   /admin/api/products/:id       → Update product
DELETE /admin/api/products/:id      → Archive product
GET   /admin/api/newsletter         → All subscribers
GET   /admin/api/stats              → Chart data (daily enquiries, order statuses, top products)
```

---

## Environment Variables

```bash
ADMIN_EMAIL=admin@syamaa.com     # Admin login email
ADMIN_PASSWORD=Syamaa@2025       # Admin login password (change this!)
```

---

## Docker Deployment

```bash
docker build -t syamaa .
docker run -p 5000:5000 \
  -e ADMIN_EMAIL=your@email.com \
  -e ADMIN_PASSWORD=YourSecurePassword \
  -v $(pwd)/instance:/app/instance \
  syamaa
```

---

## Production Checklist

- [ ] Change `ADMIN_PASSWORD` via environment variable
- [ ] Set `app.secret_key` to a fixed value (not random) so sessions survive restarts
- [ ] Use `gunicorn` instead of Flask dev server: `gunicorn -w 4 app:app`
- [ ] Put Nginx in front for SSL termination
- [ ] Back up `instance/syamaa.db` regularly
- [ ] Set `SESSION_COOKIE_SECURE=True` when on HTTPS

---

*Syamaa — Exquisite Indian Couture · 6282 201 008*
