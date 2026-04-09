"""
Browser-based live session for NeuroNudge cloud deployment.
Faithfully mirrors modules/live_session.py (LivePacingSession) in JS.

IMPORTANT — Web Speech API is blocked inside Streamlit's sandboxed iframe.
Word-repetition is therefore detected via a DUAL OSCILLATION approach:
  • Mode 2  — SYLLABLE stutter  : 4+ fast crossings in 1.5 s  (b-b-b-ball)
  • Mode 3  — WORD REPETITION   : 6+ rhythmic crossings in 4 s (the-the-the)
    Each spoken word creates one UP + one DOWN crossing, so 3 repetitions
    produce exactly 6 crossings.  A rhythmicity gate ensures the gaps are
    evenly spaced (hallmark of true repetition vs natural speech flow).

The three modes (energy-drop, syllable, word-repetition) mirror the three
detection modes in LivePacingSession._recording_thread().
"""

import streamlit as st
import streamlit.components.v1 as components


def is_native_audio_available() -> bool:
    try:
        import sounddevice as sd
        return any(d.get('max_input_channels', 0) > 0 for d in sd.query_devices())
    except Exception:
        return False


def show_browser_live_session(bpm: int = 72,
                              sensitivity: str = "Medium",
                              auto_metronome: bool = True):
    """
    Cloud live session — mirrors local LivePacingSession via Web Audio API.
    Returns audio bytes (from st.audio_input) when recording stops, else None.
    """

    # Match live_session.py sensitivity config exactly
    sens = {
        "Low":    {"drop_ratio": 0.35, "pause_ignore_ms": 2000},
        "Medium": {"drop_ratio": 0.30, "pause_ignore_ms": 1500},
        "High":   {"drop_ratio": 0.25, "pause_ignore_ms": 1000},
    }
    cfg = sens.get(sensitivity, sens["Medium"])
    drop_ratio      = cfg["drop_ratio"]
    pause_ignore_ms = cfg["pause_ignore_ms"]
    auto_met_js     = "true" if auto_metronome else "false"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:'Segoe UI',sans-serif;background:#f8faf9;padding:10px;}}
