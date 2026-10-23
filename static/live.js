/* LIVE DOTS. The live tracking feed (hack_live_dots.py --serve 8766) shown inside the Next Post desk.
   Left: the broadcast with boxes. Right: the pitch with a dot per player. Click a Spurs dot -> that player's reel opens in the drawer.
   Dots are matched to the lineup by position as a first guess; use the picker under the pitch to correct one. */

const LIVE_URL = (new URLSearchParams(location.search).get("live")) || localStorage.getItem("liveUrl") || "http://127.0.0.1:8766";
const LIVE = { state: null, ok: false, assign: {}, picked: null, guessed: false, timer: null, miss: 0 };
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

function liveGuess(spurs) {
  // first guess only: line the Spurs dots up against the lineup graphic (keeper at the back, striker at the front)
  const c = state.data.clubs.find((x) => x.id === "thfc");
  if (!c || spurs.length < 9) return false;
  const spots = c.lineup.filter((p) => p.x != null).map((p) => ({ id: p.id, along: (p.y - 14) / 72, across: p.x / 100 }));
  let best = null;
  for (const flipLen of [false, true]) for (const flipW of [false, true]) {
    const used = new Set(); let cost = 0; const pairs = [];
    const dots = spurs.map((d) => ({ id: d.id, along: flipLen ? 1 - d.x : d.x, across: flipW ? 1 - d.y : d.y })).sort((a, b) => a.along - b.along);
    for (const d of dots) {
      let b = null;
      for (const s of spots) { if (used.has(s.id)) continue; const k = (s.along - d.along) ** 2 + 0.5 * (s.across - d.across) ** 2; if (!b || k < b.k) b = { s, k }; }
      if (b) { used.add(b.s.id); cost += b.k; pairs.push([d.id, b.s.id]); }
    }
    if (!best || cost < best.cost) best = { cost, pairs };
  }
  for (const [dot, pid] of best.pairs) if (LIVE.assign[dot] == null) LIVE.assign[dot] = pid;
  liveSave();
  return true;
}

function liveName(pid) { return liveRoster().find((p) => Number(p.id) === Number(pid)); }

function liveDots(st) {
  const box = document.getElementById("live-dots");
  if (!box) return;
  const seen = new Set();
  for (const p of st.players) {
    seen.add(String(p.id));
    let el = box.querySelector(`[data-dot="${p.id}"]`);
    if (!el) { el = document.createElement("button"); el.type = "button"; el.dataset.dot = p.id; box.appendChild(el); }
    const person0 = p.team === "tot" ? liveName(LIVE.assign[p.id]) : null;
    el.className = "dot " + p.team + (person0 && person0.thumb ? " photo" : "") + (LIVE.picked === String(p.id) ? " sel" : "");
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
  if (LIVE.picked == null) { holder.innerHTML = `<span class="meta">Check the names before kick-off: the shirt numbers are a first guess from position. Click any Spurs dot to fix it or open that player's reel.</span>`; return; }
  const cur = LIVE.assign[LIVE.picked];
  const opts = liveRoster().map((p) => `<option value="${p.id}" ${Number(cur) === Number(p.id) ? "selected" : ""}>${esc(p.number ? "#" + p.number + " " : "")}${esc(p.short)}</option>`).join("");
  holder.innerHTML = `<label class="meta">This dot is <select id="live-who"><option value="">— pick —</option>${opts}</select></label>`;
}

function liveSheet() {
  const side = document.querySelector(".desk-side");
  if (!side) return;
  const holder = document.createElement("div"); holder.innerHTML = sheetHtml();
  side.replaceWith(holder.firstElementChild);
  const desk = document.querySelector(".desk");
  const open = people().some((person) => Number(person.id) === Number(state.focus));
  if (desk) desk.classList.toggle("with-reel", open);
  bindPlayers(); mountReel();
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
    if (!LIVE.guessed && state.data && liveGuess(spurs)) LIVE.guessed = true;
    liveDots(st); liveAlerts(st);
  }).catch((err) => {
    if (!(err instanceof TypeError && /fetch/i.test(err.message))) console.error("live tick failed:", err);
    if (++LIVE.miss > 3) { const badge = document.getElementById("live-badge"); if (badge) badge.textContent = "no live feed at " + LIVE_URL; }
  });
}

function mountLive() {
  livePicker();
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
  LIVE.assign[LIVE.picked] = Number(pid); liveSave();
  state.focus = Number(pid); state.reelCut = 0; liveSheet();
});
