import sqlite3
import datetime
from contextlib import contextmanager

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    number TEXT NOT NULL,
    title TEXT NOT NULL,
    price REAL NOT NULL,
    old_price REAL,
    fault TEXT,
    description TEXT,
    weight REAL,
    length REAL,
    width REAL,
    height REAL,
    video_url TEXT,
    category_id INTEGER,
    featured INTEGER NOT NULL DEFAULT 0,
    pinned INTEGER NOT NULL DEFAULT 0,
    is_top INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY (category_id) REFERENCES categories(id)
);

CREATE TABLE IF NOT EXISTS product_photos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    filename TEXT NOT NULL,
    is_main INTEGER NOT NULL DEFAULT 0,
    sort_order INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS visitors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    visit_date TEXT NOT NULL,
    ip TEXT,
    event TEXT NOT NULL DEFAULT 'visit',
    product_id INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS review_screenshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL,
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_name TEXT NOT NULL,
    customer_phone TEXT NOT NULL,
    items_json TEXT NOT NULL,
    total REAL NOT NULL,
    telegram_sent INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
CREATE INDEX IF NOT EXISTS idx_photos_product ON product_photos(product_id);
CREATE INDEX IF NOT EXISTS idx_visitors_date ON visitors(visit_date);
"""

DEFAULT_SETTINGS = {
    "site_title": config.SITE_TITLE_DEFAULT,
    "contact_phone": config.CONTACT_PHONE_DEFAULT,
    "contact_name": config.CONTACT_NAME_DEFAULT,
    "ship_address": config.SHIP_ADDRESS_DEFAULT,
    "reviews_enabled": "1",
    "telegram_proxy_scheme": "socks5",
    "telegram_proxy_ip": "",
    "telegram_proxy_port": "",
    "telegram_proxy_login": "",
    "telegram_proxy_password": "",
}


def get_connection():
    conn = sqlite3.connect(config.DATABASE_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


@contextmanager
def db_cursor(commit=False):
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        if commit:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def now():
    return datetime.datetime.utcnow().isoformat()


def init_db():
    conn = get_connection()
    conn.executescript(SCHEMA)
    conn.commit()

    _migrate(conn)

    from werkzeug.security import generate_password_hash
    cur = conn.execute("SELECT value FROM settings WHERE key = 'admin_password_hash'")
    if cur.fetchone() is None:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('admin_password_hash', ?)",
            (generate_password_hash(config.ADMIN_PASSWORD_DEFAULT),),
        )

    for key, value in DEFAULT_SETTINGS.items():
        cur = conn.execute("SELECT value FROM settings WHERE key = ?", (key,))
        if cur.fetchone() is None:
            conn.execute("INSERT INTO settings (key, value) VALUES (?, ?)", (key, value))

    conn.commit()
    conn.close()


def _migrate(conn):
    """Добавляет новые колонки в уже существующие таблицы (для сайтов, развёрнутых ранее)."""
    def existing_columns(table):
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}

    products_cols = existing_columns("products")
    if "is_top" not in products_cols:
        conn.execute("ALTER TABLE products ADD COLUMN is_top INTEGER NOT NULL DEFAULT 0")

    orders_cols = existing_columns("orders")
    if "processed" not in orders_cols:
        conn.execute("ALTER TABLE orders ADD COLUMN processed INTEGER NOT NULL DEFAULT 0")

    # Разбираем старый единый telegram_proxy_url на отдельные поля, если они ещё не заполнены
    old_row = conn.execute("SELECT value FROM settings WHERE key = 'telegram_proxy_url'").fetchone()
    new_ip_row = conn.execute("SELECT value FROM settings WHERE key = 'telegram_proxy_ip'").fetchone()
    if old_row and old_row["value"] and not (new_ip_row and new_ip_row["value"]):
        import re
        m = re.match(r"^(\w+)://(?:([^:]+):([^@]+)@)?([^:/]+)(?::(\d+))?/?$", old_row["value"].strip())
        if m:
            scheme, login, password, ip, port = m.groups()
            for key, val in [
                ("telegram_proxy_scheme", scheme or "socks5"),
                ("telegram_proxy_ip", ip or ""),
                ("telegram_proxy_port", port or ""),
                ("telegram_proxy_login", login or ""),
                ("telegram_proxy_password", password or ""),
            ]:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, val),
                )

    conn.commit()


def get_settings():
    with db_cursor() as cur:
        cur.execute("SELECT key, value FROM settings")
        return {row["key"]: row["value"] for row in cur.fetchall()}


def set_setting(key, value):
    with db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
