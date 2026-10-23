/* LIVE DOTS. The live tracking feed (hack_live_dots.py --serve 8766) shown inside the Next Post desk.
   One stage: the broadcast, the pitch with a dot per player, or both. Click a Spurs dot -> that player's reel opens in the drawer.
   Dots are matched to the lineup by position as a first guess; use the picker under the stage to correct one. */

const store = {
  get(key, fallback) { try { return localStorage.getItem(key) ?? fallback; } catch (e) { return fallback; } },
  set(key, value) { try { localStorage.setItem(key, value); } catch (e) { /* private mode */ } },
};
const LIVE_URL = new URLSearchParams(location.search).get("live") || store.get("liveUrl", "http://127.0.0.1:8766");
const COMM_URL = store.get("commUrl", "http://127.0.0.1:8767");
const MODES = ["video", "map", "pip", "pipmap"];
const LIVE = {
  tx: { after: 0, lines: [], mentions: [], miss: 0 },
  n: -1, busy: false, miss: 0, timer: null, state: null,
  assign: {}, manual: {}, slot: {}, seen: {}, last: {},
  orient: null, forced: false, picked: null,
};
try { LIVE.assign = JSON.parse(store.get("liveAssign", "{}")); } catch (e) { LIVE.assign = {}; }

const liveRoster = () => {
  const c = state.data.clubs.find((x) => x.id === "thfc");
  return c ? [...c.lineup, ...c.bench] : [];
};
const liveName = (pid) => liveRoster().find((p) => Number(p.id) === Number(pid));
const liveMode = () => { const m = store.get("liveMode", "pip"); return MODES.includes(m) ? m : "pip"; };

function liveSave() {
  store.set("liveAssign", JSON.stringify(LIVE.assign));
  clearTimeout(LIVE.pushT);
  LIVE.pushT = setTimeout(livePush, 150);
}

// tell the tracker which dot is which shirt number, so the numbers also appear on the boxes in the video
function livePush() {
  const labels = {};
  for (const [dot, pid] of Object.entries(LIVE.assign)) { const p = liveName(pid); if (p) labels[dot] = p.number ? "#" + p.number : p.short; }
  fetch(LIVE_URL + "/assign", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ labels }) }).catch(() => {});
}

function liveHtml() {
  const mode = liveMode();
  const seg = [["video", "Video"], ["map", "Dots"], ["pip", "Video + dots"]]
    .map(([m, label]) => `<button type="button" data-mode="${m}" class="${mode === m || (m === "pip" && mode === "pipmap") ? "on" : ""}">${label}</button>`).join("");
  const swap = `<button type="button" class="swap" data-swap title="Switch (M)" aria-label="Switch video and dots">⇄</button>`;
  return `<section class="live">
    <div class="stage-bar">
      <div class="seg" id="live-seg">${seg}</div>
      <button type="button" class="ghost" id="live-menu">Menu</button>
    </div>
    <div class="stage m-${mode}" id="live-stage">
      <div class="live-video"><img id="live-img" alt="" />${swap}<div class="live-badge" id="live-badge">connecting…</div><div class="live-alert" id="live-alert" hidden></div></div>
      <div class="live-pitch-wrap">${swap}
        <div class="live-pitch" id="live-pitch">
          <i class="pl half"></i><i class="pl circle"></i><i class="pl box l"></i><i class="pl box r"></i><i class="pl six l"></i><i class="pl six r"></i>
          <div id="live-dots"></div><div class="live-ball" id="live-ball" hidden></div>
          <div class="live-wait" id="live-wait">Getting ready… finding the pitch</div>
        </div>
      </div>
    </div>
    <div class="live-pick" id="live-pick"></div>
    <div class="live-tx" id="live-tx">
      <div class="tx-head"><b>Commentary</b><span class="tx-dot" id="tx-dot"></span><span class="meta" id="tx-status">connecting…</span>
        <label class="tx-follow"><input type="checkbox" id="tx-follow" checked /> Follow the announcer</label></div>
      <div class="tx-chips" id="tx-chips"></div>
      <div class="tx-lines" id="tx-lines"><p class="meta">Waiting for the commentary…</p></div>
    </div>
  </section>`;
}

// ---------------------------------------------------------------- naming the dots

const LIVE_ALL = [[false, false], [true, false], [false, true], [true, true]];
function liveExpected(p, o) { const along = (p.y - 14) / 72, across = p.x / 100; return { x: o.flipLen ? 1 - along : along, y: o.flipW ? 1 - across : across }; }
function liveDist(a, b) { return Math.hypot((a.x - b.x) * 105, (a.y - b.y) * 68); }

