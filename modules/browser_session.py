"""
Browser-based live session for NeuroNudge cloud deployment.

JS widget: real-time mic monitoring + auto-metronome on stutter detection.
st.audio_input: simultaneous recording that returns to Python for analysis.
Analysis runs automatically — no download/upload required.
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
    Cloud live session:
    - JS widget monitors mic in real-time → calibrates → auto-triggers metronome on stutter
    - st.audio_input records simultaneously → returns bytes → auto analysis in app.py
    Returns audio bytes when recording stops, else None.
    """

    # Sensitivity → stutter ratio and debounce
    sensitivity_map = {
        "Low":    {"ratio": 0.30, "debounce": 600},
        "Medium": {"ratio": 0.42, "debounce": 400},
        "High":   {"ratio": 0.55, "debounce": 250},
    }
    cfg = sensitivity_map.get(sensitivity, sensitivity_map["Medium"])
    stutter_ratio = cfg["ratio"]
    debounce_ms   = cfg["debounce"]

    html = f"""
<!DOCTYPE html><html><head><meta charset="utf-8">
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  font-family:'Segoe UI',sans-serif; background:#f8faf9;
  padding:10px; min-height:100vh;
}}
.status {{
  background:linear-gradient(135deg,#0f5132,#1a7a4a);
  color:white; border-radius:10px; padding:9px 14px;
  font-size:13px; font-weight:600; text-align:center;
  margin-bottom:8px;
}}
.metrics {{
  display:grid; grid-template-columns:repeat(4,1fr); gap:6px; margin-bottom:8px;
}}
.m {{ background:#f0f7f3; border-radius:8px; padding:7px; text-align:center; }}
.mv {{ font-size:20px; font-weight:800; color:#0f5132; }}
.ml {{ font-size:10px; color:#6b7b8d; margin-top:2px; }}
.ebar {{ background:#e9f5ee; border-radius:5px; height:8px; margin-bottom:8px; overflow:hidden; }}
.efill {{ height:100%; background:#0f5132; border-radius:5px; transition:width 0.08s; width:0%; }}
.metro {{
  background:linear-gradient(135deg,#0f5132,#1a7a4a); border-radius:10px;
  padding:10px 14px; color:white; text-align:center;
  margin-bottom:8px; display:none;
}}
.metro.on {{ display:block; }}
.mbpm {{ font-size:32px; font-weight:800; line-height:1; }}
.ml2 {{ font-size:11px; opacity:0.8; }}
.beats {{ margin:6px 0 3px; }}
.dot {{
  width:13px; height:13px; border-radius:50%;
  background:rgba(255,255,255,0.25); display:inline-block;
  margin:0 3px; transition:background 0.05s,transform 0.05s;
}}
.dot.on {{ background:#7fffd4; transform:scale(1.4); }}
.btns {{ display:flex; gap:8px; }}
button {{
  border:none; border-radius:8px; padding:10px;
  font-size:13px; font-weight:700; cursor:pointer;
  transition:all 0.15s; flex:1;
}}
.bstart {{ background:#0f5132; color:white; }}
.bstart:hover {{ background:#1a7a4a; }}
.bstop  {{ background:#dc2626; color:white; display:none; }}
.bstop:hover  {{ background:#b91c1c; }}
.done {{ background:#e9f5ee; border-radius:8px; padding:8px;
         font-size:12px; color:#0f5132; margin-top:8px;
         display:none; text-align:center; font-weight:600; }}
.done.show {{ display:block; }}
</style></head><body>

<div class="status" id="st">Click Start Session to begin</div>

<div class="metrics">
  <div class="m"><div class="mv" id="mt">0s</div><div class="ml">Time</div></div>
  <div class="m"><div class="mv" id="me">—</div><div class="ml">Energy</div></div>
  <div class="m"><div class="mv" id="ms">0</div><div class="ml">Stutters</div></div>
  <div class="m"><div class="mv" id="mm">Idle</div><div class="ml">Metronome</div></div>
</div>

<div class="ebar"><div class="efill" id="ef"></div></div>

<div class="metro" id="mc">
  <div class="mbpm">{bpm} BPM</div>
  <div class="ml2">Metronome — Active (follow the rhythm)</div>
  <div class="beats">
    <span class="dot" id="d0"></span>
    <span class="dot" id="d1"></span>
    <span class="dot" id="d2"></span>
    <span class="dot" id="d3"></span>
  </div>
</div>

<div class="btns">
  <button class="bstart" id="bs" onclick="startSess()">🎙 Start Session</button>
  <button class="bstop"  id="be" onclick="stopSess()">⏹ Stop Session</button>
</div>

<div class="done" id="done">
  ✅ Session complete — stop the mic recorder below and analysis will run automatically.
</div>

<script>
const BPM={bpm}, SR={stutter_ratio}, DBNC={debounce_ms};
const CALIB_SEC=5, SMOOTH=0.90, MIN_METRO_MS=2000, MIN_OFF_MS=1500;

let actx=null, ana=null, stream=null, running=false;
let calib=true, calibSamples=[], spoke=false;
let eThr=0, rThr=0, peak=0, ambient=0;
let metOn=false, cnt=0, t0=null;
let bThr=null, aThr=null;  // debounce timestamps
let metroTimer=null, nextBeat=0, beatIdx=0;
let metroOnTime=0, metroOffTime=0;
let smooth=0;

async function startSess() {{
  try {{
    document.getElementById('st').textContent='Requesting microphone...';
    stream = await navigator.mediaDevices.getUserMedia({{audio:true,video:false}});
    actx = new (window.AudioContext||window.webkitAudioContext)();
    const src = actx.createMediaStreamSource(stream);
    ana = actx.createAnalyser();
    ana.fftSize=2048; ana.smoothingTimeConstant=0.1;
    src.connect(ana);
    running=true; calib=true; calibSamples=[]; spoke=false;
    cnt=0; metOn=false; smooth=0; bThr=null; aThr=null;
    t0=Date.now(); metroOffTime=Date.now();
    document.getElementById('bs').style.display='none';
    document.getElementById('be').style.display='block';
    document.getElementById('mc').classList.remove('on');
    document.getElementById('done').classList.remove('show');
    loop();
  }} catch(e) {{
    document.getElementById('st').textContent='Mic error: '+e.message+' — please click Allow';
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
  document.getElementById('me').textContent=(smooth*100).toFixed(1)+'%';
  document.getElementById('ef').style.width=Math.min(100,smooth*800)+'%';

  if(calib) {{
    calibSamples.push(smooth);
    if(smooth>0.01) spoke=true;
    if(spoke) {{
      document.getElementById('st').textContent=
        'Calibrating… keep speaking naturally ('+(Math.ceil(CALIB_SEC-el)||1)+'s left)';
    }} else {{
      document.getElementById('st').textContent='Listening… start speaking now';
    }}
    if(el>=CALIB_SEC && spoke) {{
      const sorted=[...calibSamples].sort((a,b)=>a-b);
      ambient=sorted[Math.floor(sorted.length*0.1)]||0.001;
      // use top 30% as speech peak
      const spSam=calibSamples.filter(v=>v>ambient*2);
      if(spSam.length>5) {{
        peak=spSam.reduce((a,b)=>a+b)/spSam.length;
      }} else {{
        peak=sorted[Math.floor(sorted.length*0.85)];
      }}
      eThr=peak*SR;
      rThr=peak*(SR+0.18);
      calib=false;
      document.getElementById('st').textContent=
        'Monitoring — metronome auto-starts when stutter detected';
    }}
  }} else {{
    const now=Date.now();
    if(smooth<eThr && !metOn) {{
      if(!bThr) bThr=now;
      else if(now-bThr>=DBNC && now-metroOffTime>=MIN_OFF_MS) {{
        metOn=true; cnt++;
        metroOnTime=now; bThr=null; aThr=null;
        startMetro();
        document.getElementById('ms').textContent=cnt;
        document.getElementById('mm').textContent='ACTIVE';
        document.getElementById('st').textContent='Stutter detected — follow the metronome rhythm!';
      }}
    }} else if(smooth>rThr && metOn) {{
      if(!aThr) aThr=now;
      else if(now-aThr>=DBNC && now-metroOnTime>=MIN_METRO_MS) {{
        metOn=false; metroOffTime=now; aThr=null; bThr=null;
        stopMetro();
        document.getElementById('mm').textContent='Idle';
        document.getElementById('st').textContent='Monitoring — metronome auto-starts when stutter detected';
      }}
    }} else {{
      if(metOn) bThr=null; else aThr=null;
    }}
  }}
}}

function startMetro() {{
  document.getElementById('mc').classList.add('on');
  beatIdx=0; nextBeat=actx.currentTime+0.05;
  sched();
}}

function sched() {{
  if(!metOn) return;
  while(nextBeat<actx.currentTime+0.12) {{
    click(nextBeat,beatIdx%4===0);
    const i=beatIdx%4, d=(nextBeat-actx.currentTime)*1000;
    setTimeout(()=>flash(i),Math.max(0,d));
    nextBeat+=60/BPM; beatIdx++;
  }}
  metroTimer=setTimeout(sched,40);
}}

function click(t,acc) {{
  const o=actx.createOscillator(),g=actx.createGain();
  o.connect(g); g.connect(actx.destination);
  o.frequency.value=acc?1000:880;
  g.gain.setValueAtTime(acc?0.5:0.3,t);
  g.gain.exponentialRampToValueAtTime(0.001,t+0.04);
  o.start(t); o.stop(t+0.045);
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
  running=false; metOn=false;
  stopMetro();
  if(stream) stream.getTracks().forEach(t=>t.stop());
  document.getElementById('be').style.display='none';
  document.getElementById('bs').style.display='block';
  document.getElementById('bs').textContent='🔄 New Session';
  document.getElementById('st').textContent=
    'Session complete ('+cnt+' stutters detected)';
  document.getElementById('mm').textContent=cnt>0?cnt+' detected':'None';
  document.getElementById('done').classList.add('show');
}}
</script>
</body></html>
"""

    components.html(html, height=400, scrolling=False)

    st.markdown("<div style='margin-top:10px;'></div>", unsafe_allow_html=True)

    # Recording widget — auto-returns bytes when stopped → triggers analysis in app.py
    st.markdown("**🎙️ Record Your Session**")
    st.caption(
        "Tap the mic icon to start recording **at the same time** as the session above. "
        "Tap again to stop — analysis runs automatically."
    )
    audio_bytes = st.audio_input(
        "Record your voice",
        key="browser_live_input",
        help="Tap to start / tap again to stop. Analysis runs automatically when you stop."
    )

    if audio_bytes is not None:
        st.audio(audio_bytes, format="audio/wav")
        return audio_bytes

    return None
