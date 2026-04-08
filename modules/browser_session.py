"""
Browser-based live session for NeuroNudge cloud deployment.

Provides a JavaScript metronome (Web Audio API) + st.audio_input() recording
that works in any browser without requiring sounddevice hardware access.

Used automatically when sounddevice is not available (Streamlit Cloud).
Existing LivePacingSession is completely untouched.
"""

import streamlit as st
import streamlit.components.v1 as components


# ─────────────────────────────────────────────────────────────
# Environment Detection
# ─────────────────────────────────────────────────────────────
def is_native_audio_available() -> bool:
    """
    Check if sounddevice hardware is available (local) or not (cloud).
    Returns True  → use existing LivePacingSession (unchanged)
    Returns False → use browser-based session (this module)
    """
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        # Check there's at least one input device
        input_devs = [d for d in devices if d.get('max_input_channels', 0) > 0]
        return len(input_devs) > 0
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────
# JavaScript Metronome Widget
# ─────────────────────────────────────────────────────────────
def render_metronome_widget(bpm: int = 72, auto_start: bool = False) -> None:
    """
    Render a browser-native JavaScript metronome using Web Audio API.
    Plays real click sounds in the user's browser speakers.
    Works on Streamlit Cloud — no Python audio hardware needed.
    """
    auto_js = "startMetronome();" if auto_start else ""

    html = f"""
<!DOCTYPE html>
<html>
<head>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: 'Segoe UI', sans-serif;
    background: transparent;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 12px;
    padding: 12px;
  }}
  .metro-card {{
    background: linear-gradient(135deg, #0f5132 0%, #1a7a4a 100%);
    border-radius: 16px;
    padding: 18px 28px;
    text-align: center;
    color: white;
    width: 100%;
    max-width: 420px;
    box-shadow: 0 4px 20px rgba(15,81,50,0.3);
  }}
  .bpm-display {{
    font-size: 48px;
    font-weight: 800;
    letter-spacing: -2px;
    line-height: 1;
  }}
  .bpm-label {{ font-size: 13px; opacity: 0.75; margin-top: 2px; }}
  .pendulum-wrap {{
    width: 60px; height: 80px;
    margin: 12px auto 8px;
    position: relative;
    display: flex;
    justify-content: center;
  }}
  .pendulum {{
    width: 3px;
    height: 70px;
    background: rgba(255,255,255,0.9);
    transform-origin: top center;
    border-radius: 2px;
    position: relative;
    transition: none;
  }}
  .pendulum::after {{
    content: '';
    width: 14px; height: 14px;
    background: white;
    border-radius: 50%;
    position: absolute;
    bottom: -7px;
    left: -5.5px;
  }}
  .beat-indicator {{
    width: 18px; height: 18px;
    border-radius: 50%;
    background: rgba(255,255,255,0.25);
    display: inline-block;
    margin: 0 4px;
    transition: background 0.05s, transform 0.05s;
  }}
  .beat-indicator.active {{
    background: #7FFFD4;
    transform: scale(1.3);
  }}
  .btn-row {{
    display: flex;
    gap: 10px;
    justify-content: center;
    margin-top: 4px;
  }}
  button {{
    border: none;
    border-radius: 8px;
    padding: 8px 22px;
    font-size: 14px;
    font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
  }}
  .btn-start {{
    background: white;
    color: #0f5132;
  }}
  .btn-start:hover {{ background: #e0f2e9; transform: translateY(-1px); }}
  .btn-stop {{
    background: rgba(255,255,255,0.15);
    color: white;
    border: 1px solid rgba(255,255,255,0.4);
  }}
  .btn-stop:hover {{ background: rgba(255,255,255,0.25); }}
  .status-line {{
    font-size: 12px;
    opacity: 0.8;
    margin-top: 6px;
    min-height: 16px;
  }}
</style>
</head>
<body>
<div class="metro-card">
  <div class="bpm-display" id="bpmDisplay">{bpm}</div>
  <div class="bpm-label">BPM — Metronome</div>
  <div class="pendulum-wrap">
    <div class="pendulum" id="pendulum"></div>
  </div>
  <div>
    <span class="beat-indicator" id="b0"></span>
    <span class="beat-indicator" id="b1"></span>
    <span class="beat-indicator" id="b2"></span>
    <span class="beat-indicator" id="b3"></span>
  </div>
  <div class="btn-row">
    <button class="btn-start" onclick="startMetronome()">▶ Start</button>
    <button class="btn-stop" onclick="stopMetronome()">⏹ Stop</button>
  </div>
  <div class="status-line" id="statusLine">Click Start to begin pacing</div>
</div>

<script>
  let audioCtx = null;
  let nextBeat = 0;
  let schedTimer = null;
  let animFrame = null;
  let beatCount = 0;
  let playing = false;
  const BPM = {bpm};
  const beatSec = 60.0 / BPM;
  const LOOK_AHEAD = 0.1;  // seconds
  const SCHEDULE_INTERVAL = 50;  // ms

  function getCtx() {{
    if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    if (audioCtx.state === 'suspended') audioCtx.resume();
    return audioCtx;
  }}

  function scheduleClick(time, accent) {{
    const ctx = getCtx();
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.frequency.value = accent ? 1000 : 880;
    gain.gain.setValueAtTime(accent ? 0.5 : 0.3, time);
    gain.gain.exponentialRampToValueAtTime(0.001, time + 0.04);
    osc.start(time);
    osc.stop(time + 0.04);
  }}

  function scheduler() {{
    const ctx = getCtx();
    while (nextBeat < ctx.currentTime + LOOK_AHEAD) {{
      const accent = (beatCount % 4 === 0);
      scheduleClick(nextBeat, accent);
      // visual flash
      const idx = beatCount % 4;
      const delay = (nextBeat - ctx.currentTime) * 1000;
      setTimeout(() => flashBeat(idx), Math.max(0, delay));
      nextBeat += beatSec;
      beatCount++;
    }}
    schedTimer = setTimeout(scheduler, SCHEDULE_INTERVAL);
  }}

  function flashBeat(idx) {{
    document.querySelectorAll('.beat-indicator').forEach((el, i) => {{
      el.classList.toggle('active', i === idx);
    }});
    animatePendulum(idx);
  }}

  function animatePendulum(idx) {{
    const p = document.getElementById('pendulum');
    const angle = (idx % 2 === 0) ? 25 : -25;
    p.style.transform = `rotate(${{angle}}deg)`;
    p.style.transition = `transform ${{beatSec * 0.9}}s ease-in-out`;
  }}

  function startMetronome() {{
    if (playing) return;
    playing = true;
    const ctx = getCtx();
    nextBeat = ctx.currentTime + 0.05;
    beatCount = 0;
    scheduler();
    document.getElementById('statusLine').textContent =
      '🟢 Metronome running at ' + BPM + ' BPM — speak now';
  }}

  function stopMetronome() {{
    playing = false;
    clearTimeout(schedTimer);
    schedTimer = null;
    document.querySelectorAll('.beat-indicator').forEach(el => {{
      el.classList.remove('active');
    }});
    const p = document.getElementById('pendulum');
    p.style.transform = 'rotate(0deg)';
    document.getElementById('statusLine').textContent = 'Metronome stopped';
  }}

  {auto_js}
</script>
</body>
</html>
"""
    components.html(html, height=260, scrolling=False)


