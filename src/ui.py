import datetime
import json
import os
import queue
import sys
import threading
import time
import tkinter
from tkinter import filedialog

import customtkinter as ctk

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    BASE_DIR, MIC_DEVICE, SPEAKER_SELF_NAME, STEREO_MIX_DEVICE, OBSIDIAN_DIR,
    OLLAMA_MODEL, WHISPER_INITIAL_PROMPT, SUMMARY_DOMAIN_CONTEXT,
    WHISPER_PROMPT_MAX_CHARS, SUMMARY_DOMAIN_MAX_CHARS, SPEAKER_NAME_MAX_CHARS,
)
from outlook_client import get_current_or_next_meeting_details
from settings_store import load_settings, save_settings
from recorder import get_dshow_audio_devices, get_wasapi_audio_render_devices

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

# Цветовая схема: тёмно-синие поверхности (градациями: окно → блок → поле)
# вместо серых, тёмно-оранжевый акцент. [светлая тема, тёмная тема] — mode "System".
SURFACE = ["#e7ecf4", "#0c1320"]        # окно (самый тёмный уровень)
SURFACE_TOP = ["#dde5f1", "#111b2f"]    # блоки-фреймы (уровень выше окна)
SURFACE_NESTED = ["#e4ebf5", "#15223a"]  # вложенные фреймы внутри блоков
FIELD = ["#f7fafd", "#192741"]          # поля ввода, комбо, лог (ещё светлее)
BORDER = ["#b6c5d8", "#31466a"]         # рамки полей и фреймов
TEXT = ["#1d2b3f", "#d8e3f3"]           # основной текст
PLACEHOLDER = ["#8296b0", "#6b809c"]    # placeholder полей ввода
BTN_TEXT = ["#f7ead9", "#f7ead9"]       # тёплый off-white: мягче чистого белого на насыщенных кнопках
BTN_TEXT_DISABLED = ["#9aa8ba", "#5f7288"]
ACCENT = "#c65c11"                      # тёмно-оранжевый: кнопки, активные статусы
ACCENT_HOVER = "#a34a0b"
GREEN = "#1f9d4f"                       # насыщенный зелёный в тон акценту: старт записи
GREEN_HOVER = "#197e3f"
DANGER = "#b03a3a"                      # остановка записи, ошибки
DANGER_HOVER = "#8a2c2c"
WARN = "#d9a11f"                        # промежуточные статусы (загрузка модели)
SECONDARY = ["#9db0c9", "#2b3d5c"]      # вторичные кнопки («Отмена» в диалогах)
SECONDARY_HOVER = ["#879cb8", "#35496e"]


