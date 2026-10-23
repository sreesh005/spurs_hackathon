/* FRONT END / UI behavior.
   Draws the desk: lineup, search, tabs, and the player reel.
   Calls the backend at /api/library, /api/decide, and /api/read.
   Page shell: static/index.html. Look: static/styles.css. */

const TABS = [
  ["live", "Live dots"],
  ["demo", "Demo clip"],
  ["lineup", "Lineup"],
  ["best", "Best of the night"],
  ["underrated", "Underrated"],
  ["before", "Before it"],
  ["angles", "All angles"],
  ["offball", "Off the ball"],
  ["quote", "Quote card"],
  ["still", "The still"],
  ["saturated", "Already out"],
  ["sponsor", "Sponsor"],
  ["swing", "The swing"],
  ["reel", "To the player"],
  ["tonight", "Tonight"],
];

const state = {
  data: null,
  club: "sas",
  audience: "matchday",
  tab: new URLSearchParams(location.search).get("view") === "demo" ? "demo" : "live",
  focus: null,
  angle: {},
  reel: null,
  reelCut: 0,
  busy: null,
  notice: "",
  query: "",
};

const $ = (id) => document.getElementById(id);
const TALK = /speak|captaincy|mentality|proud|press|podcast|interview/;

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

// ---------------------------------------------------------------- data helpers

const club = () => state.data.clubs.find((item) => item.id === state.club);
const plays = () => state.data.plays.filter((play) => play.club === state.club);
const decision = (play) => state.data.decisions?.[play.id];
const people = () => [...club().lineup, ...club().bench];
const focused = () => people().find((person) => Number(person.id) === Number(state.focus));
const isClip = (play) => play.mode !== "context" && play.mode !== "broadcast";
const isTalk = (play) => TALK.test(titleOf(play).toLowerCase());
// the two tabs that use the live layout: the tracker feed, and the recorded 60s demo clip
const liveDesk = () => state.tab === "live" || state.tab === "demo";
const sideOpen = () => !!focused() || !!state.query.trim();

function titleOf(play) {
  const raw = play.title || play.id.replace(/^cut-|^raw-/, "").replace(/-/g, " ");
  return raw.replace(/\.[a-z0-9]+$/i, "");
}

function ranked() {
  return plays()
    .filter(isClip)
    .sort((a, b) => b.scores[state.audience] - a.scores[state.audience]);
}

function nameParts(person) {
  return (person?.short || "").toLowerCase().split(/\s+/).filter((part) => part.length > 3);
}

function playerPlays(id) {
  const person = people().find((item) => item.id === id);
  const name = (person?.short || "").toLowerCase();
  const mine = (play) => (play.named_id === id || play.heroes?.matchday?.id === id || play.heroes?.player?.id === id ? 1 : 0);
  return plays()
    .filter((play) => mine(play) || (play.players || []).some((item) => item.id === id) || (name.length > 2 && titleOf(play).toLowerCase().includes(name)))
    .sort((a, b) => mine(b) - mine(a) || b.importance - a.importance || (b.scores?.[state.audience] || 0) - (a.scores?.[state.audience] || 0));
}

function reelScore(play) {
  const watch = Number(play.tl?.watchability);
  const picture = Number.isFinite(watch) ? (watch > 1 ? watch / 10 : watch) : Number(play.picture) || 0;
  const duration = Number(play.angles?.[0]?.duration) || 0;
  const title = titleOf(play).toLowerCase();
  const named = (play.players || []).some((person) => nameParts(person).some((part) => title.includes(part))) ? 0.18 : 0;
  const talk = isTalk(play) ? 0.55 : 0;
  const bloated = duration > 90 ? 0.35 : 0;
  return (Number(play.importance) || 0) * 0.62 + picture * 0.28 + (Number(play.story) || 0) * 0.1 + named - talk - bloated;
}

function isPersonal(play, person) {
  const title = titleOf(play).toLowerCase();
  if (play.named_id === person?.id || nameParts(person).some((part) => title.includes(part))) return true;
  const crowd = (play.players || []).length;
  return crowd > 0 && crowd <= 2;
}

