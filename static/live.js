/* LIVE DOTS. The live tracking feed (hack_live_dots.py --serve 8766) shown inside the Next Post desk.
   Left: the broadcast with boxes. Right: the pitch with a dot per player. Click a Spurs dot -> that player's reel opens in the drawer.
   Dots are matched to the lineup by position as a first guess; use the picker under the pitch to correct one. */

const LIVE_URL = (new URLSearchParams(location.search).get("live")) || localStorage.getItem("liveUrl") || "http://127.0.0.1:8766";
const COMM_URL = (() => { try { return localStorage.getItem("commUrl") || "http://127.0.0.1:8767"; } catch (e) { return "http://127.0.0.1:8767"; } })();
const LIVE = { tx: { after: 0, lines: [], mentions: [], miss: 0 }, n: -1, busy: false, slot: {}, seen: {}, last: {}, forced: false, manual: {}, orient: null, state: null, ok: false, assign: {}, picked: null, guessed: false, timer: null, miss: 0 };
try { LIVE.assign = JSON.parse(localStorage.getItem("liveAssign") || "{}"); } catch (e) { LIVE.assign = {}; }

function liveSave() {
  try { localStorage.setItem("liveAssign", JSON.stringify(LIVE.assign)); } catch (e) {}
  clearTimeout(LIVE.pushT); LIVE.pushT = setTimeout(livePush, 150);
}

function livePush() {
  // tell the tracker which dot is which shirt number, so the numbers also appear on the boxes in the video
  const labels = {};
  for (const [dot, pid] of Object.entries(LIVE.assign)) { const p = liveName(pid); if (p) labels[dot] = p.number ? "#" + p.number : p.short; }
  fetch(LIVE_URL + "/assign", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ labels }) }).catch(() => {});
}

function liveRoster() {
  const c = state.data.clubs.find((x) => x.id === "thfc");
  return c ? [...c.lineup, ...c.bench] : [];
}

function livePitchLines() {
  return `<i class="pl half"></i><i class="pl circle"></i><i class="pl box l"></i><i class="pl box r"></i><i class="pl six l"></i><i class="pl six r"></i>`;
}

