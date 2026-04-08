"""
Browser-based live session for NeuroNudge cloud deployment.
Mirrors LivePacingSession: real-time mic → stutter detection → auto-metronome.
Records PCM WAV. After session, user uploads WAV for full analysis.
"""

import streamlit as st
import streamlit.components.v1 as components


def is_native_audio_available() -> bool:
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        input_devs = [d for d in devices if d.get('max_input_channels', 0) > 0]
        return len(input_devs) > 0
    except Exception:
        return False


def show_browser_live_session(bpm: int = 72,
                              sensitivity: str = "Medium",
                              auto_metronome: bool = True):
    """
    Full cloud live session:
    - Real-time mic access (getUserMedia)
    - Calibration phase (3 sec) then stutter detection
    - Auto-metronome when energy drops (stutter/block detected)
    - Records PCM WAV via ScriptProcessor
    - After stop: shows download + file_uploader for analysis
    Returns: audio bytes if user uploads recording, else None
    """

    # Sensitivity → energy ratio threshold
    sensitivity_map = {"Low": 0.35, "Medium": 0.45, "High": 0.55}
    stutter_ratio = sensitivity_map.get(sensitivity, 0.45)

    html = f"""
<!DOCTYPE html><html><head>
<meta charset="utf-8">
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{
    font-family: 'Segoe UI', sans-serif;
    background: #f8faf9;
    padding: 12px;
    min-height: 100vh;
  }}
  .card {{
    background: white;
    border-radius: 14px;
    padding: 16px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.08);
    margin-bottom: 10px;
  }}
  .status-bar {{
    background: linear-gradient(135deg, #0f5132, #1a7a4a);
    color: white;
    border-radius: 10px;
    padding: 10px 16px;
    font-size: 13px;
    font-weight: 600;
    text-align: center;
    margin-bottom: 10px;
  }}
  .metrics {{
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 8px;
    margin-bottom: 10px;
  }}
  .metric {{
    background: #f0f7f3;
    border-radius: 8px;
    padding: 8px;
    text-align: center;
  }}
  .metric-val {{
    font-size: 22px;
    font-weight: 800;
    color: #0f5132;
  }}
  .metric-lbl {{
    font-size: 10px;
    color: #6b7b8d;
    margin-top: 2px;
  }}
  .energy-wrap {{
    background: #e9f5ee;
    border-radius: 6px;
    height: 10px;
    margin-bottom: 10px;
    overflow: hidden;
  }}
  .energy-bar {{
    height: 100%;
    background: #0f5132;
    border-radius: 6px;
    transition: width 0.1s;
    width: 0%;
  }}
  .metro-card {{
    background: linear-gradient(135deg, #0f5132, #1a7a4a);
    border-radius: 12px;
    padding: 12px 16px;
    color: white;
    text-align: center;
    margin-bottom: 10px;
    display: none;
  }}
  .metro-card.visible {{ display: block; }}
  .metro-bpm {{ font-size: 36px; font-weight: 800; line-height: 1; }}
  .metro-label {{ font-size: 11px; opacity: 0.8; }}
  .beats {{ margin: 8px 0 4px; }}
  .dot {{
    width: 14px; height: 14px;
    border-radius: 50%;
    background: rgba(255,255,255,0.25);
    display: inline-block;
    margin: 0 3px;
    transition: background 0.05s, transform 0.05s;
  }}
  .dot.active {{ background: #7FFFD4; transform: scale(1.4); }}
  .btn-row {{ display: flex; gap: 10px; justify-content: center; margin-top: 8px; }}
  button {{
    border: none; border-radius: 8px;
    padding: 9px 24px; font-size: 14px; font-weight: 700;
    cursor: pointer; transition: all 0.15s;
  }}
  .btn-start {{
    background: #0f5132; color: white; width: 100%;
    padding: 12px;
  }}
  .btn-start:hover {{ background: #1a7a4a; }}
  .btn-stop {{
    background: #dc2626; color: white; width: 100%;
    padding: 12px; display: none;
  }}
  .btn-stop:hover {{ background: #b91c1c; }}
  .result-area {{ display: none; }}
  .result-area.visible {{ display: block; }}
  a.download-btn {{
    display: block;
    background: #0f5132; color: white;
    border-radius: 8px; padding: 10px;
    text-align: center; text-decoration: none;
    font-weight: 700; margin-top: 8px; font-size: 14px;
  }}
  a.download-btn:hover {{ background: #1a7a4a; }}
  .log {{ max-height: 100px; overflow-y: auto; font-size: 11px; color:#444; }}
  .log-entry {{ padding: 2px 0; border-bottom: 1px solid #f0f0f0; }}
</style>
</head>
<body>

<div class="status-bar" id="statusBar">
  Click Start Session to begin
</div>

<div class="metrics">
  <div class="metric">
    <div class="metric-val" id="mTime">0s</div>
    <div class="metric-lbl">Time</div>
  </div>
  <div class="metric">
    <div class="metric-val" id="mEnergy">-</div>
    <div class="metric-lbl">Energy</div>
  </div>
  <div class="metric">
    <div class="metric-val" id="mStutter">0</div>
    <div class="metric-lbl">Stutters</div>
  </div>
  <div class="metric">
    <div class="metric-val" id="mMetro">Idle</div>
    <div class="metric-lbl">Metronome</div>
  </div>
</div>

<div class="energy-wrap"><div class="energy-bar" id="energyBar"></div></div>

<div class="metro-card" id="metroCard">
  <div class="metro-bpm">{bpm} BPM</div>
  <div class="metro-label">Metronome — Active</div>
  <div class="beats">
    <span class="dot" id="d0"></span>
    <span class="dot" id="d1"></span>
    <span class="dot" id="d2"></span>
    <span class="dot" id="d3"></span>
  </div>
</div>

<div class="btn-row">
  <button class="btn-start" id="btnStart" onclick="startSession()">
    🎙 Start Session
  </button>
  <button class="btn-stop" id="btnStop" onclick="stopSession()">
    ⏹ Stop Session
  </button>
</div>

<div class="result-area" id="resultArea">
  <div class="card" style="margin-top:10px;">
    <b>Session Complete</b><br>
    <audio id="audioPlayback" controls style="width:100%;margin-top:8px;"></audio>
    <a class="download-btn" id="downloadLink" href="#" download="neuronudge_session.wav">
      ⬇ Download Session WAV
    </a>
    <p style="font-size:11px;color:#666;margin-top:6px;text-align:center;">
      Download the WAV above, then upload it in Streamlit to get your full analysis report.
    </p>
  </div>
  <div class="card">
    <b>Session Events</b>
    <div class="log" id="eventLog"></div>
  </div>
</div>

<script>
// ── Config ──────────────────────────────────────────────────
const BPM = {bpm};
const STUTTER_RATIO = {stutter_ratio};
const CALIBRATION_SEC = 3;
const SR = 48000;  // AudioContext default

// ── State ───────────────────────────────────────────────────
let audioCtx = null;
let analyzerNode = null;
let scriptProcessor = null;
let stream = null;
let isRunning = false;
let isCalibrating = true;
let calibSamples = [];
let pcmSamples = [];
let startTime = null;
let speechPeak = 0;
let energyThreshold = 0;
let recoveryThreshold = 0;
let metronomePlaying = false;
let stutterCount = 0;
let userHasSpoken = false;
let beatCount = 0;
let metroTimer = null;
let metroCtx = null;
let nextBeat = 0;
let events = [];
let silentGain = null;

// ── Start session ────────────────────────────────────────────
async function startSession() {{
  try {{
    document.getElementById('statusBar').textContent = 'Requesting microphone access...';
    stream = await navigator.mediaDevices.getUserMedia({{ audio: true, video: false }});

    audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const sourceNode = audioCtx.createMediaStreamSource(stream);
    
    analyzerNode = audioCtx.createAnalyser();
    analyzerNode.fftSize = 2048;
    analyzerNode.smoothingTimeConstant = 0.15;
    sourceNode.connect(analyzerNode);

    // ScriptProcessor for PCM capture
    scriptProcessor = audioCtx.createScriptProcessor(4096, 1, 1);
    scriptProcessor.onaudioprocess = function(e) {{
      if (!isRunning) return;
      const ch = e.inputBuffer.getChannelData(0);
      for (let i = 0; i < ch.length; i++) pcmSamples.push(ch[i]);
    }};
    sourceNode.connect(scriptProcessor);
    silentGain = audioCtx.createGain();
    silentGain.gain.value = 0;
    scriptProcessor.connect(silentGain);
    silentGain.connect(audioCtx.destination);

    isRunning = true;
    startTime = Date.now();
    calibSamples = [];
    pcmSamples = [];
    stutterCount = 0;
    userHasSpoken = false;
    events = [];
    isCalibrating = true;
    metronomePlaying = false;

    document.getElementById('btnStart').style.display = 'none';
    document.getElementById('btnStop').style.display = 'block';
    document.getElementById('resultArea').classList.remove('visible');
    document.getElementById('metroCard').classList.remove('visible');
    document.getElementById('mStutter').textContent = '0';
    document.getElementById('mMetro').textContent = 'Idle';

    analyzeLoop();
  }} catch(err) {{
    document.getElementById('statusBar').textContent =
      'Microphone error: ' + err.message + ' — Please allow mic access and try again.';
  }}
}}

// ── Analysis loop ────────────────────────────────────────────
function analyzeLoop() {{
  if (!isRunning) return;
  requestAnimationFrame(analyzeLoop);

  const bufLen = analyzerNode.frequencyBinCount;
  const data = new Float32Array(bufLen);
  analyzerNode.getFloatTimeDomainData(data);

  let sum = 0;
  for (let i = 0; i < bufLen; i++) sum += data[i] * data[i];
  const rms = Math.sqrt(sum / bufLen);

  const elapsed = (Date.now() - startTime) / 1000;
  updateMetrics(elapsed, rms);

  if (isCalibrating) {{
    calibSamples.push(rms);
    if (rms > 0.008) userHasSpoken = true;

    if (userHasSpoken) {{
      document.getElementById('statusBar').textContent =
        'Calibrating... Keep speaking naturally (' + Math.ceil(CALIBRATION_SEC - elapsed) + 's)';
    }} else {{
      document.getElementById('statusBar').textContent =
        'Listening... Start speaking now';
    }}

    if (elapsed >= CALIBRATION_SEC && userHasSpoken) {{
      // Compute thresholds
      const sorted = [...calibSamples].sort((a,b) => a-b);
      speechPeak = sorted[Math.floor(sorted.length * 0.9)];
      energyThreshold = speechPeak * STUTTER_RATIO;
      recoveryThreshold = speechPeak * (STUTTER_RATIO + 0.15);
      isCalibrating = false;
      events.push({{ type:'calibrated', time: Math.round(elapsed*10)/10,
        threshold: energyThreshold.toFixed(5) }});
      document.getElementById('statusBar').textContent =
        'Monitoring — metronome will auto-start on stuttering';
    }}
  }} else {{
    // Stutter detection
    if (rms < energyThreshold && !metronomePlaying) {{
      metronomePlaying = true;
      stutterCount++;
      startMetronome();
      events.push({{ type:'metronome_start', reason:'energy_drop',
        time: Math.round(elapsed*10)/10, energy: rms.toFixed(5) }});
      document.getElementById('mStutter').textContent = stutterCount;
      document.getElementById('statusBar').textContent =
        'Stutter detected — Metronome active, follow the rhythm!';
    }} else if (rms > recoveryThreshold && metronomePlaying) {{
      metronomePlaying = false;
      stopMetronome();
      events.push({{ type:'metronome_stop', time: Math.round(elapsed*10)/10,
        reason:'recovered' }});
      document.getElementById('statusBar').textContent =
        'Monitoring — metronome will auto-start on stuttering';
    }}
    document.getElementById('mMetro').textContent =
      metronomePlaying ? 'ACTIVE' : 'Idle';
  }}
}}

function updateMetrics(elapsed, rms) {{
  document.getElementById('mTime').textContent = Math.floor(elapsed) + 's';
  document.getElementById('mEnergy').textContent = (rms * 100).toFixed(1) + '%';
  const pct = Math.min(100, rms * 800);
  document.getElementById('energyBar').style.width = pct + '%';
}}

// ── Metronome ────────────────────────────────────────────────
function startMetronome() {{
  document.getElementById('metroCard').classList.add('visible');
  if (!metroCtx) metroCtx = audioCtx;
  beatCount = 0;
  nextBeat = metroCtx.currentTime + 0.05;
  scheduleMetronome();
}}

function scheduleMetronome() {{
  if (!metronomePlaying) return;
  while (nextBeat < metroCtx.currentTime + 0.1) {{
    playClick(nextBeat, beatCount % 4 === 0);
    const idx = beatCount % 4;
    const delay = (nextBeat - metroCtx.currentTime) * 1000;
    setTimeout(() => flashDot(idx), Math.max(0, delay));
    nextBeat += 60.0 / BPM;
    beatCount++;
  }}
  metroTimer = setTimeout(scheduleMetronome, 40);
}}

function playClick(time, accent) {{
  const osc = metroCtx.createOscillator();
  const g = metroCtx.createGain();
  osc.connect(g); g.connect(metroCtx.destination);
  osc.frequency.value = accent ? 1000 : 880;
  g.gain.setValueAtTime(accent ? 0.5 : 0.3, time);
  g.gain.exponentialRampToValueAtTime(0.001, time + 0.04);
  osc.start(time); osc.stop(time + 0.045);
}}

function flashDot(idx) {{
  document.querySelectorAll('.dot').forEach((d, i) =>
    d.classList.toggle('active', i === idx));
}}

function stopMetronome() {{
  clearTimeout(metroTimer);
  document.querySelectorAll('.dot').forEach(d => d.classList.remove('active'));
  document.getElementById('metroCard').classList.remove('visible');
}}

// ── Stop session ─────────────────────────────────────────────
function stopSession() {{
  isRunning = false;
  metronomePlaying = false;
  stopMetronome();
  if (stream) stream.getTracks().forEach(t => t.stop());
  scriptProcessor.disconnect();
  silentGain.disconnect();

  document.getElementById('btnStop').style.display = 'none';
  document.getElementById('btnStart').style.display = 'block';
  document.getElementById('btnStart').textContent = '🔄 New Session';
  document.getElementById('statusBar').textContent =
    'Session complete — Download WAV below for analysis';

  // Encode PCM → WAV
  const wavBuffer = encodeWAV(pcmSamples, Math.round(audioCtx.sampleRate));
  const blob = new Blob([wavBuffer], {{ type: 'audio/wav' }});
  const url = URL.createObjectURL(blob);

  document.getElementById('audioPlayback').src = url;
  const dl = document.getElementById('downloadLink');
  dl.href = url;
  dl.download = 'neuronudge_session.wav';

  // Event log
  const log = document.getElementById('eventLog');
  log.innerHTML = '';
  events.forEach(e => {{
    const d = document.createElement('div');
    d.className = 'log-entry';
    if (e.type === 'calibrated') {{
      d.textContent = '✅ Calibrated at ' + e.time + 's — threshold=' + e.threshold;
    }} else if (e.type === 'metronome_start') {{
      d.textContent = '⏸ Metronome ON at ' + e.time + 's (energy drop, energy=' + e.energy + ')';
    }} else if (e.type === 'metronome_stop') {{
      d.textContent = '✅ Metronome OFF at ' + e.time + 's (recovered)';
    }}
    log.appendChild(d);
  }});

  document.getElementById('resultArea').classList.add('visible');
}}

// ── PCM → WAV encoder ────────────────────────────────────────
function encodeWAV(samples, sampleRate) {{
  const buf = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buf);
  function ws(off, str) {{
    for (let i = 0; i < str.length; i++) view.setUint8(off + i, str.charCodeAt(i));
  }}
  ws(0, 'RIFF');
  view.setUint32(4, 36 + samples.length * 2, true);
  ws(8, 'WAVE'); ws(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);   // PCM
  view.setUint16(22, 1, true);   // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  ws(36, 'data');
  view.setUint32(40, samples.length * 2, true);
  for (let i = 0; i < samples.length; i++) {{
    const v = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(44 + i * 2, v < 0 ? v * 32768 : v * 32767, true);
  }}
  return buf;
}}
</script>
</body></html>
"""

    components.html(html, height=520, scrolling=False)

    st.markdown("<div style='margin-top:12px;'></div>", unsafe_allow_html=True)
    st.markdown("**📤 Upload Your Session Recording for Analysis**")
    st.caption(
        "After your session ends above — download the WAV file, "
        "then upload it here to get your full fluency report."
    )

    uploaded = st.file_uploader(
        "Upload session WAV",
        type=["wav"],
        key="cloud_session_upload",
        label_visibility="collapsed"
    )

    if uploaded is not None:
        audio_bytes = uploaded.getvalue()
        st.audio(audio_bytes, format="audio/wav")
        st.session_state['browser_audio_ready'] = audio_bytes
        st.success("✅ Recording received! Click **Analyse Recording** below.")

    audio_ready = st.session_state.get('browser_audio_ready')
    if audio_ready is not None:
        if st.button("🔍 Analyse Recording",
                     key="analyse_browser_live",
                     type="primary",
                     use_container_width=True):
            return audio_ready

    return None
