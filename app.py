import os
import uuid
import functools

from flask import (
    Flask, render_template, request, redirect, url_for, session,
    send_from_directory, flash, jsonify, abort, Response
)
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from PIL import Image

import config
import db
import telegram
import backup as backup_module
from startup_import import run_startup_import

app = Flask(__name__)
app.config["SECRET_KEY"] = config.SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = config.MAX_BACKUP_UPLOAD_MB * 1024 * 1024

db.init_db()
run_startup_import()


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def admin_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def get_cart():
    return session.get("cart", {})


def save_cart(cart):
    session["cart"] = cart
    session.modified = True


def get_cart_items():
    cart = get_cart()
    if not cart:
        return [], 0
    ids = [int(pid) for pid in cart.keys()]
    with db.db_cursor() as cur:
        placeholders = ",".join("?" * len(ids))
        cur.execute(
            f"SELECT p.*, "
            f"(SELECT filename FROM product_photos ph WHERE ph.product_id = p.id "
            f" ORDER BY ph.is_main DESC, ph.sort_order ASC LIMIT 1) AS main_photo "
            f"FROM products p WHERE p.id IN ({placeholders})",
            ids,
        )
        rows = {row["id"]: dict(row) for row in cur.fetchall()}

    items = []
    total = 0
    for pid_str, qty in cart.items():
        pid = int(pid_str)
        p = rows.get(pid)
        if not p:
            continue
        line_sum = round(p["price"] * qty, 2)
        total += line_sum
        items.append({
            "id": p["id"], "number": p["number"], "title": p["title"],
            "price": p["price"], "qty": qty, "sum": line_sum,
            "main_photo": p.get("main_photo"),
        })
    return items, round(total, 2)


def log_visit(event="visit", product_id=None):
    with db.db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO visitors (visit_date, ip, event, product_id, created_at) VALUES (?,?,?,?,?)",
            (db.now()[:10], request.remote_addr, event, product_id, db.now()),
        )


def fetch_categories():
    with db.db_cursor() as cur:
        cur.execute("SELECT * FROM categories ORDER BY sort_order ASC, name ASC")
        return [dict(r) for r in cur.fetchall()]


def fetch_product_main_photo(product_id):
    with db.db_cursor() as cur:
        cur.execute(
            "SELECT filename FROM product_photos WHERE product_id = ? "
            "ORDER BY is_main DESC, sort_order ASC LIMIT 1",
            (product_id,),
        )
        row = cur.fetchone()
        return row["filename"] if row else None


def base_context():
    s = db.get_settings()
    cart = get_cart()
    cart_count = sum(cart.values()) if cart else 0
    reviews_enabled = s.get("reviews_enabled", "1") == "1"
    screenshots = []
    if reviews_enabled:
        with db.db_cursor() as cur:
            cur.execute("SELECT * FROM review_screenshots ORDER BY sort_order ASC")
            screenshots = [dict(r) for r in cur.fetchall()]
    return {
        "site_title": s.get("site_title", config.SITE_TITLE_DEFAULT),
        "contact_phone": s.get("contact_phone", config.CONTACT_PHONE_DEFAULT),
        "contact_name": s.get("contact_name", config.CONTACT_NAME_DEFAULT),
        "ship_address": s.get("ship_address", config.SHIP_ADDRESS_DEFAULT),
        "reviews_enabled": reviews_enabled,
        "review_screenshots": screenshots,
        "categories": fetch_categories(),
        "cart_count": cart_count,
    }


