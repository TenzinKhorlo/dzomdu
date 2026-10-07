// Dzomdu web UI. Plain ES modules, no build step, no network access beyond this server.

const $ = (sel) => document.querySelector(sel);
const POLL_STATES = new Set(["new", "recording", "processing", "summarizing"]);

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "dataset") Object.assign(el.dataset, v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c !== null && c !== undefined && c !== false) el.append(c instanceof Node ? c : String(c));
  }
  return el;
}

async function request(method, path, body) {
  const opts = { method, headers: {} };
  if (body instanceof FormData) opts.body = body;
  else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : null;
  if (!res.ok) {
    const err = new Error(data?.detail || `${res.status} ${res.statusText}`);
    err.status = res.status;
    throw err;
  }
  return data;
}
const api = {
  get: (p) => request("GET", p),
  post: (p, b) => request("POST", p, b ?? {}),
  del: (p) => request("DELETE", p),
};

let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove("show"), 4500);
}

function fmtClock(sec) {
  sec = Math.max(0, Math.round(sec));
  const h_ = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  const mm = String(m).padStart(2, "0"), ss = String(s).padStart(2, "0");
  return h_ ? `${h_}:${mm}:${ss}` : `${mm}:${ss}`;
}
function fmtDuration(sec) {
  if (sec == null) return "";
  if (sec < 60) return `${Math.round(sec)}s`;
  const m = Math.round(sec / 60);
  return m < 60 ? `${m} min` : `${Math.floor(m / 60)}h ${String(m % 60).padStart(2, "0")}m`;
}
function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) +
    " " + d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

// stable colour per speaker label
const colourOf = new Map();
function colour(label) {
  if (!label) return null;
  if (!colourOf.has(label)) colourOf.set(label, colourOf.size % 8);
  return String(colourOf.get(label));
}

