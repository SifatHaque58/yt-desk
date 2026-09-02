const $ = (id) => document.getElementById(id);

let homeToken = null;
let homeSource = "news";
let homeQuery = "news";
let searchToken = null;
let relatedToken = null;
let currentVideo = "";
let suggestTimer = 0;
let suggestOn = -1;
let suggestSeq = 0;
let skipHist = false;

function show(view) {
  $("view_home").hidden = view !== "home";
  $("view_search").hidden = view !== "search";
  $("view_watch").hidden = view !== "watch";
  if (view !== "watch") stopPlayer();
}

function stopPlayer() {
  const frame = $("player");
  if (frame && frame.src) frame.src = "";
}

function fail(msg) {
  const el = $("err");
  if (!msg) {
    el.hidden = true;
    el.textContent = "";
    return;
  }
  el.hidden = false;
  el.textContent = msg;
}

function thumb(id) {
  return id ? `https://i.ytimg.com/vi/${id}/hqdefault.jpg` : "";
}

function compact(n) {
  if (n == null) return "";
  if (n >= 1e9) return `${(n / 1e9).toFixed(n >= 1e10 ? 0 : 1)}B`.replace(/\.0B$/, "B");
  if (n >= 1e6) return `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M`.replace(/\.0M$/, "M");
  if (n >= 1e3) return `${(n / 1e3).toFixed(n >= 1e4 ? 0 : 1)}K`.replace(/\.0K$/, "K");
  return String(n);
}

function views(n) {
  if (n == null) return "";
  return `${compact(n)} views`;
}

function cardMeta(v) {
  return [v.channel, v.published].filter(Boolean).join(" · ");
}

function thumbBlock(v, { rail = false } = {}) {
  const badges = [];
  if (!rail && v.views != null) badges.push(`<span class="views-badge">${views(v.views)}</span>`);
  if (v.length) badges.push(`<span class="len-badge">${escapeHtml(v.length)}</span>`);
  return `<span class="thumb-wrap"><img class="thumb" alt="" src="${thumb(v.video_id)}" />${badges.join("")}</span>`;
}