// Keeps a name on every Spurs dot. Players are tracked as slots (last place seen); a dot with no name takes the best free player:
// the one last seen nearest to it, or, for a player not seen yet, the one the lineup graphic expects at that spot.
function liveMatch(spurs) {
  const c = state.data.clubs.find((x) => x.id === "thfc");
  if (!c || !spurs.length) return;
  const now = Date.now(), visible = new Set(spurs.map((d) => String(d.id)));
  let changed = false;
  for (const d of spurs) { const pid = LIVE.assign[d.id]; if (pid != null) LIVE.slot[pid] = { id: String(d.id), x: d.x, y: d.y, t: now }; }
  for (const k of Object.keys(LIVE.assign)) {                                     // forget names on dots that are long gone (the player's slot stays)
    if (visible.has(k)) { LIVE.seen[k] = now; continue; }
    if (now - (LIVE.seen[k] || now) > 8000) { delete LIVE.assign[k]; delete LIVE.seen[k]; changed = true; }
  }
  const starters = c.lineup.filter((p) => p.x != null);
  const starter = (pid) => starters.find((p) => Number(p.id) === Number(pid));
  LIVE.orient = LIVE.orient || { flipLen: false, flipW: false };
  if (!LIVE.forced) {
    // pick the pitch orientation that best explains the names already on dots (unless the user fixed it)
    const named = spurs.filter((d) => LIVE.assign[d.id] != null && starter(LIVE.assign[d.id]));
    if (named.length >= 4) {
      let best = null;
      for (const [flipLen, flipW] of LIVE_ALL) {
        const cost = named.reduce((sum, d) => sum + liveDist(d, liveExpected(starter(LIVE.assign[d.id]), { flipLen, flipW })) ** 2, 0);
        if (!best || cost < best.cost) best = { cost, o: { flipLen, flipW } };
      }
      LIVE.orient = best.o;
    } else if (!Object.keys(LIVE.assign).length && spurs.length >= 5) {          // very first guess: line the dots up against the lineup graphic
      let best = null;
      for (const [flipLen, flipW] of LIVE_ALL) {
        const o = { flipLen, flipW }, used = new Set();
        let cost = 0;
        for (const d of spurs.slice().sort((a, b) => a.x - b.x)) {
          let b = null;
          for (const p of starters) { if (used.has(p.id)) continue; const k = liveDist(d, liveExpected(p, o)); if (!b || k < b.k) b = { p, k }; }
          if (b) { used.add(b.p.id); cost += b.k ** 2; }
        }
        if (!best || cost < best.cost) best = { cost, o };
      }
      LIVE.orient = best.o;
    }
  }
  const taken = new Set(spurs.filter((d) => LIVE.assign[d.id] != null).map((d) => Number(LIVE.assign[d.id])));
  for (const d of spurs.filter((x) => LIVE.assign[x.id] == null)) {
    let b = null;
    for (const p of starters) {
      if (taken.has(Number(p.id))) continue;
      const s = LIVE.slot[p.id];
      if (s && visible.has(s.id)) continue;
      const cost = s
        ? Math.max(0, liveDist(d, s) - 5 * (now - s.t) / 1000)                    // seen before: how far could he have run since
        : 10 + liveDist(d, liveExpected(p, LIVE.orient));                         // never seen: where the lineup puts him
      if (!b || cost < b.cost) b = { p, cost };
    }
    if (b) { LIVE.assign[d.id] = Number(b.p.id); LIVE.seen[d.id] = now; taken.add(Number(b.p.id)); LIVE.slot[b.p.id] = { id: String(d.id), x: d.x, y: d.y, t: now }; changed = true; }
  }
  if (changed) liveSave();
}

// ---------------------------------------------------------------- drawing the stage