function show(view) {
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${view}`));
  const nav = view === "meetings" || view === "voices" ? view : view === "new" ? "new" : null;
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === nav));
}

// -- app info (templates, people, projects, model status) ----------------------------------

let info = null;
async function loadInfo() {
  try {
    info = await api.get("/api/info");
  } catch (e) {
    toast(`Cannot reach the Dzomdu server: ${e.message}`);
    return;
  }
  $("#people-list").replaceChildren(...info.people.map((p) => h("option", { value: p })));
  $("#projects-list").replaceChildren(...info.projects.map((p) => h("option", { value: p })));
  for (const sel of document.querySelectorAll(".template-select")) {
    const current = sel.value || info.default_template;
    sel.replaceChildren(...info.templates.map((t) =>
      h("option", { value: t.key, title: t.description, selected: t.key === current }, t.name)));
  }
  const st = info.status;
  const problems = [];
  if (!st.asr.ok) problems.push(`Speech-to-text (${info.models.asr}) is not installed`);
  if (!st.diarization.ok) problems.push("Speaker separation (pyannote) is not installed");
  if (!st.llm.ok) problems.push(`LLM: ${st.llm.detail}`);
  const btn = $("#status");
  btn.classList.toggle("ok", problems.length === 0);
  btn.classList.toggle("warn", problems.length > 0);
  $("#status-text").textContent = problems.length ? `${problems.length} issue${problems.length > 1 ? "s" : ""}` : "Ready";
  btn.title = problems.length ? problems.join("\n") :
    `Speech: ${info.models.asr} · LLM: ${info.models.llm}`;
  btn.onclick = () => toast(btn.title);
  if (info.recovered.length) toast(`Recovered ${info.recovered.length} interrupted recording(s) to ${info.recovered[0].replace(/[^/]+$/, "")}`);
}

// -- new meeting form ------------------------------------------------------------------------

const attendees = [];
function renderChips() {
  const box = $("#attendees");
  box.querySelectorAll(".chip").forEach((c) => c.remove());
  const input = $("#attendee-input");
  attendees.forEach((name, i) => {
    box.insertBefore(h("span", { class: "chip" }, name,
      h("button", { type: "button", "aria-label": `Remove ${name}`, onclick: () => { attendees.splice(i, 1); renderChips(); } }, "×")), input);
  });
}
function addAttendee(raw) {
  const name = raw.trim().replace(/,$/, "").trim();
  if (name && !attendees.some((a) => a.toLowerCase() === name.toLowerCase())) attendees.push(name);
  renderChips();
}
$("#attendee-input").addEventListener("keydown", (e) => {
  const input = e.target;
  if ((e.key === "Enter" || e.key === ",") && input.value.trim()) {
    e.preventDefault();
    addAttendee(input.value);
    input.value = "";
  } else if (e.key === "Backspace" && !input.value && attendees.length) {
    attendees.pop();
    renderChips();
  } else if (e.key === "Enter") e.preventDefault();
});
$("#attendee-input").addEventListener("change", (e) => {
  // picking from the datalist fires change without a key press
  if (info?.people.includes(e.target.value)) { addAttendee(e.target.value); e.target.value = ""; }
});
$("#meeting-form").addEventListener("submit", (e) => e.preventDefault());

function meetingMeta() {
  const f = $("#meeting-form");
  const pending = $("#attendee-input").value.trim();
  if (pending) { addAttendee(pending); $("#attendee-input").value = ""; }
  return {
    title: f.title.value, project: f.project.value, attendees: [...attendees],
    template: f.template.value, num_speakers: f.num_speakers.value || null,
    live: f.live.checked, summarize: f.summarize.checked, instructions: f.instructions.value,
  };
}

// -- recorder ---------------------------------------------------------------------------------

const recorder = {
  id: null, ws: null, ctx: null, stream: null, node: null, level: 0, raf: null, startedAt: 0,

  async start(sessionId) {
    if (!navigator.mediaDevices?.getUserMedia) {
      throw new Error("This browser cannot record audio here. Open Dzomdu at http://localhost.");
    }
    this.stream = await navigator.mediaDevices.getUserMedia({
      // room recording: no call-style processing that suppresses distant voices
      audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: true },
    });
    this.ctx = new AudioContext();
    await this.ctx.audioWorklet.addModule("/static/recorder-worklet.js");
    const source = this.ctx.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.ctx, "pcm-recorder", { processorOptions: { targetRate: 16000 } });
    const mute = this.ctx.createGain();
    mute.gain.value = 0;
    source.connect(this.node).connect(mute).connect(this.ctx.destination);

    const proto = location.protocol === "https:" ? "wss" : "ws";
    this.ws = new WebSocket(`${proto}://${location.host}/api/sessions/${sessionId}/audio`);
    this.ws.binaryType = "arraybuffer";
    const queue = [];
    this.ws.onopen = () => { queue.splice(0).forEach((b) => this.ws.send(b)); };
    this.ws.onclose = (e) => {
      if (this.id && e.code !== 1000 && e.code !== 1005) toast(`Recording connection closed: ${e.reason || e.code}`);
    };
    this.node.port.onmessage = ({ data }) => {
      this.level = data.rms;
      if (this.ws.readyState === WebSocket.OPEN) this.ws.send(data.pcm);
      else if (this.ws.readyState === WebSocket.CONNECTING) queue.push(data.pcm);
    };
    this.id = sessionId;
    this.startedAt = performance.now();
    this.tick();
  },

  tick() {
    const pct = Math.min(100, Math.sqrt(this.level) * 180);
    $("#meter-fill").style.width = `${pct}%`;
    $("#rec-time").textContent = fmtClock((performance.now() - this.startedAt) / 1000);
    this.raf = requestAnimationFrame(() => this.tick());
  },

  async stop() {
    if (!this.id) return;
    this.node?.port.postMessage("flush");
    await new Promise((r) => setTimeout(r, 150)); // let the last chunk arrive
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send("stop");
    this.release();
  },

  release() {
    cancelAnimationFrame(this.raf);
    this.stream?.getTracks().forEach((t) => t.stop());
    this.ctx?.close();
    this.id = null;
    setTimeout(() => this.ws?.close(), 500);
  },
};

window.addEventListener("beforeunload", (e) => {
  if (recorder.id) { e.preventDefault(); e.returnValue = ""; }
});

$("#start-btn").addEventListener("click", async () => {
  const btn = $("#start-btn");
  btn.disabled = true;
  try {
    const meta = meetingMeta();
    const { id } = await api.post("/api/sessions", meta);
    try {
      await recorder.start(id);
    } catch (e) {
      await api.post(`/api/sessions/${id}/cancel`).catch(() => {});
      throw e.name === "NotAllowedError" ? new Error("Microphone permission was denied.") : e;
    }
    $("#rec-title").textContent = meta.title || "Recording";
    location.hash = `#/session/${id}`;
  } catch (e) {
    toast(e.message);
  } finally {
    btn.disabled = false;
  }
});

