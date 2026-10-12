/* SnapKaki front end.
 *
 * Deliberately one file, no framework, no build step. The demo-critical path
 * is camera -> backend on a real phone browser, and every build tool between
 * those two is a way for that to break at the wrong moment.
 *
 * Two pieces of real engineering here: downscale(), because a phone camera
 * produces 4-8MB per shot and that is the difference between a usable answer
 * and a dead demo; and prefs, which remembers the few things it is rude to
 * ask an elderly user twice.
 */

const $ = (id) => document.getElementById(id);

const state = {
  sessionId: null,
  language: "en",
  fields: [],
  completed: [],
  current: null,     // key of the field the current step is about
  lastStop: null,    // { reason, key } for the family hand-off
  canSpeak: true,    // does this language have a voice at all
};

/* --- preferences -------------------------------------------------------- */

/* Three things worth remembering between visits: the language, where you got
 * to, and whether you want plainer explanations. None of them is personal
 * data and none is a form value, so the privacy claim is untouched.
 *
 * Every access is wrapped: localStorage throws in a private window, in an
 * iframe with blocked storage, and during thumbnail capture. A preference is
 * a convenience, so it fails silently and the app behaves as a first visit. */
const PREFS = {
  read(key, fallback = null) {
    try { return localStorage.getItem(`snapkaki.${key}`) ?? fallback; }
    catch { return fallback; }
  },
  write(key, value) {
    try { localStorage.setItem(`snapkaki.${key}`, value); } catch { /* ignore */ }
  },
  clear(key) {
    try { localStorage.removeItem(`snapkaki.${key}`); } catch { /* ignore */ }
  },
};

const wantsSimple = () => $("simple-mode").checked;

/* --- plumbing ----------------------------------------------------------- */

function toast(message, ms = 2600) {
  const el = $("toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, ms);
}

/* Reading a dense form page takes Gemini around ten seconds, measured. That
 * is too long for a bare spinner: silence past about three seconds reads as
 * broken. The message escalates while we wait — nothing untrue, it just
 * keeps admitting we are still here. */
let busyTimers = [];

function busy(on, text = "Thinking…", followUps = []) {
  busyTimers.forEach(clearTimeout);
  busyTimers = [];
  $("busy-text").textContent = text;
  $("busy").hidden = !on;
  if (!on) return;
  followUps.forEach(([afterMs, message]) => {
    busyTimers.push(setTimeout(() => { $("busy-text").textContent = message; }, afterMs));
  });
}

async function post(path, formData) {
  const response = await fetch(path, { method: "POST", body: formData });
  if (!response.ok) {
    let detail = `${response.status}`;
    try {
      const body = await response.json();
      if (body.detail) detail = body.detail;
    } catch { /* non-JSON error body; the status is all we have */ }
    const err = new Error(detail);
    err.status = response.status;
    throw err;
  }
  return response.json();
}

async function turn(fields) {
  const body = new FormData();
  body.append("session_id", state.sessionId);
  for (const [k, v] of Object.entries(fields)) {
    if (v !== null && v !== undefined) body.append(k, v);
  }
  return post("/turn", body);
}

/* --- image downscale ----------------------------------------------------- */

const MAX_EDGE = 1600;   // plenty for OCR of a printed form
const JPEG_Q = 0.82;

/* Falls back to the original file if anything in the canvas path fails — the
 * re-encode is an optimisation, and a browser quirk in it must not cost us
 * the scan entirely. */
async function downscale(file) {
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_EDGE / Math.max(bitmap.width, bitmap.height));

    if (scale === 1 && file.size < 1_500_000) {
      bitmap.close?.();
      return file;
    }

    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    bitmap.close?.();

    const blob = await new Promise((r) => canvas.toBlob(r, "image/jpeg", JPEG_Q));
    if (!blob) return file;

    return blob.size < file.size
      ? new File([blob], "form.jpg", { type: "image/jpeg" })
      : file;
  } catch (err) {
    console.warn("downscale failed, sending original", err);
    return file;
  }
}

/* --- read aloud ----------------------------------------------------------- */

