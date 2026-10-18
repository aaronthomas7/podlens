/* PodLens client: streams an analysis, syncs claims with the YouTube player. */
(() => {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);

  const ICONS = {
    TRUE: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 8.5l3 3 7-7" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    MISLEADING: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2.5 9c1.5-2 3-2 4.5-.5s3 1.5 4.5-.5" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
    FALSE: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 4l8 8M12 4l-8 8" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
    OUTDATED: '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="5.6" fill="none" stroke="currentColor" stroke-width="2"/><path d="M8 5v3.3l2.2 1.4" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>',
    UNVERIFIABLE: '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5.8 6.2a2.3 2.3 0 1 1 3.3 2c-.7.4-1.1.8-1.1 1.6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/><circle cx="8" cy="12.4" r="1.1" fill="currentColor"/></svg>',
    PLAY: '<svg viewBox="0 0 10 10" aria-hidden="true"><path d="M2 1l7 4-7 4z" fill="currentColor"/></svg>',
  };
  const VERDICTS = {
    TRUE: { label: "True", count: "true", css: "true" },
    MISLEADING: { label: "Misleading", count: "misleading", css: "mis" },
    FALSE: { label: "False", count: "false", css: "false" },
    OUTDATED: { label: "Outdated", count: "outdated", css: "old" },
    UNVERIFIABLE: { label: "Couldn't verify", count: "couldn't verify", css: "unk" },
  };
  const ORDER = ["FALSE", "MISLEADING", "OUTDATED", "TRUE", "UNVERIFIABLE"];
  const VALUE = { TRUE: 1, OUTDATED: 0.5, MISLEADING: 0.3, FALSE: 0 };
  const WEIGHT = { high: 3, medium: 2, low: 1 };
  const CATEGORY = {
    health: "Health", finance: "Money", science: "Science", history: "History",
    politics: "Politics", statistics: "Numbers", current_events: "News", other: "General",
  };
  const LANG_CODES = {
    english: "en", hindi: "hi", malayalam: "ml", tamil: "ta", telugu: "te", kannada: "kn",
    bengali: "bn", marathi: "mr", gujarati: "gu", punjabi: "pa", urdu: "ur", japanese: "ja",
    korean: "ko", indonesian: "id", "bahasa indonesia": "id", malay: "ms", thai: "th",
    vietnamese: "vi", chinese: "zh", mandarin: "zh", filipino: "fil", tagalog: "tl",
  };
  const FILTERS = {
    all: () => true,
    bad: (c) => ["FALSE", "MISLEADING", "OUTDATED"].includes(c.verdict),
    true: (c) => c.verdict === "TRUE",
    unk: (c) => c.verdict === "UNVERIFIABLE",
  };

  const state = {
    id: null, video: null, window: null, claims: [], speakers: [], scoredSpeakers: null,
    summary: "", spokenLanguage: "", opinionsSkipped: 0, score: null, final: false, model: null,
    filter: "all", duration: null, player: null, playerReady: false, poll: null, nowId: null,
    request: null, abort: null, startedAt: 0, timer: null, config: null,
  };

  // ---------- small helpers ----------
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const [k, v] of Object.entries(attrs)) {
        if (v == null || v === false) continue;
        if (k === "class") el.className = v;
        else if (k === "text") el.textContent = v;
        else if (k === "svg") el.insertAdjacentHTML("afterbegin", v); // trusted, static icons only
        else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
        else el.setAttribute(k, v === true ? "" : String(v));
      }
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const clamp = (n, lo, hi) => Math.min(hi, Math.max(lo, n));
  const cap = (s) => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s);

  function fmt(sec) {
    sec = Math.max(0, Math.floor(sec || 0));
    const hh = Math.floor(sec / 3600), mm = Math.floor((sec % 3600) / 60), ss = sec % 60;
    const pad = (n) => String(n).padStart(2, "0");
    return hh ? `${hh}:${pad(mm)}:${pad(ss)}` : `${pad(mm)}:${pad(ss)}`;
  }

  function parseTime(text) {
    if (!text) return null;
    const t = String(text).trim().toLowerCase();
    if (/^\d+$/.test(t)) return +t;
    if (/^\d{1,3}(:\d{1,2}){1,2}$/.test(t)) return t.split(":").reduce((a, p) => a * 60 + +p, 0);
    const m = t.match(/^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$/);
    if (m && (m[1] || m[2] || m[3])) return (+m[1] || 0) * 3600 + (+m[2] || 0) * 60 + (+m[3] || 0);
    return NaN;
  }

  function parseVideo(url) {
    const raw = (url || "").trim();
    if (/^[A-Za-z0-9_-]{11}$/.test(raw)) return { id: raw, start: null };
    let u;
    try { u = new URL(/^https?:\/\//i.test(raw) ? raw : "https://" + raw); } catch { return null; }
    const host = u.hostname.toLowerCase().replace(/^www\./, "").replace(/^m\./, "");
    let id = null;
    if (host === "youtu.be") id = u.pathname.split("/")[1];
    else if (/(^|\.)youtube(-nocookie)?\.com$/.test(host)) {
      if (u.pathname === "/watch") id = u.searchParams.get("v");
      else {
        const m = u.pathname.match(/^\/(shorts|live|embed|v|e)\/([^/?#]+)/);
        if (m) id = m[2];
      }
    }
    if (!id || !/^[A-Za-z0-9_-]{11}$/.test(id)) return null;
    const t = u.searchParams.get("t") || u.searchParams.get("start");
    const start = t ? parseTime(t) : null;
    return { id, start: Number.isFinite(start) ? start : null };
  }

  function toast(text) {
    const el = $("#toast");
    el.textContent = text;
    el.hidden = false;
    clearTimeout(toast.t);
    toast.t = setTimeout(() => (el.hidden = true), 2200);
  }

  function band(value) {
    if (value == null) return "band-none";
    if (value >= 80) return "band-good";
    if (value >= 55) return "band-mixed";
    return "band-bad";
  }

  function computeScore(claims) {
    const counts = { TRUE: 0, MISLEADING: 0, FALSE: 0, OUTDATED: 0, UNVERIFIABLE: 0 };
    let total = 0, got = 0;
    for (const c of claims) {
      if (!c.verdict || !(c.verdict in counts)) continue;
      counts[c.verdict]++;
      if (c.verdict in VALUE) {
        const w = WEIGHT[c.importance] || 2;
        total += w;
        got += w * VALUE[c.verdict];
      }
    }
    const value = total ? Math.round((100 * got) / total) : null;
    return { value, counts };
  }

  async function readNdjson(res, onEvent) {
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let i;
      while ((i = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, i).trim();
        buf = buf.slice(i + 1);
        if (line) onEvent(JSON.parse(line));
      }
    }
    if (buf.trim()) onEvent(JSON.parse(buf));
  }

  // ---------- views ----------
  function showHome() {
    stopRun();
    destroyPlayer();
    $("#result").hidden = true;
    $("#home").hidden = false;
    $("#topnav").hidden = true;
    document.title = "PodLens: fact-check any YouTube video";
    loadRecent();
  }

  function showResult() {
    $("#home").hidden = true;
    $("#result").hidden = false;
    $("#topnav").hidden = false;
    window.scrollTo({ top: 0 });
  }

  function resetResult() {
    Object.assign(state, {
      id: null, video: null, window: null, claims: [], speakers: [], scoredSpeakers: null,
      summary: "", spokenLanguage: "", opinionsSkipped: 0, score: null, final: false, model: null,
      filter: "all", duration: null, nowId: null, claimsKnown: false,
    });
    $("#mock-banner").hidden = !(state.config && state.config.mock);
    $("#video-title").textContent = "Loading video…";
    $("#video-author").textContent = "";
    $("#score").hidden = true;
    $("#speakers").hidden = true;
    $("#about").hidden = true;
    $("#error-box").hidden = true;
    $("#claims").replaceChildren();
    $("#claims-empty").hidden = true;
    $("#run-info").textContent = "";
    $("#fl-ticks").replaceChildren();
    $("#fl-window").style.display = "none";
    $("#fl-end").textContent = "";
    $("#vtrack").classList.remove("watching");
    setFilter("all");
    setProgress("Starting");
    $("#progress").hidden = false;
  }

  function setProgress(text) {
    $("#progress-text").textContent = text;
  }

  function startTimer() {
    state.startedAt = Date.now();
    clearInterval(state.timer);
    const tick = () => {
      const s = Math.round((Date.now() - state.startedAt) / 1000);
      $("#elapsed").textContent = s >= 2 ? `${s}s` : "";
    };
    tick();
    state.timer = setInterval(tick, 1000);
  }

  function stopRun() {
    if (state.abort) state.abort.abort();
    state.abort = null;
    clearInterval(state.timer);
  }

  function showError(message, { retry = true } = {}) {
    $("#progress").hidden = true;
    $("#vtrack").classList.remove("watching");
    $("#error-text").textContent = message;
    $("#retry-btn").hidden = !retry;
    $("#error-box").hidden = false;
    clearInterval(state.timer);
  }

  // ---------- YouTube player ----------
  let ytPromise = null;
  function loadYT() {
    if (window.YT && window.YT.Player) return Promise.resolve(window.YT);
    if (ytPromise) return ytPromise;
    ytPromise = new Promise((resolve) => {
      window.onYouTubeIframeAPIReady = () => resolve(window.YT);
      const s = document.createElement("script");
      s.src = "https://www.youtube.com/iframe_api";
      s.onerror = () => resolve(null);
      document.head.append(s);
      setTimeout(() => resolve(window.YT && window.YT.Player ? window.YT : null), 8000);
    });
    return ytPromise;
  }

  function destroyPlayer() {
    clearInterval(state.poll);
    if (state.player && state.player.destroy) {
      try { state.player.destroy(); } catch (_) { /* ignore */ }
    }
    state.player = null;
    state.playerReady = false;
    const wrap = $(".player-wrap");
    const old = $("#player");
    if (old) old.remove();
    wrap.prepend(h("div", { id: "player" }));
    $("#player-msg").hidden = true;
  }

  function showPlayerMsg(text) {
    const el = $("#player-msg");
    el.textContent = text;
    el.hidden = false;
  }

  async function mountPlayer(videoId, start) {
    destroyPlayer();
    const YT = await loadYT();
    if (!YT) {
      showPlayerMsg("The video player couldn't load here, but the fact-check still works.");
      return null;
    }
    return new Promise((resolve) => {
      let settled = false;
      const done = (v) => { if (!settled) { settled = true; resolve(v); } };
      state.player = new YT.Player("player", {
        videoId,
        playerVars: { rel: 0, playsinline: 1, modestbranding: 1, start: Math.floor(start || 0) },
        events: {
          onReady: (e) => {
            state.playerReady = true;
            const d = e.target.getDuration ? e.target.getDuration() : 0;
            if (d > 0) setDuration(d);
            startPolling();
            done(d > 0 ? d : null);
          },
          onError: () => {
            showPlayerMsg("This video can't be played here. Timestamps will open it on YouTube instead.");
            state.playerReady = false;
            done(null);
          },
        },
      });
      setTimeout(() => done(null), 5000);
    });
  }

  function startPolling() {
    clearInterval(state.poll);
    state.poll = setInterval(() => {
      const p = state.player;
      if (!p || !state.playerReady || !p.getCurrentTime) return;
      const t = p.getCurrentTime();
      if (!state.duration && p.getDuration && p.getDuration() > 0) setDuration(p.getDuration());
      movePlayhead(t);
      markNow(t);
    }, 400);
  }

  function seekTo(seconds) {
    const p = state.player;
    if (p && state.playerReady && p.seekTo) {
      p.seekTo(seconds, true);
      if (p.playVideo) p.playVideo();
      movePlayhead(seconds);
      if (window.matchMedia("(max-width: 960px)").matches) {
        $(".player-wrap").scrollIntoView({ behavior: "smooth", block: "start" });
      }
    } else if (state.video) {
      window.open(`https://www.youtube.com/watch?v=${state.video.id}&t=${Math.floor(seconds)}s`, "_blank", "noopener");
    }
  }

  // ---------- the timeline track ----------
  function effectiveDuration() {
    if (state.duration) return state.duration;
    if (state.video && state.video.duration) return state.video.duration;
    // Unknown length (player blocked): size the track to the claims, not to the analysis cap.
    const last = state.claims.reduce((m, c) => Math.max(m, c.seconds || 0), 0);
    const w = state.window;
    const userEnd = w && w.end && !w.auto ? w.end : 0;
    return Math.max(userEnd, Math.ceil((last + 30) / 60) * 60, 60);
  }

  function setDuration(d) {
    state.duration = d;
    layoutTrack();
  }

  function pct(sec) {
    return clamp((sec / effectiveDuration()) * 100, 0.6, 99.4);
  }

  function layoutTrack() {
    const d = effectiveDuration();
    $("#fl-end").textContent = fmt(d);
    const steps = [60, 120, 300, 600, 900, 1800, 3600];
    const step = steps.find((s) => d / s <= 24) || 3600;
    $("#fl-track").style.backgroundSize = `${(step / d) * 100}% 100%`;
    const w = state.window;
    const bandEl = $("#fl-window");
    if (w && (w.start || w.end)) {
      const s = w.start || 0;
      const e = Math.min(w.end || d, d);
      bandEl.style.left = `${(s / d) * 100}%`;
      bandEl.style.width = `${Math.max(0, ((e - s) / d) * 100)}%`;
      bandEl.style.display = "block";
    } else {
      bandEl.style.display = "none";
    }
    for (const tick of $("#fl-ticks").children) {
      const c = state.claims.find((x) => x.id === tick.dataset.id);
      if (c) tick.style.left = `${pct(c.seconds)}%`;
    }
  }

  function movePlayhead(t) {
    $("#fl-head").style.left = `${clamp((t / effectiveDuration()) * 100, 0, 100)}%`;
  }

  function tickLabel(c) {
    const v = c.verdict ? VERDICTS[c.verdict].label : "Checking";
    return `${c.timestamp}, ${v}: ${c.claim}`;
  }

  function renderTicks() {
    const ticks = state.claims.map((c) =>
      h("button", {
        class: "fl-tick" + (c.verdict ? ` v-${c.verdict}` : " pending") + (state.nowId === c.id ? " is-now" : ""),
        type: "button",
        "data-id": c.id,
        style: `left:${pct(c.seconds)}%`,
        title: tickLabel(c),
        "aria-label": tickLabel(c),
        onclick: (e) => { e.stopPropagation(); revealClaim(c.id); seekTo(c.seconds); },
      })
    );
    $("#fl-ticks").replaceChildren(...ticks);
    layoutTrack();
  }

  function updateTick(c) {
    const tick = $(`.fl-tick[data-id="${c.id}"]`);
    if (!tick) return;
    tick.className = "fl-tick" + (c.verdict ? ` v-${c.verdict}` : " pending") + (state.nowId === c.id ? " is-now" : "");
    tick.title = tickLabel(c);
    tick.setAttribute("aria-label", tickLabel(c));
  }

  function markNow(t) {
    // The claim being discussed right now: the latest one that started within the last 25 seconds.
    let now = null;
    for (const c of state.claims) {
      if (c.seconds <= t + 0.5 && t - c.seconds < 25) now = c;
    }
    const id = now ? now.id : null;
    if (id === state.nowId) return;
    if (state.nowId) {
      document.getElementById(`claim-${state.nowId}`)?.classList.remove("is-now");
      $(`.fl-tick[data-id="${state.nowId}"]`)?.classList.remove("is-now");
    }
    state.nowId = id;
    if (id) {
      document.getElementById(`claim-${id}`)?.classList.add("is-now");
      $(`.fl-tick[data-id="${id}"]`)?.classList.add("is-now");
    }
  }

  function revealClaim(id) {
    const c = state.claims.find((x) => x.id === id);
    if (c && !FILTERS[state.filter](c)) setFilter("all");
    const el = document.getElementById(`claim-${id}`);
    if (el) el.scrollIntoView({ behavior: "smooth", block: "center" });
  }

  // ---------- claims ----------
  function speakerLabel(id) {
    if (id === "on-screen") return "On-screen text";
    const s = state.speakers.find((x) => x.id === id);
    return s ? s.label : id;
  }

  function langCode(name) {
    return LANG_CODES[(name || "").trim().toLowerCase()] || null;
  }

  function normalizeText(s) {
    return (s || "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
  }

  function badge(c) {
    if (!c.verdict) {
      return h("span", { class: "badge pending" }, h("span", { class: "spinner", "aria-hidden": "true" }), "Checking");
    }
    return h("span", { class: `badge v-${c.verdict}`, svg: ICONS[c.verdict] }, VERDICTS[c.verdict].label);
  }

  function evidence(c) {
    const sources = c.sources || [];
    const n = sources.length;
    const closedText = n ? `Show evidence (${n} ${n === 1 ? "source" : "sources"})` : "Show details";
    const summary = h("summary", { text: closedText });
    const body = h("div", { class: "evidence-body" });

    if (c.correction) {
      body.append(h("div", null, h("h4", { text: "What the evidence says" }), h("p", { class: "correction", text: c.correction })));
    }
    if (c.explanation) body.append(h("p", { text: c.explanation }));
    if (n) {
      body.append(
        h("div", null,
          h("h4", { text: "Sources" }),
          h("ul", { class: "sources" },
            sources.map((s) =>
              h("li", null,
                h("a", { href: s.uri, target: "_blank", rel: "noopener noreferrer" },
                  h("img", { src: `https://www.google.com/s2/favicons?domain=${encodeURIComponent(s.domain || "")}&sz=32`, alt: "", loading: "lazy", width: 16, height: 16 }),
                  h("span", null, h("span", { class: "src-title", text: s.title || s.domain }), h("span", { class: "src-domain", text: s.domain })),
                  h("span", { class: `kind ${s.kind}`, text: s.kind_label || "Web" })
                )
              )
            )
          )
        )
      );
    }
    if (c.search_queries && c.search_queries.length) {
      body.append(h("p", { class: "queries", text: `Searched for: ${c.search_queries.join("; ")}` }));
    }
    if (c.suggestions_html) {
      const host = h("div", { class: "gsearch" });
      host.attachShadow({ mode: "open" }).innerHTML = c.suggestions_html; // from Google, sanitized on the server
      body.append(host);
    }
    const details = h("details", { class: "evidence" }, summary, body);
    details.addEventListener("toggle", () => {
      summary.textContent = details.open ? "Hide evidence" : closedText;
    });
    return details;
  }

  function fillClaim(el, c, animate) {
    el.className = "claim" + (c.verdict ? ` v-${c.verdict}` : " pending") + (state.nowId === c.id ? " is-now" : "");
    const showQuote = c.quote && normalizeText(c.quote) !== normalizeText(c.claim);
    const nonEnglish = c.quote_english && normalizeText(c.quote_english) !== normalizeText(c.quote);
    const ruleNote =
      c.rule === "no_sources" && c.model_verdict
        ? `Gemini's own answer was "${VERDICTS[c.model_verdict]?.label || c.model_verdict}", but with no source to back it up, PodLens doesn't count it.`
        : c.rule === "error" ? "This claim couldn't be checked this time, so it isn't scored." : null;

    el.replaceChildren(
      h("button", { class: "ts", type: "button", "aria-label": `Play from ${c.timestamp}`, svg: ICONS.PLAY, onclick: () => seekTo(c.seconds) }, c.timestamp),
      h("div", { class: "claim-body" },
        h("div", { class: "claim-meta" },
          h("span", { class: "who", text: speakerLabel(c.speaker) }),
          c.on_screen && c.speaker !== "on-screen" ? h("span", { text: "On screen" }) : null,
          h("span", { text: CATEGORY[c.category] || "General" }),
          badge(c),
          c.verdict && c.confidence && c.rule == null ? h("span", { class: "conf", text: `${cap(c.confidence)} confidence` }) : null
        ),
        h("p", { class: "claim-text" }, h("mark", { text: c.claim })),
        showQuote ? h("p", { class: "quote", lang: langCode(state.spokenLanguage), text: `“${c.quote}”` }) : null,
        showQuote && nonEnglish ? h("p", { class: "quote", lang: "en", text: `In English: “${c.quote_english}”` }) : null,
        c.verdict && c.summary ? h("p", { class: "verdict-summary", text: c.summary }) : null,
        ruleNote ? h("p", { class: "rule-note", text: ruleNote }) : null,
        c.verdict ? evidence(c) : null
      )
    );
    el.hidden = !FILTERS[state.filter](c);
    if (animate) {
      el.classList.add("painting");
      setTimeout(() => el.classList.remove("painting"), 900);
    }
  }

  function renderClaims() {
    const list = $("#claims");
    const els = state.claims.map((c) => {
      const el = h("article", { id: `claim-${c.id}`, "data-id": c.id });
      fillClaim(el, c, false);
      return el;
    });
    list.replaceChildren(...els);
    updateEmpty();
    updateFilterCounts();
  }

  function updateClaim(c, animate) {
    const el = document.getElementById(`claim-${c.id}`);
    if (el) fillClaim(el, c, animate);
    updateTick(c);
    updateFilterCounts();
    updateEmpty();
  }

  function updateEmpty() {
    const empty = $("#claims-empty");
    if (state.claims.length === 0) {
      if (state.final || state.claimsKnown) {
        const skipped = state.opinionsSkipped ? ` It skipped ${state.opinionsSkipped} opinions or personal statements.` : "";
        empty.textContent = `Gemini didn't find factual claims to check in this part of the video.${skipped}`;
        empty.hidden = false;
      }
      return;
    }
    const visible = state.claims.filter(FILTERS[state.filter]).length;
    if (visible === 0 && state.filter !== "all") {
      empty.textContent = "No claims in this group yet.";
      empty.hidden = false;
    } else {
      empty.hidden = true;
    }
  }

  function setFilter(name) {
    state.filter = name;
    for (const b of document.querySelectorAll("#filters button")) {
      b.setAttribute("aria-checked", String(b.dataset.filter === name));
    }
    for (const c of state.claims) {
      const el = document.getElementById(`claim-${c.id}`);
      if (el) el.hidden = !FILTERS[name](c);
    }
    updateEmpty();
  }

  function updateFilterCounts() {
    const labels = { all: "All", bad: "Wrong or misleading", true: "True", unk: "Couldn't verify" };
    for (const b of document.querySelectorAll("#filters button")) {
      const f = b.dataset.filter;
      const n = state.claims.filter(FILTERS[f]).length;
      b.textContent = state.claims.length ? `${labels[f]} (${n})` : labels[f];
    }
  }

  // ---------- score, speakers, about ----------
  function renderScore() {
    const live = computeScore(state.claims);
    const final = state.final && state.score;
    const value = final ? state.score.value : live.value;
    const counts = final ? state.score.counts : live.counts;
    const checked = Object.values(counts).reduce((a, b) => a + b, 0);
    if (!checked) { $("#score").hidden = true; return; }
    $("#score").hidden = false;

    const num = $("#score-num");
    num.textContent = value == null ? "–" : String(value);
    num.className = `score-num ${band(value)}`;
    const label = $("#score-label");
    label.className = `score-label ${band(value)}`;
    if (final) label.textContent = state.score.label;
    else label.textContent = value == null ? "Checking claims" : `So far, ${checked} of ${state.claims.length} checked`;

    $("#vbar").replaceChildren(
      ...ORDER.filter((v) => counts[v]).map((v) =>
        h("span", { class: `t-${VERDICTS[v].css}`, style: `flex-grow:${counts[v]}`, title: `${counts[v]} ${VERDICTS[v].count}` })
      )
    );
    $("#counts").replaceChildren(
      ...ORDER.filter((v) => counts[v]).map((v) =>
        h("li", null, h("i", { class: `t-${VERDICTS[v].css}` }), `${counts[v]} ${VERDICTS[v].count}`)
      )
    );
    $("#method-text").textContent =
      (state.score && state.score.method) ||
      "Each checked claim counts True = 100, Outdated = 50, Misleading = 30, False = 0. High-importance claims count 3x and medium 2x. Claims PodLens couldn't verify are shown but left out of the score.";
  }

  function renderSpeakers() {
    const list = state.scoredSpeakers || state.speakers.map((s) => {
      const mine = state.claims.filter((c) => c.speaker === s.id);
      const sc = computeScore(mine);
      return { ...s, score: sc.value, claims: mine.length, counts: sc.counts };
    });
    const withClaims = list.filter((s) => s.claims > 0 && s.id !== "on-screen");
    if (withClaims.length < 2) { $("#speakers").hidden = true; return; }
    $("#speakers").hidden = false;
    $("#speaker-list").replaceChildren(
      ...withClaims.map((s) =>
        h("li", { class: "speaker-row" },
          h("span", { class: "name", text: s.label }),
          h("span", { class: `num ${band(s.score)}`, text: s.score == null ? "–" : String(s.score) }),
          h("span", { class: "minibar", "aria-hidden": "true" },
            ORDER.filter((v) => s.counts && s.counts[v]).map((v) =>
              h("span", { class: `t-${VERDICTS[v].css}`, style: `flex-grow:${s.counts[v]}` })
            )
          )
        )
      )
    );
  }

  function renderAbout() {
    if (!state.summary && !state.window) return;
    $("#about").hidden = false;
    $("#summary").textContent = state.summary || "";
    const bits = [];
    if (state.spokenLanguage) bits.push(`Spoken in ${state.spokenLanguage}.`);
    if (state.window) {
      const w = state.window;
      const what = w.label === "Whole video" ? "the whole video" : w.auto ? `up to the first ${Math.round((w.end || 0) / 60)} minutes` : w.label;
      bits.push(`Checked: ${what}.`);
    }
    if (state.window && state.window.note) bits.push(state.window.note);
    if (state.opinionsSkipped) bits.push(`${state.opinionsSkipped} opinions or personal statements were skipped.`);
    $("#window-note").textContent = bits.join(" ");
  }

  function renderVideo(video) {
    state.video = video;
    $("#video-title").textContent = video.title || "YouTube video";
    $("#video-author").textContent = video.author || "";
    document.title = `${video.title || "Video"} – PodLens`;
  }

  function renderRunInfo(a) {
    if (!a) return;
    if (a.mock) {
      $("#run-info").textContent = "Sample run in mock mode. No real checks were made.";
      return;
    }
    const when = a.created_at ? new Date(a.created_at).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "";
    const parts = [`Checked${when ? ` on ${when}` : ""} with ${a.model || "Gemini"} and Google Search`];
    if (a.seconds_taken) parts.push(` in ${Math.round(a.seconds_taken)} seconds`);
    $("#run-info").textContent = parts.join("") + ".";
  }

  // ---------- applying events ----------
  function applyAnalysis(a) {
    state.id = a.id;
    state.final = true;
    state.claimsKnown = true;
    state.model = a.model;
    state.window = a.window;
    state.summary = a.summary;
    state.spokenLanguage = a.spoken_language;
    state.opinionsSkipped = a.opinions_skipped;
    state.score = a.score;
    state.speakers = (a.speakers || []).map((s) => ({ id: s.id, label: s.label }));
    state.scoredSpeakers = (a.speakers || []).some((s) => "score" in s) ? a.speakers : null;
    state.claims = (a.claims || []).map((c) => ({ ...c }));
    $("#mock-banner").hidden = !a.mock;
    renderVideo(a.video || { id: a.video_id });
    $("#progress").hidden = true;
    $("#vtrack").classList.remove("watching");
    renderClaims();
    renderTicks();
    renderScore();
    renderSpeakers();
    renderAbout();
    renderRunInfo(a);
    if (location.pathname !== `/a/${a.id}`) history.replaceState(null, "", `/a/${a.id}`);
    clearInterval(state.timer);
  }

  function onEvent(ev) {
    switch (ev.type) {
      case "ping":
        break;
      case "status":
        setProgress(ev.message);
        if (ev.stage === "watching") $("#vtrack").classList.add("watching");
        break;
      case "meta":
        state.id = ev.analysis_id;
        state.window = ev.window;
        state.model = ev.model;
        if (ev.analysis_id && location.pathname !== `/a/${ev.analysis_id}`) {
          history.replaceState(null, "", `/a/${ev.analysis_id}`);
        }
        renderVideo(ev.video);
        if (!state.player && ev.video) mountPlayer(ev.video.id, ev.window ? ev.window.start : 0);
        if (ev.video && ev.video.duration && !state.duration) setDuration(ev.video.duration);
        layoutTrack();
        break;
      case "claims":
        $("#vtrack").classList.remove("watching");
        state.claimsKnown = true;
        state.summary = ev.summary;
        state.spokenLanguage = ev.language;
        state.opinionsSkipped = ev.opinions_skipped;
        state.speakers = ev.speakers || [];
        if (ev.window) state.window = ev.window;
        state.claims = (ev.claims || []).map((c) => ({ ...c }));
        renderClaims();
        renderTicks();
        renderAbout();
        break;
      case "verdict": {
        const c = state.claims.find((x) => x.id === ev.claim_id);
        if (!c) break;
        const { type, claim_id, ...rest } = ev;
        Object.assign(c, rest);
        updateClaim(c, true);
        renderScore();
        renderSpeakers();
        break;
      }
      case "score":
        state.score = ev.score;
        state.scoredSpeakers = ev.speakers;
        break;
      case "done":
        applyAnalysis(ev.analysis);
        if (ev.analysis && ev.analysis.video && !state.player) mountPlayer(ev.analysis.video.id, 0);
        break;
      case "error":
        showError(ev.message);
        break;
    }
  }

  // ---------- running a check ----------
  async function startCheck(req) {
    stopRun();
    state.request = req;
    resetResult();
    showResult();
    startTimer();
    setProgress("Opening the video");
    $("#vtrack").classList.add("watching");

    const duration = await Promise.race([mountPlayer(req.videoId, req.start), sleep(3000).then(() => null)]);
    await runStream("/api/analyze", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        url: req.url, start: req.startText || null, end: req.endText || null,
        language: req.language, duration: duration || state.duration || null,
      }),
    }, { fromForm: true });
  }

  async function runStream(url, options, { fromForm = false } = {}) {
    state.abort = new AbortController();
    let sawEnd = false;
    try {
      const res = await fetch(url, { ...options, signal: state.abort.signal });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        const message = data.error || "Something went wrong. Please try again.";
        if (fromForm && res.status === 400) {
          history.replaceState(null, "", "/");
          showHome();
          showFormError(message);
          return;
        }
        showError(message, { retry: res.status !== 404 });
        return;
      }
      await readNdjson(res, (ev) => {
        if (ev.type === "done" || ev.type === "error") sawEnd = true;
        onEvent(ev);
      });
      if (!sawEnd) showError("The connection dropped before the check finished. Try again to pick up where it left off.");
    } catch (err) {
      if (err.name === "AbortError") return;
      showError("Couldn't reach PodLens. Check your connection and try again.");
    }
  }

  async function openAnalysis(id) {
    stopRun();
    resetResult();
    showResult();
    setProgress("Loading the fact-check");
    try {
      const res = await fetch(`/api/analysis/${encodeURIComponent(id)}`);
      if (res.ok) {
        const a = await res.json();
        applyAnalysis(a);
        mountPlayer(a.video.id, 0);
        return;
      }
    } catch (_) { /* fall through to stream */ }
    startTimer();
    await runStream(`/api/stream/${encodeURIComponent(id)}`, { method: "GET" });
  }

  // ---------- home ----------
  function showFormError(text) {
    const el = $("#form-error");
    el.textContent = text;
    el.hidden = !text;
    if (text) $("#url").focus();
  }

  async function loadRecent() {
    try {
      const res = await fetch("/api/recent");
      if (!res.ok) return;
      const items = await res.json();
      if (!items.length) { $("#recent").hidden = true; return; }
      $("#recent").hidden = false;
      $("#recent-list").replaceChildren(
        ...items.map((it) =>
          h("li", null,
            h("a", { href: `/a/${it.id}`, "data-id": it.id, onclick: (e) => { e.preventDefault(); history.pushState(null, "", `/a/${it.id}`); openAnalysis(it.id); } },
              h("img", { src: it.thumbnail, alt: "", loading: "lazy" }),
              h("p", { class: "recent-title", text: it.title }),
              h("p", { class: "recent-meta" },
                h("span", { class: `score-pill t-${it.score == null ? "unk" : it.score >= 80 ? "true" : it.score >= 55 ? "mis" : "false"}`, text: it.score == null ? "–" : String(it.score) }),
                `${it.score_label || ""}${it.claims ? `, ${it.claims} claims` : ""}`
              )
            )
          )
        )
      );
    } catch (_) { /* recent list is optional */ }
  }

  async function loadConfig() {
    try {
      const res = await fetch("/api/config");
      const cfg = await res.json();
      state.config = cfg;
      const sel = $("#language");
      sel.replaceChildren(...cfg.languages.map((l) => h("option", { value: l, text: l })));
      $("#mock-banner").hidden = !cfg.mock;
      $("#engine-info").textContent = cfg.mock
        ? "Running in mock mode with sample data."
        : `Built with ${cfg.model} and Google Search grounding, running on Google Cloud Run.`;
    } catch (_) { /* keep defaults */ }
  }

  function bind() {
    $("#check-form").addEventListener("submit", (e) => {
      e.preventDefault();
      showFormError("");
      const url = $("#url").value.trim();
      if (!url) return showFormError("Paste a YouTube link first.");
      const video = parseVideo(url);
      if (!video) return showFormError("That doesn't look like a YouTube link. Copy it from the address bar or the Share button on YouTube.");
      const rangeOn = !$("#range-fields").hidden;
      const startText = rangeOn ? $("#start").value.trim() : "";
      const endText = rangeOn ? $("#end").value.trim() : "";
      const s = parseTime(startText), en = parseTime(endText);
      if ((startText && !Number.isFinite(s)) || (endText && !Number.isFinite(en))) {
        return showFormError("Write times like 2:30 or 1:05:00.");
      }
      if (Number.isFinite(s) && Number.isFinite(en) && startText && endText && en <= s) {
        return showFormError("The end time has to be after the start time.");
      }
      history.pushState(null, "", "/");
      startCheck({
        url, videoId: video.id, start: startText ? s : video.start, startText, endText,
        language: $("#language").value || "English",
      });
    });

    $("#range-toggle").addEventListener("click", () => {
      const fields = $("#range-fields");
      fields.hidden = !fields.hidden;
      $("#range-toggle").setAttribute("aria-expanded", String(!fields.hidden));
      if (!fields.hidden) $("#start").focus();
    });

    $("#url").addEventListener("input", () => {
      const v = parseVideo($("#url").value);
      if (v && v.start && !$("#start").value) $("#start").value = fmt(v.start);
    });

    $("#filters").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-filter]");
      if (b) setFilter(b.dataset.filter);
    });

    $("#fl-track").addEventListener("click", (e) => {
      if (e.target.closest(".fl-tick")) return;
      const rect = e.currentTarget.getBoundingClientRect();
      const frac = clamp((e.clientX - rect.left) / rect.width, 0, 1);
      seekTo(frac * effectiveDuration());
    });

    $("#share-btn").addEventListener("click", async () => {
      const link = state.id ? `${location.origin}/a/${state.id}` : location.href;
      try {
        await navigator.clipboard.writeText(link);
        toast("Link copied");
      } catch (_) {
        window.prompt("Copy this link:", link);
      }
    });

    $("#new-btn").addEventListener("click", (e) => {
      e.preventDefault();
      history.pushState(null, "", "/");
      showHome();
      $("#url").value = "";
      $("#url").focus();
    });
    $(".brand").addEventListener("click", (e) => {
      e.preventDefault();
      history.pushState(null, "", "/");
      showHome();
    });

    $("#retry-btn").addEventListener("click", () => {
      $("#error-box").hidden = true;
      if (state.request) startCheck(state.request);
      else if (state.id) openAnalysis(state.id);
      else showHome();
    });

    window.addEventListener("popstate", route);
  }

  function route() {
    const m = location.pathname.match(/^\/a\/([A-Za-z0-9]+)\/?$/);
    if (m) openAnalysis(m[1]);
    else showHome();
  }

  bind();
  loadConfig();
  route();
})();
