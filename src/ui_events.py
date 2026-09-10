# -*- coding: utf-8 -*-
"""Преобразование технических лог-сообщений в короткие события для UI.

logs/app.log по-прежнему содержит полные сообщения (для отладки);
в интерфейс попадает только результат to_ui_event().
None означает: событие служебное и в UI не показывается.
"""

# (префикс полного сообщения, короткая строка для UI).
# '{rest}' подставляет остаток строки после префикса (имя файла и т.п.).
_UI_EVENT_RULES = [
    # Запись
    ("[Recorder] Recording started", "Запись начата"),
    ("[Recorder] Recording saved: ", "Запись сохранена: {rest}"),
    ("[Recorder Warning] No audio captured", "Запись пуста — файл пропущен"),
    ("[Recorder Warning] No microphone device selected", "Микрофон не выбран — запись не начата"),
    ("[Recorder Warning] Microphone not found: ", "Микрофон не найден: {rest}"),
    ("[Recorder Warning] No WASAPI loopback devices", "Не найдено устройство системного звука"),
    ("[Recorder Warning] Output device not found", "Системный звук: используется устройство по умолчанию"),
    ("[Recorder Error] Capture failed", "Ошибка записи"),
    ("[Recorder Error] Failed to finalize file", "Ошибка сохранения записи"),
    # Обработка
    ("[Worker] Processing meeting: ", "Обработка: {rest}"),
    ("[Worker] Loading Whisper", "Расшифровка аудио…"),
    ("[Worker] Transcription complete", "Расшифровка завершена"),
    ("[Worker Error] Transcription failed", "Ошибка расшифровки"),
    ("[Worker Warning] Giving up after", "Расшифровка не удалась — запись помечена как ошибочная"),
    ("[Worker Warning] No transcript available", "Речь в записи не обнаружена"),
    ("[Worker] Generating summary", "Создание саммари…"),
    ("[Worker Warning] Ollama failed", "Ошибка саммари"),
    ("[Worker] Note saved to Obsidian: ", "Заметка сохранена в Obsidian"),
    ("[Worker Error] Obsidian error", "Ошибка сохранения в Obsidian"),
    ("[Worker] Successfully processed: ", "Обработка завершена: {rest}"),
    ("[Worker Error] Archiving failed", "Ошибка архивации"),
    ("[Worker Error] Loop error", "Ошибка фонового обработчика"),
    ("[Worker Warning] Failed to preload Ollama", "Модель саммаризации недоступна"),
    # Outlook и UI
    ("[Outlook Error]", "Не удалось получить встречу из Outlook"),
    ("[UI] Outlook: встреча в окне поиска не найдена", "Встреча в Outlook не найдена"),
    ("[UI] Outlook meeting loaded: ", "Встреча из Outlook: {rest}"),
    ("[UI Warning] Could not write metadata JSON", "Не удалось сохранить метаданные встречи"),
    ("[UI] Obsidian vault set to: ", "Папка Obsidian: {rest}"),
    # Приложение
    ("Starting Meeting Assistant", "Приложение запущено"),
    ("Meeting Assistant stopped", "Приложение остановлено"),
]


def to_ui_event(msg):
    """Возвращает короткое сообщение для UI или None (остаётся только в app.log)."""
    if not msg:
        return None
    line = str(msg).strip()
    for prefix, template in _UI_EVENT_RULES:
        if line.startswith(prefix):
            rest = line[len(prefix):].strip()
            return template.format(rest=rest)
    # Неизвестные ошибки — одной общей строкой, детали в logs/app.log
    if "Error]" in line:
        return "Ошибка — подробности в logs/app.log"
    return None
