/* FRONT END / UI behavior.
   Draws the desk: lineup, search, tabs, and the player reel.
   Calls the backend at /api/library, /api/decide, and /api/read.
   Page shell: static/index.html. Look: static/styles.css. */

const TABS = [
  ["live", "Live dots"],
  ["lineup", "Lineup"],
  ["best", "Best of the night"],
  ["underrated", "Underrated"],
  ["before", "Before it"],
  ["angles", "All angles"],
  ["offball", "Off the ball"],
  ["quote", "Quote card"],
  ["frames", "Frames"],
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
  tab: "live",
  focus: null,
  angle: {},
  reel: null,
  reelCut: 0,
  busy: null,
  notice: "",
  query: "",
};

const $ = (id) => document.getElementById(id);

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function club() {
  return state.data.clubs.find((item) => item.id === state.club);
}

function plays() {
  return state.data.plays.filter((play) => play.club === state.club);
}

function ranked() {
  return plays()
    .filter((play) => play.mode !== "context" && play.mode !== "broadcast")
    .slice()
    .sort((a, b) => b.scores[state.audience] - a.scores[state.audience]);
}

function decision(play) {
  return state.data.decisions?.[play.id];
}

function people() {
  const current = club();
  return [...current.lineup, ...current.bench];
}

function playerPlays(id) {
  const person = people().find((item) => item.id === id);
  const name = (person?.short || "").toLowerCase();
  const mine = (play) => (play.named_id === id || play.heroes?.matchday?.id === id || play.heroes?.player?.id === id ? 1 : 0);
  return plays()
    .filter((play) => {
      const tagged = (play.players || []).some((item) => item.id === id);
      const titled = name.length > 2 && titleOf(play).toLowerCase().includes(name);
      return mine(play) || tagged || titled;
    })
    .sort((a, b) => mine(b) - mine(a) || b.importance - a.importance || (b.scores?.[state.audience] || 0) - (a.scores?.[state.audience] || 0));
}

function reelScore(play) {
  const watch = Number(play.tl?.watchability);
  const picture = Number.isFinite(watch) ? (watch > 1 ? watch / 10 : watch) : Number(play.picture) || 0;
  const duration = Number(play.angles?.[0]?.duration) || 0;
  const title = titleOf(play).toLowerCase();
  const named = (play.players || []).some((person) =>
    (person.short || "")
      .toLowerCase()
      .split(/\s+/)
      .filter((part) => part.length > 3)
      .some((part) => title.includes(part))
  )
    ? 0.18
    : 0;
  const talk = /speak|captaincy|mentality|proud|press|podcast|interview/.test(title) ? 0.55 : 0;
  const bloated = duration > 90 ? 0.35 : 0;
  return (Number(play.importance) || 0) * 0.62 + picture * 0.28 + (Number(play.story) || 0) * 0.1 + named - talk - bloated;
}

function isTalk(play) {
  return /speak|captaincy|mentality|proud|press|podcast|interview/.test(titleOf(play).toLowerCase());
}

function isPersonal(play, person) {
  const title = titleOf(play).toLowerCase();
  const parts = (person?.short || "")
    .toLowerCase()
    .split(/\s+/)
    .filter((part) => part.length > 3);
  if (play.named_id === person?.id || parts.some((part) => title.includes(part))) return true;
  const crowd = (play.players || []).length;
  return crowd > 0 && crowd <= 2;
}

function momentKey(play) {
  const title = titleOf(play).toLowerCase();
  if (title.includes("over the bar")) return "over-bar";
  if (title.includes("early")) return "early";
  if (title.includes("chance")) return "chance";
  if (title.includes("tackle")) return "tackle";
  if (title.includes("cele") || title.includes("limbs")) return "cele";
  if (title.includes("goal") || title.includes("equalis")) return "goal";
  return play.id;
}

function topReel(id) {
  const person = people().find((item) => item.id === id);
  const pool = playerPlays(id)
    .filter((play) => play.mode !== "broadcast" && play.mode !== "context" && play.action !== "HIGHLIGHTS" && play.action !== "FULL")
    .filter((play) => isPersonal(play, person) && !isTalk(play))
    .slice()
    .sort((a, b) => reelScore(b) - reelScore(a));
  const picked = [];
  const seen = new Set();
  for (const play of pool) {
    const key = momentKey(play);
    if (seen.has(key)) continue;
    seen.add(key);
    picked.push(play);
    if (picked.length === 3) return picked;
  }
  for (const play of pool) {
    if (picked.includes(play)) continue;
    picked.push(play);
    if (picked.length === 3) break;
  }
  return picked;
}

