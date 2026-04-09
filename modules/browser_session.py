"""
Browser-based live session for NeuroNudge cloud deployment.

Direct JavaScript port of modules/live_session.py LivePacingSession.
Every constant and algorithm mirrors the Python source exactly.

Python → JS mapping:
  _energy_buffer (SMA-4)     → smaBuffer[4]          getSMA(rms)
  _noise_tracker (50 frames) → noiseTracker[50]       updateNoise()
  _recent_speech (30 frames) → speechBuf[30]          updateSpeech()
  _noise_floor               → noiseFloor             pct(30th %)
  energy_threshold           → eThr
  recovery_threshold         → rThr
  _low_energy_start          → lowEnergyStart
  _energy_crossings          → energyCrossings
  _was_above_threshold       → wasAbove
  _oscillation_active        → oscActive
  _recovery_start            → recovStart
  _OSCILLATION_WINDOW=1.5s   → OSC_WIN_MS=1500
  _OSCILLATION_MIN=4         → OSC_MIN=4
  _RECOVERY_GRACE_SEC=0.5    → GRACE_MS=500
  _CALIBRATION_FRAMES=12     → CALIB_FRAMES=12
  _AMBIENT_FRAMES=10         → AMBIENT_FRAMES=10
  recal_counter (every 20)   → recalCounter (every 20)
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
    Cloud live session — direct JS port of LivePacingSession.
    Returns audio bytes when recording stops, else None.
    """
    # Exact values from live_session.py _sens_config
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
  ✅ Session done — stop the mic recorder below to run analysis.
</div>

<script>
// ── Constants (mirrors live_session.py exactly) ───────────────────────────────
const BPM          = {bpm};
const DROP_RATIO   = {drop_ratio};         // _drop_ratio
const PAUSE_IGNORE = {pause_ignore_ms};    // _pause_ignore_sec (ms)
const AUTO_MET     = {auto_met_js};

const SMA_WIN        = 4;    // _SMOOTH_WINDOW = 4
const AMBIENT_FRAMES = 10;   // _AMBIENT_FRAMES = 10
const CALIB_FRAMES   = 12;   // _CALIBRATION_FRAMES = 12
const NOISE_WIN      = 50;   // _NOISE_WINDOW = 50
const SPEECH_WIN     = 30;   // _SPEECH_WINDOW = 30
const RECAL_EVERY    = 20;   // recal_counter threshold
const SNR_THRESH     = 2.0;  // speech_snr_thresh = 2.0

const OSC_WIN_MS  = 1500;    // _OSCILLATION_WINDOW = 1.5 s
const OSC_MIN     = 4;       // _OSCILLATION_MIN = 4
const GRACE_MS    = 500;     // _RECOVERY_GRACE_SEC = 0.5 s

// ── State ─────────────────────────────────────────────────────────────────────
let actx=null, ana=null, stream=null, running=false;
let phase=0;   // 0=IDLE 1=AMBIENT 2=WAIT_SPEECH 3=CALIBRATING 4=MONITORING
let t0=null, lastFrameMs=0;

// Signal — getSMA() mirrors _smoothed_energy()
let smaBuf=[];   // _energy_buffer
let rms=0;

// Noise / speech trackers (mirrors _noise_tracker, _recent_speech)
let noiseTracker=[], speechBuf=[], noiseFloor=0;
let eThr=0, rThr=0;   // energy_threshold, recovery_threshold

// Calibration
let ambBuf=[], calibBuf=[], recalCounter=0, calibrated=false;

// Metronome
let metOn=false, cnt=0;
let metroTimer=null, nextBeat=0, beatIdx=0;

// Mode 1 — energy drop (_low_energy_start)
let lowEnergyStart=null;

// Mode 3 — oscillation (_energy_crossings, _was_above_threshold, _oscillation_active)
let energyCrossings=[], wasAbove=false, oscActive=false;

// Recovery (_recovery_start)
let recovStart=null;

// ── Helpers ───────────────────────────────────────────────────────────────────
// mirrors _smoothed_energy()
function getSMA(r){{
  smaBuf.push(r);
  if(smaBuf.length>SMA_WIN) smaBuf.shift();
  return smaBuf.reduce((a,b)=>a+b)/smaBuf.length;
}}

// mirrors _update_noise_floor()
function updateNoise(r){{
  noiseTracker.push(r);
  if(noiseTracker.length>NOISE_WIN) noiseTracker.shift();
  const s=[...noiseTracker].sort((a,b)=>a-b);
  noiseFloor=s[Math.floor(s.length*0.30)]||0;
}}

// mirrors _update_speech_level()
function updateSpeech(r){{
  speechBuf.push(r);
  if(speechBuf.length>SPEECH_WIN) speechBuf.shift();
}}

// mirrors _get_snr()
function getSNR(v){{return noiseFloor>0?v/noiseFloor:100;}}

// mirrors _recalculate_thresholds()
function recalc(){{
  if(!speechBuf.length) return;
  const avg=speechBuf.reduce((a,b)=>a+b)/speechBuf.length;
  const noise=Math.max(noiseFloor,0.0001);
  const dyn=avg-noise;
  if(dyn<=0){{eThr=noise*1.2; rThr=noise*1.5;}}
  else      {{eThr=noise+dyn*DROP_RATIO; rThr=noise+dyn*0.45;}}
}}

