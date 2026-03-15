#!/bin/bash
# ─────────────────────────────────────────────
#  Syamaa Backend — Startup Script
# ─────────────────────────────────────────────

set -e

echo ""
echo "  ✦ Syamaa — Exquisite Indian Couture ✦"
echo "  ────────────────────────────────────────"

# Get the directory this script lives in (works regardless of where you run it from)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "  → Working directory: $SCRIPT_DIR"

# Create required directories
mkdir -p "$SCRIPT_DIR/instance"
mkdir -p "$SCRIPT_DIR/static"

echo "  → instance/ folder: OK"

# Optional: set admin credentials via env
# export ADMIN_EMAIL="your@email.com"
# export ADMIN_PASSWORD="YourSecurePassword"

# Install Flask if not present
if ! python3 -c "import flask" 2>/dev/null; then
  echo "  → Installing Flask…"
  pip3 install flask
fi

echo "  → Starting server on http://0.0.0.0:5000"
echo "  → Admin panel:       http://localhost:5000/admin/login"
echo "  → Default login:     admin@syamaa.com / Syamaa@2025"
echo ""

python3 app.py