/* LIVE DOTS. The live tracking feed (hack_live_dots.py --serve 8766) shown inside the Next Post desk.
   Left: the broadcast with boxes. Right: the pitch with a dot per player. Click a Spurs dot -> that player's live collection opens in the drawer:
   the plays the auto-clipper captured for him tonight, each with every angle found, or ScorePlay's library until he has one.
   Dots are matched to the lineup by position as a first guess; use the picker under the pitch to correct one.
   Clip data: /api/live/feed (counts per player, polled) and /api/live/player/{id} (server.py, live_clips.py). */

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
      <div class="lc-ticker" id="lc-ticker"></div>
      <button type="button" class="lc-toast" id="lc-toast" hidden></button>
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
    const count = person ? LC.counts[String(person.id)] || 0 : 0;
    if (el.dataset.count !== String(count || "")) el.dataset.count = count ? String(count) : "";
    el.classList.toggle("fresh", !!person && (LC.fresh[String(person.id)] || 0) > Date.now());
    if (count) el.title += ` · ${count} live ${count === 1 ? "clip" : "clips"}`;
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
  if (LIVE.picked == null) { holder.innerHTML = `<span class="meta">Check the names before kick-off: the shirt numbers are a first guess from position. Click any Spurs dot to fix it or open that player's live clips.</span>`; return; }
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
  if (!LC.timer) LC.timer = setInterval(lcFeedTick, 1500);
  lcFeedTick();
  lcTicker();
  if (state.focus) lcLoad(Number(state.focus));
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

/* ---------- LIVE CLIPS: the drawer a Spurs dot opens ---------- */

const LC = { timer: null, version: -1, counts: {}, latest: [], seen: null, fresh: {}, data: {}, loading: {}, sel: {}, feedAt: 0, serverNow: 0, demo: false, toastT: null };

function lcAge(unix) {
  if (!unix) return "";
  const now = LC.serverNow + (Date.now() - LC.feedAt) / 1000;
  const s = Math.max(0, Math.round(now - unix));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  return `${Math.floor(s / 3600)} h ago`;
}

function lcSourceTag(source) {
  const label = { live: "Live", upload: "Upload", scoreplay: "ScorePlay" }[source] || source;
  return `<span class="lc-src ${esc(source)}">${esc(label)}</span>`;
}

function lcFeedTick() {
  if (state.tab !== "live") return;
  fetch("/api/live/feed", { cache: "no-store" }).then((r) => r.json()).then((feed) => {
    LC.feedAt = Date.now(); LC.serverNow = feed.now; LC.demo = !!feed.demo;
    LC.counts = feed.counts || {};
    LC.latest = feed.latest || [];
    const ids = new Set(LC.latest.map((m) => m.id + ":" + m.angle_count));
    if (LC.seen) {
      const fresh = LC.latest.filter((m) => !LC.seen.has(m.id + ":" + m.angle_count));
      for (const m of fresh) for (const pid of m.player_ids) LC.fresh[String(pid)] = Date.now() + 8000;
      if (fresh.length) lcToast(fresh[0]);
    }
    LC.seen = ids;
    lcTicker();
    if (feed.version !== LC.version) {
      LC.version = feed.version;
      if (state.focus) lcLoad(Number(state.focus), true);
    } else if (state.focus) lcNote();
  }).catch(() => {});
}

function lcLoad(pid, quiet) {
  if (LC.loading[pid]) return;
  LC.loading[pid] = true;
  fetch(`/api/live/player/${pid}`, { cache: "no-store" }).then((r) => r.json()).then((data) => {
    LC.data[pid] = data;
    if (Number(state.focus) === pid && state.tab === "live") lcRender(!quiet);
  }).catch((err) => console.warn("live clips failed:", err)).finally(() => { LC.loading[pid] = false; });
}

function lcMoments(pid) {
  const d = LC.data[pid];
  return d ? [...d.live, ...d.library] : [];
}

function lcSelected(pid) {
  const moments = lcMoments(pid);
  if (!moments.length) return { moment: null, angle: null };
  const sel = LC.sel[pid] || {};
  const moment = moments.find((m) => m.id === sel.moment) || moments[0];
  const angle = moment.angles.find((a) => a.id === sel.angle) || moment.angles[0];
  return { moment, angle };
}

