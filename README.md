# 🎙 Voice Dictation — Bangla → English for Hyprland

A stateful, cloud-powered voice dictation pipeline that records Bangla speech, transcribes and translates it using Groq Cloud API, and types the result into the active window.

**Stack**: PipeWire → Local Audio Preprocessing → Groq STT (whisper-large-v3) → Groq LLM (llama-3.1-8b-instant) → ydotool → Wayland

---

## Architecture

This pipeline runs with zero local AI model inference overhead, making it extremely lightweight on CPU and memory:

```
F9 key → toggle_capture.sh → pw-record (16kHz WAV)
    → audio_preprocess.py (noise reduction, bandpass filter, VAD, gain)
    → Groq Cloud STT API (Bangla speech → Bangla text, whisper-large-v3, Free)
    → Groq Cloud Translation API (Bangla text → English text, llama-3.1-8b-instant, Free)
    → ydotool type (inject into active window)
```

The audio preprocessing filters noise and boosts signal quality locally (takes ~50ms on CPU) before sending it to the APIs, ensuring high recognition accuracy even with low-quality earphone mics.

---

## Prerequisites

### 1. System Packages

```bash
# Arch Linux / Manjaro
sudo pacman -S pipewire ydotool libnotify

# Fedora
sudo dnf install pipewire ydotool libnotify

# Ubuntu/Debian (ydotool may need to be built from source)
sudo apt install pipewire libnotify-bin
```

### 2. uv (Python Package Manager)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 3. API Key

You need a **Groq API Key**:
- Sign up at the [Groq Console](https://console.groq.com/) and create a free API key.

The entire pipeline is **100% free** under Groq's developer tier.

---

## Setup

```bash
cd ~/Documents/code/voice

# Run the one-time setup script
chmod +x setup.sh
./setup.sh
```

### Configure Credentials

Edit the systemd service file to add your Groq API key:

```bash
nano ~/Documents/code/voice/voice-dictation.service
```

Replace `your-groq-key-here` (or the existing placeholder) with your actual `GROQ_API_KEY`.

### Start the Service

```bash
# Start the service (it's symlinked to ~/.config/systemd/user/voice-dictation.service)
systemctl --user daemon-reload
systemctl --user enable voice-dictation
systemctl --user start voice-dictation
```

### Add the Hyprland Keybind

Append this to `~/.config/hypr/hyprland.conf`:

```conf
bind = , F9, exec, ~/Documents/code/voice/toggle_capture.sh
```

Reload Hyprland configurations:

```bash
hyprctl reload
```

---

## Usage

1. **Press F9** — recording starts (you'll see a notification).
2. **Speak in Bangla**.
3. **Press F9 again** — recording stops, audio is preprocessed, transcribed via Groq, translated via Groq Llama, and typed into the focused window.

---

## Configuration

Environment variables you can set in your systemd service file:

| Variable | Default | Options | Description |
|----------|---------|---------|-------------|
| `GROQ_API_KEY` | *(required)* | Your Groq API key | Auths API calls |
| `GROQ_MODEL` | `whisper-large-v3` | `whisper-large-v3`, `whisper-large-v3-turbo` | Speech-to-Text model |
| `GROQ_TRANS_MODEL` | `llama-3.1-8b-instant` | `llama-3.1-8b-instant`, `llama-3.3-70b-versatile` | Translation text LLM |
| `GROQ_BASE_URL` | `https://api.groq.com/openai/v1` | Custom gateway | API base URL |

---

## Real-Time Microphone Noise Suppression (Optional)

If your headset or earphone mic has loud background hiss or static, you can load a real-time noise suppression filter inside PipeWire (uses the neural RNNoise model):

1. Install the plugin:
   ```bash
   sudo pacman -S noise-suppression-for-voice
   ```
2. Enable it by creating `~/.config/pipewire/pipewire.conf.d/99-input-denoising.conf`:
   ```bash
   mkdir -p ~/.config/pipewire/pipewire.conf.d/
   cat << 'EOF' > ~/.config/pipewire/pipewire.conf.d/99-input-denoising.conf
   context.modules = [
       { name = libpipewire-module-filter-chain
           args = {
               node.description = "Noise Canceling source"
               media.name = "Noise Canceling source"
               filter.graph = {
                   nodes = [
                       {
                           type = ladspa
                           name = rnnoise
                           plugin = /usr/lib/ladspa/librnnoise_ladspa.so
                           label = noise_suppressor_mono
                           control = {
                               "VAD Threshold (%)" 50.0
                               "VAD Grace Period (ms)" 200
                           }
                       }
                   ]
               }
               capture.props = {
                   node.name = "capture.rnnoise_source"
                   node.passive = true
                   audio.rate = 48000
               }
               playback.props = {
                   node.name = "rnnoise_source"
                   media.class = Audio/Source
                   audio.rate = 48000
               }
           }
       }
   ]
   EOF
   ```
3. Restart PipeWire:
   ```bash
   systemctl --user restart pipewire pipewire-pulse
   ```
4. Open your volume control mixer (e.g. `pavucontrol`) and select **"Noise Canceling source"** as your default system input device.

---

## Troubleshooting

| Issue | Cause & Fix |
|-------|-------------|
| `ydotool: connect failed` | Run: `systemctl --user start ydotoold` |
| `/dev/uinput` permission denied | Check udev rules or run: `sudo chmod 0660 /dev/uinput` |
| Server not running error | Verify status: `systemctl --user status voice-dictation` |
| `GROQ_API_KEY not configured` | Add the key in the systemd service file or your environment. |
| Translation is blank / silent | Speak closer to the mic; check your recording volume. |
| Model decommissioned error | Groq updated its models. Check the configuration section and update `GROQ_TRANS_MODEL` in the service file to an active model (e.g. `llama-3.1-8b-instant`). |
