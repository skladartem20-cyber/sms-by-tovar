# Уцененные товары — складской сервис
# Backend: Flask + SQLite
import os
import io
import csv
import json
import shutil
import sqlite3
import zipfile
import secrets
import datetime as dt
from functools import wraps
from pathlib import Path

from flask import (
    Flask, request, jsonify, render_template,
    session, send_file, send_from_directory, abort, g
)
from werkzeug.utils import secure_filename
from werkzeug.middleware.proxy_fix import ProxyFix
from PIL import Image, ImageOps

# ----------------------------- Configuration ---------------------------------

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR / "data"))
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", BASE_DIR / "static" / "uploads"))
DB_PATH = DATA_DIR / "store.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXT = {"png", "jpg", "jpeg", "webp", "gif", "bmp"}
MAX_PHOTOS_PER_PRODUCT = 5
MAX_PHOTO_SIZE_MB = 12
THUMB_SIZE = (640, 640)

DEFAULT_PASSWORD = os.environ.get("ADMIN_PASSWORD", "010203")

def _load_or_create_secret_key() -> str:
    """SECRET_KEY должен быть общим для всех воркеров Gunicorn и переживать
    перезапуски, иначе сессия разлогинивается между запросами."""
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key
    key_file = DATA_DIR / ".secret_key"
    if key_file.exists():
        try:
            val = key_file.read_text().strip()
            if val:
                return val
        except OSError:
            pass
    new_key = secrets.token_hex(32)
    try:
        key_file.write_text(new_key)
        os.chmod(key_file, 0o600)
    except OSError:
        pass
    return new_key


app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["MAX_CONTENT_LENGTH"] = MAX_PHOTO_SIZE_MB * 1024 * 1024 * MAX_PHOTOS_PER_PRODUCT
app.config["SECRET_KEY"] = _load_or_create_secret_key()
app.config["JSON_AS_ASCII"] = False
# Сессия живёт 30 дней; SameSite=Lax корректно работает за reverse-proxy Timeweb
app.config["PERMANENT_SESSION_LIFETIME"] = dt.timedelta(days=30)
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_HTTPONLY"] = True