function momentKey(play) {
  const title = titleOf(play).toLowerCase();
  const keys = [["over the bar", "over-bar"], ["early", "early"], ["chance", "chance"], ["tackle", "tackle"], ["cele", "cele"], ["limbs", "cele"], ["goal", "goal"], ["equalis", "goal"]];
  return keys.find(([word]) => title.includes(word))?.[1] || play.id;
}

function ownClips(person) {
  return playerPlays(person.id).filter((play) => isClip(play) && isPersonal(play, person) && !isTalk(play));
}

// Top 3 clips for a player, one per kind of moment where possible.
function topReel(id) {
  const person = people().find((item) => item.id === id);
  if (!person) return [];
  const pool = ownClips(person)
    .filter((play) => play.action !== "HIGHLIGHTS" && play.action !== "FULL")
    .sort((a, b) => reelScore(b) - reelScore(a));
  const seen = new Set();
  const picked = pool.filter((play) => !seen.has(momentKey(play)) && seen.add(momentKey(play))).slice(0, 3);
  for (const play of pool) if (picked.length < 3 && !picked.includes(play)) picked.push(play);
  return picked;
}

function sliceOf(angle) {
  const duration = Number(angle?.duration) || 0;
  const window = 10;
  if (duration > window + 0.4) return { start: Math.max(0, duration - window), end: duration };
  return { start: 0, end: duration || window };
}

function setupOf(play) {
  return play?.setup_id ? state.data.plays.find((item) => item.id === play.setup_id) || null : null;
}

function chosenAngle(play) {
  const picked = state.angle[play.id];
  return play.angles.find((angle) => angle.id === picked) || play.angles[0];
}

// ---------------------------------------------------------------- search

function scorePlay(play, tokens) {
  const text = `${titleOf(play)} ${play.action_plain} ${play.players.map((person) => `${person.short} ${person.name}`).join(" ")}`.toLowerCase();
  let score = 0;
  for (const token of tokens) {
    if (/^\d+$/.test(token)) {
      if (!new RegExp(`(^|[^0-9])${token}([^0-9]|$)`).test(text)) return -1;
      score += 8;
    } else if (text.includes(token) || (token === "goal" && play.action === "GOAL")) score += 4;
    else score -= 2;
  }
  return score;
}

function findHit(query) {
  const tokens = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  if (!tokens.length || !state.data) return null;
  let best = null;
  let bestScore = 0;
  for (const play of state.data.plays) {
    const score = scorePlay(play, tokens);
    if (score > bestScore) [best, bestScore] = [play, score];
  }
  return best;
}

// ---------------------------------------------------------------- pieces

const empty = (message) => `<div class="empty">${message}</div>`;
const shop = (href, label) => `<a class="shop" href="${esc(href || "#")}" target="_blank" rel="noreferrer">${esc(label)}</a>`;

function avatar(person) {
  if (person.thumb) return `<img src="${esc(person.thumb)}" alt="" />`;
  return `<div class="avatar">${esc((person.short || "?").slice(0, 1))}</div>`;
}

function bars(play) {
  const fit = { matchday: play.importance, hardcore: play.story }[state.audience] ?? play.room;
  const rows = [["Picture", play.picture], ["Story", play.story], ["Room", play.room], ["Fit", fit]];
  return `<div class="bars">${rows
    .map(([label, value]) => {
      const width = Math.round(Math.max(0, Math.min(1, value)) * 100);
      return `<div><span>${label}</span><i><b style="width:${width}%"></b></i><span>${width}</span></div>`;
    })
    .join("")}</div>`;
}

function videoTag(angle) {
  if (!angle?.video) return `<img class="shot" src="${esc(angle?.thumb || "")}" alt="" />`;
  return `<video src="${esc(angle.video)}" poster="${esc(angle.thumb || "")}" controls playsinline preload="metadata"></video>`;
}

