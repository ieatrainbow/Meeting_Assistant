import datetime
import json
import os
import queue
import sys
import tkinter
from tkinter import filedialog

import customtkinter as ctk

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import BASE_DIR, MIC_DEVICE, STEREO_MIX_DEVICE, OBSIDIAN_DIR, OLLAMA_MODEL
from outlook_client import get_current_or_next_meeting_details
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

        self.obsidian_path = OBSIDIAN_DIR or os.path.join(BASE_DIR, "obsidian_output")
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
        self.combo_mic = ctk.CTkComboBox(frame, values=[MIC_DEVICE], width=420)
        self.combo_mic.set(MIC_DEVICE)
        self.combo_mic.grid(row=1, column=0, padx=10, sticky="ew")

        self.btn_refresh_mic = ctk.CTkButton(frame, text="↻", width=30, command=self._refresh_devices)
        self.btn_refresh_mic.grid(row=1, column=1, padx=(0, 10))

        ctk.CTkLabel(frame, text="Системный звук (loopback):").grid(row=2, column=0, sticky="w", padx=10, pady=(8, 2))
        self.combo_loopback = ctk.CTkComboBox(frame, values=[STEREO_MIX_DEVICE or ""], width=420)
        if STEREO_MIX_DEVICE:
            self.combo_loopback.set(STEREO_MIX_DEVICE)
        self.combo_loopback.grid(row=3, column=0, padx=10, sticky="ew")

        self.btn_refresh_loop = ctk.CTkButton(frame, text="↻", width=30, command=self._refresh_devices)
        self.btn_refresh_loop.grid(row=3, column=1, padx=(0, 10))
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
            self.log(f"[UI] Obsidian vault set to: {path}")

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