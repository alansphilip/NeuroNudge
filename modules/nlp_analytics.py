"""NLP analytics module for NeuroNudge.

Analyzes transcribed text for:
- Filler words (true fillers like um/uh PLUS contextual fillers like "like")
- Word repetitions (stuttering indicator)
- Speech rate (WPM)
- Fluency metrics

Improved filler word detection:
- "True fillers" (um, uh, hmm) are ALWAYS counted
- "Contextual fillers" (like, so, well, basically) are only counted when
  they appear at sentence-start or in non-meaningful positions
"""

import re
from collections import Counter


# ── True fillers: ALWAYS counted as fillers ──
TRUE_FILLERS = {
    'um', 'uh', 'uhm', 'umm', 'hmm', 'hm', 'er', 'ah',
    'erm', 'mm', 'mmm',
}

# ── Contextual fillers: only counted in filler-like positions ──
# These are real words that CAN be fillers when used as verbal padding.
# We count them if they appear at the start of a clause or surrounded
# by other fillers.
CONTEXTUAL_FILLERS = {
    'like', 'basically', 'actually', 'literally',
    'so', 'well', 'right', 'okay', 'ok',
}

# ── Multi-word filler phrases ──
MULTI_FILLERS = {
    'you know', 'i mean', 'kind of', 'sort of',
    'you see', 'let me see', 'how do i say',
}

# Combined for highlighting
ALL_SINGLE_FILLERS = TRUE_FILLERS | CONTEXTUAL_FILLERS


def count_filler_words(text: str) -> dict:
    """
    Count filler words in transcript with context awareness.

    True fillers (um, uh) are always counted.
    Contextual fillers (like, so, well) are only counted when they
    appear to be used as verbal padding, not as meaningful words.

    Returns:
        dict with 'total', 'breakdown' (counter), 'positions'
    """
    text_lower = text.lower().strip()
    if not text_lower:
        return {'total': 0, 'breakdown': {}, 'positions': []}

    words = text_lower.split()
    filler_count = Counter()
    positions = []

    # Check multi-word fillers first
    for filler in MULTI_FILLERS:
        start = 0
        while True:
            idx = text_lower.find(filler, start)
            if idx == -1:
                break
            # Verify it's at a word boundary
            before_ok = (idx == 0 or not text_lower[idx - 1].isalpha())
            end_pos = idx + len(filler)
            after_ok = (end_pos >= len(text_lower)
                        or not text_lower[end_pos].isalpha())
            if before_ok and after_ok:
                filler_count[filler] += 1
                word_pos = len(text_lower[:idx].split()) - 1
                positions.append({
                    'filler': filler,
                    'position': max(0, word_pos)
                })
            start = idx + len(filler)

    # Check single-word fillers
    for i, word in enumerate(words):
        clean = re.sub(r'[^\w]', '', word)
        if not clean:
            continue

        # True fillers: always count
        if clean in TRUE_FILLERS:
            filler_count[clean] += 1
            positions.append({'filler': clean, 'position': i})
            continue

        # Contextual fillers: use heuristics
        if clean in CONTEXTUAL_FILLERS:
            is_filler = False

            # Heuristic 1: at the very start of the text
            if i == 0:
                is_filler = True

            # Heuristic 2: after another filler
            elif i > 0:
                prev_clean = re.sub(r'[^\w]', '', words[i - 1])
                if prev_clean in TRUE_FILLERS or prev_clean in CONTEXTUAL_FILLERS:
                    is_filler = True

            # Heuristic 3: "like" used as a filler (not "like this")
            # If "like" is followed by another filler or is repeated
            if clean == 'like' and not is_filler:
                if i + 1 < len(words):
                    next_clean = re.sub(r'[^\w]', '', words[i + 1])
                    if next_clean in TRUE_FILLERS:
                        is_filler = True
                # "like" at start after a pause word
                if i > 0:
                    prev_clean = re.sub(r'[^\w]', '', words[i - 1])
                    if prev_clean in ('and', 'but', 'or', 'then', 'so'):
                        is_filler = True

            if is_filler:
                filler_count[clean] += 1
                positions.append({'filler': clean, 'position': i})

    return {
        'total': sum(filler_count.values()),
        'breakdown': dict(filler_count),
        'positions': sorted(positions, key=lambda x: x['position']),
    }


