"""Metronome module for NeuroNudge.

Generates rhythmic pacing audio for speech practice.
"""

import numpy as np
from modules.audio_utils import numpy_to_wav_bytes


def generate_click(frequency: float = 1000, duration: float = 0.05,
                   sample_rate: int = 16000, amplitude: float = 0.7) -> np.ndarray:
    """Generate a single click/tick tone."""
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    # Short sine burst with exponential decay
    click = amplitude * np.sin(2 * np.pi * frequency * t)
    envelope = np.exp(-t * 40)  # Fast decay
    click = click * envelope
    return (click * 32767).astype(np.int16)


def generate_accent_click(frequency: float = 1500, duration: float = 0.06,
                          sample_rate: int = 16000) -> np.ndarray:
    """Generate an accented click (higher pitch, louder) for downbeat."""
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    click = 0.9 * np.sin(2 * np.pi * frequency * t)
    envelope = np.exp(-t * 35)
    click = click * envelope
    return (click * 32767).astype(np.int16)


def generate_metronome_track(bpm: int = 80, duration_seconds: float = 60,
                             sample_rate: int = 16000,
                             beats_per_measure: int = 4) -> bytes:
    """
    Generate a full metronome audio track.

    Args:
        bpm: Beats per minute (typically 60-100 for speech pacing)
        duration_seconds: Total track length in seconds
        sample_rate: Audio sample rate
        beats_per_measure: Beats per measure (accented first beat)

    Returns:
        WAV file bytes ready for st.audio()
    """
    beat_interval = 60.0 / bpm  # seconds between beats
    total_samples = int(duration_seconds * sample_rate)
    track = np.zeros(total_samples, dtype=np.int16)

    click = generate_click(sample_rate=sample_rate)
    accent = generate_accent_click(sample_rate=sample_rate)

    beat_num = 0
    current_time = 0.0

    while current_time < duration_seconds:
        sample_pos = int(current_time * sample_rate)

        # Use accented click on first beat of measure
        if beat_num % beats_per_measure == 0:
            tone = accent
        else:
            tone = click

        # Place the click in the track
        end_pos = min(sample_pos + len(tone), total_samples)
        actual_len = end_pos - sample_pos
        if actual_len > 0:
            track[sample_pos:end_pos] = tone[:actual_len]

        current_time += beat_interval
        beat_num += 1

    return numpy_to_wav_bytes(track, sample_rate)


def get_recommended_bpm(speaking_style: str = "normal") -> int:
    """Get recommended BPM based on speaking style."""
    recommendations = {
        "slow": 60,
        "normal": 80,
        "moderate": 90,
        "fast": 100,
    }
    return recommendations.get(speaking_style, 80)