$("#stop-btn").addEventListener("click", async () => {
  $("#stop-btn").disabled = true;
  await recorder.stop();
  $("#stop-btn").disabled = false;
  poll(true);
});

$("#discard-btn").addEventListener("click", async () => {
  if (!confirm("Discard this recording? The audio will be deleted.")) return;
  const id = recorder.id || session.id;
  await api.post(`/api/sessions/${id}/cancel`).catch(() => {});
  recorder.release();
  location.hash = "#/";
});

$("#upload-input").addEventListener("change", async (e) => {
  const file = e.target.files[0];
  e.target.value = "";
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  form.append("meta", JSON.stringify(meetingMeta()));
  toast(`Uploading ${file.name}…`);
  try {
    const { id } = await api.post("/api/upload", form);
    location.hash = `#/session/${id}`;
  } catch (err) {
    toast(err.message);
  }
});

// -- session view -----------------------------------------------------------------------------

const session = { id: null, liveSince: 0, timer: null, state: null, lastLive: null };

function openSession(id) {
  clearTimeout(session.timer);
  if (session.id !== id) {
    Object.assign(session, { id, liveSince: 0, state: null, lastLive: null });
    $("#live").replaceChildren(h("p", { class: "empty" }, "Listening… the transcript appears after the first pause."));
  }
  poll(true);
}

async function poll(force = false) {
  clearTimeout(session.timer);
  const id = session.id;
  if (!id || !location.hash.startsWith("#/session/")) return;
  let s;
  try {
    s = await api.get(`/api/sessions/${id}?live_since=${session.liveSince}`);
  } catch (e) {
    if (e.status === 404) {
      showError("This session no longer exists (the server was restarted). Find finished meetings under Meetings.");
      return;
    }
    session.timer = setTimeout(poll, 2000);
    return;
  }
  if (id !== session.id) return;
  const changed = s.state !== session.state;
  session.state = s.state;
  render(s, changed || force);
  if (POLL_STATES.has(s.state)) session.timer = setTimeout(poll, s.state === "recording" ? 800 : 1200);
}

function render(s, changed) {
  switch (s.state) {
    case "new":
    case "recording":
      show("recording");
      if (!recorder.id) $("#rec-time").textContent = fmtClock(s.elapsed);
      $("#rec-title").textContent = s.meta.title || "Recording";
      setBanner("#rec-warning", s.warning);
      appendLive(s.live);
      break;
    case "processing":
    case "summarizing":
      show("processing");
      $("#proc-title").textContent = s.state === "processing" ? "Processing the recording" : "Writing the notes";
      $("#proc-hint").textContent = s.state === "processing"
        ? "Separating speakers and transcribing. A one-hour meeting takes a few minutes."
        : `The local LLM (${info?.models.llm ?? "LLM"}) is writing the summary and minutes.`;
      $("#proc-log").replaceChildren(...s.messages.map((m) => h("li", {}, m)));
      break;
    case "review":
      if (changed) renderReview(s);
      show("review");
      break;
    case "done":
      if (changed) renderNotes(s);
      show("notes");
      break;
    case "error":
      showError(s.error);
      break;
    case "cancelled":
      location.hash = "#/";
      break;
  }
}

function setBanner(sel, text) {
  const el = $(sel);
  el.hidden = !text;
  el.textContent = text || "";
}

function appendLive(segments) {
  if (!segments.length) return;
  const box = $("#live");
  box.querySelector(".empty")?.remove();
  const atBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 60;
  for (const seg of segments) {
    session.liveSince = Math.max(session.liveSince, seg.id);
    const label = seg.speaker || "…";
    const last = session.lastLive;
    if (last && last.label === label && seg.speaker) {
      last.p.textContent += " " + seg.text;
      continue;
    }
    const p = h("p", { class: "said" }, seg.text);
    box.append(h("div", { class: "turn" },
      h("div", { class: "who", dataset: { c: colour(seg.speaker) ?? "" } }, label, h("time", {}, fmtClock(seg.start))),
      p));
    session.lastLive = { label, p };
  }
  if (atBottom) box.scrollTop = box.scrollHeight;
}

