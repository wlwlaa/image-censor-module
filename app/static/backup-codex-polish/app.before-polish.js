"use strict";

// ===== DOM =====
const form = document.querySelector("#moderation-form");
const promptInput = document.querySelector("#prompt");
const inputImage = document.querySelector("#input-image");
const generatedImage = document.querySelector("#generated-image");
const tokenInput = document.querySelector("#token");
const submitButton = document.querySelector("#submit-button");
const hint = null;
const exportButton = document.querySelector("#export-passport");
const downloadButton = document.querySelector("#download-button");
const decisionMeta = document.querySelector("#decision-meta");

// ===== State =====
let activePreset = "safe";
let presetInputFile = null;
let presetGeneratedFile = null;
let lastPayload = null;

// ===== Preset → backend mapping (existing heuristics, unchanged) =====
const transparentPng = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=";
const presetConfig = {
  safe:     { prompt: "draw a safe corporate illustration" },
  pii:      { input: "passport-card.png" },
  unsafe:   { generated: "unsafe-content.png" },
  offline:  { generated: "detector_error.png" },
  tampered: { prompt: "draw a safe corporate illustration" },
};

const RISK_CATS = {
  prompt: ["prompt_injection", "jailbreak", "policy_violation"],
  pii:    ["pii", "pii_passport", "payment_details", "qr_or_barcode"],
  output: ["graphic_violence", "unsafe_content", "detector_error", "nsfw"],
};

// ===== Helpers =====
function pngFile(name) {
  const bytes = Uint8Array.from(atob(transparentPng), ch => ch.charCodeAt(0));
  return new File([bytes], name, { type: "image/png" });
}
function esc(v) {
  return String(v ?? "—").replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[c]);
}
function updateFileLabels() {
  document.querySelector("#input-file-name").textContent = inputImage.files[0]?.name || presetInputFile?.name || "не выбран";
  document.querySelector("#generated-file-name").textContent = generatedImage.files[0]?.name || presetGeneratedFile?.name || "не выбран";
}
function choosePreset(name) {
  if (!presetConfig[name]) return;
  activePreset = name;
  const p = presetConfig[name];
  presetInputFile = p.input ? pngFile(p.input) : null;
  presetGeneratedFile = p.generated ? pngFile(p.generated) : null;
  promptInput.value = p.prompt || "";
  inputImage.value = "";
  generatedImage.value = "";
  updateFileLabels();
  document.querySelectorAll(".case").forEach(b => b.classList.toggle("active", b.dataset.preset === name));
}

// ===== Pipeline =====
const PIPELINE = ["user","prompt","input","generator","quarantine","output","policy","passport","release"];
function setPipelineState(map) {
  document.querySelectorAll(".pipe-node").forEach(n => {
    n.classList.remove("active","done","blocked");
    const s = map[n.dataset.step];
    if (s) n.classList.add(s);
  });
}
async function animatePipeline() {
  const seq = activePreset === "offline"
    ? ["user","prompt","input","generator","quarantine","output"]
    : ["user","prompt","input","generator","quarantine","output","policy","passport"];
  const state = {};
  for (const step of seq) {
    state[step] = "active";
    setPipelineState({ ...state });
    await new Promise(r => setTimeout(r, 90));
    state[step] = "done";
  }
  setPipelineState({ ...state });
}
function inferBlockStage(payload) {
  const cats = payload?.categories || [];
  if (activePreset === "offline" || cats.includes("detector_error")) return "output";
  if (cats.some(c => RISK_CATS.pii.includes(c))) return "input";
  if (cats.some(c => RISK_CATS.output.includes(c))) return "output";
  if (cats.some(c => RISK_CATS.prompt.includes(c))) return "prompt";
  return "policy";
}
function finalizePipeline(payload) {
  const v = payload?.verdict;
  const state = {};
  PIPELINE.forEach(s => { state[s] = "done"; });
  if (v === "BLOCK") {
    const last = inferBlockStage(payload);
    state[last] = "blocked";
    const idx = PIPELINE.indexOf(last);
    PIPELINE.slice(idx + 1).forEach(s => { state[s] = ""; });
  } else if (v === "REVIEW") {
    state.policy = "active";
  } else if (v !== "ALLOW") {
    PIPELINE.forEach(s => { state[s] = ""; });
  }
  setPipelineState(state);
}