function sliceOf(angle) {
  const duration = Number(angle?.duration) || 0;
  const window = 10;
  if (duration > window + 0.4) return { start: Math.max(0, duration - window), end: duration };
  return { start: 0, end: duration || window };
}

function setupOf(play) {
  if (!play?.setup_id) return null;
  return state.data.plays.find((item) => item.id === play.setup_id) || null;
}

function chosenAngle(play) {
  const picked = state.angle[play.id];
  return play.angles.find((angle) => angle.id === picked) || play.angles[0];
}

function avatar(person, className) {
  if (person.thumb) return `<img class="${className || ""}" src="${esc(person.thumb)}" alt="" />`;
  const letter = esc((person.short || "?").slice(0, 1));
  return `<div class="avatar ${className || ""}">${letter}</div>`;
}

function bars(play) {
  const rows = [
    ["Picture", play.picture],
    ["Story", play.story],
    ["Room", play.room],
    ["Fit", state.audience === "matchday" ? play.importance : state.audience === "hardcore" ? play.story : play.room],
  ];
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
  const seen = play.tl?.sponsor_mark_visible;
  return `<article class="card">
    ${videoTag(angle)}
    <div class="pad">
      <div class="kicker">${esc(hero.short)} · ${esc(play.action_plain)} · Q${esc(play.quarter)}</div>
      <h3>${esc(play.captions[state.audience])}</h3>
      <p class="meta">${esc(play.reasons[state.audience])}</p>
      ${bars(play)}
      <div class="meta">Score ${Number(play.scores?.[state.audience] || 0).toFixed(2)} for ${esc(state.audience)}</div>
      ${play.tl ? `<p class="meta">${esc(play.tl.description)}</p><span class="tag">${seen ? `${esc(sponsor.name)} readable` : "Mark not readable in this window"}</span>` : ""}
      ${made ? `<p class="status">${esc(made.status)} · ${esc(made.note || "")}</p>` : ""}
      <div class="row">
        <button class="solid" data-act="approve" data-id="${esc(play.id)}">Approve</button>
        <button class="ghost" data-act="reject" data-id="${esc(play.id)}">Reject</button>
        <button class="ghost" data-act="read" data-media="${angle.id}">${state.busy === angle.id ? "Reading…" : "Read clip"}</button>
        ${hero.shop ? `<a class="shop" href="${esc(hero.shop)}" target="_blank" rel="noreferrer">Jersey</a>` : ""}
      </div>
      ${extra}
    </div>
  </article>`;
}

function empty(message) {
  return `<div class="empty">${message}</div>`;
}

function titleOf(play) {
  const raw = play.title || play.id.replace(/^cut-|^raw-/, "").replace(/-/g, " ");
  return raw.replace(/\.[a-z0-9]+$/i, "");
}

function scorePlay(play, tokens) {
  const text = `${titleOf(play)} ${play.action_plain} ${play.players.map((person) => `${person.short} ${person.name}`).join(" ")}`.toLowerCase();
  let score = 0;
  for (const token of tokens) {
    if (/^\d+$/.test(token)) {
      if (new RegExp(`(^|[^0-9])${token}([^0-9]|$)`).test(text)) score += 8;
      else return -1;
    } else if (text.includes(token) || (token === "goal" && play.action === "GOAL")) {
      score += 4;
    } else score -= 2;
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
    if (score > bestScore) {
      best = play;
      bestScore = score;
    }
  }
  return best;
}

function statLine(person) {
  const list = playerPlays(person.id).filter((play) => play.mode !== "broadcast" && play.mode !== "context" && isPersonal(play, person) && !isTalk(play));
  const count = (actions) => list.filter((play) => actions.includes(play.action)).length;
  const football = club().kind === "football";
  const rows = football
    ? [["Goals", count(["GOAL"])], ["Chances", count(["CHANCE"])], ["Tackles", count(["TACKLE"])], ["Clips", list.length]]
    : [["Dunks", count(["DUNK!", "STL JAM!", "WINDMILL"])], ["Threes", count(["3PT"])], ["Blocks", count(["BLOCK", "BLK"])], ["Clips", list.length]];
  return `<div class="stats">${rows.map(([label, value]) => `<div class="stat"><b>${value}</b><span>${label}</span></div>`).join("")}</div><p class="meta">Counted from the clips in this match library.</p>`;
}