function card(play, extra = "") {
  const angle = chosenAngle(play);
  const hero = play.heroes[state.audience] || play.heroes.matchday;
  const made = decision(play);
  const sponsor = club().sponsor;
  return `<article class="card">
    ${videoTag(angle)}
    <div class="pad">
      <div class="kicker">${esc(hero.short)} · ${esc(play.action_plain)} · Q${esc(play.quarter)}</div>
      <h3>${esc(play.captions[state.audience])}</h3>
      <p class="meta">${esc(play.reasons[state.audience])}</p>
      ${bars(play)}
      <div class="meta">Score ${Number(play.scores?.[state.audience] || 0).toFixed(2)} for ${esc(state.audience)}</div>
      ${play.tl ? `<p class="meta">${esc(play.tl.description)}</p><span class="tag">${play.tl.sponsor_mark_visible ? `${esc(sponsor.name)} readable` : "Mark not readable in this window"}</span>` : ""}
      ${made ? `<p class="status">${esc(made.status)} · ${esc(made.note || "")}</p>` : ""}
      <div class="row">
        <button class="solid" data-act="approve" data-id="${esc(play.id)}">Approve</button>
        <button class="ghost" data-act="reject" data-id="${esc(play.id)}">Reject</button>
        <button class="ghost" data-act="read" data-media="${angle.id}">${state.busy === angle.id ? "Reading…" : "Read clip"}</button>
        ${hero.shop ? shop(hero.shop, "Jersey") : ""}
      </div>
      ${extra}
    </div>
  </article>`;
}

const grid = (list, fn = (play) => card(play)) => `<div class="grid">${list.map(fn).join("")}</div>`;
const page = (title, lede, body) => `<h1>${title}</h1>${lede ? `<p class="lede">${lede}</p>` : ""}${body}`;

function statLine(person) {
  const list = ownClips(person);
  const count = (actions) => list.filter((play) => actions.includes(play.action)).length;
  const rows = club().kind === "football"
    ? [["Goals", count(["GOAL"])], ["Chances", count(["CHANCE"])], ["Tackles", count(["TACKLE"])], ["Clips", list.length]]
    : [["Dunks", count(["DUNK!", "STL JAM!", "WINDMILL"])], ["Threes", count(["3PT"])], ["Blocks", count(["BLOCK", "BLK"])], ["Clips", list.length]];
  return `<div class="stats">${rows.map(([label, value]) => `<div class="stat"><b>${value}</b><span>${label}</span></div>`).join("")}</div>`;
}

function lineupHtml() {
  const current = club();
  const focus = focused();
  const on = (person) => (focus && person.id === focus.id ? "on" : "");
  const tokens = current.lineup
    .map((person) => `<button type="button" class="token ${on(person)}" style="left:${person.x}%;top:${person.y}%" data-player="${person.id}">
        ${avatar(person)}
        <strong>${esc(person.short)}</strong>
        <em>${esc(person.number ? "#" + person.number : person.pos)}</em>
      </button>`)
    .join("");
  const bench = current.bench
    .map((person) => `<button type="button" data-player="${person.id}" class="${on(person)}">${avatar(person)}<span>${esc(person.short)}</span></button>`)
    .join("");
  return `<div class="lineup"><div class="court ${current.kind}"><div class="lines"></div>${tokens}</div><div class="bench">${bench}</div></div>`;
}

function sheetHtml() {
  const hit = state.query.trim() ? findHit(state.query) : null;
  const focus = focused();
  const pulled = hit
    ? `<section class="pulled"><div class="kicker">Pulled up · ${esc(titleOf(hit))}</div>${card(hit)}</section>`
    : state.query.trim()
      ? empty("Nothing in the library matches that.")
      : "";
  if (!focus) {
    const hint = liveDesk() ? "Players the announcer names show up here with their clips. Or click a dot on the map." : "Click a shirt. The reel stays open while you pick clips.";
    return `<div class="desk-side">${pulled}<p class="lede">${hint}</p></div>`;
  }
  const reel = topReel(focus.id);
  const picks = reel
    .map((play, index) => {
      const slice = sliceOf(chosenAngle(play));
      const seconds = Math.max(1, Math.round((slice.end - slice.start) * 10) / 10);
      return `<button type="button" class="reel-pick ${index === state.reelCut ? "on" : ""}" data-reel-cut="${index}">
        <b>${index + 1}</b><span>${esc(titleOf(play))}</span><em>${esc(play.action_plain)} · ${seconds}s</em>
      </button>`;
    })
    .join("");
  return `<div class="desk-side">${pulled}
    <section class="drawer" id="reel">
      <div class="drawer-head">
        <div>
          <div class="kicker">${esc(focus.pos)}${focus.number ? " · #" + esc(focus.number) : ""} · 30-second reel</div>
          <h2>${esc(focus.short)}</h2>
        </div>
        <button class="ghost" type="button" data-close-reel aria-label="Close reel">Close</button>
      </div>
      ${statLine(focus)}
      ${shop(focus.shop, "Shop the jersey")}
      ${
        reel.length
          ? `<div class="reel-stage"><video id="reel-video" controls playsinline poster="${esc(chosenAngle(reel[0])?.thumb || "")}"></video></div>
             <div class="reel-meta"><span>Top 3, last 10s of each</span><span id="reel-step">1 of ${reel.length} · ${esc(titleOf(reel[0]))}</span></div>
             <div class="reel-picks">${picks}</div>`
          : empty("No clip in this library belongs to this player alone yet.")
      }
    </section></div>`;
}

