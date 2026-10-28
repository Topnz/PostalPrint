"use strict";
// PostalPrint – user interface. Vanilla JS, no build step.
// UI texts are Danish (the user is Danish); code and comments are English.

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const FIELDS = ["name", "street", "postcode", "city", "extra"];
const MONTHS = ["januar", "februar", "marts", "april", "maj", "juni", "juli", "august",
  "september", "oktober", "november", "december"];

const state = {
  view: null,
  postcodes: {},
  cityWasAutofilled: false,
  forceArmed: false, // warnings are shown – the next Enter prints anyway
  busy: false,
  current: null, // the label shown in the confirmation dialog
  config: null,
  status: null,
  previewSeq: 0,
  addressSeq: 0,
};

const input = (name) => $(`#f-${name}`);

// --- Helpers -------------------------------------------------------------------

/**
 * Calls the local JSON API.
 * @param {string} method HTTP method.
 * @param {string} url API path, e.g. "/api/labels/print".
 * @param {object} [body] JSON body.
 * @returns {Promise<{status: number, ok: boolean, data: object}>}
 * @throws {Error} With a Danish message if the server cannot be reached.
 */
async function api(method, url, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  let response;
  try {
    response = await fetch(url, options);
  } catch {
    throw new Error("Kan ikke få kontakt til programmet. Kør start.bat igen.");
  }
  let data = {};
  try { data = await response.json(); } catch { /* e.g. an empty error page */ }
  return { status: response.status, ok: response.ok, data };
}

/** Returns a function that runs `fn` only after `ms` milliseconds without new calls. */
function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

let toastTimer;
/** Shows a short message at the bottom of the screen. */
function toast(message, ms = 2600) {
  const el = $("#toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, ms);
}

/**
 * Creates a DOM element. Text is added as text nodes, never as HTML, so user data cannot inject markup.
 * @param {string} tag
 * @param {object} [attrs] Attributes; keys starting with "on" become event listeners.
 * @param {...(Node|string)} children
 */
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else node.setAttribute(key, value);
  }
  for (const child of children) {
    if (child !== null && child !== undefined) node.append(child);
  }
  return node;
}

function printInBrowser(url) {
  // "dialog" mode: load the PDF into an invisible iframe and open the browser's print dialog
  const frame = $("#print-frame");
  frame.onload = () => setTimeout(() => {
    try { frame.contentWindow.focus(); frame.contentWindow.print(); }
    catch { window.open(url, "_blank"); }
  }, 300);
  frame.src = `${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`;
}

// --- Views ---------------------------------------------------------------------

/** Switches between the "new", "history" and "settings" views. */
function showView(name) {
  state.view = name;
  for (const section of $$(".view")) section.hidden = section.id !== `view-${name}`;
  for (const tab of $$(".tab")) {
    if (tab.dataset.view === name) tab.setAttribute("aria-current", "page");
    else tab.removeAttribute("aria-current");
  }
  if (name === "new") {
    updateSenderBanner();
    schedulePreview();
    input("name").focus();
  } else if (name === "history") {
    loadHistory();
    $("#history-search").focus();
    $("#history-search").select();
  } else if (name === "settings") {
    loadSettings();
  }
}

// --- Fields and errors ---------------------------------------------------------

function fieldBox(key) {
  return $(`.field[data-field="${key}"]`);
}

function setFieldMessage(key, kind, message) {
  const box = fieldBox(key);
  if (!box) return false;
  box.classList.remove("error", "warning");
  if (kind) box.classList.add(kind);
  $(".msg", box).textContent = message || "";
  return true;
}

function clearFieldMessages(root) {
  for (const box of $$(".field", root)) {
    box.classList.remove("error", "warning");
    const msg = $(".msg", box);
    if (msg) msg.textContent = "";
  }
}

function showFormMessage(kind, content) {
  const box = $("#form-message");
  box.className = `banner ${kind}`;
  box.replaceChildren(...(Array.isArray(content) ? content : [content]));
  box.hidden = false;
}

