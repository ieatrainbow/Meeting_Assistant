import datetime
import os
import sys
import time

# Добавляем родительский каталог в sys.path для импорта config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import LOGS_DIR
from worker import WorkerDaemon

LOG_FILE = os.path.join(LOGS_DIR, "app.log")


def log_message(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    formatted_msg = f"[{timestamp}] {msg}"
    print(formatted_msg)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(formatted_msg + "\n")
    except Exception as e:
        print(f"Failed to write to log file: {e}")


def main():
    log_message("Starting Meeting Assistant...")

    worker = WorkerDaemon(logger_callback=log_message)
    worker.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        log_message("Stopping worker...")
        worker.stop()
        worker.join()
        log_message("Meeting Assistant stopped.")


if __name__ == "__main__":
    main()