function lcAngleButtons(moment, angle) {
  return moment.angles.map((a) => `<button type="button" class="lc-angle ${a.id === angle.id ? "on" : ""}" data-lc-angle="${esc(a.id)}" data-lc-moment="${esc(moment.id)}">
      ${lcSourceTag(a.source)}<span>${esc(a.label)}</span></button>`).join("");
}

function lcRow(m, on) {
  const angles = m.angle_count > 1 ? `<em class="lc-count">${m.angle_count} angles</em>` : "";
  const when = m.live ? lcAge(m.first_seen || m.captured_at) : "ScorePlay library";
  return `<button type="button" class="lc-row ${on ? "on" : ""}" data-lc-moment="${esc(m.id)}">
      <b>${esc(m.event_plain)}</b><span>${esc(m.caption)}</span><i>${esc(when)}</i>${angles}</button>`;
}

function lcWhy(moment) {
  if (moment.angle_count < 2) return moment.live ? "One angle so far. Replays, phone uploads and ScorePlay edits of this play join it as they land." : "";
  const why = moment.grouped_by.length ? moment.grouped_by.join(" · ") : "same ScorePlay file group";
  return `${moment.angle_count} angles of one play · matched by ${why}`;
}

function lcNoteHtml(pid) {
  const d = LC.data[pid];
  if (!d) return `<span class="meta">Loading his clips…</span>`;
  const tag = d.showing === "live" ? lcSourceTag("live") : d.showing === "scoreplay" ? lcSourceTag("scoreplay") : "";
  const last = d.live[0] ? ` · last ${lcAge(d.live[0].captured_at)}` : "";
  return `${tag}<span>${esc(d.note)}${esc(last)}</span>`;
}

function lcNote() {
  const pid = Number(state.focus);
  const note = document.getElementById("lc-note");
  if (note) note.innerHTML = lcNoteHtml(pid);
  document.querySelectorAll("#lc-lists .lc-row").forEach((row) => {
    const m = lcMoments(pid).find((x) => x.id === row.dataset.lcMoment);
    const i = row.querySelector("i");
    if (m && m.live && i) i.textContent = lcAge(m.first_seen || m.captured_at);
  });
}

function lcListsHtml(pid, moment) {
  const d = LC.data[pid];
  if (!d) return "";
  const live = d.live.length
    ? `<h4 class="lc-h">Captured live tonight</h4><div class="lc-list">${d.live.map((m) => lcRow(m, moment && m.id === moment.id)).join("")}</div>`
    : `<div class="empty lc-empty">Nothing captured for him live yet. The auto-clipper adds his plays here as TwelveLabs names him.</div>`;
  const lib = d.library.length
    ? `<h4 class="lc-h">${d.live.length ? "Also in ScorePlay" : "From ScorePlay, until he has a live clip"}</h4><div class="lc-list">${d.library.map((m) => lcRow(m, moment && m.id === moment.id)).join("")}</div>`
    : "";
  return live + lib;
}

function liveSheetHtml() {
  const pid = Number(state.focus);
  const focus = liveName(pid);
  if (!focus) {
    return `<div class="desk-side"><p class="lede">Click a Spurs dot. His clips from tonight open here, each with every angle we have of the play.</p></div>`;
  }
  if (!LC.data[pid]) lcLoad(pid);
  const { moment, angle } = lcSelected(pid);
  const stage = angle
    ? `<div class="reel-stage lc-stage"><video id="lc-video" controls playsinline preload="metadata" src="${esc(angle.video)}" poster="${esc(angle.thumb || "")}"></video></div>
       <div class="lc-caption"><b>${esc(moment.event_plain)}</b> <span id="lc-cap">${esc(angle.source === "live" && angle.caption ? angle.caption : moment.caption)}</span></div>
       <div class="lc-angles" id="lc-angles">${lcAngleButtons(moment, angle)}</div>
       <p class="meta lc-why" id="lc-why">${esc(lcWhy(moment))}</p>`
    : LC.data[pid] ? "" : `<div class="reel-stage lc-stage lc-wait">Loading…</div>`;
  return `<div class="desk-side">
    <section class="drawer lc-drawer" id="live-reel">
      <div class="drawer-head">
        <div>
          <div class="kicker">${esc(focus.pos || "")} ${focus.number ? "· #" + esc(focus.number) : ""} · Live collection</div>
          <h2>${esc(focus.short)}</h2>
        </div>
        <button class="ghost" type="button" data-close-reel>Close</button>
      </div>
      <p class="lc-note" id="lc-note">${lcNoteHtml(pid)}</p>
      <div id="lc-stage-wrap">${stage}</div>
      <div id="lc-lists">${lcListsHtml(pid, moment)}</div>
      ${focus.shop ? `<a class="shop" href="${esc(focus.shop)}" target="_blank" rel="noreferrer">Shop the jersey</a>` : ""}
    </section></div>`;
}