function hideFormMessage() {
  $("#form-message").hidden = true;
}

function readRecipient() {
  return Object.fromEntries(FIELDS.map((name) => [name, input(name).value]));
}

function setCityAutofilled(value) {
  state.cityWasAutofilled = value;
  input("city").classList.toggle("autofilled", value);
  // An autofilled city is skipped by Tab
  input("city").tabIndex = value ? -1 : 0;
}

function clearForm() {
  for (const name of FIELDS) input(name).value = "";
  setCityAutofilled(false);
  disarm();
  clearFieldMessages($("#label-form"));
  hideFormMessage();
  setAddressStatus("", "");
  schedulePreview();
  input("name").focus();
}

function disarm() {
  if (state.forceArmed) {
    state.forceArmed = false;
    hideFormMessage();
    for (const box of $$("#label-form .field.warning")) setFieldMessage(box.dataset.field, null, "");
  }
}

function showErrors(errors, warnings = {}) {
  clearFieldMessages($("#label-form"));
  hideFormMessage();
  let first = null;
  for (const name of FIELDS) {
    if (errors[name]) {
      setFieldMessage(name, "error", errors[name]);
      first ??= name;
    } else if (warnings[name]) {
      setFieldMessage(name, "warning", warnings[name]);
    }
  }
  if (errors.sender) {
    showFormMessage("error", [errors.sender, " ",
      el("button", { type: "button", class: "link", onclick: () => showView("settings") }, "Gå til Indstillinger")]);
  }
  if (first) {
    input(first).focus();
    input(first).select();
  }
}

function showWarnings(warnings) {
  clearFieldMessages($("#label-form"));
  for (const key of Object.keys(warnings)) {
    if (FIELDS.includes(key)) setFieldMessage(key, "warning", ""); // highlight the field in yellow
  }
  if (warnings.address) setFieldMessage("street", "warning", "");
  const list = el("ul", {}, ...Object.values(warnings).map((m) => el("li", {}, m)));
  showFormMessage("warning", [el("strong", {}, "Tryk Enter igen for at printe alligevel"), list]);
}

// --- Postcode → city -----------------------------------------------------------

/**
 * Fills in the official city when the postcode has four digits, unless the user typed a city themselves.
 * Shared by the label form and the sender form in Settings.
 */
function autofillCity(postcodeInput, cityInput, isAutofilled, setAutofilled) {
  const code = postcodeInput.value.replace(/\D/g, "");
  const official = code.length === 4 ? state.postcodes[code] : undefined;
  if (official && (cityInput.value.trim() === "" || isAutofilled())) {
    cityInput.value = official;
    setAutofilled(true);
  } else if (!official && isAutofilled()) {
    cityInput.value = "";
    setAutofilled(false);
  }
}

// --- Pasting a whole address ---------------------------------------------------

const FLOOR_PATTERN = /^(st|kl|\d{1,2}\.?\s*(sal|tv|th|mf)?|\d{1,2}\.\s*\S+|lejl\.?.*|dør.*)\.?$/i;

/**
 * Splits a pasted address (several lines, or one comma-separated line) into fields.
 * Example: "Test Testesen⏎Fiktivvej 12⏎8700 Horsens", or "Test Testesen, Fiktivvej 12, 8700 Horsens".
 * @param {string} text
 * @returns {?{name: string, extra: string, street: string, postcode: string, city: string}}
 *   null if the text does not look like an address.
 */
