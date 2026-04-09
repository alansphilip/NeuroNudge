"""
Browser-based live session for NeuroNudge cloud deployment.
Detects all three stutter types: block (energy drop), prolongation (sustained),
repetition (rapid oscillations). Auto-metronome on any stutter.
"""

import streamlit as st
import streamlit.components.v1 as components


def is_native_audio_available() -> bool:
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        return any(d.get('max_input_channels', 0) > 0 for d in sd.query_devices())
    except Exception:
        return False


def show_browser_live_session(bpm: int = 72,
                              sensitivity: str = "Medium",
                              auto_metronome: bool = True):
    """
    Cloud live session — mirrors local LivePacingSession.
    All three stutter types detected in real time via Web Audio API.
    st.audio_input records simultaneously for auto-analysis.
    Returns audio bytes when recording stops, else None.
    """
    sens = {
        "Low":    {"ratio": 0.28, "debounce": 800},
        "Medium": {"ratio": 0.40, "debounce": 600},
        "High":   {"ratio": 0.52, "debounce": 350},
    }
    cfg = sens.get(sensitivity, sens["Medium"])
    stutter_ratio       = cfg["ratio"]
    debounce_ms         = cfg["debounce"]
    max_pre_silence_ms  = 500   # ms since last speech → block won't fire (natural pause)

    html = f"""
<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:'Segoe UI',sans-serif;background:#f8faf9;padding:10px;}}
.status{{
  background:linear-gradient(135deg,#0f5132,#1a7a4a);
  color:white;border-radius:10px;padding:9px 14px;
  font-size:13px;font-weight:600;text-align:center;margin-bottom:8px;
}}
.metrics{{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;margin-bottom:8px;}}
.m{{background:#f0f7f3;border-radius:8px;padding:8px;text-align:center;}}
.mv{{font-size:22px;font-weight:800;color:#0f5132;}}
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

<div class="metrics">
  <div class="m"><div class="mv" id="mt">0s</div><div class="ml">Time</div></div>
  <div class="m"><div class="mv" id="ms">0</div><div class="ml">Stutters</div></div>
  <div class="m"><div class="mv" id="mm">Idle</div><div class="ml">Metronome</div></div>
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
const BPM={bpm}, SR={stutter_ratio}, DBNC={debounce_ms}, MAX_PRE={max_pre_silence_ms};
const CALIB_SEC=5, SMOOTH=0.93, MIN_ON_MS=2200, MIN_OFF_MS=1500;

let actx=null,ana=null,stream=null,running=false;
let calib=true,calibSamples=[],spoke=false;
let eThr=0,rThr=0,peak=0,ambient=0,speakMid=0;
let metOn=false,cnt=0,t0=null,smooth=0;
let metroTimer=null,nextBeat=0,beatIdx=0;
let metroOnTime=0,metroOffTime=0;
let lastSpeechTime=0;  // tracks last time user was actively speaking

// Debounce timestamps
let blockDbnc=null,recovDbnc=null;

// Prolongation state
let prolongStart=null,prolongHist=[];
const PROLONG_MS=700, PROLONG_VAR=0.00015;

// Repetition state
let crossings=[],lastCross=null;
const REP_WIN_MS=2500,REP_MIN=3,REP_MAX_GAP=600,REP_MIN_GAP=120;

async function startSess() {{
  try {{
    document.getElementById('st').textContent='Requesting microphone...';
    stream=await navigator.mediaDevices.getUserMedia({{audio:true,video:false}});
    actx=new (window.AudioContext||window.webkitAudioContext)();
    const src=actx.createMediaStreamSource(stream);
    ana=actx.createAnalyser(); ana.fftSize=2048; ana.smoothingTimeConstant=0.1;
    src.connect(ana);
    running=true;calib=true;calibSamples=[];spoke=false;
    cnt=0;metOn=false;smooth=0;
    blockDbnc=null;recovDbnc=null;
    prolongStart=null;prolongHist=[];crossings=[];lastCross=null;
    t0=Date.now();metroOffTime=Date.now();lastSpeechTime=0;
    document.getElementById('bs').style.display='none';
    document.getElementById('be').style.display='block';
    document.getElementById('mc').classList.remove('on');
    document.getElementById('done').classList.remove('show');
    document.getElementById('ms').textContent='0';
    document.getElementById('mm').textContent='Idle';
    loop();
  }} catch(e) {{
    document.getElementById('st').textContent='Mic error: '+e.message+' — allow mic and retry';
  }}
}}

function loop() {{
  if(!running) return;
  requestAnimationFrame(loop);
  const buf=new Float32Array(ana.frequencyBinCount);
  ana.getFloatTimeDomainData(buf);
  let s=0; for(let i=0;i<buf.length;i++) s+=buf[i]*buf[i];
  const rms=Math.sqrt(s/buf.length);
  smooth=SMOOTH*smooth+(1-SMOOTH)*rms;
  const el=(Date.now()-t0)/1000;
  document.getElementById('mt').textContent=Math.floor(el)+'s';

  if(calib) {{
    calibSamples.push(smooth);
    if(smooth>0.01) spoke=true;
    document.getElementById('st').textContent=spoke
      ?'Calibrating… speak naturally ('+(Math.max(1,Math.ceil(CALIB_SEC-el)))+'s left)'
      :'Listening… start speaking now';
    if(el>=CALIB_SEC && spoke) {{
      const sorted=[...calibSamples].sort((a,b)=>a-b);
      ambient=sorted[Math.floor(sorted.length*0.1)]||0.001;
      const spSam=calibSamples.filter(v=>v>ambient*2);
      peak=spSam.length>5 ? spSam.reduce((a,b)=>a+b)/spSam.length
                          : sorted[Math.floor(sorted.length*0.85)];
      eThr=peak*SR; rThr=peak*(SR+0.18); speakMid=peak*0.55;
      calib=false;
      document.getElementById('st').textContent=
        'Monitoring — metronome auto-starts on stutter (block / prolongation / repetition)';
    }}
    return;
  }}

  const now=Date.now();

  // Track last active speech time (used to exclude natural pauses from block detection)
  if(smooth>rThr*0.7) lastSpeechTime=now;

  // ── Recovery: stop metronome ─────────────────────────────
  if(metOn && smooth>rThr) {{
    if(!recovDbnc) recovDbnc=now;
    else if(now-recovDbnc>=DBNC && now-metroOnTime>=MIN_ON_MS) {{
      metOn=false; metroOffTime=now; recovDbnc=null; blockDbnc=null;
      stopMetro();
      document.getElementById('mm').textContent='Idle';
      document.getElementById('st').textContent=
        'Monitoring — metronome auto-starts on stutter';
    }}
  }} else if(metOn) {{ recovDbnc=null; }}

  if(metOn) return; // already correcting — skip detection

  // ── 1. Block: energy drop DURING active speech only ────
  // Only fires if user was speaking within MAX_PRE ms — excludes
  // natural pauses, full stops, and end-of-sentence silence.
  const speechWasRecent = lastSpeechTime>0 && (now-lastSpeechTime)<MAX_PRE;
  if(smooth<eThr && speechWasRecent) {{
    if(!blockDbnc) blockDbnc=now;
    else if(now-blockDbnc>=DBNC && now-metroOffTime>=MIN_OFF_MS) {{
      trigger('block'); return;
    }}
  }} else {{ blockDbnc=null; }}

  // ── 2. Prolongation: stable moderate energy ──────────────
  if(smooth>ambient*2.5 && smooth<peak*0.8) {{
    if(!prolongStart) {{ prolongStart=now; prolongHist=[smooth]; }}
    else {{
      prolongHist.push(smooth);
      if(now-prolongStart>PROLONG_MS && prolongHist.length>12) {{
        const mean=prolongHist.reduce((a,b)=>a+b)/prolongHist.length;
        const vari=prolongHist.reduce((s,v)=>s+(v-mean)**2,0)/prolongHist.length;
        if(vari<PROLONG_VAR && now-metroOffTime>=MIN_OFF_MS) {{
          trigger('prolongation'); return;
        }}
      }}
    }}
  }} else {{ prolongStart=null; prolongHist=[]; }}

  // ── 3. Repetition: rapid energy crossings ────────────────
  const crossState=smooth>speakMid;
  if(lastCross!==null && crossState!==lastCross && crossState) {{
    crossings.push(now);
    crossings=crossings.filter(t=>now-t<REP_WIN_MS);
    if(crossings.length>=REP_MIN) {{
      const gaps=[];
      for(let i=1;i<crossings.length;i++) gaps.push(crossings[i]-crossings[i-1]);
      const avg=gaps.reduce((a,b)=>a+b)/gaps.length;
      const maxGap=Math.max(...gaps), minGap=Math.min(...gaps);
      // Rhythmicity gate: gaps must be evenly spaced — hallmark of true word repetition
      const rhythmic=(maxGap-minGap)<avg*0.7;
      if(avg<REP_MAX_GAP && avg>REP_MIN_GAP && rhythmic && now-metroOffTime>=MIN_OFF_MS) {{
        trigger('repetition'); crossings=[]; return;
      }}
    }}
  }}
  lastCross=crossState;
}}

function trigger(type) {{
  metOn=true; cnt++;
  metroOnTime=Date.now(); blockDbnc=null; recovDbnc=null;
  prolongStart=null; prolongHist=[]; crossings=[];
  startMetro(type);
  document.getElementById('ms').textContent=cnt;
  document.getElementById('mm').textContent='ACTIVE';
  const labels={{block:'Block detected',prolongation:'Prolongation detected',repetition:'Repetition detected'}};
  document.getElementById('st').textContent=(labels[type]||'Stutter')+' — follow the metronome!';
  document.getElementById('metroType').textContent=
    (labels[type]||'Stutter')+' — follow the rhythm';
}}

function startMetro(type) {{
  document.getElementById('mc').classList.add('on');
  beatIdx=0; nextBeat=actx.currentTime+0.05; sched();
}}

function sched() {{
  if(!metOn) return;
  while(nextBeat<actx.currentTime+0.12) {{
    click(nextBeat,beatIdx%4===0);
    const i=beatIdx%4,d=(nextBeat-actx.currentTime)*1000;
    setTimeout(()=>flash(i),Math.max(0,d));
    nextBeat+=60/BPM; beatIdx++;
  }}
  metroTimer=setTimeout(sched,40);
}}

function click(t,acc) {{
  const o=actx.createOscillator(),g=actx.createGain();
  o.connect(g);g.connect(actx.destination);
  o.frequency.value=acc?1000:880;
  g.gain.setValueAtTime(acc?0.5:0.3,t);
  g.gain.exponentialRampToValueAtTime(0.001,t+0.04);
  o.start(t);o.stop(t+0.045);
}}

function flash(i) {{
  document.querySelectorAll('.dot').forEach((d,j)=>d.classList.toggle('on',j===i));
}}

function stopMetro() {{
  clearTimeout(metroTimer);
  document.querySelectorAll('.dot').forEach(d=>d.classList.remove('on'));
  document.getElementById('mc').classList.remove('on');
}}

function stopSess() {{
  running=false;metOn=false;stopMetro();
  if(stream) stream.getTracks().forEach(t=>t.stop());
  document.getElementById('be').style.display='none';
  document.getElementById('bs').style.display='block';
  document.getElementById('bs').textContent='🔄 New Session';
  document.getElementById('st').textContent=
    'Session complete — '+cnt+' stutter event(s) detected';
  document.getElementById('mm').textContent=cnt?cnt+' events':'None';
  document.getElementById('done').classList.add('show');
}}
</script></body></html>
"""

    components.html(html, height=370, scrolling=False)

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