def _apply_theme() -> None:
    """Переопределяет цвета темы blue до создания виджетов."""
    t = ctk.ThemeManager.theme
    t["CTk"]["fg_color"] = SURFACE
    t["CTkToplevel"]["fg_color"] = SURFACE
    frame = t["CTkFrame"]
    frame["fg_color"] = SURFACE_TOP
    frame["top_fg_color"] = SURFACE_NESTED
    frame["border_color"] = BORDER
    btn = t["CTkButton"]
    btn["fg_color"] = [ACCENT, ACCENT]
    btn["hover_color"] = [ACCENT_HOVER, ACCENT_HOVER]
    btn["border_color"] = BORDER
    btn["text_color"] = BTN_TEXT
    btn["text_color_disabled"] = BTN_TEXT_DISABLED
    t["CTkLabel"]["text_color"] = TEXT
    entry = t["CTkEntry"]
    entry["fg_color"] = FIELD
    entry["border_color"] = BORDER
    entry["text_color"] = TEXT
    entry["placeholder_text_color"] = PLACEHOLDER
    combo = t["CTkComboBox"]
    combo["fg_color"] = FIELD
    combo["border_color"] = BORDER
    combo["button_color"] = ["#c3d2e5", "#243550"]
    combo["button_hover_color"] = ["#aec0d8", "#2b3f60"]
    combo["text_color"] = TEXT
    combo["text_color_disabled"] = BTN_TEXT_DISABLED
    textbox = t["CTkTextbox"]
    textbox["fg_color"] = FIELD
    textbox["border_color"] = BORDER
    textbox["text_color"] = TEXT
    textbox["scrollbar_button_color"] = ["#9fb2ca", "#243550"]
    textbox["scrollbar_button_hover_color"] = ["#8ba3c2", "#2b3f60"]
    dropdown = t["DropdownMenu"]
    dropdown["fg_color"] = ["#f2f6fb", "#15223a"]
    dropdown["hover_color"] = ["#d7e2f0", "#243550"]
    dropdown["text_color"] = TEXT
    t["CTkScrollableFrame"]["label_fg_color"] = SURFACE_NESTED
    scrollbar = t["CTkScrollbar"]
    scrollbar["fg_color"] = SURFACE_TOP
    scrollbar["button_color"] = ["#9fb2ca", "#243550"]
    scrollbar["button_hover_color"] = ["#8ba3c2", "#2b3f60"]
    for key in ("CTkCheckBox", "CTkRadioButton"):
        w = t[key]
        w["fg_color"] = [ACCENT, ACCENT]
        w["hover_color"] = [ACCENT_HOVER, ACCENT_HOVER]
        w["border_color"] = BORDER
        w["text_color"] = TEXT
        w["text_color_disabled"] = BTN_TEXT_DISABLED
    t["CTkCheckBox"]["checkmark_color"] = BTN_TEXT
    switch = t["CTkSwitch"]
    switch["fg_color"] = FIELD
    switch["progress_color"] = [ACCENT, ACCENT]
    switch["button_color"] = ["#c3d2e5", "#243550"]
    switch["button_hover_color"] = ["#aec0d8", "#2b3f60"]
    switch["text_color"] = TEXT
    switch["text_color_disabled"] = BTN_TEXT_DISABLED
    option = t["CTkOptionMenu"]
    option["fg_color"] = [ACCENT, ACCENT]
    option["button_color"] = [ACCENT_HOVER, ACCENT_HOVER]
    option["button_hover_color"] = ["#8f430c", "#8f430c"]
    option["text_color"] = BTN_TEXT
    option["text_color_disabled"] = BTN_TEXT_DISABLED
    progress = t["CTkProgressBar"]
    progress["fg_color"] = FIELD
    progress["progress_color"] = [ACCENT, ACCENT]
    progress["border_color"] = BORDER
    slider = t["CTkSlider"]
    slider["fg_color"] = FIELD
    slider["progress_color"] = [ACCENT, ACCENT]
    slider["button_color"] = [ACCENT, ACCENT]
    slider["button_hover_color"] = [ACCENT_HOVER, ACCENT_HOVER]
    segmented = t["CTkSegmentedButton"]
    segmented["fg_color"] = SURFACE_TOP
    segmented["selected_color"] = [ACCENT, ACCENT]
    segmented["selected_hover_color"] = [ACCENT_HOVER, ACCENT_HOVER]
    segmented["unselected_color"] = FIELD
    segmented["unselected_hover_color"] = ["#d7e2f0", "#243550"]
    segmented["text_color"] = BTN_TEXT
    segmented["text_color_disabled"] = BTN_TEXT_DISABLED
    # Базовый шрифт всех контролов: дефолт 13pt → 15pt (+2)
    t["CTkFont"]["size"] = 15


_apply_theme()

# Единые отступы интерфейса
PAD_X = 10           # внутренний отступ контролов от краёв фрейма
FRAME_PAD_X = 10     # отступ блоков от края окна
FRAME_PAD_Y = 10     # вертикальный зазор между блоками и от краёв окна
ICON_BTN_WIDTH = 32  # ширина кнопок-иконок (↻, ✕)
# Скругление углов кнопок: артефакты пикселей у CustomTkinter идут от отрисовки
# дуг на canvas — чем меньше радиус, тем они незаметнее (0 = без скругления)
BTN_CORNER_RADIUS = 4

