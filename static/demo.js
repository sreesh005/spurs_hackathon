/* DEMO CLIP. The Live dots desk without the live feed: plays the recorded 60s clip (live/clips/demo90.mp4) straight in the page.
   No tracker or transcript server needed. The Twelve Labs transcript is read from live/clips/demo90_transcript.json and its
   lines appear as the video reaches them; a named Spurs player opens their reel in the drawer, same as the Live tab.
   Uses the transcript helpers in live.js (liveAddLine, liveAfterLines, ...). */

const DEMO_CLIP = "/clips/demo90.mp4";
const DEMO_SOURCES = ["/clips/demo90_transcript.json", COMM_URL + "/clip_transcript.json"];
const DEMO = { sentences: null, timer: null, loading: false };

function demoHtml() {
  return `<section class="live demo">
    <div class="stage-bar">
      <span class="demo-note">Demo clip · 60s recording, loops</span>
      <button type="button" class="ghost" id="live-menu">Menu</button>
    </div>
    <div class="stage m-video">
      <div class="live-video"><video id="demo-video" src="${DEMO_CLIP}" autoplay muted loop playsinline controls></video><div class="live-badge">demo clip</div></div>
    </div>
    <div class="live-tx" id="live-tx">
      <div class="tx-head"><b>Commentary</b><span class="tx-dot" id="tx-dot"></span><span class="meta" id="tx-status">loading the transcript…</span>
        <label class="tx-follow"><input type="checkbox" id="tx-follow" checked /> Follow the announcer</label></div>
      <div class="tx-chips" id="tx-chips"></div>
      <div class="tx-lines" id="tx-lines"><p class="meta">Waiting for the commentary…</p></div>
    </div>
  </section>`;
}

function demoStatus(text, on) {
  const status = document.getElementById("tx-status"), dot = document.getElementById("tx-dot");
  if (status) status.textContent = text;
  if (dot) dot.className = "tx-dot" + (on ? " on" : "");
}

// the transcript file next to the clip, else the tl_transcript.py server if it happens to be running
async function demoLoad() {
  if (DEMO.sentences || DEMO.loading) return;
  DEMO.loading = true;
  for (const url of DEMO_SOURCES) {
    try {
      const r = await fetch(url, { cache: "no-store" });
      if (!r.ok) continue;
      const d = await r.json();
      const list = Array.isArray(d) ? d : d.sentences;
      if (list?.length) { DEMO.sentences = list; break; }
    } catch (e) { /* try the next source */ }
  }
  DEMO.loading = false;
  demoStatus(DEMO.sentences ? "Twelve Labs transcript" : "no transcript for the clip (run live/tl_transcript.py)", !!DEMO.sentences);
}

// show every line the video has reached; start over when it loops or is scrubbed backwards
function demoTick() {
  const video = document.getElementById("demo-video");
  if (state.tab !== "demo" || !video || !DEMO.sentences) return;
  const tx = LIVE.tx, pos = video.currentTime;
  if (pos < (tx.lastPos ?? 0) - 1) { tx.lines = []; tx.shown = 0; liveTxRender(); }
  tx.lastPos = pos;
  tx.shown = tx.shown || 0;
  let last = null, any = false;
  while (tx.shown < DEMO.sentences.length && DEMO.sentences[tx.shown].start <= pos) {
    const s = DEMO.sentences[tx.shown++];
    last = liveAddLine(s.text, 0, fmtClip(s.start)) || last;
    any = true;
  }
  if (any) liveAfterLines(last);
}

function mountDemo() {
  liveTxReset();
  liveClips();
  liveChips();
  liveTxRender();
  demoLoad().then(demoTick);
  if (!DEMO.timer) DEMO.timer = setInterval(demoTick, 200);
}
