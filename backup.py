import os
import io
import csv
import json
import shutil
import sqlite3
import zipfile
import tempfile
import datetime
import re

import boto3
from botocore.client import Config as BotoConfig

import config
import db


def _safe_name(name):
    return re.sub(r"[^\w\-]+", "_", name, flags=re.UNICODE).strip("_")


def _s3_client():
    if not (config.S3_ACCESS_KEY and config.S3_SECRET_KEY and config.S3_BUCKET):
        return None
    return boto3.client(
        "s3",
        endpoint_url=config.S3_ENDPOINT_URL,
        aws_access_key_id=config.S3_ACCESS_KEY,
        aws_secret_access_key=config.S3_SECRET_KEY,
        region_name=config.S3_REGION,
        config=BotoConfig(signature_version="s3v4"),
    )


def create_backup_zip():
    """Собирает backup/ в zip-архив в памяти и возвращает (bytes, filename)."""
    conn = db.get_connection()

    categories = conn.execute("SELECT * FROM categories ORDER BY id").fetchall()
    products = conn.execute("SELECT * FROM products ORDER BY id").fetchall()
    photos = conn.execute("SELECT * FROM product_photos ORDER BY product_id, sort_order").fetchall()
    settings = db.get_settings()
    conn.close()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(config.DATABASE_PATH, arcname="backup/store.db")

        products_csv = io.StringIO()
        writer = csv.writer(products_csv)
        writer.writerow([
            "id", "number", "title", "price", "old_price", "fault", "description",
            "weight", "length", "width", "height", "video_url",
            "category_id", "featured", "pinned", "is_active", "created_at",
        ])
        for p in products:
            writer.writerow([
                p["id"], p["number"], p["title"], p["price"], p["old_price"], p["fault"],
                p["description"], p["weight"], p["length"], p["width"], p["height"],
                p["video_url"], p["category_id"], p["featured"], p["pinned"],
                p["is_active"], p["created_at"],
            ])
        zf.writestr("backup/products.csv", products_csv.getvalue())

        categories_csv = io.StringIO()
        writer = csv.writer(categories_csv)
        writer.writerow(["id", "name", "sort_order", "created_at"])
        for c in categories:
            writer.writerow([c["id"], c["name"], c["sort_order"], c["created_at"]])
        zf.writestr("backup/categories.csv", categories_csv.getvalue())

        settings_out = {
            "contact_phone": settings.get("contact_phone", ""),
            "contact_name": settings.get("contact_name", ""),
            "admin_password": "",
            "site_title": settings.get("site_title", ""),
            "ship_address": settings.get("ship_address", ""),
            "reviews_enabled": settings.get("reviews_enabled", "1"),
        }
        zf.writestr("backup/settings.json", json.dumps(settings_out, ensure_ascii=False, indent=2))

        photos_by_product = {}
        for ph in photos:
            photos_by_product.setdefault(ph["product_id"], []).append(ph)

        for p in products:
            folder = f"{p['id']:04d}_{_safe_name(p['number'])}_{_safe_name(p['title'])}"
            plist = photos_by_product.get(p["id"], [])
            for ph in plist:
                src = os.path.join(config.UPLOADS_PATH, ph["filename"])
                if os.path.exists(src):
                    zf.write(src, arcname=f"backup/photos/{folder}/{ph['filename']}")

        review_dir = config.REVIEWS_PATH
        if os.path.isdir(review_dir):
            for fname in os.listdir(review_dir):
                fpath = os.path.join(review_dir, fname)
                if os.path.isfile(fpath):
                    zf.write(fpath, arcname=f"backup/reviews/{fname}")

    buf.seek(0)
    filename = f"backup_{datetime.date.today().isoformat()}.zip"
    return buf.read(), filename


def upload_backup_to_s3():
    client = _s3_client()
    if client is None:
        return False, "S3 не настроен (заполните переменные окружения)"

    data, filename = create_backup_zip()
    key = f"{config.S3_BACKUP_FOLDER}/{filename}"
    try:
        client.put_object(Bucket=config.S3_BUCKET, Key=key, Body=data)
        return True, key
    except Exception as exc:
        return False, str(exc)


def list_s3_backups():
    client = _s3_client()
    if client is None:
        return []
    try:
        resp = client.list_objects_v2(Bucket=config.S3_BUCKET, Prefix=f"{config.S3_BACKUP_FOLDER}/")
        items = resp.get("Contents", [])
        return sorted(
            [{"key": i["Key"], "size": i["Size"], "modified": i["LastModified"].isoformat()} for i in items],
            key=lambda x: x["modified"],
            reverse=True,
        )
    except Exception:
        return []


def download_s3_backup(key):
    client = _s3_client()
    if client is None:
        return None
    try:
        obj = client.get_object(Bucket=config.S3_BUCKET, Key=key)
        return obj["Body"].read()
    except Exception:
        return None


