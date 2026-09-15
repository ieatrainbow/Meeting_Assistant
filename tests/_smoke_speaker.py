# -*- coding: utf-8 -*-
"""Смоук атрибуции говорящих без Whisper/COM: синтетические дорожки mic/loop,
микс по формуле recorder (mic+loop)/2, проверка меток _speaker_label.

Запуск: python tests/_smoke_speaker.py
"""
import os
import sys
import tempfile
import wave

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from src.worker import _load_wav_float, _find_speaker_track, _remove_speaker_track, _speaker_label

SR = 16000
FAILURES = []

def check(name, actual, expected):
    status = "OK  " if actual == expected else "FAIL"
    if actual != expected:
        FAILURES.append(name)
    print(f"[{status}] {name}: got {actual!r}, expected {expected!r}")

def tone(freq, seconds, amp=0.2):
    t = np.arange(int(seconds * SR)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)

def silence(seconds):
    return np.zeros(int(seconds * SR), dtype=np.float32)

def write_wav(path, samples):
    pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm.tobytes())

# --- Синтетическая встреча: 0-2s говорим мы (mic), 2-4s собеседник (loop),
# --- 4-6s оба, 6-8s тишина
mic = np.concatenate([tone(200, 2.0), silence(2.0), tone(300, 2.0), silence(2.0)])
loop = np.concatenate([silence(2.0), tone(400, 2.0), tone(500, 2.0), silence(2.0)])
mix = (mic + loop) / 2.0

tmp = tempfile.mkdtemp(prefix="speaker_smoke_")
mix_path = os.path.join(tmp, "2026-01-01_10-00_Test.wav")
write_wav(mix_path, mix)

# Sidecar-дорожки как их пишет recorder
mic_path = os.path.splitext(mix_path)[0] + "_mic.wav"
loop_path = os.path.splitext(mix_path)[0] + "_loop.wav"
write_wav(mic_path, mic)
write_wav(loop_path, loop)

main_audio = _load_wav_float(mix_path)
sidecar = _load_wav_float(mic_path)

check("sidecar mic найден", _find_speaker_track(mix_path), mic_path)
check("mic активен -> Я", _speaker_label(0.2, 1.8, main_audio, sidecar, True), "Я")
check("кастомное имя -> Иван", _speaker_label(0.2, 1.8, main_audio, sidecar, True, self_name="Иван"), "Иван")
check("оба -> Иван + Собеседник", _speaker_label(4.2, 5.8, main_audio, sidecar, True, self_name="Иван"), "Иван + Собеседник")
check("loop активен -> Собеседник", _speaker_label(2.2, 3.8, main_audio, sidecar, True), "Собеседник")
check("оба активны -> Я + Собеседник", _speaker_label(4.2, 5.8, main_audio, sidecar, True), "Я + Собеседник")
check("тишина -> без метки", _speaker_label(6.2, 7.8, main_audio, sidecar, True), "")
check("вне дорожек -> без метки", _speaker_label(100.0, 101.0, main_audio, sidecar, True), "")

# Реалистичный сценарий sidecar=loop (микрофон не писался): микс == loopback,
# вся речь от собеседника. Второй канал (mic) вычитанием даёт ноль.
loop_only_path = os.path.join(tmp, "2026-01-01_11-00_LoopOnly.wav")
write_wav(loop_only_path, loop)
loop_sidecar = _load_wav_float(loop_only_path)
check("sidecar=loop -> Собеседник", _speaker_label(2.2, 3.8, loop_sidecar, loop_sidecar, False), "Собеседник")

# Отсутствие sidecar
check("нет sidecar -> не найден", _find_speaker_track(os.path.join(tmp, "missing.wav")), None)
check("нет sidecar -> без метки", _speaker_label(0.0, 1.0, main_audio, None, True), "")

# Удаление sidecar
_remove_speaker_track(mix_path)
check("sidecar удалён", _find_speaker_track(mix_path), None)

print()
if FAILURES:
    print(f"FAILED: {len(FAILURES)}: {FAILURES}")
    sys.exit(1)
print("All speaker attribution checks passed.")
