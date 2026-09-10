import datetime
import os
import queue
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import LOGS_DIR
from recorder import AudioRecorder
from worker import WorkerDaemon
from ui import AppUI
from ui_events import to_ui_event

LOG_FILE = os.path.join(LOGS_DIR, "app.log")
def _ensure_cuda_dll_paths():
    """Добавляет пути CUDA/сопутствующих DLL (conda, pip nvidia-пакеты) в PATH процесса.

    Нужно для faster-whisper (CTranslate2) при запуске вне conda-окружения:
    без этого загрузка модели падает с 'cublas64_12.dll is not found'.
    """
    candidates = []

    # Python-интерпретатор лежит в conda-окружении
    exe_dir = os.path.dirname(sys.executable)
    candidates += [
        os.path.join(exe_dir, "Library", "bin"),
        exe_dir,
    ]

    # pip-пакеты nvidia-* (torch с CUDA, cudnn и т.п.)
    for pkg_dir in sys.path:
        if pkg_dir and os.path.basename(pkg_dir) == "site-packages":
            nvidia = os.path.join(os.path.dirname(pkg_dir), "nvidia")
            if os.path.isdir(nvidia):
                for sub in ("cublas", "cudnn", "cuda_runtime"):
                    bin_dir = os.path.join(nvidia, sub, "bin")
                    if os.path.isdir(bin_dir):
                        candidates.append(bin_dir)

    for path in candidates:
        if os.path.isdir(path) and path not in os.environ.get("PATH", ""):
            os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")


_ensure_cuda_dll_paths()

log_queue = queue.Queue()


def log_message(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] {msg}"

    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted_msg + "\n")
    except Exception:
        pass

    # В UI — только короткие понятные события; полный текст остаётся в app.log.
    ui_text = to_ui_event(msg)
    if ui_text is not None:
        ui_time = datetime.datetime.now().strftime("%H:%M:%S")
        log_queue.put(f"[{ui_time}] {ui_text}")


class SafeStreamWriter:
    def __init__(self, prefix="[SYS]"):
        self.prefix = prefix
        self._buffer = ""

    def write(self, message):
        if not message:
            return
        self._buffer += message
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            line = line.strip()
            if line:
                log_message(f"{self.prefix} {line}")

    def flush(self):
        if self._buffer.strip():
            log_message(f"{self.prefix} {self._buffer.strip()}")
            self._buffer = ""


def main():
    sys.stdout = SafeStreamWriter("[STDOUT]")
    sys.stderr = SafeStreamWriter("[STDERR]")

    log_message("Starting Meeting Assistant...")

    recorder = AudioRecorder(logger_callback=log_message)
    worker = WorkerDaemon(logger_callback=log_message)
    worker.start()

    # Передаем worker в интерфейс
    app = AppUI(recorder=recorder, worker=worker, log_queue=log_queue, logger_callback=log_message)

    try:
        app.mainloop()
    finally:
        log_message("Shutting down...")
        worker.stop()
        log_message("Meeting Assistant stopped.")


if __name__ == "__main__":
    main()