def detect_repetitions(text: str, max_gap: int = 2) -> dict:
    """
    Detect consecutive or near-consecutive word repetitions.

    A key stuttering indicator is repeating the same word:
    "I I I want to" or "the the cat"

    Args:
        text: Transcript text
        max_gap: Maximum words between repetitions to count

    Returns:
        dict with 'total', 'repeated_words', 'positions'
    """
    words = text.lower().split()
    repetitions = []
    repeated_counter = Counter()

    # Skip very common words that naturally repeat in speech
    SKIP_WORDS = {'the', 'a', 'an', 'is', 'it', 'in', 'to', 'and',
                  'of', 'that', 'for', 'on', 'with', 'as', 'at',
                  'by', 'or', 'be', 'was', 'are', 'been', 'has',
                  'have', 'had', 'do', 'did', 'if', 'but', 'not',
                  'no', 'so', 'up', 'out', 'can', 'will'}

    for i in range(len(words)):
        clean_i = re.sub(r'[^\w]', '', words[i])
        if len(clean_i) < 2 or clean_i in SKIP_WORDS:
            continue

        # Only check immediate neighbors (gap 0 = adjacent)
        for gap in range(1, max_gap + 2):
            j = i + gap
            if j >= len(words):
                break
            clean_j = re.sub(r'[^\w]', '', words[j])
            if clean_i == clean_j and clean_i not in TRUE_FILLERS:
                repeated_counter[clean_i] += 1
                repetitions.append({
                    'word': clean_i,
                    'first_pos': i,
                    'second_pos': j,
                    'gap': gap - 1
                })
                break

    return {
        'total': sum(repeated_counter.values()),
        'repeated_words': dict(repeated_counter),
        'positions': repetitions,
    }


def calculate_speech_rate(text: str, duration_seconds: float,
                          exclude_pauses: float = 0,
                          word_timestamps: list = None) -> dict:
    """
    Calculate speech rate metrics accurately.

    Priority:
    1. If word timestamps available (from Vosk), use the actual voiced span
       (time from first word start to last word end) — most accurate.
    2. Else fall back to (duration - pause_time).

    Args:
        text: Transcript text
        duration_seconds: Total audio duration
        exclude_pauses: Total pause time (fallback only)
        word_timestamps: List of word dicts with 'start'/'end' keys from Vosk

    Returns:
        dict with 'wpm', 'word_count', 'speaking_time', 'classification'
    """
    words = text.split()
    word_count = len(words)

    # Use actual voiced duration from Vosk word timestamps when available
    if word_timestamps and len(word_timestamps) >= 2:
        first_start = word_timestamps[0].get('start', 0)
        last_end = word_timestamps[-1].get('end', duration_seconds)
        voiced_span = max(last_end - first_start, 1.0)
        # Actual speaking time = voiced span (words only, no silence between)
        speaking_time = voiced_span
    else:
        speaking_time = max(duration_seconds - exclude_pauses, 1.0)

    wpm = (word_count / speaking_time) * 60

    if wpm < 100:
        classification = "Slow"
        suggestion = ("Try to increase your pace slightly "
                      "for better engagement.")
    elif wpm < 130:
        classification = "Good"
        suggestion = "Your pace is comfortable for most listeners."
    elif wpm < 160:
        classification = "Moderate"
        suggestion = "Good conversational pace."
    elif wpm < 190:
        classification = "Fast"
        suggestion = "Consider slowing down for clarity."
    else:
        classification = "Very Fast"
        suggestion = "Slow down — listeners may struggle to follow."

    return {
        'wpm': round(wpm, 1),
        'word_count': word_count,
        'speaking_time': round(speaking_time, 1),
        'total_duration': round(duration_seconds, 1),
        'classification': classification,
        'suggestion': suggestion,
    }