# ─────────────────────────────────────────────────────────────
# Full Browser Session UI
# ─────────────────────────────────────────────────────────────
def show_browser_live_session(bpm: int = 72,
                              sensitivity: str = "Medium",
                              auto_metronome: bool = True):
    """
    Show the cloud-compatible live session UI:
      1. JS metronome widget (plays in browser speakers)
      2. st.audio_input() for browser mic recording
      3. Analyse button → runs full Python pipeline

    Returns: audio bytes if ready to analyse, else None
    """
    st.info(
        "☁️ **Cloud Mode** — Browser-based session. "
        "Start the metronome, speak while it plays, then record and analyse.",
        icon="🎙️"
    )

    # ── How it works ──────────────────────────────────────────
    with st.expander("ℹ️ How Cloud Session Works", expanded=False):
        st.markdown("""
**Step 1:** Click **▶ Start** on the metronome below — it plays at your chosen BPM.

**Step 2:** Click **🎙️ Start recording** in the recorder below while the metronome plays.

**Step 3:** Speak naturally, keeping pace with the metronome beats.

**Step 4:** Click **⏹ Stop** to end recording, then click **🔍 Analyse Recording**.

> The metronome provides continuous rhythmic pacing — clinically proven to reduce
> stuttering frequency. Your recording is then analysed for fluency, fillers,
> repetitions, and WPM.
        """)

    # ── Metronome widget ──────────────────────────────────────
    render_metronome_widget(bpm=bpm, auto_start=False)

    st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)

    # ── Browser mic recording ─────────────────────────────────
    st.markdown("**🎙️ Record Your Speech**")
    audio_bytes = st.audio_input(
        "Record your voice",
        key="browser_live_input",
        help="Click the microphone to start recording, click again to stop."
    )

    if audio_bytes is not None:
        st.audio(audio_bytes, format="audio/wav")
        st.session_state['browser_audio_ready'] = audio_bytes

    # ── Analyse button ────────────────────────────────────────
    audio_ready = st.session_state.get('browser_audio_ready')
    if audio_ready is not None:
        st.markdown("<div style='margin-top:8px;'></div>",
                    unsafe_allow_html=True)
        if st.button("🔍 Analyse Recording",
                     key="analyse_browser_live",
                     type="primary",
                     use_container_width=True):
            return audio_ready

    return None