// ---------------------------------------------------------------- tabs (each returns HTML for the section under the lineup)

function renderBest() {
  const list = ranked().slice(0, 6);
  return page("Best of the night", `Ranked for ${esc(state.audience)}. Picture, story, room, and fit. Switch the audience and the order moves.`, list.length ? grid(list) : empty("No clips for this club yet."));
}

function renderUnderrated() {
  const boxes = people()
    .map((person) => ({ person, play: playerPlays(person.id)[0] }))
    .filter((box) => box.play)
    .sort((a, b) => b.play.room - a.play.room);
  return page(
    "Underrated",
    "One box per player. Quieter players sit first. The clip is the best picture they are actually in.",
    boxes.length ? grid(boxes, ({ person, play }) => card(play, `<p class="meta">Box for ${esc(person.short)}</p>`)) : empty("No player clips in this library yet.")
  );
}

function renderBefore() {
  const pairs = ranked().filter(setupOf).slice(0, 8);
  const pair = (play) => {
    const setup = setupOf(play);
    return `<article class="pair">
      ${videoTag(chosenAngle(setup))}
      ${videoTag(chosenAngle(play))}
      <div class="pad">
        <div class="kicker">Setup then finish</div>
        <h3>${esc(setup.action_plain)} into ${esc(play.action_plain)}</h3>
        <p>${esc(play.captions.hardcore)}</p>
        <div class="row">
          <button class="solid" data-act="approve" data-id="${esc(play.id)}">Approve the join</button>
          <button class="ghost" data-act="reject" data-id="${esc(play.id)}">Reject</button>
        </div>
      </div>
    </article>`;
  };
  return page("Before it", "The finish, and the clip from the same quarter that sits just in front of it. Approve posts them as one package.", pairs.length ? `<div class="stack">${pairs.map(pair).join("")}</div>` : empty("No joins in this library yet."));
}

function renderAngles() {
  const list = ranked().slice(0, 12);
  const thumbs = (play) =>
    `<div class="angles">${play.angles
      .map((angle) => `<button class="${chosenAngle(play).id === angle.id ? "on" : ""}" data-angle="${angle.id}" data-play="${esc(play.id)}"><img src="${esc(angle.thumb)}" alt="Angle ${esc(angle.label)}" /></button>`)
      .join("")}</div>`;
  return page("All angles", "Every camera ScorePlay kept on the same play number. Pick one and it becomes the cut and the thumbnail on the card.", list.length ? grid(list, (play) => card(play, thumbs(play))) : empty("No angles in this library yet."));
}

function renderOffball() {
  const clips = plays().filter((play) => play.mode === "context");
  const photos = state.data.photos.filter((photo) => photo.club === state.club).slice(0, 18);
  const photoCard = (photo) => `<article class="card"><img class="shot" src="${esc(photo.image || photo.thumb)}" alt="" /><div class="pad"><h3>${esc(photo.player)}</h3><p class="meta">${esc(photo.name)}</p></div></article>`;
  return page(
    "Off the ball",
    "The tunnel, the pre-match, the postgame bite. Then the stills. The highlight reel never includes these.",
    `${clips.length ? grid(clips) : ""}${photos.length ? grid(photos, photoCard) : empty("No stills for this club in the library.")}`
  );
}

