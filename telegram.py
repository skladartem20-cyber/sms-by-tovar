import requests
import config
import db


def send_order_notification(order):
    token = config.TELEGRAM_BOT_TOKEN_DEFAULT
    chat_id = config.TELEGRAM_CHAT_ID_DEFAULT

    if not token or not chat_id:
        return False

    settings = db.get_settings()
    proxy_url = settings.get("telegram_proxy_url", "")

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