function parsePastedAddress(text) {
  let lines = text.split(/\r?\n/).map((l) => l.replace(/\s+/g, " ").trim()).filter(Boolean);
  if (lines.length === 1 && /,\s*(dk-?)?\d{4}\s+\S/i.test(lines[0])) {
    lines = lines[0].split(",").map((l) => l.trim()).filter(Boolean);
  }
  lines = lines.filter((l) => !/^(danmark|denmark|dk)$/i.test(l));
  if (lines.length < 2) return null;

  const result = { name: "", extra: "", street: "", postcode: "", city: "" };
  const postalIndex = lines.findIndex((l) => /^(dk-?)?\d{4}\s+\p{L}/iu.test(l));
  if (postalIndex >= 0) {
    const match = lines[postalIndex].match(/^(?:dk-?)?(\d{4})\s+(.+)$/i);
    result.postcode = match[1];
    result.city = match[2];
  }
  let rest = lines.filter((_, i) => i !== postalIndex);

  // A floor/door on its own line belongs to the street
  let streetIndex = -1;
  for (let i = rest.length - 1; i >= 1; i--) {
    if (/\p{L}.*\s\d{1,3}\s?\p{L}?(\s|,|$)/u.test(rest[i])) { streetIndex = i; break; }
  }
  if (streetIndex > 0) {
    let street = rest[streetIndex];
    const floors = [];
    for (let i = streetIndex + 1; i < rest.length && FLOOR_PATTERN.test(rest[i]); i++) floors.push(i);
    if (floors.length) street += ", " + floors.map((i) => rest[i]).join(" ");
    result.street = street;
    rest = rest.filter((_, i) => i !== streetIndex && !floors.includes(i));
  }
  result.name = rest[0] || "";
  result.extra = rest.slice(1).join(", ");
  return result;
}

function onNamePaste(event) {
  const text = event.clipboardData?.getData("text") || "";
  if (!/[\n,]/.test(text)) return;
  const parsed = parsePastedAddress(text);
  if (!parsed || !parsed.street) return;
  event.preventDefault();
  for (const name of FIELDS) input(name).value = parsed[name];
  setCityAutofilled(false);
  if (parsed.postcode && !parsed.city) autofillCity(input("postcode"), input("city"), () => true, setCityAutofilled);
  onFormChanged();
  checkAddressSoon();
  toast("Adressen er fordelt i felterne – tjek dem og tryk Enter");
}

// --- Preview -------------------------------------------------------------------

const schedulePreview = debounce(updatePreview, 120);

/** Asks the server for the exact label layout and draws it. Out-of-order responses are ignored. */
async function updatePreview() {
  const seq = ++state.previewSeq;
  let layout;
  try {
    const { ok, data } = await api("POST", "/api/labels/preview", { recipient: readRecipient() });
    if (!ok || seq !== state.previewSeq) return;
    layout = data;
  } catch {
    return;
  }
  drawPreview(layout);
}

/** Draws the layout (in mm, origin bottom-left) into the SVG (origin top-left). */
function drawPreview(layout) {
  const ns = "http://www.w3.org/2000/svg";
  const group = $("#preview-content");
  group.replaceChildren();
  for (const t of layout.texts) {
    const text = document.createElementNS(ns, "text");
    text.setAttribute("x", t.x);
    text.setAttribute("y", layout.height - t.y);
    text.setAttribute("font-size", t.size);
    if (t.bold) text.classList.add("bold");
    text.textContent = t.text;
    group.append(text);
  }
  if (layout.rule) {
    const line = document.createElementNS(ns, "line");
    line.setAttribute("x1", layout.rule.x1);
    line.setAttribute("x2", layout.rule.x2);
    line.setAttribute("y1", layout.height - layout.rule.y);
    line.setAttribute("y2", layout.height - layout.rule.y);
    line.setAttribute("stroke-width", Math.max(layout.rule.width, 0.3));
    group.append(line);
  }
  if (!layout.texts.some((t) => t.bold)) {
    const hint = document.createElementNS(ns, "text");
    hint.setAttribute("x", layout.margin);
    hint.setAttribute("y", layout.height - layout.margin - 4);
    hint.setAttribute("font-size", 6);
    hint.classList.add("placeholder", "bold");
    hint.textContent = "Modtagerens adresse";
    group.append(hint);
  }
  const caption = $("#preview-caption");
  if (layout.too_long && layout.texts.some((t) => t.bold)) {
    caption.textContent = "For lang til etiketten – forkort teksten.";
  } else if (layout.recipient_size) {
    caption.textContent = `Modtager i ${layout.recipient_size} pt. Den stiplede ramme er margenen på 15 mm.`;
  } else {
    caption.textContent = "Den stiplede ramme er margenen på 15 mm.";
  }
}