// ===== Decision render =====
function chipsHtml(items) {
  const values = items?.length ? items : ["no_categories"];
  return values.map(item => `<span class="chip">${esc(item)}</span>`).join("");
}
function showPayload(payload) {
  lastPayload = payload;
  const offline = activePreset === "offline" || (payload.categories || []).includes("detector_error");
  const verdictDisplay = offline ? "FAIL CLOSED" : payload.verdict;
  const verdictKey = offline ? "OFFLINE" : payload.verdict;

  const vEl = document.querySelector("#verdict-text");
  vEl.textContent = verdictDisplay;
  vEl.dataset.v = verdictKey;
  document.querySelector("#verdict-reason").textContent = payload.reason || "—";
  document.querySelector("#verdict-chips").innerHTML = chipsHtml(payload.categories);
  document.querySelector("#d-severity").textContent = payload.severity || "—";
  document.querySelector("#d-request").textContent = payload.request_id || "—";
  document.querySelector("#d-artifact").textContent = payload.artifact_id || "—";
  decisionMeta.textContent = offline ? "FAIL CLOSED" : verdictDisplay;

  // Passport
  const p = payload.passport || {};
  document.querySelector("#pp-sha").textContent = p.sha256 || "—";
  document.querySelector("#pp-policy").textContent = p.policy_version || "—";
  const dv = p.detector_versions ? Object.entries(p.detector_versions).map(([k,v]) => `${k}=${v}`).join(", ") : "—";
  document.querySelector("#pp-detector").textContent = dv;
  const sig = document.querySelector("#pp-signature");
  const sigState = payload.verdict === "ALLOW" ? "VALID" : payload.verdict === "REVIEW" ? "PENDING" : "N/A";
  sig.textContent = sigState;
  sig.dataset.state = sigState;

  const canDownload = payload.verdict === "ALLOW" && payload.artifact_id;
  downloadButton.disabled = !canDownload;
  downloadButton.dataset.artifact = payload.artifact_id || "";
  exportButton.disabled = !payload.request_id;

  finalizePipeline(payload);
  renderSoc(payload);
  renderTimeline(payload);
}
function showError(message) {
  const vEl = document.querySelector("#verdict-text");
  vEl.textContent = "ERROR"; vEl.dataset.v = "ERROR";
  document.querySelector("#verdict-reason").textContent = message;
  document.querySelector("#verdict-chips").innerHTML = "";
  decisionMeta.textContent = "ОШИБКА";
}
function resetDecision() {
  const vEl = document.querySelector("#verdict-text");
  vEl.textContent = "…"; vEl.dataset.v = "EMPTY";
  document.querySelector("#verdict-reason").textContent = "";
  document.querySelector("#verdict-chips").innerHTML = "";
  document.querySelector("#d-severity").textContent = "—";
  document.querySelector("#d-request").textContent = "—";
  document.querySelector("#d-artifact").textContent = "—";
  decisionMeta.textContent = "ВЫПОЛНЕНИЕ";
}

// ===== SOC =====
function renderSoc(payload) {
  const status = document.querySelector("#soc-status");
  const sev = document.querySelector("#soc-severity");
  const title = document.querySelector("#soc-title");
  if (payload.verdict === "ALLOW") {
    status.textContent = "НЕТ СОБЫТИЙ";
    sev.textContent = "—"; sev.dataset.sev = "";
    title.textContent = "событий нет";
    document.querySelector("#soc-event").textContent = "—";
    document.querySelector("#soc-category").textContent = "—";
    document.querySelector("#soc-state").textContent = "—";
    return;
  }
  status.textContent = "АЛЕРТ";
  const severity = payload.severity || (payload.verdict === "BLOCK" ? "HIGH" : "MEDIUM");
  sev.textContent = severity; sev.dataset.sev = severity;
  title.textContent = activePreset === "offline" ? "FAIL CLOSED · цензор недоступен" : "SOC ALERT";
  document.querySelector("#soc-event").textContent = `EVT-${(payload.request_id || "demo0001").slice(0, 8)}`;
  document.querySelector("#soc-category").textContent = (payload.categories || []).join(", ") || (activePreset === "offline" ? "guardrail_offline" : "policy_violation");
  document.querySelector("#soc-state").textContent = "OPEN";
}

