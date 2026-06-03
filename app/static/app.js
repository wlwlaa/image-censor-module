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
const decisionPanel = document.querySelector(".decision-panel");
const passportEmpty = document.querySelector("#pp-empty");
const passportContent = document.querySelector("#pp-content");
const downloadMessage = document.querySelector("#download-message");
const socPanel = document.querySelector(".soc-panel");
const socEmpty = document.querySelector("#soc-empty");
const socBody = document.querySelector("#soc-body");
const apiDemoImage = document.querySelector("#api-demo-image");
const apiDemoButton = document.querySelector("#api-demo-button");
const apiDemoResult = document.querySelector("#api-demo-result");

// ===== State =====
let activePreset = "safe";
let presetInputFile = null;
let presetGeneratedFile = null;
let lastPayload = null;

// ===== Preset → backend mapping (existing heuristics, unchanged) =====
const transparentPng = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=";
const presetConfig = {
  safe:     { prompt: "Создать безопасную корпоративную иллюстрацию" },
  pii:      { input: "passport-card.png" },
  unsafe:   { generated: "unsafe-content.png" },
  offline:  { generated: "detector_error.png" },
  tampered: { prompt: "Создать безопасную корпоративную иллюстрацию" },
};

const RISK_CATS = {
  prompt: ["prompt_injection", "jailbreak", "policy_violation"],
  pii:    ["pii", "pii_passport", "payment_details", "qr_or_barcode"],
  output: ["graphic_violence", "unsafe_content", "detector_error", "nsfw"],
};
const CATEGORY_LABELS = {
  no_categories: "Нарушений не выявлено",
  prompt_injection: "Инъекция в запросе",
  jailbreak: "Обход ограничений",
  policy_violation: "Нарушение политики",
  pii: "Персональные данные",
  pii_passport: "Персональные данные / документ",
  payment_details: "Платёжные данные",
  qr_or_barcode: "QR-код или штрихкод",
  graphic_violence: "Опасный контент",
  unsafe_content: "Опасный контент",
  detector_error: "Сбой цензора",
  internal_error: "Сбой цензора",
  nsfw: "Недопустимый контент",
  guardrail_offline: "Сбой цензора",
  integrity_violation: "Нарушение целостности",
};
const REASON_LABELS = {
  "All mandatory checks passed": "Все обязательные проверки пройдены.",
  "Potential PII, payment details, or barcode marker detected before provider call": "Обнаружены признаки персональных или платёжных данных до обращения к генератору.",
  "Mock output detector found an unsafe filename or metadata marker": "При проверке результата обнаружен опасный контент.",
  "Prompt contains a forbidden content marker": "В запросе обнаружен запрещённый маркер.",
  "Prompt contains a suspicious bypass marker": "В запросе обнаружена попытка обхода ограничений.",
  "No security checks were executed": "Проверки безопасности не были выполнены.",
};
const SEVERITY_LABELS = {
  NONE: "НЕТ",
  LOW: "НИЗКИЙ",
  MEDIUM: "СРЕДНИЙ",
  HIGH: "ВЫСОКИЙ",
  CRITICAL: "КРИТИЧЕСКИЙ",
};
const VERDICT_LABELS = {
  ALLOW: "РАЗРЕШЕНО",
  BLOCK: "ЗАБЛОКИРОВАНО",
  REVIEW: "НА ПРОВЕРКЕ",
  OFFLINE: "ЗАПРЕТ ВЫДАЧИ",
  ERROR: "ОШИБКА",
};
const SIGNATURE_LABELS = {
  VALID: "ДЕЙСТВИТЕЛЕН",
  INVALID: "НЕДЕЙСТВИТЕЛЕН",
  PENDING: "ОЖИДАЕТ",
  "N/A": "НЕТ",
};
const DETECTOR_LABELS = {
  prompt_guard: "проверка запроса",
  image_validator: "проверка изображения",
  ocr_pii_guard: "PII-анализ",
  output_guard: "проверка результата",
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
function categoryLabel(value) {
  return CATEGORY_LABELS[value] || "Категория риска";
}
function categoriesText(items) {
  return (items || []).map(categoryLabel).join(", ");
}
function reasonLabel(value) {
  if (!value) return "Решение сформировано политикой безопасности.";
  if (REASON_LABELS[value]) return REASON_LABELS[value];
  if (value.startsWith("Fail closed:")) return "Выдача запрещена: обязательная проверка недоступна.";
  return "Решение сформировано политикой безопасности.";
}
function severityLabel(value) {
  return SEVERITY_LABELS[value] || value || "—";
}
function compactValue(value, head = 12, tail = 8) {
  if (!value) return "—";
  const text = String(value);
  return text.length > head + tail + 1 ? `${text.slice(0, head)}…${text.slice(-tail)}` : text;
}
function setCompactText(selector, value, head, tail) {
  const el = document.querySelector(selector);
  el.textContent = compactValue(value, head, tail);
  el.title = value || "";
}
function setDownloadMessage(text = "", state = "") {
  downloadMessage.textContent = text;
  downloadMessage.className = `download-message${state ? ` ${state}` : ""}`;
}
function setDecisionState(state = "") {
  decisionPanel.classList.toggle("state-allow", state === "allow");
  decisionPanel.classList.toggle("state-block", state === "block");
}
function setApiDemoResult(payload, state = "") {
  apiDemoResult.className = `api-demo-result${state ? ` ${state}` : ""}`;
  apiDemoResult.textContent = typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
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
  return values.map(item => `<span class="chip${item === "no_categories" ? " neutral" : ""}" title="${esc(item)}">${esc(categoryLabel(item))}</span>`).join("");
}
function showPayload(payload) {
  lastPayload = payload;
  const offline = activePreset === "offline" || (payload.categories || []).includes("detector_error");
  const verdictDisplay = VERDICT_LABELS[offline ? "OFFLINE" : payload.verdict] || payload.verdict;
  const verdictKey = offline ? "OFFLINE" : payload.verdict;

  const vEl = document.querySelector("#verdict-text");
  vEl.textContent = verdictDisplay;
  vEl.dataset.v = verdictKey;
  document.querySelector("#verdict-reason").textContent = reasonLabel(payload.reason);
  document.querySelector("#verdict-reason").title = payload.reason || "";
  document.querySelector("#verdict-chips").innerHTML = chipsHtml(payload.categories);
  document.querySelector("#d-severity").textContent = severityLabel(payload.severity);
  document.querySelector("#d-severity").title = payload.severity || "";
  setCompactText("#d-request", payload.request_id, 12, 6);
  setCompactText("#d-artifact", payload.artifact_id, 12, 6);
  decisionMeta.textContent = verdictDisplay;
  setDecisionState(payload.verdict === "ALLOW" ? "allow" : "block");
  renderPassport(payload);
  setDownloadMessage();

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
  vEl.textContent = VERDICT_LABELS.ERROR; vEl.dataset.v = "ERROR";
  document.querySelector("#verdict-reason").textContent = message;
  document.querySelector("#verdict-chips").innerHTML = "";
  decisionMeta.textContent = "ОШИБКА";
  setDecisionState("block");
}
function resetDecision() {
  const vEl = document.querySelector("#verdict-text");
  vEl.textContent = "…"; vEl.dataset.v = "EMPTY";
  document.querySelector("#verdict-reason").textContent = "";
  document.querySelector("#verdict-chips").innerHTML = "";
  document.querySelector("#d-severity").textContent = "—";
  setCompactText("#d-request", "");
  setCompactText("#d-artifact", "");
  decisionMeta.textContent = "ВЫПОЛНЕНИЕ";
  setDecisionState();
  resetPassport();
  resetSoc();
}

// ===== Passport =====
function renderPassport(payload) {
  const p = payload.passport;
  const sig = document.querySelector("#pp-signature");
  const sigState = p ? "VALID" : payload.verdict === "REVIEW" ? "PENDING" : "N/A";
  sig.textContent = SIGNATURE_LABELS[sigState];
  sig.dataset.state = sigState;
  if (!p) {
    passportContent.classList.add("hidden");
    passportEmpty.classList.remove("hidden");
    passportEmpty.textContent = payload.verdict === "BLOCK"
      ? "Паспорт не выпущен: выдача артефакта заблокирована."
      : "Паспорт появится после разрешённой проверки.";
    return;
  }
  passportEmpty.classList.add("hidden");
  passportContent.classList.remove("hidden");
  setCompactText("#pp-sha", p.sha256, 13, 9);
  document.querySelector("#pp-policy").textContent = p.policy_version || "—";
  document.querySelector("#pp-policy").title = p.policy_version || "";
  const detectors = p.detector_versions || {};
  const detectorNames = Object.keys(detectors).map(name => DETECTOR_LABELS[name] || name).join(" · ") || "—";
  document.querySelector("#pp-detector").textContent = detectorNames;
  document.querySelector("#pp-detector").title = JSON.stringify(detectors);
}
function resetPassport() {
  passportEmpty.classList.remove("hidden");
  passportContent.classList.add("hidden");
  passportEmpty.textContent = "Паспорт появится после разрешённой проверки.";
  const sig = document.querySelector("#pp-signature");
  sig.textContent = SIGNATURE_LABELS.PENDING;
  sig.dataset.state = "PENDING";
  downloadButton.disabled = true;
  exportButton.disabled = true;
  setDownloadMessage();
}

// ===== SOC =====
function resetSoc() {
  socPanel.classList.remove("alert");
  socEmpty.classList.remove("hidden");
  socBody.classList.add("hidden");
  document.querySelector("#soc-status").textContent = "НЕТ СОБЫТИЙ";
}
function renderSoc(payload) {
  const status = document.querySelector("#soc-status");
  const sev = document.querySelector("#soc-severity");
  const title = document.querySelector("#soc-title");
  if (payload.verdict === "ALLOW") {
    resetSoc();
    return;
  }
  socPanel.classList.add("alert");
  socEmpty.classList.add("hidden");
  socBody.classList.remove("hidden");
  status.textContent = "ИНЦИДЕНТ SOC";
  const severity = payload.severity || (payload.verdict === "BLOCK" ? "HIGH" : "MEDIUM");
  sev.textContent = severityLabel(severity); sev.dataset.sev = severity;
  sev.title = severity;
  title.textContent = activePreset === "offline" ? "ЗАПРЕТ ВЫДАЧИ · цензор недоступен" : "ИНЦИДЕНТ SOC";
  document.querySelector("#soc-event").textContent = `EVT-${(payload.request_id || "demo0001").slice(0, 8)}`;
  document.querySelector("#soc-category").textContent = categoriesText(payload.categories) || (activePreset === "offline" ? "Сбой цензора" : "Нарушение политики");
  document.querySelector("#soc-category").title = (payload.categories || []).join(", ");
  document.querySelector("#soc-state").textContent = "ОТКРЫТ";
}
function renderTamperSoc(artifactId) {
  socPanel.classList.add("alert");
  socEmpty.classList.add("hidden");
  socBody.classList.remove("hidden");
  document.querySelector("#soc-status").textContent = "ИНЦИДЕНТ SOC";
  document.querySelector("#soc-severity").textContent = severityLabel("CRITICAL");
  document.querySelector("#soc-severity").dataset.sev = "CRITICAL";
  document.querySelector("#soc-severity").title = "CRITICAL";
  document.querySelector("#soc-title").textContent = "ИНЦИДЕНТ SOC · подмена файла";
  document.querySelector("#soc-event").textContent = `EVT-${String(artifactId || "demo0001").slice(0, 8)}`;
  document.querySelector("#soc-category").textContent = "Нарушение целостности";
  document.querySelector("#soc-category").title = "integrity_violation";
  document.querySelector("#soc-state").textContent = "ОТКРЫТ";
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
      decision:  { state: "blocked", note: "ЗАПРЕТ ВЫДАЧИ" },
    });
    return;
  }
  if (payload.verdict === "ALLOW") {
    setTimeline({
      request:   { state: "done", note: "принят" },
      input:     { state: "done", note: "чисто" },
      generator: { state: "done", note: "выполнено" },
      output:    { state: "done", note: "чисто" },
      decision:  { state: "done", note: "РАЗРЕШЕНО · паспорт" },
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
    decision:  { state: "blocked", note: VERDICT_LABELS[payload.verdict] || "ЗАБЛОКИРОВАНО" },
  };
  if (blockedStep !== "decision") {
    states[blockedStep] = { state: "blocked", note: "ЗАБЛОКИРОВАНО" };
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
        sig.textContent = SIGNATURE_LABELS.INVALID; sig.dataset.state = "INVALID";
        setDownloadMessage("Выдача запрещена: подпись или SHA-256 не прошли проверку.", "error");
        renderTamperSoc(artifactId);
        return;
      }
      setDownloadMessage(`Загрузка отклонена: HTTP ${response.status}. ${payload.detail || ""}`, "error");
      return;
    }
    const blob = await response.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${artifactId}.png`;
    link.click();
    URL.revokeObjectURL(link.href);
    setDownloadMessage("Артефакт выдан после проверки подписи.", "success");
  } catch (e) {
    setDownloadMessage(`Сбой загрузки: ${e.message}`, "error");
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

apiDemoButton.addEventListener("click", async () => {
  const file = apiDemoImage.files[0];
  if (!file) {
    setApiDemoResult("Выберите изображение для API demo.", "error");
    return;
  }
  apiDemoButton.disabled = true;
  apiDemoButton.textContent = "API…";
  setApiDemoResult("Проверка…");
  const body = new FormData();
  body.append("file", file, file.name);
  try {
    const response = await fetch("/upload-image", { method: "POST", body });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(`HTTP ${response.status}. ${payload.detail || "Сбой API demo"}`);
    setApiDemoResult(payload, payload.status === "success" ? "success" : payload.status === "unavailable" ? "" : "error");
  } catch (e) {
    setApiDemoResult(e.message, "error");
  } finally {
    apiDemoButton.disabled = false;
    apiDemoButton.textContent = "Проверить API";
  }
});

// ===== Wire up =====
document.querySelectorAll(".case").forEach(b => b.addEventListener("click", () => choosePreset(b.dataset.preset)));
inputImage.addEventListener("change", () => { presetInputFile = null; updateFileLabels(); });
generatedImage.addEventListener("change", () => { presetGeneratedFile = null; updateFileLabels(); });
choosePreset("safe");
setPipelineState({ user: "done" });
resetPassport();
resetSoc();
