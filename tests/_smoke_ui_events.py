# -*- coding: utf-8 -*-
"""Смоук маппинга логов UI без запуска приложения.

Запуск: python tests/_smoke_ui_events.py
Печатает короткое событие UI для каждого технического сообщения
(или None — событие остаётся только в logs/app.log).
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from ui_events import to_ui_event

SAMPLES = [
    "Starting Meeting Assistant...",
    "[Recorder] Recording started: Mic ('Mic') + Output ('Speakers')",
    "[Recorder] Recording saved: Meeting_2026-10-09_10-00_test.wav",
    "[Recorder Warning] No audio captured, file skipped.",
    "[Recorder Warning] No microphone device selected.",
    "[Recorder Error] Capture failed: boom",
    "[Worker] Processing meeting: 2026-10-09_10-00_test",
    "[Worker] Loading Whisper (large-v3)...",
    "[Worker] Transcription complete (1234 chars).",
    "[Worker] Generating summary via Ollama (llama3)...",
    "[Worker Warning] No transcript available; archiving without summary.",
    "[Worker Warning] Giving up after 3 attempts; archiving as failed.",
    "[Worker] Note saved to Obsidian: 2026-10-09_10-00_test.md",
    "[Worker] Successfully processed: 2026-10-09_10-00_test",
    "[Worker Error] Loop error: boom",
    "[Outlook] Jet filter (%d.%m.%Y): raw=5, valid=2 (future=0, ended_past=3)",
    "[Outlook Warning] DASL filter (UTC) failed: x",
    "[Outlook Error] COM Automation Error",
    "[UI] Outlook meeting loaded: Daily Sync",
    "[UI] Devices refreshed: 3 mics, 2 loopbacks.",
    "[UI Warning] Could not write metadata JSON: x",
    "[STDOUT] some cuda noise",
    "[STDERR] traceback line",
    "[Cleanup] Removed old audio (>14 days): a.wav",
    "Shutting down...",
    "Meeting Assistant stopped.",
    "some totally unknown line",
]

if __name__ == "__main__":
    for s in SAMPLES:
        print(f"{s!r}\n    -> {to_ui_event(s)!r}")