# Корректные scheme/host за reverse-proxy (Timeweb Cloud, nginx и т.п.)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# ----------------------------- Database --------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    price REAL NOT NULL DEFAULT 0,
    defect TEXT DEFAULT '',
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    weight REAL,
    length REAL,
    width REAL,
    height REAL,
    highlighted INTEGER DEFAULT 0,
    highlight_label TEXT DEFAULT '',
    highlight_color TEXT DEFAULT 'green',
    pinned INTEGER DEFAULT 0,
    status TEXT DEFAULT 'available',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    is_main INTEGER DEFAULT 0,
    sort_order INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS visitors (
    day TEXT PRIMARY KEY,
    count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS visitor_total (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    count INTEGER DEFAULT 0
);

INSERT OR IGNORE INTO visitor_total (id, count) VALUES (1, 0);
"""

DEFAULT_SETTINGS = {
    "phone": "+7 999 616-49-94",
    "messenger_link": "https://max.ru/u/f9LHodD0cOJEhQbb3wl2z11H_2DB84UCabgu1irqTeeee3BdT8Yo-cinETM",
    "messenger_name": "Max",
    "how_to_order_text": (
        "Чтобы оформить заказ, добавьте нужные товары в корзину, "
        "затем нажмите «Оформить заказ» — текст заказа автоматически скопируется "
        "в буфер обмена, а вы будете перенаправлены в мессенджер для отправки."
    ),
    "shop_title": "Уцененные товары",
    "shop_subtitle": "Склад уценки — выгодные предложения",
    "admin_password": DEFAULT_PASSWORD,
    "currency": "₽",
    # Ссылка, куда перенаправлять при оформлении заказа из корзины
    "order_link": "https://max.ru/u/f9LHodD0cOJEhQbb3wl2z11H_2DB84UCabgu1irqTeeee3BdT8Yo-cinETM",
    # Шаблон сообщения; плейсхолдеры: {items}, {total}, {count}
    "order_greeting": "Здравствуйте! Я хочу сделать заказ:",
    "order_footer": "Подскажите, пожалуйста, по наличию и доставке. Спасибо!",
}


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(_):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    for k, v in DEFAULT_SETTINGS.items():
        conn.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v)
        )
    conn.commit()
    conn.close()


# ----------------------------- Helpers ---------------------------------------

def is_admin() -> bool:
    return bool(session.get("is_admin"))


def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not is_admin():
            return jsonify({"error": "Доступ запрещён"}), 401
        return fn(*args, **kwargs)
    return wrapper


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def get_setting(key: str, default: str = "") -> str:
    db = get_db()
    row = db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str):
    db = get_db()
    db.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    db.commit()


def settings_dict() -> dict:
    db = get_db()
    return {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM settings")}


def product_to_dict(row: sqlite3.Row, photos: list) -> dict:
    return {
        "id": row["id"],
        "number": row["number"],
        "name": row["name"],
        "description": row["description"] or "",
        "price": row["price"],
        "defect": row["defect"] or "",
        "category_id": row["category_id"],
        "category_name": row["category_name"] if "category_name" in row.keys() else None,
        "weight": row["weight"],
        "length": row["length"],
        "width": row["width"],
        "height": row["height"],
        "highlighted": bool(row["highlighted"]),
        "highlight_label": row["highlight_label"] or "",
        "highlight_color": row["highlight_color"] or "green",
        "pinned": bool(row["pinned"]),
        "status": row["status"] or "available",
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "photos": photos,
    }


def fetch_photos(product_id: int) -> list:
    db = get_db()
    rows = db.execute(
        "SELECT id, filename, is_main, sort_order FROM photos "
        "WHERE product_id = ? ORDER BY is_main DESC, sort_order ASC, id ASC",
        (product_id,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "filename": r["filename"],
            "url": f"/static/uploads/{r['filename']}",
            "is_main": bool(r["is_main"]),
            "sort_order": r["sort_order"],
        }
        for r in rows
    ]


def save_photo(file_storage, product_id: int) -> str:
    """Сохраняет фото с оптимизацией. Возвращает имя файла."""
    if not allowed_file(file_storage.filename):
        raise ValueError("Недопустимый формат файла")
    ext = file_storage.filename.rsplit(".", 1)[1].lower()
    if ext in ("jpg", "jpeg"):
        ext = "jpg"
    unique = secrets.token_hex(8)
    filename = f"p{product_id}_{unique}.{ext}"
    full_path = UPLOAD_DIR / filename

    # Optimize / resize
    try:
        img = Image.open(file_storage.stream)
        img = ImageOps.exif_transpose(img)
        if img.mode in ("RGBA", "P") and ext == "jpg":
            img = img.convert("RGB")
        # Resize if too large (preserve aspect)
        max_side = 1800
        if max(img.size) > max_side:
            img.thumbnail((max_side, max_side), Image.LANCZOS)
        save_kwargs = {}
        if ext in ("jpg", "jpeg"):
            save_kwargs = {"quality": 85, "optimize": True}
            img.save(full_path, "JPEG", **save_kwargs)
        elif ext == "png":
            img.save(full_path, "PNG", optimize=True)
        elif ext == "webp":
            img.save(full_path, "WEBP", quality=85)
        else:
            img.save(full_path)
    except Exception:
        # fallback raw save
        file_storage.stream.seek(0)
        with open(full_path, "wb") as f:
            f.write(file_storage.stream.read())
    return filename


def count_visit():
    today = dt.date.today().isoformat()
    db = get_db()
    # Increment only once per session per day
    last_visit = session.get("last_visit_day")
    if last_visit != today:
        db.execute(
            "INSERT INTO visitors (day, count) VALUES (?, 1) "
            "ON CONFLICT(day) DO UPDATE SET count = count + 1",
            (today,),
        )
        db.execute("UPDATE visitor_total SET count = count + 1 WHERE id = 1")
        db.commit()
        session["last_visit_day"] = today


# ----------------------------- Routes: pages ---------------------------------

@app.route("/")
def index():
    count_visit()
    return render_template("index.html")


@app.route("/static/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


# ----------------------------- API: auth -------------------------------------

@app.post("/api/login")
def api_login():
    data = request.get_json(force=True, silent=True) or {}
    password = data.get("password", "")
    if password == get_setting("admin_password", DEFAULT_PASSWORD):
        session["is_admin"] = True
        session.permanent = True
        return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "Неверный пароль"}), 401


@app.post("/api/logout")
def api_logout():
    session.pop("is_admin", None)
    return jsonify({"ok": True})


@app.get("/api/me")
def api_me():
    return jsonify({"is_admin": is_admin()})


# ----------------------------- API: settings ---------------------------------

@app.get("/api/settings")
def api_get_settings():
    s = settings_dict()
    # Скрываем пароль для не-админов
    if not is_admin():
        s.pop("admin_password", None)
    return jsonify(s)


@app.post("/api/settings")
@admin_required
def api_update_settings():
    data = request.get_json(force=True, silent=True) or {}
    allowed_keys = set(DEFAULT_SETTINGS.keys())
    for k, v in data.items():
        if k in allowed_keys and v is not None:
            set_setting(k, str(v))
    return jsonify({"ok": True, "settings": settings_dict()})


# ----------------------------- API: categories -------------------------------

@app.get("/api/categories")
def api_categories():
    db = get_db()
    rows = db.execute(
        "SELECT c.id, c.name, c.sort_order, "
        "(SELECT COUNT(*) FROM products p WHERE p.category_id = c.id) AS product_count "
        "FROM categories c ORDER BY c.sort_order ASC, c.name ASC"
    ).fetchall()
    return jsonify([dict(r) for r in rows])


@app.post("/api/categories")
@admin_required
def api_create_category():
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "Название обязательно"}), 400
    db = get_db()
    try:
        cur = db.execute(
            "INSERT INTO categories (name, sort_order) VALUES (?, ?)",
            (name, int(data.get("sort_order") or 0)),
        )
        db.commit()
        return jsonify({"id": cur.lastrowid, "name": name})
    except sqlite3.IntegrityError:
        return jsonify({"error": "Категория с таким названием уже существует"}), 400


@app.put("/api/categories/<int:cid>")
@admin_required
def api_update_category(cid: int):
    data = request.get_json(force=True, silent=True) or {}
    db = get_db()
    if "name" in data:
        db.execute("UPDATE categories SET name = ? WHERE id = ?", (data["name"].strip(), cid))
    if "sort_order" in data:
        db.execute("UPDATE categories SET sort_order = ? WHERE id = ?", (int(data["sort_order"]), cid))
    db.commit()
    return jsonify({"ok": True})


@app.delete("/api/categories/<int:cid>")
@admin_required
def api_delete_category(cid: int):
    db = get_db()
    db.execute("DELETE FROM categories WHERE id = ?", (cid,))
    db.commit()
    return jsonify({"ok": True})


# ----------------------------- API: products ---------------------------------

@app.get("/api/products")
def api_products():
    db = get_db()
    rows = db.execute(
        "SELECT p.*, c.name AS category_name "
        "FROM products p LEFT JOIN categories c ON c.id = p.category_id "
        "ORDER BY p.pinned DESC, p.created_at DESC"
    ).fetchall()
    products = []
    for r in rows:
        products.append(product_to_dict(r, fetch_photos(r["id"])))
    return jsonify(products)


@app.get("/api/products/<int:pid>")
def api_get_product(pid: int):
    db = get_db()
    r = db.execute(
        "SELECT p.*, c.name AS category_name "
        "FROM products p LEFT JOIN categories c ON c.id = p.category_id "
        "WHERE p.id = ?",
        (pid,),
    ).fetchone()
    if not r:
        return jsonify({"error": "not found"}), 404
    return jsonify(product_to_dict(r, fetch_photos(pid)))


@app.post("/api/products")
@admin_required
def api_create_product():
    data = request.get_json(force=True, silent=True) or {}
    required = ["number", "name", "price"]
    for k in required:
        if data.get(k) in (None, ""):
            return jsonify({"error": f"Поле '{k}' обязательно"}), 400
    db = get_db()
    cur = db.execute(
        """INSERT INTO products
           (number, name, description, price, defect, category_id,
            weight, length, width, height,
            highlighted, highlight_label, highlight_color, pinned, status)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            str(data.get("number", "")).strip(),
            str(data.get("name", "")).strip(),
            str(data.get("description", "") or ""),
            float(data.get("price") or 0),
            str(data.get("defect", "") or ""),
            data.get("category_id") or None,
            float(data["weight"]) if data.get("weight") not in (None, "") else None,
            float(data["length"]) if data.get("length") not in (None, "") else None,
            float(data["width"]) if data.get("width") not in (None, "") else None,
            float(data["height"]) if data.get("height") not in (None, "") else None,
            1 if data.get("highlighted") else 0,
            str(data.get("highlight_label", "") or ""),
            str(data.get("highlight_color", "green") or "green"),
            1 if data.get("pinned") else 0,
            str(data.get("status", "available") or "available"),
        ),
    )
    db.commit()
    return jsonify({"id": cur.lastrowid})


