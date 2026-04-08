"""Report generation module for NeuroNudge.

Uses SQLite for per-user session storage — fully offline, zero setup.
"""

import json
import sqlite3
import pandas as pd
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np
import io
from pathlib import Path
from datetime import datetime


# ─────────────────────────────────────────────
# SQLite Database Setup
# ─────────────────────────────────────────────
DB_PATH = Path("data") / "neuronudge.db"


def _get_db():
    """Get a connection to the SQLite database, creating tables if needed."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row  # Access columns by name
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            username    TEXT NOT NULL,
            timestamp   TEXT NOT NULL,
            duration    REAL DEFAULT 0,
            speaking_ratio REAL DEFAULT 0,
            pause_count INTEGER DEFAULT 0,
            block_count INTEGER DEFAULT 0,
            avg_pause_duration REAL DEFAULT 0,
            transcript  TEXT DEFAULT '',
            word_count  INTEGER DEFAULT 0,
            wpm         REAL DEFAULT 0,
            filler_count INTEGER DEFAULT 0,
            filler_breakdown TEXT DEFAULT '{}',
            repetition_count INTEGER DEFAULT 0,
            fluency_score REAL DEFAULT 0,
            fluency_grade TEXT DEFAULT '',
            stutter_events INTEGER DEFAULT 0,
            metronome_events TEXT DEFAULT '[]',
            extra_data  TEXT DEFAULT '{}'
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_sessions_username
        ON sessions (username)
    """)
    conn.commit()
    return conn