function lineupHtml() {
  const current = club();
  const focus = people().find((person) => Number(person.id) === Number(state.focus));
  const tokens = current.lineup
    .map((person) => {
      const on = focus && person.id === focus.id ? "on" : "";
      return `<button type="button" class="token ${on}" style="left:${person.x}%;top:${person.y}%" data-player="${person.id}">
        ${avatar(person)}
        <strong>${esc(person.short)}</strong>
        <em>${esc(person.number ? "#" + person.number : person.pos)}</em>
      </button>`;
    })
    .join("");
  const bench = current.bench
    .map((person) => `<button type="button" data-player="${person.id}" class="${focus && person.id === focus.id ? "on" : ""}">${avatar(person)}<span>${esc(person.short)}</span></button>`)
    .join("");
  return `
    <div class="court-wrap court-top">
      <div>
        <div class="court compact ${current.kind}">
          <div class="lines"></div>
          ${tokens}
        </div>
        <div class="bench">${bench}</div>
      </div>
    </div>`;
}

function sheetHtml() {
  const hit = state.query.trim() ? findHit(state.query) : null;
  const focus = people().find((person) => Number(person.id) === Number(state.focus));
  const pulled = hit
    ? `<section class="pulled"><div class="kicker">Pulled up · ${esc(titleOf(hit))}</div>${card(hit)}</section>`
    : state.query.trim()
      ? empty("Nothing in the library matches that.")
      : "";
  if (!focus) {
    return `<div class="desk-side">${pulled}<p class="lede">${state.tab === "live" ? "Players the announcer names show up here with their clips. Or click a dot on the map." : "Click a shirt. The reel stays open while you pick clips."}</p></div>`;
  }
  const reel = topReel(focus.id);
  const picks = reel
    .map((play, index) => {
      const angle = chosenAngle(play);
      const slice = sliceOf(angle);
      const seconds = Math.max(1, Math.round((slice.end - slice.start) * 10) / 10);
      return `<button type="button" class="reel-pick ${index === (state.reelCut || 0) ? "on" : ""}" data-reel-cut="${index}">
        <b>${index + 1}</b>
        <span>${esc(titleOf(play))}</span>
        <em>${esc(play.action_plain)} · ${seconds}s</em>
      </button>`;
    })
    .join("");
  return `<div class="desk-side">${pulled}
    <section class="drawer" id="reel">
      <div class="drawer-head">
        <div>
          <div class="kicker">${esc(focus.pos)} ${focus.number ? "· #" + esc(focus.number) : ""} · 30-second reel</div>
          <h2>${esc(focus.short)}</h2>
        </div>
        <button class="ghost" type="button" data-close-reel>Close</button>
      </div>
      ${statLine(focus)}
      <a class="shop" href="${esc(focus.shop || "#")}" target="_blank" rel="noreferrer">Shop the jersey</a>
      ${
        reel.length
          ? `<div class="reel-stage"><video id="reel-video" controls playsinline poster="${esc(chosenAngle(reel[0])?.thumb || "")}"></video></div>
             <div class="reel-meta"><span>Top 3, last 10 seconds of each</span><span id="reel-step">1 of ${reel.length} · ${esc(titleOf(reel[0]))}</span></div>
             <div class="reel-picks">${picks}</div>
             <p class="meta">Ranked by how loud the action is in the clip. A play-by-play file would place these windows inside the full match.</p>`
          : empty("No clip in this library is his alone. A play-by-play file would cut his 30 seconds out of the full match.")
      }
    </section></div>`;
}

