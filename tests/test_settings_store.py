import json
import os
import shutil
import sys
import tempfile
import unittest

# Определение корневой директории проекта
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
for path in (SRC_DIR, BASE_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

import settings_store
from settings_store import load_settings, save_settings


class TestSettingsStore(unittest.TestCase):
    """Тестирование загрузки/сохранения settings.json (выбор UI)."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.settings_file = os.path.join(self.temp_dir, "settings.json")
        self._orig_file = settings_store.SETTINGS_FILE
        settings_store.SETTINGS_FILE = self.settings_file

    def tearDown(self):
        settings_store.SETTINGS_FILE = self._orig_file
        shutil.rmtree(self.temp_dir)

    def test_missing_file_returns_defaults(self):
        """Файл ещё не создан (первый запуск) — пустые значения по умолчанию."""
        self.assertEqual(load_settings(), settings_store.DEFAULTS)

    def test_save_and_load_roundtrip(self):
        """Сохранение с кириллицей и путями Windows читается обратно без искажений."""
        save_settings(
            obsidian_path="D:\\Obsidian Vault",
            mic_device="Микрофон (USB PnP Audio Device)",
            loopback_device="Динамики (Realtek(R) Audio)",
        )
        data = load_settings()
        self.assertEqual(data["obsidian_path"], "D:\\Obsidian Vault")
        self.assertEqual(data["mic_device"], "Микрофон (USB PnP Audio Device)")
        self.assertEqual(data["loopback_device"], "Динамики (Realtek(R) Audio)")

    def test_save_merges_with_existing(self):
        """Повторное сохранение не теряет ранее записанные ключи."""
        save_settings(mic_device="Mic A")
        save_settings(obsidian_path="D:\\Vault")
        data = load_settings()
        self.assertEqual(data["mic_device"], "Mic A")
        self.assertEqual(data["obsidian_path"], "D:\\Vault")

    def test_unknown_and_non_string_values_ignored(self):
        """Чужие ключи и не-строки не ломают загрузку и вычищаются при записи."""
        with open(self.settings_file, "w", encoding="utf-8") as f:
            json.dump({"obsidian_path": 123, "mic_device": "Mic A", "custom": True}, f)
        data = load_settings()
        self.assertEqual(data["obsidian_path"], "")
        self.assertEqual(data["mic_device"], "Mic A")
        save_settings(loopback_device="Speakers")
        self.assertEqual(
            sorted(load_settings()),
            ["loopback_device", "mic_device", "obsidian_path", "ollama_model"],
        )

    def test_corrupt_file_returns_defaults(self):
        """Битый JSON не роняет запуск — возвращаются дефолты."""
        with open(self.settings_file, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(load_settings()["mic_device"], "")

    def test_save_creates_file_and_no_tmp_leftover(self):
        """Атомарная запись: settings.json создан, временный файл убран."""
        save_settings(obsidian_path="D:\\Vault")
        self.assertTrue(os.path.isfile(self.settings_file))
        self.assertFalse(os.path.exists(self.settings_file + ".tmp"))


if __name__ == "__main__":
    unittest.main()