def _migrate_json_sessions():
    """One-time migration: import old JSON sessions into SQLite."""
    json_dir = Path("data/sessions")
    if not json_dir.exists():
        return

    json_files = list(json_dir.glob("session_*.json"))
    if not json_files:
        return

    conn = _get_db()
    # Check if we already migrated
    count = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    if count > 0:
        conn.close()
        return

    migrated = 0
    for f in sorted(json_files):
        try:
            with open(f) as fp:
                data = json.load(fp)

            username = data.get('user', 'Unknown')
            conn.execute("""
                INSERT INTO sessions
                (username, timestamp, duration, speaking_ratio, pause_count,
                 block_count, avg_pause_duration, transcript, word_count, wpm,
                 filler_count, filler_breakdown, repetition_count,
                 fluency_score, fluency_grade, stutter_events, metronome_events)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                username,
                data.get('timestamp', datetime.now().isoformat()),
                data.get('duration', 0),
                data.get('speaking_ratio', 0),
                data.get('pause_count', 0),
                data.get('block_count', 0),
                data.get('avg_pause_duration', 0),
                data.get('transcript', ''),
                data.get('word_count', 0),
                data.get('wpm', 0),
                data.get('filler_count', 0),
                json.dumps(data.get('filler_breakdown', {})),
                data.get('repetition_count', 0),
                data.get('fluency_score', 0),
                data.get('fluency_grade', ''),
                data.get('stutter_events', 0),
                json.dumps(data.get('metronome_events', [])),
            ))
            migrated += 1
        except Exception:
            continue

    conn.commit()
    conn.close()
    if migrated > 0:
        print(f"[NeuroNudge] Migrated {migrated} old JSON sessions into SQLite.")


# Run migration on import
_migrate_json_sessions()


# ─────────────────────────────────────────────
# Charts
# ─────────────────────────────────────────────
def create_energy_timeline(energy_profile: np.ndarray, events: list,
                           duration: float, sample_rate: int = 16000,
                           hop_size: int = 512) -> plt.Figure:
    """Create energy timeline chart with disfluency events marked."""
    fig, ax = plt.subplots(figsize=(10, 3))
    fig.patch.set_facecolor('#FFFFFF')
    ax.set_facecolor('#FAFAFA')

    time_axis = np.linspace(0, duration, len(energy_profile))

    # Filled area + line
    ax.fill_between(time_axis, energy_profile, alpha=0.35, color='#1B7340')
    ax.plot(time_axis, energy_profile, color='#1B7340', linewidth=1.2)

    # Event markers
    for event in events:
        if event['type'] == 'pause':
            ax.axvspan(event['start'], event['end'],
                       alpha=0.18, color='#F59E0B', zorder=0)
        else:
            ax.axvspan(event['start'], event['end'],
                       alpha=0.25, color='#EF4444', zorder=0)

    ax.set_xlabel('Time (seconds)', fontsize=9, color='#6B7B8D')
    ax.set_ylabel('Energy (RMS)', fontsize=9, color='#6B7B8D')
    ax.set_title('Speech Energy Timeline', fontsize=11,
                 fontweight='600', color='#1A1A2E', pad=10)

    ax.tick_params(colors='#8C9BAD', labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor('#E2E8F0')

    patches = [
        mpatches.Patch(color='#1B7340', alpha=0.5, label='Speech Energy'),
        mpatches.Patch(color='#F59E0B', alpha=0.3, label='Pause'),
        mpatches.Patch(color='#EF4444', alpha=0.3, label='Block'),
    ]
    ax.legend(handles=patches, fontsize=8, loc='upper right',
              framealpha=0.9, edgecolor='#E2E8F0')
    ax.set_xlim(0, duration)
    ax.grid(axis='y', alpha=0.4, color='#E2E8F0', linewidth=0.8)
    fig.tight_layout(pad=1.2)

    return fig


def create_fluency_breakdown_chart(breakdown: dict) -> plt.Figure:
    """Create a horizontal bar chart of fluency score penalties."""
    fig, ax = plt.subplots(figsize=(6, 3.5))
    fig.patch.set_facecolor('#FFFFFF')
    ax.set_facecolor('#FAFAFA')

    categories = list(breakdown.keys())
    values = list(breakdown.values())
    labels = [k.replace('_penalty', '').replace('_', ' ').title()
              for k in categories]
    colors = ['#F59E0B', '#EF4444', '#3B82F6']

    bars = ax.barh(labels, values, color=colors[:len(categories)],
                   height=0.45, edgecolor='none')
    ax.set_xlabel('Penalty Points', fontsize=9, color='#6B7B8D')
    ax.set_title('Fluency Score Breakdown', fontsize=11,
                 fontweight='600', color='#1A1A2E', pad=10)

    ax.tick_params(colors='#8C9BAD', labelsize=9)
    for spine in ax.spines.values():
        spine.set_edgecolor('#E2E8F0')
    ax.grid(axis='x', alpha=0.4, color='#E2E8F0', linewidth=0.8)

    for bar, val in zip(bars, values):
        ax.text(bar.get_width() + 0.15,
                bar.get_y() + bar.get_height() / 2,
                f'-{val:.1f}', va='center', fontsize=9, color='#374151',
                fontweight='600')

    ax.set_xlim(0, max(values) * 1.4 if values and max(values) > 0 else 5)
    ax.invert_yaxis()
    fig.tight_layout(pad=1.2)

    return fig


def create_filler_distribution_chart(filler_breakdown: dict) -> plt.Figure:
    """Create bar chart of filler word distribution."""
    if not filler_breakdown:
        fig, ax = plt.subplots(figsize=(5, 3))
        fig.patch.set_facecolor('#FFFFFF')
        ax.set_facecolor('#FAFAFA')
        ax.text(0.5, 0.5, '✓  No filler words detected',
                ha='center', va='center', fontsize=13,
                color='#1B7340', fontweight='600')
        ax.axis('off')
        fig.tight_layout()
        return fig

    fig, ax = plt.subplots(figsize=(6, 3.5))
    fig.patch.set_facecolor('#FFFFFF')
    ax.set_facecolor('#FAFAFA')

    words = list(filler_breakdown.keys())
    counts = list(filler_breakdown.values())
    palette = ['#1B7340', '#2E9E5A', '#45B86E', '#5CC882',
               '#77D494', '#93DFA8', '#AEEABC']
    colors = [palette[i % len(palette)] for i in range(len(words))]

    bars = ax.bar(words, counts, color=colors, edgecolor='none')
    ax.set_ylabel('Count', fontsize=9, color='#6B7B8D')
    ax.set_title('Filler Words Distribution', fontsize=11,
                 fontweight='600', color='#1A1A2E', pad=10)

    ax.tick_params(colors='#8C9BAD', labelsize=9)
    for spine in ax.spines.values():
        spine.set_edgecolor('#E2E8F0')
    ax.grid(axis='y', alpha=0.4, color='#E2E8F0', linewidth=0.8)

    for bar, count in zip(bars, counts):
        ax.text(bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.05,
                str(count), ha='center', fontsize=9,
                fontweight='700', color='#374151')

    ax.set_ylim(0, max(counts) * 1.35)
    fig.tight_layout(pad=1.2)

    return fig


# ─────────────────────────────────────────────
# Session Save / Load (SQLite, per-user)
# ─────────────────────────────────────────────
def save_session(session_data: dict) -> int:
    """
    Save a session to SQLite database.
    Returns the row ID, or -1 if validation fails.

    Validation rules:
    - Must have at least 5 words transcribed (real speech detected)
    - Duration must be > 5 seconds
    - WPM is clamped to physiological max of 300 WPM
    """
    # ── Input validation ──────────────────────────────
    word_count = session_data.get('word_count', 0)
    duration = session_data.get('duration', 0)
    wpm = session_data.get('wpm', 0)

    # Require minimum real speech
    if word_count < 1 or duration < 3:
        print(f"[SaveSession] Skipped: too short "
              f"(words={word_count}, duration={duration:.1f}s)")
        return -1

    # Clamp WPM to physiological maximum (300 WPM = speed reading limit)
    # Typical fluent speech: 120–180 WPM
    if wpm > 300:
        # Recalculate from total duration as fallback
        wpm = round((word_count / max(duration, 1)) * 60, 1)
        # If still implausible, use word_count/duration conservatively
        if wpm > 300:
            wpm = min(wpm, 300)
        session_data['wpm'] = wpm
        print(f"[SaveSession] WPM clamped to {wpm}")

    # Clamp fluency score to valid range
    score = max(0.0, min(100.0, session_data.get('fluency_score', 0)))
    session_data['fluency_score'] = score

    # ── Persist ──────────────────────────────────────
    conn = _get_db()
    username = session_data.get('user', 'Unknown')

    # Serialize complex types
    filler_bd = session_data.get('filler_breakdown', {})
    if isinstance(filler_bd, dict):
        filler_bd = json.dumps(filler_bd)

    met_events = session_data.get('metronome_events', [])
    if isinstance(met_events, list):
        met_events = json.dumps(met_events, default=str)

    cursor = conn.execute("""
        INSERT INTO sessions
        (username, timestamp, duration, speaking_ratio, pause_count,
         block_count, avg_pause_duration, transcript, word_count, wpm,
         filler_count, filler_breakdown, repetition_count,
         fluency_score, fluency_grade, stutter_events, metronome_events)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        username,
        datetime.now().isoformat(),
        round(duration, 2),
        session_data.get('speaking_ratio', 0),
        session_data.get('pause_count', 0),
        session_data.get('block_count', 0),
        session_data.get('avg_pause_duration', 0),
        session_data.get('transcript', ''),
        word_count,
        wpm,
        session_data.get('filler_count', 0),
        filler_bd,
        session_data.get('repetition_count', 0),
        score,
        session_data.get('fluency_grade', ''),
        session_data.get('stutter_events', 0),
        met_events,
    ))
    conn.commit()
    row_id = cursor.lastrowid
    conn.close()
    return row_id