function liveDots(st) {
  const box = document.getElementById("live-dots");
  if (!box) return;
  const seen = new Set(), now = Date.now(), players = st.players.slice();
  for (const p of st.players) if (p.team === "tot") LIVE.last[p.id] = { p, t: now };
  const livePids = new Set(st.players.filter((q) => q.team === "tot" && LIVE.assign[q.id] != null).map((q) => Number(LIVE.assign[q.id])));
  for (const [id, g] of Object.entries(LIVE.last)) {                             // a Spurs dot that has just dropped out stays put for a few seconds instead of vanishing
    if (st.players.some((q) => String(q.id) === id)) continue;
    if (now - g.t > 6000 || LIVE.assign[id] == null || livePids.has(Number(LIVE.assign[id]))) { delete LIVE.last[id]; continue; }
    players.push({ ...g.p, faded: true });
  }
  for (const p of players) {
    seen.add(String(p.id));
    let el = box.querySelector(`[data-dot="${p.id}"]`);
    if (!el) { el = document.createElement("button"); el.type = "button"; el.dataset.dot = p.id; box.appendChild(el); }
    const person = p.team === "tot" ? liveName(LIVE.assign[p.id]) : null;
    const photo = person?.thumb || "";
    const label = person ? (person.number ? "#" + person.number : person.short) : "";
    el.className = `dot ${p.team}${photo ? " photo" : ""}${p.faded ? " faded" : ""}${LIVE.picked === String(p.id) ? " sel" : ""}`;
    el.style.left = p.x * 100 + "%";
    el.style.top = p.y * 100 + "%";
    if (el.dataset.label !== label || el.dataset.photo !== photo) {
      el.dataset.label = label; el.dataset.photo = photo;
      el.style.backgroundImage = photo ? `url("${photo}")` : "";
      el.innerHTML = label ? `<span>${esc(label)}</span>` : "";
    }
    el.title = person ? person.short : { tot: "Spurs — click to say who", mnu: "Man United" }[p.team] || "Official";
  }
  box.querySelectorAll("[data-dot]").forEach((el) => { if (!seen.has(el.dataset.dot)) el.remove(); });
  const ball = document.getElementById("live-ball");
  if (ball) {
    ball.hidden = !st.ball;
    if (st.ball) { ball.style.left = st.ball.x * 100 + "%"; ball.style.top = st.ball.y * 100 + "%"; }
  }
}

function liveAlerts(st) {
  const box = document.getElementById("live-alert");
  const al = (st.alerts || []).at(-1);
  document.querySelectorAll("#live-dots .dot.hot").forEach((el) => el.classList.remove("hot"));
  if (!box) return;
  box.hidden = !al;
  if (!al) return;
  box.innerHTML = `<b>${esc(al.title)}</b><span>${esc(al.detail)}</span>`;
  for (const id of al.ids || []) document.querySelector(`#live-dots [data-dot="${id}"]`)?.classList.add("hot");
}

function livePicker(message) {
  const holder = document.getElementById("live-pick");
  if (!holder) return;
  const flips = `<span class="live-flips"><button type="button" class="ghost" data-live-flip="len">Swap ends</button><button type="button" class="ghost" data-live-flip="w">Swap sides</button></span>`;
  if (message) { holder.innerHTML = `${flips}<span class="meta">${message}</span>`; return; }
  if (LIVE.picked == null) { holder.innerHTML = `${flips}<span class="meta">Shirt numbers are a first guess from position. Click a Spurs dot to fix it or open that player's reel.</span>`; return; }
  const cur = LIVE.assign[LIVE.picked];
  const opts = liveRoster().map((p) => `<option value="${p.id}" ${Number(cur) === Number(p.id) ? "selected" : ""}>${esc(p.number ? "#" + p.number + " " : "")}${esc(p.short)}</option>`).join("");
  holder.innerHTML = `${flips}<label class="meta">This dot is <select id="live-who"><option value="">— pick —</option>${opts}</select></label>`;
}

// every clip of the focused player, under the reel in the drawer
function liveClips() {
  const drawer = document.getElementById("reel");
  const focus = focused();
  if (!drawer || !focus) return;
  const list = playerPlays(focus.id).filter((pl) => pl.mode !== "context");
  const rows = list.slice(0, 40).map((pl) => `<button type="button" class="reel-pick" data-live-clip="${esc(pl.id)}"><b>▶</b><span>${esc(titleOf(pl))}</span><em>${esc(pl.action_plain || "")}</em></button>`).join("");
  drawer.insertAdjacentHTML("beforeend", `<div class="live-clips"><div class="kicker">All clips with ${esc(focus.short)} (${list.length})</div>
    <div class="reel-stage"><video id="live-clip-video" controls playsinline></video></div>
    <div class="reel-picks">${rows || '<p class="meta">No clips in the library for this player yet.</p>'}</div></div>`);
}

