# -*- coding: utf-8 -*-
"""Смоук: подготовка контекста календаря и промптов саммари (без Whisper/Ollama).

Запуск: python tests/_smoke_prompts.py
"""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
sys.path.insert(0, os.path.join(BASE, "src"))

import config
from worker import prepare_calendar_context, WorkerDaemon
from config import SUMMARY_PROMPT_TEMPLATE

# 1. Ссылки заменяются плейсхолдером
body = "Подключитесь: https://teams.microsoft.com/l/meetup-join/abc123\nОбсудим релиз."
ctx = prepare_calendar_context(body)
assert "[ссылка]" in ctx and "teams.microsoft.com" not in ctx, ctx
assert "Обсудим релиз." in ctx, ctx

# 2. www-ссылки тоже режутся
assert "www.example.com" not in prepare_calendar_context("см. www.example.com/doc")

# 3. Усечение до лимита
long_body = "строка\n" * 5000
ctx = prepare_calendar_context(long_body, max_chars=100)
assert len(ctx) < 120 and ctx.endswith("…[усечено]"), (len(ctx), ctx[-30:])

# 4. Пустое описание → пустой контекст
assert prepare_calendar_context("") == ""
assert prepare_calendar_context(None) == ""

# 5. Воркер: дефолты из config при отсутствии настроек
w = WorkerDaemon()
assert w.whisper_initial_prompt == config.WHISPER_INITIAL_PROMPT
assert w.summary_domain_context == config.SUMMARY_DOMAIN_CONTEXT

# 6. Воркер: настройки перекрывают дефолты; пустые — откат к дефолту
w = WorkerDaemon(whisper_initial_prompt="Кастомная подсказка.",
                 summary_domain_context="  ")
assert w.whisper_initial_prompt == "Кастомная подсказка."
assert w.summary_domain_context == config.SUMMARY_DOMAIN_CONTEXT

# 7. Сборка промпта: домен первой строкой, контекст помечен как справочный
meta_body = prepare_calendar_context("Agenda: https://wiki.corp/x и план работ.")
context_block = (
    "\nОписание встречи из календаря (справочная информация: "
    "используй только для понимания контекста, НЕ добавляй в "
    f"саммари факты, которые не прозвучали во встрече):\n{meta_body}\n"
)
prompt = SUMMARY_PROMPT_TEMPLATE.format(
    subject="Релиз 2.0", context=context_block, transcript="текст")
if w.summary_domain_context:
    prompt = f"Общий контекст: {w.summary_domain_context}.\n" + prompt
assert prompt.startswith("Общий контекст: "), prompt
assert "справочная информация" in prompt and "НЕ добавляй" in prompt, prompt
assert "[ссылка]" in prompt and "wiki.corp" not in prompt, prompt

print("Prompts smoke checks passed.")
