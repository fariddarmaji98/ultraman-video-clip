#!/usr/bin/env python3
"""
ClipMaker v4 — Fixed window, scrollable content, structured mm:ss time inputs.
Photo + Audio/Video clip tool with built-in player + YouTube download.
Requires: customtkinter, pygame-ce, Pillow, ffmpeg+ffprobe, yt-dlp.
"""
import customtkinter as ctk
import subprocess
import threading
import re
import os
import json
import yt_dlp
import pygame
from PIL import Image, ImageDraw, ImageTk
from tkinter import filedialog, messagebox

APP_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "hermes", "cache", "scratch")
CONFIG_PATH = os.path.join(APP_DIR, "clipmaker_config.json")

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

TEXT_DIM = "#888888"
SEEK_BACK = 5
SEEK_FWD = 30


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f)
    except Exception:
        pass


def fmt_time(seconds):
    if seconds is None:
        return "00:00"
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def parse_time_inputs(min_entry, sec_entry):
    """Read structured minute/second entry widgets. Return float seconds."""
    try:
        m = int(min_entry.get().strip() or "0")
    except ValueError:
        raise ValueError("Menit harus angka bulat.")
    try:
        s = int(sec_entry.get().strip() or "0")
    except ValueError:
        raise ValueError("Detik harus angka bulat.")
    if s >= 60:
        m += s // 60
        s = s % 60
    return float(m * 60 + s)


def ffprobe_duration(path):
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            stderr=subprocess.STDOUT, text=True
        )
        return float(out.strip())
    except Exception:
        return None


def ffprobe_has_video(path):
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-select_streams", "v",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
            stderr=subprocess.STDOUT, text=True
        )
        return "video" in out.strip()
    except Exception:
        return False


def extract_video_frame(path, timestamp=0, max_w=500):
    tmp = os.path.join(APP_DIR, "_player_frame.png")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{timestamp}", "-i", path,
             "-frames:v", "1", "-vf", f"scale={max_w}:-1", tmp],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5
        )
        if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            return tmp
    except Exception:
        pass
    return None


def generate_waveform_image(path, max_w=500, h=100):
    tmp = os.path.join(APP_DIR, "_player_waveform.png")
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", path,
             "-filter_complex", f"showwavespic=s={max_w}x{h}:colors=#1f6aa5|#ffffff",
             "-frames:v", "1", tmp],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10
        )
        if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            return tmp
    except Exception:
        pass
    return None


def generate_audio_placeholder(max_w=500, h=100):
    tmp = os.path.join(APP_DIR, "_player_placeholder.png")
    try:
        img = Image.new("RGB", (max_w, h), "#1a1a1a")
        d = ImageDraw.Draw(img)
        cx, cy = max_w // 2, h // 2
        d.ellipse([cx - 8, cy - 20, cx + 8, cy - 4], fill="#1f6aa5")
        d.line([cx + 8, cy - 20, cx + 8, cy + 12], fill="#1f6aa5", width=3)
        d.ellipse([cx + 2, cy + 6, cx + 18, cy + 16], fill="#1f6aa5")
        d.text((cx - 50, cy + 25), "AUDIO", fill="#555555")
        img.save(tmp)
        return tmp
    except Exception:
        return None


