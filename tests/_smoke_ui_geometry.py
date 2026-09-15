"""Смоук геометрии UI: строит AppUI с моками, проверяет размеры/отступы. Без воркера."""
import os
import queue
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

import tkinter
import customtkinter as ctk
import ui

recorder = type("R", (), {"is_recording": False, "start": lambda self, **kw: "", "stop": lambda self: None})()

app = ui.AppUI(recorder, worker=None, log_queue=queue.Queue(), logger_callback=lambda m: None)
app.update_idletasks()
app.update()

errors = []


def check(cond, msg):
    if not cond:
        errors.append(msg)


# 1. Кнопки управления записью одинаковой ширины и высоты
w1, h1 = app.btn_start.winfo_width(), app.btn_start.winfo_height()
w2, h2 = app.btn_stop.winfo_width(), app.btn_stop.winfo_height()
check(w1 == w2 and h1 == h2, f"Start/Stop разные: start={w1}x{h1}, stop={w2}x{h2}")

# 2. Кнопки инструментов попарно одинаковой ширины
tw = [app.btn_select_obsidian.winfo_width(), app.btn_whisper_prompt.winfo_width(),
      app.btn_summary_context.winfo_width(), app.btn_speaker_name.winfo_width()]
check(len(set(tw)) == 1, f"Кнопки инструментов разной ширины: {tw}")

# 3. Надписи без многоточия
for btn in (app.btn_select_obsidian, app.btn_whisper_prompt, app.btn_summary_context, app.btn_speaker_name):
    check("…" not in btn.cget("text") and "..." not in btn.cget("text"), f"Многоточие в надписи: {btn.cget('text')}")
    # Надпись умещается в кнопку
    check(btn.winfo_width() >= btn.winfo_reqwidth(), f"Текст не умещается: {btn.cget('text')}")

# 4. Индикатор модели — в блоке модели, в строке заголовка (над комбо)
model_frame = app.combo_model.master
check(app.lbl_model_status.master.master is model_frame, "Индикатор модели не в блоке модели")
check(app.lbl_model_status.winfo_y() < app.combo_model.winfo_y(), "Индикатор модели не в строке заголовка")
check(app.lbl_model_status.cget("text") == "загрузка в память...",
      f"Начальный текст статуса: {app.lbl_model_status.cget('text')}")

# 5. Комбо микрофона и модели: одинаковые отступы до краёв фреймов
def rel_x(w, frame):
    return w.winfo_rootx() - frame.winfo_rootx()

dm = rel_x(app.combo_mic, app.combo_mic.master)
do = rel_x(app.combo_model, app.combo_model.master)
check(dm == do, f"Разный левый отступ комбо: mic={dm}, model={do}")

# 8. Таймер записи и кнопка копирования лога существуют
check(hasattr(app, "lbl_rec_timer") and app.lbl_rec_timer.winfo_exists(), "Нет таймера записи")
check(app.lbl_rec_timer.cget("text") == "", "Таймер не пуст до старта записи")
check(hasattr(app, "btn_copy_log") and app.btn_copy_log.winfo_exists(), "Нет кнопки копирования лога")

# 9. Кнопка Outlook — акцентная, с короткой надписью; зазор до ✕ как в блоке устройств
check(app.btn_outlook.cget("text") == "Outlook", f"Надпись кнопки Outlook: {app.btn_outlook.cget('text')}")
check(app.btn_outlook.cget("fg_color") == "#c65c11", "Кнопка Outlook не акцентная")
check(app.btn_outlook.cget("text_color") == ["#f7ead9", "#f7ead9"], "Текст кнопки Outlook не off-white")
gap_devices = (app.btn_refresh_mic.winfo_rootx() -
               (app.combo_mic.winfo_rootx() + app.combo_mic.winfo_width()))
gap_meeting = (app.btn_outlook.winfo_rootx() -
               (app.entry_subject.winfo_rootx() + app.entry_subject.winfo_width()))
check(abs(gap_meeting - gap_devices) <= 1, f"Зазор Outlook/✕ ({gap_meeting}) != устройств ({gap_devices})")

# 9a. Блок инструментов — второй сверху, своп кнопок и новые названия
meet_bottom = app.entry_subject.master.winfo_rooty() + app.entry_subject.master.winfo_height()
tools_top = app.btn_select_obsidian.master.winfo_rooty()
device_top = app.combo_mic.master.winfo_rooty()
check(abs(tools_top - meet_bottom - 10) <= 2, f"Блок инструментов не второй: gap={tools_top - meet_bottom}")
check(abs(device_top - (tools_top + app.btn_select_obsidian.master.winfo_height()) - 10) <= 2,
      "Блок устройств не третий")


def cell(btn):
    return btn.grid_info()["row"], btn.grid_info()["column"]