/* The challenge names Elderlies under Information Accessibility, and until
 * this existed our answer to someone who struggles to read was more reading.
 *
 * Cloud TTS first, because it is consistent across devices and covers
 * Mandarin, Malay and Tamil properly. The browser's own speechSynthesis is
 * the fallback: it is free and instant but its voices vary wildly by device,
 * and on some Android builds there is no Chinese voice at all. Hokkien has
 * no voice anywhere, so the button is simply hidden for it. */
let audio = null;

function stopSpeaking() {
  if (audio) { audio.pause(); audio = null; }
  try { window.speechSynthesis?.cancel(); } catch { /* not everywhere */ }
  const btn = $("speak");
  btn.classList.remove("playing");
  btn.disabled = false;
  $("speak-label").textContent = "Read aloud";
}

function spokenText() {
  // What is on the card, in reading order: the step, then the detail.
  return [$("card-step").textContent, $("card-why").hidden ? "" : $("card-why").textContent]
    .filter(Boolean).join(". ");
}

async function speak() {
  if (audio) { stopSpeaking(); return; }

  const text = spokenText();
  if (!text) return;

  const btn = $("speak");
  btn.disabled = true;
  $("speak-label").textContent = "Loading…";

  try {
    const body = new FormData();
    body.append("session_id", state.sessionId);
    body.append("text", text);
    const response = await fetch("/speak", { method: "POST", body });

    // 204 = this language has no voice. Hide the button rather than
    // pretend; a Mandarin reader on romanised Hokkien is worse than silence.
    if (response.status === 204) {
      state.canSpeak = false;
      btn.hidden = true;
      toast("No voice available for this language yet.", 3200);
      return;
    }
    if (!response.ok) throw new Error(String(response.status));

    const blob = await response.blob();
    audio = new Audio(URL.createObjectURL(blob));
    audio.onended = stopSpeaking;
    audio.onerror = stopSpeaking;
    btn.classList.add("playing");
    $("speak-label").textContent = "Stop";
    await audio.play();
  } catch (err) {
    console.warn("cloud tts failed, trying the browser", err);
    if (!browserSpeak(text)) toast("Couldn't read that aloud.", 3200);
  } finally {
    btn.disabled = false;
    if (!audio) $("speak-label").textContent = "Read aloud";
  }
}

const BROWSER_LOCALES = { en: "en-US", zh: "zh-CN", ms: "ms-MY", ta: "ta-IN" };

function browserSpeak(text) {
  if (!window.speechSynthesis) return false;
  try {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = BROWSER_LOCALES[state.language] || "en-US";
    utterance.rate = 0.92;
    utterance.onend = stopSpeaking;
    $("speak").classList.add("playing");
    $("speak-label").textContent = "Stop";
    window.speechSynthesis.speak(utterance);
    return true;
  } catch {
    return false;
  }
}

/* --- asking a question ---------------------------------------------------- */

/* Dictation runs in the browser, not in the cloud, and that is a decision
 * rather than laziness. The alternative is recording audio and uploading it
 * to Cloud Speech-to-Text, which would be a little more accurate and would
 * mean a recording of the user's voice, taken while they sit over a form
 * covered in their own details, leaving the device. Web Speech keeps it on
 * the phone, which is the same promise the rest of the product makes.
 *
 * Support is good but not universal, so the button only appears where the
 * API exists and the text box always works. */
const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;

const SPEECH_LOCALES = { en: "en-SG", zh: "zh-CN", ms: "ms-MY", ta: "ta-IN",
                         hokkien: "zh-CN" };

let recogniser = null;

function listen() {
  if (!Recognition) return;
  const mic = $("mic");

  if (recogniser) { recogniser.stop(); return; }

  const r = new Recognition();
  r.lang = SPEECH_LOCALES[state.language] || "en-SG";
  r.interimResults = true;
  r.continuous = false;

  r.onresult = (event) => {
    const said = Array.from(event.results).map((x) => x[0].transcript).join("");
    $("ask-input").value = said;
  };
  r.onend = () => {
    recogniser = null;
    mic.classList.remove("listening");
    // Dictating a question and then having to press a second button is the
    // kind of step that loses the person this is for.
    if ($("ask-input").value.trim()) askQuestion();
  };
  r.onerror = () => {
    recogniser = null;
    mic.classList.remove("listening");
    toast("Didn't catch that. You can type it instead.", 3200);
  };

  recogniser = r;
  mic.classList.add("listening");
  try { r.start(); } catch { recogniser = null; mic.classList.remove("listening"); }
}

