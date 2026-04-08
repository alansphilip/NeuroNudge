"""
NeuroNudge — Offline Assistive Speech Feedback & AI Coach System

Main Streamlit Application
"""

import streamlit as st
import numpy as np
from datetime import datetime

# Module imports
from styles import get_custom_css
from modules.audio_utils import audio_bytes_to_numpy, get_duration, numpy_to_wav_bytes, resample_audio
from modules.disfluency_detector import compute_fluency_profile
from modules.metronome import generate_metronome_track, get_recommended_bpm
from modules.vosk_asr import check_vosk_model, transcribe_audio
from modules.nlp_analytics import analyze_transcript, highlight_transcript
from modules.ai_coach import (
    check_ollama_status, generate_coaching,
    generate_fallback_coaching, generate_practice_plan
)
from modules.report_generator import (
    create_energy_timeline, create_fluency_breakdown_chart,
    create_filler_distribution_chart, save_session,
    load_session_history, create_progress_chart
)

# ─────────────────────────────────────────────
# Page Config
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="NeuroNudge",
    page_icon="N",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(get_custom_css(), unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Helper: Custom Metric Card
# ─────────────────────────────────────────────
def nn_metric(label, value, accent="green", sub="", anim=0):
    """Render a custom metric card with left accent bar and optional animation."""
    anim_class = f' nn-metric-animated-{anim}' if anim else ''
    st.markdown(f"""
    <div class="nn-metric{anim_class}">
        <div class="metric-accent accent-{accent}"></div>
        <p class="metric-label">{label}</p>
        <p class="metric-value">{value}</p>
        {'<p class="metric-sub">' + sub + '</p>' if sub else ''}
    </div>
    """, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# Speech Tips
# ─────────────────────────────────────────────
SPEECH_TIPS = [
    {
        "title": "The Power of Pausing",
        "tip": "Replace filler words like 'um' and 'uh' with a short, intentional pause. "
               "Silence feels longer to you than to your audience — and it makes you sound confident.",
    },
    {
        "title": "Breathe From Your Diaphragm",
        "tip": "Before speaking, take a slow deep breath from your belly, not your chest. "
               "Diaphragmatic breathing reduces anxiety and gives your voice more power and stability.",
    },
    {
        "title": "Slow Down to Speed Up",
        "tip": "Reducing your speaking pace by just 10% makes you sound more confident and authoritative. "
               "Listeners actually perceive slower speakers as more knowledgeable.",
    },
    {
        "title": "Record Yourself Daily",
        "tip": "Just 60 seconds of daily recording and playback is the fastest way to improve. "
               "You'll notice patterns you never realized — consistency beats long sessions every time.",
    },
    {
        "title": "Warm Up Your Voice",
        "tip": "Before an important speech, hum gently for 30 seconds, then say 'mee-may-mah-moh-moo' slowly. "
               "This relaxes your vocal cords and prevents your voice from cracking.",
    },
    {
        "title": "Focus on One Thing at a Time",
        "tip": "Don't try to fix everything in one session. Pick ONE area — maybe reducing fillers, "
               "or speaking slower — and focus solely on that. Small wins build lasting habits.",
    },
    {
        "title": "Use the Metronome Trick",
        "tip": "Speaking to a steady beat trains your natural rhythm and pacing. "
               "Start at 70 BPM and practice matching one syllable per beat — it transforms your flow.",
    },
    {
        "title": "Eye Contact Builds Confidence",
        "tip": "Even when practicing alone, look at a fixed point as if it's a person. "
               "This trains your brain to stay composed under the 'pressure' of being watched.",
    },
    {
        "title": "End Strong, Start Strong",
        "tip": "The first and last 10 seconds of any speech are what people remember most. "
               "Practice your opening and closing lines until they're second nature.",
    },
    {
        "title": "Drink Water, Not Coffee",
        "tip": "Caffeine tightens your vocal cords and dries your throat. Before speaking, "
               "drink room-temperature water — it keeps your voice smooth and clear.",
    },
    {
        "title": "Smile While Speaking",
        "tip": "A slight smile changes your vocal tone — listeners can literally 'hear' a smile. "
               "It makes you sound warmer, friendlier, and more approachable.",
    },
    {
        "title": "Practice With Tongue Twisters",
        "tip": "Say 'She sells seashells by the seashore' five times fast before a session. "
               "Tongue twisters improve articulation and warm up your speech muscles.",
    },
]


def _get_tip_index():
    if 'tip_index' not in st.session_state:
        seed = int(datetime.now().timestamp())
        st.session_state.tip_index = seed % len(SPEECH_TIPS)
    return st.session_state.tip_index


# ─────────────────────────────────────────────
# Session State
# ─────────────────────────────────────────────
defaults = {
    'logged_in': False,
    'username': '',
    'current_page': 'Dashboard',
    'audio_data': None,
    'audio_numpy': None,
    'sample_rate': 16000,
    'fluency_profile': None,
    'transcript_result': None,
    'nlp_result': None,
    'coaching_result': None,
    'session_analyzed': False,
}
for key, val in defaults.items():
    if key not in st.session_state:
        st.session_state[key] = val


# ─────────────────────────────────────────────
# Animated SVG Logo — Microphone with Sound Arcs
# ─────────────────────────────────────────────
LOGO_SVG_LARGE = """
<svg width="72" height="72" viewBox="0 0 72 72" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="36" cy="36" r="34" fill="#0F5132" fill-opacity="0.08" stroke="#0F5132" stroke-opacity="0.12" stroke-width="1.5"/>
  <!-- Microphone body -->
  <rect x="30" y="18" width="12" height="22" rx="6" fill="#0F5132"/>
  <!-- Mic stand arc -->
  <path d="M24 36 C24 44 29 48 36 48 C43 48 48 44 48 36" stroke="#0F5132" stroke-width="2.5" stroke-linecap="round" fill="none"/>
  <!-- Mic stand line -->
  <line x1="36" y1="48" x2="36" y2="54" stroke="#0F5132" stroke-width="2.5" stroke-linecap="round"/>
  <line x1="30" y1="54" x2="42" y2="54" stroke="#0F5132" stroke-width="2.5" stroke-linecap="round"/>
  <!-- Sound arcs (animated) -->
  <path d="M52 26 C55 30 55 38 52 42" stroke="#1A6B4F" stroke-width="2" stroke-linecap="round" fill="none" opacity="0.6">
    <animate attributeName="opacity" values="0.2;0.7;0.2" dur="1.5s" repeatCount="indefinite"/>
  </path>
  <path d="M57 22 C62 28 62 40 57 46" stroke="#1A6B4F" stroke-width="1.8" stroke-linecap="round" fill="none" opacity="0.4">
    <animate attributeName="opacity" values="0.1;0.5;0.1" dur="1.8s" repeatCount="indefinite"/>
  </path>
  <path d="M20 26 C17 30 17 38 20 42" stroke="#1A6B4F" stroke-width="2" stroke-linecap="round" fill="none" opacity="0.6">
    <animate attributeName="opacity" values="0.2;0.7;0.2" dur="1.5s" begin="0.3s" repeatCount="indefinite"/>
  </path>
  <path d="M15 22 C10 28 10 40 15 46" stroke="#1A6B4F" stroke-width="1.8" stroke-linecap="round" fill="none" opacity="0.4">
    <animate attributeName="opacity" values="0.1;0.5;0.1" dur="1.8s" begin="0.3s" repeatCount="indefinite"/>
  </path>
</svg>
"""

LOGO_SVG_SMALL = """
<svg width="36" height="36" viewBox="0 0 72 72" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="36" cy="36" r="34" fill="rgba(255,255,255,0.08)" stroke="rgba(255,255,255,0.15)" stroke-width="1.5"/>
  <rect x="30" y="18" width="12" height="22" rx="6" fill="#A7D7C5"/>
  <path d="M24 36 C24 44 29 48 36 48 C43 48 48 44 48 36" stroke="#A7D7C5" stroke-width="2.5" stroke-linecap="round" fill="none"/>
  <line x1="36" y1="48" x2="36" y2="54" stroke="#A7D7C5" stroke-width="2.5" stroke-linecap="round"/>
  <line x1="30" y1="54" x2="42" y2="54" stroke="#A7D7C5" stroke-width="2.5" stroke-linecap="round"/>
  <path d="M52 26 C55 30 55 38 52 42" stroke="#7BC4A8" stroke-width="2" stroke-linecap="round" fill="none">
    <animate attributeName="opacity" values="0.3;0.8;0.3" dur="1.5s" repeatCount="indefinite"/>
  </path>
  <path d="M20 26 C17 30 17 38 20 42" stroke="#7BC4A8" stroke-width="2" stroke-linecap="round" fill="none">
    <animate attributeName="opacity" values="0.3;0.8;0.3" dur="1.5s" begin="0.3s" repeatCount="indefinite"/>
  </path>
</svg>
"""

LOGO_SVG_RECORDING = """
<svg width="48" height="48" viewBox="0 0 72 72" fill="none" xmlns="http://www.w3.org/2000/svg">
  <circle cx="36" cy="36" r="34" fill="#FEE2E2" stroke="#FCA5A5" stroke-width="1.5"/>
  <rect x="30" y="18" width="12" height="22" rx="6" fill="#DC2626"/>
  <path d="M24 36 C24 44 29 48 36 48 C43 48 48 44 48 36" stroke="#DC2626" stroke-width="2.5" stroke-linecap="round" fill="none"/>
  <line x1="36" y1="48" x2="36" y2="54" stroke="#DC2626" stroke-width="2.5" stroke-linecap="round"/>
  <line x1="30" y1="54" x2="42" y2="54" stroke="#DC2626" stroke-width="2.5" stroke-linecap="round"/>
  <path d="M52 26 C55 30 55 38 52 42" stroke="#EF4444" stroke-width="2" stroke-linecap="round" fill="none">
    <animate attributeName="opacity" values="0.3;1;0.3" dur="0.8s" repeatCount="indefinite"/>
  </path>
  <path d="M57 22 C62 28 62 40 57 46" stroke="#EF4444" stroke-width="1.8" stroke-linecap="round" fill="none">
    <animate attributeName="opacity" values="0.1;0.7;0.1" dur="1s" repeatCount="indefinite"/>
  </path>
  <path d="M20 26 C17 30 17 38 20 42" stroke="#EF4444" stroke-width="2" stroke-linecap="round" fill="none">
    <animate attributeName="opacity" values="0.3;1;0.3" dur="0.8s" begin="0.2s" repeatCount="indefinite"/>
  </path>
  <path d="M15 22 C10 28 10 40 15 46" stroke="#EF4444" stroke-width="1.8" stroke-linecap="round" fill="none">
    <animate attributeName="opacity" values="0.1;0.7;0.1" dur="1s" begin="0.2s" repeatCount="indefinite"/>
  </path>
</svg>
"""


# ─────────────────────────────────────────────
# LOGIN PAGE
# ─────────────────────────────────────────────
def page_login():
    st.markdown("""
    <style>
        section[data-testid="stSidebar"] { display: none; }
        .block-container { max-width: 460px; margin: auto; padding-top: 6vh; }
        .stApp {
            background: linear-gradient(
                180deg,
                #E8F5EC 0%,
                #EFF6F0 15%,
                #F3F7F4 30%,
                #F7F8FA 60%
            ) !important;
        }
    </style>
    """, unsafe_allow_html=True)

    # Animated SVG logo — separate call to avoid f-string HTML issues
    st.markdown(
        '<div style="text-align:center;">'
        '<div style="display:inline-block; animation: breathe 3s ease-in-out infinite;">'
        + LOGO_SVG_LARGE +
        '</div></div>',
        unsafe_allow_html=True
    )

    # Brand text
    st.markdown("""
    <div style="text-align:center; margin-bottom: 8px;">
        <h1 style="color:#0F5132 !important; margin:10px 0 0 0; font-size:34px;
                   font-weight:800; font-family:'Outfit',sans-serif;
                   letter-spacing:-0.5px;">
            NeuroNudge
        </h1>
        <p style="color:#6B7B8D; font-size:11px; letter-spacing:2.5px;
                  margin-top:6px; font-weight:600; text-transform:uppercase;">
            Offline Speech Feedback &amp; AI Coach
        </p>
    </div>
    """, unsafe_allow_html=True)

    # Sound wave bars
    st.markdown("""
    <div class="wave-container">
        <div class="wave-bar" style="animation-duration:1.2s; animation-delay:0s;"></div>
        <div class="wave-bar" style="animation-duration:0.9s; animation-delay:0.15s;"></div>
        <div class="wave-bar" style="animation-duration:1.4s; animation-delay:0.05s;"></div>
        <div class="wave-bar" style="animation-duration:0.8s; animation-delay:0.2s;"></div>
        <div class="wave-bar" style="animation-duration:1.1s; animation-delay:0.1s;"></div>
        <div class="wave-bar" style="animation-duration:1.3s; animation-delay:0.25s;"></div>
        <div class="wave-bar" style="animation-duration:0.7s; animation-delay:0.08s;"></div>
    </div>
    """, unsafe_allow_html=True)

    # Login card
    st.markdown("""
    <div class="login-card">
        <p style="font-size:18px; font-weight:700; color:#1A1A2E;
                  font-family:'Outfit',sans-serif; margin:0 0 4px 0;
                  text-align:center;">Welcome</p>
        <p style="color:#8C9BAD; font-size:13px; text-align:center;
                  margin-bottom:16px;">
            Enter your name to start your practice session</p>
    </div>
    """, unsafe_allow_html=True)

    with st.form("login_form"):
        username = st.text_input("Your Name", placeholder="Enter your name",
                                 max_chars=30, label_visibility="collapsed")
        submitted = st.form_submit_button("Get Started",
                                          use_container_width=True)
        if submitted:
            if username.strip():
                st.session_state.logged_in = True
                st.session_state.username = username.strip()
                st.rerun()
            else:
                st.error("Please enter your name to continue.")

    st.markdown("""
    <div style="text-align:center; margin-top:36px;">
        <p style="color:#A0B0B8; font-size:11px; letter-spacing:0.3px;">
            All data stays on your device · No internet required</p>
    </div>
    """, unsafe_allow_html=True)


if not st.session_state.logged_in:
    page_login()
    st.stop()


# ─────────────────────────────────────────────
# Sidebar
# ─────────────────────────────────────────────
with st.sidebar:
    # SVG logo — separate call to avoid f-string issues
    st.markdown(
        '<div style="text-align:center; padding: 16px 0 4px 0;">'
        '<div style="display:inline-block;">'
        + LOGO_SVG_SMALL +
        '</div></div>',
        unsafe_allow_html=True
    )
    st.markdown("""
    <div style="text-align:center; margin-bottom: 4px;">
        <h2 style="color: #D4E7DC; margin: 4px 0 0 0; font-size: 20px;
                   font-family:'Outfit',sans-serif;">NeuroNudge</h2>
        <p style="color: rgba(255,255,255,0.4); font-size: 10px; margin: 2px 0 0 0;
                  letter-spacing: 1.5px;">SPEECH COACH</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    st.markdown(f"""
    <div style="padding: 8px 12px; background: rgba(255,255,255,0.07);
                border-radius: 8px; margin-bottom: 14px;">
        <p style="color:rgba(255,255,255,0.45); font-size:11px; margin:0;">Logged in as</p>
        <p style="color:#E8F0EB; font-size:14px; font-weight:600; margin:2px 0 0 0;">
            {st.session_state.username}</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""<p style='color:rgba(255,255,255,0.35); font-size:10px;
                letter-spacing:2px; margin-bottom:6px;'>NAVIGATE</p>""",
                unsafe_allow_html=True)

    pages = {
        "Dashboard": "Dashboard",
        "Practice Session": "Practice",
        "Session Report": "Report",
        "AI Coach": "Coach",
        "History": "History",
    }
    for label, page_key in pages.items():
        if st.button(label, key=f"nav_{page_key}", use_container_width=True):
            st.session_state.current_page = page_key

    st.markdown("---")
    st.markdown(
        "<p style='color:rgba(255,255,255,0.25); font-size:10px; text-align:center;'>"
        "v1.0 · All data stays on your device</p>",
        unsafe_allow_html=True
    )
    if st.button("Sign Out", key="logout", use_container_width=True):
        for key in list(st.session_state.keys()):
            del st.session_state[key]
        st.rerun()


# ─────────────────────────────────────────────
# PAGE: Dashboard
# ─────────────────────────────────────────────
def page_dashboard():
    hour = datetime.now().hour
    if hour < 12:
        greeting = "Good Morning"
    elif hour < 17:
        greeting = "Good Afternoon"
    else:
        greeting = "Good Evening"

    st.markdown(f"""
    <div class="hero">
        <p class="hero-label">NEURONUDGE</p>
        <h2>{greeting}, {st.session_state.username}!</h2>
        <p>Practice your speech, detect disfluencies, and get personalized AI coaching —
        all offline, all private, all on your device.</p>
    </div>
    """, unsafe_allow_html=True)

    history = load_session_history(st.session_state.username)

    # Custom metric cards — staggered scale-in animation
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        nn_metric("Total Sessions", len(history), "green", anim=1)
    with c2:
        if history:
            avg_score = np.mean([s.get('fluency_score', 0) for s in history])
            nn_metric("Avg Fluency", f"{avg_score:.0f}/100", "blue", anim=2)
        else:
            nn_metric("Avg Fluency", "—", "blue", anim=2)
    with c3:
        if history:
            latest = history[-1].get('fluency_score', 0)
            nn_metric("Latest Score", f"{latest:.0f}/100", "teal", anim=3)
        else:
            nn_metric("Latest Score", "—", "teal", anim=3)
    with c4:
        nn_metric("Privacy", "100%", "amber", sub="Fully offline", anim=4)

    st.markdown('<div class="nn-divider"></div>', unsafe_allow_html=True)

    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.markdown('<div class="section-header"><h3 style="margin:0;">How It Works</h3></div>',
                    unsafe_allow_html=True)

        steps = [
            ("1", "Record Your Speech",
             "Use the built-in recorder or upload a WAV file. Speak freely or read a passage."),
            ("2", "Get Instant Analysis",
             "Detect pauses, filler words, repetitions, and speech blocks automatically."),
            ("3", "AI-Powered Coaching",
             "Get personalized feedback and practice plans from a local AI, fully offline."),
            ("4", "Track Your Progress",
             "View session history, fluency trends, and measure your improvement over time."),
        ]
        for num, title, desc in steps:
            st.markdown(f"""
            <div class="step-card anim-{num}">
                <div class="step-num">{num}</div>
                <div class="step-content">
                    <h4>{title}</h4>
                    <p>{desc}</p>
                </div>
            </div>
            """, unsafe_allow_html=True)

    with col_right:
        tip_data = SPEECH_TIPS[_get_tip_index()]
        st.markdown(f"""
        <div class="tip-card anim-2">
            <p class="tip-label">SPEECH TIP OF THE DAY</p>
            <p class="tip-title">{tip_data['title']}</p>
            <p class="tip-body">{tip_data['tip']}</p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("")

        st.markdown("""
        <div class="card anim-3" style="text-align:center;">
            <div class="card-header">Quick Start</div>
            <p style="color:#6B7B8D; font-size:13px; margin:6px 0 14px 0;">
                Ready to practice? Jump straight into a session.</p>
        </div>
        """, unsafe_allow_html=True)
        if st.button("Start Practice Session", key="quick_start",
                     type="primary", use_container_width=True):
            st.session_state.current_page = "Practice"
            st.rerun()

        if history and len(history) >= 2:
            scores = [s.get('fluency_score', 0) for s in history]
            change = scores[-1] - scores[-2]
            if change > 0:
                arrow = "+"
                clr = "#059669"
            elif change < 0:
                arrow = ""
                clr = "#DC2626"
            else:
                arrow = ""
                clr = "#6B7B8D"
            st.markdown(f"""
            <div class="card anim-4">
                <div class="card-header">Last Session vs Previous</div>
                <p style="font-size:28px; font-weight:700; color:{clr};
                          margin:8px 0 4px 0; font-family:'Outfit',sans-serif;">
                    {arrow}{change:.0f} points
                </p>
                <p style="color:#8C9BAD; font-size:12px;">
                    {scores[-2]:.0f} → {scores[-1]:.0f} fluency score</p>
            </div>
            """, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# PAGE: Practice Session
# ─────────────────────────────────────────────
def page_practice():
    from modules.live_session import LivePacingSession, check_microphone

    st.markdown("""
    <div class="hero">
        <p class="hero-label">PRACTICE SESSION</p>
        <h2>Record &amp; Analyze Your Speech</h2>
        <p>The metronome auto-activates when stuttering is detected to help you regain rhythm.</p>
    </div>
    """, unsafe_allow_html=True)

    if 'live_session' not in st.session_state:
        st.session_state.live_session = None
    if 'live_session_result' not in st.session_state:
        st.session_state.live_session_result = None

    tab_live, tab_upload = st.tabs(["Live Session (with auto-pacing)",
                                    "Upload WAV File"])

    with tab_live:
        st.markdown("""
        <div class="card" style="border-left: 4px solid #0F5132;">
            <div class="card-header">How Smart Pacing Works</div>
            <p style="color:#6B7B8D; line-height:1.7; font-size:13px; margin-top:8px;">
                <b>Step 1:</b> Press Start and begin speaking naturally.<br>
                <b>Step 2:</b> The system listens for ~5 seconds to learn your voice level.<br>
                <b>Step 3:</b> Once calibrated, it monitors your speech energy in real-time.<br>
                <b>Step 4:</b> When energy drops (stutter/block), the metronome auto-starts.<br>
                <b>Step 5:</b> When your speech recovers, the metronome auto-stops.
            </p>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("### Session Settings")
        col_s1, col_s2, col_s3 = st.columns(3)

        with col_s1:
            bpm = st.slider("Metronome BPM", 40, 120, 72, 2, key="live_bpm",
                             help="Speed of metronome clicks when triggered")
            if bpm <= 60:
                st.caption("Very Slow — deep breathing pace")
            elif bpm <= 80:
                st.caption("Recommended — stuttering practice")
            elif bpm <= 100:
                st.caption("Natural — everyday speech")
            else:
                st.caption("Fast — advanced drills")

        with col_s2:
            sensitivity = st.select_slider(
                "Detection Sensitivity",
                options=["Low", "Medium", "High"],
                value="Medium", key="sensitivity",
                help="How sensitive the stuttering detection is"
            )

        with col_s3:
            auto_metronome = st.toggle("Auto-metronome", value=True,
                                        key="auto_met_toggle",
                                        help="Turn OFF to disable automatic metronome")
            if auto_metronome:
                st.caption("Metronome will auto-play on stutter")
            else:
                st.caption("Metronome disabled — record only")

        # ── Auto-detect: native sounddevice (local) vs cloud ──────────
        from modules.browser_session import (
            is_native_audio_available, show_browser_live_session)
        _native = is_native_audio_available()

        if not _native:
            # ── Cloud / browser mode ───────────────────────────────────
            _b_audio = show_browser_live_session(
                bpm=bpm, sensitivity=sensitivity, auto_metronome=auto_metronome)
            if _b_audio is not None:
                _raw = _b_audio.getvalue() if hasattr(_b_audio, 'getvalue') \
                       else bytes(_b_audio)
                st.session_state.audio_data = _raw
                st.session_state.live_session_result = None
                st.session_state.session_analyzed = False
                with st.spinner("Analysing your speech..."):
                    _run_analysis()
            if st.session_state.get('session_analyzed'):
                st.success(
                    "✅ Analysis complete! Go to **Session Report** for results.")

        else:
            # ── Native / local mode (existing code — zero changes) ─────
            mic_status = check_microphone()
            session_running = (st.session_state.live_session is not None
                               and st.session_state.live_session.is_running)

            if not session_running:
                col_start, col_info = st.columns([2, 3])
                with col_start:
                    if mic_status['available']:
                        if st.button("Start Live Session", key="start_live",
                                     type="primary", use_container_width=True):
                            session = LivePacingSession(
                                sample_rate=16000, bpm=bpm,
                                sensitivity=sensitivity)
                            session.metronome_enabled = auto_metronome
                            session.start()
                            st.session_state.live_session = session
                            st.session_state.live_session_result = None
                            st.rerun()
                    else:
                        st.error(mic_status['message'])

                with col_info:
                    dev_name = mic_status.get('device_name', 'Default Microphone')
                    st.markdown(f"""
                    <div style="background:#F0F7F3; border-radius:10px;
                                padding:12px 16px;">
                        <p style="font-size:12px; color:#0F5132; margin:0;">
                            Microphone: {dev_name}<br>
                            <span style="color:#6B7B8D;">Press Start → speak for
                            2–3 sec (calibration) → metronome auto-triggers on
                            stutters → press Stop when done</span>
                        </p>
                    </div>
                    """, unsafe_allow_html=True)

                if st.session_state.live_session_result:
                    result = st.session_state.live_session_result
                    st.markdown('<div class="nn-divider"></div>',
                                unsafe_allow_html=True)
                    st.markdown("### Session Complete")

                    if st.session_state.audio_data:
                        st.audio(st.session_state.audio_data, format="audio/wav")

                    rc1, rc2, rc3, rc4 = st.columns(4)
                    with rc1:
                        nn_metric("Duration", f"{result['duration']}s", "green")
                    with rc2:
                        nn_metric("Stutter Events", result['stutter_count'],
                                  "rose")
                    with rc3:
                        met_starts = [e for e in result['events']
                                      if e['type'] == 'metronome_start']
                        nn_metric("Metronome Triggered", len(met_starts), "amber")
                    with rc4:
                        if result['energy_history']:
                            avg_e = np.mean(result['energy_history'])
                            nn_metric("Avg Energy", f"{avg_e:.5f}", "blue")

                    cal = result.get('calibration', {})
                    if cal.get('calibrated'):
                        st.markdown(f"""
                        <div style="background:#F0F7F3; border-radius:10px;
                                    padding:10px 14px; margin:8px 0;
                                    border-left:3px solid #0F5132;">
                            <p style="font-size:11px; color:#0F5132; margin:0;">
                                <b>Auto-calibrated:</b>
                                Speech peak = {cal.get('speech_peak', 0):.5f} |
                                Stutter threshold =
                                {cal.get('energy_threshold', 0):.5f} |
                                Recovery threshold =
                                {cal.get('recovery_threshold', 0):.5f} |
                                Ambient = {cal.get('ambient_energy', 0):.5f}
                            </p>
                        </div>
                        """, unsafe_allow_html=True)
                    else:
                        st.warning("Session ended before calibration. "
                                   "Speak for at least 3 seconds next time.")

                    if result['events']:
                        with st.expander("Session Event Log"):
                            for evt in result['events']:
                                etype = evt.get('type', '')
                                if etype == 'speech_detected':
                                    st.markdown(
                                        f"Speech detected at `{evt['time']}s`")
                                elif etype == 'calibrated':
                                    st.markdown(
                                        f"Calibrated at `{evt['time']}s` — "
                                        f"threshold: `{evt.get('threshold')}`, "
                                        f"recovery: `{evt.get('recovery')}`")
                                elif etype == 'metronome_start':
                                    reason = evt.get('reason', '')
                                    if reason == 'repetition_stutter':
                                        st.markdown(
                                            f"🔄 Metronome ON at "
                                            f"`{evt['time']}s` "
                                            f"(repetition: "
                                            f"'{evt.get('word', '?')}' "
                                            f"x{evt.get('count', '?')})")
                                    elif reason == 'syllable_stutter':
                                        st.markdown(
                                            f"🔁 Metronome ON at "
                                            f"`{evt['time']}s` "
                                            f"(syllable stutter detected)")
                                    else:
                                        st.markdown(
                                            f"⏸️ Metronome ON at "
                                            f"`{evt['time']}s` "
                                            f"(energy drop, "
                                            f"energy: "
                                            f"`{evt.get('energy', 'N/A')}`)")
                                elif etype == 'metronome_stop':
                                    st.markdown(
                                        f"✅ Metronome OFF at `{evt['time']}s`"
                                        f" ({evt.get('reason', 'recovered')})")

                    st.markdown('<div class="nn-divider"></div>',
                                unsafe_allow_html=True)

                    if st.button("Run Full Analysis on This Recording",
                                 key="analyze_live", type="primary"):
                        with st.spinner("Analyzing your speech..."):
                            _run_analysis_from_live(result)

                    if st.session_state.session_analyzed:
                        st.success("Analysis complete! Go to Session Report "
                                   "for results.")

            else:
                session = st.session_state.live_session
                status = session.get_status()

                if not status.get('user_has_spoken'):
                    phase_msg = "Listening... Start speaking now"
                    phase_color = "#2563EB"
                elif not status.get('calibrated'):
                    phase_msg = "Calibrating... Keep speaking naturally"
                    phase_color = "#D97706"
                else:
                    phase_msg = "Monitoring — metronome will trigger on stuttering"
                    phase_color = "#059669"

                st.markdown(
                    '<div style="text-align:center; padding:24px 24px 0;'
                    ' background:#FFF5F5; border-radius:14px 14px 0 0;'
                    ' border:2px solid #FCA5A5; border-bottom:none;">'
                    '<div style="display:inline-block;">'
                    + LOGO_SVG_RECORDING +
                    '</div></div>',
                    unsafe_allow_html=True
                )
                st.markdown(f"""
                <div style="text-align:center; padding:0 24px 24px;
                            background: #FFF5F5;
                            border-radius:0 0 14px 14px;
                            border:2px solid #FCA5A5; border-top:none;
                            margin-bottom:16px;">
                    <p style="color:#991B1B; font-size:18px; font-weight:700;
                       margin:8px 0; font-family:'Outfit',sans-serif;">
                        Recording in progress</p>
                    <p style="color:{phase_color}; font-size:13px;
                       font-weight:600;">{phase_msg}</p>
                </div>
                """, unsafe_allow_html=True)

                sc1, sc2, sc3, sc4 = st.columns(4)
                with sc1:
                    nn_metric("Time", f"{status['elapsed_seconds']}s", "green")
                with sc2:
                    nn_metric("Energy",
                              f"{status['current_energy']:.5f}", "blue")
                with sc3:
                    nn_metric("Stutters", status['stutter_count'], "rose")
                with sc4:
                    if status['metronome_playing']:
                        nn_metric("Metronome", "Active", "green",
                                  sub="Playing")
                    else:
                        nn_metric("Metronome", "Idle", "amber", sub="Standby")

                if st.button("Stop Session", key="stop_live",
                             type="primary", use_container_width=True):
                    result = session.stop()
                    st.session_state.live_session_result = result
                    st.session_state.live_session = None
                    st.session_state.audio_data = numpy_to_wav_bytes(
                        result['audio'], 16000)
                    st.rerun()

    with tab_upload:
        st.markdown("### Upload a Recording")

        st.info("Upload a previously recorded WAV file for analysis.")

        uploaded_file = st.file_uploader("Upload a WAV file", type=['wav'],
                                          key="wav_upload")
        if uploaded_file is not None:
            audio_source = uploaded_file.getvalue()
            st.session_state.audio_data = audio_source
            st.session_state.live_session_result = None
            st.session_state.session_analyzed = False
            st.audio(audio_source, format="audio/wav")

            st.markdown("<div style='margin-top:14px;'></div>",
                        unsafe_allow_html=True)

            # Speed toggle
            speed_col, btn_col = st.columns([1, 2])
            with speed_col:
                fast_mode = st.toggle(
                    "⚡ Fast Mode",
                    value=True,
                    help="Fast: small Vosk model (~3s). Accurate: large model (~25s). "
                         "Fast works great for clear recordings."
                )
            model_path = (
                "models/vosk-model-small-en-us-0.15" if fast_mode
                else "models/vosk-model-en-us-0.22"
            )
            with btn_col:
                mode_label = "⚡ Fast" if fast_mode else "🎯 Accurate"
                if st.button(f"🔍 Analyse Recording ({mode_label})",
                             key="run_analysis_upload",
                             type="primary", use_container_width=True):
                    with st.spinner(
                        "Analysing — Fast mode (~5s)..." if fast_mode
                        else "Analysing — Accurate mode (~25s)..."
                    ):
                        _run_analysis(model_path=model_path)

        if st.session_state.get('session_analyzed'):
            st.success("✅ Analysis complete! Go to **Session Report** for results.")


# ─────────────────────────────────────────────
# Analysis Pipelines
# ─────────────────────────────────────────────
def _run_analysis_from_live(live_result):
    """Run analysis pipeline using audio from a live session."""
    progress = st.progress(0, text="Processing live recording...")

    if 'audio_float' in live_result and live_result['audio_float'] is not None:
        audio_float = live_result['audio_float']
    else:
        audio_int16 = live_result['audio']
        audio_float = audio_int16.astype(np.float32) / 32767.0
    sr = live_result['sample_rate']

    st.session_state.audio_numpy = audio_float
    st.session_state.sample_rate = sr
    progress.progress(15, text="Detecting disfluencies...")

    profile = compute_fluency_profile(audio_float, sr)
    st.session_state.fluency_profile = profile
    progress.progress(35, text="Transcribing speech...")

    vosk_result = transcribe_audio(audio_float, sr)
    st.session_state.transcript_result = vosk_result
    progress.progress(65, text="Running NLP analytics...")

    transcript_text = vosk_result.get('text', '') if vosk_result['success'] else ''
    word_timestamps = vosk_result.get('words', []) if vosk_result['success'] else []
    nlp = analyze_transcript(
        text=transcript_text,
        duration_seconds=profile['total_duration'],
        pause_count=profile['pause_count'],
        total_pause_time=profile['total_pause_time'],
        speaking_ratio=profile['speaking_ratio'],
        word_timestamps=word_timestamps,
    )
    st.session_state.nlp_result = nlp
    progress.progress(85, text="Saving session...")

    session_data = {
        'user': st.session_state.username,
        'duration': profile['total_duration'],
        'speaking_ratio': profile['speaking_ratio'],
        'pause_count': profile['pause_count'],
        'block_count': profile['block_count'],
        'avg_pause_duration': profile['avg_pause_duration'],
        'transcript': transcript_text,
        'word_count': nlp['speech_rate']['word_count'],
        'wpm': nlp['speech_rate']['wpm'],
        'filler_count': nlp['filler_words']['total'],
        'filler_breakdown': nlp['filler_words']['breakdown'],
        'repetition_count': nlp['repetitions']['total'],
        'fluency_score': nlp['fluency_score']['score'],
        'fluency_grade': nlp['fluency_score']['grade'],
        'stutter_events': live_result.get('stutter_count', 0),
        'metronome_events': live_result.get('events', []),
    }
    save_session(session_data)
    progress.progress(100, text="Done!")
    st.session_state.session_analyzed = True


def _run_analysis(model_path: str = None):
    """Run the complete analysis pipeline from uploaded WAV file."""
    VOSK_SR = 16000  # Vosk requires exactly 16kHz

    progress = st.progress(0, text="Loading audio...")

    audio_np, sr = audio_bytes_to_numpy(st.session_state.audio_data)

    # ── Resample to 16kHz if needed ──────────────────────────────
    if sr != VOSK_SR:
        progress.progress(8, text=f"Resampling from {sr}Hz → {VOSK_SR}Hz...")
        audio_np = resample_audio(audio_np, orig_sr=sr, target_sr=VOSK_SR)
        sr = VOSK_SR

    # ── Normalise to float32 ──────────────────────────────────────
    if audio_np.dtype != np.float32:
        audio_float = audio_np.astype(np.float32) / 32767.0
    else:
        audio_float = audio_np

    st.session_state.audio_numpy = audio_float
    st.session_state.sample_rate = sr
    progress.progress(15, text="Detecting disfluencies...")

    profile = compute_fluency_profile(audio_float, sr)
    st.session_state.fluency_profile = profile
    progress.progress(35, text="Transcribing speech...")

    vosk_result = transcribe_audio(audio_float, sr, model_path=model_path)
    st.session_state.transcript_result = vosk_result
    progress.progress(65, text="Running NLP analytics...")

    transcript_text = vosk_result.get('text', '') if vosk_result['success'] else ''
    word_timestamps = vosk_result.get('words', []) if vosk_result['success'] else []
    nlp = analyze_transcript(
        text=transcript_text,
        duration_seconds=profile['total_duration'],
        pause_count=profile['pause_count'],
        total_pause_time=profile['total_pause_time'],
        speaking_ratio=profile['speaking_ratio'],
        word_timestamps=word_timestamps,
    )
    st.session_state.nlp_result = nlp
    progress.progress(85, text="Saving session...")

    session_data = {
        'user': st.session_state.username,
        'duration': profile['total_duration'],
        'speaking_ratio': profile['speaking_ratio'],
        'pause_count': profile['pause_count'],
        'block_count': profile['block_count'],
        'avg_pause_duration': profile['avg_pause_duration'],
        'transcript': transcript_text,
        'word_count': nlp['speech_rate']['word_count'],
        'wpm': nlp['speech_rate']['wpm'],
        'filler_count': nlp['filler_words']['total'],
        'filler_breakdown': nlp['filler_words']['breakdown'],
        'repetition_count': nlp['repetitions']['total'],
        'fluency_score': nlp['fluency_score']['score'],
        'fluency_grade': nlp['fluency_score']['grade'],
    }
    save_session(session_data)
    progress.progress(100, text="Done!")
    st.session_state.session_analyzed = True


# ─────────────────────────────────────────────
# PAGE: Session Report
# ─────────────────────────────────────────────
def page_report():
    st.markdown("""
    <div class="hero">
        <p class="hero-label">SESSION REPORT</p>
        <h2>Your Speech Analysis Results</h2>
        <p>Detailed metrics, transcript with highlights, and fluency breakdown.</p>
    </div>
    """, unsafe_allow_html=True)

    if not st.session_state.session_analyzed:
        st.markdown("""
        <div class="card" style="text-align:center; padding:40px;">
            <p style="color:#6B7B8D; font-size:16px;">No session analyzed yet.<br>
            Go to <b>Practice Session</b> to record and analyze your speech.</p>
        </div>
        """, unsafe_allow_html=True)
        return

    profile = st.session_state.fluency_profile
    nlp = st.session_state.nlp_result
    transcript = st.session_state.transcript_result

    st.markdown("### Key Metrics")
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        nn_metric("Fluency Score",
                  f"{nlp['fluency_score']['score']:.0f}/100", "green",
                  sub=nlp['fluency_score']['grade'])
    with c2:
        nn_metric("Speech Rate",
                  f"{nlp['speech_rate']['wpm']:.0f} WPM", "blue",
                  sub=nlp['speech_rate']['classification'])
    with c3:
        nn_metric("Pauses", str(profile['pause_count']), "amber")
    with c4:
        nn_metric("Filler Words", str(nlp['filler_words']['total']), "rose")
    with c5:
        nn_metric("Repetitions", str(nlp['repetitions']['total']), "purple")

    c6, c7, c8, c9 = st.columns(4)
    with c6:
        nn_metric("Duration", f"{profile['total_duration']:.1f}s", "teal")
    with c7:
        nn_metric("Word Count", str(nlp['speech_rate']['word_count']), "blue")
    with c8:
        nn_metric("Speaking Ratio", f"{profile['speaking_ratio']:.0f}%", "green")
    with c9:
        nn_metric("Blocks", str(profile['block_count']), "rose")

    st.markdown('<div class="nn-divider"></div>', unsafe_allow_html=True)

    st.markdown("### Speech Energy Timeline")
    fig_energy = create_energy_timeline(
        profile['energy_profile'], profile['events'], profile['total_duration']
    )
    st.pyplot(fig_energy)

    st.markdown('<div class="nn-divider"></div>', unsafe_allow_html=True)

    col_left, col_right = st.columns([3, 2])

    with col_left:
        st.markdown("### Transcript")
        if transcript and transcript['success'] and transcript['text']:
            highlighted = highlight_transcript(
                transcript['text'], nlp['filler_words'], nlp['repetitions']
            )
            st.markdown(f"""
            <div class="card" style="line-height:1.8; font-size:15px;">
                {highlighted}
            </div>
            <p style="font-size:11px; color:#8C9BAD; margin-top:4px;">
                <span class="filler-word">Amber</span> = Filler words &nbsp;
                <span class="repetition">Red</span> = Repetitions
            </p>
            """, unsafe_allow_html=True)
        elif transcript and not transcript['success']:
            st.warning(f"Transcription issue: "
                       f"{transcript.get('error', 'Unknown error')}")
        else:
            st.info("No transcript available.")

    with col_right:
        st.markdown("### Score Breakdown")
        if nlp['fluency_score'].get('breakdown'):
            fig_break = create_fluency_breakdown_chart(
                nlp['fluency_score']['breakdown'])
            st.pyplot(fig_break)

        st.markdown("### Filler Words")
        fig_filler = create_filler_distribution_chart(
            nlp['filler_words']['breakdown'])
        st.pyplot(fig_filler)

    if profile['events']:
        st.markdown('<div class="nn-divider"></div>', unsafe_allow_html=True)
        st.markdown("### Detected Events")
        import pandas as pd
        events_df = pd.DataFrame(profile['events'])
        events_df.columns = ['Start (s)', 'End (s)', 'Duration (s)', 'Type']
        events_df['Type'] = events_df['Type'].map(
            {'pause': 'Pause', 'block': 'Block'})
        st.dataframe(events_df, width=862, hide_index=True)


# ─────────────────────────────────────────────
# PAGE: AI Coach
# ─────────────────────────────────────────────
def page_coach():
    st.markdown("""
    <div class="hero">
        <p class="hero-label">AI COACH</p>
        <h2>Personalized Speech Coaching</h2>
        <p>Get AI-powered feedback and practice plans — completely offline.</p>
    </div>
    """, unsafe_allow_html=True)

    if not st.session_state.session_analyzed:
        st.markdown("""
        <div class="card" style="text-align:center; padding:40px;">
            <p style="color:#6B7B8D; font-size:16px;">No session to coach on yet.<br>
            Go to <b>Practice Session</b> first.</p>
        </div>
        """, unsafe_allow_html=True)
        return

    nlp = st.session_state.nlp_result
    profile = st.session_state.fluency_profile
    transcript = st.session_state.transcript_result

    session_data = {
        'duration': profile['total_duration'],
        'word_count': nlp['speech_rate']['word_count'],
        'wpm': nlp['speech_rate']['wpm'],
        'filler_count': nlp['filler_words']['total'],
        'filler_breakdown': str(nlp['filler_words']['breakdown']),
        'pause_count': profile['pause_count'],
        'block_count': profile['block_count'],
        'speaking_ratio': profile['speaking_ratio'],
        'fluency_score': nlp['fluency_score']['score'],
        'repetitions': nlp.get('repetitions', {}).get('total', 0),
        'stutter_events': st.session_state.get(
            'live_stutter_count', profile.get('block_count', 0)),
        'transcript': transcript.get('text', '') if transcript and transcript[
            'success'] else '',
    }

    ollama = check_ollama_status()
    col1, col2 = st.columns([3, 2])

    with col1:
        st.markdown("### Coaching Feedback")

        if ollama['running']:
            model_choice = st.selectbox("Select LLM Model", ollama['models'],
                                         index=0 if ollama['models'] else 0)
            if st.button("Generate AI Coaching", type="primary",
                         key="gen_coach"):
                with st.spinner("AI Coach is analyzing your session and history..."):
                    history = load_session_history(st.session_state.username)
                    # Convert DB rows to dicts if needed
                    history_dicts = []
                    for row in history:
                        if isinstance(row, dict):
                            history_dicts.append(row)
                        else:
                            try:
                                history_dicts.append(dict(row))
                            except Exception:
                                pass
                    result = generate_coaching(
                        session_data,
                        model=model_choice,
                        session_history=history_dicts,
                        username=st.session_state.username,
                    )
                if result['success']:
                    st.session_state.coaching_result = result['coaching']
                else:
                    st.warning(f"LLM error: {result['error']}")
                    st.session_state.coaching_result = \
                        generate_fallback_coaching(session_data)
        else:
            st.info("Ollama is offline — using built-in coaching.")
            if st.button("Generate Coaching Analysis", type="primary",
                         key="gen_fallback"):
                st.session_state.coaching_result = \
                    generate_fallback_coaching(session_data)

        if st.session_state.coaching_result:
            st.markdown("""
            <div style="border:1px solid #e2e8f0; border-radius:14px;
                        padding:4px 20px 12px; background:#fff;
                        box-shadow:0 2px 8px rgba(0,0,0,0.06); margin-top:8px;">
            """, unsafe_allow_html=True)
            st.markdown(st.session_state.coaching_result)
            st.markdown("</div>", unsafe_allow_html=True)

    with col2:
        st.markdown("### Session Summary")
        st.markdown(f"""
        <div class="card">
            <div class="card-header">Quick Stats</div>
            <table style="width:100%; font-size:14px; line-height:2.2;">
                <tr><td>Fluency Score</td>
                    <td style="text-align:right;"><b>{nlp['fluency_score']['score']:.0f}/100</b></td></tr>
                <tr><td>Speech Rate</td>
                    <td style="text-align:right;"><b>{nlp['speech_rate']['wpm']:.0f} WPM</b></td></tr>
                <tr><td>Filler Words</td>
                    <td style="text-align:right;"><b>{nlp['filler_words']['total']}</b></td></tr>
                <tr><td>Pauses</td>
                    <td style="text-align:right;"><b>{profile['pause_count']}</b></td></tr>
                <tr><td>Duration</td>
                    <td style="text-align:right;"><b>{profile['total_duration']:.0f}s</b></td></tr>
            </table>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("### 📅 Your Next Practice Plan")
        if ollama['running']:
            if st.button("Generate My Practice Plan", key="gen_plan",
                         type="primary"):
                with st.spinner("Creating your personalised plan..."):
                    history = load_session_history(st.session_state.username)
                    history_dicts = []
                    for row in history:
                        try:
                            history_dicts.append(
                                dict(row) if not isinstance(row, dict) else row)
                        except Exception:
                            pass
                    plan_result = generate_practice_plan(
                        history_dicts,
                        current_session=session_data,
                        username=st.session_state.username,
                    )
                    if plan_result['success']:
                        st.session_state['practice_plan'] = plan_result['plan']
                        weakness = plan_result.get('weakness', '')
                        if weakness:
                            st.info(f"📌 Plan targets your weakest area: "
                                    f"**{weakness.replace('_', ' ').title()}**")
                    else:
                        st.warning(f"Plan error: {plan_result['error']}")

        if st.session_state.get('practice_plan'):
            st.markdown(st.session_state['practice_plan'])
        else:
            st.markdown("""
            <div class="card">
                <div class="card-header">Quick Exercise</div>
                <p style="line-height:1.7; color:#555;">Read a paragraph aloud for 2 minutes.
                Focus on <b>steady breathing</b> and replacing fillers
                with intentional, short pauses. Use the metronome at <b>70 BPM</b>.</p>
            </div>
            """, unsafe_allow_html=True)


# ─────────────────────────────────────────────
# PAGE: History
# ─────────────────────────────────────────────
def page_history():
    st.markdown("""
    <div class="hero">
        <p class="hero-label">SESSION HISTORY</p>
        <h2>Track Your Progress</h2>
        <p>Review past sessions and see your improvement over time.</p>
    </div>
    """, unsafe_allow_html=True)

    col_h, col_r = st.columns([5, 1])
    with col_h:
        st.markdown("### Fluency Progress")
    with col_r:
        if st.button("🔄 Refresh", key="refresh_history"):
            st.rerun()

    history = load_session_history(st.session_state.username)

    if not history:
        st.markdown("""
        <div class="card" style="text-align:center; padding:40px;">
            <p style="color:#6B7B8D; font-size:16px;">No sessions recorded yet.<br>
            Complete a practice session to start tracking progress.</p>
        </div>
        """, unsafe_allow_html=True)
        return

    st.markdown("### Fluency Progress")
    fig_progress = create_progress_chart(history)
    st.pyplot(fig_progress)

    st.markdown('<div class="nn-divider"></div>', unsafe_allow_html=True)

    st.markdown("### All Sessions")
    import pandas as pd

    table_data = []
    for i, s in enumerate(reversed(history), 1):
        table_data.append({
            '#': i,
            'Date': s.get('timestamp', 'N/A')[:16],
            'Score': f"{s.get('fluency_score', 0):.0f}/100",
            'Grade': s.get('fluency_grade', 'N/A'),
            'WPM': s.get('wpm', 0),
            'Fillers': s.get('filler_count', 0),
            'Pauses': s.get('pause_count', 0),
            'Duration': f"{s.get('duration', 0):.0f}s",
        })

    df = pd.DataFrame(table_data)
    st.dataframe(df, width=1028, hide_index=True)

    st.markdown('<div class="nn-divider"></div>', unsafe_allow_html=True)
    st.markdown("### Overall Statistics")
    sc1, sc2, sc3, sc4 = st.columns(4)
    scores = [s.get('fluency_score', 0) for s in history]

    with sc1:
        nn_metric("Best Score", f"{max(scores):.0f}/100", "green")
    with sc2:
        nn_metric("Average Score", f"{np.mean(scores):.0f}/100", "blue")
    with sc3:
        nn_metric("Total Sessions", len(history), "teal")
    with sc4:
        if len(scores) >= 2:
            improvement = scores[-1] - scores[0]
            nn_metric("Improvement", f"{improvement:+.0f} pts", "amber")
        else:
            nn_metric("Improvement", "—", "amber")


# ─────────────────────────────────────────────
# Router
# ─────────────────────────────────────────────
page_map = {
    "Dashboard": page_dashboard,
    "Practice": page_practice,
    "Report": page_report,
    "Coach": page_coach,
    "History": page_history,
}

current = st.session_state.current_page
if current in page_map:
    page_map[current]()
else:
    page_dashboard()