// --- Online address check (layer 2) --------------------------------------------

function setAddressStatus(kind, message) {
  const box = $("#address-status");
  box.className = `address-status ${kind}`;
  box.textContent = message;
}

const checkAddressSoon = debounce(checkAddress, 700);

/** Runs the online check in the background while the user types, and shows the result. */
async function checkAddress() {
  const street = input("street").value.trim();
  const postcode = input("postcode").value.replace(/\D/g, "");
  if (!state.config?.address_check?.online || !/\p{L}.*\s\d/u.test(street) || !state.postcodes[postcode]) {
    setAddressStatus("", "");
    return;
  }
  const seq = ++state.addressSeq;
  setAddressStatus("", "Tjekker adressen online …");
  try {
    const { data } = await api("POST", "/api/address/check", { street, postcode });
    if (seq !== state.addressSeq) return;
    if (data.status === "found") setAddressStatus("ok", "✓ Adressen findes");
    else if (data.is_warning) setAddressStatus("warning", `⚠ ${data.message}`);
    else setAddressStatus("", data.status === "unavailable" ? "Online-tjek ikke tilgængeligt lige nu." : "");
  } catch {
    if (seq === state.addressSeq) setAddressStatus("", "");
  }
}

// --- Printing and confirmation -------------------------------------------------

function onFormChanged() {
  disarm();
  schedulePreview();
}

/**
 * Enter in the form: validate and print.
 * 422 → show errors, 409 → show warnings (the next Enter forces), 200 → open the confirmation dialog.
 */
async function submitLabel(event) {
  event.preventDefault();
  if (state.busy || !$("#confirm").hidden) return;
  state.busy = true;
  $("#print-button").disabled = true;
  $("#print-button").textContent = "Printer …";
  try {
    const { status, ok, data } = await api("POST", "/api/labels/print", {
      recipient: readRecipient(),
      force: state.forceArmed,
    });
    if (status === 422) {
      state.forceArmed = false;
      showErrors(data.errors || {}, data.warnings || {});
    } else if (status === 409) {
      showWarnings(data.warnings || {});
      state.forceArmed = true;
    } else if (!ok) {
      showFormMessage("error", data.error || "Noget gik galt. Prøv igen.");
    } else {
      state.forceArmed = false;
      clearFieldMessages($("#label-form"));
      hideFormMessage();
      openConfirm(data);
    }
  } catch (err) {
    showFormMessage("error", err.message);
  } finally {
    state.busy = false;
    $("#print-button").disabled = false;
    $("#print-button").textContent = "Print";
  }
}

function applyPrintResult(result) {
  if (result.print_in_browser) printInBrowser(result.pdf_url);
}

/** Shows "Did the label come out fine?". Enter saves it to the history, Esc prints it again. */
function openConfirm(result) {
  state.current = result;
  const r = result.recipient;
  $("#confirm-recipient").textContent = [r.name, r.extra, r.street, `${r.postcode} ${r.city}`]
    .filter(Boolean).join(" · ");
  updateConfirmError(result.print_error);
  $("#confirm").hidden = false;
  $("#confirm-yes").focus();
  applyPrintResult(result);
}

function updateConfirmError(message) {
  const box = $("#confirm-error");
  $("#confirm-title").textContent = message ? "Etiketten blev ikke printet" : "Kom etiketten pænt ud?";
  box.hidden = !message;
  box.textContent = message ? `${message} PDF'en er gemt, så du kan også printe den selv via «Åbn PDF».` : "";
}

function closeConfirm() {
  $("#confirm").hidden = true;
  state.current = null;
}

