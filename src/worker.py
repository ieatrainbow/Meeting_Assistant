import datetime
import gc
import json
import os
import re
import shutil
import threading
import time
import requests

from config import (
    INBOX_DIR,
    ARCHIVE_DIR,
    OBSIDIAN_DIR,
    AUDIO_EXTENSIONS,
    WHISPER_MODEL_SIZE,
    WHISPER_DEVICE,
    WHISPER_COMPUTE_TYPE,
    WHISPER_LANGUAGE,
    WHISPER_INITIAL_PROMPT,
    WHISPER_BEAM_SIZE,
    WHISPER_VAD_MIN_SILENCE_MS,
    OLLAMA_URL,
    OLLAMA_MODEL,
    OLLAMA_NUM_CTX,
    OLLAMA_WARMUP_TIMEOUT,
    OLLAMA_TIMEOUT,
    SUMMARY_PROMPT_TEMPLATE,
    WORKER_POLL_INTERVAL,
    WORKER_CLEANUP_INTERVAL_HOURS,
    ARCHIVE_RETENTION_DAYS,
    MAX_TRANSCRIBE_RETRIES,
)

# Пороги сегментации Whisper: подобраны под записи встреч
# (см. комментарии при вызове transcribe), отдельно не конфигурируются.
WHISPER_NO_SPEECH_THRESHOLD = 0.6
WHISPER_LOG_PROB_THRESHOLD = -1.0
WHISPER_COMPRESSION_RATIO_THRESHOLD = 2.4

MONTH_NAMES = {
    1: "01_Jan",
    2: "02_Feb",
    3: "03_Mar",
    4: "04_Apr",
    5: "05_May",
    6: "06_Jun",
    7: "07_Jul",
    8: "08_Aug",
    9: "09_Sep",
    10: "10_Oct",
    11: "11_Nov",
    12: "12_Dec"
}

def transliterate(text):
    cyrillic_to_latin = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo', 'ж': 'zh',
        'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n', 'о': 'o',
        'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f', 'х': 'kh', 'ц': 'ts',
        'ч': 'ch', 'ш': 'sh', 'щ': 'shch', 'ъ': '', 'ы': 'y', 'ь': '', 'э': 'e', 'ю': 'yu',
        'я': 'ya',
        'А': 'A', 'Б': 'B', 'В': 'V', 'Г': 'G', 'Д': 'D', 'Е': 'E', 'Ё': 'Yo', 'Ж': 'Zh',
        'З': 'Z', 'И': 'I', 'Й': 'Y', 'К': 'K', 'Л': 'L', 'М': 'M', 'Н': 'N', 'О': 'O',
        'П': 'P', 'Р': 'R', 'С': 'S', 'Т': 'T', 'У': 'U', 'Ф': 'F', 'Х': 'Kh', 'Ц': 'Ts',
        'Ч': 'Ch', 'Ш': 'Sh', 'Щ': 'Shch', 'Ъ': '', 'Ы': 'Y', 'Ь': '', 'Э': 'E', 'Ю': 'Yu',
        'Я': 'Ya'
    }
    transliterated_chars = [cyrillic_to_latin.get(char, char) for char in text]
    transliterated_text = "".join(transliterated_chars)
    cleaned = re.sub(r'[^a-zA-Z0-9_-]', '_', transliterated_text)
    cleaned = re.sub(r'_+', '_', cleaned)
    return cleaned.strip('_')