# ---------------------------------------------------------------------------
# public storefront
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    log_visit("visit")
    q = request.args.get("q", "").strip()
    sort = request.args.get("sort", "pinned")
    category_id = request.args.get("category", type=int)

    top_query = (
        "SELECT p.*, "
        "(SELECT filename FROM product_photos ph WHERE ph.product_id = p.id "
        " ORDER BY ph.is_main DESC, ph.sort_order ASC LIMIT 1) AS main_photo "
        "FROM products p WHERE p.is_active = 1 AND p.is_top = 1 "
    )
    top_params = []
    if category_id:
        top_query += "AND p.category_id = ? "
        top_params.append(category_id)
    top_query += "ORDER BY p.created_at DESC LIMIT 12"

    with db.db_cursor() as cur:
        cur.execute(top_query, top_params)
        top_products = [dict(r) for r in cur.fetchall()]

    query = (
        "SELECT p.*, "
        "(SELECT filename FROM product_photos ph WHERE ph.product_id = p.id "
        " ORDER BY ph.is_main DESC, ph.sort_order ASC LIMIT 1) AS main_photo "
        "FROM products p WHERE p.is_active = 1 "
    )
    params = []
    if q:
        query += "AND (p.title LIKE ? OR p.number LIKE ?) "
        params += [f"%{q}%", f"%{q}%"]
    if category_id:
        query += "AND p.category_id = ? "
        params.append(category_id)

    order_map = {
        "pinned": "p.pinned DESC, p.featured DESC, p.created_at DESC",
        "price_asc": "p.price ASC",
        "price_desc": "p.price DESC",
        "new": "p.created_at DESC",
    }
    query += "ORDER BY " + order_map.get(sort, order_map["pinned"])

    with db.db_cursor() as cur:
        cur.execute(query, params)
        products = [dict(r) for r in cur.fetchall()]

    ctx = base_context()
    ctx.update({
        "products": products,
        "top_products": top_products,
        "q": q,
        "sort": sort,
        "active_category": category_id,
    })
    return render_template("index.html", **ctx)


@app.route("/product/<int:product_id>")
def product_detail(product_id):
    with db.db_cursor() as cur:
        cur.execute("SELECT * FROM products WHERE id = ? AND is_active = 1", (product_id,))
        row = cur.fetchone()
        if not row:
            abort(404)
        product = dict(row)
        cur.execute(
            "SELECT * FROM product_photos WHERE product_id = ? ORDER BY is_main DESC, sort_order ASC",
            (product_id,),
        )
        photos = [dict(r) for r in cur.fetchall()]
        category = None
        if product["category_id"]:
            cur.execute("SELECT * FROM categories WHERE id = ?", (product["category_id"],))
            crow = cur.fetchone()
            category = dict(crow) if crow else None

    log_visit("visit", product_id)

    ctx = base_context()
    ctx.update({"product": product, "photos": photos, "category": category})
    return render_template("product.html", **ctx)


@app.route("/cart/add", methods=["POST"])
def cart_add():
    product_id = request.form.get("product_id", type=int)
    qty = max(1, request.form.get("qty", default=1, type=int))
    if not product_id:
        abort(400)

    with db.db_cursor() as cur:
        cur.execute("SELECT id FROM products WHERE id = ? AND is_active = 1", (product_id,))
        if not cur.fetchone():
            abort(404)

    cart = get_cart()
    key = str(product_id)
    cart[key] = cart.get(key, 0) + qty
    save_cart(cart)
    log_visit("cart_add", product_id)

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        _, total = get_cart_items()
        return jsonify({"ok": True, "cart_count": sum(cart.values()), "total": total})
    return redirect(url_for("product_detail", product_id=product_id, added=1))


@app.route("/cart/update", methods=["POST"])
def cart_update():
    product_id = str(request.form.get("product_id", ""))
    action = request.form.get("action")
    cart = get_cart()

    if product_id in cart:
        if action == "remove":
            del cart[product_id]
        elif action == "inc":
            cart[product_id] += 1
        elif action == "dec":
            cart[product_id] -= 1
            if cart[product_id] <= 0:
                del cart[product_id]
    save_cart(cart)
    return redirect(url_for("cart_view"))