async function confirmLabel() {
  if (state.busy || !state.current) return;
  state.busy = true;
  try {
    const { ok, data } = await api("POST", `/api/labels/${state.current.id}/confirm`);
    if (!ok) {
      updateConfirmError(data.error || "Kunne ikke gemme i historikken.");
      return;
    }
    closeConfirm();
    clearForm();
    toast("Gemt i historikken");
  } catch (err) {
    updateConfirmError(err.message);
  } finally {
    state.busy = false;
  }
}

async function reprintLabel() {
  if (state.busy || !state.current) return;
  state.busy = true;
  try {
    const { ok, data } = await api("POST", `/api/labels/${state.current.id}/reprint`);
    if (!ok) {
      updateConfirmError(data.error || "Kunne ikke printe igen.");
      return;
    }
    updateConfirmError(data.print_error);
    applyPrintResult(data);
    if (!data.print_error) toast("Sendt til printeren igen");
  } catch (err) {
    updateConfirmError(err.message);
  } finally {
    state.busy = false;
  }
}

async function cancelLabel() {
  if (!state.current) return;
  await api("POST", `/api/labels/${state.current.id}/cancel`).catch(() => {});
  closeConfirm();
  input("name").focus();
  toast("Ikke gemt i historikken. PDF'en ligger stadig i historikmappen.", 4000);
}

// --- History -------------------------------------------------------------------

const searchHistorySoon = debounce(() => loadHistory(), 150);

async function loadHistory() {
  const q = $("#history-search").value.trim();
  const list = $("#history-list");
  try {
    const { data } = await api("GET", `/api/history?q=${encodeURIComponent(q)}`);
    renderHistory(data.entries || [], q);
  } catch (err) {
    list.replaceChildren(el("p", { class: "empty" }, err.message));
  }
}

function formatWhen(iso) {
  const d = new Date(iso);
  const time = d.toLocaleTimeString("da-DK", { hour: "2-digit", minute: "2-digit" });
  return `${d.getDate()}. ${MONTHS[d.getMonth()].slice(0, 3)}. ${time}`;
}

function renderHistory(entries, q) {
  const list = $("#history-list");
  if (!entries.length) {
    list.replaceChildren(el("p", { class: "empty" }, q ? `Ingen etiketter matcher «${q}».` : "Ingen etiketter endnu."));
    return;
  }
  const nodes = [];
  let month = null;
  for (const entry of entries) {
    const key = entry.printed_at.slice(0, 7);
    if (key !== month) {
      month = key;
      const [year, m] = key.split("-");
      nodes.push(el("h3", { class: "month-title" }, `${MONTHS[Number(m) - 1]} ${year}`));
    }
    const r = entry.recipient;
    const address = [r.extra, r.street, `${r.postcode} ${r.city}`].filter(Boolean).join(" · ");
    const reprints = entry.reprints ? ` · printet igen ${entry.reprints}×` : "";
    nodes.push(el("div", { class: "history-row" },
      el("div", { class: "when" }, formatWhen(entry.printed_at)),
      el("div", { class: "who" }, el("strong", {}, r.name), el("span", {}, address + reprints)),
      el("div", { class: "row-actions" },
        el("button", { type: "button", class: "secondary small", onclick: () => reprintHistory(entry.id) }, "Print igen"),
        el("button", { type: "button", class: "secondary small", onclick: () => window.open(`/api/labels/${entry.id}/pdf`, "_blank") }, "Åbn PDF"),
      ),
    ));
  }
  list.replaceChildren(...nodes);
}

async function reprintHistory(id) {
  try {
    const { ok, data } = await api("POST", `/api/history/${id}/reprint`);
    if (!ok) { toast(data.error || "Kunne ikke printe.", 5000); return; }
    applyPrintResult(data);
    toast(data.print_error ? data.print_error : "Sendt til printeren", data.print_error ? 7000 : 2600);
    loadHistory();
  } catch (err) {
    toast(err.message, 5000);
  }
}

// --- Settings ------------------------------------------------------------------

