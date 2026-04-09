"""
Browser-based live session for NeuroNudge cloud deployment.
Mirrors modules/live_session.py (LivePacingSession) in JavaScript.

KEY FIX: The EMA smoother (α=0.92, τ≈1.2s) is too slow to track individual
word humps (200–400 ms each). Mode 2 and Mode 3 now use RAW instantaneous
RMS for crossing detection so every word-energy peak registers immediately.
The heavy EMA is kept only for Mode 1 (sustained energy-drop / block detection).

Detection modes:
  Mode 1 — Block        : heavy-EMA energy drops below eThr for PAUSE_IGNORE ms
  Mode 2 — Syllable     : raw RMS crosses oscMid 4+ times in 1.5 s  (b-b-b)
  Mode 3 — Word repeat  : raw RMS crosses wrepMid 5+ rhythmically in 4 s (the-the-the)
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
    Cloud live session using Web Audio API.
    Returns audio bytes (from st.audio_input) when recording stops, else None.
    """
    sens = {
        "Low":    {"drop_ratio": 0.35, "pause_ignore_ms": 2000},
        "Medium": {"drop_ratio": 0.30, "pause_ignore_ms": 1500},
        "High":   {"drop_ratio": 0.25, "pause_ignore_ms": 1000},
    }
    cfg             = sens.get(sensitivity, sens["Medium"])
    drop_ratio      = cfg["drop_ratio"]
    pause_ignore_ms = cfg["pause_ignore_ms"]
    auto_met_js     = "true" if auto_metronome else "false"

    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:'Segoe UI',sans-serif;background:#f8faf9;padding:10px;}}
