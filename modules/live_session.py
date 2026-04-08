"""Live pacing session module for NeuroNudge.

Provides real-time audio monitoring with automatic metronome activation
when STUTTERING is detected — via TWO detection methods:

1. ENERGY-DROP DETECTION (volume-based):
   - Uses SNR instead of absolute energy thresholds
   - Detects sustained silence/low energy during speech blocks
   - Triggers after configurable duration of low energy

2. REPETITION DETECTION (ASR-based):
   - Uses Vosk streaming recognition for real-time partial results
   - Detects consecutive word repetitions (e.g., "or or or orange")
   - Triggers when same word appears 3+ times in a row
   - Works even when speech volume stays normal

Both methods independently trigger the metronome. Recovery occurs when
the user resumes fluent speech (energy recovers OR new unique words).
"""

import json
import numpy as np
import threading
import time

try:
    import sounddevice as sd
    SD_AVAILABLE = True
except (ImportError, OSError):
    SD_AVAILABLE = False


class LivePacingSession:
    """Real-time speech monitoring with auto-triggered metronome pacing.

    Noise-robust: uses SNR-based detection instead of absolute energy.
    """

    def __init__(self, sample_rate=16000, bpm=72, sensitivity='Medium'):
        self.sample_rate = sample_rate
        self.bpm = bpm
        self.sensitivity = sensitivity

        # Sensitivity: how long silence must persist before triggering
        self._sens_config = {
            'Low':    {'drop_ratio': 0.35, 'pause_ignore_sec': 2.0},
            'Medium': {'drop_ratio': 0.30, 'pause_ignore_sec': 1.5},
            'High':   {'drop_ratio': 0.25, 'pause_ignore_sec': 1.0},
        }
        cfg = self._sens_config.get(sensitivity, self._sens_config['Medium'])
        self._drop_ratio = cfg['drop_ratio']  # Energy must drop to this
                                               # fraction of speech avg
        self._pause_ignore_sec = cfg['pause_ignore_sec']

        # State flags
        self.is_running = False
        self.metronome_enabled = True
        self.metronome_playing = False
        self.current_energy = 0.0
        self.stutter_count = 0

        # Adaptive calibration
        self._calibrated = False
        self._calibration_energies = []
        self._CALIBRATION_FRAMES = 12
        self.energy_threshold = 0.0
        self.recovery_threshold = 0.0
        self._speech_peak = 0.0
        self._speech_avg = 0.0

        # Rolling noise floor (adapts to environment changes)
        self._noise_floor = 0.0
        self._noise_tracker = []
        self._NOISE_WINDOW = 50  # Track last 50 low-energy frames

        # Rolling speech level (tracks recent speech energy)
        self._recent_speech = []
        self._SPEECH_WINDOW = 30  # Track last 30 speech frames

        # Warm-up: detect when user starts speaking
        self._user_has_spoken = False
        self._ambient_energy = 0.0
        self._ambient_samples = []
        self._AMBIENT_FRAMES = 10  # ~1 sec of ambient noise

        # Audio buffers
        self.recorded_chunks = []
        self.energy_history = []
        self.events = []

        # Internal timing
        self._low_energy_start = None
        self._start_time = 0
        self._lock = threading.Lock()
        self._metronome_lock = threading.Lock()  # Prevent double-trigger
        self._metronome_thread = None

        # Smoothing buffer (avoids single-frame glitches)
        self._energy_buffer = []
        self._SMOOTH_WINDOW = 4  # Average over 4 frames (~400ms)

        # ── Repetition stutter detection (ASR-based) ──
        self._vosk_recognizer = None
        self._recent_words = []        # Sliding window of recent words
        self._WORD_WINDOW = 10         # Track last 10 words
        self._REP_THRESHOLD = 2        # 2+ same word = stutter
        self._rep_stutter_active = False
        self.repetition_stutter_count = 0
        self._fluent_word_count = 0    # Unique words since last rep stutter
        self._FLUENT_RECOVERY = 3      # 3 unique words to stop metronome
        self._last_partial_len = 0     # Track partial result changes

        # ── Syllable/sub-word stutter detection (energy oscillation) ──
        self._energy_crossings = []    # Timestamps of threshold crossings
        self._OSCILLATION_WINDOW = 1.5 # Look at last 1.5 seconds
        self._OSCILLATION_MIN = 4      # 4+ crossings = rapid stuttering
        self._was_above_threshold = False
        self._oscillation_active = False

        # ── Metronome persistence ──
        self._recovery_start = None     # When recovery was first detected
        self._RECOVERY_GRACE_SEC = 0.5  # Fluent speech must last 0.5s to stop

        # Pre-generate metronome click
        self._make_click()

    def _make_click(self):
        """Generate a click tone for the metronome."""
        dur = 0.04
        t = np.linspace(0, dur, int(self.sample_rate * dur), endpoint=False)
        click = 0.7 * np.sin(2 * np.pi * 880 * t) * np.exp(-t * 45)
        self._click = click.astype(np.float32)
        self._beat_samples = int(60.0 / self.bpm * self.sample_rate)

    def _smoothed_energy(self, rms):
        """Return smoothed energy to avoid single-frame noise."""
        self._energy_buffer.append(rms)
        if len(self._energy_buffer) > self._SMOOTH_WINDOW:
            self._energy_buffer.pop(0)
        return float(np.mean(self._energy_buffer))

    def _update_noise_floor(self, rms):
        """Update rolling noise floor estimate from low-energy frames."""
        self._noise_tracker.append(rms)
        if len(self._noise_tracker) > self._NOISE_WINDOW:
            self._noise_tracker.pop(0)
        self._noise_floor = float(np.percentile(self._noise_tracker, 30))

    def _update_speech_level(self, rms):
        """Track recent speech energy level for adaptive thresholds."""
        self._recent_speech.append(rms)
        if len(self._recent_speech) > self._SPEECH_WINDOW:
            self._recent_speech.pop(0)

    def _get_snr(self, energy):
        """Compute signal-to-noise ratio relative to noise floor."""
        if self._noise_floor <= 0:
            return 100.0  # Very high SNR if no noise
        return energy / self._noise_floor

    def _recalculate_thresholds(self):
        """Dynamically adjust thresholds based on recent speech and noise."""
        if not self._recent_speech:
            return

        recent_avg = float(np.mean(self._recent_speech))
        noise = max(self._noise_floor, 0.0001)

        # Dynamic range: how much louder speech is than noise
        dynamic_range = recent_avg - noise

        if dynamic_range <= 0:
            # Speech barely above noise — use very tight thresholds
            self.energy_threshold = noise * 1.2
            self.recovery_threshold = noise * 1.5
        else:
            # Stutter threshold: noise floor + small fraction of dynamic range
            self.energy_threshold = noise + dynamic_range * self._drop_ratio
            # Recovery: noise floor + larger fraction (must clearly be speaking)
            self.recovery_threshold = noise + dynamic_range * 0.45

    def _check_repetition_stutter(self, audio_chunk, elapsed):
        """Feed audio to Vosk and check for word repetitions in real-time.

        Detects stuttering like 'or or or orange' where volume stays normal
        but the same word is repeated 3+ times consecutively.

        Checks BOTH partial results (low latency, updates every frame)
        and final results (when Vosk finalizes a phrase).
        """
        if self._vosk_recognizer is None:
            return

        # Convert float32 chunk to int16 bytes for Vosk
        audio_int16 = (np.clip(audio_chunk, -1.0, 1.0) * 32767
                       ).astype(np.int16)
        audio_bytes = audio_int16.tobytes()

        # Feed to recognizer
        is_final = self._vosk_recognizer.AcceptWaveform(audio_bytes)

        if is_final:
            # Phrase finalized — check final result, then reset tracking
            result = json.loads(self._vosk_recognizer.Result())
            final_text = result.get('text', '').strip().lower()
            if final_text:
                self._scan_for_repetitions(final_text.split(), elapsed)
            # Reset partial tracking for next phrase
            self._last_partial_len = 0
            return

        # Check partial result (updates every ~100ms)
        partial = json.loads(self._vosk_recognizer.PartialResult())
        partial_text = partial.get('partial', '').strip().lower()

        if not partial_text:
            self._last_partial_len = 0
            return

        words = partial_text.split()
        if len(words) == self._last_partial_len:
            return  # No new words since last check

        self._last_partial_len = len(words)
        self._scan_for_repetitions(words, elapsed)

    def _scan_for_repetitions(self, words, elapsed):
        """Scan a word list for consecutive repetitions (3+)."""
        if len(words) < self._REP_THRESHOLD:
            return

        # Find longest consecutive run of same word at end of list
        consec_count = 1
        for i in range(len(words) - 1, 0, -1):
            if words[i] == words[i - 1]:
                consec_count += 1
            else:
                break

        if consec_count >= self._REP_THRESHOLD:
            repeated_word = words[-1]
            if not self._rep_stutter_active:
                self._rep_stutter_active = True
                self.repetition_stutter_count += 1
                self._fluent_word_count = 0
                self._trigger_metronome(
                    elapsed, 'repetition_stutter',
                    word=repeated_word, count=consec_count)
        else:
            # Check for fluent recovery
            if self._rep_stutter_active and len(words) >= 2:
                # Count unique consecutive words at end
                unique_run = 1
                for i in range(len(words) - 1, 0, -1):
                    if words[i] != words[i - 1]:
                        unique_run += 1
                        if unique_run >= self._FLUENT_RECOVERY:
                            break
                    else:
                        break

                if unique_run >= self._FLUENT_RECOVERY:
                    self._rep_stutter_active = False
                    self._stop_metronome(elapsed, 'fluent_recovery')

    def _check_energy_oscillation(self, smoothed_energy, elapsed):
        """Detect rapid energy oscillations that indicate syllable-level stuttering.

        When someone stutters at the syllable level (b-b-b-ball), energy
        rapidly alternates between speech and silence. We detect this by
        counting how many times energy crosses a midpoint threshold
        within a short time window.

        4+ crossings in 1.5 seconds = syllable stuttering → trigger metronome.
        """
        if not self._calibrated:
            return

        # Use midpoint between noise floor and speech average as crossing line
        midpoint = (self.energy_threshold + self.recovery_threshold) / 2
        is_above = smoothed_energy > midpoint

        # Detect threshold crossing (above→below or below→above)
        if is_above != self._was_above_threshold:
            self._energy_crossings.append(elapsed)
            self._was_above_threshold = is_above

        # Trim old crossings outside the window
        cutoff = elapsed - self._OSCILLATION_WINDOW
        self._energy_crossings = [
            t for t in self._energy_crossings if t > cutoff
        ]

        crossing_count = len(self._energy_crossings)

        if crossing_count >= self._OSCILLATION_MIN:
            # Rapid oscillation detected — syllable stuttering
            if not self._oscillation_active:
                self._oscillation_active = True
                self._trigger_metronome(
                    elapsed, 'syllable_stutter',
                    crossings=crossing_count)
        else:
            # Oscillation stopped — check for recovery
            if self._oscillation_active and crossing_count <= 1:
                self._oscillation_active = False
                # Only stop if no other detection mode is active
                if not self._rep_stutter_active:
                    self._stop_metronome(elapsed, 'oscillation_recovery')

    def _recording_thread(self):
        """Background thread: records audio, calibrates, and monitors."""
        block_size = 1600  # 100ms at 16kHz
        frame_idx = 0
        recal_counter = 0  # Re-calibrate every N frames

        try:
            with sd.InputStream(samplerate=self.sample_rate, channels=1,
                                dtype='float32', blocksize=block_size) as stream:
                while self.is_running:
                    data, overflowed = stream.read(block_size)
                    audio = data[:, 0].copy()
                    frame_idx += 1

                    with self._lock:
                        self.recorded_chunks.append(audio)

                    rms = float(np.sqrt(np.mean(audio ** 2)))
                    smoothed = self._smoothed_energy(rms)
                    elapsed = time.time() - self._start_time

                    with self._lock:
                        self.current_energy = smoothed
                        self.energy_history.append(rms)

                    # ── PHASE 0: Learn ambient noise (first ~1 second) ──
                    if frame_idx <= self._AMBIENT_FRAMES:
                        self._ambient_samples.append(rms)
                        if frame_idx == self._AMBIENT_FRAMES:
                            self._ambient_energy = float(
                                np.mean(self._ambient_samples))
                            self._noise_floor = self._ambient_energy
                            # Seed noise tracker
                            self._noise_tracker = list(self._ambient_samples)
                            print(f"[LiveSession] Ambient energy: "
                                  f"{self._ambient_energy:.6f}")
                        continue

                    # ── PHASE 1: Wait for user to start speaking ──
                    # In noisy environments, use SNR instead of absolute
                    snr = self._get_snr(rms)
                    speech_snr_thresh = 2.0  # Speech must be 2x noise floor

                    if not self._user_has_spoken:
                        if snr > speech_snr_thresh and rms > 0.002:
                            self._user_has_spoken = True
                            with self._lock:
                                self.events.append({
                                    'type': 'speech_detected',
                                    'time': round(elapsed, 2),
                                    'energy': round(rms, 5),
                                    'snr': round(snr, 2),
                                })
                            print(f"[LiveSession] Speech detected at "
                                  f"{elapsed:.1f}s, energy={rms:.5f}, "
                                  f"SNR={snr:.1f}x")
                        else:
                            # Still ambient — keep updating noise floor
                            self._update_noise_floor(rms)
                        continue

                    # ── PHASE 2: Calibrate from actual speech ──
                    if not self._calibrated:
                        if snr > speech_snr_thresh:
                            self._calibration_energies.append(rms)

                        if len(self._calibration_energies) >= \
                                self._CALIBRATION_FRAMES:
                            self._speech_avg = float(np.mean(
                                self._calibration_energies))
                            self._speech_peak = float(np.max(
                                self._calibration_energies))

                            # Seed the recent speech tracker
                            self._recent_speech = list(
                                self._calibration_energies)

                            # Calculate initial thresholds
                            noise = max(self._noise_floor, 0.0001)
                            dynamic_range = self._speech_avg - noise

                            if dynamic_range <= 0:
                                # Very noisy — use tight thresholds
                                self.energy_threshold = noise * 1.2
                                self.recovery_threshold = noise * 1.5
                            else:
                                self.energy_threshold = (
                                    noise + dynamic_range * self._drop_ratio)
                                self.recovery_threshold = (
                                    noise + dynamic_range * 0.45)

                            self._calibrated = True

                            with self._lock:
                                self.events.append({
                                    'type': 'calibrated',
                                    'time': round(elapsed, 2),
                                    'energy': round(self._speech_avg, 5),
                                    'threshold': round(
                                        self.energy_threshold, 5),
                                    'recovery': round(
                                        self.recovery_threshold, 5),
                                    'noise_floor': round(noise, 5),
                                    'dynamic_range': round(
                                        dynamic_range, 5),
                                })
                            print(
                                f"[LiveSession] Calibrated at {elapsed:.1f}s: "
                                f"speech_avg={self._speech_avg:.5f}, "
                                f"noise_floor={noise:.5f}, "
                                f"dynamic_range={dynamic_range:.5f}, "
                                f"stutter_thresh="
                                f"{self.energy_threshold:.5f}, "
                                f"recovery_thresh="
                                f"{self.recovery_threshold:.5f}"
                            )
                        continue

                    # ── PHASE 3: Stutter detection (calibrated) ──

                    # Continuously track noise floor from low-energy frames
                    if smoothed < self.energy_threshold:
                        self._update_noise_floor(rms)

                    # Track speech energy from high-energy frames
                    if smoothed > self.recovery_threshold:
                        self._update_speech_level(rms)

                    # Periodically re-calculate thresholds to adapt to
                    # changing noise (e.g. someone opens a door, AC turns on)
                    recal_counter += 1
                    if recal_counter >= 20:  # Every 2 seconds
                        recal_counter = 0
                        self._recalculate_thresholds()

                    # ── Detection Mode 1: Energy drop (volume loss) ──
                    if smoothed < self.energy_threshold:
                        # Energy is low — start or continue timing
                        if self._low_energy_start is None:
                            self._low_energy_start = time.time()

                        low_duration = time.time() - self._low_energy_start

                        # Only trigger after sustained low energy
                        if low_duration >= self._pause_ignore_sec:
                            self._trigger_metronome(
                                elapsed, 'energy_drop',
                                energy=round(smoothed, 5),
                                pause_duration=round(low_duration, 2))

                    else:
                        # Energy is above stutter threshold
                        if smoothed > self.recovery_threshold:
                            self._stop_metronome(elapsed, 'energy_recovery')
                        # Reset low-energy timer
                        self._low_energy_start = None

                    # ── Detection Mode 2: Repetition stutter (ASR) ──
                    # Checks partial ASR for repeated words
                    self._check_repetition_stutter(audio, elapsed)

                    # ── Detection Mode 3: Energy oscillation ──
                    # Detects sub-word syllable stuttering (b-b-b-ball)
                    # by tracking rapid energy threshold crossings
                    self._check_energy_oscillation(
                        smoothed, elapsed)

        except Exception as e:
            print(f"[LiveSession] Recording error: {e}")
            import traceback
            traceback.print_exc()

    def _trigger_metronome(self, elapsed, reason, **extra):
        """Unified metronome trigger — prevents double-start from both modes."""
        with self._metronome_lock:
            # Reset any pending recovery — stutter is happening again
            self._recovery_start = None
            if self.metronome_playing or not self.metronome_enabled:
                return  # Already playing or disabled
            self.metronome_playing = True
            self.stutter_count += 1
            event = {
                'type': 'metronome_start',
                'time': round(elapsed, 2),
                'reason': reason,
            }
            event.update(extra)
            with self._lock:
                self.events.append(event)
            print(f"[LiveSession] METRONOME ON at {elapsed:.1f}s "
                  f"(reason: {reason})")
            self._start_metronome()

    def _stop_metronome(self, elapsed, reason):
        """Stop metronome only after sustained fluent recovery.

        Instead of stopping instantly, requires fluent speech to persist
        for _RECOVERY_GRACE_SEC seconds. If stutter recurs during that
        window, the timer resets and metronome keeps playing.
        """
        with self._metronome_lock:
            if not self.metronome_playing:
                return

            now = time.time()

            # First call — start the recovery grace timer
            if self._recovery_start is None:
                self._recovery_start = now
                return  # Don't stop yet, start timing

            # Check if grace period has elapsed
            recovery_duration = now - self._recovery_start
            if recovery_duration < self._RECOVERY_GRACE_SEC:
                return  # Still in grace period, keep playing

            # Recovery confirmed — stop metronome
            self.metronome_playing = False
            self._rep_stutter_active = False
            self._oscillation_active = False
            self._recovery_start = None
            with self._lock:
                self.events.append({
                    'type': 'metronome_stop',
                    'time': round(elapsed, 2),
                    'reason': reason,
                })
            print(f"[LiveSession] METRONOME OFF at {elapsed:.1f}s "
                  f"({reason})")

    def _start_metronome(self):
        """Start playing metronome clicks using a dedicated output stream."""
        if self._metronome_thread and self._metronome_thread.is_alive():
            return

        def _play():
            try:
                # Build one beat-interval of audio
                beat_samples = int(60.0 / self.bpm * self.sample_rate)
                beat_buf = np.zeros(beat_samples, dtype=np.float32)
                click_len = min(len(self._click), beat_samples)
                beat_buf[:click_len] = self._click[:click_len]

                # Use a dedicated OutputStream so it doesn't fight
                # with the InputStream used for recording
                with sd.OutputStream(samplerate=self.sample_rate,
                                     channels=1, dtype='float32',
                                     blocksize=beat_samples) as out:
                    while self.metronome_playing and self.is_running:
                        out.write(beat_buf.reshape(-1, 1))
            except Exception as e:
                print(f"[LiveSession] Metronome error: {e}")

        self._metronome_thread = threading.Thread(target=_play, daemon=True)
        self._metronome_thread.start()

    def start(self):
        """Start the live pacing session."""
        if not SD_AVAILABLE:
            raise RuntimeError("sounddevice is not available.")

        self.is_running = True
        self.metronome_playing = False
        self._user_has_spoken = False
        self._calibrated = False
        self._calibration_energies = []
        self._ambient_samples = []
        self._ambient_energy = 0.0
        self._noise_floor = 0.0
        self._noise_tracker = []
        self._recent_speech = []
        self.recorded_chunks = []
        self.energy_history = []
        self.events = []
        self.current_energy = 0.0
        self.stutter_count = 0
        self.repetition_stutter_count = 0
        self._low_energy_start = None
        self._start_time = time.time()
        self._metronome_thread = None
        self.energy_threshold = 0.0
        self.recovery_threshold = 0.0
        self._energy_buffer = []

        # Initialize real-time ASR in background (don't block start)
        self._recent_words = []
        self._rep_stutter_active = False
        self._fluent_word_count = 0
        self._last_partial_len = 0
        self._energy_crossings = []
        self._was_above_threshold = False
        self._oscillation_active = False
        self._recovery_start = None
        self._vosk_recognizer = None

        def _init_vosk():
            try:
                from modules.vosk_asr import get_streaming_recognizer
                rec, name = get_streaming_recognizer(self.sample_rate)
                self._vosk_recognizer = rec
                if rec:
                    print(f"[LiveSession] ASR repetition detection: "
                          f"ON (model: {name})")
                else:
                    print("[LiveSession] ASR repetition detection: "
                          "OFF (no model)")
            except Exception as e:
                print(f"[LiveSession] ASR init error: {e}")

        threading.Thread(target=_init_vosk, daemon=True).start()

        self._thread = threading.Thread(
            target=self._recording_thread, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop the session and return results."""
        self.is_running = False
        self.metronome_playing = False

        if hasattr(self, '_thread') and self._thread.is_alive():
            self._thread.join(timeout=2.0)

        try:
            sd.stop()
        except Exception:
            pass

        elapsed = time.time() - self._start_time

        with self._lock:
            if self.recorded_chunks:
                audio_float = np.concatenate(self.recorded_chunks)
            else:
                audio_float = np.zeros(
                    int(self.sample_rate), dtype=np.float32)
            events = list(self.events)
            energy_hist = list(self.energy_history)

        audio_float = np.clip(audio_float, -1.0, 1.0)
        audio_int16 = (audio_float * 32767).astype(np.int16)

        return {
            'audio': audio_int16,
            'audio_float': audio_float,
            'sample_rate': self.sample_rate,
            'duration': round(elapsed, 2),
            'energy_history': energy_hist,
            'events': events,
            'stutter_count': self.stutter_count,
            'repetition_stutter_count': self.repetition_stutter_count,
            'calibration': {
                'speech_peak': round(self._speech_peak, 5),
                'speech_avg': round(self._speech_avg, 5),
                'energy_threshold': round(self.energy_threshold, 5),
                'recovery_threshold': round(self.recovery_threshold, 5),
                'ambient_energy': round(self._ambient_energy, 5),
                'noise_floor': round(self._noise_floor, 5),
                'calibrated': self._calibrated,
                'pause_ignore_sec': self._pause_ignore_sec,
                'asr_enabled': self._vosk_recognizer is not None,
            }
        }

    def get_status(self):
        """Get current session status for UI display."""
        elapsed = time.time() - self._start_time if self.is_running else 0
        with self._lock:
            return {
                'is_running': self.is_running,
                'metronome_playing': self.metronome_playing,
                'metronome_enabled': self.metronome_enabled,
                'current_energy': round(self.current_energy, 5),
                'stutter_count': self.stutter_count,
                'repetition_stutter_count': self.repetition_stutter_count,
                'rep_stutter_active': self._rep_stutter_active,
                'elapsed_seconds': round(elapsed, 1),
                'user_has_spoken': self._user_has_spoken,
                'calibrated': self._calibrated,
                'threshold': round(self.energy_threshold, 5),
            }


def check_microphone():
    """Check if a microphone is available."""
    if not SD_AVAILABLE:
        return {
            'available': False,
            'message':
                'sounddevice not installed. Run: pip install sounddevice',
        }
    try:
        default_input = sd.query_devices(kind='input')
        return {
            'available': True,
            'device_name': default_input.get('name', 'Unknown'),
            'message':
                f"Microphone ready: {default_input.get('name', 'Default')}",
        }
    except Exception as e:
        return {
            'available': False,
            'message': f'No microphone detected: {str(e)}',
        }
