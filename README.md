# ClipMaker

Tool buat nge-klip potongan video/audio lagu di menit tertentu, tempel background foto, output video foto + audio lagu.

## Fitur

- **Player built-in** — play/pause audio/video langsung di app, dengan seek bar + time display
- **Preview gambar** — video tampil frame live, audio tampil waveform
- **Input start/end structured** — `[mm] : [ss]` terpisah, bukan freetext
- **Set Start/End = Now** — capture posisi player saat ini
- **Preview Clip** — dengar potongan start→end sebelum generate
- **YouTube download** — paste URL, auto-download audio via yt-dlp
- **Auto-save output** — hasil `clip_<timestamp>.mp4` langsung ke Desktop
- **Progress bar** — real-time encoding progress

## Requirements

```bash
pip install customtkinter pygame-ce Pillow yt-dlp
```

FFmpeg + ffprobe harus di PATH.

## Jalankan

Double-click `ClipMaker.bat`, atau:

```bash
python clipmaker.py
```

## Cara Pakai

1. **Browse** foto background
2. **Browse** audio/video sumber, atau **paste URL YouTube** → Unduh
3. Tekan **Play** → dengar → pas posisi pas → **Set Start = Now**
4. Lanjut play → pas selesai → **Set End = Now**
5. (Opsional) **Preview Clip** untuk cek
6. **Generate Clip** → hasil muncul di Desktop
