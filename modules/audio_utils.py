"""Audio capture and utility functions for NeuroNudge."""

import io
import wave
import struct
import numpy as np
from pathlib import Path

# Default audio settings
SAMPLE_RATE = 16000  # Vosk requires 16kHz
CHANNELS = 1
DTYPE = np.int16


def audio_bytes_to_numpy(audio_bytes: bytes) -> np.ndarray:
    """Convert raw audio bytes (from st.audio_input) to numpy array."""
    try:
        bio = io.BytesIO(audio_bytes)
        with wave.open(bio, 'rb') as wf:
            n_frames = wf.getnframes()
            raw_data = wf.readframes(n_frames)
            sample_width = wf.getsampwidth()
            sr = wf.getframerate()
            n_channels = wf.getnchannels()

            if sample_width == 2:
                audio = np.frombuffer(raw_data, dtype=np.int16)
            elif sample_width == 4:
                audio = np.frombuffer(raw_data, dtype=np.int32)
                audio = (audio / 2**16).astype(np.int16)
            else:
                audio = np.frombuffer(raw_data, dtype=np.int16)

            # Convert stereo to mono
            if n_channels > 1:
                audio = audio.reshape(-1, n_channels)[:, 0]

            return audio, sr
    except Exception:
        # Fallback: try reading as raw PCM
        audio = np.frombuffer(audio_bytes, dtype=np.int16)
        return audio, SAMPLE_RATE


def numpy_to_wav_bytes(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> bytes:
    """Convert numpy array to WAV bytes."""
    bio = io.BytesIO()
    with wave.open(bio, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(audio.astype(np.int16).tobytes())
    return bio.getvalue()


def save_wav(audio: np.ndarray, filepath: str, sample_rate: int = SAMPLE_RATE):
    """Save numpy audio array to WAV file."""
    filepath = Path(filepath)
    filepath.parent.mkdir(parents=True, exist_ok=True)

    with wave.open(str(filepath), 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio.astype(np.int16).tobytes())


def load_wav(filepath: str):
    """Load WAV file and return numpy array + sample rate."""
    with wave.open(filepath, 'rb') as wf:
        sr = wf.getframerate()
        raw = wf.readframes(wf.getnframes())
        audio = np.frombuffer(raw, dtype=np.int16)
    return audio, sr


def get_duration(audio: np.ndarray, sample_rate: int = SAMPLE_RATE) -> float:
    """Get audio duration in seconds."""
    return len(audio) / sample_rate


def normalize_audio(audio: np.ndarray) -> np.ndarray:
    """Normalize audio to [-1, 1] range as float."""
    # If already float32/float64, assume it's already normalized
    if audio.dtype in (np.float32, np.float64):
        return audio.astype(np.float32)
    return audio.astype(np.float32) / 32768.0


def compute_rms_energy(audio: np.ndarray, frame_size: int = 1024, hop_size: int = 512) -> np.ndarray:
    """Compute frame-level RMS energy."""
    audio_float = normalize_audio(audio)
    n_frames = (len(audio_float) - frame_size) // hop_size + 1
    energy = np.zeros(n_frames)

    for i in range(n_frames):
        start = i * hop_size
        frame = audio_float[start:start + frame_size]
        energy[i] = np.sqrt(np.mean(frame ** 2))

    return energy


def resample_audio(audio: np.ndarray, orig_sr: int, target_sr: int = SAMPLE_RATE) -> np.ndarray:
    """Simple resampling using linear interpolation."""
    if orig_sr == target_sr:
        return audio

    duration = len(audio) / orig_sr
    target_length = int(duration * target_sr)
    indices = np.linspace(0, len(audio) - 1, target_length)
    resampled = np.interp(indices, np.arange(len(audio)), audio.astype(np.float32))
    return resampled.astype(np.int16)