@app.route("/cart")
def cart_view():
    items, total = get_cart_items()
    ctx = base_context()
    ctx.update({"items": items, "total": total})
    return render_template("cart.html", **ctx)


@app.route("/checkout", methods=["POST"])
def checkout():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    items, total = get_cart_items()

    if not name or not phone or not items:
        flash("Заполните имя и телефон", "error")
        return redirect(url_for("cart_view"))

    order = {"customer_name": name, "customer_phone": phone, "items": items, "total": total}
    sent = telegram.send_order_notification(order)

    import json as _json
    with db.db_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO orders (customer_name, customer_phone, items_json, total, telegram_sent, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (name, phone, _json.dumps(items, ensure_ascii=False), total, int(sent), db.now()),
        )

    save_cart({})
    ctx = base_context()
    ctx.update({"order_total": total})
    return render_template("checkout_success.html", **ctx)


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(config.UPLOADS_PATH, filename)


@app.route("/reviews-media/<path:filename>")
def review_file(filename):
    return send_from_directory(config.REVIEWS_PATH, filename)


# ---------------------------------------------------------------------------
# admin auth
# ---------------------------------------------------------------------------

@app.route("/adm/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        password = request.form.get("password", "")
        settings = db.get_settings()
        stored_hash = settings.get("admin_password_hash", "")
        if stored_hash and check_password_hash(stored_hash, password):
            session["is_admin"] = True
            nxt = request.args.get("next") or url_for("admin_dashboard")
            return redirect(nxt)
        flash("Неверный пароль", "error")
    return render_template("admin/login.html")


@app.route("/adm/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))


# ---------------------------------------------------------------------------
# admin: dashboard / stats
# ---------------------------------------------------------------------------

@app.route("/adm")
@admin_required
def admin_dashboard():
    with db.db_cursor() as cur:
        cur.execute("SELECT COUNT(*) c FROM products WHERE is_active = 1")
        products_count = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) c FROM categories")
        categories_count = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) c FROM visitors WHERE event = 'visit'")
        visits_count = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) c FROM visitors WHERE event = 'cart_add'")
        cart_adds_count = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) c FROM orders")
        orders_count = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) c FROM orders WHERE processed = 0")
        orders_unprocessed_count = cur.fetchone()["c"]
        cur.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 15")
        recent_orders = [dict(r) for r in cur.fetchall()]

    return render_template(
        "admin/dashboard.html",
        products_count=products_count,
        categories_count=categories_count,
        visits_count=visits_count,
        cart_adds_count=cart_adds_count,
        orders_count=orders_count,
        orders_unprocessed_count=orders_unprocessed_count,
        recent_orders=recent_orders,
    )


@app.route("/adm/orders/<int:order_id>/toggle-processed", methods=["POST"])
@admin_required
def admin_order_toggle_processed(order_id):
    with db.db_cursor() as cur:
        cur.execute("SELECT processed FROM orders WHERE id = ?", (order_id,))
        row = cur.fetchone()
        if not row:
            abort(404)
        new_value = 0 if row["processed"] else 1
    with db.db_cursor(commit=True) as cur:
        cur.execute("UPDATE orders SET processed = ? WHERE id = ?", (new_value, order_id))
    return redirect(request.referrer or url_for("admin_dashboard"))