function renderQuote() {
  const list = ranked().slice(0, 4);
  const quote = (play) => `<article class="quote">
      <img class="bg" src="${esc(chosenAngle(play).thumb)}" alt="" />
      <div class="pad"><div class="kicker">${esc(play.quote_source || "Desk line")}</div><p>${esc(play.quote)}</p></div>
    </article>`;
  return page("Quote card", "A desk line on the still. If TwelveLabs hears commentary in the clip, that replaces the line and is labeled as heard, not invented.", list.length ? grid(list, quote) : empty("No clips to set type on."));
}

function renderStill() {
  const list = ranked().filter((play) => play.still).slice(0, 6);
  const still = (play) => `<article class="card">
      <img class="shot" src="${esc(play.still.image || play.still.thumb)}" alt="" />
      <div class="pad">
        <div class="kicker">Still of ${esc(play.heroes.matchday.short)}</div>
        <h3>${esc(play.action_plain)}</h3>
        <p class="meta">Paired from the photo bucket, not a frame grab.</p>
      </div>
    </article>`;
  return page("The still", "The video is the moment. The photo, from the same player in the same match, is the post.", list.length ? grid(list, still) : empty("No photo paired to a clip yet."));
}

function renderSaturated() {
  const list = plays().filter((play) => play.saturated).slice(0, 8);
  return page("Already out", "The finish belongs to someone who is already all over the library. Fine for matchday. A weak post for their personal channels.", list.length ? grid(list) : empty("Nothing in this library is saturated past the line."));
}

function renderSponsor() {
  const { sponsor, kit } = club();
  const list = ranked().slice(0, 6);
  return page(
    esc(sponsor.name),
    `${esc(sponsor.blurb)} Read a clip before calling the logo visible.`,
    `<p class="meta"><a href="${esc(sponsor.url)}" target="_blank" rel="noreferrer">${esc(sponsor.name)}</a> · ${esc(sponsor.place)} · Kit ${esc(kit)}</p>${list.length ? grid(list) : empty("No clips to check for the mark.")}`
  );
}

function renderSwing() {
  const buckets = new Map();
  for (const play of plays()) buckets.set(play.quarter, [...(buckets.get(play.quarter) || []), play]);
  let best = null;
  let bestScore = -1;
  buckets.forEach((bucket, quarter) => {
    const score = bucket.reduce((sum, play) => sum + play.importance, 0);
    if (score > bestScore) [best, bestScore] = [quarter, score];
  });
  const run = (buckets.get(best) || []).slice().sort((a, b) => a.number - b.number).slice(0, 8);
  const row = (play) => `<article>
      <img src="${esc(chosenAngle(play).thumb)}" alt="" />
      <div><div class="kicker">#${play.number}</div><h3>${esc(play.action_plain)}</h3><p class="meta">${esc(play.heroes.matchday.short)}</p></div>
      <button class="solid" data-act="approve" data-id="${esc(play.id)}">Approve</button>
    </article>`;
  return page("The swing", best ? `Quarter ${esc(best)}, in order. This is the stretch with the most in it.` : "No stretch yet.", `<div class="swing">${run.map(row).join("")}</div>`);
}

function renderReel() {
  const roster = people();
  const person = roster.find((item) => item.id === state.reel) || roster[0];
  const list = person ? topReel(person.id) : [];
  const options = roster.map((item) => `<option value="${item.id}" ${item.id === person?.id ? "selected" : ""}>${esc(item.short)}</option>`).join("");
  return `<div class="reel-head">
      <div><h1>To the player</h1><p class="lede">The cut you would actually send them. Written for their channels, not the club account.</p></div>
      <select id="reel-select" aria-label="Player">${options}</select>
    </div>
    ${person ? `<p>${shop(person.shop, `Jersey · ${person.short}`)}</p>` : ""}
    ${list.length ? grid(list) : empty("No clips for that player.")}`;
}

