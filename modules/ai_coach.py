"""Offline AI Coach module for NeuroNudge.

Supports two backends:
- Ollama (local, offline): used automatically when running locally
- Groq API (cloud, free): used when GROQ_API_KEY environment variable is set
  Get a free key at: https://console.groq.com
"""

import json
import os
import requests

OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3"
GROQ_API_URL  = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL    = "llama-3.1-8b-instant"   # Current free Groq model (fast)
GROQ_MODELS   = [                         # All available Groq free models
    "llama-3.1-8b-instant",
    "llama-3.3-70b-versatile",
    "gemma2-9b-it",
    "mixtral-8x7b-32768",
]


def _get_groq_key() -> str:
    """Return Groq API key from env var or Streamlit secrets."""
    key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        try:
            import streamlit as st
            key = st.secrets.get("GROQ_API_KEY", "")
        except Exception:
            pass
    return key


def _llm_generate(prompt: str, temperature: float = 0.7,
                  max_tokens: int = 1200,
                  model: str = None) -> str:
    """
    Route LLM request to Groq (cloud) or Ollama (local) automatically.
    Raises Exception on failure.
    """
    groq_key = _get_groq_key()

    if groq_key:
        # ── Groq API (cloud) ──────────────────────────────────────
        groq_model = model if model in GROQ_MODELS else GROQ_MODEL
        resp = requests.post(
            GROQ_API_URL,
            headers={
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": groq_model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_completion_tokens": max_tokens,
            },
            timeout=30
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    else:
        # ── Ollama (local) ────────────────────────────────────────
        resp = requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={
                "model": DEFAULT_MODEL,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": temperature,
                            "top_p": 0.9,
                            "num_predict": max_tokens},
            },
            timeout=90
        )
        resp.raise_for_status()
        return resp.json().get("response", "")


def check_ollama_status() -> dict:
    """
    Check if Groq API key is set (cloud mode) or Ollama is running (local mode).
    """
    groq_key = _get_groq_key()
    if groq_key:
        return {
            'running': True,
            'models': GROQ_MODELS,
            'message': f'Groq API active ({GROQ_MODEL} — cloud mode)',
            'backend': 'groq'
        }

    try:
        response = requests.get(f"{OLLAMA_URL}/api/tags", timeout=3)
        if response.status_code == 200:
            data = response.json()
            models = [m['name'] for m in data.get('models', [])]
            return {
                'running': True,
                'models': models,
                'message': f"Ollama running — {', '.join(models) if models else 'No models'}",
                'backend': 'ollama'
            }
    except Exception:
        pass

    return {
        'running': False,
        'models': [],
        'message': (
            "AI Coach unavailable.\n\n"
            "Option A (local): Install Ollama → ollama pull llama3\n"
            "Option B (cloud): Set GROQ_API_KEY at console.groq.com (free)"
        ),
        'backend': 'none'
    }


