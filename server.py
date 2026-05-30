#!/usr/bin/env python3
"""
server.py — Persistent translation engine for voice dictation.

Loads faster-whisper (CTranslate2) model once and provides a FastAPI endpoint 
to process audio and inject text.
"""

import os
import sys
import time
import subprocess
import uvicorn
import numpy as np
import wave
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from faster_whisper import WhisperModel

app = FastAPI(title="Voice Dictation Server")

# ─── Configuration ───────────────────────────────────────────────────────────
MODEL_SIZE = os.environ.get("WHISPER_MODEL", "turbo")
DEVICE = os.environ.get("WHISPER_DEVICE", "auto")       
COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE", "auto") 
TYPING_DELAY_SEC = 0.15

print(f"[server] Loading model: {MODEL_SIZE} (device={DEVICE}, compute={COMPUTE_TYPE})")
model = WhisperModel(MODEL_SIZE, device=DEVICE, compute_type=COMPUTE_TYPE)
print("[server] Model loaded and ready.")

class TranslationRequest(BaseModel):
    audio_path: str
    inject: bool = True

def is_hallucination(segment) -> bool:
    text = segment.text.strip()
    if not text or len(text) < 1:
        return True
    if segment.avg_logprob < -1.5:
        return True
    if segment.compression_ratio > 2.4:
        return True
    if segment.no_speech_prob > 0.8:
        return True
    
    hallucination_patterns = [
        "thank you for watching", "thanks for watching", "subscribe",
        "like and subscribe", "please subscribe", "thank you for listening",
        "see you in the next", "bye bye", "the end", "music", "♪",
    ]
    lower = text.lower()
    return any(pattern in lower for pattern in hallucination_patterns)

def inject_text(text: str):
    if not text:
        return
    print(f"[server] Injecting: {text}")
    time.sleep(TYPING_DELAY_SEC)
    try:
        subprocess.run(
            ["ydotool", "type", "--", text],
            check=True,
        )
    except Exception as e:
        print(f"[server] Injection failed: {e}")

@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL_SIZE}

@app.post("/translate")
async def translate_endpoint(request: TranslationRequest, background_tasks: BackgroundTasks):
    if not os.path.exists(request.audio_path):
        raise HTTPException(status_code=404, detail="Audio file not found")

    print(f"[server] Processing audio: {request.audio_path}")
    
    try:
        # Pre-processing (Normalization)
        with wave.open(request.audio_path, 'rb') as wf:
            params = wf.getparams()
            audio_bytes = wf.readframes(params.nframes)
            audio_data = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
            peak = np.abs(audio_data).max()
            if peak > 0:
                audio_data = audio_data * (0.9 / peak)
                print(f"[server] Audio peak: {peak:.3f} (Normalized to 0.9)")
            else:
                print("[server] Warning: Audio peak is 0.0 (Silence)")

        initial_prompt = (
            "Translate the following Bengali audio into clear, natural English text. "
            "The output must be in English Only. "
            "User is dictating text for a Linux window."
        )

        segments, info = model.transcribe(
            audio_data,
            language="bn",
            task="translate",
            beam_size=5,
            temperature=0,
            initial_prompt=initial_prompt,
            condition_on_previous_text=False,
            vad_filter=False,
        )

        translated_parts = []
        print(f"[server] Segments found:")
        for segment in segments:
            is_halluc = is_hallucination(segment)
            print(f"  - [{segment.start:.2f}s -> {segment.end:.2f}s] text='{segment.text.strip()}' hallucination={is_halluc} logprob={segment.avg_logprob:.2f} ratio={segment.compression_ratio:.2f} no_speech={segment.no_speech_prob:.2f}")
            if not is_halluc:
                translated_parts.append(segment.text.strip())

        result_text = " ".join(translated_parts)
        print(f"[server] Final Result: '{result_text}'")

        if request.inject and result_text:
            background_tasks.add_task(inject_text, result_text)
        elif request.inject:
            print("[server] No valid text to inject.")

        return {"text": result_text, "language": info.language}

    except Exception as e:
        print(f"[server] Error during translation: {e}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    port = int(os.environ.get("SERVER_PORT", 8000))
    uvicorn.run(app, host="127.0.0.1", port=port)
