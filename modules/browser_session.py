"""
Browser-based live session for NeuroNudge cloud deployment.

Two detection modes, matching live_session.py:

  Mode 1 — BLOCK      : SMA-4 smoothed energy below eThr for PAUSE_IGNORE ms
                         (direct port of live_session.py energy-drop logic)

  Mode 2 — REPETITION : Web Speech API interim transcript → 2+ consecutive
                         same word triggers metronome (mirrors Vosk-based
                         _scan_for_repetitions, _REP_THRESHOLD=2)

Mode 3 (oscillation) is intentionally omitted:
  - The Python oscillation detector works because sounddevice delivers exactly
    100ms frames with zero jitter.
  - Web Audio API frames have variable latency (5–50ms jitter), making SMA-4
    timing inconsistent and causing normal consonant stops (/b/ /d/ /t/) to
    produce spurious crossings → false triggers on fluent speech.
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
    Cloud live session. Returns audio bytes when recording stops, else None.
    """
    # PAUSE_IGNORE increased from Python defaults: browser has no audio
    # separation between input/output streams, so normal sentence pauses
    # (0.5-2 s) must not trip the block detector.
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
.asrBadge{{display:inline-block;font-size:10px;padding:2px 6px;border-radius:6px;
  background:#d1fae5;color:#065f46;font-weight:600;margin-left:6px;vertical-align:middle;}}
.asrBadge.off{{background:#fee2e2;color:#991b1b;}}
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
// ── Constants (mirrors live_session.py) ───────────────────────────────────────
const BPM          = {bpm};
const DROP_RATIO   = {drop_ratio};
const PAUSE_IGNORE = {pause_ignore_ms};
const AUTO_MET     = {auto_met_js};

const SMA_WIN        = 4;    // _SMOOTH_WINDOW = 4
const AMBIENT_FRAMES = 10;   // _AMBIENT_FRAMES = 10
const CALIB_FRAMES   = 12;   // _CALIBRATION_FRAMES = 12
const NOISE_WIN      = 50;   // _NOISE_WINDOW = 50
const SPEECH_WIN     = 30;   // _SPEECH_WINDOW = 30
const RECAL_EVERY    = 20;   // every 20 frames
const SNR_THRESH     = 2.0;
const GRACE_MS       = 500;  // _RECOVERY_GRACE_SEC = 0.5 s

// Repetition — REP_THRESH=3 (not 2 as in Python) because Web Speech API
// interim results are noisier than Vosk and produce more false repeats.
const REP_THRESH    = 3;     // 3+ same consecutive words = stutter
const REP_RECOVERY  = 3;     // 3+ unique consecutive words = fluent

// ── State ─────────────────────────────────────────────────────────────────────
let actx=null, ana=null, stream=null, running=false;
let phase=0;
let t0=null, lastFrameMs=0;

let smaBuf=[], rms=0;
let noiseTracker=[], speechBuf=[], noiseFloor=0;
let eThr=0, rThr=0;
let ambBuf=[], calibBuf=[], recalCounter=0, calibrated=false;

let metOn=false, cnt=0;
let metroTimer=null, nextBeat=0, beatIdx=0;
let lowEnergyStart=null, recovStart=null, prevSmoothed=0;

// Repetition (Web Speech API)
let recognition=null, repActive=false, lastWords=[];

// ── Helpers ───────────────────────────────────────────────────────────────────
function getSMA(r){{
  smaBuf.push(r);
  if(smaBuf.length>SMA_WIN) smaBuf.shift();
  return smaBuf.reduce((a,b)=>a+b)/smaBuf.length;
}}
function updateNoise(r){{
  noiseTracker.push(r);
  if(noiseTracker.length>NOISE_WIN) noiseTracker.shift();
  const s=[...noiseTracker].sort((a,b)=>a-b);
  noiseFloor=s[Math.floor(s.length*0.30)]||0;
}}
function updateSpeech(r){{
  speechBuf.push(r);
  if(speechBuf.length>SPEECH_WIN) speechBuf.shift();
}}
function getSNR(v){{return noiseFloor>0?v/noiseFloor:100;}}
function recalc(){{
  if(!speechBuf.length) return;
  const avg=speechBuf.reduce((a,b)=>a+b)/speechBuf.length;
  const noise=Math.max(noiseFloor,0.0001), dyn=avg-noise;
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
    lowEnergyStart=null; recovStart=null;
    repActive=false; lastWords=[];
    phase=1;

    document.getElementById('bs').style.display='none';
    document.getElementById('be').style.display='block';
    document.getElementById('mc').classList.remove('on');
    document.getElementById('done').classList.remove('show');
    document.getElementById('ms').textContent='0';
    document.getElementById('mm').textContent='Idle';
    document.getElementById('msnr').textContent='—';

    initSpeechRec();
    loop();
  }}catch(e){{setStatus('Mic error: '+e.message);}}
}}

// ── Mode 2: Web Speech API — mirrors Vosk _scan_for_repetitions() ─────────────
function initSpeechRec(){{
  const SR=window.SpeechRecognition||window.webkitSpeechRecognition;
  if(!SR){{
    setPh('Speech recognition unavailable — block detection only');
    return;
  }}
  recognition=new SR();
  recognition.continuous=true;
  recognition.interimResults=true;
  recognition.lang='en-US';

  recognition.onresult=(event)=>{{
    if(phase!==4) return;
    // Build latest interim transcript
    let interim='';
    for(let i=event.resultIndex;i<event.results.length;i++){{
      if(!event.results[i].isFinal) interim+=event.results[i][0].transcript;
    }}
    if(interim.trim()) scanRepetitions(interim.trim().toLowerCase());
  }};

  recognition.onerror=(e)=>{{
    if(e.error==='not-allowed') setPh('⚠️ Speech API blocked — block detection only');
    if(running && e.error!=='aborted')
      setTimeout(()=>{{try{{recognition.start();}}catch(ex){{}}}},1000);
  }};

  recognition.onend=()=>{{
    if(running) setTimeout(()=>{{try{{recognition.start();}}catch(e){{}}}},300);
  }};

  try{{recognition.start();}}catch(e){{}}
}}

// mirrors _scan_for_repetitions()
function scanRepetitions(text){{
  const words=text.split(/\s+/).filter(w=>w.length>0);
  if(words.length<REP_THRESH || words.length===lastWords.length) return;
  lastWords=words;

  // "Find longest consecutive run of same word at end of list"
  let consec=1;
  for(let i=words.length-1;i>0;i--){{
    if(words[i]===words[i-1]) consec++;
    else break;
  }}

  if(consec>=REP_THRESH){{
    if(!repActive&&!metOn){{
      repActive=true;
      triggerMetronome('repetition','Word repeated: "'+words[words.length-1]+'" ×'+consec);
    }}
  }}else{{
    // Check fluent recovery — 3+ unique consecutive words
    if(repActive&&words.length>=2){{
      let unique=1;
      for(let i=words.length-1;i>0;i--){{
        if(words[i]!==words[i-1]) unique++;
        else break;
      }}
      if(unique>=REP_RECOVERY){{
        repActive=false;
        tryStop();
      }}
    }}
  }}
}}

// ── Main loop (~100ms frames, mirrors block_size=1600 @ 16kHz) ────────────────
function loop(){{
  if(!running) return;
  requestAnimationFrame(loop);
  const now=Date.now();
  if(now-lastFrameMs<90) return;
  lastFrameMs=now;

  const buf=new Float32Array(ana.frequencyBinCount);
  ana.getFloatTimeDomainData(buf);
  let s=0; for(let i=0;i<buf.length;i++) s+=buf[i]*buf[i];
  rms=Math.sqrt(s/buf.length);

  document.getElementById('mt').textContent=Math.floor((now-t0)/1000)+'s';

  // Phase 1: Ambient
  if(phase===1){{
    ambBuf.push(rms); updateNoise(rms);
    const rem=Math.max(0,Math.ceil(1-(now-t0)/1000));
    setStatus('Stay silent… learning ambient noise ('+rem+'s)');
    setPh('Phase 1/4 — Ambient calibration');
    if(ambBuf.length>=AMBIENT_FRAMES) phase=2;
    return;
  }}

  // Phase 2: Wait for speech
  if(phase===2){{
    const snr=getSNR(rms);
    document.getElementById('msnr').textContent=snr.toFixed(1)+'×';
    if(snr>SNR_THRESH&&rms>0.002){{
      phase=3;
      setStatus('Calibrating… keep speaking naturally');
      setPh('Phase 2/4 — Measuring your voice level');
    }}else{{
      updateNoise(rms);
      setStatus('Listening… start speaking now');
      setPh('Phase 2/4 — Waiting for speech (SNR '+snr.toFixed(1)+'×)');
    }}
    return;
  }}

  // Phase 3: Calibrate
  if(phase===3){{
    const snr=getSNR(rms);
    document.getElementById('msnr').textContent=snr.toFixed(1)+'×';
    if(snr>SNR_THRESH) calibBuf.push(rms);
    setStatus('Calibrating… ('+Math.max(0,CALIB_FRAMES-calibBuf.length)+' frames left)');
    setPh('Phase 3/4 — Computing thresholds');
    if(calibBuf.length>=CALIB_FRAMES){{
      const avg=calibBuf.reduce((a,b)=>a+b)/calibBuf.length;
      speechBuf=[...calibBuf];
      const noise=Math.max(noiseFloor,0.0001), dyn=avg-noise;
      if(dyn<=0){{eThr=noise*1.2; rThr=noise*1.5;}}
      else      {{eThr=noise+dyn*DROP_RATIO; rThr=noise+dyn*0.45;}}
      calibrated=true; smaBuf=[];
      phase=4;
      setStatus('Monitoring — metronome auto-starts on stutter');
      setPh('Phase 4/4 — Live detection active ✓');
    }}
    return;
  }}

  // Phase 4: Stutter detection — mirrors live_session.py lines 429-466
  const smoothed=getSMA(rms);
  document.getElementById('msnr').textContent=getSNR(smoothed).toFixed(1)+'×';

  if(smoothed<eThr) updateNoise(rms);       // line 432
  // Update speech level at eThr*1.2 (not just rThr) so thresholds adapt
  // when user speaks softer post-calibration — prevents eThr drifting high
  // and turning normal moderate speech into perpetual "low energy".
  if(smoothed>eThr*1.2) updateSpeech(rms);
  if(++recalCounter>=RECAL_EVERY){{recalCounter=0; recalc();}}  // line 441

  // Mode 1: Energy drop (lines 447-466)
  // Only ARM the block timer if the previous frame was clearly above eThr
  // (i.e. they were speaking and energy just dropped). If they were already
  // quiet (prevSmoothed <= eThr), don't start the timer — this prevents
  // false triggers when the user simply starts the session at low volume.
  if(smoothed<eThr){{
    if(!lowEnergyStart && prevSmoothed>eThr)
      lowEnergyStart=now;   // ARM: came from above threshold → now dropped
    if(lowEnergyStart && now-lowEnergyStart>=PAUSE_IGNORE)
      triggerMetronome('energy_drop','Block — follow the metronome!');
  }}else{{
    if(smoothed>rThr) tryStop();   // energy recovery attempt
    lowEnergyStart=null;
  }}
  prevSmoothed=smoothed;
}}

// ── Trigger — mirrors _trigger_metronome() ────────────────────────────────────
function triggerMetronome(reason, label){{
  if(!AUTO_MET) return;
  recovStart=null;        // "Reset any pending recovery"
  if(metOn) return;       // "Already playing"
  metOn=true; cnt++;
  setStatus((label||'Stutter detected')+' — follow the metronome!');
  document.getElementById('metroType').textContent=
    (reason==='energy_drop'?'Block detected':
     reason==='repetition'?'Word repetition detected':
     'Stutter detected')+' — follow the rhythm';
  document.getElementById('mc').classList.add('on');
  document.getElementById('ms').textContent=cnt;
  document.getElementById('mm').textContent='ACTIVE';
  setPh('🔴 Stutter event #'+cnt);
  startMetro();
}}

// ── Grace-period stop — mirrors _stop_metronome() ────────────────────────────
function tryStop(){{
  if(!metOn){{recovStart=null;return;}}
  const now=Date.now();
  if(!recovStart){{recovStart=now;return;}}
  if(now-recovStart<GRACE_MS) return;
  // Confirmed recovery
  metOn=false; recovStart=null; repActive=false;
  clearTimeout(metroTimer);
  document.querySelectorAll('.dot').forEach(d=>d.classList.remove('on'));
  document.getElementById('mc').classList.remove('on');
  document.getElementById('mm').textContent='Idle';
  setStatus('Monitoring — metronome auto-starts on stutter');
  setPh('Phase 4/4 — Live detection active ✓');
}}

// ── Metronome ─────────────────────────────────────────────────────────────────
function startMetro(){{beatIdx=0;nextBeat=actx.currentTime+0.05;sched();}}
function sched(){{
  if(!metOn) return;
  while(nextBeat<actx.currentTime+0.12){{
    playClick(nextBeat,beatIdx%4===0);
    const d=(nextBeat-actx.currentTime)*1000,i=beatIdx%4;
    setTimeout(()=>flash(i),Math.max(0,d));
    nextBeat+=60/BPM; beatIdx++;
  }}
  metroTimer=setTimeout(sched,40);
}}
function playClick(t,acc){{
  const o=actx.createOscillator(),g=actx.createGain();
  o.connect(g);g.connect(actx.destination);
  o.frequency.value=acc?1000:880;
  g.gain.setValueAtTime(acc?0.5:0.3,t);
  g.gain.exponentialRampToValueAtTime(0.001,t+0.04);
  o.start(t);o.stop(t+0.045);
}}
function flash(i){{document.querySelectorAll('.dot').forEach((d,j)=>d.classList.toggle('on',j===i));}}

// ── Stop session ──────────────────────────────────────────────────────────────
function stopSess(){{
  running=false; metOn=false; clearTimeout(metroTimer);
  document.querySelectorAll('.dot').forEach(d=>d.classList.remove('on'));
  if(stream) stream.getTracks().forEach(t=>t.stop());
  try{{if(recognition) recognition.stop();}}catch(e){{}}
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
        "Tap the mic icon to start recording simultaneously. "
        "Tap stop when done — analysis runs automatically."
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