function showError(text) {
  $("#error-text").textContent = text || "Unknown error";
  show("error");
}

// -- review ----------------------------------------------------------------------------------

let audioEl = null;
function renderReview(s) {
  const cards = s.speakers.map((sp, i) => {
    const badge = sp.status === "auto"
      ? h("span", { class: "badge auto" }, `Recognised · ${sp.score.toFixed(2)}`)
      : sp.status === "suggested"
        ? h("span", { class: "badge suggested" }, `Might be ${sp.suggestion} · ${sp.score.toFixed(2)}`)
        : h("span", { class: "badge" }, "New voice");
    const input = h("input", {
      list: "people-list", value: sp.name || sp.suggestion || "", dataset: { cluster: sp.cluster },
      placeholder: `Name — or leave empty for “${sp.unknown_label}”`, "aria-label": `Name of speaker ${i + 1}`,
    });
    const play = h("button", {
      class: "btn btn-secondary play", type: "button", disabled: !sp.has_clip,
      onclick: () => {
        audioEl?.pause();
        audioEl = new Audio(`/api/sessions/${s.id}/clips/${encodeURIComponent(sp.cluster)}`);
        audioEl.play().catch((e) => toast(`Cannot play clip: ${e.message}`));
      },
    }, "▶ Play voice");
    return h("div", { class: "card speaker-card", dataset: { c: String(i % 8) } },
      h("div", { class: "speaker-top" },
        h("span", { class: "speaker-name" }, `Speaker ${i + 1}`), badge,
        h("span", { class: "meta" }, `${fmtDuration(sp.talk_seconds)} · ${sp.turns} turn${sp.turns === 1 ? "" : "s"}`)),
      ...sp.quotes.map((q) => h("p", { class: "quote" }, h("time", {}, fmtClock(q.start)), `“${q.text.length > 220 ? q.text.slice(0, 217) + "…" : q.text}”`)),
      h("div", { class: "name-row" }, input, play));
  });
  $("#speaker-cards").replaceChildren(...cards);
}

$("#review-submit").addEventListener("click", async () => {
  const names = {};
  document.querySelectorAll("#speaker-cards input[data-cluster]").forEach((inp) => {
    names[inp.dataset.cluster] = inp.value.trim() || null;
  });
  const btn = $("#review-submit");
  btn.disabled = true;
  try {
    audioEl?.pause();
    await api.post(`/api/sessions/${session.id}/review`, { names });
    poll(true);
  } catch (e) {
    toast(e.message);
  } finally {
    btn.disabled = false;
  }
});

// -- notes -----------------------------------------------------------------------------------

let noteMarkdown = "";
async function renderNotes(s) {
  setBanner("#notes-warning", s.warning);
  $("#notes-title").textContent = s.title || "Meeting notes";
  $("#regen-template").value = s.meta.template || info?.default_template || "standard";
  try {
    const note = await api.get(`/api/sessions/${s.id}/note`);
    noteMarkdown = note.markdown;
    $("#note").innerHTML = note.html; // rendered server-side with raw HTML disabled
    const rel = info && note.path.startsWith(info.vault) ? note.path.slice(info.vault.length + 1) : note.path;
    $("#notes-path").textContent = `Saved in your vault: ${rel}`;
    $("#notes-path").title = note.path;
    $("#obsidian-link").href = note.obsidian_url;
  } catch (e) {
    $("#note").replaceChildren(h("p", { class: "empty" }, e.message));
  }
}

$("#note").addEventListener("click", (e) => {
  const a = e.target.closest('a[href^="#t"]');
  if (!a) return;
  e.preventDefault(); // keep the router's hash intact
  const target = document.getElementById(a.getAttribute("href").slice(1));
  if (target) {
    target.scrollIntoView({ behavior: "smooth", block: "center" });
    target.classList.add("flash");
    setTimeout(() => target.classList.remove("flash"), 1600);
  }
});

$("#copy-md").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(noteMarkdown);
    toast("Markdown copied");
  } catch {
    toast("Copy failed; open the file instead");
  }
});