function liveHtml() {
  const mode = (() => { try { return localStorage.getItem("liveMode") === "map" ? "map" : "video"; } catch (e) { return "video"; } })();
  return `<section class="live">
    <div class="stage-bar">
      <div class="seg" id="live-seg">
        <button type="button" data-mode="video" class="${mode === "video" ? "on" : ""}">Video</button>
        <button type="button" data-mode="map" class="${mode === "map" ? "on" : ""}">Dots</button>
      </div>
      <button type="button" class="ghost" id="live-menu">Menu</button>
    </div>
    <div class="stage m-${mode}" id="live-stage">
      <div class="live-video"><img id="live-img" alt="" /><button type="button" class="swap" data-swap title="Switch (M)">⇄</button><div class="live-badge" id="live-badge">connecting…</div><div class="live-alert" id="live-alert" hidden></div></div>
      <div class="live-pitch-wrap"><button type="button" class="swap" data-swap title="Switch (M)">⇄</button>
        <div class="live-pitch" id="live-pitch">${livePitchLines()}<div id="live-dots"></div><div class="live-ball" id="live-ball" hidden></div>
          <div class="live-wait" id="live-wait">Getting ready… finding the pitch</div></div>
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

const LIVE_ALL = [[false, false], [true, false], [false, true], [true, true]];
function liveExpected(p, o) { const along = (p.y - 14) / 72, across = p.x / 100; return { x: o.flipLen ? 1 - along : along, y: o.flipW ? 1 - across : across }; }
function liveDist(a, b) { return Math.hypot((a.x - b.x) * 105, (a.y - b.y) * 68); }

function liveMatch(spurs) {
  // Keeps a name on every Spurs dot. Players are tracked as slots (last place seen); a dot with no name takes the best free player:
  // the one last seen nearest to it, or, for a player not seen yet, the one the lineup graphic expects at that spot.
  const c = state.data.clubs.find((x) => x.id === "thfc");
  if (!c || !spurs.length) return;
  const now = Date.now(), visible = new Set(spurs.map((d) => String(d.id))); let changed = false;
  for (const d of spurs) { const pid = LIVE.assign[d.id]; if (pid != null) LIVE.slot[pid] = { id: String(d.id), x: d.x, y: d.y, t: now }; }
  for (const k of Object.keys(LIVE.assign)) {                                   // forget names on dots that are long gone (the player's slot stays)
    if (visible.has(k)) { LIVE.seen[k] = now; continue; }
    if (now - (LIVE.seen[k] || now) > 8000) { delete LIVE.assign[k]; delete LIVE.seen[k]; changed = true; }
  }
  const starters = c.lineup.filter((p) => p.x != null);
  if (!LIVE.orient) LIVE.orient = { flipLen: false, flipW: false };
  const unnamed = spurs.filter((d) => LIVE.assign[d.id] == null);
  // pick the pitch orientation that best explains the names already on dots (unless the user fixed it)
  if (!LIVE.forced) {
    const named = spurs.filter((d) => LIVE.assign[d.id] != null && starters.some((p) => Number(p.id) === Number(LIVE.assign[d.id])));
    const pool = named.length >= 4 ? named : (LIVE.assignedAny ? [] : []);
    if (pool.length >= 4) {
      let best = null;
      for (const [fl, fw] of LIVE_ALL) {
        let cost = 0; for (const d of pool) { const e = liveExpected(starters.find((p) => Number(p.id) === Number(LIVE.assign[d.id])), { flipLen: fl, flipW: fw }); cost += liveDist(d, e) ** 2; }
        if (!best || cost < best.cost) best = { cost, fl, fw };
      }
      LIVE.orient = { flipLen: best.fl, flipW: best.fw };
    } else if (!Object.keys(LIVE.assign).length && spurs.length >= 5) {            // very first guess: line the dots up against the lineup graphic
      let best = null;
      for (const [fl, fw] of LIVE_ALL) {
        const o = { flipLen: fl, flipW: fw }, used = new Set(); let cost = 0;
        for (const d of spurs.slice().sort((a, b) => a.x - b.x)) { let b = null; for (const p of starters) { if (used.has(p.id)) continue; const k = liveDist(d, liveExpected(p, o)); if (!b || k < b.k) b = { p, k }; } if (b) { used.add(b.p.id); cost += b.k ** 2; } }
        if (!best || cost < best.cost) best = { cost, o };
      }
      LIVE.orient = best.o;
    }
  }
  const taken = new Set(spurs.filter((d) => LIVE.assign[d.id] != null).map((d) => Number(LIVE.assign[d.id])));
  for (const d of unnamed) {
    let b = null;
    for (const p of starters) {
      if (taken.has(Number(p.id))) continue;
      const s = LIVE.slot[p.id]; let cost;
      if (s && !visible.has(s.id)) cost = Math.max(0, liveDist(d, s) - 5 * (now - s.t) / 1000);         // seen before: how far could he have run since
      else if (s) continue;
      else cost = 10 + liveDist(d, liveExpected(p, LIVE.orient));                                            // never seen: where the lineup puts him
      if (!b || cost < b.cost) b = { p, cost };
    }
    if (b) { LIVE.assign[d.id] = Number(b.p.id); LIVE.seen[d.id] = now; taken.add(Number(b.p.id)); LIVE.slot[b.p.id] = { id: String(d.id), x: d.x, y: d.y, t: now }; changed = true; }
  }
  if (changed) liveSave();
}

function liveName(pid) { return liveRoster().find((p) => Number(p.id) === Number(pid)); }

function liveDots(st) {
  const box = document.getElementById("live-dots");
  if (!box) return;
  const seen = new Set(), now = Date.now();
  const players = st.players.slice();
  for (const p of st.players) if (p.team === "tot") LIVE.last[p.id] = { p, t: now };
  const livePids = new Set(st.players.filter((q) => q.team === "tot" && LIVE.assign[q.id] != null).map((q) => Number(LIVE.assign[q.id])));
  for (const [id, g] of Object.entries(LIVE.last)) {                       // a Spurs dot that has just dropped out stays put for a few seconds instead of vanishing
    if (st.players.some((q) => String(q.id) === id)) continue;
    if (now - g.t > 6000 || LIVE.assign[id] == null || livePids.has(Number(LIVE.assign[id]))) { delete LIVE.last[id]; continue; }
    players.push({ ...g.p, ghost: true });
  }
  for (const p of players) {
    seen.add(String(p.id));
    let el = box.querySelector(`[data-dot="${p.id}"]`);
    if (!el) { el = document.createElement("button"); el.type = "button"; el.dataset.dot = p.id; box.appendChild(el); }
    const person0 = p.team === "tot" ? liveName(LIVE.assign[p.id]) : null;
    el.className = "dot " + p.team + (person0 && person0.thumb ? " photo" : "") + (p.ghost ? " ghost" : "") + (LIVE.picked === String(p.id) ? " sel" : "");
    el.style.left = (p.x * 100) + "%"; el.style.top = (p.y * 100) + "%";
    const person = p.team === "tot" ? liveName(LIVE.assign[p.id]) : null;
    const label = person ? (person.number ? "#" + person.number : person.short) : "";
    const photo = person && person.thumb ? person.thumb : "";
    if (el.dataset.label !== label || el.dataset.photo !== photo) {
      el.dataset.label = label; el.dataset.photo = photo;
      el.style.backgroundImage = photo ? `url("${photo}")` : "";
      el.innerHTML = label ? `<span>${esc(label)}</span>` : "";
    }
    el.title = person ? person.short : (p.team === "tot" ? "Spurs — click to say who" : p.team === "mnu" ? "Man United" : "Official");
  }
  box.querySelectorAll("[data-dot]").forEach((el) => { if (!seen.has(el.dataset.dot)) el.remove(); });
  const ball = document.getElementById("live-ball");
  if (ball) { if (st.ball) { ball.hidden = false; ball.style.left = (st.ball.x * 100) + "%"; ball.style.top = (st.ball.y * 100) + "%"; } else ball.hidden = true; }
}

function liveAlerts(st) {
  const box = document.getElementById("live-alert");
  const al = (st.alerts || [])[st.alerts.length - 1];
  document.querySelectorAll("#live-dots .dot.hot").forEach((el) => el.classList.remove("hot"));
  if (!box) return;
  if (!al) { box.hidden = true; return; }
  box.hidden = false; box.innerHTML = `<b>${esc(al.title)}</b><span>${esc(al.detail)}</span>`;
  for (const id of al.ids || []) document.querySelector(`#live-dots [data-dot="${id}"]`)?.classList.add("hot");
}