function escapeHtml(s) {
  return String(s || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function videoCard(v) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "card";
  btn.innerHTML = `${thumbBlock(v)}<h3></h3><p></p>`;
  btn.querySelector("h3").textContent = v.title || v.video_id;
  btn.querySelector("p").textContent = cardMeta(v);
  btn.addEventListener("click", () => openWatch(v.video_id));
  return btn;
}

function railItem(v) {
  const btn = document.createElement("button");
  btn.type = "button";
  btn.className = "rail-item";
  btn.innerHTML = `${thumbBlock(v, { rail: true })}<div><h4></h4><p></p></div>`;
  btn.querySelector("h4").textContent = v.title || v.video_id;
  const bits = [v.channel, views(v.views), v.published].filter(Boolean);
  btn.querySelector("p").textContent = bits.join(" · ");
  btn.addEventListener("click", () => openWatch(v.video_id));
  return btn;
}

function renderStats(v) {
  const el = $("watch_stats");
  el.innerHTML = "";
  const bits = [
    [v.views, "views"],
    [v.likes, "likes"],
    [v.comments, "comments"],
  ];
  for (const [n, label] of bits) {
    if (n == null) continue;
    const span = document.createElement("span");
    span.className = "stat";
    span.textContent = `${compact(n)} ${label}`;
    el.appendChild(span);
  }
}

function skeletons(n = 8) {
  const frag = document.createDocumentFragment();
  for (let i = 0; i < n; i++) {
    const d = document.createElement("div");
    d.className = "skel-card";
    d.innerHTML = `<div class="skel thumb"></div><div class="skel line"></div><div class="skel line short"></div>`;
    frag.appendChild(d);
  }
  return frag;
}

function emptyBox(text) {
  const p = document.createElement("p");
  p.className = "empty";
  p.textContent = text;
  return p;
}

function setUrl(view, extra = {}) {
  if (skipHist) return;
  const u = new URL(location.origin + "/");
  if (view === "search" && extra.q) u.searchParams.set("q", extra.q);
  if (view === "watch" && extra.v) u.searchParams.set("v", extra.v);
  const state = { view, ...extra };
  const method = extra.replace ? "replaceState" : "pushState";
  history[method](state, "", u);
}

async function api(path, opts) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function jsonPost(path, body) {
  return api(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
}

async function loadCountries() {
  const rows = await api("/api/countries");
  const sel = $("country");
  const session = await api("/api/session");
  sel.innerHTML = "";
  for (const r of rows) {
    const opt = document.createElement("option");
    opt.value = r.code;
    opt.textContent = r.name;
    sel.appendChild(opt);
  }
  sel.value = session.gl;
}

async function loadHome() {
  show("home");
  fail("");
  document.title = "yt-desk";
  setUrl("home", { replace: !history.state });
  const grid = $("home_grid");
  grid.innerHTML = "";
  grid.appendChild(skeletons());
  $("home_more").hidden = true;
  try {
    const data = await api("/api/home");
    const source = data.source || "news";
    homeSource = source;
    homeQuery = data.query || homeQuery;
    $("home_title").textContent =
      source === "home" ? "Home" : source === "trending" ? "Trending" : "This week";
    const need = data.need || 3;
    const n = data.watches || 0;
    $("home_note").textContent =
      source === "home"
        ? `Feed for this exit after ${n} watches.`
        : source === "trending"
          ? `Trending here. Watch ${Math.max(0, need - n)} more to try For You.`
          : `What’s circulating this week. Watch ${Math.max(0, need - n)} more, then Home will ask For You.`;
    grid.innerHTML = "";
    const videos = data.videos || [];
    if (!videos.length) grid.appendChild(emptyBox("Nothing ranked for this exit yet. Try a search."));
    for (const v of videos) grid.appendChild(videoCard(v));
    homeToken = data.continuation || null;
    $("home_more").hidden = !homeToken;
  } catch (err) {
    grid.innerHTML = "";
    grid.appendChild(emptyBox(err.message));
  }
}

async function moreHome() {
  if (!homeToken) return;
  $("home_more").disabled = true;
  try {
    let data;
    if (homeSource === "trending") {
      data = await jsonPost("/api/trending", { continuation: homeToken });
    } else if (homeSource === "news") {
      data = await jsonPost("/api/search", {
        q: homeQuery,
        uploaded: "week",
        continuation: homeToken,
      });
    } else {
      data = await jsonPost("/api/home", { continuation: homeToken });
    }
    for (const v of data.videos || []) $("home_grid").appendChild(videoCard(v));
    homeToken = data.continuation || null;
    $("home_more").hidden = !homeToken;
  } catch (err) {
    fail(err.message);
  } finally {
    $("home_more").disabled = false;
  }
}

async function runSearch() {
  const q = $("q").value.trim();
  if (!q) return;
  show("search");
  fail("");
  $("suggest").hidden = true;
  document.title = `${q} · yt-desk`;
  setUrl("search", { q });
  $("search_title").textContent = q;
  const grid = $("search_grid");
  grid.innerHTML = "";
  grid.appendChild(skeletons(6));
  $("search_more").hidden = true;
  try {
    const uploaded = $("uploaded").value;
    const body = { q };
    if (uploaded) body.uploaded = uploaded;
    const data = await jsonPost("/api/search", body);
    grid.innerHTML = "";
    const videos = data.videos || [];
    if (!videos.length) grid.appendChild(emptyBox(`No videos for “${q}”.`));
    for (const v of videos) grid.appendChild(videoCard(v));
    searchToken = data.continuation || null;
    $("search_more").hidden = !searchToken;
  } catch (err) {
    grid.innerHTML = "";
    grid.appendChild(emptyBox(err.message));
  }
}

async function moreSearch() {
  if (!searchToken) return;
  $("search_more").disabled = true;
  try {
    const body = {
      q: $("q").value.trim(),
      continuation: searchToken,
    };
    const uploaded = $("uploaded").value;
    if (uploaded) body.uploaded = uploaded;
    const data = await jsonPost("/api/search", body);
    for (const v of data.videos || []) $("search_grid").appendChild(videoCard(v));
    searchToken = data.continuation || null;
    $("search_more").hidden = !searchToken;
  } catch (err) {
    fail(err.message);
  } finally {
    $("search_more").disabled = false;
  }
}

async function openWatch(id) {
  if (!id || id.length !== 11) return;
  currentVideo = id;
  show("watch");
  fail("");
  setUrl("watch", { v: id });
  $("player").src = `https://www.youtube.com/embed/${id}?rel=0&modestbranding=1&autoplay=1&playsinline=1`;
  $("watch_on_yt").href = `https://www.youtube.com/watch?v=${id}`;
  $("watch_title").textContent = "…";
  $("watch_channel").textContent = "";
  $("watch_subs").textContent = "";
  $("watch_avatar").textContent = "";
  $("watch_stats").innerHTML = "";
  $("watch_desc").hidden = true;
  $("watch_desc").classList.remove("open");
  $("related").innerHTML = "";
  $("related_more").hidden = true;
  try {
    const data = await api(`/api/watch/${encodeURIComponent(id)}`);
    await jsonPost("/api/history", { video_id: id }).catch(() => {});
    const v = data.video || {};
    $("watch_title").textContent = v.title || id;
    document.title = `${v.title || "Watch"} · yt-desk`;
    $("watch_channel").textContent = v.channel || "";
    $("watch_subs").textContent = v.subscribers != null ? `${compact(v.subscribers)} subscribers` : "";
    $("watch_avatar").textContent = (v.channel || "?").trim().charAt(0).toUpperCase();
    renderStats(v);
    const desc = (v.description || "").trim();
    const box = $("watch_desc");
    if (desc) {
      box.hidden = false;
      box.textContent = desc;
    }
    const related = data.related || [];
    if (!related.length) $("related").appendChild(emptyBox("No related videos for this exit."));
    for (const r of related) $("related").appendChild(railItem(r));
    relatedToken = data.continuation || null;
    $("related_more").hidden = !relatedToken;
  } catch (err) {
    fail(err.message);
  }
}

async function moreRelated() {
  if (!relatedToken || !currentVideo) return;
  $("related_more").disabled = true;
  try {
    const data = await jsonPost(`/api/watch/${encodeURIComponent(currentVideo)}`, {
      continuation: relatedToken,
    });
    for (const r of data.related || []) $("related").appendChild(railItem(r));
    relatedToken = data.continuation || null;
    $("related_more").hidden = !relatedToken;
  } catch (err) {
    fail(err.message);
  } finally {
    $("related_more").disabled = false;
  }
}

async function suggest() {
  const q = $("q").value.trim();
  if (q.length < 2) {
    $("suggest").hidden = true;
    return;
  }
  const n = ++suggestSeq;
  try {
    const data = await api(`/api/suggest?q=${encodeURIComponent(q)}`);
    if (n !== suggestSeq) return;
    const box = $("suggest");
    box.innerHTML = "";
    suggestOn = -1;
    for (const s of data.suggestions || []) {
      const li = document.createElement("li");
      li.textContent = s;
      li.addEventListener("mousedown", (e) => {
        e.preventDefault();
        $("q").value = s;
        box.hidden = true;
        runSearch().catch((err) => fail(err.message));
      });
      box.appendChild(li);
    }
    box.hidden = !box.children.length;
  } catch {
    if (n === suggestSeq) $("suggest").hidden = true;
  }
}

$("q").addEventListener("input", () => {
  clearTimeout(suggestTimer);
  suggestTimer = setTimeout(suggest, 220);
});

$("q").addEventListener("keydown", (e) => {
  const items = [...$("suggest").querySelectorAll("li")];
  if (e.key === "Escape") {
    $("suggest").hidden = true;
    return;
  }
  if (!$("suggest").hidden && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
    e.preventDefault();
    if (!items.length) return;
    if (e.key === "ArrowDown") suggestOn = (suggestOn + 1) % items.length;
    else suggestOn = (suggestOn - 1 + items.length) % items.length;
    items.forEach((li, i) => li.classList.toggle("on", i === suggestOn));
    $("q").value = items[suggestOn].textContent;
  }
});

document.addEventListener("click", (e) => {
  if (!$("search_form").contains(e.target)) $("suggest").hidden = true;
});

$("search_form").addEventListener("submit", (e) => {
  e.preventDefault();
  $("suggest").hidden = true;
  runSearch().catch((err) => fail(err.message));
});

$("uploaded").addEventListener("change", () => {
  if (!$("view_search").hidden) runSearch().catch((err) => fail(err.message));
});

$("go_home").addEventListener("click", () => loadHome().catch((err) => fail(err.message)));
$("home_more").addEventListener("click", () => moreHome().catch((err) => fail(err.message)));
$("search_more").addEventListener("click", () => moreSearch().catch((err) => fail(err.message)));
$("related_more").addEventListener("click", () => moreRelated().catch((err) => fail(err.message)));
$("watch_desc").addEventListener("click", () => $("watch_desc").classList.toggle("open"));

$("country").addEventListener("change", async () => {
  try {
    await jsonPost("/api/session", { gl: $("country").value });
    if (!$("view_watch").hidden && currentVideo) await openWatch(currentVideo);
    else if (!$("view_search").hidden) await runSearch();
    else await loadHome();
  } catch (err) {
    fail(err.message);
  }
});

window.addEventListener("popstate", () => {
  skipHist = true;
  const p = new URLSearchParams(location.search);
  const run = p.get("v")
    ? openWatch(p.get("v"))
    : p.get("q")
      ? (($("q").value = p.get("q")), runSearch())
      : loadHome();
  Promise.resolve(run).catch((err) => fail(err.message)).finally(() => {
    skipHist = false;
  });
});

let vpnBusy = false;
let vpnChecking = false;
let vpnMeasured = { key: "", exit_ip: "", observed: null };

function vpnKey(state) {
  const t = state.tunnel || {};
  return [state.on, t.up, t.ip, t.interface, t.region].join("|");
}

function vpnRender(state, { checking = false } = {}) {
  const tun = state.tunnel || {};
  const btn = $("vpn_toggle");
  btn.disabled = vpnBusy;
  btn.classList.toggle("on", !!state.on);
  btn.textContent = vpnBusy ? "…" : state.on ? "VPN on" : "VPN off";

  let tone = "";
  const seen = (state.observed || {}).country;
  const want = $("country").value;
  let label = "direct";
  if (!state.on && tun.whole_machine) {
    tone = "warn";
    label = "PIA still routing";
  } else if (!state.on) {
    label = "this machine";
  } else if (!tun.up) {
    tone = "bad";
    label = "tunnel down";
  } else if (checking) {
    tone = "warn";
    label = "checking";
  } else if (seen) {
    label = `YouTube ${seen}`;
    tone = want && seen !== want ? "warn" : "ok";
  } else {
    tone = "warn";
    label = tun.region || "routed";
  }
  $("vpn_dot").className = "vpn-dot" + (tone ? " " + tone : "");
  $("vpn_text").innerHTML = `<b>${escapeHtml(label)}</b>`;
  $("vpn_info").title = [
    state.exit_ip || tun.ip,
    tun.region,
    seen ? `YouTube ${seen}` : "",
  ].filter(Boolean).join(" · ") || "Re-check the exit";
  const hint = $("player_hint");
  if (hint) {
    if (tun.whole_machine) {
      hint.hidden = false;
      hint.textContent = "The player is on the VPN too, so YouTube may ask you to sign in. Split PIA (All Other Apps → Bypass VPN), or sign in on youtube.com in this browser, or use Watch on YouTube.";
    } else {
      hint.hidden = true;
    }
  }

  const warn = $("vpn_warn");
  warn.hidden = !tun.whole_machine;
  warn.textContent = tun.whole_machine
    ? "PIA is tunnelling the whole machine. Split it if you want git and the browser on the home IP."
    : "";

  const geo = $("geo");
  if (state.on && seen && want && seen !== want) {
    geo.hidden = false;
    geo.classList.add("mismatch");
    geo.textContent = `YouTube is serving ${seen}, not ${want}. Pick a matching PIA region, or search anyway.`;
  } else {
    geo.hidden = true;
    geo.classList.remove("mismatch");
    geo.textContent = "";
  }
}

async function vpnRefresh({ check = false } = {}) {
  try {
    let state = await (await fetch("/api/proxy")).json();
    const key = vpnKey(state);
    const stale = state.on && (state.tunnel || {}).up && key !== vpnMeasured.key;
    if (check || stale) {
      vpnChecking = true;
      vpnRender(state, { checking: true });
      state = await (await fetch("/api/proxy?check=true")).json();
      vpnMeasured = {
        key: vpnKey(state),
        exit_ip: state.exit_ip || "",
        observed: state.observed || null,
      };
      vpnChecking = false;
    } else if (key === vpnMeasured.key) {
      state.exit_ip = vpnMeasured.exit_ip;
      state.observed = vpnMeasured.observed;
    }
    vpnRender(state);
    return state;
  } catch {
    vpnChecking = false;
    $("vpn_dot").className = "vpn-dot bad";
    $("vpn_text").textContent = "offline";
    return null;
  }
}

async function vpnToggle() {
  if (vpnBusy) return;
  const now = await (await fetch("/api/proxy")).json();
  vpnBusy = true;
  vpnRender(now);
  let result;
  try {
    result = await jsonPost(now.on ? "/api/proxy/stop" : "/api/proxy/start", {});
  } catch {
    result = { ok: false, error: "request failed" };
  }
  vpnBusy = false;
  if (!result.ok) {
    vpnRender(result.status || now);
    $("vpn_dot").className = "vpn-dot bad";
    $("vpn_text").textContent = result.error || "could not switch";
    return;
  }
  vpnMeasured = { key: "", exit_ip: "", observed: null };
  await vpnRefresh({ check: !now.on });
}

$("vpn_toggle").addEventListener("click", vpnToggle);
$("vpn_info").addEventListener("click", () => vpnRefresh({ check: true }));

async function boot() {
  await loadCountries();
  vpnRefresh({ check: true });
  setInterval(() => {
    if (!vpnBusy && !vpnChecking) vpnRefresh();
  }, 15000);
  skipHist = true;
  const params = new URLSearchParams(location.search);
  try {
    if (params.get("v")) await openWatch(params.get("v"));
    else if (params.get("q")) {
      $("q").value = params.get("q");
      await runSearch();
    } else {
      await loadHome();
    }
  } finally {
    skipHist = false;
  }
}

boot().catch((err) => fail(err.message));