@app.route("/adm/stats")
@admin_required
def admin_stats():
    import datetime as _dt
    today = _dt.date.today()
    yesterday = today - _dt.timedelta(days=1)
    week_ago = today - _dt.timedelta(days=7)
    month_ago = today - _dt.timedelta(days=30)

    def period_counts(date_from, date_to=None):
        date_to = date_to or today
        with db.db_cursor() as cur:
            cur.execute(
                "SELECT "
                "SUM(CASE WHEN event='visit' THEN 1 ELSE 0 END) visits, "
                "SUM(CASE WHEN event='cart_add' THEN 1 ELSE 0 END) cart_adds "
                "FROM visitors WHERE visit_date >= ? AND visit_date <= ?",
                (date_from.isoformat(), date_to.isoformat()),
            )
            row = cur.fetchone()
            return {"visits": row["visits"] or 0, "cart_adds": row["cart_adds"] or 0}

    summary = {
        "today": period_counts(today),
        "yesterday": period_counts(yesterday, yesterday),
        "week": period_counts(week_ago),
        "month": period_counts(month_ago),
    }

    with db.db_cursor() as cur:
        cur.execute(
            "SELECT visit_date, "
            "SUM(CASE WHEN event='visit' THEN 1 ELSE 0 END) visits, "
            "SUM(CASE WHEN event='cart_add' THEN 1 ELSE 0 END) cart_adds "
            "FROM visitors GROUP BY visit_date ORDER BY visit_date DESC LIMIT 30"
        )
        daily = [dict(r) for r in cur.fetchall()]
    return render_template("admin/stats.html", daily=daily, summary=summary)


# ---------------------------------------------------------------------------
# admin: categories
# ---------------------------------------------------------------------------

@app.route("/adm/categories", methods=["GET", "POST"])
@admin_required
def admin_categories():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if name:
            with db.db_cursor(commit=True) as cur:
                cur.execute(
                    "INSERT INTO categories (name, sort_order, created_at) VALUES (?, 0, ?)",
                    (name, db.now()),
                )
        return redirect(url_for("admin_categories"))

    with db.db_cursor() as cur:
        cur.execute(
            "SELECT c.*, (SELECT COUNT(*) FROM products p WHERE p.category_id = c.id) product_count "
            "FROM categories c ORDER BY c.sort_order ASC, c.name ASC"
        )
        categories = [dict(r) for r in cur.fetchall()]
    return render_template("admin/categories.html", categories=categories)


@app.route("/adm/categories/<int:cat_id>/delete", methods=["POST"])
@admin_required
def admin_category_delete(cat_id):
    with db.db_cursor(commit=True) as cur:
        cur.execute("UPDATE products SET category_id = NULL WHERE category_id = ?", (cat_id,))
        cur.execute("DELETE FROM categories WHERE id = ?", (cat_id,))
    return redirect(url_for("admin_categories"))


# ---------------------------------------------------------------------------
# admin: products
# ---------------------------------------------------------------------------

@app.route("/adm/products")
@admin_required
def admin_products():
    with db.db_cursor() as cur:
        cur.execute(
            "SELECT p.*, c.name AS category_name, "
            "(SELECT filename FROM product_photos ph WHERE ph.product_id = p.id "
            " ORDER BY ph.is_main DESC, ph.sort_order ASC LIMIT 1) AS main_photo "
            "FROM products p LEFT JOIN categories c ON c.id = p.category_id "
            "ORDER BY p.pinned DESC, p.id DESC"
        )
        products = [dict(r) for r in cur.fetchall()]
    return render_template("admin/products.html", products=products)


def _product_form_data():
    return {
        "number": request.form.get("number", "").strip(),
        "title": request.form.get("title", "").strip(),
        "price": request.form.get("price", type=float) or 0,
        "old_price": request.form.get("old_price", type=float) or None,
        "fault": request.form.get("fault", "").strip(),
        "description": request.form.get("description", "").strip(),
        "weight": request.form.get("weight", type=float),
        "length": request.form.get("length", type=float),
        "width": request.form.get("width", type=float),
        "height": request.form.get("height", type=float),
        "video_url": request.form.get("video_url", "").strip(),
        "category_id": request.form.get("category_id", type=int),
        "featured": 1 if request.form.get("featured") else 0,
        "pinned": 1 if request.form.get("pinned") else 0,
        "is_top": 1 if request.form.get("is_top") else 0,
        "is_active": 1 if request.form.get("is_active", "1") else 0,
    }


