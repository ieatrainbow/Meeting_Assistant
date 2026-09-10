import os
import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (os.path.join(BASE_DIR, "src"), BASE_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from worker import WorkerDaemon

w = WorkerDaemon(logger_callback=print)
print("DEFAULT:", w.ollama_model)
print("MODELS:", w.fetch_available_models())

# Переключение модели без реального сервера
import time
from unittest.mock import patch

with patch("worker.requests.post") as mock_post, patch("worker.requests.get") as mock_get:
    mock_post.return_value.status_code = 200
    mock_get.return_value.status_code = 200
    mock_get.return_value.json.return_value = {"models": [{"name": "a"}, {"name": "b"}]}

    w2 = WorkerDaemon(logger_callback=print, ollama_model="a")
    assert w2.ollama_model == "a"
    w2.set_ollama_model("b")
    time.sleep(0.5)  # ждём фоновый перезагрев
    assert w2.ollama_model == "b"
    assert w2.model_status == "ready"
    payloads = [c.kwargs["json"]["model"] for c in mock_post.call_args_list]
    print("POST PAYLOADS:", payloads)
    assert payloads == ["a", "b"]  # сначала выгрузка 'a', затем прогрев 'b'
    print("SWITCH OK")

# Модуль UI должен как минимум импортироваться
import ui  # noqa: F401

print("UI IMPORT OK")

