"""
Browser-based live session for NeuroNudge cloud deployment.
Faithfully mirrors modules/live_session.py (LivePacingSession) in JS:

 Phase 0 – Learn ambient noise (~1 s, AMBIENT_FRAMES frames)
 Phase 1 – Wait for user to start speaking (SNR > 2×)
 Phase 2 – Calibrate on real speech (CALIB_FRAMES frames)
 Phase 3 – Stutter detection with three independent modes:
    1. Energy-drop    : sustained low energy after speech
    2. Oscillation    : 4+ threshold crossings in 1.5 s (syllable stutter)
    3. Word-repetition: Web Speech API partial text → 3+ same word in a row

Recovery uses a grace-period (GRACE_SEC) just like the Python version.
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
    Cloud live session — faithfully mirrors local LivePacingSession.
    Uses Web Audio API + Web Speech API for real-time detection.
    Returns audio bytes when recording stops, else None.
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
  font-size:13px;font-weight:600;text-align:center;margin-bottom:8px;
}}
.phase{{
  font-size:11px;opacity:.75;margin-top:3px;text-align:center;
}}
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

<div class="status" id="st">Click Start Session to begin</div>
<div class="phase" id="ph"></div>

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
// ── Config (mirrors live_session.py) ────────────────────────────────────────
const BPM            = {bpm};
const DROP_RATIO     = {drop_ratio};       // fraction of dynamic range → stutter threshold
const PAUSE_IGNORE   = {pause_ignore_ms}; // ms of sustained low energy before triggering
const AUTO_MET       = {auto_met_js};

// Audio processing
const SMOOTH_K       = 0.92;  // EMA coefficient (mirrors _SMOOTH_WINDOW≈4 → α≈1-1/4)
const AMBIENT_FRAMES = 10;    // ~1 s of 100ms frames  (mirrors _AMBIENT_FRAMES)
const CALIB_FRAMES   = 12;    // speech frames needed   (mirrors _CALIBRATION_FRAMES)
const NOISE_WIN      = 50;    // rolling noise window   (mirrors _NOISE_WINDOW)
const SPEECH_WIN     = 30;    // rolling speech window  (mirrors _SPEECH_WINDOW)
const RECAL_EVERY    = 20;    // frames between recalibrations
const SNR_SPEECH     = 2.0;   // SNR threshold to detect speech onset

// Oscillation detection (mirrors _check_energy_oscillation)
const OSC_WIN_MS     = 1500;  // 1.5 s window
const OSC_MIN        = 4;     // 4+ crossings → syllable stutter

// Word repetition (Web Speech API, mirrors _scan_for_repetitions)
const REP_MIN        = 3;     // 3+ consecutive same word

// Recovery grace (mirrors _RECOVERY_GRACE_SEC)
const GRACE_MS       = 500;

// Metronome min-on / min-off guards (prevents rapid flipping)
const MIN_ON_MS      = 2000;
const MIN_OFF_MS     = 1000;

// ── State ────────────────────────────────────────────────────────────────────
let actx=null, ana=null, stream=null, running=false;

// Phase tracking
const PHASE = {{IDLE:0, AMBIENT:1, WAIT_SPEECH:2, CALIBRATING:3, MONITORING:4}};
let phase=PHASE.IDLE;

// Smoothed RMS
let smooth=0;

// Ambient / noise floor
let ambBuf=[], noiseTracker=[], noiseFloor=0;

// Speech calibration
let calibBuf=[], speechRecent=[];
let eThr=0, rThr=0, midpoint=0;

// Adaptive recalibration
let recalCounter=0;

// Metronome
let metOn=false, cnt=0, t0=null;
let metroTimer=null, nextBeat=0, beatIdx=0;
let metroOnTime=0, metroOffTime=-MIN_OFF_MS;

// Recovery grace
let recovStart=null;

// Phase 3 state
let frameIdx=0;
let lowEnergyStart=null;

// Oscillation detection
let energyCrossings=[], wasAbove=false;
let oscActive=false;

// Word-repetition (Web Speech API)
let recognition=null, repActive=false;
let lastPartialWords=[];

// ── Helpers ──────────────────────────────────────────────────────────────────
function pct(arr, p) {{
  const s=[...arr].sort((a,b)=>a-b);
  return s[Math.floor(s.length*p)]||0;
}}
function mean(arr) {{ return arr.length ? arr.reduce((a,b)=>a+b)/arr.length : 0; }}
function maxOf(arr) {{ return arr.reduce((a,b)=>b>a?b:a, -Infinity); }}

function getNoise() {{
  return Math.max(noiseFloor, 0.0001);
}}

function recalcThresholds() {{
  if(!speechRecent.length) return;
  const recentAvg = mean(speechRecent);
  const noise = getNoise();
  const dynRange = recentAvg - noise;
  if(dynRange <= 0) {{
    eThr = noise * 1.2;
    rThr = noise * 1.5;
  }} else {{
    eThr = noise + dynRange * DROP_RATIO;
    rThr = noise + dynRange * 0.45;
  }}
  midpoint = (eThr + rThr) / 2;
}}

function updateNoise(rms) {{
  noiseTracker.push(rms);
  if(noiseTracker.length > NOISE_WIN) noiseTracker.shift();
  noiseFloor = pct(noiseTracker, 0.30);
}}

function updateSpeech(rms) {{
  speechRecent.push(rms);
  if(speechRecent.length > SPEECH_WIN) speechRecent.shift();
}}

function getSNR(rms) {{
  return noiseFloor > 0 ? rms / noiseFloor : 100;
}}

// ── Start session ────────────────────────────────────────────────────────────
async function startSess() {{
  try {{
    setStatus('Requesting microphone...');
    stream=await navigator.mediaDevices.getUserMedia({{audio:true,video:false}});
    actx=new (window.AudioContext||window.webkitAudioContext)();
    const src=actx.createMediaStreamSource(stream);
    ana=actx.createAnalyser(); ana.fftSize=2048; ana.smoothingTimeConstant=0.0;
    src.connect(ana);

    running=true; smooth=0; t0=Date.now();
    ambBuf=[]; noiseTracker=[]; noiseFloor=0;
    calibBuf=[]; speechRecent=[];
    eThr=0; rThr=0; midpoint=0;
    recalCounter=0; frameIdx=0;
    metOn=false; cnt=0;
    metroOnTime=0; metroOffTime=Date.now()-MIN_OFF_MS;
    recovStart=null;
    lowEnergyStart=null;
    energyCrossings=[]; wasAbove=false; oscActive=false;
    repActive=false; lastPartialWords=[];

    phase=PHASE.AMBIENT;

    document.getElementById('bs').style.display='none';
    document.getElementById('be').style.display='block';
    document.getElementById('mc').classList.remove('on');
    document.getElementById('done').classList.remove('show');
    document.getElementById('ms').textContent='0';
    document.getElementById('mm').textContent='Idle';
    document.getElementById('msnr').textContent='—';

    startSpeechRec();
    loop();
  }} catch(e) {{
    setStatus('Mic error: '+e.message+' — allow mic and retry');
  }}
}}

// ── Main audio loop (100ms per frame via requestAnimationFrame) ───────────────
let lastFrameMs=0;
function loop() {{
  if(!running) return;
  requestAnimationFrame(loop);

  const now=Date.now();
  if(now - lastFrameMs < 80) return; // ~10 fps processing, avoid flooding
  lastFrameMs=now;

  const buf=new Float32Array(ana.frequencyBinCount);
  ana.getFloatTimeDomainData(buf);
  let s=0; for(let i=0;i<buf.length;i++) s+=buf[i]*buf[i];
  const rms=Math.sqrt(s/buf.length);
  smooth = SMOOTH_K*smooth + (1-SMOOTH_K)*rms;

  const el=(now-t0)/1000;
  document.getElementById('mt').textContent=Math.floor(el)+'s';

  frameIdx++;

  // ── PHASE 0: Ambient noise learning (~1 s) ───────────────────────────────
  if(phase === PHASE.AMBIENT) {{
    ambBuf.push(rms);
    noiseTracker.push(rms);
    setStatus('Learning ambient noise… please stay silent ('+(Math.max(1,Math.ceil(1-el)))+'s)');
    setPh('Phase 1/4 — Ambient noise calibration');
    if(ambBuf.length >= AMBIENT_FRAMES) {{
      noiseFloor = pct(noiseTracker, 0.30);
      phase = PHASE.WAIT_SPEECH;
    }}
    return;
  }}

  // ── PHASE 1: Wait for user to start speaking ─────────────────────────────
  if(phase === PHASE.WAIT_SPEECH) {{
    const snr = getSNR(rms);
    document.getElementById('msnr').textContent = snr.toFixed(1)+'×';
    if(snr > SNR_SPEECH && rms > 0.002) {{
      phase = PHASE.CALIBRATING;
      setStatus('Calibrating… keep speaking naturally');
      setPh('Phase 2/4 — Calibrating on your voice');
    }} else {{
      updateNoise(rms);
      setStatus('Listening… start speaking now');
      setPh('Phase 2/4 — Waiting for speech (SNR: '+snr.toFixed(1)+'×)');
    }}
    return;
  }}

  // ── PHASE 2: Calibrate from actual speech ───────────────────────────────
  if(phase === PHASE.CALIBRATING) {{
    const snr = getSNR(rms);
    document.getElementById('msnr').textContent = snr.toFixed(1)+'×';
    if(snr > SNR_SPEECH) calibBuf.push(rms);

    const remain = Math.max(0, CALIB_FRAMES - calibBuf.length);
    setStatus('Calibrating… keep speaking ('+remain+' frames left)');
    setPh('Phase 3/4 — Measuring your speech level');

    if(calibBuf.length >= CALIB_FRAMES) {{
      // Seed recent speech tracker
      speechRecent = [...calibBuf];
      noiseTracker = [...ambBuf, ...noiseTracker.slice(-20)];
      noiseFloor   = pct(noiseTracker, 0.30);
      recalcThresholds();
      phase = PHASE.MONITORING;
      setStatus('Monitoring — metronome auto-starts on stutter');
      setPh('Phase 4/4 — Live monitoring active');
    }}
    return;
  }}

  // ── PHASE 3: Stutter detection ───────────────────────────────────────────
  const snr = getSNR(smooth);
  document.getElementById('msnr').textContent = snr.toFixed(1)+'×';

  // Update noise floor from low-energy frames
  if(smooth < eThr) updateNoise(rms);
  // Update speech level from high-energy frames
  if(smooth > rThr) updateSpeech(rms);

  // Periodic recalibration
  recalCounter++;
  if(recalCounter >= RECAL_EVERY) {{
    recalCounter=0;
    recalcThresholds();
  }}

  // ── Recovery check (runs before detection; mirrors _stop_metronome) ──────
  if(metOn && smooth > rThr) {{
    if(!recovStart) {{
      recovStart = now;  // start grace timer
    }} else if(now - recovStart >= GRACE_MS && now - metroOnTime >= MIN_ON_MS) {{
      stopMetronome('energy_recovery');
    }}
  }} else if(metOn && smooth <= rThr) {{
    recovStart = null;  // reset grace if energy drops again
  }}

  if(metOn) return; // already correcting, skip new triggers

  // ── Mode 1: Energy drop (sustained low energy after speech) ─────────────
  if(smooth < eThr) {{
    if(lowEnergyStart === null) lowEnergyStart = now;
    const lowDur = now - lowEnergyStart;
    if(lowDur >= PAUSE_IGNORE && now - metroOffTime >= MIN_OFF_MS) {{
      triggerMetronome('block');
      return;
    }}
    setStatus('Low energy… ('+Math.floor(lowDur/100)/10+'s / '+PAUSE_IGNORE/1000+'s)');
  }} else {{
    lowEnergyStart = null;
  }}

  // ── Mode 2: Energy oscillation — syllable stuttering (b-b-b-ball) ────────
  const isAbove = smooth > midpoint;
  if(isAbove !== wasAbove) {{
    energyCrossings.push(now);
    wasAbove = isAbove;
  }}
  energyCrossings = energyCrossings.filter(t => now - t < OSC_WIN_MS);

  if(energyCrossings.length >= OSC_MIN) {{
    if(!oscActive && now - metroOffTime >= MIN_OFF_MS) {{
      oscActive = true;
      triggerMetronome('syllable_stutter');
      return;
    }}
  }} else {{
    if(oscActive && energyCrossings.length <= 1) oscActive = false;
  }}
}}

// ── Mode 3: Word repetition via Web Speech API ────────────────────────────
function startSpeechRec() {{
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if(!SR) return;
  recognition = new SR();
  recognition.lang = 'en-US';
  recognition.continuous = true;
  recognition.interimResults = true;

  recognition.onresult = (e) => {{
    if(!running || phase !== PHASE.MONITORING) return;
    let partial = '';
    for(let i=e.resultIndex; i<e.results.length; i++) {{
      if(!e.results[i].isFinal) partial += e.results[i][0].transcript;
    }}
    const words = partial.trim().toLowerCase().split(/\\s+/).filter(w=>w);
    if(words.length < REP_MIN) return;
    if(words.length === lastPartialWords.length) return;
    lastPartialWords = words;
    scanRepetitions(words);
  }};

  recognition.onend = () => {{ if(running) recognition.start(); }};
  recognition.onerror = () => {{ if(running) setTimeout(()=>recognition.start(), 500); }};
  try {{ recognition.start(); }} catch(e) {{}}
}}

function scanRepetitions(words) {{
  // Count consecutive same word at end of partial (mirrors _scan_for_repetitions)
  let consec = 1;
  for(let i=words.length-1; i>0; i--) {{
    if(words[i]===words[i-1]) consec++;
    else break;
  }}
  const now = Date.now();
  if(consec >= REP_MIN && !repActive && !metOn && now - metroOffTime >= MIN_OFF_MS) {{
    repActive = true;
    triggerMetronome('repetition', words[words.length-1], consec);
    return;
  }}
  // Recovery: 3+ unique words
  if(repActive) {{
    let unique=1;
    for(let i=words.length-1;i>0;i--) {{
      if(words[i]!==words[i-1]) {{ unique++; if(unique>=3) break; }}
      else break;
    }}
    if(unique >= 3) {{
      repActive=false;
      if(metOn) stopMetronome('fluent_recovery');
    }}
  }}
}}

// ── Trigger / stop metronome ─────────────────────────────────────────────────
function triggerMetronome(type, word, count) {{
  if(!AUTO_MET || metOn) return;
  metOn=true; cnt++;
  metroOnTime=Date.now();
  recovStart=null; lowEnergyStart=null;
  oscActive=true; energyCrossings=[];

  startMetro();
  document.getElementById('ms').textContent=cnt;
  document.getElementById('mm').textContent='ACTIVE';
  const labels={{block:'Block detected',syllable_stutter:'Syllable stutter',repetition:'Repetition detected'}};
  const winfo = word ? ` ("${{word}}" ×${{count}})` : '';
  setStatus((labels[type]||'Stutter')+winfo+' — follow the metronome!');
  document.getElementById('metroType').textContent=(labels[type]||'Stutter')+' — follow the rhythm';
  document.getElementById('mc').classList.add('on');
  setPh('🔴 Stutter event #'+cnt);
}}

function stopMetronome(reason) {{
  if(!metOn) return;
  metOn=false;
  metroOffTime=Date.now();
  recovStart=null; oscActive=false; repActive=false;
  clearTimeout(metroTimer);
  document.querySelectorAll('.dot').forEach(d=>d.classList.remove('on'));
  document.getElementById('mc').classList.remove('on');
  document.getElementById('mm').textContent='Idle';
  setStatus('Monitoring — metronome auto-starts on stutter');
  setPh('Phase 4/4 — Live monitoring active');
}}

// ── Metronome scheduler (Web Audio, mirrors _start_metronome) ────────────────
function startMetro() {{
  beatIdx=0; nextBeat=actx.currentTime+0.05; sched();
}}

function sched() {{
  if(!metOn) return;
  while(nextBeat < actx.currentTime+0.12) {{
    click(nextBeat, beatIdx%4===0);
    const d=(nextBeat-actx.currentTime)*1000;
    const i=beatIdx%4;
    setTimeout(()=>flash(i), Math.max(0,d));
    nextBeat += 60/BPM; beatIdx++;
  }}
  metroTimer=setTimeout(sched,40);
}}

function click(t,acc) {{
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
  try {{ if(recognition) recognition.stop(); }} catch(e) {{}}
  document.getElementById('be').style.display='none';
  document.getElementById('bs').style.display='block';
  document.getElementById('bs').textContent='🔄 New Session';
  setStatus('Session complete — '+cnt+' stutter event(s) detected');
  document.getElementById('mm').textContent=cnt?cnt+' events':'None';
  document.getElementById('mc').classList.remove('on');
  document.getElementById('done').classList.add('show');
  setPh('');
}}

function setStatus(msg) {{ document.getElementById('st').textContent=msg; }}
function setPh(msg)     {{ document.getElementById('ph').textContent=msg; }}
</script></body></html>
"""

    components.html(html, height=400, scrolling=False)

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