@app.route("/adm/products/new", methods=["GET", "POST"])
@admin_required
def admin_product_new():
    categories = fetch_categories()
    if request.method == "POST":
        data = _product_form_data()
        with db.db_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO products (number, title, price, old_price, fault, description, "
                "weight, length, width, height, video_url, category_id, featured, pinned, is_top, "
                "is_active, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    data["number"], data["title"], data["price"], data["old_price"], data["fault"],
                    data["description"], data["weight"], data["length"], data["width"], data["height"],
                    data["video_url"], data["category_id"], data["featured"], data["pinned"], data["is_top"],
                    data["is_active"], db.now(),
                ),
            )
            new_id = cur.lastrowid
        _handle_photo_uploads(new_id)
        return redirect(url_for("admin_products"))

    return render_template("admin/product_form.html", product=None, photos=[], categories=categories)


@app.route("/adm/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_product_edit(product_id):
    categories = fetch_categories()
    with db.db_cursor() as cur:
        cur.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        row = cur.fetchone()
        if not row:
            abort(404)
        product = dict(row)

    if request.method == "POST":
        data = _product_form_data()
        with db.db_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE products SET number=?, title=?, price=?, old_price=?, fault=?, description=?, "
                "weight=?, length=?, width=?, height=?, video_url=?, category_id=?, featured=?, "
                "pinned=?, is_top=?, is_active=? WHERE id=?",
                (
                    data["number"], data["title"], data["price"], data["old_price"], data["fault"],
                    data["description"], data["weight"], data["length"], data["width"], data["height"],
                    data["video_url"], data["category_id"], data["featured"], data["pinned"], data["is_top"],
                    data["is_active"], product_id,
                ),
            )
        _handle_photo_uploads(product_id)
        return redirect(url_for("admin_product_edit", product_id=product_id))

    with db.db_cursor() as cur:
        cur.execute(
            "SELECT * FROM product_photos WHERE product_id = ? ORDER BY is_main DESC, sort_order ASC",
            (product_id,),
        )
        photos = [dict(r) for r in cur.fetchall()]

    return render_template("admin/product_form.html", product=product, photos=photos, categories=categories)


@app.route("/adm/products/<int:product_id>/delete", methods=["POST"])
@admin_required
def admin_product_delete(product_id):
    with db.db_cursor() as cur:
        cur.execute("SELECT filename FROM product_photos WHERE product_id = ?", (product_id,))
        files = [r["filename"] for r in cur.fetchall()]
    for fname in files:
        fpath = os.path.join(config.UPLOADS_PATH, fname)
        if os.path.exists(fpath):
            os.remove(fpath)
    with db.db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM products WHERE id = ?", (product_id,))
    return redirect(url_for("admin_products"))


def _allowed_image(filename):
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return ext in config.ALLOWED_IMAGE_EXT


def _handle_photo_uploads(product_id):
    files = request.files.getlist("photos")
    if not files or files == [None]:
        return

    with db.db_cursor() as cur:
        cur.execute("SELECT COUNT(*) c FROM product_photos WHERE product_id = ?", (product_id,))
        existing_count = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) c FROM product_photos WHERE product_id = ? AND is_main = 1", (product_id,))
        has_main = cur.fetchone()["c"] > 0

    sort_i = existing_count
    for f in files:
        if not f or not f.filename:
            continue
        if existing_count >= config.MAX_PHOTOS_PER_PRODUCT:
            break
        if not _allowed_image(f.filename):
            continue

        ext = f.filename.rsplit(".", 1)[-1].lower()
        token = uuid.uuid4().hex[:16]
        is_main = 0
        if not has_main:
            is_main = 1
            has_main = True
        prefix = "main_" if is_main else ""
        filename = f"{prefix}p{product_id}_{token}.{ext if ext != 'jpeg' else 'jpg'}"
        filename = secure_filename(filename)
        dest = os.path.join(config.UPLOADS_PATH, filename)

        try:
            img = Image.open(f.stream)
            img = img.convert("RGB") if img.mode in ("RGBA", "P") else img
            img.thumbnail((1920, 1920))
            img.save(dest, quality=87, optimize=True)
        except Exception:
            f.stream.seek(0)
            f.save(dest)

        with db.db_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO product_photos (product_id, filename, is_main, sort_order) VALUES (?,?,?,?)",
                (product_id, filename, is_main, 0 if is_main else sort_i),
            )
        existing_count += 1
        sort_i += 1


