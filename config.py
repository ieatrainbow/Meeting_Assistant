import os

from dotenv import load_dotenv

load_dotenv()

os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# ---------------------------------------------------------------------------
# Каталоги
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

INBOX_DIR = os.path.join(BASE_DIR, "inbox")
ARCHIVE_DIR = os.path.join(BASE_DIR, "archive")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

OBSIDIAN_DIR = os.getenv("OBSIDIAN_DIR", os.path.join(BASE_DIR, "obsidian_output"))

# Проверка обязательных каталогов
for folder in [INBOX_DIR, ARCHIVE_DIR, LOGS_DIR]:
    if not os.path.exists(folder):
        os.makedirs(folder)

if not os.path.exists(OBSIDIAN_DIR):
    print(f"[Config Warning] Obsidian vault missing: {OBSIDIAN_DIR}")

# ---------------------------------------------------------------------------
# Запись аудио (recorder.py)
# ---------------------------------------------------------------------------
# Частота дискретизации итогового файла
TARGET_SAMPLE_RATE = int(os.getenv("TARGET_SAMPLE_RATE", "16000"))

# Расширения обрабатываемых аудиофайлов (через запятую в .env)
AUDIO_EXTENSIONS = tuple(
    "." + ext.strip().lower().lstrip(".")
    for ext in os.getenv("AUDIO_EXTENSIONS", ".wav,.mp3,.m4a").split(",")
    if ext.strip()
)

# dshow-имена устройств по умолчанию (UI позволяет выбрать другие)
MIC_DEVICE = os.getenv("MIC_DEVICE", "audio=Микрофон (USB PnP Audio Device)")
STEREO_MIX_DEVICE = os.getenv("STEREO_MIX_DEVICE", "audio=Стерео микшер (Realtek(R) Audio)")

# ---------------------------------------------------------------------------
# Транскрибация (faster-whisper)
# ---------------------------------------------------------------------------
WHISPER_MODEL_SIZE = os.getenv("WHISPER_MODEL_SIZE", "large-v3")
WHISPER_DEVICE = os.getenv("WHISPER_DEVICE", "cuda")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "float16")

WHISPER_LANGUAGE = os.getenv("WHISPER_LANGUAGE", "ru")
# Подсказка модели для снижения галлюцинаций на тишине
WHISPER_INITIAL_PROMPT = os.getenv("WHISPER_INITIAL_PROMPT", "Запись встречи на русском языке.")
WHISPER_BEAM_SIZE = int(os.getenv("WHISPER_BEAM_SIZE", "5"))
# VAD (Silero): отрезание тишины/шума — main источник галлюцинаций
WHISPER_VAD_MIN_SILENCE_MS = int(os.getenv("WHISPER_VAD_MIN_SILENCE_MS", "500"))

# ---------------------------------------------------------------------------
# Саммаризация (Ollama)
# ---------------------------------------------------------------------------
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "gemma4-64k-q4:latest")
# Размер контекста модели (закрепляется в VRAM через keep_alive=-1)
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "8192"))
# Таймауты HTTP-запросов, сек
OLLAMA_WARMUP_TIMEOUT = int(os.getenv("OLLAMA_WARMUP_TIMEOUT", "60"))
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "300"))

# Шаблон промпта саммари. Плейсхолдеры: {subject}, {context}, {transcript}.
# При переопределении в .env не используйте одиночные '{' вне плейсхолдеров.
SUMMARY_PROMPT_TEMPLATE = os.getenv(
    "SUMMARY_PROMPT_TEMPLATE",
    'Ниже представлена расшифровка встречи: "{subject}".{context}\n'
    "Сделай краткое саммари, ключевые тезисы и список поручений (Action Items).\n\n"
    "Текст:\n{transcript}",
)

# ---------------------------------------------------------------------------
# Фоновый воркер
# ---------------------------------------------------------------------------
# Интервал опроса inbox, сек
WORKER_POLL_INTERVAL = int(os.getenv("WORKER_POLL_INTERVAL", "2"))
# Периодичность очистки старого аудио в archive, часы
WORKER_CLEANUP_INTERVAL_HOURS = int(os.getenv("WORKER_CLEANUP_INTERVAL_HOURS", "12"))
# Сколько дней хранить аудио в archive (0 — не удалять)
ARCHIVE_RETENTION_DAYS = int(os.getenv("ARCHIVE_RETENTION_DAYS", "7"))
# Попыток транскрибации файла, после которых он архивируется с ошибкой
MAX_TRANSCRIBE_RETRIES = int(os.getenv("MAX_TRANSCRIBE_RETRIES", "3"))

# ---------------------------------------------------------------------------
# Календарь Outlook
# ---------------------------------------------------------------------------
# Окно поиска встреч: начавшиеся не ранее N минут назад (идущие сейчас ловятся
# dtend-условием независимо от давности старта) или ближайшие N часов
OUTLOOK_LOOKBACK_MINUTES = int(os.getenv("OUTLOOK_LOOKBACK_MINUTES", "30"))
OUTLOOK_LOOKAHEAD_HOURS = int(os.getenv("OUTLOOK_LOOKAHEAD_HOURS", "12"))