@app.put("/api/products/<int:pid>")
@admin_required
def api_update_product(pid: int):
    data = request.get_json(force=True, silent=True) or {}
    db = get_db()
    fields_map = {
        "number": str, "name": str, "description": str, "price": float,
        "defect": str, "category_id": lambda x: int(x) if x else None,
        "weight": lambda x: float(x) if x not in (None, "") else None,
        "length": lambda x: float(x) if x not in (None, "") else None,
        "width": lambda x: float(x) if x not in (None, "") else None,
        "height": lambda x: float(x) if x not in (None, "") else None,
        "highlighted": lambda x: 1 if x else 0,
        "highlight_label": str,
        "highlight_color": str,
        "pinned": lambda x: 1 if x else 0,
        "status": str,
    }
    sets, vals = [], []
    for k, conv in fields_map.items():
        if k in data:
            try:
                sets.append(f"{k} = ?")
                vals.append(conv(data[k]))
            except (ValueError, TypeError):
                pass
    if sets:
        sets.append("updated_at = CURRENT_TIMESTAMP")
        vals.append(pid)
        db.execute(f"UPDATE products SET {', '.join(sets)} WHERE id = ?", vals)
        db.commit()
    return jsonify({"ok": True})


@app.delete("/api/products/<int:pid>")
@admin_required
def api_delete_product(pid: int):
    db = get_db()
    photos = db.execute("SELECT filename FROM photos WHERE product_id = ?", (pid,)).fetchall()
    for ph in photos:
        try:
            (UPLOAD_DIR / ph["filename"]).unlink(missing_ok=True)
        except Exception:
            pass
    db.execute("DELETE FROM products WHERE id = ?", (pid,))
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/products/bulk_delete")
@admin_required
def api_bulk_delete():
    data = request.get_json(force=True, silent=True) or {}
    ids = data.get("ids") or []
    if not ids:
        return jsonify({"ok": True, "deleted": 0})
    db = get_db()
    qmarks = ",".join("?" * len(ids))
    photos = db.execute(
        f"SELECT filename FROM photos WHERE product_id IN ({qmarks})", ids
    ).fetchall()
    for ph in photos:
        try:
            (UPLOAD_DIR / ph["filename"]).unlink(missing_ok=True)
        except Exception:
            pass
    db.execute(f"DELETE FROM products WHERE id IN ({qmarks})", ids)
    db.commit()
    return jsonify({"ok": True, "deleted": len(ids)})


