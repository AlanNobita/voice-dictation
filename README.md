# 🎙 Voice Dictation — Bangla → English for Hyprland

Stateful voice dictation pipeline that records Bangla speech, translates it to English using local AI, and types it into the active window.

**Stack**: PipeWire → faster-whisper (CTranslate2) → ydotool → Wayland

---

## Prerequisites

### System Packages

```bash
# Arch Linux / Manjaro
sudo pacman -S pipewire ydotool libnotify

# Fedora
sudo dnf install pipewire ydotool libnotify

# Ubuntu/Debian (ydotool may need to be built from source)
sudo apt install pipewire libnotify-bin
```

### uv (Python Package Manager)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

> Already have uv? Make sure it's `>=0.4` — run `uv --version` to check.

---

## Setup

```bash
cd ~/Documents/code/voice

# Run the one-time setup script
chmod +x setup.sh
./setup.sh
```

This will:
1. Verify all system dependencies are present
2. Install the udev rule for `/dev/uinput` (requires sudo)
3. Install & start the `ydotoold` systemd user service
4. Run `uv sync` to create a `.venv` and install `faster-whisper`
5. Make scripts executable
6. Print the Hyprland keybind to add

### Add the Hyprland Keybind

Append to `~/.config/hypr/hyprland.conf`:

```conf
bind = , F9, exec, ~/Documents/code/voice/toggle_capture.sh
```

Then reload:

```bash
hyprctl reload
```

---

## Usage

1. **Press F9** — recording starts (you'll see a notification)
2. **Speak in Bangla**
3. **Press F9 again** — recording stops, translation runs, English text is typed into the focused window

### First Run

The first invocation downloads the Whisper model (~500 MB for `small`). Subsequent runs use the cached model.

---

## Configuration

Environment variables you can set in your shell or in the keybind:

| Variable | Default | Options |
|----------|---------|---------|
| `WHISPER_MODEL` | `turbo` | `tiny`, `base`, `small`, `medium`, `large-v3`, `turbo` |
| `WHISPER_DEVICE` | `auto` | `cpu`, `cuda`, `auto` |
| `WHISPER_COMPUTE` | `auto` | `int8`, `float16`, `auto` |

Example: use the `turbo` model on GPU:

```conf
bind = , F9, exec, WHISPER_MODEL=turbo WHISPER_DEVICE=cuda ~/Documents/code/voice/toggle_capture.sh
```

---

## Managing Dependencies with uv

```bash
cd ~/Documents/code/voice

# Install / sync all dependencies
uv sync

# Add a new dependency
uv add <package-name>

# Run process.py directly via uv
uv run process.py /tmp/voice_capture.wav

# Lock dependencies (creates uv.lock)
uv lock
```

> **How it works**: `uv sync` reads `pyproject.toml`, creates a `.venv` in the project directory, and installs all dependencies into it. The `toggle_capture.sh` script uses `uv run` to execute `process.py` inside this environment automatically.

---

## File Structure

```
voice/
├── 99-uinput.rules        # udev rule for /dev/uinput
├── ydotoold.service        # systemd user service
├── toggle_capture.sh       # Bash orchestrator (F9 toggle)
├── process.py              # Translation engine (faster-whisper)
├── pyproject.toml          # Python project definition (for uv)
├── requirements.txt        # Pinned dependencies (fallback)
├── setup.sh                # One-time installer
├── hyprland.conf.snippet   # Keybind to copy into hyprland.conf
└── README.md               # This file
```

---

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `ydotool: connect failed` | `systemctl --user start ydotoold` |
| `/dev/uinput` permission denied | Re-login after udev rule install, or `sudo chmod 0660 /dev/uinput` |
| No audio captured | Check `wpctl status` — ensure a capture device is active |
| Model download stalls | Set `HF_HUB_OFFLINE=1` after first download to use cache |
| Slow on CPU | Use `WHISPER_MODEL=tiny` or `WHISPER_MODEL=base` |
