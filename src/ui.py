import datetime
import json
import os
import queue
import sys
import threading
import tkinter
from tkinter import filedialog

import customtkinter as ctk

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BASE_DIR, MIC_DEVICE, STEREO_MIX_DEVICE, OBSIDIAN_DIR, OLLAMA_MODEL
from outlook_client import get_current_or_next_meeting_details
from settings_store import load_settings, save_settings
from recorder import get_dshow_audio_devices, get_wasapi_audio_render_devices

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


class AppUI(ctk.CTk):
    def __init__(self, recorder, worker, log_queue=None, logger_callback=None):
        super().__init__()

        self.recorder = recorder
        self.worker = worker
        self.log_queue = log_queue or queue.Queue()
        self.log = logger_callback or print

        # Восстановление пользовательских настроек (settings.json), иначе — из .env
        settings = load_settings()
        saved_obsidian = settings["obsidian_path"]
        self.obsidian_path = saved_obsidian or OBSIDIAN_DIR or os.path.join(BASE_DIR, "obsidian_output")
        self._saved_mic = settings["mic_device"]
        self._saved_loopback = settings["loopback_device"]
        self._saved_ollama_model = settings["ollama_model"]
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
        self.geometry("680x760")
        self.resizable(False, False)

        self._build_header()
        self._build_meeting_frame()
        self._build_device_frame()
        self._build_control_frame()
        self._build_status_frame()
        self._build_log_frame()
        self.after(200, self._poll_log_queue)
        self.after(150, self._refresh_devices)
        self.after(150, self._refresh_models)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(padx=20, pady=(10, 5), fill="x")

        self.lbl_title = ctk.CTkLabel(
            header, text="Meeting Assistant",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        self.lbl_title.pack(side="left")

        self.btn_select_obsidian = ctk.CTkButton(
            header, text="Папка Obsidian...", width=150,
            command=self._select_obsidian_folder
        )
        self.btn_select_obsidian.pack(side="right")

    def _build_meeting_frame(self):
        frame = ctk.CTkFrame(self)
        frame.pack(padx=20, pady=5, fill="x")

        ctk.CTkLabel(frame, text="Тема встречи:").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 2))
        self.entry_subject = ctk.CTkEntry(frame, width=380, placeholder_text="Введите тему или получите из Outlook")
        self.entry_subject.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10)

        self.btn_outlook = ctk.CTkButton(frame, text="Из Outlook", width=120, command=self._fetch_outlook)
        self.btn_outlook.grid(row=1, column=2, padx=(10, 10), pady=(0, 10))

        self.lbl_outlook_info = ctk.CTkLabel(frame, text="Встреча из календаря не выбрана.", justify="left",
                                             font=ctk.CTkFont(size=11))
        self.lbl_outlook_info.grid(row=2, column=0, columnspan=3, sticky="w", padx=10, pady=(0, 10))
        frame.columnconfigure(0, weight=1)

    def _build_device_frame(self):
        frame = ctk.CTkFrame(self)
        frame.pack(padx=20, pady=5, fill="x")

        ctk.CTkLabel(frame, text="Микрофон:").grid(row=0, column=0, sticky="w", padx=10, pady=(10, 2))
        self.combo_mic = ctk.CTkComboBox(frame, values=[MIC_DEVICE], width=420,
                                         command=self._on_device_selected)
        self.combo_mic.set(self._saved_mic or MIC_DEVICE)
        self.combo_mic.grid(row=1, column=0, padx=10, sticky="ew")

        self.btn_refresh_mic = ctk.CTkButton(frame, text="↻", width=30, command=self._refresh_devices)
        self.btn_refresh_mic.grid(row=1, column=1, padx=(0, 10))

        ctk.CTkLabel(frame, text="Системный звук (loopback):").grid(row=2, column=0, sticky="w", padx=10, pady=(8, 2))
        self.combo_loopback = ctk.CTkComboBox(frame, values=[STEREO_MIX_DEVICE or ""], width=420,
                                              command=self._on_device_selected)
        if self._saved_loopback or STEREO_MIX_DEVICE:
            self.combo_loopback.set(self._saved_loopback or STEREO_MIX_DEVICE)
        self.combo_loopback.grid(row=3, column=0, padx=10, sticky="ew")

        self.btn_refresh_loop = ctk.CTkButton(frame, text="↻", width=30, command=self._refresh_devices)
        self.btn_refresh_loop.grid(row=3, column=1, padx=(0, 10))

        ctk.CTkLabel(frame, text="Модель Ollama:").grid(row=4, column=0, sticky="w", padx=10, pady=(8, 2))
        self.combo_model = ctk.CTkComboBox(
            frame, values=[self._saved_ollama_model or OLLAMA_MODEL], width=420,
            command=self._on_model_selected
        )
        self.combo_model.set(self._saved_ollama_model or OLLAMA_MODEL)
        self.combo_model.grid(row=5, column=0, padx=10, sticky="ew")

        self.btn_refresh_models = ctk.CTkButton(frame, text="↻", width=30, command=self._refresh_models)
        self.btn_refresh_models.grid(row=5, column=1, padx=(0, 10))
        frame.columnconfigure(0, weight=1)

    def _build_control_frame(self):
        frame = ctk.CTkFrame(self)
        frame.pack(padx=20, pady=5, fill="x")

        self.btn_start = ctk.CTkButton(frame, text="● Начать запись", height=40,
                                       font=ctk.CTkFont(size=14, weight="bold"),
                                       fg_color="#2f8f4e", hover_color="#256b3d",
                                       command=self._start_recording)
        self.btn_start.pack(side="left", padx=10, pady=10, expand=True, fill="x")

        self.btn_stop = ctk.CTkButton(frame, text="■ Остановить запись", height=40,
                                      font=ctk.CTkFont(size=14, weight="bold"),
                                      fg_color="#b03a3a", hover_color="#8a2c2c",
                                      state="disabled", command=self._stop_recording)
        self.btn_stop.pack(side="left", padx=10, pady=10, expand=True, fill="x")

    def _build_status_frame(self):
        frame = ctk.CTkFrame(self)
        frame.pack(padx=20, pady=5, fill="x")

        self.lbl_rec_status = ctk.CTkLabel(frame, text="Запись: не активна", font=ctk.CTkFont(size=12))
        self.lbl_rec_status.pack(anchor="w", padx=10, pady=(8, 2))

        self.lbl_queue_status = ctk.CTkLabel(frame, text="Очередь обработки: 0", font=ctk.CTkFont(size=12))
        self.lbl_queue_status.pack(anchor="w", padx=10, pady=2)

        self.lbl_current_task = ctk.CTkLabel(frame, text="Текущая задача: —", font=ctk.CTkFont(size=12),
                                             anchor="w")
        self.lbl_current_task.pack(anchor="w", padx=10, pady=(2, 2))

        self.lbl_model_status = ctk.CTkLabel(frame, text="Модель Ollama: загрузка...", font=ctk.CTkFont(size=12),
                                             anchor="w")
        self.lbl_model_status.pack(anchor="w", padx=10, pady=(2, 8))

    def _build_log_frame(self):
        frame = ctk.CTkFrame(self)
        frame.pack(padx=20, pady=(5, 15), fill="both", expand=True)

        self.txt_logs = ctk.CTkTextbox(frame, height=200, state="disabled", wrap="word")
        self.txt_logs.pack(fill="both", expand=True, padx=10, pady=10)

        self.after(1000, self._update_status)

    # ------------------------------------------------------------------
    # Handlers
    # ------------------------------------------------------------------

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
        """Сохраняет выбор пользователя (папка Obsidian, устройства, модель) в settings.json."""
        save_settings(
            obsidian_path=self.obsidian_path,
            mic_device=self._saved_mic,
            loopback_device=self._saved_loopback,
            ollama_model=self._saved_ollama_model,
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
        self.log(f"[UI] Outlook meeting loaded: {details.get('subject')}")

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
                text_color="#2f8f4e"
            )

    def _stop_recording(self):
        self.recorder.stop()
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.lbl_rec_status.configure(text="Запись: не активна")
        self._pending_meta = None

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
            "loading": "Модель Ollama: загрузка в VRAM...",
            "ready": "Модель Ollama: готова",
            "unavailable": "Модель Ollama: недоступна",
        }.get(model_status, "Модель Ollama: —")
        model_color = {
            "loading": "#d0a016",
            "ready": "#2f8f4e",
            "unavailable": "#b03a3a",
        }.get(model_status, None)
        if model_color is None:
            self.lbl_model_status.configure(text=model_text)
        else:
            self.lbl_model_status.configure(text=model_text, text_color=model_color)

        self.after(1000, self._update_status)