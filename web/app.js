/* SnapKaki front end.
 *
 * Deliberately one file, no framework, no build step. The demo-critical path
 * is camera -> backend on a real phone browser, and every build tool between
 * those two is a way for that to break at the wrong moment.
 *
 * The one piece of real engineering here is downscale(): a modern phone
 * camera produces a 4-8MB JPEG, and uploading that over mobile data is the
 * difference between a 2-second answer and a dead demo.
 */

const $ = (id) => document.getElementById(id);

const state = {
  sessionId: null,
  language: "en",
  fields: [],
  completed: [],
  current: null,     // key of the field the current step is about
  lastStop: null,    // { reason, key } for the family hand-off
};

/* --- plumbing ----------------------------------------------------------- */

function toast(message, ms = 2600) {
  const el = $("toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, ms);
}

/* Reading a dense form page takes Gemini around ten seconds, measured. That
 * is too long to show a bare spinner: silence past about three seconds reads
 * as broken. So the message escalates while we wait — it says nothing untrue,
 * it just keeps admitting that we are still here. */
let busyTimers = [];

function busy(on, text = "Thinking…", followUps = []) {
  busyTimers.forEach(clearTimeout);
  busyTimers = [];
  $("busy-text").textContent = text;
  $("busy").hidden = !on;
  if (!on) return;
  followUps.forEach(([afterMs, message]) => {
    busyTimers.push(setTimeout(() => {
      $("busy-text").textContent = message;
    }, afterMs));
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
    throw new Error(detail);
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

/* Shrink a camera photo before upload.
 *
 * Falls back to the original file if anything in the canvas path fails —
 * an 1600px re-encode is an optimisation, and a browser quirk in it must
 * not cost us the scan entirely. */
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

    const blob = await new Promise((resolve) =>
      canvas.toBlob(resolve, "image/jpeg", JPEG_Q)
    );
    if (!blob) return file;

    // If the re-encode somehow grew the file, keep the original.
    return blob.size < file.size
      ? new File([blob], "form.jpg", { type: "image/jpeg" })
      : file;
  } catch (err) {
    console.warn("downscale failed, sending original", err);
    return file;
  }
}

/* --- rendering ----------------------------------------------------------- */

function renderCard(result) {
  const card = $("card");
  card.classList.toggle("stopped", Boolean(result.stopped));

  $("card-step").textContent = result.message || "";

  const why = $("card-why");
  why.textContent = result.detail || "";
  why.hidden = !result.detail;

  const sources = $("card-sources");
  if (result.sources && result.sources.length) {
    sources.textContent = `Based on: ${result.sources.join(" · ")}`;
    sources.hidden = false;
  } else {
    sources.hidden = true;
  }
}

function renderActions(result) {
  const didIt = $("did-it");
  const explain = $("explain");
  const family = $("family");

  // "I've done this" only makes sense for a step the user can act on, and
  // must never appear on a gated step — that would be a one-tap path past
  // the thing we just stopped for.
  const actionable = !result.stopped && result.field_key &&
    ["enter", "choose", "check", "read"].includes(result.action);

  didIt.hidden = !actionable;
  if (actionable) didIt.textContent = `I've done ${shorten(result.field_label)}`;

  explain.hidden = !result.field_key;
  family.hidden = !result.offer_family_loop;
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

    // Built with DOM methods rather than innerHTML: field.label comes from
    // a model reading a photo, so it never goes near HTML parsing.
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
  return state.sessionId;
}

async function scan(file) {
  if (!file) return;
  busy(true, "Reading the form…", [
    [4000, "Still reading — it's a dense page…"],
    [9000, "Almost there…"],
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
  busy(true, "Looking it up…");
  try {
    apply(await turn({ kind: "ask", field_key: key }));
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

function init() {
  // Hard-coded to match config.SUPPORTED_LANGUAGES so the picker is usable
  // before the first session call; /session returns the authoritative list.
  fillLanguages({
    en: "English",
    zh: "Mandarin Chinese",
    ms: "Malay",
    ta: "Tamil",
    hokkien: "Hokkien",
  });

  $("camera").addEventListener("change", (e) => scan(e.target.files[0]));
  $("camera-again").addEventListener("change", (e) => scan(e.target.files[0]));
  $("upload").addEventListener("change", (e) => scan(e.target.files[0]));
  $("pick-shot").addEventListener("click", () => $("upload").click());

  $("did-it").addEventListener("click", () => {
    if (state.current) markDone(state.current);
  });
  $("explain").addEventListener("click", () => {
    if (state.current) explainField(state.current);
  });
  $("family").addEventListener("click", askFamily);

  $("copy-message").addEventListener("click", copyMessage);
  $("close-family").addEventListener("click", () => $("family-dialog").close());

  $("language").addEventListener("change", (e) => {
    state.language = e.target.value;
    // A language change starts a fresh session rather than mutating one
    // mid-flow, so the event trail and the answers stay in one language.
    state.sessionId = null;
    toast("Language set. Take a photo to start.");
  });
}

init();