const SETTINGS_INPUTS = {
  "sender.name": "#s-name",
  "sender.street": "#s-street",
  "sender.postcode": "#s-postcode",
  "sender.city": "#s-city",
};
let senderCityAutofilled = false;

async function loadSettings() {
  clearFieldMessages($("#settings-form"));
  try {
    const { data } = await api("GET", "/api/config");
    applyConfig(data);
  } catch (err) {
    toast(err.message, 5000);
    return;
  }
  const c = state.config;
  $("#s-name").value = c.sender.name;
  $("#s-street").value = c.sender.street;
  $("#s-postcode").value = c.sender.postcode;
  $("#s-city").value = c.sender.city;
  $("#s-mode").value = c.print.mode;
  $("#s-sumatra").value = c.print.sumatra_path;
  $("#s-rotation").value = String(c.print.rotation);
  $("#s-online").checked = c.address_check.online;
  senderCityAutofilled = false;
  setPrinterOptions([], c.print.printer_name);
  updateModeVisibility();
  $("#welcome-banner").hidden = !state.status.sender_missing;
  (state.status.sender_missing ? $("#s-name") : $("#s-mode")).focus();
  loadPrinters();
}

function applyConfig(data) {
  state.config = data.config;
  state.status = data.status;
  updateSumatraStatus();
  updateSenderBanner();
}

function updateSenderBanner() {
  $("#sender-banner").hidden = !state.status?.sender_missing;
}

function updateSumatraStatus() {
  const box = $("#sumatra-status");
  box.replaceChildren();
  if (state.status?.sumatra_path) {
    box.textContent = `Fundet: ${state.status.sumatra_path}`;
  } else {
    box.append("Ikke fundet. ",
      el("a", { href: state.status?.sumatra_download_url || "#", target: "_blank", rel: "noopener" }, "Hent SumatraPDF gratis"),
      " og installér det, så findes det automatisk.");
  }
}

function setPrinterOptions(printers, selected) {
  const select = $("#s-printer");
  const names = [...printers];
  if (selected && !names.includes(selected)) names.unshift(selected);
  select.replaceChildren(
    el("option", { value: "" }, "Windows' standardprinter"),
    ...names.map((name) => el("option", { value: name }, printers.includes(name) || !printers.length ? name : `${name} (ikke fundet)`)),
  );
  select.value = selected || "";
}

async function loadPrinters() {
  const select = $("#s-printer");
  const selected = select.value || state.config?.print.printer_name || "";
  $("#refresh-printers").disabled = true;
  try {
    const { data } = await api("GET", "/api/printers");
    setPrinterOptions(data.printers || [], selected);
  } catch { /* keep the current list */ } finally {
    $("#refresh-printers").disabled = false;
  }
}

function updateModeVisibility() {
  $(".sumatra-only").hidden = $("#s-mode").value !== "sumatra";
}

function readSettings() {
  return {
    sender: {
      name: $("#s-name").value,
      street: $("#s-street").value,
      postcode: $("#s-postcode").value,
      city: $("#s-city").value,
    },
    print: {
      mode: $("#s-mode").value,
      printer_name: $("#s-printer").value,
      sumatra_path: $("#s-sumatra").value,
      rotation: Number($("#s-rotation").value),
    },
    address_check: { online: $("#s-online").checked },
  };
}

async function saveSettings() {
  clearFieldMessages($("#settings-form"));
  try {
    const { status, data } = await api("PUT", "/api/config", readSettings());
    if (status === 422) {
      let first = null;
      for (const [key, message] of Object.entries(data.errors)) {
        setFieldMessage(key, "error", message);
        first ??= SETTINGS_INPUTS[key];
      }
      if (first) $(first).focus();
      return false;
    }
    applyConfig(data);
    $("#welcome-banner").hidden = true;
    return true;
  } catch (err) {
    toast(err.message, 5000);
    return false;
  }
}

async function onSettingsSubmit(event) {
  event.preventDefault();
  if (await saveSettings()) {
    toast("Indstillinger gemt");
    schedulePreview();
  }
}