function setStatus(m){{document.getElementById('st').textContent=m;}}
function setPh(m)    {{document.getElementById('ph').textContent=m;}}

// ── Start ─────────────────────────────────────────────────────────────────────
async function startSess(){{
  try{{
    setStatus('Requesting microphone…');
    stream=await navigator.mediaDevices.getUserMedia({{audio:true,video:false}});
    actx=new (window.AudioContext||window.webkitAudioContext)();
    const src=actx.createMediaStreamSource(stream);
    ana=actx.createAnalyser(); ana.fftSize=2048; ana.smoothingTimeConstant=0.0;
    src.connect(ana);

    running=true; t0=Date.now(); lastFrameMs=0;
    smaBuf=[]; rms=0;
    ambBuf=[]; calibBuf=[]; noiseTracker=[]; speechBuf=[]; noiseFloor=0;
    eThr=0; rThr=0; recalCounter=0; calibrated=false;
    metOn=false; cnt=0;
    lowEnergyStart=null;
    energyCrossings=[]; wasAbove=false; oscActive=false; recovStart=null;
    phase=1;

    document.getElementById('bs').style.display='none';
    document.getElementById('be').style.display='block';
    document.getElementById('mc').classList.remove('on');
    document.getElementById('done').classList.remove('show');
    document.getElementById('ms').textContent='0';
    document.getElementById('mm').textContent='Idle';
    document.getElementById('msnr').textContent='—';
    loop();
  }}catch(e){{setStatus('Mic error: '+e.message+' — allow mic access and retry');}}
}}

// ── Main loop (100 ms per frame, mirrors block_size=1600 @ 16kHz) ─────────────
function loop(){{
  if(!running) return;
  requestAnimationFrame(loop);
  const now=Date.now();
  if(now-lastFrameMs<90) return;   // ~100ms frames
  lastFrameMs=now;

  // Compute RMS for this frame
  const buf=new Float32Array(ana.frequencyBinCount);
  ana.getFloatTimeDomainData(buf);
  let s=0; for(let i=0;i<buf.length;i++) s+=buf[i]*buf[i];
  rms=Math.sqrt(s/buf.length);

  // Update elapsed time display
  const el=(now-t0)/1000;
  document.getElementById('mt').textContent=Math.floor(el)+'s';

  // ── PHASE 0: Ambient noise (mirrors frame_idx <= AMBIENT_FRAMES) ──────────
  if(phase===1){{
    ambBuf.push(rms); updateNoise(rms);
    const rem=Math.max(0,Math.ceil(1-el));
    setStatus('Learning ambient noise… stay silent ('+rem+'s)');
    setPh('Phase 1/4 — Ambient calibration');
    if(ambBuf.length>=AMBIENT_FRAMES){{
      noiseFloor=noiseTracker.slice().sort((a,b)=>a-b)[Math.floor(noiseTracker.length*0.3)]||0;
      phase=2;
    }}
    return;
  }}

  // ── PHASE 1: Wait for speech (mirrors _user_has_spoken check) ────────────
  if(phase===2){{
    const snr=getSNR(rms);
    document.getElementById('msnr').textContent=snr.toFixed(1)+'×';
    if(snr>SNR_THRESH && rms>0.002){{
      phase=3;
      setStatus('Calibrating… keep speaking naturally');
      setPh('Phase 2/4 — Measuring your voice level');
    }}else{{
      updateNoise(rms);
      setStatus('Listening… start speaking now');
      setPh('Phase 2/4 — Waiting for speech (SNR: '+snr.toFixed(1)+'×)');
    }}
    return;
  }}

  // ── PHASE 2: Calibrate (mirrors _calibrated check) ────────────────────────
  if(phase===3){{
    const snr=getSNR(rms);
    document.getElementById('msnr').textContent=snr.toFixed(1)+'×';
    if(snr>SNR_THRESH) calibBuf.push(rms);
    const rem=Math.max(0,CALIB_FRAMES-calibBuf.length);
    setStatus('Calibrating… ('+rem+' frames left, keep speaking)');
    setPh('Phase 3/4 — Computing thresholds');
    if(calibBuf.length>=CALIB_FRAMES){{
      // Mirror lines 379-400 of live_session.py
      const avg=calibBuf.reduce((a,b)=>a+b)/calibBuf.length;
      speechBuf=[...calibBuf];
      const noise=Math.max(noiseFloor,0.0001);
      const dyn=avg-noise;
      if(dyn<=0){{eThr=noise*1.2; rThr=noise*1.5;}}
      else      {{eThr=noise+dyn*DROP_RATIO; rThr=noise+dyn*0.45;}}
      calibrated=true; smaBuf=[]; wasAbove=false;
      phase=4;
      setStatus('Monitoring — metronome auto-starts on stutter');
      setPh('Phase 4/4 — Live detection active ✓');
    }}
    return;
  }}

  // ── PHASE 3: Stutter detection (mirrors lines 429-476 of live_session.py) ──

  // _smoothed_energy(rms) — 4-frame SMA
  const smoothed=getSMA(rms);
  document.getElementById('msnr').textContent=getSNR(smoothed).toFixed(1)+'×';

  // Continuously track noise floor from low-energy frames (line 432-433)
  if(smoothed<eThr) updateNoise(rms);

  // Track speech energy from high-energy frames (line 436-437)
  if(smoothed>rThr) updateSpeech(rms);

  // Periodically re-calculate thresholds (lines 441-444)
  recalCounter++;
  if(recalCounter>=RECAL_EVERY){{recalCounter=0; recalc();}}

  // ── Detection Mode 1: Energy drop (lines 447-466) ────────────────────────
  if(smoothed<eThr){{
    if(!lowEnergyStart) lowEnergyStart=now;
    const lowDur=now-lowEnergyStart;
    if(lowDur>=PAUSE_IGNORE){{
      triggerMetronome('energy_drop');
    }}
  }}else{{
    // Energy above stutter threshold
    if(smoothed>rThr){{
      // Mirrors: self._stop_metronome(elapsed, 'energy_recovery')
      tryStop();
    }}
    lowEnergyStart=null;   // Reset low-energy timer
  }}

  // ── Detection Mode 3: Energy oscillation (lines 472-476) ─────────────────
  // Mirrors _check_energy_oscillation(smoothed, elapsed)
  checkOscillation(smoothed, now);
}}

