"""
Browser-based live session for NeuroNudge cloud deployment.

FINAL STABLE VERSION — two detection modes only:

  Mode 1 — BLOCK      : energy drops below noise×SNR_THRESH for PAUSE_IGNORE ms
                         AND SNR is near ambient (not just soft speech).
  Mode 3 — REPETITION : smoothFast crosses wrepMid ≥ 6 times in 1.5 s
                         with each gap 80–300 ms and rhythmicity < 0.5.
                         Gap cap of 300 ms ensures only FAST repetitions
                         (stuttered words) trigger — not normal speech transitions
                         (which have 300–600 ms word gaps).

Mode 2 (syllable oscillation) has been REMOVED because normal speech at
2–3 words/sec creates 4+ smoothMid crossings per 1.5 s window, causing the
metronome to cycle continuously.
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
    Returns audio bytes (st.audio_input) when recording stops, else None.
    """
    sens = {
        "Low":    {"drop_ratio": 0.35, "pause_ignore_ms": 3000},
        "Medium": {"drop_ratio": 0.30, "pause_ignore_ms": 2500},
        "High":   {"drop_ratio": 0.25, "pause_ignore_ms": 2000},
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

// Smoothing
const SLOW_K  = 0.92;  // Mode 1 block — heavy EMA (τ≈1.2 s)
const FAST_K  = 0.30;  // Mode 3 word-rep — fast EMA (τ≈80 ms)

// Calibration
const AMBIENT_FRAMES = 10;
const CALIB_FRAMES   = 10;
const NOISE_WIN      = 50;
const SPEECH_WIN     = 30;
const RECAL_EVERY    = 20;
const SNR_THRESH     = 2.0;

// ── Mode 3: Word-repetition ──────────────────────────────────────────────────
// "the-the-the" → smoothFast crosses wrepMid 6+ times in 1.5 s
// Gap constraint 80–300 ms is the KEY discriminator:
//   Stuttered words repeat at 3–10 Hz → gap 100–330 ms ✓
//   Normal speech word transitions are 300–600 ms apart → rejected ✓
const WREP_WIN_MS  = 1500;  // 1.5 s window
const WREP_MIN     = 6;     // 6 crossings ≈ 3 word repetitions
const WREP_DBN_MS  = 60;    // crossing debounce (ignore < 60 ms apart)
const WREP_AVG_MIN = 80;    // ms — avg gap lower bound
const WREP_AVG_MAX = 300;   // ms — avg gap upper bound (KEY: rejects slow speech)
const WREP_RHYTHM  = 0.50;  // (gMax-gMin)/gAvg < 0.5 — tight rhythmicity

// ── Recovery & guards ────────────────────────────────────────────────────────
const GRACE_MS        = 800;   // fluent speech must persist this long before stopping
const MIN_ON_MS       = 2500;  // metronome stays on at least 2.5 s
const MIN_OFF_MS      = 2500;  // metronome stays off at least 2.5 s before re-trigger
const MAX_SPEECH_GAP  = 700;   // ms — Mode 1: must have spoken within this window
const MAX_SPEECH_WREP = 1200;  // ms — Mode 3: speech look-back window

// ── State ─────────────────────────────────────────────────────────────────────
let actx=null, ana=null, stream=null, running=false;
let phase=0;  // 0=IDLE 1=AMBIENT 2=WAIT_SPEECH 3=CALIBRATING 4=MONITORING
let t0=null, lastFrameMs=0;

let smooth=0, smoothFast=0, rms=0;

let ambBuf=[], noiseTracker=[], noiseFloor=0;
let calibBuf=[], speechBuf=[];
let eThr=0, rThr=0, wrepMid=0;
let recalCounter=0;

let metOn=false, cnt=0;
let metroTimer=null, nextBeat=0, beatIdx=0;
let metroOnTime=0, metroOffTime=0, recovStart=null;

let lastSpeechTime=0;
let lowEnergyStart=null;
let wrepCrossings=[], lastWrepAbove=null, lastWrepCrossMs=0;

// ── Helpers ───────────────────────────────────────────────────────────────────
function pct(arr,p){{
  const s=[...arr].sort((a,b)=>a-b);
  return s[Math.floor(s.length*p)]||0;
}}
function mean(arr){{return arr.length?arr.reduce((a,b)=>a+b)/arr.length:0;}}
function getSNR(v){{return noiseFloor>0?v/noiseFloor:100;}}
function setStatus(m){{document.getElementById('st').textContent=m;}}
function setPh(m)    {{document.getElementById('ph').textContent=m;}}

function updateNoise(v){{
  noiseTracker.push(v);
  if(noiseTracker.length>NOISE_WIN) noiseTracker.shift();
  noiseFloor=pct(noiseTracker,0.30);
}}
function updateSpeech(v){{
  speechBuf.push(v);
  if(speechBuf.length>SPEECH_WIN) speechBuf.shift();
}}

function recalc(){{
  if(!speechBuf.length) return;
  const avg=mean(speechBuf), noise=Math.max(noiseFloor,0.0001);
  const dyn=avg-noise;
  if(dyn<=0){{eThr=noise*1.2; rThr=noise*1.5;}}
  else      {{eThr=noise+dyn*DROP_RATIO; rThr=noise+dyn*0.45;}}
  // Word-rep midpoint: low enough to catch individual word humps via smoothFast
  wrepMid=noise+dyn*0.20;
}}

// ── Start ─────────────────────────────────────────────────────────────────────
async function startSess(){{
  try{{
    setStatus('Requesting microphone…');
    stream=await navigator.mediaDevices.getUserMedia({{audio:true,video:false}});
    actx=new (window.AudioContext||window.webkitAudioContext)();
    const src=actx.createMediaStreamSource(stream);
    ana=actx.createAnalyser(); ana.fftSize=2048; ana.smoothingTimeConstant=0.0;
    src.connect(ana);

    running=true; smooth=0; smoothFast=0; rms=0;
    t0=Date.now(); lastFrameMs=0;
    ambBuf=[]; noiseTracker=[]; noiseFloor=0;
    calibBuf=[]; speechBuf=[];
    eThr=0; rThr=0; wrepMid=0; recalCounter=0;
    metOn=false; cnt=0;
    metroOnTime=0; metroOffTime=Date.now()-MIN_OFF_MS;
    recovStart=null; lastSpeechTime=0; lowEnergyStart=null;
    wrepCrossings=[]; lastWrepAbove=null; lastWrepCrossMs=0;
    phase=1;

    document.getElementById('bs').style.display='none';
    document.getElementById('be').style.display='block';
    document.getElementById('mc').classList.remove('on');
    document.getElementById('done').classList.remove('show');
    document.getElementById('ms').textContent='0';
    document.getElementById('mm').textContent='Idle';
    document.getElementById('msnr').textContent='—';
    loop();
  }}catch(e){{setStatus('Mic error: '+e.message+' — allow mic and retry');}}
}}

// ── Main loop ─────────────────────────────────────────────────────────────────
function loop(){{
  if(!running) return;
  requestAnimationFrame(loop);
  const now=Date.now();
  if(now-lastFrameMs<80) return;   // ~12 fps
  lastFrameMs=now;

  const buf=new Float32Array(ana.frequencyBinCount);
  ana.getFloatTimeDomainData(buf);
  let s=0; for(let i=0;i<buf.length;i++) s+=buf[i]*buf[i];
  rms       = Math.sqrt(s/buf.length);
  smooth    = SLOW_K*smooth     + (1-SLOW_K)*rms;
  smoothFast= FAST_K*smoothFast + (1-FAST_K)*rms;

  const el=(now-t0)/1000;
  document.getElementById('mt').textContent=Math.floor(el)+'s';

  // ── Phase 1: Ambient ───────────────────────────────────────────────────────
  if(phase===1){{
    ambBuf.push(rms); updateNoise(rms);
    const rem=Math.max(0,Math.ceil(1-el));
    setStatus('Learning ambient noise… stay silent ('+rem+'s)');
    setPh('Step 1/4 — Ambient calibration');
    if(ambBuf.length>=AMBIENT_FRAMES) phase=2;
    return;
  }}

  // ── Phase 2: Wait for speech ───────────────────────────────────────────────
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

  // ── Phase 3: Calibrate ────────────────────────────────────────────────────
  if(phase===3){{
    const snr=getSNR(rms);
    document.getElementById('msnr').textContent=snr.toFixed(1)+'×';
    if(snr>SNR_THRESH){{calibBuf.push(rms); updateSpeech(rms);}}
    const rem=Math.max(0,CALIB_FRAMES-calibBuf.length);
    setStatus('Calibrating… ('+rem+' frames left, keep speaking)');
    setPh('Step 3/4 — Computing thresholds');
    if(calibBuf.length>=CALIB_FRAMES){{
      noiseFloor=pct(noiseTracker,0.30); recalc();
      phase=4;
      setStatus('Monitoring — metronome auto-starts on stutter');
      setPh('Step 4/4 — Live detection active ✓');
    }}
    return;
  }}

  // ── Phase 4: MONITORING ───────────────────────────────────────────────────
  const snrNow=getSNR(smooth);
  document.getElementById('msnr').textContent=snrNow.toFixed(1)+'×';

  // Adaptive trackers — SNR-based so soft speech updates thresholds too
  if(smooth<eThr) updateNoise(rms);
  if(snrNow>SNR_THRESH && smooth>eThr) updateSpeech(rms);
  if(++recalCounter>=RECAL_EVERY){{recalCounter=0; recalc();}}

  // Speech context — any frame where SNR shows clear voice
  if(snrNow>SNR_THRESH) lastSpeechTime=now;
  const speechRecent     = lastSpeechTime>0 && (now-lastSpeechTime)<MAX_SPEECH_GAP;
  const speechRecentWrep = lastSpeechTime>0 && (now-lastSpeechTime)<MAX_SPEECH_WREP;

  // When not speaking, reset timers so no stale data carries over
  if(!speechRecent)  lowEnergyStart=null;
  if(!speechRecentWrep){{ wrepCrossings=[]; }}

  // ── Recovery ──────────────────────────────────────────────────────────────
  if(metOn){{
    if(smooth>rThr){{
      if(!recovStart) recovStart=now;
      else if(now-recovStart>=GRACE_MS && now-metroOnTime>=MIN_ON_MS)
        stopMetro('energy_recovery');
    }}else recovStart=null;
    return;
  }}

  // ── MODE 1: Block — sustained silence during speech ───────────────────────
  // Requires: energy below threshold  AND  SNR near ambient (< SNR_THRESH)
  // SNR gate prevents soft voice (SNR 5-15×) from triggering; only true
  // near-silence (SNR ~1×) counts as a block.
  if(smooth<eThr && snrNow<SNR_THRESH && speechRecent){{
    if(!lowEnergyStart) lowEnergyStart=now;
    if(now-lowEnergyStart>=PAUSE_IGNORE && now-metroOffTime>=MIN_OFF_MS){{
      trigger('block'); return;
    }}
  }}else lowEnergyStart=null;

  // ── MODE 3: Word repetition — fast rhythmic energy humps ─────────────────
  // Uses smoothFast (K=0.3, τ≈80 ms): fast enough to track individual word
  // humps (200–400 ms) but not raw noise.
  // WREP_AVG_MAX=300 ms is the critical discriminator:
  //   Stuttered repetitions ("the-the-the"): ~100–250 ms per crossing ✓
  //   Normal speech word boundaries:          ~300–600 ms per crossing ✗
  if(speechRecentWrep){{
    const aboveWrep=(smoothFast>wrepMid);
    if(lastWrepAbove!==null && aboveWrep!==lastWrepAbove){{
      if(now-lastWrepCrossMs>WREP_DBN_MS){{
        wrepCrossings.push(now);
        lastWrepCrossMs=now;
      }}
    }}
    lastWrepAbove=aboveWrep;
  }}
  wrepCrossings=wrepCrossings.filter(t=>now-t<WREP_WIN_MS);

  if(wrepCrossings.length>=WREP_MIN && now-metroOffTime>=MIN_OFF_MS){{
    const gaps=[];
    for(let i=1;i<wrepCrossings.length;i++) gaps.push(wrepCrossings[i]-wrepCrossings[i-1]);
    const a=mean(gaps), gMax=Math.max(...gaps), gMin=Math.min(...gaps);
    const rhythmic=(gMax-gMin)<a*WREP_RHYTHM;
    if(a>=WREP_AVG_MIN && a<=WREP_AVG_MAX && rhythmic){{
      trigger('repetition'); return;
    }}
  }}
}}

// ── Trigger / Stop ────────────────────────────────────────────────────────────
function trigger(type){{
  if(!AUTO_MET||metOn) return;
  metOn=true; cnt++;
  metroOnTime=Date.now(); recovStart=null;
  lowEnergyStart=null; wrepCrossings=[];   // clear all pending data
  startMetro();
  document.getElementById('ms').textContent=cnt;
  document.getElementById('mm').textContent='ACTIVE';
  const lab={{block:'Block detected',repetition:'Repetition ×3 detected'}};
  setStatus((lab[type]||'Stutter detected')+' — follow the metronome!');
  document.getElementById('metroType').textContent=(lab[type]||'Stutter')+' — follow the rhythm';
  document.getElementById('mc').classList.add('on');
  setPh('🔴 Stutter event #'+cnt);
}}

function stopMetro(reason){{
  if(!metOn) return;
  metOn=false; metroOffTime=Date.now(); recovStart=null;
  lowEnergyStart=null;
  wrepCrossings=[]; lastWrepAbove=null; // clear so no immediate re-trigger
  clearTimeout(metroTimer);
  document.querySelectorAll('.dot').forEach(d=>d.classList.remove('on'));
  document.getElementById('mc').classList.remove('on');
  document.getElementById('mm').textContent='Idle';
  setStatus('Monitoring — metronome auto-starts on stutter');
  setPh('Step 4/4 — Live detection active ✓');
}}

// ── Metronome (Web Audio) ─────────────────────────────────────────────────────
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