// ===== Timeline =====
function setTimeline(states) {
  document.querySelectorAll("#timeline li").forEach(li => {
    li.classList.remove("done","active","blocked");
    const em = li.querySelector("em");
    const s = states[li.dataset.step];
    if (!s) { em.textContent = "ожидание"; return; }
    li.classList.add(s.state || "done");
    em.textContent = s.note || "";
  });
}
function renderTimeline(payload) {
  if (activePreset === "offline" || (payload.categories || []).includes("detector_error")) {
    setTimeline({
      request:   { state: "done", note: "принят" },
      input:     { state: "done", note: "чисто" },
      generator: { state: "done", note: "в карантине" },
      output:    { state: "blocked", note: "детектор недоступен" },
      decision:  { state: "blocked", note: "FAIL CLOSED" },
    });
    return;
  }
  if (payload.verdict === "ALLOW") {
    setTimeline({
      request:   { state: "done", note: "принят" },
      input:     { state: "done", note: "чисто" },
      generator: { state: "done", note: "выполнено" },
      output:    { state: "done", note: "чисто" },
      decision:  { state: "done", note: "ALLOW · паспорт" },
    });
    return;
  }
  const stage = inferBlockStage(payload);
  const map = { prompt: "request", input: "input", output: "output", policy: "decision" };
  const blockedStep = map[stage] || "decision";
  const states = {
    request:   { state: "done", note: "принят" },
    input:     { state: "done", note: "проверено" },
    generator: { state: "done", note: "в карантине" },
    output:    { state: "done", note: "проверено" },
    decision:  { state: "blocked", note: payload.verdict || "BLOCK" },
  };
  if (blockedStep !== "decision") {
    states[blockedStep] = { state: "blocked", note: "BLOCK" };
    const order = ["request","input","generator","output","decision"];
    const idx = order.indexOf(blockedStep);
    order.slice(idx + 1, order.length - 1).forEach(s => { delete states[s]; });
  }
  setTimeline(states);
}
function resetTimeline() { setTimeline({}); }

// ===== Download =====
async function downloadArtifact(artifactId) {
  const token = tokenInput.value.trim();
  if (!token) { showError("Введите токен загрузки для проверенной выдачи."); return; }
  try {
    const response = await fetch(`/v1/download/${encodeURIComponent(artifactId)}`, { headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      if (response.status === 409) {
        const sig = document.querySelector("#pp-signature");
        sig.textContent = "INVALID"; sig.dataset.state = "INVALID";
      }
      showError(`Загрузка отклонена: HTTP ${response.status}. ${payload.detail || ""}`);
      return;
    }
    const blob = await response.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${artifactId}.png`;
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (e) {
    showError(`Сбой загрузки: ${e.message}`);
  }
}

downloadButton.addEventListener("click", () => {
  const id = downloadButton.dataset.artifact;
  if (id) downloadArtifact(id);
});

exportButton.addEventListener("click", () => {
  if (!lastPayload) return;
  const blob = new Blob([JSON.stringify(lastPayload, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `safety-passport-${lastPayload.request_id || "demo"}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
});

// ===== Submit =====
form.addEventListener("submit", async event => {
  event.preventDefault();
  submitButton.disabled = true;
  submitButton.textContent = "Проверяем…";
  resetDecision();
  resetTimeline();
  await animatePipeline();

  const body = new FormData();
  if (promptInput.value.trim()) body.append("prompt", promptInput.value.trim());
  const actualInput = inputImage.files[0] || presetInputFile;
  const actualGenerated = generatedImage.files[0] || presetGeneratedFile;
  if (actualInput) body.append("input_image", actualInput, actualInput.name);
  if (actualGenerated) body.append("generated_image", actualGenerated, actualGenerated.name);

  try {
    const response = await fetch("/v1/moderate", { method: "POST", body });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(`HTTP ${response.status}. ${payload.detail || "Сбой проверки"}`);
    showPayload(payload);
  } catch (e) {
    showError(e.message);
  } finally {
    submitButton.disabled = false;
    submitButton.innerHTML = "Проверить <b>→</b>";
  }
});

// ===== Wire up =====
document.querySelectorAll(".case").forEach(b => b.addEventListener("click", () => choosePreset(b.dataset.preset)));
inputImage.addEventListener("change", () => { presetInputFile = null; updateFileLabels(); });
generatedImage.addEventListener("change", () => { presetGeneratedFile = null; updateFileLabels(); });
choosePreset("safe");
setPipelineState({ user: "done" });
