import datetime
import gc
import json
import math
import os
import re
import shutil
import threading
import time
import wave
import requests

import numpy as np

from config import (
    INBOX_DIR,
    ARCHIVE_DIR,
    OBSIDIAN_DIR,
    AUDIO_EXTENSIONS,
    SPEAKER_SELF_NAME,
    SPEAKER_TRACK_SUFFIXES,
    TARGET_SAMPLE_RATE,
    WHISPER_MODEL_SIZE,
    WHISPER_DEVICE,
    WHISPER_COMPUTE_TYPE,
    WHISPER_LANGUAGE,
    WHISPER_INITIAL_PROMPT,
    WHISPER_BEAM_SIZE,
    WHISPER_VAD_MIN_SILENCE_MS,
    WHISPER_VAD_MAX_SPEECH_S,
    OLLAMA_URL,
    OLLAMA_MODEL,
    OLLAMA_NUM_CTX,
    OLLAMA_WARMUP_TIMEOUT,
    OLLAMA_TIMEOUT,
    SUMMARY_PROMPT_TEMPLATE,
    SUMMARY_DOMAIN_CONTEXT,
    SUMMARY_CONTEXT_MAX_CHARS,
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

# Пост-фильтр галлюцинаций Whisper: VAD пропускает куски шума/тишины как речь,
# и модель выдаёт заученные фразы (заставки YouTube, объявления и т.п.) с
# высокой уверенностью — пороги no_speech/log_prob их не отсекают. Резервные
# эвристики: чёрный список фраз + жёсткие метрики уверенности сегмента.
WHISPER_HALLUCINATION_PATTERNS = (
    "субтитры делал", "субтитры делaл", "subtitles by", "subtitle",
    "продолжение следует", "спасибо за просмотр", "благодарю за просмотр",
    "подписывайтесь на канал", "ставьте лайки", "to be continued",
    "осторожно, двери закрываются", "осторожно двери закрываются",
    "американская авиа", "американские авиалинии", "экскурсия по",
    "thanks for watching", "subscribe to",
)
# Сегмент отбрасывается, если no_speech_prob высокий, а модель неуверена
# (строже, чем встроенные пороги transcribe, которые галлюцинации пропускают)
WHISPER_SEGMENT_NO_SPEECH_STRICT = 0.5
WHISPER_SEGMENT_LOG_PROB_STRICT = -0.7

# Атрибуция говорящих по sidecar-дорожке (recorder пишет <имя>_mic.wav рядом
# с миксом). Энергия «второго» канала восстанавливается вычитанием:
# loop = 2*mix - mic. Говорящий считается единственным, если его дорожка
# громче другой более чем на SPEAKER_DOMINANCE_DB дБ в окне сегмента.
SPEAKER_DOMINANCE_DB = 3.0
# Ниже этой амплитуды (RMS) оба канала считаются тишиной — метка не ставится
SPEAKER_SILENCE_FLOOR = 1e-4

MONTH_NAMES = {
    1: "01_January",
    2: "02_February",
    3: "03_March",
    4: "04_April",
    5: "05_May",
    6: "06_June",
    7: "07_July",
    8: "08_August",
    9: "09_September",
    10: "10_October",
    11: "11_November",
    12: "12_December"
}

def sanitize_subject(text):
    """Очистка темы встречи для имени файла/папки: кириллица сохраняется,
    запрещённые для файловой системы символы заменяются на '_'."""
    cleaned = re.sub(r'[^\w-]', '_', text, flags=re.UNICODE)
    cleaned = re.sub(r'_+', '_', cleaned)
    return cleaned.strip('_')

def prepare_calendar_context(body, max_chars=SUMMARY_CONTEXT_MAX_CHARS):
    """Подготовка описания встречи из календаря для промпта саммари.

    Ссылки заменяются плейсхолдером (в описаниях календаря встречаются
    Teams/Zoom-ссылки и «простыни» приглашений — модели в саммари они не
    нужны), цепочки пустых строк сжимаются, текст усекается до max_chars,
    чтобы длинное описание не вытеснило транскрипт из контекста Ollama.
    """
    text = (body or "").strip()
    if not text:
        return ""
    text = re.sub(r"(?:https?://|www\.)\S+", "[ссылка]", text, flags=re.IGNORECASE)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + " …[усечено]"
    return text

def is_hallucination(segment):
    """Эвристика отбраковки сегментов-галлюцинаций Whisper на тишине/шуме.

    1) Текст совпадает с известной фразой-галлюцинацией (lowercase).
    2) Метрики сегмента «неречевые»: высокий no_speech_prob при низкой
       уверенности модели (avg_logprob ниже строгого порога).
    """
    text = segment.text.strip().lower()
    if not text:
        return True
    for pattern in WHISPER_HALLUCINATION_PATTERNS:
        if pattern in text:
            return True
    if (segment.no_speech_prob > WHISPER_SEGMENT_NO_SPEECH_STRICT
            and segment.avg_logprob < WHISPER_SEGMENT_LOG_PROB_STRICT):
        return True
    return False

def _find_speaker_track(audio_path):
    """Путь к sidecar-дорожке говорящего рядом с миксом, если она есть."""
    base = os.path.splitext(audio_path)[0]
    for suffix in SPEAKER_TRACK_SUFFIXES:
        candidate = base + suffix
        if os.path.exists(candidate):
            return candidate
    return None

def _load_wav_float(path):
    """Загружает WAV 16 kHz mono int16 как float32 numpy. None при ошибке."""
    try:
        with wave.open(path, 'rb') as wf:
            frames = wf.getnframes()
            raw = wf.readframes(frames)
            channels = wf.getnchannels()
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32767.0
        if channels > 1:
            samples = samples.reshape(-1, channels).mean(axis=1)
        return samples
    except Exception:
        return None

def _speaker_label(start_s, end_s, main_audio, sidecar_audio, sidecar_is_mic, self_name="Я"):
    """Метка говорящего для сегмента [start_s, end_s] по энергиям дорожек.

    main_audio — микс (mic+loopback)/2, sidecar_audio — «сырая» дорожка
    микрофона (или loopback, если микрофон не писался). Энергия второго
    канала восстанавливается: loop = 2*mix - mic. self_name — метка владельца
    микрофона. Возвращает self_name, 'Собеседник', их комбинацию или ''
    (тишина/нет данных).
    """
    if main_audio is None or sidecar_audio is None:
        return ""
    sr = TARGET_SAMPLE_RATE
    a = max(0, int(start_s * sr))
    b = min(len(main_audio), int(end_s * sr), len(sidecar_audio))
    if b <= a:
        return ""

    win_main = main_audio[a:b]
    win_side = sidecar_audio[a:b]
    # Микс из одной дорожки (recorder пишет sidecar == микс): второй канал
    # отсутствует, вся речь принадлежит владельцу sidecar-дорожки
    if np.allclose(win_main, win_side, atol=1e-4):
        if float(np.sqrt(np.mean(win_side ** 2))) < SPEAKER_SILENCE_FLOOR:
            return ""
        return self_name if sidecar_is_mic else "Собеседник"
    # Вычитание может дать отрицательный шум — обрезаем в 0
    e_side = float(np.sqrt(np.mean(win_side ** 2)))
    other = np.clip(win_main * 2.0 - win_side, 0.0, None)
    e_other = float(np.sqrt(np.mean(other ** 2)))

    if e_side < SPEAKER_SILENCE_FLOOR and e_other < SPEAKER_SILENCE_FLOOR:
        return ""
    if e_other < SPEAKER_SILENCE_FLOOR:
        return self_name if sidecar_is_mic else "Собеседник"
    if e_side < SPEAKER_SILENCE_FLOOR:
        return "Собеседник" if sidecar_is_mic else self_name

    eps = 1e-9
    ratio_db = 10.0 * math.log10((e_side + eps) / (e_other + eps))
    mic_db = ratio_db if sidecar_is_mic else -ratio_db
    if mic_db > SPEAKER_DOMINANCE_DB:
        return self_name
    if mic_db < -SPEAKER_DOMINANCE_DB:
        return "Собеседник"
    return f"{self_name} + Собеседник"

def _remove_speaker_track(audio_path):
    """Удаляет sidecar-дорожки после обработки микса (больше не нужны)."""
    base = os.path.splitext(audio_path)[0]
    for suffix in SPEAKER_TRACK_SUFFIXES:
        sidecar_path = base + suffix
        if os.path.exists(sidecar_path):
            try:
                os.remove(sidecar_path)
            except OSError as e:
                print(f"[Worker Warning] Could not remove speaker track: {e}")

class WorkerDaemon(threading.Thread):
    def __init__(self, logger_callback=None, ollama_model=None,
                 whisper_initial_prompt=None, summary_domain_context=None):
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
        # Имя владельца микрофона в транскрипте; UI перекрывает из settings.json
        self.speaker_self_name = SPEAKER_SELF_NAME
        # Подсказка Whisper и контекст домена саммари: выбор из settings.json/UI,
        # иначе — дефолты из .env
        self.whisper_initial_prompt = (whisper_initial_prompt or "").strip() or WHISPER_INITIAL_PROMPT
        self.summary_domain_context = (summary_domain_context or "").strip() or SUMMARY_DOMAIN_CONTEXT

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

    def save_to_obsidian(self, year_str, month_str, day_str, safe_folder_name, raw_subject, date_str, meta, summary, transcript):
        try:
            if not self.obsidian_dir:
                return

            # Meetings/<год>/<месяц>/<день> — заметки группируются по дате встречи
            obsidian_target_dir = os.path.join(self.obsidian_dir, "Meetings", year_str, month_str, day_str)
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
        safe_folder_name = f"{parts[0]}_{parts[1]}_{sanitize_subject(raw_subject)}" if len(parts) >= 3 else sanitize_subject(
            filename_no_ext)

        try:
            file_mtime = os.path.getmtime(audio_path)
            file_date = datetime.datetime.fromtimestamp(file_mtime)
        except Exception:
            file_date = datetime.datetime.now()

        year_str = str(file_date.year)
        month_str = MONTH_NAMES.get(file_date.month, f"{file_date.month:02d}")
        day_str = file_date.strftime("%d")
        date_formatted = file_date.strftime("%Y-%m-%d %H:%M")

        target_dir = os.path.join(ARCHIVE_DIR, year_str, month_str, safe_folder_name)
        os.makedirs(target_dir, exist_ok=True)

        self.log(f"[Worker] Processing meeting: {safe_folder_name}")

        # Sidecar-дорожка говорящего: грузим до транскрибации (для атрибуции
        # «Я / Собеседник»); нет или битая — сегменты идут без меток.
        sidecar_path = _find_speaker_track(audio_path)
        sidecar_audio = _load_wav_float(sidecar_path) if sidecar_path else None
        sidecar_is_mic = bool(sidecar_path) and sidecar_path.endswith("_mic.wav")
        main_audio = None
        if sidecar_audio is not None:
            main_audio = _load_wav_float(audio_path)
            if main_audio is None:
                self.log(f"[Worker Warning] Could not load mix for speaker attribution: {filename_full}")
            else:
                self.log(f"[Worker] Speaker attribution enabled ({os.path.basename(sidecar_path)}).")

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
            # max_speech_duration_s режет длинные «речевые» куски: сплошные
            # фрагменты ~40 c на тишине/шуме — типичное место галлюцинаций.
            segments, _ = whisper_model.transcribe(
                audio_path,
                beam_size=WHISPER_BEAM_SIZE,
                language=WHISPER_LANGUAGE,
                vad_filter=True,
                vad_parameters=dict(
                    min_silence_duration_ms=WHISPER_VAD_MIN_SILENCE_MS,
                    max_speech_duration_s=WHISPER_VAD_MAX_SPEECH_S,
                ),
                condition_on_previous_text=False,
                no_speech_threshold=WHISPER_NO_SPEECH_THRESHOLD,
                log_prob_threshold=WHISPER_LOG_PROB_THRESHOLD,
                compression_ratio_threshold=WHISPER_COMPRESSION_RATIO_THRESHOLD,
                initial_prompt=self.whisper_initial_prompt,
            )
            transcript_lines = []
            filtered_count = 0
            for s in segments:
                if is_hallucination(s):
                    filtered_count += 1
                    self.log(
                        f"[Worker] Dropped hallucination-like segment "
                        f"[{s.start:.1f}s - {s.end:.1f}s] "
                        f"(no_speech={s.no_speech_prob:.2f}, logprob={s.avg_logprob:.2f}): "
                        f"{s.text.strip()!r}"
                    )
                    continue
                label = _speaker_label(
                    s.start, s.end, main_audio, sidecar_audio,
                    sidecar_is_mic, self_name=self.speaker_self_name
                )
                prefix = f"{label}: " if label else ""
                transcript_lines.append(f"[{s.start:.1f}s - {s.end:.1f}s] {prefix}{s.text}")
            if filtered_count:
                self.log(f"[Worker] Filtered {filtered_count} hallucination-like segment(s).")
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
                _remove_speaker_track(audio_path)
            else:
                # Sidecar оставляем — понадобится на следующей попытке
                self.current_task = None
                time.sleep(5)
                return
        else:
            # Транскрибация удалась: sidecar-дорожка больше не нужна
            _remove_speaker_track(audio_path)

        # 2. Генерация Саммари Ollama
        if not full_transcript.strip() and summary is None:
            # Речи нет (тишина/шум). НЕ выходим из process_file: файл должен
            # уйти в архив, иначе он останется в inbox и будет обрабатываться
            # по кругу (бесконечный цикл обработки).
            summary = "Речь в записи не обнаружена."
            self.log("[Worker Warning] No transcript available; archiving without summary.")

        if summary is None:
            self.log(f"[Worker] Generating summary via Ollama ({self.ollama_model})...")

            context_body = prepare_calendar_context(meta.get("body", ""))
            if context_body:
                prompt_context = (
                    "\nОписание встречи из календаря (справочная информация: "
                    "используй только для понимания контекста, НЕ добавляй в "
                    "саммари факты, которые не прозвучали во встрече):\n"
                    f"{context_body}\n"
                )
            else:
                prompt_context = ""

            prompt = SUMMARY_PROMPT_TEMPLATE.format(
                subject=raw_subject,
                context=prompt_context,
                transcript=full_transcript,
            )
            # Общая тема встреч (контекст домена) — первой строкой промпта
            if self.summary_domain_context:
                prompt = f"Общий контекст: {self.summary_domain_context}.\n" + prompt

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
            day_str=day_str,
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

                    # Осиротевшие sidecar-дорожки (микс уже удалён/обработан) — в мусор
                    for f in files:
                        if f.endswith(tuple(SPEAKER_TRACK_SUFFIXES)):
                            base = os.path.splitext(f)[0]
                            if not any(os.path.exists(os.path.join(INBOX_DIR, base + ext))
                                       for ext in AUDIO_EXTENSIONS):
                                try:
                                    os.remove(os.path.join(INBOX_DIR, f))
                                    self.log(f"[Cleanup] Removed orphaned speaker track: {f}")
                                except OSError as e:
                                    self.log(f"[Cleanup Error] {f}: {e}")

                    # Sidecar-дорожки в очередь на транскрибацию не попадают
                    audio_files = [
                        os.path.join(INBOX_DIR, f) for f in files
                        if f.lower().endswith(tuple(AUDIO_EXTENSIONS))
                           and not f.endswith('.tmp')
                           and not f.endswith(tuple(SPEAKER_TRACK_SUFFIXES))
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