.status{{
  background:linear-gradient(135deg,#0f5132,#1a7a4a);
  color:white;border-radius:10px;padding:9px 14px;
  font-size:13px;font-weight:600;text-align:center;margin-bottom:4px;
}}
.phase{{font-size:11px;color:#6b7b8d;text-align:center;margin-bottom:8px;min-height:16px;}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:8px;}}
.m{{background:#f0f7f3;border-radius:8px;padding:8px;text-align:center;}}
.mv{{font-size:20px;font-weight:800;color:#0f5132;}}
.ml{{font-size:10px;color:#6b7b8d;margin-top:2px;}}
.metro{{
  background:linear-gradient(135deg,#0f5132,#1a7a4a);border-radius:10px;
  padding:10px 14px;color:white;text-align:center;margin-bottom:8px;display:none;
}}
.metro.on{{display:block;}}
.mbpm{{font-size:32px;font-weight:800;line-height:1;}}
.msub{{font-size:11px;opacity:0.8;}}
.beats{{margin:6px 0 3px;}}
.dot{{
  width:13px;height:13px;border-radius:50%;
  background:rgba(255,255,255,0.25);display:inline-block;
  margin:0 3px;transition:background 0.05s,transform 0.05s;
}}
.dot.on{{background:#7fffd4;transform:scale(1.4);}}
.btns{{display:flex;gap:8px;}}
button{{
  border:none;border-radius:8px;padding:10px;
  font-size:13px;font-weight:700;cursor:pointer;
  transition:all 0.15s;flex:1;
}}
.bstart{{background:#0f5132;color:white;}}
.bstart:hover{{background:#1a7a4a;}}
.bstop{{background:#dc2626;color:white;display:none;}}
.bstop:hover{{background:#b91c1c;}}
.done{{
  background:#e9f5ee;border-radius:8px;padding:8px;
  font-size:12px;color:#0f5132;margin-top:8px;
  display:none;text-align:center;font-weight:600;
}}
.done.show{{display:block;}}
</style></head><body>

<div class="status"  id="st">Click Start Session to begin</div>
<div class="phase"   id="ph"></div>

<div class="metrics">
  <div class="m"><div class="mv" id="mt">0s</div><div class="ml">Time</div></div>
  <div class="m"><div class="mv" id="ms">0</div><div class="ml">Stutters</div></div>
  <div class="m"><div class="mv" id="mm">Idle</div><div class="ml">Metronome</div></div>
  <div class="m"><div class="mv" id="msnr">—</div><div class="ml">SNR</div></div>
</div>

<div class="metro" id="mc">
  <div class="mbpm">{bpm} BPM</div>
  <div class="msub" id="metroType">Metronome — Active</div>
  <div class="beats">
    <span class="dot" id="d0"></span><span class="dot" id="d1"></span>
    <span class="dot" id="d2"></span><span class="dot" id="d3"></span>
  </div>
</div>

<div class="btns">
  <button class="bstart" id="bs" onclick="startSess()">🎙 Start Session</button>
  <button class="bstop"  id="be" onclick="stopSess()">⏹ Stop Session</button>
</div>
<div class="done" id="done">
  ✅ Session done — stop the mic recorder below to run analysis automatically.
</div>

<script>
// ── Config — mirrors live_session.py constants ───────────────────────────────
const BPM            = {bpm};
const DROP_RATIO     = {drop_ratio};        // energy drop fraction → stutter threshold
const PAUSE_IGNORE   = {pause_ignore_ms};   // ms of sustained low energy before trigger
const AUTO_MET       = {auto_met_js};

// Audio EMA + frame sizes (100 ms frames at ~44 kHz via Web Audio)
const SMOOTH_K       = 0.92;   // EMA coefficient (~4-frame window)
const AMBIENT_FRAMES = 10;     // ~1 s ambient noise learning
const CALIB_FRAMES   = 12;     // speech frames for calibration
const NOISE_WIN      = 50;     // rolling noise window (frames)
const SPEECH_WIN     = 30;     // rolling speech window (frames)
const RECAL_EVERY    = 20;     // frames between threshold recalibrations
const SNR_SPEECH     = 2.0;    // SNR threshold to detect speech onset

// Mode 2 — SYLLABLE stutter oscillation (b-b-b-ball) — mirrors _OSCILLATION_MIN
const OSC_WIN_MS     = 1500;   // 1.5 s window
const OSC_MIN        = 4;      // 4+ crossings = syllable stutter

// Mode 3 — WORD REPETITION oscillation (the-the-the)
// Each repeated word creates ONE up-crossing + ONE down-crossing.
// 3 repetitions → 6 crossings. We use a lower energy midpoint so we can
// see the individual word humps even when speech volume is normal.
const WREP_WIN_MS    = 4000;   // 4 s window (allows slow repetitions)
const WREP_MIN       = 6;      // 6 crossings = 3 word repetitions
const WREP_MIN_GAP   = 100;    // min ms between crossings (real words ≥100 ms)
const WREP_MAX_GAP   = 1000;   // max ms between crossings (≤1 s per word)
const WREP_RHYTHM    = 0.75;   // rhythmicity: (max-min)/avg must be < this

// Recovery grace period — mirrors _RECOVERY_GRACE_SEC = 0.5 s
const GRACE_MS       = 500;
const MIN_ON_MS      = 2000;   // metronome stays on at least 2 s
const MIN_OFF_MS     = 1000;   // metronome stays off at least 1 s before re-trigger

// ── State ────────────────────────────────────────────────────────────────────
let actx=null, ana=null, stream=null, running=false;

// Phases: 0=IDLE 1=AMBIENT 2=WAIT_SPEECH 3=CALIBRATING 4=MONITORING
let phase=0;

let smooth=0, t0=null, lastFrameMs=0, frameIdx=0;

// Noise / speech trackers
let ambBuf=[], noiseTracker=[], noiseFloor=0;
let calibBuf=[], speechRecent=[];
let eThr=0, rThr=0;          // energy-drop thresholds
let oscMid=0;                 // midpoint for syllable oscillation
let wrepMid=0;                // lower midpoint for word-rep oscillation
let recalCounter=0;

// Metronome state
let metOn=false, cnt=0;
let metroTimer=null, nextBeat=0, beatIdx=0;
let metroOnTime=0, metroOffTime=0, recovStart=null;

// Mode 1 — energy drop
let lowEnergyStart=null;

// Mode 2 — syllable oscillation
let oscCrossings=[], lastOscAbove=null, oscActive=false;

// Mode 3 — word repetition oscillation
let wrepCrossings=[], lastWrepAbove=null, wrepActive=false;

// ── Utility ──────────────────────────────────────────────────────────────────
function pct(arr, p) {{
  const s=[...arr].sort((a,b)=>a-b);
  return s[Math.floor(s.length*p)] || 0;
}}
function avg(arr) {{ return arr.length ? arr.reduce((a,b)=>a+b)/arr.length : 0; }}

function updateNoise(rms) {{
  noiseTracker.push(rms);
  if(noiseTracker.length > NOISE_WIN) noiseTracker.shift();
  noiseFloor = pct(noiseTracker, 0.30);
}}
function updateSpeech(rms) {{
  speechRecent.push(rms);
  if(speechRecent.length > SPEECH_WIN) speechRecent.shift();
}}
function getSNR(rms) {{ return noiseFloor > 0 ? rms/noiseFloor : 100; }}

function recalc() {{
  if(!speechRecent.length) return;
  const recentAvg = avg(speechRecent);
  const noise = Math.max(noiseFloor, 0.0001);
  const dyn   = recentAvg - noise;
  if(dyn <= 0) {{
    eThr = noise * 1.2;  rThr = noise * 1.5;
  }} else {{
    eThr = noise + dyn * DROP_RATIO;
    rThr = noise + dyn * 0.45;
  }}
  // Oscillation midpoints
  oscMid  = (eThr + rThr) / 2;     // syllable: between thresholds
  wrepMid = noise + dyn * 0.20;    // word-rep: 20% of dynamic range above noise
                                    //  → catches individual word humps
}}

function setStatus(m) {{ document.getElementById('st').textContent = m; }}
function setPh(m)     {{ document.getElementById('ph').textContent = m; }}

// ── Start session ────────────────────────────────────────────────────────────
async function startSess() {{
  try {{
    setStatus('Requesting microphone…');
    stream = await navigator.mediaDevices.getUserMedia({{audio:true,video:false}});
    actx   = new (window.AudioContext||window.webkitAudioContext)();
    const src = actx.createMediaStreamSource(stream);
    ana = actx.createAnalyser();
    ana.fftSize = 2048;
    ana.smoothingTimeConstant = 0.0; // we do our own EMA
    src.connect(ana);

    running=true; smooth=0; t0=Date.now(); lastFrameMs=0; frameIdx=0;
    ambBuf=[];  noiseTracker=[]; noiseFloor=0;
    calibBuf=[]; speechRecent=[];
    eThr=0; rThr=0; oscMid=0; wrepMid=0; recalCounter=0;
    metOn=false; cnt=0;
    metroOnTime=0; metroOffTime=Date.now()-MIN_OFF_MS; recovStart=null;
    lowEnergyStart=null;
    oscCrossings=[]; lastOscAbove=null; oscActive=false;
    wrepCrossings=[]; lastWrepAbove=null; wrepActive=false;
    phase=1; // AMBIENT

    document.getElementById('bs').style.display='none';
    document.getElementById('be').style.display='block';
    document.getElementById('mc').classList.remove('on');
    document.getElementById('done').classList.remove('show');
    document.getElementById('ms').textContent='0';
    document.getElementById('mm').textContent='Idle';
    document.getElementById('msnr').textContent='—';

    loop();
  }} catch(e) {{
    setStatus('Mic error: '+e.message+' — allow mic and retry');
  }}
}}

// ── Main loop (~10 fps, 100 ms per frame) ────────────────────────────────────
function loop() {{
  if(!running) return;
  requestAnimationFrame(loop);

  const now = Date.now();
  if(now - lastFrameMs < 80) return;
  lastFrameMs = now;
  frameIdx++;

  const buf = new Float32Array(ana.frequencyBinCount);
  ana.getFloatTimeDomainData(buf);
  let s=0; for(let i=0;i<buf.length;i++) s+=buf[i]*buf[i];
  const rms = Math.sqrt(s/buf.length);
  smooth = SMOOTH_K*smooth + (1-SMOOTH_K)*rms;

  const el = (now-t0)/1000;
  document.getElementById('mt').textContent = Math.floor(el)+'s';

  // ── PHASE 1: Ambient noise (~1 s) ────────────────────────────────────────
  if(phase===1) {{
    ambBuf.push(rms);
    updateNoise(rms);
    const remain = Math.max(0, Math.ceil(1 - el));
    setStatus('Learning ambient noise… stay silent ('+remain+'s)');
    setPh('Step 1 / 4 — Ambient calibration');
    if(ambBuf.length >= AMBIENT_FRAMES) {{ phase=2; }} // WAIT_SPEECH
    return;
  }}

  // ── PHASE 2: Wait for speech (SNR gate) ──────────────────────────────────
  if(phase===2) {{
    const snr = getSNR(rms);
    document.getElementById('msnr').textContent = snr.toFixed(1)+'×';
    if(snr > SNR_SPEECH && rms > 0.002) {{
      phase=3; // CALIBRATING
      setStatus('Calibrating… keep speaking naturally');
      setPh('Step 2 / 4 — Measuring your voice level');
    }} else {{
      updateNoise(rms);
      setStatus('Listening… start speaking now');
      setPh('Step 2 / 4 — Waiting for speech (SNR '+snr.toFixed(1)+'×)');
    }}
    return;
  }}

  // ── PHASE 3: Calibrate ───────────────────────────────────────────────────
  if(phase===3) {{
    const snr = getSNR(rms);
    document.getElementById('msnr').textContent = snr.toFixed(1)+'×';
    if(snr > SNR_SPEECH) {{ calibBuf.push(rms); updateSpeech(rms); }}
    const remain = Math.max(0, CALIB_FRAMES - calibBuf.length);
    setStatus('Calibrating… ('+remain+' frames left)');
    setPh('Step 3 / 4 — Computing detection thresholds');
    if(calibBuf.length >= CALIB_FRAMES) {{
      noiseFloor = pct(noiseTracker, 0.30);
      recalc();
      phase=4; // MONITORING
      setStatus('Monitoring — metronome auto-starts on stutter');
      setPh('Step 4 / 4 — Live stutter detection active');
    }}
    return;
  }}

  // ── PHASE 4: MONITORING ──────────────────────────────────────────────────
  const snr = getSNR(smooth);
  document.getElementById('msnr').textContent = snr.toFixed(1)+'×';

  // Adaptive trackers
  if(smooth < eThr) updateNoise(rms);
  if(smooth > rThr) updateSpeech(rms);
  recalCounter++;
  if(recalCounter >= RECAL_EVERY) {{ recalCounter=0; recalc(); }}

  // ── Recovery (grace period before stopping metronome) ────────────────────
  if(metOn) {{
    if(smooth > rThr) {{
      if(!recovStart) {{ recovStart=now; }}
      else if(now-recovStart >= GRACE_MS && now-metroOnTime >= MIN_ON_MS) {{
        stopMetro('energy_recovery');
      }}
    }} else {{
      recovStart=null; // energy dropped again — reset grace
    }}
    return; // skip new triggers while correcting
  }}

  // ── MODE 1: Energy-drop (sustained low energy) ───────────────────────────
  if(smooth < eThr) {{
    if(lowEnergyStart===null) lowEnergyStart=now;
    if(now-lowEnergyStart >= PAUSE_IGNORE && now-metroOffTime >= MIN_OFF_MS) {{
      trigger('block'); return;
    }}
  }} else {{
    lowEnergyStart=null;
  }}

  // ── MODE 2: SYLLABLE oscillation (b-b-b-ball) ────────────────────────────
  const aboveOsc = smooth > oscMid;
  if(lastOscAbove!==null && aboveOsc!==lastOscAbove) {{
    oscCrossings.push(now);
  }}
  lastOscAbove = aboveOsc;
  oscCrossings = oscCrossings.filter(t => now-t < OSC_WIN_MS);

  if(oscCrossings.length >= OSC_MIN) {{
    if(!oscActive && now-metroOffTime >= MIN_OFF_MS) {{
      oscActive=true;
      trigger('syllable_stutter'); return;
    }}
  }} else {{
    if(oscActive && oscCrossings.length<=1) oscActive=false;
  }}

  // ── MODE 3: WORD REPETITION (the-the-the) ────────────────────────────────
  // Uses a LOWER energy midpoint (wrepMid = 20% of dynamic range)
  // so individual word humps register as separate crossings.
  // Pattern for "the-the-the": UP, DOWN, UP, DOWN, UP, DOWN → 6 crossings
  // The gaps between crossings should be evenly spaced (rhythmicity gate).
  const aboveWrep = smooth > wrepMid;
  if(lastWrepAbove!==null && aboveWrep!==lastWrepAbove) {{
    wrepCrossings.push(now);
  }}
  lastWrepAbove = aboveWrep;
  wrepCrossings = wrepCrossings.filter(t => now-t < WREP_WIN_MS);

  if(wrepCrossings.length >= WREP_MIN) {{
    const gaps=[];
    for(let i=1;i<wrepCrossings.length;i++) gaps.push(wrepCrossings[i]-wrepCrossings[i-1]);
    const a   = avg(gaps);
    const gMax= Math.max(...gaps);
    const gMin= Math.min(...gaps);
    const rhythmic = (gMax-gMin) < a * WREP_RHYTHM; // evenly spaced = repetition
    if(a > WREP_MIN_GAP && a < WREP_MAX_GAP && rhythmic &&
       now-metroOffTime >= MIN_OFF_MS) {{
      wrepActive=true;
      trigger('repetition'); wrepCrossings=[]; return;
    }}
  }}
  if(wrepActive && smooth > rThr) wrepActive=false;
}}

// ── Trigger ──────────────────────────────────────────────────────────────────
function trigger(type) {{
  if(!AUTO_MET || metOn) return;
  metOn=true; cnt++;
  metroOnTime=Date.now(); recovStart=null;
  lowEnergyStart=null; oscCrossings=[]; wrepCrossings=[];
  startMetro(type);
  document.getElementById('ms').textContent=cnt;
  document.getElementById('mm').textContent='ACTIVE';
  const lab={{block:'Block detected',syllable_stutter:'Syllable stutter',repetition:'Word repetition detected'}};
  setStatus((lab[type]||'Stutter detected')+' — follow the metronome!');
  document.getElementById('metroType').textContent=(lab[type]||'Stutter')+' — follow the rhythm';
  document.getElementById('mc').classList.add('on');
  setPh('🔴 Stutter event #'+cnt);
}}

function stopMetro(reason) {{
  if(!metOn) return;
  metOn=false; metroOffTime=Date.now(); recovStart=null;
  oscActive=false; wrepActive=false;
  clearTimeout(metroTimer);
  document.querySelectorAll('.dot').forEach(d=>d.classList.remove('on'));
  document.getElementById('mc').classList.remove('on');
  document.getElementById('mm').textContent='Idle';
  setStatus('Monitoring — metronome auto-starts on stutter');
  setPh('Step 4 / 4 — Live stutter detection active');
}}

// ── Metronome scheduler (Web Audio, precise timing) ──────────────────────────
function startMetro(type) {{
  beatIdx=0; nextBeat=actx.currentTime+0.05; sched();
}}
function sched() {{
  if(!metOn) return;
  while(nextBeat < actx.currentTime+0.12) {{
    playClick(nextBeat, beatIdx%4===0);
    const d=(nextBeat-actx.currentTime)*1000;
    const i=beatIdx%4;
    setTimeout(()=>flash(i), Math.max(0,d));
    nextBeat += 60/BPM; beatIdx++;
  }}
  metroTimer=setTimeout(sched,40);
}}
function playClick(t,acc) {{
  const o=actx.createOscillator(), g=actx.createGain();
  o.connect(g); g.connect(actx.destination);
  o.frequency.value = acc?1000:880;
  g.gain.setValueAtTime(acc?0.5:0.3, t);
  g.gain.exponentialRampToValueAtTime(0.001, t+0.04);
  o.start(t); o.stop(t+0.045);
}}
function flash(i) {{
  document.querySelectorAll('.dot').forEach((d,j)=>d.classList.toggle('on',j===i));
}}

// ── Stop session ─────────────────────────────────────────────────────────────
function stopSess() {{
  running=false; metOn=false;
  clearTimeout(metroTimer);
  document.querySelectorAll('.dot').forEach(d=>d.classList.remove('on'));
  if(stream) stream.getTracks().forEach(t=>t.stop());
  document.getElementById('be').style.display='none';
  document.getElementById('bs').style.display='block';
  document.getElementById('bs').textContent='🔄 New Session';
  setStatus('Session complete — '+cnt+' stutter event(s) detected');
  document.getElementById('mm').textContent = cnt ? cnt+' events' : 'None';
  document.getElementById('mc').classList.remove('on');
  document.getElementById('done').classList.add('show');
  setPh('');
}}
</script></body></html>
"""

    components.html(html, height=410, scrolling=False)

    st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)
    st.markdown("**🎙️ Record Your Session**")
    st.caption(
        "Tap the mic icon to start recording at the same time as the session above. "
        "Tap again to stop — analysis runs automatically."
    )
    audio_bytes = st.audio_input(
        "Record your voice",
        key="browser_live_input",
        help="Tap to start / stop. Analysis runs automatically when you stop."
    )
    if audio_bytes is not None:
        st.audio(audio_bytes, format="audio/wav")
        return audio_bytes
    return None