check(cell(app.btn_select_obsidian) == (0, 0), f"Папка Obsidian: {cell(app.btn_select_obsidian)}")
check(cell(app.btn_speaker_name) == (0, 1), f"Имя пользователя: {cell(app.btn_speaker_name)}")
check(cell(app.btn_summary_context) == (1, 0), f"Промт Summary: {cell(app.btn_summary_context)}")
check(cell(app.btn_whisper_prompt) == (1, 1), f"Промпт Whisper: {cell(app.btn_whisper_prompt)}")
check(app.btn_speaker_name.cget("text") == "Имя пользователя", "Кнопка не переименована в «Имя пользователя»")
check(app.btn_summary_context.cget("text") == "Промт Summary", "Кнопка не переименована в «Промт Summary»")

# 9b. Скругление кнопок = BTN_CORNER_RADIUS
for btn in (app.btn_start, app.btn_stop, app.btn_outlook, app.btn_copy_log,
            app.btn_select_obsidian, app.btn_speaker_name,
            app.btn_summary_context, app.btn_whisper_prompt):
    check(btn.cget("corner_radius") == 4, f"corner_radius={btn.cget('corner_radius')} у {btn.cget('text')}")

# 10. Тексты статуса модели (в строке заголовка, без префикса «Модель:»)
app.worker = type("W", (), {"queue_files": [], "current_task": None, "model_status": "ready"})
app._update_status()
check(app.lbl_model_status.cget("text") == "загружена в память", f"Текст ready: {app.lbl_model_status.cget('text')}")
app.worker.model_status = "loading"
app._update_status()
check(app.lbl_model_status.cget("text") == "загрузка в память...", f"Текст loading: {app.lbl_model_status.cget('text')}")
app.worker.model_status = "unavailable"
app._update_status()
check(app.lbl_model_status.cget("text") == "недоступна", f"Текст unavailable: {app.lbl_model_status.cget('text')}")

# 11. Таймер тикает при активной записи
app.recorder.is_recording = True
app._rec_started_at = time.monotonic() - 65  # 1:05
app._update_rec_timer()
check(app.lbl_rec_timer.cget("text") == "01:05", f"Текст таймера: {app.lbl_rec_timer.cget('text')}")
if app._rec_timer_job is not None:
    app.after_cancel(app._rec_timer_job)
    app._rec_timer_job = None
app.recorder.is_recording = False

# 6. Нижний отступ последнего элемента блока до низа фрейма
def bottom_gap(w, frame):
    return (frame.winfo_rooty() + frame.winfo_height()) - (w.winfo_rooty() + w.winfo_height())

gap_loop = bottom_gap(app.combo_loopback, app.combo_loopback.master)
gap_model = bottom_gap(app.combo_model, model_frame)
check(gap_loop == gap_model, f"Разный нижний отступ: loopback={gap_loop}, model={gap_model}")

# 6a. Внешние отступы: боковые у всех блоков одинаковые, вертикальные зазоры равны FRAME_PAD_Y
def left_margin(frame):
    return frame.winfo_rootx() - app.winfo_rootx()

frames = {app.combo_mic.master, app.combo_loopback.master, model_frame,
          app.btn_select_obsidian.master, app.btn_start.master,
          app.lbl_rec_status.master.master, app.txt_logs.master}
margins = {left_margin(f) for f in frames}
check(len(margins) == 1, f"Боковые отступы блоков разные: {margins}")

ordered = sorted(frames, key=lambda f: f.winfo_rooty())
gaps = [ordered[i + 1].winfo_rooty() - (ordered[i].winfo_rooty() + ordered[i].winfo_height())
        for i in range(len(ordered) - 1)]
check(all(abs(g - 10) <= 1 for g in gaps), f"Вертикальные зазоры между блоками не равны 10: {gaps}")
check(margins.pop() == 10, f"Боковой отступ не 10: {margins}")

# 7. Иконные кнопки одной ширины
iw = {app.btn_refresh_mic.winfo_width(), app.btn_refresh_loop.winfo_width(),
      app.btn_refresh_models.winfo_width(), app.btn_clear_meeting.winfo_width()}
check(len(iw) == 1, f"Иконные кнопки разной ширины: {iw}")

print("BUTTONS start=%dx%d stop=%dx%d" % (w1, h1, w2, h2))
print("TOOLS widths=%s" % tw)
print("MODEL status in model block: %s, status_y=%d" % (app.lbl_model_status.master.master is model_frame, app.lbl_model_status.winfo_y()))
print("PADS combo left mic=%d model=%d, bottom loop=%d model=%d" % (dm, do, gap_loop, gap_model))

app.destroy()
if errors:
    print("FAILED:")
    for e in errors:
        print(" -", e)
    sys.exit(1)
print("UI_GEOMETRY_OK")