function livePicker() {
  const holder = document.getElementById("live-pick");
  if (!holder) return;
  const flips = `<span class="live-flips"><button type="button" class="ghost" data-live-flip="len">Swap ends</button><button type="button" class="ghost" data-live-flip="w">Swap sides</button></span>`;
  if (LIVE.picked == null) { holder.innerHTML = `${flips}<span class="meta">Check the names before kick-off: the shirt numbers are a first guess from position. Click any Spurs dot to fix it or open that player's reel.</span>`; return; }
  const cur = LIVE.assign[LIVE.picked];
  const opts = liveRoster().map((p) => `<option value="${p.id}" ${Number(cur) === Number(p.id) ? "selected" : ""}>${esc(p.number ? "#" + p.number + " " : "")}${esc(p.short)}</option>`).join("");
  holder.innerHTML = `${flips}<label class="meta">This dot is <select id="live-who"><option value="">— pick —</option>${opts}</select></label>`;
}

function liveClips() {
  const drawer = document.getElementById("reel");
  if (!drawer) return;
  drawer.querySelector(".live-clips")?.remove();
  const focus = people().find((p) => p && p.short && Number(p.id) === Number(state.focus));
  if (!focus) return;
  const list = playerPlays(focus.id).filter((pl) => pl.mode !== "context");
  const rows = list.slice(0, 40).map((pl) => `<button type="button" class="reel-pick" data-live-clip="${esc(pl.id)}"><b>▶</b><span>${esc(titleOf(pl))}</span><em>${esc(pl.action_plain || "")}</em></button>`).join("");
  drawer.insertAdjacentHTML("beforeend", `<div class="live-clips"><div class="kicker" style="margin-top:16px">All clips with ${esc(focus.short)} (${list.length})</div>
    <div class="reel-stage"><video id="live-clip-video" controls playsinline></video></div>
    <div class="reel-picks">${rows || '<p class="meta">No clips in the library for this player yet.</p>'}</div></div>`);
}