def compute_fluency_score(filler_data: dict, repetition_data: dict,
                          speech_rate: dict, pause_count: int,
                          speaking_ratio: float) -> dict:
    """
    Compute overall fluency score (0-100).
    Higher score = more fluent speech.
    """
    score = 100.0

    # Penalty for filler words (max -30)
    word_count = max(speech_rate.get('word_count', 1), 1)
    filler_ratio = filler_data['total'] / word_count
    filler_penalty = min(filler_ratio * 200, 30)
    score -= filler_penalty

    # Penalty for repetitions (max -20)
    rep_ratio = repetition_data['total'] / word_count
    rep_penalty = min(rep_ratio * 150, 20)
    score -= rep_penalty

    # Penalty for too many pauses (max -20)
    duration_min = speech_rate.get('total_duration', 60) / 60
    pause_per_min = pause_count / max(duration_min, 0.5)
    pause_penalty = min(pause_per_min * 3, 20)
    score -= pause_penalty

    # Penalty for extremes in speech rate (max -15)
    wpm = speech_rate.get('wpm', 130)
    if wpm < 80 or wpm > 200:
        score -= 15
    elif wpm < 100 or wpm > 180:
        score -= 8
    elif wpm < 110 or wpm > 160:
        score -= 3

    # Bonus for good speaking ratio (max +5)
    if speaking_ratio > 80:
        score += 5
    elif speaking_ratio > 60:
        score += 2

    score = max(0, min(100, score))

    if score >= 85:
        grade = "Excellent"
    elif score >= 70:
        grade = "Good"
    elif score >= 55:
        grade = "Fair"
    elif score >= 40:
        grade = "Needs Improvement"
    else:
        grade = "Practice More"

    return {
        'score': round(score, 1),
        'grade': grade,
        'breakdown': {
            'filler_penalty': round(filler_penalty, 1),
            'repetition_penalty': round(rep_penalty, 1),
            'pause_penalty': round(pause_penalty, 1),
        }
    }


def analyze_transcript(text: str, duration_seconds: float,
                       pause_count: int = 0, total_pause_time: float = 0,
                       speaking_ratio: float = 80,
                       word_timestamps: list = None) -> dict:
    """Run full NLP analysis on transcript."""
    if not text or not text.strip():
        return {
            'filler_words': {'total': 0, 'breakdown': {}, 'positions': []},
            'repetitions': {
                'total': 0, 'repeated_words': {}, 'positions': []},
            'speech_rate': {
                'wpm': 0, 'word_count': 0, 'speaking_time': 0,
                'total_duration': duration_seconds,
                'classification': 'N/A',
                'suggestion': 'No speech detected.'},
            'fluency_score': {'score': 0, 'grade': 'N/A', 'breakdown': {}},
            'word_count': 0,
        }

    filler_data = count_filler_words(text)
    rep_data = detect_repetitions(text)
    rate_data = calculate_speech_rate(
        text, duration_seconds, total_pause_time,
        word_timestamps=word_timestamps)
    fluency = compute_fluency_score(
        filler_data, rep_data, rate_data, pause_count, speaking_ratio)

    return {
        'filler_words': filler_data,
        'repetitions': rep_data,
        'speech_rate': rate_data,
        'fluency_score': fluency,
        'word_count': rate_data['word_count'],
    }



def highlight_transcript(text: str, filler_data: dict,
                         rep_data: dict) -> str:
    """
    Generate HTML-highlighted transcript.
    Filler words in yellow, repetitions in orange.
    """
    words = text.split()
    filler_positions = {p['position'] for p in
                        filler_data.get('positions', [])}
    rep_positions = set()
    for r in rep_data.get('positions', []):
        rep_positions.add(r['first_pos'])
        rep_positions.add(r['second_pos'])

    highlighted = []
    for i, word in enumerate(words):
        if i in filler_positions:
            highlighted.append(
                f'<span class="filler-word">{word}</span>')
        elif i in rep_positions:
            highlighted.append(
                f'<span class="repetition">{word}</span>')
        else:
            highlighted.append(word)

    return ' '.join(highlighted)
