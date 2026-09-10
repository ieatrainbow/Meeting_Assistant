import datetime
import os
import sys
import threading
import wave

import numpy as np
import pyaudiowpatch as pyaudio

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import INBOX_DIR, MIC_DEVICE, STEREO_MIX_DEVICE, TARGET_SAMPLE_RATE

TARGET_RATE = TARGET_SAMPLE_RATE  # Частота дискретизации итогового файла


def get_dshow_audio_devices():
    """Возвращает список доступных физических микрофонов."""
    devices = []
    try:
        p = pyaudio.PyAudio()
        for i in range(p.get_device_count()):
            dev = p.get_device_info_by_index(i)
            if dev.get('maxInputChannels', 0) > 0 and not dev.get('isLoopbackDevice', False):
                devices.append(dev['name'])
        p.terminate()
    except Exception as e:
        print(f"[Mic Scan Error] {repr(e)}")
    return list(dict.fromkeys(devices))


def get_wasapi_audio_render_devices():
    """Возвращает список всех устройств воспроизведения через WASAPI Loopback."""
    devices = []
    try:
        p = pyaudio.PyAudio()
        for dev in p.get_loopback_device_info_generator():
            devices.append(dev['name'])
        p.terminate()
    except Exception as e:
        print(f"[Speaker Scan Error] {repr(e)}")
    return list(dict.fromkeys(devices))


def _to_mono_16k(data, channels, in_rate):
    """Конвертирует сырой аудиочанк (paFloat32) в mono 16 kHz (float32 numpy)."""
    samples = np.frombuffer(data, dtype=np.float32)
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if in_rate != TARGET_RATE and len(samples):
        duration = len(samples) / in_rate
        target_len = int(duration * TARGET_RATE)
        if target_len <= 0:
            return np.array([], dtype=np.float32)
        indices = np.linspace(0, len(samples) - 1, target_len)
        samples = np.interp(indices, np.arange(len(samples)), samples).astype(np.float32)
    return samples