def generate_coaching(session_data: dict, model: str = None,
                      session_history: list = None,
                      username: str = None) -> dict:
    """
    Generate deeply personalized coaching feedback using local LLM.

    Args:
        session_data: dict with metrics from the current session
        model: Ollama model name
        session_history: list of past sessions for this user (DB rows)
        username: user's name for personalization

    Returns:
        dict with 'coaching', 'success', 'error'
    """
    model = model or DEFAULT_MODEL
    name = username or "there"

    # ── Build session history context ──
    history_lines = []
    score_trend = []
    wpm_trend = []
    filler_trend = []

    if session_history and len(session_history) >= 2:
        recent = session_history[-5:]  # up to last 5 sessions
        for i, s in enumerate(recent, 1):
            score = s.get('fluency_score', 0)
            wpm = s.get('wpm', 0)
            fillers = s.get('filler_count', 0)
            pauses = s.get('pause_count', 0)
            ts = s.get('timestamp', '')[:10]
            score_trend.append(score)
            wpm_trend.append(wpm)
            filler_trend.append(fillers)
            history_lines.append(
                f"  Session {i} ({ts}): Score={score:.0f}/100, "
                f"WPM={wpm:.0f}, Fillers={fillers}, Pauses={pauses}"
            )

        # Compute trends
        if len(score_trend) >= 2:
            score_dir = score_trend[-1] - score_trend[-2]
            score_trend_str = (
                f"improving (+{score_dir:.1f} pts)" if score_dir > 2
                else f"declining ({score_dir:.1f} pts)" if score_dir < -2
                else "stable"
            )
            filler_dir = filler_trend[-1] - filler_trend[-2]
            filler_trend_str = (
                "getting better (fewer fillers)" if filler_dir < 0
                else "getting worse (more fillers)" if filler_dir > 0
                else "consistent"
            )
        else:
            score_trend_str = "first comparison"
            filler_trend_str = "first comparison"

        history_context = (
            f"PAST SESSION HISTORY (most recent last):\n"
            + "\n".join(history_lines)
            + f"\n\nTREND: Fluency score is {score_trend_str}. "
            + f"Filler word usage is {filler_trend_str}."
        )
    else:
        history_context = "PAST SESSION HISTORY: This is their first session."

    # ── Identify main problem areas for this session ──
    current_score = session_data.get('fluency_score', 0)
    current_wpm = session_data.get('wpm', 0)
    fillers = session_data.get('filler_count', 0)
    pauses = session_data.get('pause_count', 0)
    stutter_events = session_data.get('stutter_events', 0)
    word_count = session_data.get('word_count', 1)
    filler_rate = round(fillers / max(word_count, 1) * 100, 1)

    problems = []
    if filler_rate > 10:
        problems.append(f"high filler word rate ({filler_rate}% of words)")
    if pauses > 5:
        problems.append(f"many prolonged pauses ({pauses})")
    if current_wpm < 90:
        problems.append(f"slow speech rate ({current_wpm:.0f} WPM)")
    elif current_wpm > 180:
        problems.append(f"very fast speech ({current_wpm:.0f} WPM)")
    if stutter_events > 3:
        problems.append(f"frequent stuttering ({stutter_events} events)")

    main_problems = (
        ", ".join(problems) if problems
        else "no major issues — great session!"
    )

    prompt = f"""You are NeuroNudge, a warm and expert speech fluency coach.
You are giving personalized feedback to {name} after their practice session.

{history_context}

CURRENT SESSION METRICS:
- Duration: {session_data.get('duration', 0):.0f} seconds
- Words spoken: {word_count}
- Speech rate: {current_wpm:.0f} words per minute
- Filler words: {fillers} ({filler_rate}% of speech)
- Prolonged pauses: {pauses}
- Stutter events detected: {stutter_events}
- Fluency score: {current_score:.0f}/100

TRANSCRIPT SAMPLE:
{session_data.get('transcript', 'Not available.')[:500]}

PRIMARY CONCERNS: {main_problems}

Generate a **professional speech therapy coaching report** in EXACTLY this format:

---
## Session Coaching Report

### 1. Executive Summary
(2-3 sentences: overall performance, fluency score interpretation, most significant finding)

### 2. Quantitative Analysis
- **Fluency Score ({current_score:.0f}/100):** [clinical interpretation]
- **Speech Rate ({current_wpm:.0f} WPM):** [interpretation, normal is 120-180 WPM]
- **Filler Words ({fillers}, {filler_rate}%):** [clinical significance, acceptable is under 5%]
- **Pauses ({pauses}):** [interpretation]
- **Stutter Events ({stutter_events}):** [severity: mild/moderate/severe]

### 3. Progress Assessment
(Compare numerically to previous sessions. Is performance improving, stable, or declining?)

### 4. Primary Intervention Area
(Identify the most critical issue. Explain WHY it is problematic clinically and which evidence-based technique addresses it: Easy Onset, Light Articulatory Contact, Prolonged Speech, or Diaphragmatic Breathing.)

### 5. Targeted Exercise Protocol
- **Exercise Name:**
- **Duration:** X minutes
- **Step-by-step Instructions:** (3-4 steps)
- **Expected Outcome:** What improvement after 1 week

### 6. Therapist Note
(Personal and warm 1-2 sentences addressing {name} directly.)
---

Use clinical but accessible language. Be specific to THEIR numbers. Under 350 words."""

    try:
        text = _llm_generate(prompt, temperature=0.7, max_tokens=1200)
        return {
            'coaching': text,
            'success': True,
            'error': None,
            'model_used': GROQ_MODEL if _get_groq_key() else DEFAULT_MODEL,
        }
    except requests.ConnectionError:
        return {'coaching': '', 'success': False,
                'error': 'Cannot connect to Ollama. Make sure it is running.'}
    except Exception as e:
        return {'coaching': '', 'success': False,
                'error': f'Error: {str(e)}'}