async function printCalibration() {
  if (!(await saveSettings())) return;
  try {
    const { data } = await api("POST", "/api/calibration/print");
    applyPrintResult(data);
    toast(data.print_error || "Kalibreringsetiket sendt – mål den med en lineal", data.print_error ? 7000 : 3500);
  } catch (err) {
    toast(err.message, 5000);
  }
}

// --- Keyboard ------------------------------------------------------------------

/** Global keyboard shortcuts. While the confirmation dialog is open, only Enter and Esc apply. */
function onKeyDown(event) {
  const confirmOpen = !$("#confirm").hidden;
  if (confirmOpen) {
    if (event.repeat) { event.preventDefault(); return; } // a held-down Enter must not confirm
    if (event.key === "Enter") { event.preventDefault(); confirmLabel(); }
    else if (event.key === "Escape") { event.preventDefault(); reprintLabel(); }
    return;
  }
  const ctrl = event.ctrlKey || event.metaKey;
  if (ctrl && event.key.toLowerCase() === "h") { event.preventDefault(); showView("history"); return; }
  if (ctrl && event.key === ",") { event.preventDefault(); showView("settings"); return; }
  if (event.key === "Escape") {
    event.preventDefault();
    if (state.view === "new") clearForm();
    else showView("new");
  }
}

// --- Startup -------------------------------------------------------------------

function bindEvents() {
  document.addEventListener("keydown", onKeyDown);
  for (const tab of $$(".tab")) tab.addEventListener("click", () => showView(tab.dataset.view));
  for (const link of $$("[data-goto]")) link.addEventListener("click", () => showView(link.dataset.goto));

  $("#label-form").addEventListener("submit", submitLabel);
  for (const name of FIELDS) input(name).addEventListener("input", () => {
    if (fieldBox(name).classList.contains("error")) setFieldMessage(name, null, "");
    onFormChanged();
  });
  input("name").addEventListener("paste", onNamePaste);
  input("postcode").addEventListener("input", () => {
    autofillCity(input("postcode"), input("city"), () => state.cityWasAutofilled, setCityAutofilled);
    checkAddressSoon();
  });
  input("street").addEventListener("input", checkAddressSoon);
  input("city").addEventListener("input", () => setCityAutofilled(false));

  $("#confirm-yes").addEventListener("click", confirmLabel);
  $("#confirm-reprint").addEventListener("click", reprintLabel);
  $("#confirm-cancel").addEventListener("click", cancelLabel);
  $("#confirm-open-pdf").addEventListener("click", () => {
    if (state.current) window.open(state.current.pdf_url, "_blank");
  });

  $("#history-search").addEventListener("input", searchHistorySoon);
  $("#open-folder").addEventListener("click", async () => {
    const { ok, data } = await api("POST", "/api/history/folder/open").catch((e) => ({ data: { error: e.message } }));
    if (!ok) toast(data.error || "Mappen kunne ikke åbnes.", 5000);
  });

  $("#settings-form").addEventListener("submit", onSettingsSubmit);
  $("#s-mode").addEventListener("change", updateModeVisibility);
  $("#refresh-printers").addEventListener("click", loadPrinters);
  $("#print-calibration").addEventListener("click", printCalibration);
  $("#s-postcode").addEventListener("input", () => autofillCity(
    $("#s-postcode"), $("#s-city"), () => senderCityAutofilled, (v) => { senderCityAutofilled = v; }));
  $("#s-city").addEventListener("input", () => { senderCityAutofilled = false; });
}

async function init() {
  bindEvents();
  try {
    const [postcodes, config] = await Promise.all([api("GET", "/api/postcodes"), api("GET", "/api/config")]);
    state.postcodes = postcodes.data;
    applyConfig(config.data);
  } catch (err) {
    showView("new");
    showFormMessage("error", err.message);
    return;
  }
  showView(state.status.sender_missing ? "settings" : "new");
}

init();