class AudioRecorder:
    def __init__(self, logger_callback=None):
        self.is_recording = False
        self.record_thread = None
        self.current_file = None
        self.temp_file = None
        self.log = logger_callback or print
        self.mic_device = MIC_DEVICE
        self.stereo_mix_device = STEREO_MIX_DEVICE

        self.mic_buf = []  # список чанков np.float32 16 kHz (склейка только в финале)
        self.loop_buf = []
        self._buf_lock = threading.Lock()
        self._stop_event = threading.Event()

    def start(self, prefix="Meeting", mic_device=None, stereo_mix_device=None, wasapi_device=None):
        if self.is_recording:
            self.log("[Recorder] Recording is already in progress.")
            return self.current_file

        mic_name = mic_device or self.mic_device
        spk_name = wasapi_device or stereo_mix_device

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")
        safe_prefix = "".join(c for c in prefix if c.isalnum() or c in (' ', '_', '-')).strip()
        if not safe_prefix:
            safe_prefix = "Unplanned_Meeting"

        filename = f"{timestamp}_{safe_prefix}.wav"
        self.current_file = os.path.join(INBOX_DIR, filename)
        self.temp_file = self.current_file + ".tmp"

        self.mic_buf = []
        self.loop_buf = []
        self._stop_event.clear()
        self.is_recording = True

        self.record_thread = threading.Thread(
            target=self._record_loop,
            args=(self.temp_file, mic_name, spk_name),
            daemon=True
        )
        self.record_thread.start()

        self.log(f"[Recorder] Recording started: Mic ('{mic_name}') + Output ('{spk_name}')")
        return self.current_file

    def _find_mic_device(self, p, mic_name):
        """Ищет устройство ввода по подстроке имени."""
        # Убираем dshow-префикс 'audio=', если он задан в конфиге
        if mic_name:
            mic_name = mic_name.replace("audio=", "").strip()
        else:
            self.log("[Recorder Warning] No microphone device selected.")
            return None
        for i in range(p.get_device_count()):
            dev = p.get_device_info_by_index(i)
            if dev.get('maxInputChannels', 0) > 0 and not dev.get('isLoopbackDevice', False):
                if mic_name.lower() in dev['name'].lower():
                    return dev
        self.log(f"[Recorder Warning] Microphone not found: {mic_name}")
        return None

    def _find_loopback_device(self, p, spk_name):
        """Ищет WASAPI loopback-устройство по подстроке имени."""
        devices = list(p.get_loopback_device_info_generator())
        if not devices:
            self.log("[Recorder Warning] No WASAPI loopback devices available.")
            return None
        if spk_name:
            spk_name = spk_name.replace("audio=", "").strip()
            for dev in devices:
                if spk_name.lower() in dev['name'].lower():
                    return dev
        self.log(f"[Recorder Warning] Output device not found ('{spk_name}'), using default loopback.")
        return devices[0]

    def _open_input_stream(self, p, dev, callback):
        """Открывает входной поток с фоллбеком по частоте дискретизации."""
        # У loopback-устройств активные каналы лежат в maxInputChannels (WASAPI),
        # maxOutputChannels может быть 0, что даёт 'Invalid audio channels'.
        channels = int(dev.get('maxInputChannels') or 0) or int(dev.get('maxOutputChannels') or 1)
        rates = [int(dev.get('defaultSampleRate') or 0)]
        rates += [r for r in (48000, 44100, 96000) if r not in rates]
        last_error = None
        for rate in rates:
            if rate <= 0:
                continue
            try:
                return p.open(
                    format=pyaudio.paFloat32,
                    channels=channels,
                    rate=rate,
                    input=True,
                    input_device_index=dev['index'],
                    frames_per_buffer=1024,
                    stream_callback=lambda in_data, frame_count, time_info, status,
                        channels=channels, r=rate: callback(in_data, frame_count, time_info, status, channels, r)
                )
            except Exception as e:
                last_error = e
                self.log(f"[Recorder Warning] Open failed (ch={channels}, rate={rate}): {e}")
        raise RuntimeError(f"Could not open stream for '{dev['name']}': {last_error}")


    def _mic_callback(self, in_data, frame_count, time_info, status, channels, rate):
        chunk = _to_mono_16k(in_data, channels, rate)
        with self._buf_lock:
            self.mic_buf.append(chunk)
        return (in_data, pyaudio.paContinue)

    def _loop_callback(self, in_data, frame_count, time_info, status, channels, rate):
        chunk = _to_mono_16k(in_data, channels, rate)
        with self._buf_lock:
            self.loop_buf.append(chunk)
        return (in_data, pyaudio.paContinue)

    def _record_loop(self, path, mic_name, spk_name):
        """Захват аудио с микрофона и системного вывода, микширование и запись WAV 16 kHz."""
        p = pyaudio.PyAudio()
        mic_stream = None
        loop_stream = None

        try:
            mic_dev = self._find_mic_device(p, mic_name)
            loop_dev = self._find_loopback_device(p, spk_name)

            if mic_dev is None and loop_dev is None:
                raise RuntimeError("No audio input or loopback devices available.")

            if mic_dev is not None:
                mic_stream = self._open_input_stream(p, mic_dev, self._mic_callback)

            if loop_dev is not None:
                loop_stream = self._open_input_stream(p, loop_dev, self._loop_callback)

            self.log("[Recorder] Audio capture active.")
            self._stop_event.wait()

            if mic_stream is not None:
                mic_stream.stop_stream()
                mic_stream.close()
            if loop_stream is not None:
                loop_stream.stop_stream()
                loop_stream.close()

        except Exception as e:
            self.log(f"[Recorder Error] Capture failed: {e}")
            self.is_recording = False
        finally:
            p.terminate()

        self._finalize_file(path)

    def _finalize_file(self, path):
        """Микширует буферы и пишет итоговый WAV 16 kHz mono."""
        try:
            with self._buf_lock:
                mic_chunks, loop_chunks = self.mic_buf, self.loop_buf
                # Отдаём себе копии ссылок и сразу сбрасываем, чтобы не держать блокировку
                self.mic_buf, self.loop_buf = [], []

            # Склейка один раз: O(N) вместо O(N^2) при конкатенации в callback
            mic = np.concatenate(mic_chunks) if mic_chunks else np.array([], dtype=np.float32)
            loop = np.concatenate(loop_chunks) if loop_chunks else np.array([], dtype=np.float32)

            if len(mic) == 0 and len(loop) == 0:
                self.log("[Recorder Warning] No audio captured, file skipped.")
                self.is_recording = False
                return

            # Микширование: выравниваем по длине, усредняем активные каналы
            if len(mic) and len(loop):
                n = min(len(mic), len(loop))
                mixed = (mic[:n] + loop[:n]) / 2.0
            else:
                mixed = mic if len(mic) else loop
            mixed = np.clip(mixed, -1.0, 1.0)

            pcm = (mixed * 32767.0).astype(np.int16)

            with wave.open(path, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(TARGET_RATE)
                wf.writeframes(pcm.tobytes())

            # Атомарная замена .tmp -> .wav
            final_path = path[:-len(".tmp")]
            if os.path.exists(final_path):
                os.remove(final_path)
            os.replace(path, final_path)

            self.log(f"[Recorder] Recording saved: {os.path.basename(final_path)}")
        except Exception as e:
            self.log(f"[Recorder Error] Failed to finalize file: {e}")
        finally:
            self.is_recording = False

    def stop(self):
        """Останавливает запись и дожидается завершения потока захвата."""
        if not self.is_recording:
            self.log("[Recorder] No recording in progress.")
            return None

        self._stop_event.set()
        if self.record_thread and self.record_thread.is_alive():
            self.record_thread.join(timeout=10)
        return self.current_file