def generate_practice_plan(session_history: list, model: str = None,
                           current_session: dict = None,
                           username: str = None) -> dict:
    """
    Generate a unique, session-specific 5-day practice plan.
    Every plan is different — targets the current session's primary weakness.
    """
    model = model or DEFAULT_MODEL
    name = username or "you"
    cs = current_session or {}

    # Identify the primary weakness this session
    wpm = cs.get('wpm', 130)
    fillers = cs.get('filler_count', 0)
    pauses = cs.get('pause_count', 0)
    stutter_events = cs.get('stutter_events', 0)
    score = cs.get('fluency_score', 50)
    word_count = max(cs.get('word_count', 1), 1)
    filler_rate = fillers / word_count * 100

    weakness_scores = {
        'speech_rate': abs(wpm - 150) / 150,
        'filler_words': min(filler_rate / 10, 1.0),
        'pauses': min(pauses / 10, 1.0),
        'stuttering': min(stutter_events / 10, 1.0),
    }
    primary_weakness = max(weakness_scores, key=weakness_scores.get)
    weakness_label = {
        'speech_rate': f"speech rate of {wpm:.0f} WPM ({'too fast' if wpm > 160 else 'too slow'})",
        'filler_words': f"{fillers} filler words ({filler_rate:.1f}% of speech)",
        'pauses': f"{pauses} prolonged pauses detected",
        'stuttering': f"{stutter_events} stutter events",
    }[primary_weakness]

    history_lines = []
    for i, s in enumerate(session_history[-4:], 1):
        history_lines.append(
            f"Session {i}: Score={s.get('fluency_score', 0):.0f}, "
            f"WPM={s.get('wpm', 0):.0f}, Fillers={s.get('filler_count', 0)}, "
            f"Pauses={s.get('pause_count', 0)}"
        )
    history_text = "\n".join(history_lines) if history_lines else "First session."

    session_num = len(session_history) + 1
    themes = [
        "breathing and pacing control",
        "slow deliberate reading aloud",
        "casual conversation simulation",
        "phone/presentation scenario practice",
        "poetry and rhythmic speech",
        "tongue twisters and articulation drills",
        "self-recording and review",
    ]
    theme = themes[session_num % len(themes)]

    prompt = f"""You are NeuroNudge AI, a speech therapy assistant.
Generate a UNIQUE 5-day progressive practice plan for {name} (Session #{session_num}).

THIS SESSION'S PRIMARY WEAKNESS: {weakness_label}
Fluency Score: {score:.0f}/100

PAST SESSIONS:
{history_text}

THEME FOR THIS PLAN: {theme}

Rules:
- Each day MUST be different (do not repeat Day 1's exercise)
- Days must get progressively harder
- Every exercise must directly target "{primary_weakness.replace('_', ' ')}"
- Use the theme creatively

Format exactly:

## 5-Day Practice Plan — Session #{session_num}
**Target:** {primary_weakness.replace('_', ' ').title()} | **Theme:** {theme.title()}

**Day 1 — Foundation (10 min)**
[Exercise with exact step-by-step instructions]

**Day 2 — Building (12 min)**
[Harder variation]

**Day 3 — Application (15 min)**
[Real-world simulated context]

**Day 4 — Challenge (15 min)**
[Challenging version]

**Day 5 — Integration (20 min)**
[Full practice + self-recording and review]

**Key Rule This Week:** [One rule for {name} all week]
**Success Check:** [How to measure improvement by Day 5]

Be specific and practical. 3-4 sentences per day."""

    try:
        text = _llm_generate(prompt, temperature=0.85, max_tokens=900)
        return {
            'plan': text, 'success': True, 'error': None,
            'weakness': primary_weakness, 'session_num': session_num,
        }
    except Exception as e:
        return {'plan': '', 'success': False, 'error': str(e)}


def generate_fallback_coaching(session_data: dict) -> str:
    """
    Generate basic coaching feedback WITHOUT Ollama (rule-based fallback).
    Used when Ollama is not available.
    """
    feedback = []
    score = session_data.get('fluency_score', 0)
    wpm = session_data.get('wpm', 0)
    fillers = session_data.get('filler_count', 0)
    pauses = session_data.get('pause_count', 0)

    # Overall
    if score >= 80:
        feedback.append("🌟 **Great session!** Your fluency score is excellent.")
    elif score >= 60:
        feedback.append("👍 **Good effort!** You're making solid progress.")
    elif score >= 40:
        feedback.append("💪 **Keep practicing!** There's room for improvement, and that's okay.")
    else:
        feedback.append("🌱 **Every session counts!** Let's focus on small improvements.")

    # Speech rate
    if wpm > 0:
        if wpm < 100:
            feedback.append(f"📊 **Speech Rate:** {wpm} WPM — a bit slow. Try reading aloud to build pace.")
        elif wpm <= 160:
            feedback.append(f"📊 **Speech Rate:** {wpm} WPM — comfortable pace. Well done!")
        else:
            feedback.append(f"📊 **Speech Rate:** {wpm} WPM — quite fast. Practice pausing between sentences.")

    # Fillers
    if fillers == 0:
        feedback.append("✅ **Filler words:** None detected! Excellent control.")
    elif fillers <= 3:
        feedback.append(f"⚠️ **Filler words:** {fillers} detected. Good, but try replacing them with brief pauses.")
    else:
        feedback.append(f"🔸 **Filler words:** {fillers} detected. Practice pausing silently instead of saying 'um' or 'uh'.")

    # Pauses
    if pauses <= 2:
        feedback.append("✅ **Pauses:** Natural flow with minimal interruptions.")
    elif pauses <= 5:
        feedback.append(f"⚠️ **Pauses:** {pauses} prolonged pauses. Try reading familiar passages to build confidence.")
    else:
        feedback.append(f"🔸 **Pauses:** {pauses} prolonged pauses. Practice with the metronome to maintain rhythm.")

    # Exercise
    feedback.append("\n**🎯 Quick Exercise:** Read a paragraph from a book aloud for 2 minutes, "
                    "focusing on steady breathing and replacing fillers with short, intentional pauses.")

    return "\n\n".join(feedback)