$("#regen-btn").addEventListener("click", async () => {
  const body = { template: $("#regen-template").value, instructions: $("#regen-instructions").value };
  try {
    await api.post(`/api/sessions/${session.id}/regenerate`, body);
  } catch (e) {
    if (e.status === 409 && e.message.startsWith("edited:")) {
      if (!confirm("This note was edited after it was generated (e.g. in Obsidian). Replace it and lose those edits?")) return;
      await api.post(`/api/sessions/${session.id}/regenerate`, { ...body, force: true });
    } else {
      toast(e.message);
      return;
    }
  }
  $("#regen-instructions").value = "";
  poll(true);
});

// -- meetings & voices ------------------------------------------------------------------------

async function loadMeetings() {
  show("meetings");
  let data;
  try {
    data = await api.get("/api/meetings");
  } catch (e) {
    toast(e.message);
    return;
  }
  $("#active-list").replaceChildren(...data.active.map((a) =>
    h("a", { href: `#/session/${a.id}` }, `● ${a.title} — ${a.state}`)));
  $("#meetings-empty").hidden = data.meetings.length > 0;
  $("#meetings-table").parentElement.hidden = data.meetings.length === 0;
  const rows = data.meetings.map((m) => h("tr", {
    class: "clickable", tabindex: "0",
    onclick: () => openMeeting(m.id),
    onkeydown: (e) => { if (e.key === "Enter") openMeeting(m.id); },
  },
  h("td", { class: "num" }, fmtDate(m.date)),
  h("td", {}, h("strong", {}, m.title)),
  h("td", {}, m.project || ""),
  h("td", {}, m.people.join(", ")),
  h("td", { class: "num" }, fmtDuration(m.duration))));
  $("#meetings-table").replaceChildren(
    h("thead", {}, h("tr", {}, ...["Date", "Title", "Project", "People", "Length"].map((t) => h("th", {}, t)))),
    h("tbody", {}, ...rows));
}

async function openMeeting(meetingId) {
  try {
    const { id } = await api.post(`/api/meetings/${encodeURIComponent(meetingId)}/open`);
    location.hash = `#/session/${id}`;
  } catch (e) {
    toast(e.message);
  }
}

async function loadVoices() {
  show("voices");
  let voices;
  try {
    voices = await api.get("/api/speakers");
  } catch (e) {
    toast(e.message);
    return;
  }
  $("#voices-empty").hidden = voices.length > 0;
  $("#voices-table").parentElement.hidden = voices.length === 0;
  const rows = voices.map((v) => h("tr", {},
    h("td", {}, h("strong", {}, v.name)),
    h("td", { class: "num" }, `${v.samples} sample${v.samples === 1 ? "" : "s"}`),
    h("td", { class: "num" }, v.consent ? "Consent given" : "—"),
    h("td", { style: "text-align:right" },
      h("button", { class: "btn btn-secondary", type: "button", onclick: () => renameVoice(v.name) }, "Rename"), " ",
      h("button", { class: "btn btn-secondary", type: "button", onclick: () => forgetVoice(v.name) }, "Forget"))));
  $("#voices-table").replaceChildren(
    h("thead", {}, h("tr", {}, ...["Name", "Voiceprint", "Consent", ""].map((t) => h("th", {}, t)))),
    h("tbody", {}, ...rows));
}

async function renameVoice(name) {
  const next = prompt(`Rename ${name} to:`, name);
  if (!next || next.trim() === name) return;
  try {
    await api.post("/api/speakers/rename", { old: name, new: next.trim() });
    loadVoices();
    loadInfo();
  } catch (e) {
    toast(e.message);
  }
}

async function forgetVoice(name) {
  if (!confirm(`Forget ${name}'s voice? Their voiceprints and clips are deleted; meeting notes and their profile are kept.`)) return;
  try {
    await api.del(`/api/speakers/${encodeURIComponent(name)}`);
    toast(`Forgot ${name}'s voice`);
    loadVoices();
  } catch (e) {
    toast(e.message);
  }
}

// -- routing ---------------------------------------------------------------------------------

function route() {
  const hash = location.hash || "#/";
  if (hash.startsWith("#/session/")) {
    openSession(decodeURIComponent(hash.slice("#/session/".length)));
    return;
  }
  clearTimeout(session.timer);
  if (hash === "#/meetings") loadMeetings();
  else if (hash === "#/voices") loadVoices();
  else {
    show("new");
    if (info) loadInfo(); // refresh people/projects added since
  }
}

window.addEventListener("hashchange", route);
loadInfo().then(route);
