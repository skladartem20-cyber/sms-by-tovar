"""
При старте приложения проверяет наличие папки backup/ в корне проекта.
Если backup/.imported ещё не создан — выполняет импорт согласно логике
из BACKUP_LOGIC.md и создаёт маркер, чтобы не импортировать повторно.
"""
import os
import io
import zipfile

import backup as backup_module

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
BACKUP_DIR = os.path.join(PROJECT_ROOT, "backup")
MARKER_FILE = os.path.join(BACKUP_DIR, ".imported")


def run_startup_import():
    if not os.path.isdir(BACKUP_DIR):
        return
    if os.path.exists(MARKER_FILE):
        return

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for dirpath, dirnames, filenames in os.walk(BACKUP_DIR):
            for fname in filenames:
                full = os.path.join(dirpath, fname)
                arcname = os.path.join("backup", os.path.relpath(full, BACKUP_DIR))
                zf.write(full, arcname=arcname)
    buf.seek(0)

    ok, info = backup_module.import_backup_zip(buf)
    if ok:
        with open(MARKER_FILE, "w") as f:
            f.write("imported")
        print(f"[startup_import] Импорт завершён: {info}")
    else:
        print(f"[startup_import] Ошибка импорта: {info}")