function lcRender(full) {
  // Keep the video playing when new clips arrive: only the lists and notes move unless the pick changed.
  const pid = Number(state.focus);
  const video = document.getElementById("lc-video");
  const { moment, angle } = lcSelected(pid);
  const same = video && angle && video.getAttribute("src") === angle.video;
  if (full || !same) { liveSheet(); lcPlay(); return; }
  const lists = document.getElementById("lc-lists"); if (lists) lists.innerHTML = lcListsHtml(pid, moment);
  const angles = document.getElementById("lc-angles"); if (angles) angles.innerHTML = lcAngleButtons(moment, angle);
  const why = document.getElementById("lc-why"); if (why) why.textContent = lcWhy(moment);
  lcNote();
}

function lcPlay() {
  const video = document.getElementById("lc-video");
  if (video) video.play().catch(() => {});
}

function lcTicker() {
  const box = document.getElementById("lc-ticker");
  if (!box) return;
  if (!LC.latest.length) { box.innerHTML = `<span class="meta">Just captured: nothing yet. Clips land here seconds after the auto-clipper cuts them.</span>`; return; }
  box.innerHTML = `<span class="kicker">Just captured</span>` + LC.latest.slice(0, 5).map((m) => {
    const who = m.player_ids.map((pid) => liveName(pid)?.short).filter(Boolean).join(", ") || "Untagged";
    const pid = m.player_ids[0];
    return `<button type="button" class="lc-chip" ${pid ? `data-lc-player="${pid}" data-lc-open="${esc(m.id)}"` : "disabled"}>
      <b>${esc(who)}</b><span>${esc(m.event_plain)}${m.angle_count > 1 ? ` · ${m.angle_count} angles` : ""}</span><i>${esc(lcAge(m.captured_at))}</i></button>`;
  }).join("");
}

function lcToast(m) {
  const toast = document.getElementById("lc-toast");
  if (!toast) return;
  const who = m.player_ids.map((pid) => liveName(pid)?.short).filter(Boolean).join(", ") || "Untagged";
  toast.hidden = false;
  toast.dataset.lcPlayer = m.player_ids[0] || "";
  toast.dataset.lcOpen = m.id;
  toast.innerHTML = `<b>New clip</b> ${esc(who)} · ${esc(m.event_plain)}${m.angle_count > 1 ? ` · ${m.angle_count} angles` : ""}`;
  clearTimeout(LC.toastT); LC.toastT = setTimeout(() => { toast.hidden = true; }, 5000);
}

function lcOpen(pid, momentId) {
  state.focus = Number(pid); state.reelCut = 0;
  if (momentId) LC.sel[pid] = { moment: momentId };
  liveSheet();
  if (LC.data[pid]) lcPlay();
  lcLoad(Number(pid), true);
}

document.addEventListener("click", (event) => {
  if (state.tab !== "live") return;
  const node = event.target?.nodeType === 1 ? event.target : event.target?.parentElement;
  const open = node?.closest?.("[data-lc-player]");
  if (open && open.dataset.lcPlayer) {
    event.preventDefault();
    lcOpen(Number(open.dataset.lcPlayer), open.dataset.lcOpen);
    const toast = document.getElementById("lc-toast"); if (toast && open === toast) toast.hidden = true;
    return;
  }
  const pick = node?.closest?.("[data-lc-moment]");
  if (!pick || !node.closest("#live-reel")) return;
  event.preventDefault();
  const pid = Number(state.focus);
  LC.sel[pid] = { moment: pick.dataset.lcMoment, angle: pick.dataset.lcAngle || null };
  liveSheet();
  lcPlay();
});