async function askQuestion() {
  const input = $("ask-input");
  const question = input.value.trim();
  if (!question || !state.current) return;

  input.blur();
  busy(true, "Looking it up…", [[5000, "Checking the guidance…"]]);
  try {
    const result = await turn({
      kind: "ask",
      field_key: state.current,
      question,
      simple: wantsSimple(),
    });
    input.value = "";
    apply(result);
  } catch (err) {
    toast(`Couldn't answer that: ${err.message}`, 4200);
  } finally {
    busy(false);
  }
}

/* --- rendering ----------------------------------------------------------- */

const KICKERS = {
  enter: "Next step", choose: "Choose one", check: "Check this",
  read: "Have a look", ask: "Worth asking", done: "All done",
};

const KIND_LABELS = {
  choice: "pick", checkbox: "tick", signature: "sign",
  number: "number", date: "date", text: "write",
};

function kickerFor(result) {
  if (result.kind === "unknown_form") return "Not a form I know";
  if (result.stopped) return "Let's pause here";
  if (result.kind === "explain") return "What this means";
  return KICKERS[result.action] || "";
}

function renderCard(result) {
  const card = $("card");
  card.classList.toggle("stopped", Boolean(result.stopped));

  const kicker = $("card-kicker");
  const text = kickerFor(result);
  kicker.textContent = text;
  kicker.hidden = !text;

  $("card-step").textContent = result.message || "";

  const why = $("card-why");
  why.textContent = result.detail || "";
  why.hidden = !result.detail;

  // The printed choices and the layout note for this field. Both come from
  // vision and were being discarded; they are exactly what someone staring
  // at "Rental Status of Residence" wants to see.
  const onform = $("onform");
  const note = $("onform-note");
  const opts = $("onform-options");
  const hasNote = Boolean(result.field_notes);
  const list = result.field_options || [];

  note.textContent = result.field_notes || "";
  note.hidden = !hasNote;

  opts.replaceChildren();
  for (const o of list) {
    const chip = document.createElement("span");
    chip.textContent = o;        // model-derived: never parsed as HTML
    opts.append(chip);
  }
  opts.hidden = list.length === 0;
  onform.hidden = !(hasNote || list.length);

  // Official source for a form we hold no guidance for. The href is only
  // ever a government domain - the backend drops anything else before it
  // reaches here (see agents/signpost.py) - but rel/target are set in the
  // markup regardless, because a link we did not write is still a link.
  const link = $("card-link");
  if (result.authority_url) {
    link.href = result.authority_url;
    link.textContent = "Open the official page";
    link.hidden = false;
  } else {
    link.removeAttribute("href");
    link.hidden = true;
  }

  // A new card means whatever was being read is now stale.
  stopSpeaking();
  $("speak").hidden = !(state.canSpeak && $("card-step").textContent.trim());

  const sources = $("card-sources");
  sources.replaceChildren();
  if (result.sources && result.sources.length) {
    const head = document.createElement("b");
    head.textContent = "Based on";
    sources.append(head);
    for (const s of result.sources) {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = s;           // model-derived text: never parsed as HTML
      sources.append(chip);
    }
    sources.hidden = false;
  } else {
    sources.hidden = true;
  }
}

function renderProgress() {
  const bar = $("progress");
  if (!state.fields.length) { bar.hidden = true; return; }

  const done = state.fields.filter(
    (f) => f.done || state.completed.includes(f.key)
  ).length;
  const total = state.fields.length;

  $("progress-count").textContent = `${done} of ${total}`;
  $("progress-fill").style.width = `${Math.round((done / total) * 100)}%`;
  $("progress-label").textContent = done === total ? "Form complete" : "Your progress";
  bar.hidden = false;
}