class AppUI(ctk.CTk):
    def __init__(self, recorder, worker, log_queue=None, logger_callback=None):
        super().__init__()

        self.recorder = recorder
        self.worker = worker
        self.log_queue = log_queue or queue.Queue()
        self.log = logger_callback or print
        # Жирный шрифт кнопок (размер берётся из темы, +2 к дефолту = 15)
        self.btn_font = ctk.CTkFont()  # обычное начертание, размер из темы

        # Восстановление пользовательских настроек (settings.json), иначе — из .env
        settings = load_settings()
        saved_obsidian = settings["obsidian_path"]
        self.obsidian_path = saved_obsidian or OBSIDIAN_DIR or os.path.join(BASE_DIR, "obsidian_output")
        self._saved_mic = settings["mic_device"]
        self._saved_loopback = settings["loopback_device"]
        self._saved_ollama_model = settings["ollama_model"]
        self._saved_speaker_name = settings["speaker_self_name"] or SPEAKER_SELF_NAME
        self._saved_whisper_prompt = settings["whisper_initial_prompt"]
        self._saved_summary_context = settings["summary_domain_context"]
        if self.worker is not None:
            self.worker.speaker_self_name = self._saved_speaker_name
        if self._saved_ollama_model and self.worker is not None \
                and getattr(self.worker, "ollama_model", None) != self._saved_ollama_model:
            if hasattr(self.worker, "set_ollama_model"):
                self.worker.set_ollama_model(self._saved_ollama_model)
            else:
                self.worker.ollama_model = self._saved_ollama_model
        if saved_obsidian:
            if self.worker is not None:
                self.worker.obsidian_dir = self.obsidian_path
            if not os.path.isdir(saved_obsidian):
                self.log(f"[UI Warning] Saved Obsidian path missing: {saved_obsidian}")
        self.all_logs = []
        self.active_tab = "status"
        self.current_outlook_details = None

        self.title("Meeting Assistant")
        self.geometry("680x880")
        self.resizable(False, False)

        self._build_meeting_frame()
        self._build_tools_frame()
        self._build_device_frame()
        self._build_model_frame()
        self._build_control_frame()
        self._build_status_frame()
        self._build_log_frame()
        self.after(200, self._poll_log_queue)
        self.after(150, self._refresh_devices)
        self.after(150, self._refresh_models)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_meeting_frame(self):
        frame = ctk.CTkFrame(self)
        frame.pack(padx=FRAME_PAD_X, pady=(FRAME_PAD_Y, FRAME_PAD_Y), fill="x")

        ctk.CTkLabel(frame, text="Тема встречи:").grid(row=0, column=0, sticky="w", padx=PAD_X, pady=(10, 2))
        self.entry_subject = ctk.CTkEntry(frame, placeholder_text="Введите тему или получите из Outlook")
        self.entry_subject.grid(row=1, column=0, columnspan=2, sticky="ew", padx=PAD_X, pady=(0, 10))

        # Акцентная кнопка: единственное действие в блоке, зелёный — цвет действия.
        # Зазор до ✕ = PAD_X, как между комбо и кнопкой ↻ в блоках устройств.
        self.btn_outlook = ctk.CTkButton(frame, text="Outlook", width=120,
                                         font=self.btn_font,
                                         fg_color=ACCENT, hover_color=ACCENT_HOVER,
                                         corner_radius=BTN_CORNER_RADIUS,
                                         command=self._fetch_outlook)
        self.btn_outlook.grid(row=1, column=2, padx=(0, PAD_X), pady=(0, 10))

        self.btn_clear_meeting = ctk.CTkButton(
            frame, text="✕", width=ICON_BTN_WIDTH, state="disabled",
            font=self.btn_font,
            corner_radius=BTN_CORNER_RADIUS,
            command=self._clear_meeting_info
        )
        self.btn_clear_meeting.grid(row=1, column=3, padx=(0, PAD_X), pady=(0, 10))

        self.lbl_outlook_info = ctk.CTkLabel(frame, text="Встреча из календаря не выбрана.", justify="left",
                                             font=ctk.CTkFont(size=11))
        self.lbl_outlook_info.grid(row=2, column=0, columnspan=4, sticky="w", padx=PAD_X, pady=(0, 10))
        frame.columnconfigure(0, weight=1)

    def _build_device_frame(self):
        frame = ctk.CTkFrame(self)
        frame.pack(padx=FRAME_PAD_X, pady=(0, FRAME_PAD_Y), fill="x")

        ctk.CTkLabel(frame, text="Микрофон:").grid(row=0, column=0, sticky="w", padx=PAD_X, pady=(10, 2))
        self.combo_mic = ctk.CTkComboBox(frame, values=[MIC_DEVICE],
                                         command=self._on_device_selected)
        self.combo_mic.set(self._saved_mic or MIC_DEVICE)
        self.combo_mic.grid(row=1, column=0, padx=PAD_X, sticky="ew")

        self.btn_refresh_mic = ctk.CTkButton(frame, text="↻", width=ICON_BTN_WIDTH,
                                             font=self.btn_font,
                                             corner_radius=BTN_CORNER_RADIUS, command=self._refresh_devices)
        self.btn_refresh_mic.grid(row=1, column=1, padx=(0, PAD_X))

        ctk.CTkLabel(frame, text="Системный звук (loopback):").grid(row=2, column=0, sticky="w", padx=PAD_X, pady=(8, 2))
        self.combo_loopback = ctk.CTkComboBox(frame, values=[STEREO_MIX_DEVICE or ""],
                                              command=self._on_device_selected)
        if self._saved_loopback or STEREO_MIX_DEVICE:
            self.combo_loopback.set(self._saved_loopback or STEREO_MIX_DEVICE)
        self.combo_loopback.grid(row=3, column=0, padx=PAD_X, sticky="ew", pady=(0, 10))

        self.btn_refresh_loop = ctk.CTkButton(frame, text="↻", width=ICON_BTN_WIDTH,
                                              font=self.btn_font,
                                              corner_radius=BTN_CORNER_RADIUS, command=self._refresh_devices)
        self.btn_refresh_loop.grid(row=3, column=1, padx=(0, PAD_X), pady=(0, 10))
        frame.columnconfigure(0, weight=1)

    def _build_model_frame(self):
        """Модель Ollama — отдельный блок под настройками звука, со статусом готовности."""
        frame = ctk.CTkFrame(self)
        frame.pack(padx=FRAME_PAD_X, pady=(0, FRAME_PAD_Y), fill="x")

        # Заголовок и статус в одной строке: «Модель Ollama: загружена в память»
        head = ctk.CTkFrame(frame, fg_color="transparent")
        head.grid(row=0, column=0, columnspan=2, sticky="ew", padx=PAD_X, pady=(10, 2))
        ctk.CTkLabel(head, text="Модель Ollama:").pack(side="left")
        self.lbl_model_status = ctk.CTkLabel(head, text="загрузка в память...",
                                             font=ctk.CTkFont(size=14))
        self.lbl_model_status.pack(side="left", padx=(6, 0))

        self.combo_model = ctk.CTkComboBox(
            frame, values=[self._saved_ollama_model or OLLAMA_MODEL],
            command=self._on_model_selected
        )
        self.combo_model.set(self._saved_ollama_model or OLLAMA_MODEL)
        self.combo_model.grid(row=1, column=0, padx=PAD_X, sticky="ew", pady=(0, 10))

        self.btn_refresh_models = ctk.CTkButton(frame, text="↻", width=ICON_BTN_WIDTH,
                                                font=self.btn_font,
                                                corner_radius=BTN_CORNER_RADIUS, command=self._refresh_models)
        self.btn_refresh_models.grid(row=1, column=1, padx=(0, PAD_X), pady=(0, 10))
        frame.columnconfigure(0, weight=1)

    def _open_prompt_dialog(self, kind):
        """Окно редактирования промпта: textarea, счётчик символов, Сохранить/Отмена.

        При открытии подставляется текущее значение (пользовательская настройка
        или дефолт из config/.env). Очистка поля при сохранении = сброс к дефолту.
        """
        if kind == "whisper":
            title = "Подсказка Whisper (initial prompt)"
            max_chars = WHISPER_PROMPT_MAX_CHARS
            default = WHISPER_INITIAL_PROMPT
            current = self._saved_whisper_prompt or default
        else:
            title = "Общая тема для саммари (контекст домена)"
            max_chars = SUMMARY_DOMAIN_MAX_CHARS
            default = SUMMARY_DOMAIN_CONTEXT
            current = self._saved_summary_context or default

        dialog = ctk.CTkToplevel(self)
        dialog.title(title)
        dialog.geometry("600x340")
        dialog.resizable(False, False)
        dialog.transient(self)

        ctk.CTkLabel(
            dialog,
            text=(f"Дефолт: {default}\n"
                  f"Пустое поле при сохранении = возврат к дефолту. Лимит: {max_chars} символов."),
            justify="left", wraplength=560, font=ctk.CTkFont(size=11),
        ).pack(anchor="w", padx=10, pady=(10, 5))

        txt = ctk.CTkTextbox(dialog, wrap="word")
        txt.pack(fill="both", expand=True, padx=10, pady=5)
        txt.insert("1.0", current)

        lbl_counter = ctk.CTkLabel(dialog, text="", font=ctk.CTkFont(size=11))
        lbl_counter.pack(anchor="w", padx=10)

        def update_counter(_event=None):
            length = len(txt.get("1.0", "end-1c").strip())
            lbl_counter.configure(
                text=f"{length} / {max_chars}",
                text_color=DANGER if length > max_chars else None,
            )

        txt.bind("<KeyRelease>", update_counter)
        update_counter()

        def save():
            text = txt.get("1.0", "end-1c").strip()
            if len(text) > max_chars:
                text = text[:max_chars].rstrip()
            # Промпты однострочные по смыслу — переносы схлопываем в пробелы
            text = " ".join(text.split())
            if kind == "whisper":
                self._saved_whisper_prompt = text
                if self.worker is not None:
                    self.worker.whisper_initial_prompt = text or WHISPER_INITIAL_PROMPT
            else:
                self._saved_summary_context = text
                if self.worker is not None:
                    self.worker.summary_domain_context = text or SUMMARY_DOMAIN_CONTEXT
            self._save_current_settings()
            dialog.destroy()
            self.log(f"[UI] Prompt saved: {title} ({len(text)} chars)")

        btns = ctk.CTkFrame(dialog, fg_color="transparent")
        btns.pack(fill="x", padx=10, pady=(0, 10))
        ctk.CTkButton(btns, text="Сохранить", width=110,
                      font=self.btn_font, command=save).pack(side="right")
        ctk.CTkButton(btns, text="Отмена", width=90, fg_color=SECONDARY,
                      hover_color=SECONDARY_HOVER, font=self.btn_font,
                      command=dialog.destroy).pack(side="right", padx=(0, 8))

        # grab после отрисовки окна, иначе Tk может отказать («not viewable»)
        dialog.after(100, dialog.grab_set)

    def _build_tools_frame(self):
        """Служебные кнопки (папка Obsidian, промпты, имя в транскрипте).

        Кнопки в 2×2 сетке, тянутся по ширине — ряды визуально ровные.
        """
        frame = ctk.CTkFrame(self)
        frame.pack(padx=FRAME_PAD_X, pady=(0, FRAME_PAD_Y), fill="x")

        # Промпты и имя говорящего — редактируются в отдельных окнах.
        # Симметричные padx (10,5)/(5,10): при равных весах колонок кнопки
        # получаются одинаковой ширины, внешний отступ = PAD_X.
        self.btn_select_obsidian = ctk.CTkButton(
            frame, text="Папка Obsidian", corner_radius=BTN_CORNER_RADIUS,
            font=self.btn_font,
            command=self._select_obsidian_folder
        )
        self.btn_select_obsidian.grid(row=0, column=0, sticky="ew", padx=(PAD_X, 5), pady=(10, 5))

        self.btn_speaker_name = ctk.CTkButton(
            frame, text="Имя пользователя", corner_radius=BTN_CORNER_RADIUS,
            font=self.btn_font,
            command=self._open_name_dialog)
        self.btn_speaker_name.grid(row=0, column=1, sticky="ew", padx=(5, PAD_X), pady=(10, 5))

        self.btn_summary_context = ctk.CTkButton(
            frame, text="Промт Summary", corner_radius=BTN_CORNER_RADIUS,
            font=self.btn_font,
            command=lambda: self._open_prompt_dialog("summary"))
        self.btn_summary_context.grid(row=1, column=0, sticky="ew", padx=(PAD_X, 5), pady=(0, 10))

        self.btn_whisper_prompt = ctk.CTkButton(
            frame, text="Промпт Whisper", corner_radius=BTN_CORNER_RADIUS,
            font=self.btn_font,
            command=lambda: self._open_prompt_dialog("whisper"))
        self.btn_whisper_prompt.grid(row=1, column=1, sticky="ew", padx=(5, PAD_X), pady=(0, 10))

        # uniform: жирный шрифт делает тексты кнопок разной ширины — колонки
        # должны оставаться одинаковыми
        frame.columnconfigure(0, weight=1, uniform="tools")
        frame.columnconfigure(1, weight=1, uniform="tools")

    def _build_control_frame(self):
        frame = ctk.CTkFrame(self)
        frame.pack(padx=FRAME_PAD_X, pady=(0, FRAME_PAD_Y), fill="x")

        # grid с равными весами колонок — кнопки строго одинаковой ширины
        self.btn_start = ctk.CTkButton(frame, text="● Начать запись", height=40,
                                       font=self.btn_font,
                                       fg_color=GREEN, hover_color=GREEN_HOVER,
                                       corner_radius=BTN_CORNER_RADIUS,
                                       command=self._start_recording)
        self.btn_start.grid(row=0, column=0, sticky="ew", padx=(PAD_X, 5), pady=10)

        self.btn_stop = ctk.CTkButton(frame, text="■ Остановить запись", height=40,
                                      font=self.btn_font,
                                      fg_color=DANGER, hover_color=DANGER_HOVER,
                                      corner_radius=BTN_CORNER_RADIUS,
                                      state="disabled", command=self._stop_recording)
        self.btn_stop.grid(row=0, column=1, sticky="ew", padx=(5, PAD_X), pady=10)

        frame.columnconfigure(0, weight=1, uniform="controls")
        frame.columnconfigure(1, weight=1, uniform="controls")

    def _build_status_frame(self):
        frame = ctk.CTkFrame(self)
        frame.pack(padx=FRAME_PAD_X, pady=(0, FRAME_PAD_Y), fill="x")

        # Статус записи слева, таймер длительности справа (акцентный, зелёный).
        # В одной строке — без «дыр» в блоке, когда таймер пуст.
        top = ctk.CTkFrame(frame, fg_color="transparent")
        top.pack(fill="x", padx=PAD_X, pady=(10, 2))
        self.lbl_rec_status = ctk.CTkLabel(top, text="Запись: не активна", font=ctk.CTkFont(size=14))
        self.lbl_rec_status.pack(side="left")
        self.lbl_rec_timer = ctk.CTkLabel(top, text="", font=ctk.CTkFont(size=14),
                                          text_color=ACCENT)
        self.lbl_rec_timer.pack(side="right")
        self._rec_timer_job = None
        self._rec_started_at = None

        self.lbl_queue_status = ctk.CTkLabel(frame, text="Очередь обработки: 0", font=ctk.CTkFont(size=14))
        self.lbl_queue_status.pack(anchor="w", padx=PAD_X, pady=2)

        self.lbl_current_task = ctk.CTkLabel(frame, text="Текущая задача: —", font=ctk.CTkFont(size=14),
                                             anchor="w")
        self.lbl_current_task.pack(anchor="w", padx=PAD_X, pady=(2, 10))

    def _build_log_frame(self):
        frame = ctk.CTkFrame(self)
        frame.pack(padx=FRAME_PAD_X, pady=(0, FRAME_PAD_Y), fill="both", expand=True)

        # Шапка лога: подпись слева, кнопка копирования справа (не влияет на выравнивание)
        head = ctk.CTkFrame(frame, fg_color="transparent")
        head.pack(fill="x", padx=PAD_X, pady=(PAD_X, 0))
        ctk.CTkLabel(head, text="Лог:", font=ctk.CTkFont(size=14)).pack(side="left")
        self.btn_copy_log = ctk.CTkButton(head, text="⧉", width=ICON_BTN_WIDTH, height=24,
                                          font=self.btn_font,
                                          corner_radius=BTN_CORNER_RADIUS,
                                          command=self._copy_log)
        self.btn_copy_log.pack(side="right")

        self.txt_logs = ctk.CTkTextbox(frame, height=200, state="disabled", wrap="word")
        self.txt_logs.pack(fill="both", expand=True, padx=PAD_X, pady=PAD_X)

        self.after(1000, self._update_status)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

    def _open_name_dialog(self):
        """Окно ввода имени владельца микрофона в транскрипте (метка «Я»)."""
        default = SPEAKER_SELF_NAME

        dialog = ctk.CTkToplevel(self)
        dialog.title("Имя в транскрипте (владелец микрофона)")
        dialog.geometry("460x190")
        dialog.resizable(False, False)
        dialog.transient(self)

        ctk.CTkLabel(
            dialog,
            text=(f"Метка владельца микрофона в расшифровке. Дефолт: {default}.\n"
                  "Пустое значение при сохранении = возврат к дефолту."),
            justify="left", wraplength=420, font=ctk.CTkFont(size=11),
        ).pack(anchor="w", padx=10, pady=(10, 5))

        entry = ctk.CTkEntry(dialog, width=420)
        entry.insert(0, self._saved_speaker_name or default)
        entry.pack(padx=10, pady=5)

        def save():
            text = " ".join(entry.get().split())[:SPEAKER_NAME_MAX_CHARS]
            self._saved_speaker_name = text or default
            if self.worker is not None:
                self.worker.speaker_self_name = self._saved_speaker_name
            self._save_current_settings()
            dialog.destroy()
            self.log(f"[UI] Speaker name saved: {self._saved_speaker_name}")

        btns = ctk.CTkFrame(dialog, fg_color="transparent")
        btns.pack(fill="x", padx=10, pady=(5, 10))
        ctk.CTkButton(btns, text="Сохранить", width=110,
                      font=self.btn_font, command=save).pack(side="right")
        ctk.CTkButton(btns, text="Отмена", width=90, fg_color=SECONDARY,
                      hover_color=SECONDARY_HOVER, font=self.btn_font,
                      command=dialog.destroy).pack(side="right", padx=(0, 8))

        # grab после отрисовки окна, иначе Tk может отказать («not viewable»)
        dialog.after(100, dialog.grab_set)

    def _select_obsidian_folder(self):
        path = filedialog.askdirectory(initialdir=self.obsidian_path, parent=self)
        if path:
            self.obsidian_path = path
            if self.worker is not None:
                self.worker.obsidian_dir = path
            self._save_current_settings()
            self.log(f"[UI] Obsidian vault set to: {path}")

    def _on_device_selected(self, _choice=None):
        """Сохраняет выбор аудиоустройств при выборе из выпадающего списка."""
        self._saved_mic = self.combo_mic.get().strip()
        self._saved_loopback = self.combo_loopback.get().strip()
        self._save_current_settings()

    def _on_model_selected(self, _choice=None):
        """Применяет выбранную модель к воркеру и сохраняет выбор."""
        model = self.combo_model.get().strip()
        if not model:
            return
        self._saved_ollama_model = model
        if self.worker is not None and hasattr(self.worker, "set_ollama_model"):
            self.worker.set_ollama_model(model)
        self._save_current_settings()
        self.log(f"[UI] Ollama model selected: {model}")

    def _refresh_models(self):
        """Запрашивает список установленных моделей Ollama в фоне (HTTP не блокирует UI)."""
        if self.worker is None or not hasattr(self.worker, "fetch_available_models"):
            return

        def task():
            models = self.worker.fetch_available_models()
            self.after(0, lambda: self._apply_models(models))

        threading.Thread(target=task, daemon=True).start()

    def _apply_models(self, models):
        if not models:
            self.log("[UI Warning] Ollama models list unavailable (server not reachable)")
            return

        self.combo_model.configure(values=models)
        current = self.combo_model.get().strip()
        if current in models:
            return
        # Сохранённой/дефолтной модели нет среди установленных — берём первую доступную
        self.log(f"[UI Warning] Model '{current}' is not installed in Ollama; using '{models[0]}'")
        self.combo_model.set(models[0])
        self._on_model_selected(models[0])

    def _save_current_settings(self):
        """Сохраняет выбор пользователя (папка Obsidian, устройства, модель, промпты, имя)."""
        save_settings(
            clear_keys=[
                key for key, value in (("whisper_initial_prompt", self._saved_whisper_prompt),
                                       ("summary_domain_context", self._saved_summary_context))
                if not value
            ],
            obsidian_path=self.obsidian_path,
            mic_device=self._saved_mic,
            loopback_device=self._saved_loopback,
            ollama_model=self._saved_ollama_model,
            speaker_self_name=self._saved_speaker_name,
            whisper_initial_prompt=self._saved_whisper_prompt or "",
            summary_domain_context=self._saved_summary_context or "",
        )

    def _on_close(self):
        """Перед выходом фиксирует текущее состояние устройств (в т.ч. ручной ввод)."""
        self._save_current_settings()
        self.destroy()

    def _fetch_outlook(self):
        self.lbl_outlook_info.configure(text="Поиск встречи в календаре Outlook...")
        self.update_idletasks()
        details = get_current_or_next_meeting_details(log_callback=self.log)
        if not details:
            self.lbl_outlook_info.configure(text="Ближайших встреч в календаре не найдено.")
            self.log("[UI] Outlook: встреча в окне поиска не найдена (см. [Outlook] строки выше)")
            return

        self.current_outlook_details = details
        self.entry_subject.delete(0, "end")
        self.entry_subject.insert(0, details.get("subject") or "Meeting")

        organizer = details.get("organizer") or "—"
        attendees = details.get("attendees") or []
        start = details.get("start") or "—"
        info = f"{start} | Организатор: {organizer} | Участников: {len(attendees)}"
        self.lbl_outlook_info.configure(text=info)

        meta = {
            "subject": details.get("subject"),
            "organizer": organizer,
            "attendees": attendees,
            "body": details.get("body") or "",
        }
        # Метаданные будут подхвачены воркером после завершения записи
        self._pending_meta = meta
        self._update_clear_button_state()
        self.log(f"[UI] Outlook meeting loaded: {details.get('subject')}")

    def _update_clear_button_state(self):
        """Кнопка очистки активна только когда описание встречи получено из Outlook."""
        has_body = bool((self.current_outlook_details or {}).get("body"))
        self.btn_clear_meeting.configure(state="normal" if has_body else "disabled")

    def _clear_meeting_info(self):
        """Очищает тему и данные встречи, полученные из Outlook."""
        self.current_outlook_details = None
        self._pending_meta = None
        self.entry_subject.delete(0, "end")
        self.lbl_outlook_info.configure(text="Встреча из календаря не выбрана.")
        self.btn_clear_meeting.configure(state="disabled")
        self.log("[UI] Meeting info cleared")

    def _refresh_devices(self):
        mics = get_dshow_audio_devices() or [MIC_DEVICE]
        loops = get_wasapi_audio_render_devices() or [STEREO_MIX_DEVICE or ""]
        self.combo_mic.configure(values=mics)
        self.combo_loopback.configure(values=loops)

        # Восстановить сохранённый выбор, если устройство ещё доступно
        for combo, saved, label, available in (
            (self.combo_mic, self._saved_mic, "mic", mics),
            (self.combo_loopback, self._saved_loopback, "loopback", loops),
        ):
            if saved and saved in available:
                combo.set(saved)
            elif saved:
                self.log(f"[UI Warning] Saved {label} device not found: {saved}")

        self.log(f"[UI] Devices refreshed: {len(mics)} mics, {len(loops)} loopbacks.")

    def _start_recording(self):
        subject = self.entry_subject.get().strip() or "Meeting"
        mic = self.combo_mic.get().strip() or None
        loopback = self.combo_loopback.get().strip() or None

        path = self.recorder.start(prefix=subject, mic_device=mic, stereo_mix_device=loopback)
        if self.recorder.is_recording:
            # Метаданные встречи кладём рядом с будущим .tmp-файлом
            meta = getattr(self, "_pending_meta", None) or {
                "subject": subject, "organizer": "", "attendees": [], "body": ""
            }
            try:
                with open(path + ".json", "w", encoding="utf-8") as f:
                    json.dump(meta, f, ensure_ascii=False, indent=2)
            except Exception as e:
                self.log(f"[UI Warning] Could not write metadata JSON: {e}")

            # Устройства могли быть введены вручную — фиксируем выбор
            self._saved_mic = mic
            self._saved_loopback = loopback
            self._save_current_settings()

            self.btn_start.configure(state="disabled")
            self.btn_stop.configure(state="normal")
            self.lbl_rec_status.configure(
                text=f"Запись: активна ({os.path.basename(path)})",
                text_color=ACCENT
            )
            # Запуск таймера длительности записи (акцентный крупный шрифт)
            self._rec_started_at = time.monotonic()
            self.lbl_rec_timer.configure(font=ctk.CTkFont(size=18, weight="bold"))
            self._update_rec_timer()

    def _stop_recording(self):
        self.recorder.stop()
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.lbl_rec_status.configure(text="Запись: не активна")
        # Остановка и скрытие таймера
        if self._rec_timer_job is not None:
            self.after_cancel(self._rec_timer_job)
            self._rec_timer_job = None
        self._rec_started_at = None
        self.lbl_rec_timer.configure(text="", font=ctk.CTkFont(size=14))
        # Тема и описание встречи больше не нужны — очищаем после записи
        self._clear_meeting_info()

    def _update_rec_timer(self):
        """Тикает раз в секунду, пока идёт запись; показывает MM:SS или H:MM:SS."""
        if not self.recorder.is_recording or self._rec_started_at is None:
            self._rec_timer_job = None
            return
        elapsed = int(time.monotonic() - self._rec_started_at)
        hours, rem = divmod(elapsed, 3600)
        minutes, seconds = divmod(rem, 60)
        text = f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"
        self.lbl_rec_timer.configure(text=text)
        self._rec_timer_job = self.after(1000, self._update_rec_timer)

    def _copy_log(self):
        """Копирует весь лог в буфер обмена."""
        text = "\n".join(self.all_logs)
        self.clipboard_clear()
        self.clipboard_append(text)
        self.log(f"[UI] Log copied to clipboard ({len(self.all_logs)} lines)")

    # ------------------------------------------------------------------
    # Background UI updates
    # ------------------------------------------------------------------

    def _poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.all_logs.append(msg)
                self.txt_logs.configure(state="normal")
                self.txt_logs.insert("end", msg + "\n")
                self.txt_logs.see("end")
                self.txt_logs.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(200, self._poll_log_queue)

    def _update_status(self):
        queue_files = getattr(self.worker, "queue_files", [])
        current = getattr(self.worker, "current_task", None)
        self.lbl_queue_status.configure(text=f"Очередь обработки: {len(queue_files)}")
        self.lbl_current_task.configure(
            text=f"Текущая задача: {current if current else '—'}"
        )

        model_status = getattr(self.worker, "model_status", "loading")
        model_text = {
            "loading": "загрузка в память...",
            "ready": "загружена в память",
            "unavailable": "недоступна",
        }.get(model_status, "не загружена")
        model_color = {
            "loading": WARN,
            "ready": ACCENT,
            "unavailable": DANGER,
        }.get(model_status, None)
        if model_color is None:
            self.lbl_model_status.configure(text=model_text)
        else:
            self.lbl_model_status.configure(text=model_text, text_color=model_color)

        self.after(1000, self._update_status)