def import_backup_zip(file_stream):
    """
    Импортирует бэкап из zip-файла согласно логике:
    - store.db приоритетно, CSV как фоллбэк
    - фото копируются в UPLOADS_PATH
    - категории и товары сохраняют оригинальные id
    """
    with tempfile.TemporaryDirectory() as tmp:
        zpath = os.path.join(tmp, "upload.zip")
        with open(zpath, "wb") as f:
            f.write(file_stream.read())

        with zipfile.ZipFile(zpath) as zf:
            zf.extractall(tmp)

        root = None
        for candidate in [os.path.join(tmp, "backup"), tmp]:
            if os.path.exists(os.path.join(candidate, "store.db")) or os.path.exists(
                os.path.join(candidate, "products.csv")
            ):
                root = candidate
                break
        if root is None:
            for dirpath, dirnames, filenames in os.walk(tmp):
                if "store.db" in filenames or "products.csv" in filenames:
                    root = dirpath
                    break
        if root is None:
            return False, "Не найдена структура бэкапа (store.db / products.csv)"

        settings_path = os.path.join(root, "settings.json")
        if os.path.exists(settings_path):
            try:
                with open(settings_path, "r", encoding="utf-8") as f:
                    s = json.load(f)
                if s.get("contact_phone"):
                    db.set_setting("contact_phone", s["contact_phone"])
                if s.get("contact_name"):
                    db.set_setting("contact_name", s["contact_name"])
                if s.get("site_title"):
                    db.set_setting("site_title", s["site_title"])
                if s.get("ship_address"):
                    db.set_setting("ship_address", s["ship_address"])
                if "reviews_enabled" in s:
                    db.set_setting("reviews_enabled", str(s["reviews_enabled"]))
            except (json.JSONDecodeError, OSError):
                pass

        conn = db.get_connection()
        cur = conn.cursor()

        src_db_path = os.path.join(root, "store.db")
        imported_categories = []
        imported_products = []

        if os.path.exists(src_db_path):
            try:
                src_conn = sqlite3.connect(src_db_path)
                src_conn.row_factory = sqlite3.Row
                imported_categories = src_conn.execute("SELECT * FROM categories").fetchall()
                imported_products = src_conn.execute("SELECT * FROM products").fetchall()
                src_conn.close()
            except sqlite3.Error:
                imported_categories = []
                imported_products = []

        if not imported_categories and os.path.exists(os.path.join(root, "categories.csv")):
            with open(os.path.join(root, "categories.csv"), newline="", encoding="utf-8") as f:
                imported_categories = list(csv.DictReader(f))

        if not imported_products and os.path.exists(os.path.join(root, "products.csv")):
            with open(os.path.join(root, "products.csv"), newline="", encoding="utf-8") as f:
                imported_products = list(csv.DictReader(f))

        def val(row, key, default=None):
            try:
                v = row[key]
            except (KeyError, IndexError):
                return default
            return default if v is None else v

        for c in imported_categories:
            cid = int(val(c, "id"))
            name = val(c, "name", "Без названия")
            sort_order = val(c, "sort_order", 0) or 0
            created = val(c, "created_at") or db.now()
            cur.execute(
                "INSERT INTO categories (id, name, sort_order, created_at) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name",
                (cid, name, sort_order, created),
            )

        product_id_map = {}
        for p in imported_products:
            pid = int(val(p, "id"))
            product_id_map[pid] = pid
            cur.execute(
                "INSERT INTO products (id, number, title, price, old_price, fault, description, "
                "weight, length, width, height, video_url, category_id, featured, pinned, "
                "is_active, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET title=excluded.title, price=excluded.price",
                (
                    pid,
                    val(p, "number", ""),
                    val(p, "title", ""),
                    float(val(p, "price", 0) or 0),
                    (float(val(p, "old_price")) if val(p, "old_price") not in (None, "") else None),
                    val(p, "fault", ""),
                    val(p, "description", ""),
                    (float(val(p, "weight")) if val(p, "weight") not in (None, "") else None),
                    (float(val(p, "length")) if val(p, "length") not in (None, "") else None),
                    (float(val(p, "width")) if val(p, "width") not in (None, "") else None),
                    (float(val(p, "height")) if val(p, "height") not in (None, "") else None),
                    val(p, "video_url", ""),
                    (int(val(p, "category_id")) if val(p, "category_id") not in (None, "") else None),
                    int(val(p, "featured", 0) or 0),
                    int(val(p, "pinned", 0) or 0),
                    int(val(p, "is_active", 1) if val(p, "is_active", 1) not in (None, "") else 1),
                    val(p, "created_at") or db.now(),
                ),
            )

        conn.commit()

        photos_root = os.path.join(root, "photos")
        photos_imported = 0
        if os.path.isdir(photos_root):
            for folder_name in os.listdir(photos_root):
                folder_path = os.path.join(photos_root, folder_name)
                if not os.path.isdir(folder_path):
                    continue
                m = re.match(r"^(\d{4})_", folder_name)
                if not m:
                    continue
                pid = int(m.group(1))
                if pid not in product_id_map:
                    continue

                cur.execute("DELETE FROM product_photos WHERE product_id = ?", (pid,))
                files = sorted(os.listdir(folder_path))
                sort_i = 0
                for fname in files:
                    fsrc = os.path.join(folder_path, fname)
                    if not os.path.isfile(fsrc):
                        continue
                    is_main = 1 if fname.startswith("main_") else 0
                    dest = os.path.join(config.UPLOADS_PATH, fname)
                    shutil.copyfile(fsrc, dest)
                    cur.execute(
                        "INSERT INTO product_photos (product_id, filename, is_main, sort_order) "
                        "VALUES (?, ?, ?, ?)",
                        (pid, fname, is_main, 0 if is_main else sort_i),
                    )
                    if not is_main:
                        sort_i += 1
                    photos_imported += 1

        reviews_root = os.path.join(root, "reviews")
        reviews_imported = 0
        if os.path.isdir(reviews_root):
            for fname in os.listdir(reviews_root):
                fsrc = os.path.join(reviews_root, fname)
                if os.path.isfile(fsrc):
                    shutil.copyfile(fsrc, os.path.join(config.REVIEWS_PATH, fname))
                    cur.execute(
                        "INSERT INTO review_screenshots (filename, sort_order, created_at) VALUES (?, ?, ?)",
                        (fname, reviews_imported, db.now()),
                    )
                    reviews_imported += 1

        conn.commit()
        conn.close()

        return True, {
            "categories": len(imported_categories),
            "products": len(imported_products),
            "photos": photos_imported,
            "reviews": reviews_imported,
        }
