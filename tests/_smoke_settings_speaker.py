# -*- coding: utf-8 -*-
"""Проверка settings_store: ключ speaker_self_name сохраняется и читается.

Запуск: python tests/_smoke_settings_speaker.py
"""
import os
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "src"))
import settings_store

settings_store.SETTINGS_FILE = os.path.join(tempfile.mkdtemp(prefix="settings_smoke_"), "settings.json")

# Дефолт из config
assert settings_store.DEFAULTS["speaker_self_name"] == "Вы", settings_store.DEFAULTS
assert settings_store.load_settings()["speaker_self_name"] == "Вы"

# Сохранение кастомного имени
settings_store.save_settings(speaker_self_name="Иван")
assert settings_store.load_settings()["speaker_self_name"] == "Иван"

# Пустое значение не затирает сохранённое (save_settings игнорирует пустые)
settings_store.save_settings(speaker_self_name="  ")
assert settings_store.load_settings()["speaker_self_name"] == "Иван"

print("Settings speaker_self_name checks passed.")
