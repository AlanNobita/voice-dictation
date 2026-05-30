#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# toggle_capture.sh — Stateful voice capture orchestrator for Hyprland
#
# First invocation:  Starts pw-record capturing 16kHz/mono/s16le WAV
# Second invocation: Stops recording and triggers translation → injection
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WAV_FILE="/tmp/voice_capture.wav"
PID_FILE="/tmp/voice_capture.pid"
LOG_FILE="/tmp/voice_capture.log"

# ─── Helpers ─────────────────────────────────────────────────────────────────
log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

notify() {
    log "NOTIFICATION: $1 - $2"
    notify-send -a "Voice Dictation" -i audio-input-microphone "$1" "$2" 2>/dev/null || true
}

# ─── Toggle Logic ────────────────────────────────────────────────────────────
if [[ -f "$PID_FILE" ]]; then
    # ── Second press: Stop recording & process ───────────────────────────────
    PID=$(cat "$PID_FILE")

    if kill -0 "$PID" 2>/dev/null; then
        log "Stopping recording (PID: $PID)..."
        kill "$PID"
        wait "$PID" 2>/dev/null || true
    else
        log "Recording PID $PID not found."
    fi

    rm -f "$PID_FILE"

    # Sanity check: make sure we actually captured something
    if [[ ! -s "$WAV_FILE" ]]; then
        notify "⚠ Error" "No audio was captured (empty file)."
        exit 1
    fi

    FILE_SIZE=$(stat -c%s "$WAV_FILE")
    if (( FILE_SIZE < 10000 )); then
        notify "⚠ Error" "Audio too short or silent ($((FILE_SIZE/1024))KB)."
        rm -f "$WAV_FILE"
        exit 1
    fi

    notify "⏳ Processing…" "Translating Bangla → English"

    # Run the translation engine
    log "Starting translation engine..."
    if uv run --project "$SCRIPT_DIR" "$SCRIPT_DIR/process.py" "$WAV_FILE" >> "$LOG_FILE" 2>&1; then
        log "Translation and injection successful."
        notify "✅ Done" "Text injected into active window."
    else
        log "ERROR: Processing failed or result was empty."
        if ! curl -s "http://127.0.0.1:8000/health" > /dev/null; then
            notify "❌ Error" "Server not running. Start it with: systemctl --user start voice-dictation"
        elif grep -q "Server returned empty text" "$LOG_FILE"; then
            notify "⚠ Silence" "No speech detected or translation too short."
        else
            notify "❌ Error" "Translation failed. Check $LOG_FILE"
        fi
    fi

    # Cleanup
    rm -f "$WAV_FILE"
else
    # ── First press: Start recording ─────────────────────────────────────────
    rm -f "$WAV_FILE"
    log "Starting recording..."
    # Use pw-record with explicit parameters. 
    # We don't specify --target to let PipeWire choose the default active source,
    # but we ensure the format is correct for Whisper.
    pw-record \
        --rate=16000 \
        --channels=1 \
        --format=s16 \
        --quality=4 \
        "$WAV_FILE" >> "$LOG_FILE" 2>&1 &

    echo $! > "$PID_FILE"
    log "Recording started (PID: $(cat "$PID_FILE"))"

    notify "🎙 Recording" "Speak in Bangla. Press F9 again to stop."
fi