@app.route("/adm/photos/<int:photo_id>/delete", methods=["POST"])
@admin_required
def admin_photo_delete(photo_id):
    with db.db_cursor() as cur:
        cur.execute("SELECT * FROM product_photos WHERE id = ?", (photo_id,))
        row = cur.fetchone()
        if not row:
            abort(404)
        photo = dict(row)

    fpath = os.path.join(config.UPLOADS_PATH, photo["filename"])
    if os.path.exists(fpath):
        os.remove(fpath)

    with db.db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM product_photos WHERE id = ?", (photo_id,))
        if photo["is_main"]:
            cur.execute(
                "SELECT id FROM product_photos WHERE product_id = ? ORDER BY sort_order ASC LIMIT 1",
                (photo["product_id"],),
            )
            nxt = cur.fetchone()
            if nxt:
                cur.execute("UPDATE product_photos SET is_main = 1 WHERE id = ?", (nxt["id"],))

    return redirect(url_for("admin_product_edit", product_id=photo["product_id"]))


@app.route("/adm/photos/<int:photo_id>/make-main", methods=["POST"])
@admin_required
def admin_photo_make_main(photo_id):
    with db.db_cursor() as cur:
        cur.execute("SELECT * FROM product_photos WHERE id = ?", (photo_id,))
        row = cur.fetchone()
        if not row:
            abort(404)
        photo = dict(row)

    with db.db_cursor(commit=True) as cur:
        cur.execute("UPDATE product_photos SET is_main = 0 WHERE product_id = ?", (photo["product_id"],))
        cur.execute("UPDATE product_photos SET is_main = 1 WHERE id = ?", (photo_id,))

    return redirect(url_for("admin_product_edit", product_id=photo["product_id"]))


# ---------------------------------------------------------------------------
# admin: reviews (screenshots carousel)
# ---------------------------------------------------------------------------

@app.route("/adm/reviews", methods=["GET", "POST"])
@admin_required
def admin_reviews():
    if request.method == "POST":
        if "toggle" in request.form:
            settings = db.get_settings()
            current = settings.get("reviews_enabled", "1")
            db.set_setting("reviews_enabled", "0" if current == "1" else "1")
        else:
            files = request.files.getlist("screenshots")
            with db.db_cursor() as cur:
                cur.execute("SELECT COUNT(*) c FROM review_screenshots")
                order_i = cur.fetchone()["c"]
            for f in files:
                if not f or not f.filename or not _allowed_image(f.filename):
                    continue
                ext = f.filename.rsplit(".", 1)[-1].lower()
                filename = secure_filename(f"rev_{uuid.uuid4().hex[:16]}.{ext if ext != 'jpeg' else 'jpg'}")
                dest = os.path.join(config.REVIEWS_PATH, filename)
                try:
                    img = Image.open(f.stream)
                    img = img.convert("RGB") if img.mode in ("RGBA", "P") else img
                    img.thumbnail((1600, 1600))
                    img.save(dest, quality=87, optimize=True)
                except Exception:
                    f.stream.seek(0)
                    f.save(dest)
                with db.db_cursor(commit=True) as cur:
                    cur.execute(
                        "INSERT INTO review_screenshots (filename, sort_order, created_at) VALUES (?,?,?)",
                        (filename, order_i, db.now()),
                    )
                order_i += 1
        return redirect(url_for("admin_reviews"))

    with db.db_cursor() as cur:
        cur.execute("SELECT * FROM review_screenshots ORDER BY sort_order ASC")
        screenshots = [dict(r) for r in cur.fetchall()]
    settings = db.get_settings()
    return render_template(
        "admin/reviews.html",
        screenshots=screenshots,
        reviews_enabled=settings.get("reviews_enabled", "1") == "1",
    )