function liveApply(st) {
  LIVE.miss = 0;
  LIVE.state = st;
  const badge = document.getElementById("live-badge"), wait = document.getElementById("live-wait");
  if (badge) badge.textContent = !st.ready ? "getting ready" : st.cutaway ? "off the main camera" : "live";
  if (wait) { wait.hidden = st.ready && !st.cutaway; wait.textContent = !st.ready ? "Getting ready… finding the pitch" : "Waiting for the main camera…"; }
  if (!st.ready) return;
  if (state.data) liveMatch(st.players.filter((p) => p.team === "tot"));
  liveDots(st);
  liveAlerts(st);
  liveClipTx(st);
}

// The picture and the dots are applied in the same step: fetch the numbered frame that belongs to this state, then draw both.
function liveTick() {
  if (state.tab !== "live" || !document.getElementById("live-dots") || LIVE.busy) return;
  LIVE.busy = true;
  fetch(LIVE_URL + "/state.json", { cache: "no-store" }).then((r) => r.json()).then(async (st) => {
    const img = document.getElementById("live-img");
    if (st.n && st.n === LIVE.n) return;                                         // nothing new yet
    if (st.n && img && !LIVE.noFrames) {
      const r = await fetch(`${LIVE_URL}/frame/${st.n}.jpg`, { cache: "no-store" });
      if (r.ok) {
        const url = URL.createObjectURL(await r.blob());
        img.src = url;
        try { await img.decode(); } catch (e) { /* draw anyway */ }
        if (LIVE.url) URL.revokeObjectURL(LIVE.url);
        LIVE.url = url;
      } else if (r.status === 404 && !LIVE.n) { LIVE.noFrames = true; img.src = LIVE_URL + "/video.mjpg"; }
    } else if (!st.n && img && !img.src) img.src = LIVE_URL + "/video.mjpg";
    LIVE.n = st.n || 0;
    liveApply(st);
  }).catch((err) => {
    if (!(err instanceof TypeError && /fetch/i.test(err.message))) console.error("live tick failed:", err);
    if (++LIVE.miss > 20) { const badge = document.getElementById("live-badge"); if (badge) badge.textContent = "no live feed at " + LIVE_URL; }
  }).finally(() => { LIVE.busy = false; });
}

// ---------------------------------------------------------------- announcer transcript

let LIVE_NAMES = null;
const plainText = (x) => String(x || "").normalize("NFD").replace(/[̀-ͯ]/g, "");

