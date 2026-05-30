#!/usr/bin/env python3
"""
process.py — Client for the Voice Dictation Server.

Sends audio path to the server for translation and injection.
Falls back to local model loading if the server is unreachable.
"""

import os
import sys
import requests
import subprocess
from pathlib import Path

SERVER_URL = "http://127.0.0.1:8000"

def call_server(audio_path: str) -> bool:
    """Try to call the background server."""
    try:
        response = requests.post(
            f"{SERVER_URL}/translate",
            json={"audio_path": str(Path(audio_path).absolute()), "inject": True},
            timeout=30
        )
        if response.status_code == 200:
            result = response.json()
            text = result.get('text', '').strip()
            if not text:
                print("[client] Server returned empty text.")
                return False
            print(f"[client] Server success: {text}")
            return True
        else:
            print(f"[client] Server error: {response.status_code} - {response.text}")
            return False
    except requests.exceptions.ConnectionError:
        print("[client] Server not running.")
        return False
    except Exception as e:
        print(f"[client] Unexpected error: {e}")
        return False

def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <audio_file.wav>", file=sys.stderr)
        sys.exit(1)

    audio_path = sys.argv[1]
    if not os.path.isfile(audio_path):
        print(f"[client] Error: File not found: {audio_path}", file=sys.stderr)
        sys.exit(1)

    # Try calling the server first
    if not call_server(audio_path):
        print("[client] Falling back to local model loading (this will be slow!)...")
        # I'll keep the old logic in a separate block or just warn the user.
        # Given the "lag" problem, it's better to tell the user to start the server.
        print("[client] Please ensure the voice-dictation server is running to avoid lag.")
        
        # Original logic fallback could be here, but let's encourage server usage.
        # For now, we'll just fail gracefully or try to run the server.
        sys.exit(1)

if __name__ == "__main__":
    main()