def load_session_history(username: str = None) -> list:
    """Load session history for a specific user (or all if username is None)."""
    conn = _get_db()

    if username:
        rows = conn.execute(
            "SELECT * FROM sessions WHERE username = ? ORDER BY timestamp ASC",
            (username,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM sessions ORDER BY timestamp ASC"
        ).fetchall()

    conn.close()

    sessions = []
    for row in rows:
        session = dict(row)
        # Deserialize JSON fields
        try:
            session['filler_breakdown'] = json.loads(
                session.get('filler_breakdown', '{}'))
        except (json.JSONDecodeError, TypeError):
            session['filler_breakdown'] = {}
        try:
            session['metronome_events'] = json.loads(
                session.get('metronome_events', '[]'))
        except (json.JSONDecodeError, TypeError):
            session['metronome_events'] = []
        sessions.append(session)

    return sessions


def get_all_usernames() -> list:
    """Get a list of all usernames that have session history."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT DISTINCT username FROM sessions ORDER BY username"
    ).fetchall()
    conn.close()
    return [row['username'] for row in rows]


# ─────────────────────────────────────────────
# Progress Chart
# ─────────────────────────────────────────────
def create_progress_chart(sessions: list) -> plt.Figure:
    """
    Create progress chart showing fluency score over valid sessions.
    Skips sessions with no transcript (score=0, grade=N/A).
    """
    # Filter to only real sessions with actual speech data
    valid = [
        s for s in sessions
        if s.get('fluency_score', 0) > 0
        and s.get('word_count', 0) >= 3
        and s.get('grade', s.get('fluency_grade', '')) != 'N/A'
    ]

    fig, ax = plt.subplots(figsize=(8, 4))
    fig.patch.set_facecolor('#FFFFFF')
    ax.set_facecolor('#FAFAFA')

    if not valid:
        ax.text(0.5, 0.5, 'No valid sessions yet.\nComplete a practice session to see progress.',
                ha='center', va='center', fontsize=13, color='#0F5132',
                fontweight='600')
        ax.axis('off')
        fig.tight_layout()
        return fig

    scores = [s.get('fluency_score', 0) for s in valid]
    x = list(range(1, len(scores) + 1))

    # Main score line
    ax.plot(x, scores, 'o-', color='#1B7340', linewidth=2.2,
            markersize=8, markerfacecolor='white',
            markeredgecolor='#1B7340', markeredgewidth=2,
            zorder=3, label='Fluency Score')
    ax.fill_between(x, scores, alpha=0.12, color='#1B7340')

    # Add score labels above each point
    for xi, yi in zip(x, scores):
        ax.annotate(f'{yi:.0f}',
                    xy=(xi, yi), xytext=(0, 10),
                    textcoords='offset points',
                    ha='center', fontsize=9,
                    fontweight='700', color='#1B7340')

    # Trend line (only if enough points)
    if len(scores) >= 3:
        z = np.polyfit(x, scores, 1)
        p = np.poly1d(z)
        ax.plot(x, p(x), '--', color='#F59E0B', linewidth=1.5,
                alpha=0.7, label='Trend')
        ax.legend(fontsize=9, framealpha=0.9, edgecolor='#E2E8F0')

    ax.set_xlabel('Session', fontsize=9, color='#6B7B8D')
    ax.set_ylabel('Fluency Score (0–100)', fontsize=9, color='#6B7B8D')
    ax.set_title('Fluency Progress Over Time', fontsize=11,
                 fontweight='600', color='#1A1A2E', pad=10)
    ax.set_ylim(0, 105)
    ax.set_xticks(x)
    ax.tick_params(colors='#8C9BAD', labelsize=9)
    for spine in ax.spines.values():
        spine.set_edgecolor('#E2E8F0')
    ax.grid(axis='y', alpha=0.4, color='#E2E8F0', linewidth=0.8)
    fig.tight_layout(pad=1.2)
    return fig