function renderLineup() {
  const current = club();
  const focus = people().find((person) => person.id === state.focus) || current.lineup[0];
  const clip = focus ? playerPlays(focus.id)[0] : null;
  const tokens = current.lineup
    .map((person) => {
      const on = focus && person.id === focus.id ? "on" : "";
      return `<button type="button" class="token ${on}" style="left:${person.x}%;top:${person.y}%" data-player="${person.id}">
        ${avatar(person)}
        <strong>${esc(person.short)}</strong>
        <em>${esc(person.number ? "#" + person.number : person.pos)}</em>
      </button>`;
    })
    .join("");
  const bench = current.bench
    .map(
      (person) => `<button data-player="${person.id}">${avatar(person)}<span>${esc(person.short)}</span></button>`
    )
    .join("");
  const sponsor = current.sponsor;
  const full = plays().find((play) => play.action === "FULL");
  const highlights = plays().filter((play) => play.action === "HIGHLIGHTS");
  const broadcast = [full, ...highlights].filter(Boolean);
  const broadcastHtml = broadcast.length
    ? `<div class="broadcast">${broadcast
        .map((play) => `<article class="card">${videoTag(chosenAngle(play))}<div class="pad"><div class="kicker">${esc(play.action_plain)}</div><h3>${esc(play.captions.matchday)}</h3></div></article>`)
        .join("")}</div>`
    : "";
  $("main").innerHTML = `
    <h1>${esc(current.short)} lineup</h1>
    <p class="lede">Hover a shirt for the sponsor. Click a player for the clip that should go on their own channels, and the jersey link.</p>
    ${broadcastHtml}
    <div class="court-wrap">
      <div>
        <div class="court ${current.kind}">
          <div class="lines"></div>
          ${tokens}
        </div>
        <div class="bench">${bench}</div>
      </div>
      <aside class="panel" id="inspect">
        <div class="kicker">${esc(sponsor.place)}</div>
        <div class="sponsor-name">${esc(sponsor.name)}</div>
        <p class="meta">${esc(sponsor.blurb)}</p>
        <a href="${esc(sponsor.url)}" target="_blank" rel="noreferrer">Sponsor site</a>
        ${
          focus
            ? `<h2 style="margin-top:18px">${esc(focus.short)}</h2>
               <p class="meta">${esc(focus.pos)} ${focus.number ? "· #" + esc(focus.number) : ""}</p>
               <a class="shop" href="${esc(focus.shop)}" target="_blank" rel="noreferrer">Shop the jersey</a>`
            : ""
        }
        ${clip ? `<div style="margin-top:14px">${card(clip)}</div>` : `<p class="meta">No clip in this library for that player.</p>`}
      </aside>
    </div>`;
}

function renderBest() {
  const list = ranked().slice(0, 6);
  $("main").innerHTML = `
    <h1>Best of the night</h1>
    <p class="lede">Ranked for ${esc(state.audience)}. Picture, story, room, and fit. Switch the audience and the order moves.</p>
    ${list.length ? `<div class="grid">${list.map((play) => card(play)).join("")}</div>` : empty("No clips for this club yet.")}`;
}

function renderUnderrated() {
  const boxes = people()
    .map((person) => ({ person, play: playerPlays(person.id)[0] }))
    .filter((box) => box.play)
    .sort((a, b) => b.play.room - a.play.room);
  $("main").innerHTML = `
    <h1>Underrated</h1>
    <p class="lede">One box per player. Quieter players sit first. The clip is the best picture they are actually in.</p>
    ${
      boxes.length
        ? `<div class="grid">${boxes
            .map(
              ({ person, play }) =>
                `<div>${card(play, `<p class="meta">Box for ${esc(person.short)}</p>`)}</div>`
            )
            .join("")}</div>`
        : empty("No player clips in this library yet.")
    }`;
}