function liveSheet() {
  const side = document.querySelector(".desk-side");
  if (!side) return;
  const holder = document.createElement("div"); holder.innerHTML = sheetHtml();
  side.replaceWith(holder.firstElementChild);
  const desk = document.querySelector(".desk");
  const open = people().some((person) => Number(person.id) === Number(state.focus));
  if (desk) desk.classList.toggle("with-reel", open);
  bindPlayers(); mountReel(); liveClips();
}

function liveApply(st) {
  LIVE.miss = 0; LIVE.state = st;
  const badge = document.getElementById("live-badge"), wait = document.getElementById("live-wait");
  if (badge) badge.textContent = !st.ready ? "getting ready" : st.cutaway ? "off the main camera" : "live";
  if (wait) { wait.hidden = st.ready && !st.cutaway; wait.textContent = !st.ready ? "Getting ready… finding the pitch" : "Waiting for the main camera…"; }
  if (!st.ready) return;
  const spurs = st.players.filter((p) => p.team === "tot");
  if (state.data) liveMatch(spurs);
  liveDots(st); liveAlerts(st);
}

function liveTick() {
  // The picture and the dots are applied in the same step: fetch the numbered frame that belongs to this state, then draw both.
  if (state.tab !== "live" || !document.getElementById("live-dots") || LIVE.busy) return;
  LIVE.busy = true;
  fetch(LIVE_URL + "/state.json", { cache: "no-store" }).then((r) => r.json()).then(async (st) => {
    const img = document.getElementById("live-img");
    if (st.n && st.n === LIVE.n) return;                              // nothing new yet
    if (st.n && img && !LIVE.noFrames) {
      const r = await fetch(`${LIVE_URL}/frame/${st.n}.jpg`, { cache: "no-store" });
      if (r.ok) {
        const url = URL.createObjectURL(await r.blob());
        img.src = url; try { await img.decode(); } catch (e) { /* draw anyway */ }
        if (LIVE.url) URL.revokeObjectURL(LIVE.url); LIVE.url = url;
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
function liveNameIndex() {
  if (LIVE_NAMES || !state.data) return LIVE_NAMES || [];
  const strip = (x) => String(x || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
  const out = [], seen = new Set();
  for (const p of liveRoster()) {
    const forms = new Set([strip(p.short), strip(p.name), strip(p.name).split(/\s+/).pop(), strip(p.short).split(/\s+/).pop()]);
    for (const f of forms) { if (f.length < 3 || seen.has(f)) continue; seen.add(f); out.push({ f, p, re: new RegExp("\\b" + f.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+") + "(?:'s)?\\b", "gi") }); }
  }
  return (LIVE_NAMES = out);
}
function liveFindNames(text) {
  const plain = String(text).normalize("NFD").replace(/[\u0300-\u036f]/g, ""), hits = [];
  for (const n of liveNameIndex()) { n.re.lastIndex = 0; let m; while ((m = n.re.exec(plain))) hits.push({ at: m.index, len: m[0].length, p: n.p }); }
  hits.sort((a, b) => a.at - b.at || b.len - a.len);
  const clean = []; let end = -1; for (const h of hits) if (h.at >= end) { clean.push(h); end = h.at + h.len; }
  return { plain, hits: clean };
}
function liveFocusPlayer(p, why) {
  state.focus = Number(p.id); state.reelCut = 0; liveSheet();
  const v = document.getElementById("reel-video"); if (v) { v.muted = true; v.play?.().catch(() => {}); }
}
function liveChips() {
  const box = document.getElementById("tx-chips"); if (!box) return;
  box.innerHTML = LIVE.tx.mentions.length
    ? `<span class="meta">Just named</span>` + LIVE.tx.mentions.map((m) => `<button type="button" class="tx-chip ${Number(state.focus) === Number(m.p.id) ? "on" : ""}" data-who="${m.p.id}">${m.p.thumb ? `<img src="${m.p.thumb}" alt="" />` : ""}${esc(m.p.short)}</button>`).join("")
    : `<span class="meta">Players the announcer names will show up here, with their clips on the right.</span>`;
}
function liveTxRender() {
  const box = document.getElementById("tx-lines"); if (!box) return;
  const stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 30;
  box.innerHTML = LIVE.tx.lines.slice(-40).map((l) => {
    let html = "", at = 0;
    for (const h of l.hits) { html += esc(l.plain.slice(at, h.at)) + `<mark data-who="${h.p.id}">${esc(l.plain.slice(h.at, h.at + h.len))}</mark>`; at = h.at + h.len; }
    html += esc(l.plain.slice(at));
    return `<p class="${l.fresh ? "fresh" : ""}"><time>${new Date(l.t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</time> ${html}</p>`;
  }).join("") || '<p class="meta">Waiting for the commentary…</p>';
  if (stick) box.scrollTop = box.scrollHeight;
  for (const l of LIVE.tx.lines) l.fresh = false;
}
function liveTxTick() {
  if (state.tab !== "live" || !document.getElementById("live-tx")) return;
  const dot = document.getElementById("tx-dot"), st = document.getElementById("tx-status");
  fetch(`${COMM_URL}/transcript.json?after=${LIVE.tx.after}`, { cache: "no-store" }).then((r) => r.json()).then((d) => {
    LIVE.tx.miss = 0; if (dot) dot.className = "tx-dot on"; if (st) st.textContent = d.ready ? "listening" : "starting the recogniser…";
    let changed = false, last = null;
    for (const seg of d.segments || []) {
      if (seg.id <= LIVE.tx.after) continue;
      LIVE.tx.after = seg.id;
      const { plain, hits } = liveFindNames(seg.text);
      LIVE.tx.lines.push({ t: seg.t, plain, hits, fresh: true }); changed = true;
      for (const h of hits) { LIVE.tx.mentions = LIVE.tx.mentions.filter((m) => m.p.id !== h.p.id); LIVE.tx.mentions.push({ p: h.p, t: Date.now() }); last = h.p; }
    }
    LIVE.tx.mentions = LIVE.tx.mentions.slice(-6);
    if (changed) { liveTxRender(); if (last) { const follow = document.getElementById("tx-follow"); if (!follow || follow.checked) { if (Number(state.focus) !== Number(last.id)) liveFocusPlayer(last); } } liveChips(); }
  }).catch(() => { if (++LIVE.tx.miss > 3) { if (dot) dot.className = "tx-dot"; if (st) st.textContent = "no commentary feed — run commentary.py"; } });
}

function mountLive() {
  livePicker(); liveClips();
  liveChips();
  if (!LIVE.timer) { LIVE.timer = setInterval(liveTick, 40); setInterval(liveTxTick, 1000); }
}

document.addEventListener("click", (event) => {
  const dot = event.target.closest?.("[data-dot]");
  if (!dot || state.tab !== "live") return;
  event.preventDefault(); event.stopPropagation();
  LIVE.picked = dot.dataset.dot;
  const pid = LIVE.assign[LIVE.picked];
  const isSpurs = dot.classList.contains("tot");
  if (isSpurs && pid != null) { state.focus = Number(pid); state.reelCut = 0; liveSheet(); }
  document.querySelectorAll("#live-dots .dot").forEach((el) => el.classList.toggle("sel", el === dot));
  if (isSpurs) livePicker(); else { const h = document.getElementById("live-pick"); if (h) h.innerHTML = `<span class="meta">Only Spurs dots open a reel.</span>`; }
}, true);

document.addEventListener("change", (event) => {
  if (event.target.id !== "live-who") return;
  const pid = event.target.value;
  if (!pid || LIVE.picked == null) return;
  for (const k of Object.keys(LIVE.assign)) if (Number(LIVE.assign[k]) === Number(pid) && k !== LIVE.picked) delete LIVE.assign[k];
  LIVE.assign[LIVE.picked] = Number(pid); LIVE.manual[pid] = true; LIVE.slot[pid] = { id: LIVE.picked, x: (LIVE.state?.players.find((q) => String(q.id) === LIVE.picked)?.x) ?? 0.5, y: (LIVE.state?.players.find((q) => String(q.id) === LIVE.picked)?.y) ?? 0.5, t: Date.now() }; liveSave();
  state.focus = Number(pid); state.reelCut = 0; liveSheet();
  if (LIVE.state) liveDots(LIVE.state);
});

document.addEventListener("click", (event) => {
  const b = event.target.closest?.("[data-live-clip]");
  if (!b) return;
  event.preventDefault(); event.stopPropagation();
  const play = state.data.plays.find((pl) => String(pl.id) === b.dataset.liveClip);
  const video = document.getElementById("live-clip-video");
  if (!play || !video) return;
  const angle = chosenAngle(play), slice = sliceOf(angle);
  document.getElementById("reel-video")?.pause();
  video.ontimeupdate = () => { if (slice.end && video.currentTime >= slice.end - 0.05) { video.pause(); video.ontimeupdate = null; } };
  video.onloadedmetadata = () => { try { video.currentTime = slice.start || 0; } catch (e) {} video.play().catch(() => {}); };
  const src = angle?.video || "";
  if (video.getAttribute("src") !== src) video.src = src; else { video.currentTime = slice.start || 0; video.play().catch(() => {}); }
  document.querySelectorAll("[data-live-clip]").forEach((x) => x.classList.toggle("on", x === b));
}, true);

document.addEventListener("click", (event) => {
  const f = event.target.closest?.("[data-live-flip]");
  if (!f) return;
  event.preventDefault();
  LIVE.forced = true; LIVE.orient = LIVE.orient || { flipLen: false, flipW: false };
  if (f.dataset.liveFlip === "len") LIVE.orient.flipLen = !LIVE.orient.flipLen; else LIVE.orient.flipW = !LIVE.orient.flipW;
  for (const k of Object.keys(LIVE.assign)) if (!LIVE.manual[LIVE.assign[k]]) delete LIVE.assign[k];     // keep only names you set by hand, redo the rest
  LIVE.slot = {}; for (const k of Object.keys(LIVE.assign)) {}
  liveSave(); if (LIVE.state) { liveMatch(LIVE.state.players.filter((p) => p.team === "tot")); liveDots(LIVE.state); }
}, true);

document.addEventListener("click", (event) => {
  const w = event.target.closest?.("[data-who]");
  if (!w) return;
  const p = liveRoster().find((x) => Number(x.id) === Number(w.dataset.who));
  if (p) { const f = document.getElementById("tx-follow"); liveFocusPlayer(p); liveChips(); }
});

document.addEventListener("click", (event) => {
  const b = event.target.closest?.("#live-seg [data-mode]");
  if (b) { liveSetMode(b.dataset.mode); return; }
  if (event.target.closest?.("#live-menu")) document.body.classList.toggle("show-nav");
});

function liveSetMode(m) {
  const st = document.getElementById("live-stage"); if (!st) return;
  st.className = "stage m-" + m;
  document.querySelectorAll("#live-seg button").forEach((x) => x.classList.toggle("on", x.dataset.mode === m));
  try { localStorage.setItem("liveMode", m); } catch (e) { /* fine */ }
}
document.addEventListener("click", (event) => {
  const sw = event.target.closest?.("[data-swap]"), st = document.getElementById("live-stage");
  if (sw && st) { event.preventDefault(); liveSetMode(st.classList.contains("m-map") ? "video" : "map"); return; }
  // in Dots view the video is the small inset: click it to bring the video back
  const inset = event.target.closest?.(".stage.m-map .live-video");
  if (inset) liveSetMode("video");
});
document.addEventListener("keydown", (event) => {
  if (event.key.toLowerCase() !== "m" || /input|textarea|select/i.test(event.target.tagName) || event.metaKey || event.ctrlKey) return;
  const st = document.getElementById("live-stage"); if (st) liveSetMode(st.classList.contains("m-map") ? "video" : "map");
});