class ClipMaker(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("ClipMaker")
        self.geometry("560x760")
        self.resizable(False, False)
        cfg = load_config()
        self.source_duration = 0.0
        self.audio_loaded = False
        self.is_playing = False
        self.is_seeking = False
        self.playback_start_offset = 0.0
        self.playback_start_wall = 0.0
        self.current_path = None
        self.is_video = False
        self._preview_photo = None

        try:
            pygame.mixer.init()
            pygame.mixer.music.set_endevent(pygame.USEREVENT)
        except Exception:
            pass

        # === Scrollable content frame ===
        self.scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        self.scroll.pack(fill="both", expand=True)

        pad = {"padx": 20, "pady": (0, 8)}

        # --- Photo ---
        ctk.CTkLabel(self.scroll, text="Background Foto").pack(anchor="w", padx=20, pady=(16, 4))
        self.foto_row = ctk.CTkFrame(self.scroll, fg_color="transparent")
        self.foto_row.pack(fill="x", **pad)
        self.foto_entry = ctk.CTkEntry(self.foto_row, placeholder_text="Pilih file foto (jpg/png)")
        self.foto_entry.pack(side="left", fill="x", expand=True)
        self.foto_entry.insert(0, cfg.get("foto", ""))
        ctk.CTkButton(self.foto_row, text="Browse", width=80, command=self.browse_foto).pack(side="right", padx=(8, 0))

        # --- Audio/Video ---
        ctk.CTkLabel(self.scroll, text="Audio / Video Sumber").pack(anchor="w", padx=20, pady=(8, 4))
        self.av_row = ctk.CTkFrame(self.scroll, fg_color="transparent")
        self.av_row.pack(fill="x", **pad)
        self.av_entry = ctk.CTkEntry(self.av_row, placeholder_text="Pilih file (mp3/mp4/wav/m4a)")
        self.av_entry.pack(side="left", fill="x", expand=True)
        self.av_entry.insert(0, cfg.get("av", ""))
        ctk.CTkButton(self.av_row, text="Browse", width=80, command=self.browse_av).pack(side="right", padx=(8, 0))

        # --- YouTube Download ---
        ctk.CTkLabel(self.scroll, text="Atau Unduh dari YouTube").pack(anchor="w", padx=20, pady=(4, 4))
        self.yt_frame = ctk.CTkFrame(self.scroll, fg_color="transparent")
        self.yt_frame.pack(fill="x", **pad)
        self.yt_entry = ctk.CTkEntry(self.yt_frame, placeholder_text="Paste URL YouTube...")
        self.yt_entry.pack(side="left", fill="x", expand=True)
        self.yt_btn = ctk.CTkButton(self.yt_frame, text="Unduh", width=80, command=self.download_youtube)
        self.yt_btn.pack(side="right", padx=(8, 0))

        # === PLAYER ===
        ctk.CTkLabel(self.scroll, text="Player", font=ctk.CTkFont(size=14, weight="bold")).pack(anchor="w", padx=20, pady=(12, 4))

        self.preview_label = ctk.CTkLabel(self.scroll, text="", height=110)
        self.preview_label.pack(fill="x", padx=20, pady=(0, 4))

        self.player_row = ctk.CTkFrame(self.scroll, fg_color="transparent")
        self.player_row.pack(fill="x", **pad)

        self.play_btn = ctk.CTkButton(self.player_row, text="\u25b6 Play", width=90, state="disabled",
                                      command=self.toggle_play)
        self.play_btn.pack(side="left")

        self.time_label = ctk.CTkLabel(self.player_row, text="00:00 / --:--",
                                       font=ctk.CTkFont(size=13), text_color=TEXT_DIM)
        self.time_label.pack(side="left", padx=(12, 0))

        ctk.CTkButton(self.player_row, text="\u23ea -5s", width=60, state="disabled",
                      command=lambda: self.seek_relative(-SEEK_BACK)).pack(side="right")
        ctk.CTkButton(self.player_row, text="+30s \u23e9", width=70, state="disabled",
                      command=lambda: self.seek_relative(SEEK_FWD)).pack(side="right", padx=(8, 0))

        self.seek_bar = ctk.CTkSlider(self.player_row, height=8, command=self.on_seek, state="disabled")
        self.seek_bar.pack(side="left", fill="x", expand=True, padx=(12, 8))
        self.seek_bar.set(0)

        # --- Start / End: structured mm:ss inputs ---
        self.se_frame = ctk.CTkFrame(self.scroll, fg_color="transparent")
        self.se_frame.pack(fill="x", padx=20, pady=(8, 8))

        # Start
        left = ctk.CTkFrame(self.se_frame, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(left, text="Start").pack(anchor="w")
        start_inner = ctk.CTkFrame(left, fg_color="transparent")
        start_inner.pack(fill="x")
        self.start_min = ctk.CTkEntry(start_inner, width=50, placeholder_text="mm", justify="center")
        self.start_min.pack(side="left")
        ctk.CTkLabel(start_inner, text=":", width=10, justify="center").pack(side="left")
        self.start_sec = ctk.CTkEntry(start_inner, width=50, placeholder_text="ss", justify="center")
        self.start_sec.pack(side="left", padx=(0, 8))

        # End
        right = ctk.CTkFrame(self.se_frame, fg_color="transparent")
        right.pack(side="right", fill="x", expand=True, padx=(12, 0))
        ctk.CTkLabel(right, text="End").pack(anchor="w")
        end_inner = ctk.CTkFrame(right, fg_color="transparent")
        end_inner.pack(fill="x")
        self.end_min = ctk.CTkEntry(end_inner, width=50, placeholder_text="mm", justify="center")
        self.end_min.pack(side="left")
        ctk.CTkLabel(end_inner, text=":", width=10, justify="center").pack(side="left")
        self.end_sec = ctk.CTkEntry(end_inner, width=50, placeholder_text="ss", justify="center")
        self.end_sec.pack(side="left", padx=(0, 8))

        # Restore saved start/end
        prev_start = cfg.get("start", "")
        if ":" in prev_start:
            pm, ps = prev_start.split(":", 1)
            self.start_min.insert(0, pm)
            self.start_sec.insert(0, ps)
        prev_end = cfg.get("end", "")
        if ":" in prev_end:
            pm, ps = prev_end.split(":", 1)
            self.end_min.insert(0, pm)
            self.end_sec.insert(0, ps)

        # Tools row
        self.tools_row = ctk.CTkFrame(self.scroll, fg_color="transparent")
        self.tools_row.pack(fill="x", padx=20, pady=(0, 8))
        ctk.CTkButton(self.tools_row, text="Set Start = Now", width=120, state="disabled",
                      command=self.set_start_from_current).pack(side="left")
        ctk.CTkButton(self.tools_row, text="Set End = Now", width=120, state="disabled",
                      command=self.set_end_from_current).pack(side="left", padx=(8, 0))
        self.preview_btn = ctk.CTkButton(self.tools_row, text="\u25b6 Preview Clip", width=130, state="disabled",
                                         command=self.preview_clip)
        self.preview_btn.pack(side="right")

        # --- Generate ---
        self.gen_btn = ctk.CTkButton(self.scroll, text="Generate Clip", height=42,
                                     font=ctk.CTkFont(size=16, weight="bold"), command=self.on_generate)
        self.gen_btn.pack(fill="x", padx=20, pady=(12, 8))

        # --- Progress ---
        self.progress = ctk.CTkProgressBar(self.scroll, height=8)
        self.progress.pack(fill="x", padx=20, pady=(0, 4))
        self.progress.set(0)

        self.status = ctk.CTkLabel(self.scroll, text="Siap.", text_color=TEXT_DIM, font=ctk.CTkFont(size=12))
        self.status.pack(anchor="w", padx=20, pady=(0, 16))

        self.after(200, self._tick)

    # === Player ===
    def _enable_player(self):
        self.play_btn.configure(state="normal")
        self.seek_bar.configure(state="normal")
        for w in self.player_row.winfo_children():
            if isinstance(w, ctk.CTkButton) and w.cget("state") == "disabled":
                w.configure(state="normal")
        for w in self.tools_row.winfo_children():
            if isinstance(w, ctk.CTkButton) and w.cget("state") == "disabled":
                w.configure(state="normal")

    def toggle_play(self):
        if not self.audio_loaded:
            return
        if self.is_playing:
            self._pause()
        else:
            self._play()

    def _play(self):
        if not self.audio_loaded:
            return
        try:
            offset = self.playback_start_offset
            pygame.mixer.music.play(start=offset)
            self.is_playing = True
            self.playback_start_wall = pygame.time.get_ticks() / 1000.0
            self.play_btn.configure(text="\u23f8 Pause")
        except Exception as e:
            messagebox.showerror("Error", str(e))

    def _pause(self):
        if not self.is_playing:
            return
        pygame.mixer.music.pause()
        self.is_playing = False
        self.playback_start_offset = self._get_playback_position()
        self.play_btn.configure(text="\u25b6 Play")

    def _get_playback_position(self):
        if self.is_playing:
            elapsed = (pygame.time.get_ticks() / 1000.0) - self.playback_start_wall
            return self.playback_start_offset + elapsed
        return self.playback_start_offset

    def _tick(self):
        if self.is_playing:
            pos = self._get_playback_position()
            if self.source_duration > 0:
                if pos >= self.source_duration:
                    self._on_playback_end()
                else:
                    self.time_label.configure(text=f"{fmt_time(pos)} / {fmt_time(self.source_duration)}")
                    if not self.is_seeking:
                        self.seek_bar.set(pos / self.source_duration if self.source_duration > 0 else 0)
                    if self.is_video and int(pos) != int(getattr(self, "_last_frame_sec", -1)):
                        self._last_frame_sec = int(pos)
                        threading.Thread(target=self._update_video_frame, args=(pos,), daemon=True).start()
        self.after(200, self._tick)

    def _on_playback_end(self):
        self.is_playing = False
        self.playback_start_offset = 0.0
        self.play_btn.configure(text="\u25b6 Play")
        self.seek_bar.set(0)
        self.time_label.configure(text=f"00:00 / {fmt_time(self.source_duration)}")

    def on_seek(self, value):
        if not self.audio_loaded or self.source_duration <= 0:
            return
        target = value * self.source_duration
        self.playback_start_offset = target
        if self.is_playing:
            pygame.mixer.music.stop()
            pygame.mixer.music.play(start=target)
            self.playback_start_wall = pygame.time.get_ticks() / 1000.0
        self.time_label.configure(text=f"{fmt_time(target)} / {fmt_time(self.source_duration)}")
        if self.is_video:
            self._last_frame_sec = int(target)
            threading.Thread(target=self._update_video_frame, args=(target,), daemon=True).start()

    def seek_relative(self, delta):
        if not self.audio_loaded or self.source_duration <= 0:
            return
        was_playing = self.is_playing
        target = max(0, min(self._get_playback_position() + delta, self.source_duration))
        self.playback_start_offset = target
        if was_playing:
            pygame.mixer.music.stop()
            pygame.mixer.music.play(start=target)
            self.playback_start_wall = pygame.time.get_ticks() / 1000.0
            self.is_playing = True
        self.seek_bar.set(target / self.source_duration)
        self.time_label.configure(text=f"{fmt_time(target)} / {fmt_time(self.source_duration)}")
        if self.is_video:
            self._last_frame_sec = int(target)
            threading.Thread(target=self._update_video_frame, args=(target,), daemon=True).start()

    def set_start_from_current(self):
        pos = self._get_playback_position()
        m, s = divmod(int(pos), 60)
        self.start_min.delete(0, "end")
        self.start_min.insert(0, str(m))
        self.start_sec.delete(0, "end")
        self.start_sec.insert(0, str(s))

    def set_end_from_current(self):
        pos = self._get_playback_position()
        m, s = divmod(int(pos), 60)
        self.end_min.delete(0, "end")
        self.end_min.insert(0, str(m))
        self.end_sec.delete(0, "end")
        self.end_sec.insert(0, str(s))

    # === Load audio ===
    def _load_audio(self, path):
        if not os.path.isfile(path):
            return
        self.current_path = path
        threading.Thread(target=self._probe_and_load, args=(path,), daemon=True).start()

    def _probe_and_load(self, path):
        dur = ffprobe_duration(path)
        if dur is None or dur <= 0:
            self.after(0, lambda: self.status.configure(text="Gagal baca durasi. File corrupt?"))
            self.after(0, lambda: messagebox.showerror("Error", "Tidak bisa baca durasi file."))
            return
        self.source_duration = dur
        self.is_video = ffprobe_has_video(path)

        if self.is_video:
            frame_path = extract_video_frame(path, timestamp=0)
        else:
            frame_path = generate_waveform_image(path)
            if not frame_path:
                frame_path = generate_audio_placeholder()
        if frame_path:
            self.after(0, lambda p=frame_path: self._show_preview(p))

        load_path = path
        if self.is_video:
            tmp_wav = os.path.join(APP_DIR, "_player_audio.wav")
            self.after(0, lambda: self.status.configure(text="Extracting audio dari video..."))
            try:
                subprocess.run(
                    ["ffmpeg", "-y", "-i", path, "-vn", "-acodec", "pcm_s16le",
                     "-ar", "44100", "-ac", "2", tmp_wav],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120
                )
                if os.path.exists(tmp_wav) and os.path.getsize(tmp_wav) > 0:
                    load_path = tmp_wav
                else:
                    self.after(0, lambda: messagebox.showerror("Error", "Gagal extract audio dari video."))
                    return
            except Exception as e:
                self.after(0, lambda: messagebox.showerror("Error", f"Gagal extract audio:\n{e}"))
                return

        try:
            if pygame.mixer.music.get_busy():
                pygame.mixer.music.stop()
            pygame.mixer.music.load(load_path)
            self.audio_loaded = True
            self.playback_start_offset = 0.0
            self.is_playing = False
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", f"Gagal load audio:\n{e}"))
            return

        self.after(0, lambda: self._enable_player())
        self.after(0, lambda: self.time_label.configure(text=f"00:00 / {fmt_time(dur)}"))
        self.after(0, lambda: self.seek_bar.set(0))
        self.after(0, lambda: self.play_btn.configure(text="\u25b6 Play"))
        kind = "Video" if self.is_video else "Audio"
        self.after(0, lambda: self.status.configure(text=f"{kind} siap. Total: {fmt_time(dur)}. Tekan Play."))

    def _show_preview(self, img_path):
        try:
            img = Image.open(img_path)
            if img.width > 500:
                ratio = 500 / img.width
                img = img.resize((500, int(img.height * ratio)), Image.LANCZOS)
            self._preview_photo = ImageTk.PhotoImage(img)
            self.preview_label.configure(image=self._preview_photo, text="")
        except Exception:
            self.preview_label.configure(image=None, text="(preview gagal)")

    def _update_video_frame(self, timestamp):
        if not self.is_video or not self.current_path:
            return
        ts = int(timestamp)
        frame_path = extract_video_frame(self.current_path, timestamp=ts)
        if frame_path:
            self.after(0, lambda p=frame_path: self._show_preview(p))

    # === Browse handlers ===
    def browse_foto(self):
        f = filedialog.askopenfilename(title="Pilih Foto",
                                       filetypes=[("Image", "*.jpg *.jpeg *.png *.bmp *.webp")])
        if f:
            self.foto_entry.delete(0, "end")
            self.foto_entry.insert(0, f)

    def browse_av(self):
        f = filedialog.askopenfilename(
            title="Pilih Audio/Video",
            filetypes=[("Audio/Video", "*.mp3 *.mp4 *.wav *.m4a *.aac *.flac *.mkv *.avi"), ("All", "*.*")])
        if f:
            self.av_entry.delete(0, "end")
            self.av_entry.insert(0, f)
            self.status.configure(text="Memuat audio...")
            self._load_audio(f)

    # === YouTube ===
    def download_youtube(self):
        url = self.yt_entry.get().strip()
        if not url:
            messagebox.showerror("Error", "Masukkan URL YouTube.")
            return
        if not re.match(r"https?://", url):
            messagebox.showerror("Error", "URL tidak valid.")
            return
        save_dir = filedialog.askdirectory(title="Pilih folder simpan")
        if not save_dir:
            return
        self.yt_btn.configure(state="disabled", text="Downloading...")
        self.status.configure(text="Mengunduh dari YouTube...")
        self.progress.set(0)
        threading.Thread(target=self._yt_download, args=(url, save_dir), daemon=True).start()

    def _yt_download(self, url, save_dir):
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(save_dir, "%(title)s.%(ext)s"),
            "quiet": True, "no_warnings": True,
            "progress_hooks": [self._yt_progress_hook],
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filepath = ydl.prepare_filename(info)
                if not os.path.exists(filepath):
                    base = os.path.splitext(filepath)[0]
                    for ext in (".webm", ".m4a", ".mp3", ".opus", ".mp4"):
                        candidate = base + ext
                        if os.path.exists(candidate):
                            filepath = candidate
                            break
            self.after(0, lambda: self.av_entry.delete(0, "end"))
            self.after(0, lambda: self.av_entry.insert(0, filepath))
            self.after(0, lambda: self.progress.set(1))
            self.after(0, lambda: self.status.configure(text=f"Terunduh: {os.path.basename(filepath)}"))
            self.after(0, lambda: messagebox.showinfo("Sukses", f"Terunduh:\n{filepath}\n\nOtomatis dimuat ke player."))
            self.after(100, lambda: self._load_audio(filepath))
        except yt_dlp.utils.DownloadError as e:
            self.after(0, lambda: self.status.configure(text="Gagal unduh."))
            self.after(0, lambda: messagebox.showerror("Error", f"Gagal unduh:\n{e}"))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
        finally:
            self.after(0, lambda: self.yt_btn.configure(state="normal", text="Unduh"))

    def _yt_progress_hook(self, d):
        if d["status"] == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes", 0)
            if total and total > 0:
                pct = downloaded / total
                self.after(0, lambda p=pct: self.progress.set(p))
                speed = d.get("speed", 0)
                speed_str = f"{speed / 1024 / 1024:.1f} MB/s" if speed else "?"
                self.after(0, lambda s=speed_str: self.status.configure(text=f"Unduh... {pct*100:.0f}% ({s})"))
        elif d["status"] == "finished":
            self.after(0, lambda: self.progress.set(1))
            self.after(0, lambda: self.status.configure(text="Selesai unduh. Memuat..."))

    # === Preview ===
    def preview_clip(self):
        av = self.av_entry.get().strip()
        if not av or not os.path.isfile(av):
            return
        try:
            start = parse_time_inputs(self.start_min, self.start_sec)
            end = parse_time_inputs(self.end_min, self.end_sec)
        except ValueError as e:
            messagebox.showerror("Error", str(e))
            return
        if end <= start:
            messagebox.showerror("Error", "End harus setelah Start.")
            return
        dur = end - start
        threading.Thread(target=lambda: subprocess.Popen(
            ["ffplay", "-ss", f"{start}", "-t", f"{dur}", "-autoexit", "-nodisp", av],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        ), daemon=True).start()
        self.status.configure(text=f"Preview: {fmt_time(start)} \u2192 {fmt_time(end)} ({dur:.0f}s)")

    # === Generate ===
    def on_generate(self):
        foto = self.foto_entry.get().strip()
        av = self.av_entry.get().strip()
        if not foto or not os.path.isfile(foto):
            messagebox.showerror("Error", "File foto tidak ditemukan.")
            return
        if not av or not os.path.isfile(av):
            messagebox.showerror("Error", "File audio/video tidak ditemukan.")
            return
        try:
            start = parse_time_inputs(self.start_min, self.start_sec)
            end = parse_time_inputs(self.end_min, self.end_sec)
        except ValueError as e:
            messagebox.showerror("Error", str(e))
            return
        if end <= start:
            messagebox.showerror("Error", "End harus setelah Start.")
            return
        dur = end - start
        if dur <= 0:
            messagebox.showerror("Error", "Durasi <= 0.")
            return

        # Auto-generate output path on Desktop
        import time
        ts = time.strftime("%Y%m%d_%H%M%S")
        out = os.path.join(os.path.expanduser("~"), "Desktop", f"clip_{ts}.mp4")

        save_config({"foto": foto, "av": av,
                     "start": f"{int(start//60):02d}:{int(start%60):02d}",
                     "end": f"{int(end//60):02d}:{int(end%60):02d}"})
        self.gen_btn.configure(state="disabled", text="Processing...")
        self.progress.set(0)
        self.status.configure(text=f"Mulai: {fmt_time(start)} \u2192 {fmt_time(end)} ({dur:.0f}s)")
        threading.Thread(target=self.run_ffmpeg, args=(foto, av, start, dur, out), daemon=True).start()

    def run_ffmpeg(self, foto, av, start, dur, out):
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", foto,
            "-ss", f"{start}",
            "-t", f"{dur}",
            "-i", av,
            "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-tune", "stillimage",
            "-pix_fmt", "yuv420p",
            "-r", "30",
            "-shortest",
            out,
        ]
        try:
            proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                    text=True, universal_newlines=True)
            total = dur
            for line in proc.stderr:
                m = re.search(r"time=(\d+:\d+:\d+\.\d+)", line)
                if m:
                    parts = m.group(1).split(":")
                    secs = int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
                    pct = min(secs / total, 1.0) if total > 0 else 0
                    self.after(0, lambda p=pct: self.progress.set(p))
                    self.after(0, lambda s=secs: self.status.configure(
                        text=f"Encoding... {fmt_time(s)} / {fmt_time(total)}"))
            proc.wait()
            if proc.returncode == 0:
                self.after(0, lambda: self.progress.set(1))
                self.after(0, lambda: self.status.configure(text=f"Selesai! \u2192 {out}"))
                self.after(0, lambda: messagebox.showinfo("Sukses", f"Video tersimpan:\n{out}"))
            else:
                self.after(0, lambda: self.status.configure(text="Gagal!"))
                self.after(0, lambda: messagebox.showerror("Error", f"ffmpeg gagal (code {proc.returncode})."))
        except FileNotFoundError:
            self.after(0, lambda: messagebox.showerror("Error", "ffmpeg tidak ditemukan di PATH."))
        except Exception as e:
            self.after(0, lambda: messagebox.showerror("Error", str(e)))
        finally:
            self.after(0, lambda: self.gen_btn.configure(state="normal", text="Generate Clip"))


if __name__ == "__main__":
    app = ClipMaker()
    app.mainloop()
