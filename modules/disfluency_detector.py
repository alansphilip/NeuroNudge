"""Disfluency detection module for NeuroNudge.

Analyzes audio signals to detect:
- Prolonged pauses (silence > threshold)
- Blocks (sudden energy drops)
- Hesitation patterns

Uses adaptive thresholds calibrated to the actual recording's noise floor
so results are accurate across different microphones and environments.
"""

import numpy as np
from modules.audio_utils import normalize_audio, compute_rms_energy


def _calibrate_silence_threshold(energy: np.ndarray,
                                 min_floor: float = 0.003) -> float:
    """
    Auto-calibrate silence threshold from the audio's actual noise floor.

    Uses the 20th percentile of non-zero energy frames as the noise floor,
    then sets the silence threshold just above it. This adapts to both
    quiet rooms and noisy environments automatically.

    Returns: silence threshold float
    """
    nonzero = energy[energy > min_floor]
    if len(nonzero) < 5:
        return 0.01  # Very quiet recording fallback
    noise_floor = float(np.percentile(nonzero, 20))
    # Silence = below 2.5x noise floor, min at min_floor
    threshold = max(noise_floor * 2.5, min_floor)
    return threshold


def detect_pauses(audio: np.ndarray, sample_rate: int = 16000,
                  silence_threshold: float = None,
                  min_pause_duration: float = 0.4) -> list:
    """
    Detect prolonged pauses (silence) in audio.

    Args:
        audio: Audio signal as numpy array
        sample_rate: Sample rate in Hz
        silence_threshold: RMS energy below this = silence.
                           If None, auto-calibrates from noise floor.
        min_pause_duration: Minimum pause length to flag (seconds)

    Returns:
        List of dicts with 'start', 'end', 'duration', 'type'
    """
    frame_size = 1024
    hop_size = 512
    energy = compute_rms_energy(audio, frame_size, hop_size)

    # Auto-calibrate threshold if not provided
    if silence_threshold is None:
        silence_threshold = _calibrate_silence_threshold(energy)

    min_pause_frames = int(min_pause_duration * sample_rate / hop_size)
    pauses = []
    in_silence = False
    silence_start = 0

    for i, e in enumerate(energy):
        if e < silence_threshold:
            if not in_silence:
                in_silence = True
                silence_start = i
        else:
            if in_silence:
                silence_length = i - silence_start
                if silence_length >= min_pause_frames:
                    start_time = silence_start * hop_size / sample_rate
                    end_time = i * hop_size / sample_rate
                    pauses.append({
                        'start': round(start_time, 2),
                        'end': round(end_time, 2),
                        'duration': round(end_time - start_time, 2),
                        'type': 'pause'
                    })
                in_silence = False

    # Handle pause at end of recording
    if in_silence:
        silence_length = len(energy) - silence_start
        if silence_length >= min_pause_frames:
            start_time = silence_start * hop_size / sample_rate
            end_time = len(energy) * hop_size / sample_rate
            pauses.append({
                'start': round(start_time, 2),
                'end': round(end_time, 2),
                'duration': round(end_time - start_time, 2),
                'type': 'pause'
            })

    return pauses


def detect_blocks(audio: np.ndarray, sample_rate: int = 16000,
                  energy_drop_ratio: float = 0.3,
                  min_block_duration: float = 0.2) -> list:
    """
    Detect speech blocks - sudden drops in energy during speech.

    Args:
        audio: Audio signal as numpy array
        sample_rate: Sample rate
        energy_drop_ratio: Ratio threshold for energy drop
        min_block_duration: Minimum block length (seconds)

    Returns:
        List of dicts with 'start', 'end', 'duration', 'type'
    """
    frame_size = 1024
    hop_size = 512
    energy = compute_rms_energy(audio, frame_size, hop_size)

    if len(energy) < 3:
        return []

    # Smooth energy to avoid single-frame noise spikes
    kernel = np.ones(5) / 5
    smoothed = np.convolve(energy, kernel, mode='same')

    # Adaptive speech threshold from actual speech frames
    noise_thresh = _calibrate_silence_threshold(energy)
    speech_frames = smoothed[smoothed > noise_thresh]
    if len(speech_frames) < 3:
        return []
    speech_threshold = float(np.percentile(speech_frames, 25))

    blocks = []
    min_block_frames = int(min_block_duration * sample_rate / hop_size)
    in_block = False
    block_start = 0

    for i in range(1, len(smoothed)):
        if (smoothed[i] < speech_threshold * energy_drop_ratio
                and smoothed[i - 1] > speech_threshold):
            if not in_block:
                in_block = True
                block_start = i
        elif smoothed[i] > speech_threshold:
            if in_block:
                block_length = i - block_start
                if block_length >= min_block_frames:
                    start_time = block_start * hop_size / sample_rate
                    end_time = i * hop_size / sample_rate
                    blocks.append({
                        'start': round(start_time, 2),
                        'end': round(end_time, 2),
                        'duration': round(end_time - start_time, 2),
                        'type': 'block'
                    })
                in_block = False

    return blocks


def compute_fluency_profile(audio: np.ndarray, sample_rate: int = 16000) -> dict:
    """
    Compute comprehensive fluency profile from audio signal.

    Returns dict with:
        - speaking_ratio: % of time with speech
        - pause_count: number of prolonged pauses
        - block_count: number of blocks
        - avg_pause_duration: average pause length
        - total_duration: total audio duration
        - energy_profile: frame-level energy array
        - events: list of all detected events
        - silence_threshold: the auto-calibrated threshold used
    """
    duration = len(audio) / sample_rate
    energy = compute_rms_energy(audio, 1024, 512)

    # Calibrate once, share with both detectors for consistency
    silence_thresh = _calibrate_silence_threshold(energy)

    pauses = detect_pauses(audio, sample_rate,
                           silence_threshold=silence_thresh)
    blocks = detect_blocks(audio, sample_rate)

    total_pause_time = sum(p['duration'] for p in pauses)
    speaking_time = max(duration - total_pause_time, 0)
    speaking_ratio = (speaking_time / duration * 100) if duration > 0 else 0

    all_events = sorted(pauses + blocks, key=lambda x: x['start'])

    return {
        'total_duration': round(duration, 2),
        'speaking_ratio': round(speaking_ratio, 1),
        'pause_count': len(pauses),
        'block_count': len(blocks),
        'avg_pause_duration': (
            round(float(np.mean([p['duration'] for p in pauses])), 2)
            if pauses else 0.0
        ),
        'max_pause_duration': (
            round(float(max(p['duration'] for p in pauses)), 2)
            if pauses else 0.0
        ),
        'total_pause_time': round(total_pause_time, 2),
        'energy_profile': energy,
        'events': all_events,
        'pauses': pauses,
        'blocks': blocks,
        'silence_threshold': round(silence_thresh, 5),
    }
