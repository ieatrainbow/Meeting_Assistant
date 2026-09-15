"""Хранилище пользовательских настроек (settings.json).

Хранит выбор, сделанный в UI: папку Obsidian, аудиоустройства и модель Ollama.
Файл создаётся при первом сохранении и перекрывает значения из .env.
"""
import json
import os

from config import BASE_DIR, SPEAKER_SELF_NAME

SETTINGS_FILE = os.path.join(BASE_DIR, "settings.json")

# Ключи и значения по умолчанию (пустая строка = брать значение из config/.env)
DEFAULTS = {
    "obsidian_path": "",
    "mic_device": "",
    "loopback_device": "",
    "ollama_model": "",
    "speaker_self_name": SPEAKER_SELF_NAME,
    "whisper_initial_prompt": "",
    "summary_domain_context": "",
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
    """Атомарно обновляет settings.json.

    Пустые значения по умолчанию игнорируются (не затирают сохранённое).
    Чтобы сбросить настройку к дефолту (пустая строка = значение из
    config/.env), перечислите её ключи в clear_keys.
    """
    clear = set(kwargs.pop("clear_keys", None) or ())
    data = load_settings()
    for key, value in kwargs.items():
        if key in DEFAULTS and isinstance(value, str) and value.strip():
            data[key] = value.strip()
    for key in clear:
        if key in DEFAULTS:
            data[key] = ""
    tmp_path = SETTINGS_FILE + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, SETTINGS_FILE)
    except OSError as e:
        print(f"[Settings Warning] Could not write {SETTINGS_FILE}: {e}")