function renderTonight() {
  const open = ranked().filter((play) => (decision(play)?.status || "pending") === "pending").slice(0, 5);
  const done = plays().filter((play) => decision(play) && decision(play).status !== "pending").slice(0, 6);
  const doneCard = (play) => {
    const made = decision(play);
    return `<article class="card"><div class="pad"><span class="tag ${made.status === "rejected" ? "warn" : ""}">${esc(made.status)}</span><h3>${esc(play.action_plain)}</h3><p class="meta">${esc(made.note || "")}</p></div></article>`;
  };
  return page(
    "Tonight",
    `Five posts, in order, for ${esc(state.audience)}. Yes writes the caption back onto the ScorePlay asset when the library accepts it.`,
    `${state.notice ? `<p class="status">${esc(state.notice)}</p>` : ""}
    ${open.length ? grid(open) : empty("The queue is clear.")}
    ${done.length ? `<h2 class="sub">Decided</h2>${grid(done, doneCard)}` : ""}`
  );
}

const RENDER = {
  best: renderBest,
  underrated: renderUnderrated,
  before: renderBefore,
  angles: renderAngles,
  offball: renderOffball,
  quote: renderQuote,
  still: renderStill,
  saturated: renderSaturated,
  sponsor: renderSponsor,
  swing: renderSwing,
  reel: renderReel,
  tonight: renderTonight,
};

// ---------------------------------------------------------------- render

function renderChrome() {
  const current = club();
  const line = [current.score, current.opponent, current.when, `${current.play_count} plays`].filter(Boolean).map(esc).join(" · ");
  $("game").innerHTML = `<strong>${esc(current.name)}</strong><span>${line}</span>`;
  const buttons = (list, key, on, label) => list.map((item) => `<button type="button" data-${key}="${item.id}" class="${item.id === on ? "on" : ""}">${esc(label(item))}</button>`).join("");
  $("clubs").innerHTML = buttons(state.data.clubs, "club", state.club, (item) => item.short);
  $("audiences").innerHTML = buttons(state.data.audiences, "audience", state.audience, (item) => item.label);
  $("nav").innerHTML = buttons(TABS.map(([id, label]) => ({ id, label })), "tab", state.tab, (item) => item.label);
}

function render() {
  try {
    const live = liveDesk();
    if (live && state.club !== "thfc" && state.data.clubs.some((item) => item.id === "thfc")) {
      state.club = "thfc";
      state.focus = null;
    }
    renderChrome();
    const rest = RENDER[state.tab]?.() || "";
    document.body.classList.toggle("live-mode", live);
    $("main").innerHTML = `<div class="desk ${sideOpen() ? "with-reel" : ""}">${state.tab === "demo" ? demoHtml() : live ? liveHtml() : lineupHtml()}${sheetHtml()}</div>${rest ? `<section id="rest">${rest}</section>` : ""}`;
    mountReel();
    if (state.tab === "demo") mountDemo();
    else if (live) mountLive();
  } catch (error) {
    const note = document.createElement("p");
    note.className = "status";
    note.textContent = error.stack || error.message;
    $("main").appendChild(note);
  }
}

// Redraw only the side sheet (search hit + reel), so videos elsewhere keep playing.
function renderSheet() {
  const side = document.querySelector(".desk-side");
  if (!side) return render();
  const holder = document.createElement("div");
  holder.innerHTML = sheetHtml();
  side.replaceWith(holder.firstElementChild);
  document.querySelector(".desk")?.classList.toggle("with-reel", sideOpen());
  document.querySelectorAll(".court [data-player], .bench [data-player]").forEach((button) => button.classList.toggle("on", Number(button.dataset.player) === Number(state.focus)));
  mountReel();
  if (liveDesk()) liveClips();
}

function focusPlayer(id) {
  state.focus = id == null ? null : Number(id);
  state.reelCut = 0;
  if (state.tab === "lineup" || liveDesk() || id == null) renderSheet();
  else {
    state.tab = "lineup";
    render();
  }
}

// ---------------------------------------------------------------- reel player: plays the last 10s of each top clip in turn

let reelToken = 0;