@app.route("/adm/reviews/<int:shot_id>/delete", methods=["POST"])
@admin_required
def admin_review_delete(shot_id):
    with db.db_cursor() as cur:
        cur.execute("SELECT * FROM review_screenshots WHERE id = ?", (shot_id,))
        row = cur.fetchone()
    if row:
        fpath = os.path.join(config.REVIEWS_PATH, row["filename"])
        if os.path.exists(fpath):
            os.remove(fpath)
        with db.db_cursor(commit=True) as cur:
            cur.execute("DELETE FROM review_screenshots WHERE id = ?", (shot_id,))
    return redirect(url_for("admin_reviews"))


# ---------------------------------------------------------------------------
# admin: settings (telegram, proxy, contacts, admin password)
# ---------------------------------------------------------------------------

@app.route("/adm/settings", methods=["GET", "POST"])
@admin_required
def admin_settings():
    if request.method == "POST":
        for key in ["site_title", "contact_phone", "contact_name", "ship_address", "telegram_proxy_url"]:
            value = request.form.get(key)
            if value is not None:
                db.set_setting(key, value.strip())

        new_password = request.form.get("new_admin_password", "").strip()
        if new_password:
            db.set_setting("admin_password_hash", generate_password_hash(new_password))
            flash("Пароль администратора обновлён", "success")

        flash("Настройки сохранены", "success")
        return redirect(url_for("admin_settings"))

    settings = db.get_settings()
    telegram_configured = bool(config.TELEGRAM_BOT_TOKEN_DEFAULT and config.TELEGRAM_CHAT_ID_DEFAULT)
    return render_template("admin/settings.html", settings=settings, telegram_configured=telegram_configured)


# ---------------------------------------------------------------------------
# admin: backup
# ---------------------------------------------------------------------------

@app.route("/adm/backup")
@admin_required
def admin_backup():
    s3_backups = backup_module.list_s3_backups()
    return render_template("admin/backup.html", s3_backups=s3_backups)


@app.route("/adm/backup/download")
@admin_required
def admin_backup_download():
    data, filename = backup_module.create_backup_zip()
    return Response(
        data,
        mimetype="application/zip",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@app.route("/adm/backup/upload-s3", methods=["POST"])
@admin_required
def admin_backup_upload_s3():
    ok, info = backup_module.upload_backup_to_s3()
    flash(f"Бэкап загружен в S3: {info}" if ok else f"Ошибка: {info}", "success" if ok else "error")
    return redirect(url_for("admin_backup"))


@app.route("/adm/backup/import", methods=["POST"])
@admin_required
def admin_backup_import():
    f = request.files.get("backup_file")
    if not f or not f.filename:
        flash("Файл не выбран", "error")
        return redirect(url_for("admin_backup"))

    ok, info = backup_module.import_backup_zip(f.stream)
    if ok:
        flash(
            f"Импортировано: категорий {info['categories']}, товаров {info['products']}, "
            f"фото {info['photos']}, отзывов {info['reviews']}",
            "success",
        )
    else:
        flash(f"Ошибка импорта: {info}", "error")
    return redirect(url_for("admin_backup"))


# ---------------------------------------------------------------------------
# error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found(e):
    return render_template("404.html", **base_context()), 404


@app.errorhandler(413)
def too_large(e):
    flash(f"Файл слишком большой. Максимальный размер загрузки — {config.MAX_BACKUP_UPLOAD_MB} МБ.", "error")
    if session.get("is_admin"):
        return redirect(request.referrer or url_for("admin_backup"))
    return render_template("404.html", **base_context()), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=False)
