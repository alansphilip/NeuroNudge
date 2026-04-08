"""Speech recognition for NeuroNudge.

Auto-selects the best available backend:
  - Cloud (GROQ_API_KEY set) : Groq Whisper-large-v3 (~4% WER, instant)
  - Local (large model)      : Vosk vosk-model-en-us-0.22 (~9.6% WER)
  - Local (small model)      : Vosk vosk-model-small-en-us-0.15 (fallback)

Existing local behaviour is completely unchanged.
"""

import io
import json
import os
import numpy as np
import scipy.io.wavfile as wf
from pathlib import Path

try:
    from vosk import Model, KaldiRecognizer, SetLogLevel
    VOSK_AVAILABLE = True
    SetLogLevel(-1)
except ImportError:
    VOSK_AVAILABLE = False


# ─────────────────────────────────────────────────────────────
# Groq Whisper helper
# ─────────────────────────────────────────────────────────────
def _get_groq_key() -> str:
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("GROQ_API_KEY", "")
        except Exception:
            pass
    return key


def _transcribe_with_groq(audio: np.ndarray,
                          sample_rate: int = 16000) -> dict:
    """
    Transcribe using Groq Whisper-large-v3 API (cloud fallback).
    Returns same dict structure as Vosk transcribe_audio().
    """
    import requests

    # Convert numpy → WAV bytes in memory
    if audio.dtype != np.int16:
        audio_i16 = (np.clip(audio.astype(np.float32), -1.0, 1.0)
                     * 32767).astype(np.int16)
    else:
        audio_i16 = audio

    buf = io.BytesIO()
    wf.write(buf, sample_rate, audio_i16)
    buf.seek(0)

    groq_key = _get_groq_key()
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {groq_key}"},
            files={"file": ("audio.wav", buf, "audio/wav")},
            data={
                "model": "whisper-large-v3",
                "language": "en",
                "response_format": "verbose_json",
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        full_text = data.get("text", "").strip()

        # Build word-level timestamps from segments
        words = []
        for seg in data.get("segments", []):
            for w in seg.get("words", []):
                words.append({
                    "word": w.get("word", "").strip(),
                    "start": w.get("start", 0.0),
                    "end": w.get("end", 0.0),
                })

        return {
            "success": True,
            "text": full_text,
            "corrected_text": full_text,   # Whisper is already accurate
            "raw_text": full_text,
            "words": words,
            "model": "groq-whisper-large-v3",
            "error": None,
        }
    except Exception as e:
        return {
            "success": False,
            "text": "",
            "corrected_text": "",
            "raw_text": "",
            "words": [],
            "model": "groq-whisper-large-v3",
            "error": str(e),
        }

# Model paths — ordered by preference (best first)
MODEL_CANDIDATES = [
    Path("models/vosk-model-en-us-0.22"),         # Large (~1.8 GB, best)
    Path("models/vosk-model-en-us-0.22-lgraph"),   # Large-graph variant
    Path("models/vosk-model-small-en-us-0.15"),    # Small (~40 MB, fallback)
]

# Cache the loaded model to avoid reloading on every call
_cached_model = None
_cached_model_path = None


def _find_best_model() -> Path:
    """Find the best available Vosk model on disk."""
    for candidate in MODEL_CANDIDATES:
        if candidate.exists() and (candidate / 'conf').exists():
            return candidate
    return None


def _get_model(model_path: str = None):
    """Load and cache the Vosk model."""
    global _cached_model, _cached_model_path

    if model_path:
        path = Path(model_path)
    else:
        path = _find_best_model()

    if path is None:
        return None, None

    # Return cached model if same path
    if _cached_model is not None and _cached_model_path == str(path):
        return _cached_model, path

    try:
        _cached_model = Model(str(path))
        _cached_model_path = str(path)
        print(f"[Vosk] Loaded model: {path.name}")
        return _cached_model, path
    except Exception as e:
        print(f"[Vosk] Failed to load model {path}: {e}")
        return None, None


def check_vosk_model(model_path: str = None) -> dict:
    """Check if Vosk is available and model is downloaded."""
    if not VOSK_AVAILABLE:
        return {
            'available': False,
            'model_found': False,
            'message': 'Vosk is not installed. Run: pip install vosk'
        }

    best = _find_best_model() if not model_path else Path(model_path)

    if best and best.exists() and (best / 'conf').exists():
        is_large = 'small' not in best.name
        return {
            'available': True,
            'model_found': True,
            'model_name': best.name,
            'is_large_model': is_large,
            'message': (
                f'Vosk model: {best.name} '
                f'({"high accuracy" if is_large else "basic accuracy"})'
            )
        }

    return {
        'available': True,
        'model_found': False,
        'message': (
            "No Vosk model found.\n\n"
            "For best accuracy (90%+), download the LARGE model:\n"
            "  vosk-model-en-us-0.22 (~1.8 GB)\n"
            "  https://alphacephei.com/vosk/models\n\n"
            "Steps:\n"
            "1. Download the model zip\n"
            "2. Extract to: models/vosk-model-en-us-0.22/\n"
            "3. Restart the app"
        )
    }


def _prepare_audio(audio: np.ndarray) -> bytes:
    """Convert audio array to int16 bytes for Vosk."""
    if audio.dtype == np.float32 or audio.dtype == np.float64:
        audio_int16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    else:
        audio_int16 = audio.astype(np.int16)
    return audio_int16.tobytes()


def transcribe_audio(audio: np.ndarray, sample_rate: int = 16000,
                     model_path: str = None) -> dict:
    """
    Transcribe audio — auto-routes to Groq Whisper (cloud) or Vosk (local).

    If GROQ_API_KEY is set → uses Groq Whisper-large-v3 (~4% WER, instant).
    Otherwise             → uses best available Vosk model (large > small).

    Args:
        audio:       numpy array (int16 or float32) at 16kHz
        sample_rate: sample rate (must be 16000 for Vosk)
        model_path:  optional path override for Vosk model (ignored on cloud)

    Returns:
        dict with 'success', 'text', 'corrected_text', 'raw_text',
                  'words', 'model', 'error'
    """
    # ── Cloud path: Groq Whisper ──────────────────────────────
    if _get_groq_key():
        return _transcribe_with_groq(audio, sample_rate)

    # ── Local path: Vosk ──────────────────────────────────────
    model, path = _get_model(model_path)

    if model is None:
        status = check_vosk_model(model_path)
        return {
            'text': '',
            'words': [],
            'success': False,
            'error': status['message'],
            'model_used': None
        }

    try:
        recognizer = KaldiRecognizer(model, sample_rate)
        recognizer.SetWords(True)

        # Always convert to int16 bytes first
        # (handles both float32 and int16 input correctly)
        audio_bytes = _prepare_audio(audio)

        # Chunk size in bytes: 1.5 seconds of 16kHz 16-bit mono
        # = 16000 samples/s * 1.5s * 2 bytes/sample = 48000 bytes
        # Larger chunks give the model more context = better accuracy
        CHUNK_BYTES = 48000  # 1.5s per chunk

        all_words = []
        text_parts = []

        for i in range(0, len(audio_bytes), CHUNK_BYTES):
            chunk = audio_bytes[i:i + CHUNK_BYTES]
            if len(chunk) < 800:  # Skip tiny trailing chunks
                continue
            if recognizer.AcceptWaveform(chunk):
                result = json.loads(recognizer.Result())
                part_text = result.get('text', '').strip()
                if part_text:
                    text_parts.append(part_text)
                for w in result.get('result', []):
                    conf = w.get('conf', 0)
                    if conf >= 0.5:  # Filter low-confidence words
                        all_words.append({
                            'word': w.get('word', ''),
                            'start': round(w.get('start', 0), 2),
                            'end': round(w.get('end', 0), 2),
                            'confidence': round(conf, 2),
                        })

        # Get final segment (critical — always call this)
        final = json.loads(recognizer.FinalResult())
        final_text = final.get('text', '').strip()
        if final_text:
            text_parts.append(final_text)
        for w in final.get('result', []):
            conf = w.get('conf', 0)
            if conf >= 0.5:
                all_words.append({
                    'word': w.get('word', ''),
                    'start': round(w.get('start', 0), 2),
                    'end': round(w.get('end', 0), 2),
                    'confidence': round(conf, 2),
                })

        # Deduplicate words by start time (avoid double-counting)
        seen_starts = set()
        unique_words = []
        for w in all_words:
            if w['start'] not in seen_starts:
                seen_starts.add(w['start'])
                unique_words.append(w)
        all_words = sorted(unique_words, key=lambda x: x['start'])

        full_text = ' '.join(text_parts)

        avg_conf = 0.0
        if all_words:
            avg_conf = float(np.mean([w['confidence'] for w in all_words]))

        return {
            'text': full_text,
            'words': all_words,
            'success': True,
            'error': None,
            'model_used': path.name,
            'avg_confidence': round(avg_conf, 3),
        }

    except Exception as e:
        return {
            'text': '',
            'words': [],
            'success': False,
            'error': f'Transcription error: {str(e)}',
            'model_used': path.name if path else None
        }



def transcribe_audio_streaming(audio: np.ndarray, sample_rate: int = 16000,
                               model_path: str = None) -> list:
    """
    Transcribe audio with partial results for longer recordings.
    Returns list of text segments.
    """
    model, path = _get_model(model_path)
    if model is None:
        return []

    try:
        recognizer = KaldiRecognizer(model, sample_rate)
        recognizer.SetWords(True)

        segments = []
        audio_bytes = _prepare_audio(audio)

        is_large = 'small' not in path.name
        chunk_size = 32000 if is_large else 16000

        for i in range(0, len(audio_bytes), chunk_size):
            chunk = audio_bytes[i:i + chunk_size]
            if recognizer.AcceptWaveform(chunk):
                result = json.loads(recognizer.Result())
                if result.get('text'):
                    segments.append(result['text'])

        final = json.loads(recognizer.FinalResult())
        if final.get('text'):
            segments.append(final['text'])

        return segments

    except Exception:
        return []


def get_streaming_recognizer(sample_rate: int = 16000):
    """
    Get a KaldiRecognizer for real-time streaming recognition.

    Used by LivePacingSession for real-time repetition stutter detection.
    Returns (recognizer, model_name) or (None, None) if unavailable.
    """
    if not VOSK_AVAILABLE:
        return None, None

    model, path = _get_model()
    if model is None:
        return None, None

    try:
        recognizer = KaldiRecognizer(model, sample_rate)
        try:
            recognizer.SetPartialWords(True)
        except Exception:
            pass  # Not available in all Vosk versions
        return recognizer, path.name
    except Exception as e:
        print(f"[Vosk] Failed to create streaming recognizer: {e}")
        return None, None