function liveNameIndex() {
  if (LIVE_NAMES || !state.data) return LIVE_NAMES || [];
  const out = [], seen = new Set();
  for (const p of liveRoster()) {
    const short = plainText(p.short).toLowerCase(), name = plainText(p.name).toLowerCase();
    for (const f of new Set([short, name, name.split(/\s+/).pop(), short.split(/\s+/).pop()])) {
      if (f.length < 3 || seen.has(f)) continue;
      seen.add(f);
      out.push({ p, re: new RegExp("\\b" + f.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+") + "(?:'s)?\\b", "gi") });
    }
  }
  return (LIVE_NAMES = out);
}

function liveFindNames(text) {
  const plain = plainText(text), hits = [];
  for (const n of liveNameIndex()) { n.re.lastIndex = 0; let m; while ((m = n.re.exec(plain))) hits.push({ at: m.index, len: m[0].length, p: n.p }); }
  hits.sort((a, b) => a.at - b.at || b.len - a.len);
  const clean = [];
  let end = -1;
  for (const h of hits) if (h.at >= end) { clean.push(h); end = h.at + h.len; }
  return { plain, hits: clean };
}

function liveFocusPlayer(p) {
  focusPlayer(p.id);
  const v = document.getElementById("reel-video");
  if (v) { v.muted = true; v.play?.().catch(() => {}); }
}

function liveChips() {
  const box = document.getElementById("tx-chips");
  if (!box) return;
  box.innerHTML = LIVE.tx.mentions.length
    ? `<span class="meta">Just named</span>` + LIVE.tx.mentions.map(({ p }) => `<button type="button" class="tx-chip ${Number(state.focus) === Number(p.id) ? "on" : ""}" data-who="${p.id}">${p.thumb ? `<img src="${esc(p.thumb)}" alt="" />` : ""}${esc(p.short)}</button>`).join("")
    : `<span class="meta">Players the announcer names will show up here, with their clips on the right.</span>`;
}

function liveTxRender() {
  const box = document.getElementById("tx-lines");
  if (!box) return;
  const stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
  box.innerHTML = LIVE.tx.lines.slice(-40).map((l) => {
    let html = "", at = 0;
    for (const h of l.hits) { html += esc(l.plain.slice(at, h.at)) + `<mark data-who="${h.p.id}">${esc(l.plain.slice(h.at, h.at + h.len))}</mark>`; at = h.at + h.len; }
    html += esc(l.plain.slice(at));
    const time = l.label || new Date(l.t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    return `<p class="${l.fresh ? "fresh" : ""}"><time>${time}</time> ${html}</p>`;
  }).join("") || '<p class="meta">Waiting for the commentary…</p>';
  if (stick) box.scrollTop = box.scrollHeight;
  for (const l of LIVE.tx.lines) l.fresh = false;
}

// adds one line; returns the last player it names
function liveAddLine(text, t, label) {
  const { plain, hits } = liveFindNames(text);
  LIVE.tx.lines.push({ t, plain, hits, fresh: true, label });
  for (const h of hits) LIVE.tx.mentions = [...LIVE.tx.mentions.filter((m) => m.p.id !== h.p.id), { p: h.p }];
  LIVE.tx.mentions = LIVE.tx.mentions.slice(-6);
  return hits.at(-1)?.p || null;
}

function liveAfterLines(last) {
  liveTxRender();
  const follow = document.getElementById("tx-follow");
  if (last && (!follow || follow.checked) && Number(state.focus) !== Number(last.id)) liveFocusPlayer(last);
  liveChips();
}

const fmtClip = (x) => Math.floor(x / 60) + ":" + String(Math.floor(x % 60)).padStart(2, "0");

// Twelve Labs transcript of the demo clip: lines appear as the video reaches them, and start over when the loop does
function liveClipTx(st) {
  const T = LIVE.tx.clip, tx = LIVE.tx;
  if (!T || !st.clip) return;
  const pos = st.clip.pos;
  if (pos < (tx.lastPos ?? 0) - 2) { tx.lines = []; tx.shown = 0; liveTxRender(); }
  tx.lastPos = pos;
  tx.shown = tx.shown || 0;
  let last = null, any = false;
  while (tx.shown < T.length && T[tx.shown].start <= pos) { const s = T[tx.shown++]; last = liveAddLine(s.text, 0, fmtClip(s.start)) || last; any = true; }
  if (any) liveAfterLines(last);
}

function liveTxTick() {
  if (state.tab !== "live" || !document.getElementById("live-tx")) return;
  const dot = document.getElementById("tx-dot"), status = document.getElementById("tx-status");
  const say = (text, on) => { if (status) status.textContent = text; if (dot) dot.className = "tx-dot" + (on ? " on" : ""); };
  if (LIVE.tx.clip) return say("Twelve Labs transcript", true);
  fetch(`${COMM_URL}/clip_transcript.json`, { cache: "no-store" }).then((r) => r.json()).then((d) => {
    if (d.sentences?.length) { Object.assign(LIVE.tx, { clip: d.sentences, shown: 0, lines: [], lastPos: 0 }); say("Twelve Labs transcript", true); }
    else say(d.ready ? "no speech found in the clip" : "waiting for the Twelve Labs transcript…", false);
  }).catch(() => {});
  // live recogniser, used when there is no clip transcript
  fetch(`${COMM_URL}/transcript.json?after=${LIVE.tx.after}`, { cache: "no-store" }).then((r) => r.json()).then((d) => {
    if (LIVE.tx.clip) return;
    LIVE.tx.miss = 0;
    say(d.ready ? "listening" : "starting the recogniser…", true);
    let last = null, any = false;
    for (const seg of d.segments || []) {
      if (seg.id <= LIVE.tx.after) continue;
      LIVE.tx.after = seg.id;
      last = liveAddLine(seg.text, seg.t) || last;
      any = true;
    }
    if (any) liveAfterLines(last);
  }).catch(() => { if (++LIVE.tx.miss > 3 && !LIVE.tx.clip) say("no commentary feed — run commentary.py", false); });
}

function mountLive() {
  livePicker();
  liveClips();
  liveChips();
  liveTxRender();
  if (!LIVE.timer) { LIVE.timer = setInterval(liveTick, 40); setInterval(liveTxTick, 1000); }
}

// ---------------------------------------------------------------- stage modes: video, map, video with map inset (pip), map with video inset (pipmap)

function liveSetMode(m) {
  const st = document.getElementById("live-stage");
  if (!st) return;
  st.className = "stage m-" + m;
  document.querySelectorAll("#live-seg button").forEach((x) => x.classList.toggle("on", x.dataset.mode === (m === "pipmap" ? "pip" : m)));
  store.set("liveMode", m);
}

function liveFlip() {
  const st = document.getElementById("live-stage");
  if (!st) return;
  const cur = MODES.find((m) => st.classList.contains("m-" + m));
  liveSetMode({ video: "map", map: "video", pip: "pipmap", pipmap: "pip" }[cur] || "pip");
}

// ---------------------------------------------------------------- events (capture phase, ahead of the desk's own click handler)

document.addEventListener("click", (event) => {
  if (state.tab !== "live") return;
  const hit = (selector) => event.target.closest?.(selector);
  const stop = () => { event.preventDefault(); event.stopPropagation(); };
  let el;
  if ((el = hit("[data-dot]"))) {
    stop();
    LIVE.picked = el.dataset.dot;
    document.querySelectorAll("#live-dots .dot").forEach((x) => x.classList.toggle("sel", x === el));
    if (!el.classList.contains("tot")) return livePicker("Only Spurs dots open a reel.");
    livePicker();
    const pid = LIVE.assign[LIVE.picked];
    if (pid != null) focusPlayer(pid);
  } else if ((el = hit("[data-live-clip]"))) {
    stop();
    const play = state.data.plays.find((pl) => String(pl.id) === el.dataset.liveClip);
    const video = document.getElementById("live-clip-video");
    if (!play || !video) return;
    const angle = chosenAngle(play), slice = sliceOf(angle), src = angle?.video || "";
    document.getElementById("reel-video")?.pause();
    video.ontimeupdate = () => { if (slice.end && video.currentTime >= slice.end - 0.05) { video.pause(); video.ontimeupdate = null; } };
    video.onloadedmetadata = () => { try { video.currentTime = slice.start || 0; } catch (e) { /* not seekable */ } video.play().catch(() => {}); };
    if (video.getAttribute("src") !== src) video.src = src;
    else { video.currentTime = slice.start || 0; video.play().catch(() => {}); }
    document.querySelectorAll("[data-live-clip]").forEach((x) => x.classList.toggle("on", x === el));
  } else if ((el = hit("[data-live-flip]"))) {
    stop();
    LIVE.forced = true;
    LIVE.orient = LIVE.orient || { flipLen: false, flipW: false };
    if (el.dataset.liveFlip === "len") LIVE.orient.flipLen = !LIVE.orient.flipLen;
    else LIVE.orient.flipW = !LIVE.orient.flipW;
    for (const k of Object.keys(LIVE.assign)) if (!LIVE.manual[LIVE.assign[k]]) delete LIVE.assign[k];   // keep only names you set by hand, redo the rest
    LIVE.slot = {};
    liveSave();
    if (LIVE.state) { liveMatch(LIVE.state.players.filter((p) => p.team === "tot")); liveDots(LIVE.state); }
  } else if ((el = hit("[data-who]"))) {
    const p = liveName(el.dataset.who);
    if (p) { liveFocusPlayer(p); liveChips(); }
  } else if ((el = hit("#live-seg [data-mode]"))) {
    const inPipmap = document.getElementById("live-stage")?.classList.contains("m-pipmap");
    liveSetMode(el.dataset.mode === "pip" && inPipmap ? "pipmap" : el.dataset.mode);
  } else if (hit("#live-menu")) document.body.classList.toggle("show-nav");
  else if (hit("[data-swap]")) { event.preventDefault(); liveFlip(); }
  else if (hit(".stage.m-pipmap .live-video")) liveSetMode("pip");           // the small inset picture swaps places with the big one
}, true);

document.addEventListener("change", (event) => {
  if (event.target.id !== "live-who") return;
  const pid = event.target.value;
  if (!pid || LIVE.picked == null) return;
  for (const k of Object.keys(LIVE.assign)) if (Number(LIVE.assign[k]) === Number(pid) && k !== LIVE.picked) delete LIVE.assign[k];
  const dot = LIVE.state?.players.find((q) => String(q.id) === LIVE.picked);
  LIVE.assign[LIVE.picked] = Number(pid);
  LIVE.manual[pid] = true;
  LIVE.slot[pid] = { id: LIVE.picked, x: dot?.x ?? 0.5, y: dot?.y ?? 0.5, t: Date.now() };
  liveSave();
  focusPlayer(pid);
  if (LIVE.state) liveDots(LIVE.state);
});

document.addEventListener("keydown", (event) => {
  if (state.tab !== "live" || event.key.toLowerCase() !== "m" || /input|textarea|select/i.test(event.target.tagName) || event.metaKey || event.ctrlKey) return;
  liveFlip();
});
