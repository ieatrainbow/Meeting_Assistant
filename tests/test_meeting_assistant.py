import os
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

import requests

# Определение корневой директории проекта
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(BASE_DIR, "src")
for path in (SRC_DIR, BASE_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

import config
from worker import transliterate, WorkerDaemon
from recorder import AudioRecorder


class TestTransliteration(unittest.TestCase):
    """Тестирование корректности транслитерации для имен файлов и папок."""

    def test_cyrillic_transliteration(self):
        """Проверка перевода кириллицы в латиницу."""
        self.assertEqual(transliterate("Обсуждение проекта"), "Obsuzhdenie_proekta")

    def test_special_characters(self):
        """Проверка очистки спецсимволов и лишних подчеркиваний."""
        self.assertEqual(transliterate("QA отдел / Sync!@#"), "QA_otdel_Sync")

    def test_mixed_text(self):
        """Проверка обработки смешанного англо-русского текста с дефисами."""
        self.assertEqual(transliterate("Meeting 123 - Важно"), "Meeting_123_-_Vazhno")


class TestAudioRecorder(unittest.TestCase):
    """Тестирование логики формирования файлов записи FFmpeg."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir)

    @patch("recorder.INBOX_DIR", tempfile.mkdtemp())
    @patch.object(AudioRecorder, "_record_loop", new=lambda self, *a, **k: None)
    def test_start_recording_creates_paths(self):
        """Проверка корректности формирования путей для .wav и .tmp файлов."""
        recorder = AudioRecorder(logger_callback=lambda x: None)
        recorder.start(prefix="Тест_Встреча")

        self.assertTrue(recorder.is_recording)
        self.assertIsNotNone(recorder.current_file)
        self.assertTrue(recorder.current_file.endswith(".wav"))
        self.assertTrue(recorder.temp_file.endswith(".tmp"))

    @patch("subprocess.Popen")
    def test_prevent_double_recording(self, mock_popen):
        """Проверка блокировки повторного запуска уже активной записи."""
        recorder = AudioRecorder(logger_callback=lambda x: None)
        recorder.is_recording = True
        recorder.current_file = "active.wav"

        result = recorder.start(prefix="New_Meeting")
        self.assertEqual(result, "active.wav")
        mock_popen.assert_not_called()


class TestWorkerLogic(unittest.TestCase):
    """Тестирование бизнес-логики фонового воркера."""

    def setUp(self):
        self.temp_obsidian = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_obsidian)

    def test_save_to_obsidian_structure(self):
        """Проверка структуры и содержания создаваемой заметки в Obsidian."""
        with patch("worker.OBSIDIAN_DIR", self.temp_obsidian):
            worker = WorkerDaemon(logger_callback=lambda x: None)

            meta = {
                "organizer": "Иван Иванов",
                "attendees": ["Петр Петров", "Сидор Сидоров"],
                "body": "Повестка: обсудить архитектуру."
            }

            worker.save_to_obsidian(
                year_str="2026",
                month_str="09_September",
                day_str="10",
                safe_folder_name="2026-05-10_Test_Meeting",
                raw_subject="Test Meeting",
                date_str="2026-05-10 10:00",
                meta=meta,
                summary="• Ключевое решение принято.",
                transcript="[0.0s - 5.0s] Всем привет."
            )

            expected_path = os.path.join(
                self.temp_obsidian, "Meetings", "2026", "09_September", "10", "2026-05-10_Test_Meeting.md"
            )

            self.assertTrue(os.path.exists(expected_path))

            with open(expected_path, "r", encoding="utf-8") as f:
                content = f.read()

            self.assertIn("type: meeting", content)
            self.assertIn("# Meeting: Test Meeting", content)
            self.assertIn("Иван Иванов", content)
            self.assertIn("- Петр Петров", content)
            self.assertIn("• Ключевое решение принято.", content)
    
    def test_ollama_error_handling(self):
        """Проверка, что ошибка сети при прогреве Ollama не приводит к исключению."""
        with patch("requests.post", side_effect=requests.exceptions.ConnectionError):
            worker = WorkerDaemon(logger_callback=lambda x: None)
            worker.warmup_ollama()  # не бросает исключение
    
    def test_cleanup_old_audio(self):
        """Проверка удаления из архива аудиофайлов старше ARCHIVE_RETENTION_DAYS."""
        temp_dir = tempfile.mkdtemp()
        try:
            old_file = os.path.join(temp_dir, "old_meeting.wav")
            fresh_file = os.path.join(temp_dir, "fresh_meeting.wav")
            keep_txt = os.path.join(temp_dir, "notes.txt")  # не аудио — не удаляется
            for path in (old_file, fresh_file, keep_txt):
                with open(path, "w"):
                    pass

            # old_meeting.wav делаем «старше» срока хранения
            old_stamp = time.time() - (config.ARCHIVE_RETENTION_DAYS + 1) * 24 * 3600
            os.utime(old_file, (old_stamp, old_stamp))

            with patch("worker.ARCHIVE_DIR", temp_dir):
                worker = WorkerDaemon(logger_callback=lambda x: None)
                worker.cleanup_old_audio()

            self.assertFalse(os.path.exists(old_file))
            self.assertTrue(os.path.exists(fresh_file))
            self.assertTrue(os.path.exists(keep_txt))
        finally:
            shutil.rmtree(temp_dir)


class TestOutlookIntegration(unittest.TestCase):
    """Тестирование обработки ошибок MAPI клиента Outlook."""

    @patch("win32com.client.Dispatch")
    def test_outlook_handle_com_error(self, mock_dispatch):
        """Проверка корректного фоллбека при отсутствии Outlook в системе."""
        mock_dispatch.side_effect = Exception("COM Automation Error")

        from outlook_client import get_current_or_next_meeting_details
        result = get_current_or_next_meeting_details()

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