function renderActions(result) {
  const didIt = $("did-it");

  // "I've done this" must never appear on a gated step — that would be a
  // one-tap path past the thing we just stopped for.
  const actionable = !result.stopped && result.field_key &&
    ["enter", "choose", "check", "read"].includes(result.action);

  didIt.hidden = !actionable;
  if (actionable) didIt.textContent = `I've done ${shorten(result.field_label)}`;

  $("explain").hidden = !result.field_key;
  $("family").hidden = !result.offer_family_loop;

  // The ask row needs a field to ask ABOUT - it is scoped to the current
  // one, which is what keeps retrieval tight.
  const askable = Boolean(result.field_key);
  $("ask-form").hidden = !askable;
  if (askable) {
    // shorten() already appends an ellipsis when it truncates, so only add
    // one when it did not.
    const subject = shorten(result.field_label, 24);
    $("ask-input").placeholder =
      `Ask about ${subject}${subject.endsWith("…") ? "" : "…"}`;
  }
}

function shorten(label, max = 28) {
  if (!label) return "this";
  return label.length <= max ? label : `${label.slice(0, max - 1)}…`;
}

function renderFields() {
  const list = $("fields");
  list.replaceChildren();

  for (const field of state.fields) {
    const li = document.createElement("li");
    const done = field.done || state.completed.includes(field.key);
    const locked = field.kind === "signature";

    li.className = [
      done ? "done" : "",
      field.key === state.current ? "current" : "",
      locked ? "locked" : "",
    ].filter(Boolean).join(" ");

    // Built with DOM methods rather than innerHTML: field.label comes from a
    // model reading a photo, so it never goes near HTML parsing.
    const tick = document.createElement("span");
    tick.className = "tick";
    tick.setAttribute("aria-hidden", "true");
    tick.textContent = "✓";

    const label = document.createElement("span");
    label.className = "label";
    label.textContent = field.label;

    const button = document.createElement("button");
    button.type = "button";
    button.append(tick, label);

    const kindLabel = KIND_LABELS[field.kind];
    if (kindLabel) {
      const kind = document.createElement("span");
      kind.className = "kind";
      kind.textContent = kindLabel;
      button.append(kind);
    }

    button.setAttribute(
      "aria-label",
      `${field.label}${done ? ", done" : ""}. Explain this field.`
    );
    button.addEventListener("click", () => explainField(field.key));

    li.append(button);
    list.append(li);
  }
}

function apply(result) {
  if (result.fields && result.fields.length) state.fields = result.fields;
  if (result.completed) state.completed = result.completed;
  state.current = result.field_key || null;

  if (result.stopped) {
    state.lastStop = { reason: result.stop_reason, key: result.field_key };
  }

  $("start").hidden = true;
  $("work").hidden = false;

  renderCard(result);
  renderActions(result);
  renderProgress();
  renderFields();
}

/* --- actions ------------------------------------------------------------- */

async function ensureSession() {
  if (state.sessionId) return state.sessionId;
  const body = new FormData();
  body.append("language", $("language").value || state.language);
  const data = await post("/session", body);
  state.sessionId = data.session_id;
  state.language = data.language;
  if (typeof data.can_speak === "boolean") state.canSpeak = data.can_speak;
  PREFS.write("session", data.session_id);
  return state.sessionId;
}

async function scan(file) {
  if (!file) return;
  busy(true, "Reading the form…", [
    [3500, "Still reading — it's a dense page…"],
    [7500, "Almost there…"],
  ]);
  try {
    await ensureSession();
    const image = await downscale(file);
    const body = new FormData();
    body.append("session_id", state.sessionId);
    body.append("kind", "scan");
    body.append("image", image, image.name || "form.jpg");
    apply(await post("/turn", body));
  } catch (err) {
    toast(`Couldn't read that: ${err.message}`, 4200);
  } finally {
    busy(false);
  }
}

async function explainField(key) {
  busy(true, "Looking it up…", [[5000, "Checking the guidance…"]]);
  try {
    apply(await turn({ kind: "ask", field_key: key, simple: wantsSimple() }));
  } catch (err) {
    toast(`Couldn't explain that: ${err.message}`, 4200);
  } finally {
    busy(false);
  }
}

async function markDone(key) {
  busy(true, "Nice. What's next…");
  try {
    apply(await turn({ kind: "done", field_key: key }));
  } catch (err) {
    toast(`Something went wrong: ${err.message}`, 4200);
  } finally {
    busy(false);
  }
}

