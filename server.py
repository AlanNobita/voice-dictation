#!/usr/bin/env python3
"""
server.py — Voice dictation server: Groq Cloud STT + Groq Cloud Translation.

Pipeline:
  1. Preprocess audio locally (noise reduction, bandpass, VAD, gain)
  2. Write preprocessed audio to a temporary WAV file
  3. Upload to Groq API (whisper-large-v3) to get Bangla text (Free STT)
  4. Send Bangla text to Groq API (llama-3.1-8b-instant) to translate (Free Translation)
  5. Inject English text into the active window (ydotool)
"""

import os
import sys
import time
import subprocess
import uvicorn
import wave
import numpy as np
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from openai import OpenAI

from audio_preprocess import preprocess

app = FastAPI(title="Voice Dictation Server")

# ─── Configuration ───────────────────────────────────────────────────────────
TYPING_DELAY_SEC = 0.15

# API Key & Models (Using Groq for both steps)
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_BASE_URL = os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1")

STT_MODEL = os.environ.get("GROQ_MODEL", "whisper-large-v3")
TRANSLATION_MODEL = os.environ.get("GROQ_TRANS_MODEL", "llama-3.1-8b-instant")

# Validation check at startup
if not GROQ_API_KEY:
    print("[server] WARNING: GROQ_API_KEY is not set! Voice dictation will fail.")

# OpenAI-compatible Groq Client
groq_client = OpenAI(
    api_key=GROQ_API_KEY,
    base_url=GROQ_BASE_URL,
)


class TranslationRequest(BaseModel):
    audio_path: str
    inject: bool = True


def save_preprocessed_wav(audio_data: np.ndarray, sr: int, output_path: str):
    """Save float32 audio back to a standard 16-bit PCM WAV file for API upload."""
    pcm_data = (audio_data * 32767.0).astype(np.int16)
    
    with wave.open(output_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 2 bytes = 16 bits
        wf.setframerate(sr)
        wf.writeframes(pcm_data.tobytes())


def transcribe_bangla_via_groq(audio_path: str) -> str:
    """Send audio file to Groq's Whisper API to transcribe Bangla speech."""
    print(f"[server] Uploading to Groq STT ({STT_MODEL})...")
    
    try:
        with open(audio_path, "rb") as audio_file:
            response = groq_client.audio.transcriptions.create(
                model=STT_MODEL,
                file=audio_file,
                language="bn",
                response_format="json",
            )
        text = response.text.strip()
        print(f"[server] Groq transcription: '{text}'")
        return text
    except Exception as e:
        print(f"[server] Groq STT error: {e}")
        raise


def translate_to_english_via_groq(bangla_text: str) -> str:
    """Translate Bangla text to English using Groq's Llama model."""
    text_clean = bangla_text.strip()
    if not text_clean:
        return ""

    # Check for obvious Whisper noise/silence hallucinations
    lower = text_clean.lower()
    hallucination_patterns = [
        "thank you for watching", "thanks for watching", "subscribe",
        "like and subscribe", "please subscribe", "thank you for listening",
        "see you in the next", "bye bye", "the end", "music", "♪",
        "ধন্যবাদ", "সাবস্ক্রাইব", "ইউটিউব", "ভিডিও"
    ]
    if any(pat in lower for pat in hallucination_patterns) and len(text_clean.split()) <= 3:
        print(f"[server] Discarding suspected STT hallucination: '{text_clean}'")
        return ""

    print(f"[server] Requesting translation from Groq ({TRANSLATION_MODEL})...")

    try:
        response = groq_client.chat.completions.create(
            model=TRANSLATION_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a strict, literal, one-way translator machine. "
                        "Your ONLY job is to translate Bengali (Bangla) text into English. "
                        "Follow these rules strictly:\n"
                        "1. Output ONLY the English translation. Never converse, explain, or reply to the text.\n"
                        "2. Never answer questions or respond to greetings. If the input is 'কেমন আছেন?', output 'How are you?'. Do NOT say 'I am doing well'.\n"
                        "3. If the input is already in English, output it exactly as-is.\n"
                        "4. If the input is static, repetitive nonsense, or typical speech-to-text noise (like 'thank you', 'subscribe', 'ধন্যবাদ'), output absolutely nothing.\n\n"
                        "Examples:\n"
                        "- Input: 'কেমন আছেন?' -> Output: 'How are you?'\n"
                        "- Input: 'হ্যালো' -> Output: 'Hello'\n"
                        "- Input: 'আমি এখন কোড করছি' -> Output: 'I am coding now'\n"
                        "- Input: 'ধন্যবাদ ধন্যবাদ' -> Output: ''"
                    ),
                },
                {
                    "role": "user",
                    "content": text_clean,
                },
            ],
            temperature=0.0,  # Zero creativity for strict translation
            max_tokens=1024,
        )

        translated = response.choices[0].message.content.strip()
        
        # Double check if LLM returned standard hallucination phrases in English
        lower_trans = translated.lower()
        if any(pat in lower_trans for pat in ["thank you for watching", "thanks for watching", "please subscribe", "subscribe to my channel"]):
            print(f"[server] Discarding suspected LLM hallucination output: '{translated}'")
            return ""

        print(f"[server] Groq translation: '{translated}'")
        return translated

    except Exception as e:
        print(f"[server] Groq translation error: {e}")
        raise


def inject_text(text: str):
    """Simulate keypress typing using ydotool."""
    if not text:
        return
    print(f"[server] Injecting text: {text}")
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
    return {
        "status": "ok",
        "stt_model": STT_MODEL,
        "translation_model": TRANSLATION_MODEL,
        "groq_configured": bool(GROQ_API_KEY),
    }


@app.post("/translate")
async def translate_endpoint(request: TranslationRequest, background_tasks: BackgroundTasks):
    if not os.path.exists(request.audio_path):
        raise HTTPException(status_code=404, detail="Audio file not found")

    if not GROQ_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY not configured. Set it in the environment.",
        )

    print(f"[server] Processing request for audio: {request.audio_path}")

    try:
        # Step 1: Preprocess raw audio
        audio_data, sr = preprocess(request.audio_path)

        if len(audio_data) < sr * 0.3:  # Too short after VAD
            print("[server] Audio too short or silent after preprocessing.")
            return {"text": "", "bangla": "", "language": "bn"}

        # Step 2: Save preprocessed audio to a temporary file for upload
        preprocessed_path = "/tmp/voice_capture_preprocessed.wav"
        save_preprocessed_wav(audio_data, sr, preprocessed_path)

        # Step 3: Transcribe using Groq Cloud API
        bangla_text = transcribe_bangla_via_groq(preprocessed_path)

        # Clean up temporary preprocessed file
        if os.path.exists(preprocessed_path):
            os.remove(preprocessed_path)

        if not bangla_text.strip():
            print("[server] No speech transcription returned.")
            return {"text": "", "bangla": "", "language": "bn"}

        # Step 4: Translate using Groq Llama Model
        english_text = translate_to_english_via_groq(bangla_text)

        # Step 5: Inject translation into active window
        if request.inject and english_text:
            background_tasks.add_task(inject_text, english_text)
        elif request.inject:
            print("[server] No valid text to inject.")

        return {"text": english_text, "bangla": bangla_text, "language": "bn"}

    except Exception as e:
        print(f"[server] Error processing request: {e}")
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    port = int(os.environ.get("SERVER_PORT", 8000))
    uvicorn.run(app, host="127.0.0.1", port=port)