# ----------------------------- API: photos -----------------------------------

@app.post("/api/products/<int:pid>/photos")
@admin_required
def api_upload_photos(pid: int):
    db = get_db()
    prod = db.execute("SELECT id FROM products WHERE id = ?", (pid,)).fetchone()
    if not prod:
        return jsonify({"error": "Товар не найден"}), 404

    existing = db.execute("SELECT COUNT(*) AS c FROM photos WHERE product_id = ?", (pid,)).fetchone()["c"]
    slots_left = MAX_PHOTOS_PER_PRODUCT - existing
    if slots_left <= 0:
        return jsonify({"error": f"Максимум {MAX_PHOTOS_PER_PRODUCT} фото на товар"}), 400

    files = request.files.getlist("photos")
    if not files:
        return jsonify({"error": "Файлы не переданы"}), 400

    saved = []
    for f in files[:slots_left]:
        if not f or not f.filename:
            continue
        try:
            filename = save_photo(f, pid)
        except Exception as e:
            continue
        is_main = 1 if existing == 0 and not saved else 0
        cur = db.execute(
            "INSERT INTO photos (product_id, filename, is_main, sort_order) VALUES (?,?,?,?)",
            (pid, filename, is_main, existing + len(saved)),
        )
        saved.append({"id": cur.lastrowid, "filename": filename})
    db.commit()
    return jsonify({"ok": True, "saved": saved, "photos": fetch_photos(pid)})