async function askFamily() {
  busy(true, "Writing the message…");
  try {
    const result = await turn({
      kind: "family",
      field_key: state.lastStop?.key || state.current || "",
      // The stop code, not the card text — the backend turns it into
      // something that reads naturally forwarded to another person.
      reason: state.lastStop?.reason || "",
    });
    $("family-subject").textContent = result.detail || "Message for your family";
    $("family-message").value = result.message || "";
    $("family-dialog").showModal();
  } catch (err) {
    toast(`Couldn't write the message: ${err.message}`, 4200);
  } finally {
    busy(false);
  }
}

async function copyMessage() {
  const text = $("family-message").value;
  try {
    await navigator.clipboard.writeText(text);
    toast("Copied. Paste it to your family.");
  } catch {
    // Clipboard API needs a secure context and a user gesture; selecting the
    // text is the reliable fallback on an older mobile browser.
    const box = $("family-message");
    box.removeAttribute("readonly");
    box.select();
    box.setAttribute("readonly", "");
    toast("Press and hold to copy.", 3400);
  }
}

/* Pick up an unfinished form from a previous visit.
 *
 * The person this is built for puts the phone down mid-form and comes back
 * later, and making them re-photograph everything is the kind of small
 * indignity that stops people using a thing. Server state already exists;
 * this is only the client half. */
async function resume() {
  const saved = PREFS.read("session");
  if (!saved) return false;

  state.sessionId = saved;
  try {
    const result = await turn({ kind: "next" });
    if (!result.fields || !result.fields.length) return false;
    apply(result);
    toast("Picked up where you left off.", 3200);
    return true;
  } catch (err) {
    // 404 means the session aged out. Anything else and we would rather
    // start clean than show a half-restored form.
    state.sessionId = null;
    PREFS.clear("session");
    return false;
  }
}

/* --- wiring -------------------------------------------------------------- */

function fillLanguages(languages) {
  const select = $("language");
  select.replaceChildren();
  for (const [code, name] of Object.entries(languages)) {
    const option = document.createElement("option");
    option.value = code;
    option.textContent = name;
    select.append(option);
  }
  select.value = state.language;
}

async function init() {
  // Hard-coded to match config.SUPPORTED_LANGUAGES so the picker is usable
  // before the first session call; /session returns the authoritative list.
  state.language = PREFS.read("lang", "en");
  fillLanguages({
    en: "English",
    zh: "Mandarin Chinese",
    ms: "Malay",
    ta: "Tamil",
    hokkien: "Hokkien",
  });

  $("simple-mode").checked = PREFS.read("simple") === "1";

  $("camera").addEventListener("change", (e) => scan(e.target.files[0]));
  $("camera-again").addEventListener("change", (e) => scan(e.target.files[0]));
  $("upload").addEventListener("change", (e) => scan(e.target.files[0]));
  $("pick-shot").addEventListener("click", () => $("upload").click());

  $("did-it").addEventListener("click", () => { if (state.current) markDone(state.current); });
  $("explain").addEventListener("click", () => { if (state.current) explainField(state.current); });
  $("family").addEventListener("click", askFamily);
  $("speak").addEventListener("click", speak);
  $("mic").hidden = !Recognition;
  $("mic").addEventListener("click", listen);
  $("ask-form").addEventListener("submit", (e) => { e.preventDefault(); askQuestion(); });

  $("copy-message").addEventListener("click", copyMessage);
  $("close-family").addEventListener("click", () => $("family-dialog").close());

  $("simple-mode").addEventListener("change", (e) => {
    PREFS.write("simple", e.target.checked ? "1" : "0");
    // Re-ask the current field straight away, so the setting visibly does
    // something rather than silently applying to the next question.
    if (state.current) explainField(state.current);
  });

  $("language").addEventListener("change", (e) => {
    state.language = e.target.value;
    state.canSpeak = e.target.value !== "hokkien";
    PREFS.write("lang", e.target.value);
    // A language change starts a fresh session rather than mutating one
    // mid-flow, so the event trail and the answers stay in one language.
    state.sessionId = null;
    PREFS.clear("session");
    toast("Language set. Take a photo to start.");
  });

  await resume();
}

init();
