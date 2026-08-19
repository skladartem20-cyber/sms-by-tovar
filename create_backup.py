"""
Создаёт папку backup_{дата}/ в корне проекта со структурой:
store.db, products.csv, categories.csv, settings.json, photos/

Запуск:
    python3 create_backup.py

После создания переименуйте папку в backup/ и положите в корень
нового проекта перед первым запуском — импорт произойдёт автоматически.
"""
import os
import csv
import json
import shutil
import sqlite3
import datetime
import re

import config
import db


def safe_name(name):
    return re.sub(r"[^\w\-]+", "_", name or "", flags=re.UNICODE).strip("_")


def main():
    out_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        f"backup_{datetime.date.today().isoformat()}",
    )
    photos_dir = os.path.join(out_dir, "photos")
    os.makedirs(photos_dir, exist_ok=True)

    shutil.copyfile(config.DATABASE_PATH, os.path.join(out_dir, "store.db"))

    conn = db.get_connection()
    products = conn.execute("SELECT * FROM products ORDER BY id").fetchall()
    categories = conn.execute("SELECT * FROM categories ORDER BY id").fetchall()
    photos = conn.execute("SELECT * FROM product_photos ORDER BY product_id, sort_order").fetchall()
    settings = db.get_settings()
    conn.close()

    with open(os.path.join(out_dir, "products.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([
            "id", "number", "title", "price", "old_price", "fault", "description",
            "weight", "length", "width", "height", "video_url",
            "category_id", "featured", "pinned", "is_active", "created_at",
        ])
        for p in products:
            writer.writerow([p[k] for k in p.keys()])

    with open(os.path.join(out_dir, "categories.csv"), "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "name", "sort_order", "created_at"])
        for c in categories:
            writer.writerow([c[k] for k in c.keys()])

    settings_out = {
        "contact_phone": settings.get("contact_phone", ""),
        "contact_name": settings.get("contact_name", ""),
        "admin_password": "",
        "site_title": settings.get("site_title", ""),
        "ship_address": settings.get("ship_address", ""),
        "reviews_enabled": settings.get("reviews_enabled", "1"),
    }
    with open(os.path.join(out_dir, "settings.json"), "w", encoding="utf-8") as f:
        json.dump(settings_out, f, ensure_ascii=False, indent=2)

    photos_by_product = {}
    for ph in photos:
        photos_by_product.setdefault(ph["product_id"], []).append(ph)

    for p in products:
        folder_name = f"{p['id']:04d}_{safe_name(p['number'])}_{safe_name(p['title'])}"
        folder_path = os.path.join(photos_dir, folder_name)
        plist = photos_by_product.get(p["id"], [])
        if not plist:
            continue
        os.makedirs(folder_path, exist_ok=True)
        for ph in plist:
            src = os.path.join(config.UPLOADS_PATH, ph["filename"])
            if os.path.exists(src):
                shutil.copyfile(src, os.path.join(folder_path, ph["filename"]))

    review_out = os.path.join(out_dir, "reviews")
    if os.path.isdir(config.REVIEWS_PATH) and os.listdir(config.REVIEWS_PATH):
        os.makedirs(review_out, exist_ok=True)
        for fname in os.listdir(config.REVIEWS_PATH):
            src = os.path.join(config.REVIEWS_PATH, fname)
            if os.path.isfile(src):
                shutil.copyfile(src, os.path.join(review_out, fname))

    print(f"Бэкап создан: {out_dir}")
    print("Переименуйте папку в backup/ и положите в корень нового проекта перед деплоем.")


if __name__ == "__main__":
    main()