.status{{background:linear-gradient(135deg,#0f5132,#1a7a4a);color:white;
  border-radius:10px;padding:9px 14px;font-size:13px;font-weight:600;
  text-align:center;margin-bottom:4px;}}
.phase{{font-size:11px;color:#6b7b8d;text-align:center;margin-bottom:8px;min-height:16px;}}
.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:8px;}}
.m{{background:#f0f7f3;border-radius:8px;padding:8px;text-align:center;}}
.mv{{font-size:20px;font-weight:800;color:#0f5132;}}
.ml{{font-size:10px;color:#6b7b8d;margin-top:2px;}}
.metro{{background:linear-gradient(135deg,#0f5132,#1a7a4a);border-radius:10px;
  padding:10px 14px;color:white;text-align:center;margin-bottom:8px;display:none;}}
.metro.on{{display:block;}}
.mbpm{{font-size:32px;font-weight:800;line-height:1;}}
.msub{{font-size:11px;opacity:0.8;}}
.beats{{margin:6px 0 3px;}}
.dot{{width:13px;height:13px;border-radius:50%;background:rgba(255,255,255,0.25);
  display:inline-block;margin:0 3px;transition:background .05s,transform .05s;}}
.dot.on{{background:#7fffd4;transform:scale(1.4);}}
.btns{{display:flex;gap:8px;}}
button{{border:none;border-radius:8px;padding:10px;font-size:13px;
  font-weight:700;cursor:pointer;transition:all .15s;flex:1;}}
.bstart{{background:#0f5132;color:white;}}
.bstart:hover{{background:#1a7a4a;}}
.bstop{{background:#dc2626;color:white;display:none;}}
.bstop:hover{{background:#b91c1c;}}
.done{{background:#e9f5ee;border-radius:8px;padding:8px;font-size:12px;
  color:#0f5132;margin-top:8px;display:none;text-align:center;font-weight:600;}}
.done.show{{display:block;}}
</style></head><body>

<div class="status" id="st">Click Start Session to begin</div>
<div class="phase"  id="ph"></div>

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
// ── Config ────────────────────────────────────────────────────────────────────
const BPM          = {bpm};
const DROP_RATIO   = {drop_ratio};
const PAUSE_IGNORE = {pause_ignore_ms};
const AUTO_MET     = {auto_met_js};

// Three smoothing levels — mirrors live_session.py philosophy:
//   SLOW_K (0.92, τ≈1.2 s) : Mode 1 — sustained energy-drop blocks
//   MID_K  (0.60, τ≈140ms) : Mode 2 — syllable oscillations (mirrors Python 4-frame SMA)
//   FAST_K (0.30, τ≈80ms)  : Mode 3 — word-level humps (fast but not raw noise)
const SLOW_K = 0.92;
const MID_K  = 0.60;
const FAST_K = 0.30;

// Calibration
const AMBIENT_FRAMES = 10;
const CALIB_FRAMES   = 10;   // slightly lower = faster calibration
const NOISE_WIN      = 50;
const SPEECH_WIN     = 30;
const RECAL_EVERY    = 20;
const SNR_THRESH     = 2.0;

// Mode 2 — Syllable stutter (b-b-b) — uses raw RMS
const OSC_WIN_MS   = 1500;
const OSC_MIN      = 4;

// Mode 3 — Word repetition (the-the-the) — uses raw RMS
// Each repeated word = 1 up-crossing + 1 down-crossing
// 3 repetitions → 5+ crossings in a 4-second window, evenly spaced
const WREP_WIN_MS  = 4000;
const WREP_MIN     = 5;       // 5 crossings ≈ 2.5 word repetitions (catches fast stutters)
const WREP_MIN_GAP = 80;      // ms — crossing debounce (no faster than 80 ms)
const WREP_AVG_MIN = 120;     // ms — average gap must be ≥ 120 ms (real words)
const WREP_AVG_MAX = 1000;    // ms — average gap must be ≤ 1000 ms
const WREP_RHYTHM  = 0.80;    // rhythmicity: (gMax-gMin)/gAvg < this

// Recovery & metronome guards
const GRACE_MS     = 500;
const MIN_ON_MS    = 2000;
const MIN_OFF_MS   = 1000;

// Speech-context guard — prevents natural pauses triggering the metronome.
// Modes 1/2 only fire if speech was active within MAX_SPEECH_GAP ms.
// Mode 3 allows a slightly longer look-back (repetitions can have brief gaps).
const MAX_SPEECH_GAP      = 600;   // ms — block/syllable
const MAX_SPEECH_GAP_WREP = 1200;  // ms — word-repetition (words may be slow)

// ── State ─────────────────────────────────────────────────────────────────────
let actx=null, ana=null, stream=null, running=false;
let phase=0; // 0=IDLE 1=AMBIENT 2=WAIT_SPEECH 3=CALIBRATING 4=MONITORING
let t0=null, lastFrameMs=0, frameIdx=0;

// Signal — three smoothing levels
let smooth=0;      // heavy EMA  (Mode 1)
let smoothMid=0;   // medium EMA (Mode 2 syllable)
let smoothFast=0;  // fast EMA   (Mode 3 word-rep)
let rms=0;         // raw instantaneous (used only for noise floor updates)

// Noise / calibration
let ambBuf=[], noiseTracker=[], noiseFloor=0;
let calibBuf=[], speechRecent=[];
let eThr=0, rThr=0, oscMid=0, wrepMid=0;
let recalCounter=0;

// Metronome
let metOn=false, cnt=0;
let metroTimer=null, nextBeat=0, beatIdx=0;
let metroOnTime=0, metroOffTime=0, recovStart=null;

// Mode 1
let lowEnergyStart=null;

// Speech-context tracking (mirrors lastSpeechTime in live_session.py)
let lastSpeechTime=0;

// Mode 2 — syllable oscillation (raw RMS)
let oscCrossings=[], lastOscAbove=null, oscActive=false;

// Mode 3 — word repetition (raw RMS, with crossing debounce)
let wrepCrossings=[], lastWrepAbove=null, wrepActive=false, lastWrepCrossTime=0;

// ── Helpers ───────────────────────────────────────────────────────────────────
function pct(arr,p){{const s=[...arr].sort((a,b)=>a-b);return s[Math.floor(s.length*p)]||0;}}
function mean(arr){{return arr.length?arr.reduce((a,b)=>a+b)/arr.length:0;}}
function setStatus(m){{document.getElementById('st').textContent=m;}}
function setPh(m)    {{document.getElementById('ph').textContent=m;}}

function updateNoise(v){{
  noiseTracker.push(v);
  if(noiseTracker.length>NOISE_WIN) noiseTracker.shift();
  noiseFloor=pct(noiseTracker,0.30);
}}
function updateSpeech(v){{
  speechRecent.push(v);
  if(speechRecent.length>SPEECH_WIN) speechRecent.shift();
}}
function getSNR(v){{return noiseFloor>0?v/noiseFloor:100;}}

function recalc(){{
  if(!speechRecent.length) return;
  const avg=mean(speechRecent), noise=Math.max(noiseFloor,0.0001);
  const dyn=avg-noise;
  if(dyn<=0){{eThr=noise*1.2; rThr=noise*1.5;}}
  else      {{eThr=noise+dyn*DROP_RATIO; rThr=noise+dyn*0.45;}}
  oscMid  = (eThr+rThr)/2;         // midpoint for syllable crossing (~37% of range)
  wrepMid = noise+dyn*0.18;        // lower midpoint — catches individual word humps
                                    // For raw RMS: word energy >> wrepMid > gap energy
}}

// ── Start session ─────────────────────────────────────────────────────────────
async function startSess(){{
  try{{
    setStatus('Requesting microphone…');
    stream=await navigator.mediaDevices.getUserMedia({{audio:true,video:false}});
    actx=new (window.AudioContext||window.webkitAudioContext)();
    const src=actx.createMediaStreamSource(stream);
    ana=actx.createAnalyser(); ana.fftSize=2048; ana.smoothingTimeConstant=0.0;
    src.connect(ana);

    running=true; smooth=0; rms=0; t0=Date.now(); lastFrameMs=0; frameIdx=0;
    ambBuf=[]; noiseTracker=[]; noiseFloor=0;
    calibBuf=[]; speechRecent=[];
    eThr=0; rThr=0; oscMid=0; wrepMid=0; recalCounter=0;
    metOn=false; cnt=0;
    metroOnTime=0; metroOffTime=Date.now()-MIN_OFF_MS; recovStart=null;
    smooth=0; smoothMid=0; smoothFast=0; rms=0;
    lowEnergyStart=null; lastSpeechTime=0;
    oscCrossings=[]; lastOscAbove=null; oscActive=false;
    wrepCrossings=[]; lastWrepAbove=null; wrepActive=false; lastWrepCrossTime=0;
    phase=1;

    document.getElementById('bs').style.display='none';
    document.getElementById('be').style.display='block';
    document.getElementById('mc').classList.remove('on');
    document.getElementById('done').classList.remove('show');
    document.getElementById('ms').textContent='0';
    document.getElementById('mm').textContent='Idle';
    document.getElementById('msnr').textContent='—';
    loop();
  }}catch(e){{setStatus('Mic error: '+e.message);}}
}}

// ── Main loop (~10 fps) ───────────────────────────────────────────────────────
function loop(){{
  if(!running) return;
  requestAnimationFrame(loop);
  const now=Date.now();
  if(now-lastFrameMs<80) return;
  lastFrameMs=now; frameIdx++;

  const buf=new Float32Array(ana.frequencyBinCount);
  ana.getFloatTimeDomainData(buf);
  let s=0; for(let i=0;i<buf.length;i++) s+=buf[i]*buf[i];
  rms      = Math.sqrt(s/buf.length);
  smooth    = SLOW_K*smooth    + (1-SLOW_K)*rms;   // Mode 1 — heavy
  smoothMid = MID_K *smoothMid + (1-MID_K) *rms;   // Mode 2 — medium (mirrors Python 4-frame SMA)
  smoothFast= FAST_K*smoothFast+ (1-FAST_K)*rms;   // Mode 3 — fast

  const el=(now-t0)/1000;
  document.getElementById('mt').textContent=Math.floor(el)+'s';

  // ── Phase 1: Ambient (~1 s) ──────────────────────────────────────────────
  if(phase===1){{
    ambBuf.push(rms); updateNoise(rms);
    const rem=Math.max(0,Math.ceil(1-el));
    setStatus('Learning ambient noise… stay silent ('+rem+'s)');
    setPh('Step 1/4 — Ambient calibration');
    if(ambBuf.length>=AMBIENT_FRAMES) phase=2;
    return;
  }}

  // ── Phase 2: Wait for speech ─────────────────────────────────────────────
  if(phase===2){{
    const snr=getSNR(rms);
    document.getElementById('msnr').textContent=snr.toFixed(1)+'×';
    if(snr>SNR_THRESH && rms>0.002){{
      phase=3;
      setStatus('Calibrating… keep speaking naturally');
      setPh('Step 2/4 — Measuring your voice level');
    }}else{{
      updateNoise(rms);
      setStatus('Listening… start speaking now');
      setPh('Step 2/4 — Waiting for speech (SNR '+snr.toFixed(1)+'×)');
    }}
    return;
  }}

  // ── Phase 3: Calibrate ───────────────────────────────────────────────────
  if(phase===3){{
    const snr=getSNR(rms);
    document.getElementById('msnr').textContent=snr.toFixed(1)+'×';
    if(snr>SNR_THRESH){{calibBuf.push(rms); updateSpeech(rms);}}
    const rem=Math.max(0,CALIB_FRAMES-calibBuf.length);
    setStatus('Calibrating… ('+rem+' frames left, speak naturally)');
    setPh('Step 3/4 — Computing thresholds');
    if(calibBuf.length>=CALIB_FRAMES){{
      noiseFloor=pct(noiseTracker,0.30); recalc();
      phase=4;
      setStatus('Monitoring — metronome auto-starts on stutter');
      setPh('Step 4/4 — Live stutter detection active ✓');
    }}
    return;
  }}

  // ── Phase 4: MONITORING ──────────────────────────────────────────────────
  document.getElementById('msnr').textContent=getSNR(smooth).toFixed(1)+'×';

  // Adaptive trackers
  if(smooth<eThr) updateNoise(rms);
  if(smooth>rThr) updateSpeech(rms);
  if(++recalCounter>=RECAL_EVERY){{recalCounter=0; recalc();}}

  // Track last active speech moment (energy clearly above noise)
  // This is the key guard against natural pauses triggering the metronome.
  if(smooth > rThr*0.7) lastSpeechTime=now;

  const speechWasRecent     = lastSpeechTime>0 && (now-lastSpeechTime)<MAX_SPEECH_GAP;
  const speechWasRecentWrep = lastSpeechTime>0 && (now-lastSpeechTime)<MAX_SPEECH_GAP_WREP;

  // If not speaking recently, clear accumulated crossing data so stale
  // crossings from before the pause don't combine with post-pause crossings.
  if(!speechWasRecent) {{
    lowEnergyStart=null;
    oscCrossings=[]; oscActive=false;
  }}
  if(!speechWasRecentWrep) {{
    wrepCrossings=[]; wrepActive=false;
  }}

  // ── Recovery (before new triggers) ───────────────────────────────────────
  if(metOn){{
    if(smooth>rThr){{
      if(!recovStart) recovStart=now;
      else if(now-recovStart>=GRACE_MS && now-metroOnTime>=MIN_ON_MS)
        stopMetro('energy_recovery');
    }}else recovStart=null;
    return; // don't try new triggers while correcting
  }}

  // ── Mode 1: Energy-drop block ─────────────────────────────────────────────
  // ONLY fires when speech was active within MAX_SPEECH_GAP ms.
  // Natural pauses, full stops, and end-of-sentence silence are excluded.
  if(smooth<eThr && speechWasRecent){{
    if(!lowEnergyStart) lowEnergyStart=now;
    if(now-lowEnergyStart>=PAUSE_IGNORE && now-metroOffTime>=MIN_OFF_MS){{
      trigger('block'); return;
    }}
  }}else lowEnergyStart=null;

  // ── Mode 2: Syllable stutter — smoothMid crossings at oscMid ───────────────
  // Uses medium EMA (K=0.6, τ≈140ms) — mirrors Python's 4-frame rolling average.
  // Inter-word gaps in fluent speech (50-100ms) don't drop smoothMid below oscMid.
  // Stutter gaps (200ms+) do → produces crossings only on real b-b-b stutters.
  const aboveOsc=(smoothMid>oscMid);
  if(speechWasRecent && lastOscAbove!==null && aboveOsc!==lastOscAbove) oscCrossings.push(now);
  lastOscAbove=aboveOsc;
  oscCrossings=oscCrossings.filter(t=>now-t<OSC_WIN_MS);
  if(oscCrossings.length>=OSC_MIN && !oscActive && now-metroOffTime>=MIN_OFF_MS){{
    oscActive=true; trigger('syllable_stutter'); return;
  }}
  if(oscActive && oscCrossings.length<=1) oscActive=false;

  // ── Mode 3: Word repetition — smoothFast crossings at wrepMid ───────────────
  // Uses fast EMA (K=0.3, τ≈80ms) — fast enough to track individual word humps
  // (200-400ms each) but smoother than raw RMS so within-frame noise is filtered.
  const aboveWrep=(smoothFast>wrepMid);
  if(speechWasRecentWrep && lastWrepAbove!==null && aboveWrep!==lastWrepAbove){{
    if(now-lastWrepCrossTime>WREP_MIN_GAP){{
      wrepCrossings.push(now);
      lastWrepCrossTime=now;
    }}
  }}
  lastWrepAbove=aboveWrep;
  wrepCrossings=wrepCrossings.filter(t=>now-t<WREP_WIN_MS);

  if(wrepCrossings.length>=WREP_MIN){{
    const gaps=[];
    for(let i=1;i<wrepCrossings.length;i++) gaps.push(wrepCrossings[i]-wrepCrossings[i-1]);
    const a=mean(gaps), gMax=Math.max(...gaps), gMin=Math.min(...gaps);
    const rhythmic=(gMax-gMin)<a*WREP_RHYTHM;
    if(a>=WREP_AVG_MIN && a<=WREP_AVG_MAX && rhythmic && now-metroOffTime>=MIN_OFF_MS){{
      wrepActive=true; trigger('repetition'); wrepCrossings=[]; return;
    }}
  }}
  if(wrepActive && smooth>rThr) wrepActive=false;
}}

// ── Trigger / Stop ────────────────────────────────────────────────────────────
function trigger(type){{
  if(!AUTO_MET||metOn) return;
  metOn=true; cnt++;
  metroOnTime=Date.now(); recovStart=null; lowEnergyStart=null;
  oscCrossings=[]; wrepCrossings=[]; oscActive=true;
  startMetro();
  document.getElementById('ms').textContent=cnt;
  document.getElementById('mm').textContent='ACTIVE';
  const lab={{block:'Block detected',syllable_stutter:'Syllable stutter',repetition:'Word repetition detected ×3'}};
  setStatus((lab[type]||'Stutter detected')+' — follow the metronome!');
  document.getElementById('metroType').textContent=(lab[type]||'Stutter')+' — follow the rhythm';
  document.getElementById('mc').classList.add('on');
  setPh('🔴 Stutter event #'+cnt);
}}

function stopMetro(reason){{
  if(!metOn) return;
  metOn=false; metroOffTime=Date.now(); recovStart=null;
  oscActive=false; wrepActive=false;
  clearTimeout(metroTimer);
  document.querySelectorAll('.dot').forEach(d=>d.classList.remove('on'));
  document.getElementById('mc').classList.remove('on');
  document.getElementById('mm').textContent='Idle';
  setStatus('Monitoring — metronome auto-starts on stutter');
  setPh('Step 4/4 — Live stutter detection active ✓');
}}

// ── Metronome (Web Audio precise scheduling) ──────────────────────────────────
function startMetro(){{beatIdx=0; nextBeat=actx.currentTime+0.05; sched();}}
function sched(){{
  if(!metOn) return;
  while(nextBeat<actx.currentTime+0.12){{
    click(nextBeat,beatIdx%4===0);
    const d=(nextBeat-actx.currentTime)*1000, i=beatIdx%4;
    setTimeout(()=>flash(i),Math.max(0,d));
    nextBeat+=60/BPM; beatIdx++;
  }}
  metroTimer=setTimeout(sched,40);
}}
function click(t,acc){{
  const o=actx.createOscillator(),g=actx.createGain();
  o.connect(g); g.connect(actx.destination);
  o.frequency.value=acc?1000:880;
  g.gain.setValueAtTime(acc?0.5:0.3,t);
  g.gain.exponentialRampToValueAtTime(0.001,t+0.04);
  o.start(t); o.stop(t+0.045);
}}
function flash(i){{document.querySelectorAll('.dot').forEach((d,j)=>d.classList.toggle('on',j===i));}}

// ── Stop session ──────────────────────────────────────────────────────────────
function stopSess(){{
  running=false; metOn=false; clearTimeout(metroTimer);
  document.querySelectorAll('.dot').forEach(d=>d.classList.remove('on'));
  if(stream) stream.getTracks().forEach(t=>t.stop());
  document.getElementById('be').style.display='none';
  document.getElementById('bs').style.display='block';
  document.getElementById('bs').textContent='🔄 New Session';
  setStatus('Session complete — '+cnt+' stutter event(s) detected');
  document.getElementById('mm').textContent=cnt?cnt+' events':'None';
  document.getElementById('mc').classList.remove('on');
  document.getElementById('done').classList.add('show');
  setPh('');
}}
</script></body></html>
"""

    components.html(html, height=415, scrolling=False)

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
