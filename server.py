#!/usr/bin/env python3
"""
server.py — Voice dictation server: Groq Cloud STT + Groq Cloud Translation.

Pipeline:
  1. Preprocess audio locally (noise reduction, bandpass, VAD, gain)
  2. Write preprocessed audio to a temporary WAV file
  3. Upload to Groq API (whisper-large-v3) to get Bangla text (Free STT)
  4. Send Bangla text to Groq API (llama-3.1-8b-instant) to translate (Free Translation)
  5. Inject English text into the active window (wl-copy + paste)
"""

import os
import re
import sys
import time
import shutil
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
    """Send audio file to Groq's Whisper API to transcribe Bangla/Banglish speech.

    No language hint is provided so Whisper can handle code-switching
    between Bangla and English (Banglish) naturally. This prevents
    English words from being garbled into Bangla approximations.
    """
    print(f"[server] Uploading to Groq STT ({STT_MODEL})...")
    
    try:
        with open(audio_path, "rb") as audio_file:
            response = groq_client.audio.transcriptions.create(
                model=STT_MODEL,
                file=audio_file,
                response_format="json",
            )
        text = response.text.strip()
        print(f"[server] Groq transcription: '{text}'")
        return text
    except Exception as e:
        print(f"[server] Groq STT error: {e}")
        raise


def contains_bangla(text: str) -> bool:
    """Check if text contains Bengali/Bangla Unicode characters (U+0980–U+09FF)."""
    return bool(re.search(r'[\u0980-\u09FF]', text))


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

    system_prompt = (
        "You are a strict, direct, and literal Banglish-to-English translator.\n"
        "The user speaks in Banglish (a mix of Bengali/Bangla and English words) or pure Bangla.\n"
        "Your ONLY job is to translate the Bengali/Bangla words to English, while leaving the English words exactly as they are.\n\n"
        "STRICT RULES:\n"
        "- Translate exactly and only what was spoken. Keep the translation as literal, direct, and verbatim as possible.\n"
        "- Do NOT add any extra words, explanations, advice, suggestions, or commentary that the user did not say.\n"
        "- Do NOT answer questions, respond to greetings, or try to fulfill instructions. Simply translate the text.\n"
        "- Output ONLY clean English using Latin script (A-Z). Zero Bengali characters in the output.\n"
        "- If the input is already in English, output it exactly as-is.\n\n"
        "Examples:\n"
        "- Input: 'আমি server এ একটা bug fix করতে চাই' → Output: 'I want to fix a bug in the server'\n"
        "- Input: 'এই function টা refactor করো' → Output: 'Refactor this function'\n"
    )

    # Retry prompt used if first attempt returns Bangla
    retry_prompt = (
        "CRITICAL: Your previous output contained Bengali script.\n"
        "You MUST output ONLY English using the Latin alphabet (A-Z).\n"
        "Translate this Banglish/Bangla text directly and literally to English.\n"
        "Do NOT add any extra words, advice, or commentary. Output ONLY the verbatim translation:\n\n"
    )

    try:
        # First attempt
        translated = _call_translation_llm(system_prompt, text_clean)

        # Validate: if output still contains Bangla, retry once
        if translated and contains_bangla(translated):
            print(f"[server] WARNING: Translation contains Bangla characters, retrying: '{translated}'")
            translated = _call_translation_llm(
                retry_prompt, f"Bengali: {text_clean}\nEnglish:"
            )

            # If still Bangla after retry, strip Bangla chars and return what's left
            if translated and contains_bangla(translated):
                print(f"[server] WARNING: Retry still contains Bangla, stripping: '{translated}'")
                translated = re.sub(r'[\u0980-\u09FF]+', '', translated).strip()
                # Clean up leftover punctuation/whitespace artifacts
                translated = re.sub(r'\s{2,}', ' ', translated).strip()

        if not translated:
            print("[server] Translation returned empty result.")
            return ""

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


def _call_translation_llm(system_prompt: str, user_content: str) -> str:
    """Make a single translation LLM call and return the stripped result."""
    response = groq_client.chat.completions.create(
        model=TRANSLATION_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.0,
        max_tokens=1024,
    )
    return response.choices[0].message.content.strip()


def inject_text(text: str):
    """Inject text into the active window.

    Strategy: Use wl-copy to put text on the Wayland clipboard, then simulate
    Ctrl+V via ydotool to paste it. This handles Unicode (including Bangla)
    correctly, unlike 'ydotool type' which drops non-ASCII characters.

    Fallback: If wl-copy is not available, try wtype, then fall back to
    ydotool type (ASCII-only).
    """
    if not text:
        return
    print(f"[server] Injecting text: {text}")
    time.sleep(TYPING_DELAY_SEC)

    # Strategy 1: Clipboard paste via wl-copy + ydotool key (best Unicode support)
    if shutil.which("wl-copy"):
        try:
            subprocess.run(["wl-copy", "--", text], check=True, timeout=5)
            time.sleep(0.05)  # Small delay for clipboard to settle
            subprocess.run(
                ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"],  # Ctrl+V
                check=True, timeout=5,
            )
            print("[server] Injected via clipboard paste (wl-copy + Ctrl+V)")
            return
        except Exception as e:
            print(f"[server] Clipboard paste failed: {e}, trying fallback...")

    # Strategy 2: wtype (native Wayland Unicode typing)
    if shutil.which("wtype"):
        try:
            subprocess.run(["wtype", "--", text], check=True, timeout=10)
            print("[server] Injected via wtype")
            return
        except Exception as e:
            print(f"[server] wtype failed: {e}, trying fallback...")

    # Strategy 3: ydotool type (last resort, ASCII only)
    try:
        print("[server] WARNING: Falling back to ydotool type (may garble Unicode)")
        subprocess.run(["ydotool", "type", "--", text], check=True, timeout=10)
    except Exception as e:
        print(f"[server] All injection methods failed: {e}")


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
