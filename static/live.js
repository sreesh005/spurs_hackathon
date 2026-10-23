/* LIVE DOTS. The live tracking feed (hack_live_dots.py --serve 8766) shown inside the Next Post desk.
   Left: the broadcast with boxes. Right: the pitch with a dot per player. Click a Spurs dot -> that player's reel opens in the drawer.
   Dots are matched to the lineup by position as a first guess; use the picker under the pitch to correct one. */

const LIVE_URL = (new URLSearchParams(location.search).get("live")) || localStorage.getItem("liveUrl") || "http://127.0.0.1:8766";
const LIVE = { slot: {}, seen: {}, last: {}, forced: false, manual: {}, orient: null, state: null, ok: false, assign: {}, picked: null, guessed: false, timer: null, miss: 0 };
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
  return `<section class="live">
    <div class="live-top">
      <div class="live-video"><img id="live-img" alt="" src="${LIVE_URL}/video.mjpg" /><div class="live-badge" id="live-badge">connecting…</div><div class="live-alert" id="live-alert" hidden></div></div>
    </div>
    <div class="live-pitch-wrap">
      <div class="live-pitch" id="live-pitch">${livePitchLines()}<div id="live-dots"></div><div class="live-ball" id="live-ball" hidden></div>
        <div class="live-wait" id="live-wait">Getting ready… finding the pitch</div></div>
      <div class="live-pick" id="live-pick"></div>
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

function liveTick() {
  if (state.tab !== "live" || !document.getElementById("live-dots")) return;
  fetch(LIVE_URL + "/state.json", { cache: "no-store" }).then((r) => r.json()).then((st) => {
    LIVE.miss = 0; LIVE.state = st;
    const badge = document.getElementById("live-badge"), wait = document.getElementById("live-wait");
    if (badge) badge.textContent = !st.ready ? "getting ready" : st.cutaway ? "off the main camera" : "live";
    if (wait) { wait.hidden = st.ready && !st.cutaway; wait.textContent = !st.ready ? "Getting ready… finding the pitch" : "Waiting for the main camera…"; }
    if (!st.ready) return;
    const spurs = st.players.filter((p) => p.team === "tot");
    if (state.data) liveMatch(spurs); liveDots(st); liveAlerts(st);
  }).catch((err) => {
    if (!(err instanceof TypeError && /fetch/i.test(err.message))) console.error("live tick failed:", err);
    if (++LIVE.miss > 3) { const badge = document.getElementById("live-badge"); if (badge) badge.textContent = "no live feed at " + LIVE_URL; }
  });
}

function mountLive() {
  livePicker(); liveClips();
  if (!LIVE.timer) LIVE.timer = setInterval(liveTick, 80);
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