@app.delete("/api/photos/<int:photo_id>")
@admin_required
def api_delete_photo(photo_id: int):
    db = get_db()
    row = db.execute("SELECT product_id, filename, is_main FROM photos WHERE id = ?", (photo_id,)).fetchone()
    if not row:
        return jsonify({"error": "Фото не найдено"}), 404
    try:
        (UPLOAD_DIR / row["filename"]).unlink(missing_ok=True)
    except Exception:
        pass
    db.execute("DELETE FROM photos WHERE id = ?", (photo_id,))
    # If main photo was deleted — promote the first remaining
    if row["is_main"]:
        remaining = db.execute(
            "SELECT id FROM photos WHERE product_id = ? ORDER BY sort_order ASC LIMIT 1",
            (row["product_id"],),
        ).fetchone()
        if remaining:
            db.execute("UPDATE photos SET is_main = 1 WHERE id = ?", (remaining["id"],))
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/photos/<int:photo_id>/main")
@admin_required
def api_set_main_photo(photo_id: int):
    db = get_db()
    row = db.execute("SELECT product_id FROM photos WHERE id = ?", (photo_id,)).fetchone()
    if not row:
        return jsonify({"error": "Фото не найдено"}), 404
    db.execute("UPDATE photos SET is_main = 0 WHERE product_id = ?", (row["product_id"],))
    db.execute("UPDATE photos SET is_main = 1 WHERE id = ?", (photo_id,))
    db.commit()
    return jsonify({"ok": True})


@app.post("/api/products/<int:pid>/photos/reorder")
@admin_required
def api_reorder_photos(pid: int):
    data = request.get_json(force=True, silent=True) or {}
    order = data.get("order") or []
    db = get_db()
    for i, photo_id in enumerate(order):
        db.execute(
            "UPDATE photos SET sort_order = ? WHERE id = ? AND product_id = ?",
            (i, int(photo_id), pid),
        )
    db.commit()
    return jsonify({"ok": True})


# ----------------------------- API: stats ------------------------------------

@app.get("/api/stats")
@admin_required
def api_stats():
    db = get_db()
    total_visitors = db.execute("SELECT count FROM visitor_total WHERE id = 1").fetchone()["count"]
    today = dt.date.today().isoformat()
    today_visitors = db.execute(
        "SELECT count FROM visitors WHERE day = ?", (today,)
    ).fetchone()
    today_visitors = today_visitors["count"] if today_visitors else 0
    last_7 = db.execute(
        "SELECT day, count FROM visitors WHERE day >= ? ORDER BY day ASC",
        ((dt.date.today() - dt.timedelta(days=6)).isoformat(),),
    ).fetchall()

    total_products = db.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
    total_value = db.execute("SELECT COALESCE(SUM(price),0) AS s FROM products").fetchone()["s"]
    total_categories = db.execute("SELECT COUNT(*) AS c FROM categories").fetchone()["c"]
    by_status = db.execute(
        "SELECT status, COUNT(*) AS c FROM products GROUP BY status"
    ).fetchall()
    by_category = db.execute(
        "SELECT COALESCE(c.name, 'Без категории') AS name, COUNT(p.id) AS c "
        "FROM products p LEFT JOIN categories c ON c.id = p.category_id "
        "GROUP BY c.id ORDER BY c DESC"
    ).fetchall()

    return jsonify({
        "visitors_total": total_visitors,
        "visitors_today": today_visitors,
        "visitors_last_7": [dict(r) for r in last_7],
        "products_total": total_products,
        "products_value": total_value,
        "categories_total": total_categories,
        "by_status": {r["status"]: r["c"] for r in by_status},
        "by_category": [dict(r) for r in by_category],
    })


