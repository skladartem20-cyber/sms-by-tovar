import requests
import config
import db


def build_proxy_url(settings):
    ip = (settings.get("telegram_proxy_ip") or "").strip()
    if not ip:
        return None
    scheme = settings.get("telegram_proxy_scheme") or "socks5"
    port = (settings.get("telegram_proxy_port") or "").strip()
    login = (settings.get("telegram_proxy_login") or "").strip()
    password = (settings.get("telegram_proxy_password") or "").strip()

    auth = f"{login}:{password}@" if login else ""
    host = f"{ip}:{port}" if port else ip
    return f"{scheme}://{auth}{host}"


def send_order_notification(order):
    token = config.TELEGRAM_BOT_TOKEN_DEFAULT
    chat_id = config.TELEGRAM_CHAT_ID_DEFAULT

    if not token or not chat_id:
        return False

    settings = db.get_settings()
    proxy_url = build_proxy_url(settings)

    lines = [
        "🆕 Новый заказ",
        f"Имя: {order['customer_name']}",
        f"Телефон: {order['customer_phone']}",
        "",
        "Состав заказа:",
    ]
    for item in order["items"]:
        lines.append(f"— {item['title']} (арт. {item['number']}) × {item['qty']} = {item['sum']} ₽")
    lines.append("")
    lines.append(f"Итого: {order['total']} ₽")
    text = "\n".join(lines)

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}

    proxies = None
    if proxy_url:
        proxies = {"http": proxy_url, "https": proxy_url}

    try:
        resp = requests.post(url, json=payload, proxies=proxies, timeout=15)
        return resp.status_code == 200
    except requests.RequestException:
        return False