function renderBefore() {
  const pairs = ranked().filter((play) => setupOf(play)).slice(0, 8);
  $("main").innerHTML = `
    <h1>Before it</h1>
    <p class="lede">The finish, and the clip from the same quarter that sits just in front of it. Approve posts them as one package.</p>
    ${
      pairs.length
        ? pairs
            .map((play) => {
              const setup = setupOf(play);
              return `<article class="pair" style="margin-bottom:14px">
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
            })
            .join("")
        : empty("No joins in this library yet.")
    }`;
}

function renderAngles() {
  const list = ranked();
  $("main").innerHTML = `
    <h1>All angles</h1>
    <p class="lede">Every camera ScorePlay kept on the same play number. Pick one and it becomes the cut on the card.</p>
    ${
      list.length
        ? `<div class="grid">${list
            .slice(0, 12)
            .map((play) => {
              const thumbs = play.angles
                .map((angle) => {
                  const on = chosenAngle(play).id === angle.id ? "on" : "";
                  return `<button class="${on}" data-angle="${angle.id}" data-play="${esc(play.id)}"><img src="${esc(angle.thumb)}" alt="Angle ${esc(angle.label)}" /></button>`;
                })
                .join("");
              return card(play, `<div class="angles">${thumbs}</div>`);
            })
            .join("")}</div>`
        : empty("No angles in this library yet.")
    }`;
}

function renderOffball() {
  const clips = plays().filter((play) => play.mode === "context");
  const photos = state.data.photos.filter((photo) => photo.club === state.club).slice(0, 18);
  $("main").innerHTML = `
    <h1>Off the ball</h1>
    <p class="lede">The tunnel, the pre-match, the postgame bite. Then the stills. The highlight reel never includes these.</p>
    ${clips.length ? `<div class="grid">${clips.map((play) => card(play)).join("")}</div>` : ""}
    ${
      photos.length
        ? `<div class="grid">${photos
            .map(
              (photo) => `<article class="card"><img class="shot" src="${esc(photo.image || photo.thumb)}" alt="" /><div class="pad"><h3>${esc(photo.player)}</h3><p class="meta">${esc(photo.name)}</p></div></article>`
            )
            .join("")}</div>`
        : empty("No stills for this club in the library.")
    }`;
}

function renderQuote() {
  const list = ranked().slice(0, 4);
  $("main").innerHTML = `
    <h1>Quote card</h1>
    <p class="lede">A desk line on the still. If TwelveLabs hears commentary in the clip, that replaces the line and is labeled as heard, not invented.</p>
    ${
      list.length
        ? `<div class="grid">${list
            .map((play) => {
              const angle = chosenAngle(play);
              return `<article class="quote">
                <img class="bg" src="${esc(angle.thumb)}" alt="" />
                <div class="pad">
                  <div class="kicker">${esc(play.quote_source || "Desk line")}</div>
                  <p>${esc(play.quote)}</p>
                </div>
              </article>`;
            })
            .join("")}</div>`
        : empty("No clips to set type on.")
    }`;
}

function renderFrames() {
  const play = ranked()[0];
  if (!play) {
    $("main").innerHTML = `<h1>Frames</h1>${empty("No clip to pull frames from.")}`;
    return;
  }
  const angle = chosenAngle(play);
  $("main").innerHTML = `
    <h1>Frames</h1>
    <p class="lede">Each angle is a candidate thumbnail. The one you pick is the frame on the post.</p>
    ${card(
      play,
      `<div class="angles">${play.angles
        .map((item) => `<button class="${item.id === angle.id ? "on" : ""}" data-angle="${item.id}" data-play="${esc(play.id)}"><img src="${esc(item.thumb)}" alt="" /></button>`)
        .join("")}</div>`
    )}`;
}

function renderStill() {
  const list = ranked().filter((play) => play.still).slice(0, 6);
  $("main").innerHTML = `
    <h1>The still</h1>
    <p class="lede">The video is the moment. The photo, from the same player in the same match, is the post.</p>
    ${
      list.length
        ? `<div class="grid">${list
            .map(
              (play) => `<article class="still-card">
                <img src="${esc(play.still.image || play.still.thumb)}" alt="" />
                <div class="pad">
                  <div class="kicker">Still of ${esc(play.heroes.matchday.short)}</div>
                  <h3>${esc(play.action_plain)}</h3>
                  <p class="meta">Paired from the photo bucket, not a frame grab.</p>
                </div>
              </article>`
            )
            .join("")}</div>`
        : empty("No photo paired to a clip yet.")
    }`;
}

function renderSaturated() {
  const list = plays().filter((play) => play.saturated);
  $("main").innerHTML = `
    <h1>Already out</h1>
    <p class="lede">The finish belongs to someone who is already all over the library. Fine for matchday. A weak post for their personal channels.</p>
    ${list.length ? `<div class="grid">${list.slice(0, 8).map((play) => card(play)).join("")}</div>` : empty("Nothing in this library is saturated past the line.")}`;
}

function renderSponsor() {
  const current = club();
  const list = ranked().slice(0, 6);
  $("main").innerHTML = `
    <h1>${esc(current.sponsor.name)}</h1>
    <p class="lede">${esc(current.sponsor.blurb)} Read a clip before calling the logo visible.</p>
    <p><a href="${esc(current.sponsor.url)}" target="_blank" rel="noreferrer">${esc(current.sponsor.name)}</a> · ${esc(current.sponsor.place)} · Kit ${esc(current.kit)}</p>
    ${list.length ? `<div class="grid">${list.map((play) => card(play)).join("")}</div>` : empty("No clips to check for the mark.")}`;
}

function renderSwing() {
  const buckets = new Map();
  plays().forEach((play) => {
    const bucket = buckets.get(play.quarter) || [];
    bucket.push(play);
    buckets.set(play.quarter, bucket);
  });
  let bestQuarter = null;
  let bestScore = -1;
  buckets.forEach((bucket, quarter) => {
    const score = bucket.reduce((sum, play) => sum + play.importance, 0);
    if (score > bestScore) {
      bestScore = score;
      bestQuarter = quarter;
    }
  });
  const run = (buckets.get(bestQuarter) || []).slice().sort((a, b) => a.number - b.number).slice(0, 8);
  $("main").innerHTML = `
    <h1>The swing</h1>
    <p class="lede">${bestQuarter ? `Quarter ${esc(bestQuarter)}, in order. This is the stretch with the most in it.` : "No stretch yet."}</p>
    <div class="swing">${run
      .map((play) => {
        const angle = chosenAngle(play);
        return `<article>
          <img src="${esc(angle.thumb)}" alt="" />
          <div>
            <div class="kicker">#${play.number}</div>
            <h3>${esc(play.action_plain)}</h3>
            <p class="meta">${esc(play.heroes.matchday.short)}</p>
          </div>
          <button class="solid" data-act="approve" data-id="${esc(play.id)}">Approve</button>
        </article>`;
      })
      .join("")}</div>`;
}

function renderReel() {
  const roster = people();
  const id = state.reel || roster[0]?.id;
  const person = roster.find((item) => item.id === id) || roster[0];
  const list = person ? topReel(person.id) : [];
  $("main").innerHTML = `
    <div class="reel-head">
      <div>
        <h1>To the player</h1>
        <p class="lede">The cut you would actually send them. Written for their channels, not the club account.</p>
      </div>
      <select id="reel-select">${roster
        .map((item) => `<option value="${item.id}" ${item.id === person?.id ? "selected" : ""}>${esc(item.short)}</option>`)
        .join("")}</select>
    </div>
    ${person ? `<p><a class="shop" href="${esc(person.shop)}" target="_blank" rel="noreferrer">Jersey · ${esc(person.short)}</a></p>` : ""}
    ${list.length ? `<div class="grid">${list.slice(0, 4).map((play) => card(play)).join("")}</div>` : empty("No clips for that player.")}`;
}

function renderTonight() {
  const open = ranked().filter((play) => !decision(play) || decision(play).status === "pending").slice(0, 5);
  const done = plays().filter((play) => decision(play) && decision(play).status !== "pending");
  $("main").innerHTML = `
    <h1>Tonight</h1>
    <p class="lede">Five posts, in order, for ${esc(state.audience)}. Yes writes the caption back onto the ScorePlay asset when the library accepts it.</p>
    ${state.notice ? `<p class="status">${esc(state.notice)}</p>` : ""}
    ${open.length ? `<div class="grid">${open.map((play) => card(play)).join("")}</div>` : empty("The queue is clear.")}
    ${
      done.length
        ? `<h2 style="margin:22px 0 10px">Decided</h2><div class="grid">${done
            .slice(0, 6)
            .map((play) => `<article class="card"><div class="pad"><span class="tag ${decision(play).status === "rejected" ? "warn" : ""}">${esc(decision(play).status)}</span><h3>${esc(play.action_plain)}</h3><p class="meta">${esc(decision(play).note || "")}</p></div></article>`)
            .join("")}</div>`
        : ""
    }`;
}

const RENDER = {
  lineup: renderLineup,
  best: renderBest,
  underrated: renderUnderrated,
  before: renderBefore,
  angles: renderAngles,
  offball: renderOffball,
  quote: renderQuote,
  frames: renderFrames,
  still: renderStill,
  saturated: renderSaturated,
  sponsor: renderSponsor,
  swing: renderSwing,
  reel: renderReel,
  tonight: renderTonight,
};

function renderChrome() {
  const current = club();
  $("game").innerHTML = `<strong>${esc(current.name)}</strong><span>${current.score ? esc(current.score) + " · " : ""}${esc(current.opponent)}${current.when ? " · " + esc(current.when) : ""} · ${current.play_count} plays</span>`;
  $("clubs").innerHTML = state.data.clubs
    .map((item) => `<button data-club="${item.id}" class="${item.id === state.club ? "on" : ""}">${esc(item.short)}</button>`)
    .join("");
  $("audiences").innerHTML = state.data.audiences
    .map((item) => `<button data-audience="${item.id}" class="${item.id === state.audience ? "on" : ""}">${esc(item.label)}</button>`)
    .join("");
  $("nav").innerHTML = TABS.map(([id, label]) => `<button data-tab="${id}" class="${id === state.tab ? "on" : ""}">${esc(label)}</button>`).join("");
  document.body.dataset.club = state.club;
}

function render() {
  try {
    if (state.tab === "live" && state.club !== "thfc" && state.data.clubs.some((item) => item.id === "thfc")) { state.club = "thfc"; state.focus = null; }
    renderChrome();
    let rest = "";
    if (state.tab !== "lineup" && state.tab !== "live") {
      (RENDER[state.tab] || renderLineup)();
      rest = $("main").innerHTML;
    }
    const open = people().some((person) => Number(person.id) === Number(state.focus));
    document.body.classList.toggle("live-mode", state.tab === "live");
    $("main").innerHTML = `<div class="desk ${open ? "with-reel" : ""}">${state.tab === "live" ? liveHtml() : lineupHtml()}${sheetHtml()}</div>${rest ? `<section id="rest">${rest}</section>` : ""}`;
    bindPlayers();
    mountReel();
    if (state.tab === "live") mountLive();
  } catch (error) {
    const note = document.createElement("p");
    note.className = "status";
    note.textContent = error.stack || error.message;
    $("main").appendChild(note);
  }
}

function bindPlayers() {
  document.querySelectorAll("[data-player]").forEach((button) => {
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      state.focus = Number(button.dataset.player);
      state.reelCut = 0;
      state.tab = "lineup";
      render();
    });
  });
}

let reelToken = 0;

function mountReel() {
  const video = document.getElementById("reel-video");
  if (!video || !state.focus) return;
  const picks = topReel(state.focus);
  const cut = Math.min(state.reelCut || 0, Math.max(picks.length - 1, 0));
  const play = picks[cut];
  if (!play) return;
  const angle = chosenAngle(play);
  const slice = sliceOf(angle);
  const key = `${state.focus}:${cut}:${angle?.id}`;
  if (video.dataset.key === key) return;
  video.dataset.key = key;
  const step = document.getElementById("reel-step");
  if (step) step.textContent = `${cut + 1} of ${picks.length} · ${titleOf(play)}`;
  const token = ++reelToken;
  let advancing = false;
  let ready = false;
  video.ontimeupdate = null;
  video.onended = null;
  video.onloadedmetadata = null;
  video.pause();
  const go = () => {
    if (token !== reelToken || !ready || advancing) return;
    if (!Number.isFinite(video.currentTime) || video.currentTime + 0.12 < slice.end) return;
    advancing = true;
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
      video.addEventListener(
        "seeked",
        () => {
          if (token === reelToken) begin();
        },
        { once: true }
      );
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
  const nextSrc = angle?.video || "";
  if (video.getAttribute("src") !== nextSrc) video.src = nextSrc;
  else if (video.readyState >= 1) arm();
}

function advanceReel() {
  const picks = topReel(state.focus);
  if (!picks.length || (state.reelCut || 0) >= picks.length - 1) {
    const video = document.getElementById("reel-video");
    if (video) video.pause();
    const step = document.getElementById("reel-step");
    if (step) step.textContent = "Reel finished";
    return;
  }
  state.reelCut += 1;
  document.querySelectorAll("[data-reel-cut]").forEach((button) => {
    button.classList.toggle("on", Number(button.dataset.reelCut) === state.reelCut);
  });
  mountReel();
}

async function refresh() {
  const response = await fetch("/api/library");
  if (!response.ok) throw new Error(await response.text());
  state.data = await response.json();
  render();
}

async function act(name, playId, mediaId) {
  if (name === "read") {
    state.busy = Number(mediaId);
    state.notice = "TwelveLabs is reading the first 12 seconds.";
    render();
    const response = await fetch("/api/read", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ media_id: Number(mediaId) }),
    });
    state.busy = null;
    state.notice = response.ok ? "Clip read." : "TwelveLabs could not read that file.";
    if (!response.ok) console.warn(await response.text());
    await refresh();
    return;
  }
  const response = await fetch("/api/decide", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ play_id: playId, audience: state.audience, status: name === "approve" ? "approved" : "rejected" }),
  });
  const payload = await response.json();
  state.notice = payload.note || "";
  await refresh();
}

document.addEventListener(
  "click",
  (event) => {
    const node = event.target?.nodeType === 1 ? event.target : event.target?.parentElement;
    if (!node?.closest) return;
    const pick = node.closest("[data-reel-cut]");
    if (!pick) return;
    event.preventDefault();
    state.reelCut = Number(pick.dataset.reelCut);
    document.querySelectorAll("[data-reel-cut]").forEach((button) => {
      button.classList.toggle("on", Number(button.dataset.reelCut) === state.reelCut);
    });
    const video = document.getElementById("reel-video");
    if (video) delete video.dataset.key;
    mountReel();
    document.getElementById("reel-video")?.play?.().catch(() => {});
    event.stopPropagation();
  },
  true
);

document.body.addEventListener("click", (event) => {
  const clubButton = event.target.closest("[data-club]");
  if (clubButton) {
    state.club = clubButton.dataset.club;
    state.focus = null;
    state.reel = null;
    state.reelCut = 0;
    render();
    return;
  }
  const audienceButton = event.target.closest("[data-audience]");
  if (audienceButton) {
    state.audience = audienceButton.dataset.audience;
    render();
    return;
  }
  const tabButton = event.target.closest("[data-tab]");
  if (tabButton) {
    state.tab = tabButton.dataset.tab;
    render();
    return;
  }
  const closeReel = event.target.closest("[data-close-reel]");
  if (closeReel) {
    state.focus = null;
    state.reelCut = 0;
    render();
    return;
  }
  if (event.target.closest("#reel") && !event.target.closest("[data-close-reel]")) {
    const reelPick = event.target.closest("[data-reel-cut]");
    if (reelPick) {
      event.preventDefault();
      event.stopPropagation();
      state.reelCut = Number(reelPick.dataset.reelCut);
      document.querySelectorAll("[data-reel-cut]").forEach((button) => {
        button.classList.toggle("on", Number(button.dataset.reelCut) === state.reelCut);
      });
      const video = document.getElementById("reel-video");
      if (video) delete video.dataset.key;
      mountReel();
    }
    return;
  }
  const playerButton = event.target.closest("[data-player]");
  if (playerButton) {
    state.focus = Number(playerButton.dataset.player);
    state.reelCut = 0;
    state.tab = "lineup";
    render();
    return;
  }
  const angleButton = event.target.closest("[data-angle]");
  if (angleButton) {
    state.angle[angleButton.dataset.play] = Number(angleButton.dataset.angle);
    render();
    return;
  }
  const action = event.target.closest("[data-act]");
  if (action) act(action.dataset.act, action.dataset.id, action.dataset.media);
});

document.body.addEventListener("change", (event) => {
  if (event.target.id === "reel-select") {
    state.reel = Number(event.target.value);
    render();
  }
});

document.getElementById("search").addEventListener("input", (event) => {
  state.query = event.target.value;
  if (state.tab === "live" && typeof liveSheet === "function") liveSheet();
  else render();
});

document.getElementById("search").addEventListener("keydown", (event) => {
  if (event.key !== "Enter") return;
  const hit = findHit(state.query);
  if (!hit) return;
  if (state.tab !== "live") state.club = hit.club;
  state.focus = hit.named_id || hit.heroes?.matchday?.id || null;
  state.reelCut = 0;
  if (state.tab !== "live") state.tab = "lineup";
  if (state.tab === "live" && typeof liveSheet === "function") liveSheet();
  else render();
});

refresh().catch((error) => {
  $("main").innerHTML = empty(esc(error.message || "The desk could not load the library."));
});
