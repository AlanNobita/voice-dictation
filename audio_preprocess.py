#!/usr/bin/env python3
"""
audio_preprocess.py — Audio preprocessing for poor-quality earphone mics.

Pipeline:
  1. Load WAV → float32
  2. Bandpass filter (300–3400 Hz) to isolate speech
  3. Spectral noise reduction (noisereduce)
  4. Voice Activity Detection — trim silence
  5. Auto gain control → target RMS
  6. Peak normalization → 0.9
"""

import numpy as np
import wave
from scipy.signal import butter, sosfilt


def load_wav(path: str) -> tuple[np.ndarray, int]:
    """Load a WAV file and return (float32 samples, sample_rate)."""
    with wave.open(path, "rb") as wf:
        sample_rate = wf.getframerate()
        n_channels = wf.getnchannels()
        n_frames = wf.getnframes()
        raw = wf.readframes(n_frames)

    audio = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0

    # If stereo, mix down to mono
    if n_channels > 1:
        audio = audio.reshape(-1, n_channels).mean(axis=1)

    return audio, sample_rate


def bandpass_filter(
    audio: np.ndarray, sr: int, low_hz: int = 300, high_hz: int = 3400
) -> np.ndarray:
    """
    Apply a Butterworth bandpass filter to isolate the speech frequency range.
    Cuts low-frequency hum/rumble and high-frequency hiss from cheap mics.
    """
    nyquist = sr / 2.0
    low = low_hz / nyquist
    high = min(high_hz / nyquist, 0.99)  # Clamp to avoid exceeding Nyquist
    sos = butter(N=5, Wn=[low, high], btype="band", output="sos")
    return sosfilt(sos, audio).astype(np.float32)


def reduce_noise(audio: np.ndarray, sr: int) -> np.ndarray:
    """
    Apply spectral-gating noise reduction.
    Uses the first 0.5s of audio to estimate the noise profile.
    """
    import noisereduce as nr

    return nr.reduce_noise(
        y=audio,
        sr=sr,
        stationary=True,
        prop_decrease=0.75,
        n_std_thresh_stationary=1.5,
    ).astype(np.float32)


def trim_silence(
    audio: np.ndarray,
    sr: int,
    frame_ms: int = 30,
    energy_threshold: float = 0.005,
    min_speech_ms: int = 200,
    pad_ms: int = 150,
) -> np.ndarray:
    """
    Trim leading and trailing silence using energy-based VAD.
    Keeps a small padding around detected speech.
    """
    frame_len = int(sr * frame_ms / 1000)
    n_frames = len(audio) // frame_len

    if n_frames < 2:
        return audio

    # Compute per-frame energy
    energies = np.array(
        [
            np.sqrt(np.mean(audio[i * frame_len : (i + 1) * frame_len] ** 2))
            for i in range(n_frames)
        ]
    )

    # Find frames above threshold
    active = np.where(energies > energy_threshold)[0]

    if len(active) == 0:
        # No speech detected — return empty array to signify silence
        return np.array([], dtype=np.float32)

    first_active = active[0]
    last_active = active[-1]

    # Check minimum speech duration
    speech_duration_ms = (last_active - first_active + 1) * frame_ms
    if speech_duration_ms < min_speech_ms:
        return np.array([], dtype=np.float32)

    # Add padding
    pad_frames = int(pad_ms / frame_ms)
    start = max(0, first_active - pad_frames) * frame_len
    end = min(n_frames, last_active + pad_frames + 1) * frame_len

    return audio[start:end]


def auto_gain(audio: np.ndarray, target_rms: float = 0.1) -> np.ndarray:
    """
    Boost quiet signals to a target RMS level.
    Prevents over-amplification of pure noise using a noise floor check.
    """
    if len(audio) == 0:
        return audio

    current_rms = np.sqrt(np.mean(audio**2))
    # If the signal is below the noise floor, do not apply gain to avoid noise explosion
    if current_rms < 0.002:
        print(f"[preprocess] Signal RMS too low ({current_rms:.5f}) — skipping auto gain")
        return audio

    gain = target_rms / current_rms
    gain = min(gain, 20.0)  # Cap at 20x to prevent noise explosion
    return (audio * gain).astype(np.float32)


def peak_normalize(audio: np.ndarray, target_peak: float = 0.9) -> np.ndarray:
    """Normalize audio so the peak amplitude equals target_peak."""
    peak = np.abs(audio).max()
    if peak < 1e-6:
        return audio
    return (audio * (target_peak / peak)).astype(np.float32)


def preprocess(audio_path: str) -> tuple[np.ndarray, int]:
    """
    Full preprocessing pipeline for voice dictation.

    Returns (processed_float32_audio, sample_rate).
    """
    print(f"[preprocess] Loading: {audio_path}")
    audio, sr = load_wav(audio_path)
    print(f"[preprocess] Loaded: {len(audio)} samples, {sr} Hz, {len(audio)/sr:.1f}s")

    # 1. Bandpass filter — isolate speech frequencies
    audio = bandpass_filter(audio, sr)
    print(f"[preprocess] Bandpass filtered (300–3400 Hz)")

    # 2. Noise reduction — spectral gating
    audio = reduce_noise(audio, sr)
    print(f"[preprocess] Noise reduced (spectral gating)")

    # 3. Trim silence — remove dead air
    len_before = len(audio)
    audio = trim_silence(audio, sr)
    trimmed_pct = (1 - len(audio) / max(len_before, 1)) * 100
    print(f"[preprocess] Trimmed silence: {trimmed_pct:.0f}% removed, {len(audio)/sr:.1f}s remaining")

    # 4. Auto gain — boost quiet signals
    rms_before = np.sqrt(np.mean(audio**2))
    audio = auto_gain(audio)
    rms_after = np.sqrt(np.mean(audio**2))
    print(f"[preprocess] Auto gain: RMS {rms_before:.4f} → {rms_after:.4f}")

    # 5. Peak normalize
    audio = peak_normalize(audio)
    print(f"[preprocess] Peak normalized to 0.9")

    return audio, sr