class WorkerDaemon(threading.Thread):
    def __init__(self, logger_callback=None, ollama_model=None):
        super().__init__(daemon=True)
        self.log = logger_callback or print
        self.running = True
        self.current_task = None
        self.queue_files = []
        self.obsidian_dir = OBSIDIAN_DIR
        # Модель саммаризации: выбор из settings.json/UI, иначе — дефолт из .env
        self.ollama_model = ollama_model or OLLAMA_MODEL
        self.model_status = "loading"  # loading | ready | unavailable
        self._fail_counts = {}  # попытки обработки файла (защита от зацикливания)

    def warmup_ollama(self):
        self.log(f"[Worker] Preloading Ollama model ({self.ollama_model}) into VRAM...")
        try:
            requests.post(
                OLLAMA_URL,
                json={
                    "model": self.ollama_model,
                    "prompt": "",
                    "keep_alive": -1,
                    "options": {"num_ctx": OLLAMA_NUM_CTX}
                },
                timeout=OLLAMA_WARMUP_TIMEOUT
            )
            self.model_status = "ready"
            self.log("[Worker] Ollama model preloaded and pinned to VRAM.")
        except Exception as e:
            self.model_status = "unavailable"
            self.log(f"[Worker Warning] Failed to preload Ollama: {e}")

    def fetch_available_models(self):
        """Имена моделей, установленных в Ollama (GET /api/tags).

        Возвращает [] при недоступности сервера — UI покажет предупреждение.
        """
        # OLLAMA_URL указывает на /api/generate — список моделей лежит рядом, в /api/tags
        tags_url = OLLAMA_URL.split("/api/")[0] + "/api/tags"
        try:
            response = requests.get(tags_url, timeout=5)
            if response.status_code == 200:
                return [m["name"] for m in response.json().get("models", []) if m.get("name")]
            self.log(f"[Worker Warning] Ollama tags HTTP {response.status_code}")
        except Exception as e:
            self.log(f"[Worker Warning] Could not list Ollama models: {e}")
        return []

    def set_ollama_model(self, model_name):
        """Меняет модель саммаризации и в фоне перезагревает её в VRAM."""
        model_name = (model_name or "").strip()
        if not model_name or model_name == self.ollama_model:
            return
        previous_model = self.ollama_model
        self.ollama_model = model_name
        self.model_status = "loading"
        self.log(f"[Worker] Ollama model switched to {model_name}; re-warming...")
        threading.Thread(target=self._rewarm_model, args=(previous_model,), daemon=True).start()

    def _rewarm_model(self, previous_model):
        # Выгружаем прежнюю модель из VRAM (keep_alive=-1 закреплял её навсегда),
        # чтобы не держать в памяти две модели одновременно.
        try:
            requests.post(
                OLLAMA_URL,
                json={"model": previous_model, "prompt": "", "keep_alive": 0},
                timeout=OLLAMA_WARMUP_TIMEOUT
            )
        except Exception:
            pass
        self.warmup_ollama()

    def save_to_obsidian(self, year_str, month_str, safe_folder_name, raw_subject, date_str, meta, summary, transcript):
        try:
            if not self.obsidian_dir:
                return

            obsidian_target_dir = os.path.join(self.obsidian_dir, year_str, month_str)
            os.makedirs(obsidian_target_dir, exist_ok=True)

            md_filename = f"{safe_folder_name}.md"
            md_path = os.path.join(obsidian_target_dir, md_filename)

            organizer = meta.get("organizer", "")
            attendees = meta.get("attendees", [])
            body = meta.get("body", "")

            attendees_str = "\n".join([f"  - {a}" for a in attendees]) if attendees else "  - Не указаны"
            body_str = f"> {body.replace(chr(10), chr(10) + '> ')}" if body else "Отсутствует"

            md_content = (
                f"---\n"
                f"date: {date_str}\n"
                f"type: meeting\n"
                f"tags:\n"
                f"  - meetings\n"
                f"---\n\n"
                f"# Meeting: {raw_subject}\n\n"
                f"## 📌 Информация о встрече\n"
                f"- **Дата:** {date_str}\n"
                f"- **Организатор:** {organizer if organizer else 'Не указан'}\n"
                f"- **Участники:**\n{attendees_str}\n\n"
                f"### 📝 Описание из календаря:\n"
                f"{body_str}\n\n"
                f"---\n\n"
                f"## 📋 Summary & Action Items\n"
                f"{summary}\n\n"
                f"---\n\n"
                f"## 🎙️ Full Transcript\n"
                f"{transcript}\n"
            )

            with open(md_path, "w", encoding="utf-8") as f:
                f.write(md_content)

            self.log(f"[Worker] Note saved to Obsidian: {safe_folder_name}.md")

        except Exception as e:
            self.log(f"[Worker Error] Obsidian error: {e}")

    def process_file(self, audio_path):
        if not self.running:
            return

        filename_full = os.path.basename(audio_path)
        filename_no_ext = os.path.splitext(filename_full)[0]

        self.current_task = filename_no_ext

        meta_json_path = f"{audio_path}.json"
        meta = {}
        if os.path.exists(meta_json_path):
            try:
                with open(meta_json_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception as e:
                self.log(f"[Worker Warning] Could not read metadata JSON: {e}")

        parts = filename_no_ext.split("_", 2)
        raw_subject = meta.get("subject") or (parts[2] if len(parts) >= 3 else "Meeting")
        safe_folder_name = f"{parts[0]}_{parts[1]}_{transliterate(raw_subject)}" if len(parts) >= 3 else transliterate(
            filename_no_ext)

        try:
            file_mtime = os.path.getmtime(audio_path)
            file_date = datetime.datetime.fromtimestamp(file_mtime)
        except Exception:
            file_date = datetime.datetime.now()

        year_str = str(file_date.year)
        month_str = MONTH_NAMES.get(file_date.month, f"{file_date.month:02d}")
        date_formatted = file_date.strftime("%Y-%m-%d %H:%M")

        target_dir = os.path.join(ARCHIVE_DIR, year_str, month_str, safe_folder_name)
        os.makedirs(target_dir, exist_ok=True)

        self.log(f"[Worker] Processing meeting: {safe_folder_name}")

        # 1. Транскрибация Whisper
        full_transcript = ""
        summary = None
        try:
            from faster_whisper import WhisperModel
            self.log(f"[Worker] Loading Whisper ({WHISPER_MODEL_SIZE})...")
            whisper_model = WhisperModel(
                WHISPER_MODEL_SIZE,
                device=WHISPER_DEVICE,
                compute_type=WHISPER_COMPUTE_TYPE
            )

            # VAD (Silero) отрезает тишину/шум — main источник галлюцинаций;
            # condition_on_previous_text=False не даёт модели «зацикливаться»
            # и тащить выдуманный контекст в следующие сегменты.
            segments, _ = whisper_model.transcribe(
                audio_path,
                beam_size=WHISPER_BEAM_SIZE,
                language=WHISPER_LANGUAGE,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=WHISPER_VAD_MIN_SILENCE_MS),
                condition_on_previous_text=False,
                no_speech_threshold=WHISPER_NO_SPEECH_THRESHOLD,
                log_prob_threshold=WHISPER_LOG_PROB_THRESHOLD,
                compression_ratio_threshold=WHISPER_COMPRESSION_RATIO_THRESHOLD,
                initial_prompt=WHISPER_INITIAL_PROMPT,
            )
            transcript_lines = [f"[{s.start:.1f}s - {s.end:.1f}s] {s.text}" for s in segments]
            full_transcript = "\n".join(transcript_lines)

            self.log(f"[Worker] Transcription complete ({len(full_transcript)} chars).")

            del whisper_model
            gc.collect()
            try:
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass

        except Exception as e:
            self.log(f"[Worker Error] Transcription failed: {e}")
            key = os.path.basename(audio_path)
            self._fail_counts[key] = self._fail_counts.get(key, 0) + 1
            if self._fail_counts[key] >= MAX_TRANSCRIBE_RETRIES:
                # Сдаёмся после N попыток: архивируем файл, иначе он
                # застрянет в inbox и обработка зациклится.
                self.log(f"[Worker Warning] Giving up after {MAX_TRANSCRIBE_RETRIES} attempts; archiving as failed.")
                full_transcript = ""
                summary = "Ошибка транскрибации."
            else:
                self.current_task = None
                time.sleep(5)
                return

        # 2. Генерация Саммари Ollama
        if not full_transcript.strip() and summary is None:
            # Речи нет (тишина/шум). НЕ выходим из process_file: файл должен
            # уйти в архив, иначе он останется в inbox и будет обрабатываться
            # по кругу (бесконечный цикл обработки).
            summary = "Речь в записи не обнаружена."
            self.log("[Worker Warning] No transcript available; archiving without summary.")

        if summary is None:
            self.log(f"[Worker] Generating summary via Ollama ({self.ollama_model})...")

            context_body = meta.get("body", "").strip()
            prompt_context = f"\nОписание встречи из календаря:\n{context_body}\n" if context_body else ""

            prompt = SUMMARY_PROMPT_TEMPLATE.format(
                subject=raw_subject,
                context=prompt_context,
                transcript=full_transcript,
            )

            try:
                response = requests.post(
                    OLLAMA_URL,
                    json={
                        "model": self.ollama_model,
                        "prompt": prompt,
                        "stream": False,
                        "keep_alive": -1,
                        "options": {"num_ctx": OLLAMA_NUM_CTX}
                    },
                    timeout=OLLAMA_TIMEOUT
                )
                if response.status_code == 200:
                    summary = response.json().get("response", "Empty response from Ollama.")
                else:
                    summary = f"Ollama HTTP Error {response.status_code}: {response.text}"
            except Exception as e:
                self.log(f"[Worker Warning] Ollama failed: {e}")
                time.sleep(1)

        # 3. Сохранение локально
        try:
            with open(os.path.join(target_dir, "transcript.txt"), "w", encoding="utf-8") as f:
                f.write(full_transcript)
            with open(os.path.join(target_dir, "summary.txt"), "w", encoding="utf-8") as f:
                f.write(summary)

            archived_audio_path = os.path.join(target_dir, filename_full)
            if os.path.exists(archived_audio_path):
                os.remove(archived_audio_path)
            shutil.move(audio_path, archived_audio_path)

            if os.path.exists(meta_json_path):
                os.remove(meta_json_path)

            self.log(f"[Worker] Successfully processed: {safe_folder_name}")

        except Exception as e:
            self.log(f"[Worker Error] Archiving failed: {e}")

        # 4. Сохранение в Obsidian
        self.save_to_obsidian(
            year_str=year_str,
            month_str=month_str,
            safe_folder_name=safe_folder_name,
            raw_subject=raw_subject,
            date_str=date_formatted,
            meta=meta,
            summary=summary,
            transcript=full_transcript
        )

        self.current_task = None

    def cleanup_old_audio(self):
        if not os.path.exists(ARCHIVE_DIR) or ARCHIVE_RETENTION_DAYS <= 0:
            return

        now = time.time()
        retention_period = ARCHIVE_RETENTION_DAYS * 24 * 3600

        for root, _, files in os.walk(ARCHIVE_DIR):
            for file in files:
                if file.lower().endswith(tuple(AUDIO_EXTENSIONS)):
                    file_path = os.path.join(root, file)
                    try:
                        file_mtime = os.path.getmtime(file_path)
                        if (now - file_mtime) > retention_period:
                            os.remove(file_path)
                            self.log(f"[Cleanup] Removed old audio (>{ARCHIVE_RETENTION_DAYS} days): {os.path.basename(file_path)}")
                    except Exception as e:
                        self.log(f"[Cleanup Error] Could not delete {file}: {e}")

    def run(self):
        self.log("[Worker] Background worker started.")
        self.warmup_ollama()
        last_cleanup = 0

        while self.running:
            try:
                if time.time() - last_cleanup > WORKER_CLEANUP_INTERVAL_HOURS * 3600:
                    self.cleanup_old_audio()
                    last_cleanup = time.time()

                if os.path.exists(INBOX_DIR):
                    files = os.listdir(INBOX_DIR)

                    audio_files = [
                        os.path.join(INBOX_DIR, f) for f in files
                        if f.lower().endswith(tuple(AUDIO_EXTENSIONS))
                           and not f.endswith('.tmp')
                    ]

                    audio_files.sort(key=lambda x: os.path.getmtime(x))
                    self.queue_files = [os.path.basename(f) for f in audio_files]

                    if audio_files:
                        self.process_file(audio_files[0])

            except Exception as e:
                self.log(f"[Worker Error] Loop error: {e}")
                self.current_task = None

            time.sleep(WORKER_POLL_INTERVAL)

    def restart(self):
        self.stop()
        time.sleep(1)
        self.log("[Worker] Restarting background worker...")
        self.running = True
        self.warmup_ollama()
        self.run()

    def stop(self):
        self.running = False