function mountReel() {
  const video = $("reel-video");
  if (!video || !state.focus) return;
  const picks = topReel(state.focus);
  const cut = Math.min(state.reelCut, Math.max(picks.length - 1, 0));
  const play = picks[cut];
  if (!play) return;
  const angle = chosenAngle(play);
  const slice = sliceOf(angle);
  const key = `${state.focus}:${cut}:${angle?.id}`;
  if (video.dataset.key === key) return;
  video.dataset.key = key;
  const step = $("reel-step");
  if (step) step.textContent = `${cut + 1} of ${picks.length} · ${titleOf(play)}`;
  document.querySelectorAll("[data-reel-cut]").forEach((button) => button.classList.toggle("on", Number(button.dataset.reelCut) === cut));
  const token = ++reelToken;
  let ready = false;
  video.pause();
  const go = () => {
    if (token !== reelToken || !ready || !Number.isFinite(video.currentTime) || video.currentTime + 0.12 < slice.end) return;
    ready = false;
    advanceReel();
  };
  const begin = () => {
    if (token !== reelToken) return;
    ready = true;
    video.play().catch(() => {});
  };
  const arm = () => {
    if (token !== reelToken) return;
    if (slice.start > 0.05 && Math.abs(video.currentTime - slice.start) > 0.3) {
      video.addEventListener("seeked", begin, { once: true });
      try {
        video.currentTime = slice.start;
      } catch (error) {
        begin();
      }
      return;
    }
    begin();
  };
  video.ontimeupdate = go;
  video.onended = go;
  video.onloadedmetadata = arm;
  const src = angle?.video || "";
  if (video.getAttribute("src") !== src) video.src = src;
  else if (video.readyState >= 1) arm();
}

function advanceReel() {
  const picks = topReel(state.focus);
  if (state.reelCut >= picks.length - 1) {
    $("reel-video")?.pause();
    const step = $("reel-step");
    if (step) step.textContent = "Reel finished";
    return;
  }
  state.reelCut += 1;
  mountReel();
}

// ---------------------------------------------------------------- API

async function refresh() {
  const response = await fetch("/api/library");
  if (!response.ok) throw new Error(await response.text());
  state.data = await response.json();
  render();
}

async function post(path, body) {
  return fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}

async function act(name, playId, mediaId) {
  if (name === "read") {
    state.busy = Number(mediaId);
    state.notice = "TwelveLabs is reading the first 12 seconds.";
    render();
    const response = await post("/api/read", { media_id: Number(mediaId) });
    state.busy = null;
    state.notice = response.ok ? "Clip read." : "TwelveLabs could not read that file.";
    if (!response.ok) console.warn(await response.text());
  } else {
    const response = await post("/api/decide", { play_id: playId, audience: state.audience, status: name === "approve" ? "approved" : "rejected" });
    state.notice = (await response.json()).note || "";
  }
  await refresh();
}

// ---------------------------------------------------------------- events

document.body.addEventListener("click", (event) => {
  const hit = (selector) => event.target.closest(selector);
  let el;
  if ((el = hit("[data-reel-cut]"))) {
    state.reelCut = Number(el.dataset.reelCut);
    const video = $("reel-video");
    if (video) delete video.dataset.key;
    mountReel();
  } else if ((el = hit("[data-close-reel]"))) focusPlayer(null);
  else if ((el = hit("[data-club]"))) {
    Object.assign(state, { club: el.dataset.club, focus: null, reel: null, reelCut: 0 });
    render();
  } else if ((el = hit("[data-audience]"))) {
    state.audience = el.dataset.audience;
    render();
  } else if ((el = hit("[data-tab]"))) {
    state.tab = el.dataset.tab;
    document.body.classList.remove("show-nav");
    render();
  } else if ((el = hit("[data-player]"))) focusPlayer(el.dataset.player);
  else if ((el = hit("[data-angle]"))) {
    state.angle[el.dataset.play] = Number(el.dataset.angle);
    render();
  } else if ((el = hit("[data-act]"))) act(el.dataset.act, el.dataset.id, el.dataset.media);
});

document.body.addEventListener("change", (event) => {
  if (event.target.id !== "reel-select") return;
  state.reel = Number(event.target.value);
  render();
});

$("search").addEventListener("input", (event) => {
  state.query = event.target.value;
  if (state.data) renderSheet();
});

$("search").addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  const hit = findHit(state.query);
  if (!hit) return;
  const id = hit.named_id || hit.heroes?.matchday?.id || null;
  if (!liveDesk() && hit.club !== state.club) {
    Object.assign(state, { club: hit.club, focus: id, reelCut: 0, tab: "lineup" });
    render();
  } else focusPlayer(id);
});

refresh().catch((error) => {
  $("main").innerHTML = empty(esc(error.message || "The desk could not load the library."));
});