@app.get("/api/visitor_count")
def api_visitor_count():
    """Публичный счётчик — общее число."""
    db = get_db()
    row = db.execute("SELECT count FROM visitor_total WHERE id = 1").fetchone()
    return jsonify({"count": row["count"] if row else 0})


# ----------------------------- API: backup -----------------------------------

@app.get("/api/backup")
@admin_required
def api_backup():
    """Создаёт ZIP-архив с CSV и всеми фотографиями по папкам."""
    db = get_db()
    products = db.execute(
        "SELECT p.*, c.name AS category_name "
        "FROM products p LEFT JOIN categories c ON c.id = p.category_id "
        "ORDER BY p.id ASC"
    ).fetchall()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # CSV: products
        csv_io = io.StringIO()
        writer = csv.writer(csv_io, delimiter=";")
        writer.writerow([
            "id", "number", "name", "description", "price", "defect",
            "category", "weight_kg", "length_cm", "width_cm", "height_cm",
            "highlighted", "highlight_label", "pinned", "status",
            "created_at", "updated_at", "photos"
        ])
        for p in products:
            photos = db.execute(
                "SELECT filename FROM photos WHERE product_id = ? ORDER BY is_main DESC, sort_order ASC",
                (p["id"],),
            ).fetchall()
            writer.writerow([
                p["id"], p["number"], p["name"], p["description"] or "",
                p["price"], p["defect"] or "", p["category_name"] or "",
                p["weight"] or "", p["length"] or "", p["width"] or "", p["height"] or "",
                "да" if p["highlighted"] else "нет", p["highlight_label"] or "",
                "да" if p["pinned"] else "нет", p["status"] or "available",
                p["created_at"], p["updated_at"],
                ", ".join(ph["filename"] for ph in photos),
            ])
        zf.writestr("products.csv", "\ufeff" + csv_io.getvalue())

        # CSV: categories
        cat_io = io.StringIO()
        cw = csv.writer(cat_io, delimiter=";")
        cw.writerow(["id", "name", "sort_order"])
        for c in db.execute("SELECT * FROM categories ORDER BY id").fetchall():
            cw.writerow([c["id"], c["name"], c["sort_order"]])
        zf.writestr("categories.csv", "\ufeff" + cat_io.getvalue())

        # JSON: settings (без пароля)
        s = settings_dict()
        s.pop("admin_password", None)
        zf.writestr("settings.json", json.dumps(s, ensure_ascii=False, indent=2))

        # Photos by folder
        for p in products:
            photos = db.execute(
                "SELECT filename, is_main FROM photos WHERE product_id = ? "
                "ORDER BY is_main DESC, sort_order ASC",
                (p["id"],),
            ).fetchall()
            safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in (p["name"] or ""))[:40]
            folder = f"photos/{p['id']:04d}_{p['number']}_{safe_name}"
            for ph in photos:
                src = UPLOAD_DIR / ph["filename"]
                if src.exists():
                    arc_name = ("main_" if ph["is_main"] else "") + ph["filename"]
                    zf.write(src, f"{folder}/{arc_name}")

        # SQLite copy
        db_copy_path = DATA_DIR / "store.db"
        if db_copy_path.exists():
            zf.write(db_copy_path, "store.db")

        # README
        zf.writestr("README.txt",
                    "Бэкап создан: " + dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S") + "\n"
                    "Содержимое:\n"
                    " - products.csv   — таблица товаров (UTF-8 BOM, разделитель ';')\n"
                    " - categories.csv — таблица категорий\n"
                    " - settings.json  — настройки магазина\n"
                    " - photos/        — фотографии товаров по папкам (id_номер_название)\n"
                    " - store.db       — полная копия БД (SQLite)\n")

    buf.seek(0)
    fname = f"backup_{dt.datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    return send_file(
        buf, mimetype="application/zip",
        as_attachment=True, download_name=fname,
    )


# ----------------------------- Error handlers --------------------------------

@app.errorhandler(413)
def too_large(_):
    return jsonify({"error": f"Файл слишком большой (макс {MAX_PHOTO_SIZE_MB} МБ)"}), 413


# ----------------------------- Entrypoint ------------------------------------

with app.app_context():
    init_db()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=False)