// mirrors _check_energy_oscillation()
function checkOscillation(smoothed, now){{
  if(!calibrated) return;

  // "Use midpoint between noise floor and speech average as crossing line"
  const midpoint=(eThr+rThr)/2;
  const isAbove=(smoothed>midpoint);

  // "Detect threshold crossing (above→below or below→above)"
  if(isAbove!==wasAbove){{
    energyCrossings.push(now);
    wasAbove=isAbove;
  }}

  // "Trim old crossings outside the window"
  energyCrossings=energyCrossings.filter(t=>now-t<OSC_WIN_MS);

  const count=energyCrossings.length;

  if(count>=OSC_MIN){{
    // "4+ crossings in 1.5 s = syllable stuttering → trigger"
    if(!oscActive){{
      oscActive=true;
      triggerMetronome('syllable_stutter');
    }}
  }}else{{
    // "Oscillation stopped — check for recovery"
    if(oscActive && count<=1){{
      oscActive=false;
      // Mirrors: if not self._rep_stutter_active: self._stop_metronome(...)
      tryStop();
    }}
  }}
}}

// ── triggerMetronome — mirrors _trigger_metronome() ──────────────────────────
function triggerMetronome(reason){{
  if(!AUTO_MET) return;
  // "Reset any pending recovery — stutter is happening again"
  recovStart=null;
  if(metOn) return;  // "Already playing"
  metOn=true; cnt++;
  setStatus((reason==='energy_drop'?'Block':'Syllable stutter')+' — follow the metronome!');
  document.getElementById('metroType').textContent=
    (reason==='energy_drop'?'Block detected':'Syllable stutter — follow the rhythm');
  document.getElementById('mc').classList.add('on');
  document.getElementById('ms').textContent=cnt;
  document.getElementById('mm').textContent='ACTIVE';
  setPh('🔴 Stutter event #'+cnt);
  startMetro();
}}

// ── tryStop — mirrors _stop_metronome() with grace period ────────────────────
// "Instead of stopping instantly, requires fluent speech to persist
//  for _RECOVERY_GRACE_SEC seconds."
function tryStop(){{
  if(!metOn){{ recovStart=null; return; }}
  const now=Date.now();
  if(!recovStart){{ recovStart=now; return; }}  // Start grace timer
  if(now-recovStart<GRACE_MS) return;            // Still in grace period
  // Grace period elapsed — stop metronome
  metOn=false; recovStart=null; oscActive=false;
  // Clear crossing buffer (browser adaptation: prevents speaker→mic feedback
  // loop from old click sounds creating immediate re-trigger)
  energyCrossings=[]; wasAbove=false;
  clearTimeout(metroTimer);
  document.querySelectorAll('.dot').forEach(d=>d.classList.remove('on'));
  document.getElementById('mc').classList.remove('on');
  document.getElementById('mm').textContent='Idle';
  setStatus('Monitoring — metronome auto-starts on stutter');
  setPh('Phase 4/4 — Live detection active ✓');
}}

// ── Metronome (Web Audio precise scheduling) ──────────────────────────────────
function startMetro(){{beatIdx=0; nextBeat=actx.currentTime+0.05; sched();}}
function sched(){{
  if(!metOn) return;
  while(nextBeat<actx.currentTime+0.12){{
    playClick(nextBeat,beatIdx%4===0);
    const d=(nextBeat-actx.currentTime)*1000, i=beatIdx%4;
    setTimeout(()=>flash(i),Math.max(0,d));
    nextBeat+=60/BPM; beatIdx++;
  }}
  metroTimer=setTimeout(sched,40);
}}
function playClick(t,acc){{
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
