"""Хранилище пользовательских настроек (settings.json).

Хранит выбор, сделанный в UI: папку Obsidian и аудиоустройства.
Файл создаётся при первом сохранении и перекрывает значения из .env.
"""
import json
import os

from config import BASE_DIR

SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")

# Ключи и значения по умолчанию (пустая строка = брать значение из config/.env)
DEFAULTS = {
    "obsidian_path": "",
    "mic_device": "",
    "loopback_device": "",
}


def load_settings():
    """Читает settings.json; при отсутствии файла или ошибке возвращает дефолты."""
    data = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            stored = json.load(f)
        for key in DEFAULTS:
            value = stored.get(key)
            if isinstance(value, str) and value.strip():
                data[key] = value.strip()
    except FileNotFoundError:
        pass
    except (OSError, ValueError) as e:
        print(f"[Settings Warning] Could not read {SETTINGS_FILE}: {e}")
    return data


def save_settings(**kwargs):
    """Атомарно обновляет settings.json; неизвестные ключи и пустые значения игнорируются."""
    data = load_settings()
    for key, value in kwargs.items():
        if key in DEFAULTS and isinstance(value, str) and value.strip():
            data[key] = value.strip()
    tmp_path = SETTINGS_FILE + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, SETTINGS_FILE)
    except OSError as e:
        print(f"[Settings Warning] Could not write {SETTINGS_FILE}: {e}")