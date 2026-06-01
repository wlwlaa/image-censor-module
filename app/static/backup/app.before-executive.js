"use strict";

// ====== DOM ======
const form = document.querySelector("#moderation-form");
const promptInput = document.querySelector("#prompt");
const inputImage = document.querySelector("#input-image");
const generatedImage = document.querySelector("#generated-image");
const tokenInput = document.querySelector("#token");
const submitButton = document.querySelector("#submit-button");
const result = document.querySelector("#result");
const emptyState = document.querySelector("#empty-state");
const hint = document.querySelector("#preset-hint");
const exportButton = document.querySelector("#export-passport");
const kpiSoc = document.querySelector("#kpi-soc");
const kpiBlocked = document.querySelector("#kpi-blocked");
const kpiReview = document.querySelector("#kpi-review");
const decisionMeta = document.querySelector("#decision-meta");
const passportKv = document.querySelector("#passport-kv");
const passportEmpty = document.querySelector("#passport-empty");

// ====== State ======
let activePreset = "passport";
let presetInputFile = null;
let presetGeneratedFile = null;
let lastPayload = null;
let socCount = 0, blockedCount = 0, reviewCount = 0;

// ====== Preset mapping (backend heuristics unchanged) ======
const transparentPng = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=";
const presetConfig = {
  safe: {
    prompt: "draw a safe corporate illustration",
    hint: "Базовый ALLOW: чистый промпт → детектор пропускает → подписанный паспорт → проверенная выдача.",
  },
  passport: {
    input: "passport-id-edit.png",
    hint: "Demo. PII-эвристика по имени файла (passport) → BLOCK до генератора.",
  },
  bankcard: {
    input: "bank-card-edit.png",
    hint: "Demo. PII-эвристика (card) → BLOCK до генератора.",
  },
  payment: {
    input: "payment-order-edit.png",
    hint: "Demo. PII-эвристика (payment) → BLOCK до генератора.",
  },
  deepfake: {
    generated: "unsafe-exec-deepfake.png",
    hint: "Demo / roadmap. Маркер mock-детектора (unsafe) → BLOCK после карантина. Боевая модель — за рамками MVP.",
  },
  phishing: {
    generated: "unsafe-phishing-banner.png",
    hint: "Demo / roadmap. Маркер mock-детектора (unsafe) → BLOCK после карантина.",
  },
  offline: {
    generated: "detector_error.png",
    hint: "Отказ детектора → fail closed → выдача запрещена. Статус: FAIL CLOSED.",
  },
  tampered: {
    prompt: "draw a safe corporate illustration",
    hint: "Сначала ALLOW + паспорт. Затем локально: printf tampered > data/release/<artifact_id>.png и нажми Скачать → HTTP 409 (HMAC mismatch).",
  },
};

const RISK_CATS = {
  prompt: ["prompt_injection", "jailbreak", "policy_violation"],
  pii: ["pii", "pii_passport", "payment_details", "qr_or_barcode"],
  fraud: ["fraud", "document_forgery", "deepfake"],
  output: ["graphic_violence", "unsafe_content", "detector_error", "nsfw"],
};

// ====== Helpers ======
function pngFile(name) {
  const bytes = Uint8Array.from(atob(transparentPng), ch => ch.charCodeAt(0));
  return new File([bytes], name, { type: "image/png" });
}
function escapeHtml(value) {
  return String(value ?? "—").replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[c]);
}
function updateFileLabels() {
  document.querySelector("#input-file-name").textContent = inputImage.files[0]?.name || presetInputFile?.name || "не выбран";
  document.querySelector("#generated-file-name").textContent = generatedImage.files[0]?.name || presetGeneratedFile?.name || "не выбран";
}
function choosePreset(name) {
  if (!presetConfig[name]) return;
  activePreset = name;
  const preset = presetConfig[name];
  presetInputFile = preset.input ? pngFile(preset.input) : null;
  presetGeneratedFile = preset.generated ? pngFile(preset.generated) : null;
  promptInput.value = preset.prompt || "";
  inputImage.value = "";
  generatedImage.value = "";
  hint.textContent = preset.hint;
  updateFileLabels();
  document.querySelectorAll(".case").forEach(b => b.classList.toggle("active", b.dataset.preset === name));
}

// ====== Pipeline ======
const PIPELINE_STEPS = ["user","prompt","input","generator","quarantine","output","policy","passport","release"];
function setPipelineState(stateMap) {
  document.querySelectorAll(".pipe-node").forEach(n => {
    n.classList.remove("active","done","blocked");
    const s = stateMap[n.dataset.step];
    if (s) n.classList.add(s);
  });
}
function setPipelineStatus(text) { document.querySelector("#pipeline-status").textContent = text; }

async function animatePipeline() {
  setPipelineStatus("ВЫПОЛНЕНИЕ");
  const seq = activePreset === "offline"
    ? ["user","prompt","input","generator","quarantine","output"]
    : ["user","prompt","input","generator","quarantine","output","policy","passport"];
  const state = {};
  for (const step of seq) {
    state[step] = "active";
    setPipelineState({ ...state });
    await new Promise(r => setTimeout(r, 110));
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
  const verdict = payload?.verdict;
  const state = {};
  PIPELINE_STEPS.forEach(s => { state[s] = "done"; });
  if (verdict === "BLOCK") {
    const last = inferBlockStage(payload);
    state[last] = "blocked";
    const idx = PIPELINE_STEPS.indexOf(last);
    PIPELINE_STEPS.slice(idx + 1).forEach(s => { state[s] = ""; });
    setPipelineStatus(activePreset === "offline" ? "FAIL CLOSED" : "ЗАБЛОКИРОВАНО");
  } else if (verdict === "REVIEW") {
    state.policy = "active"; setPipelineStatus("НА РЕВЬЮ");
  } else if (verdict === "ALLOW") {
    state.release = "done"; setPipelineStatus("РАЗРЕШЕНО");
  } else { setPipelineStatus("ОШИБКА"); }
  setPipelineState(state);
}

// ====== Risk ======
function computeRiskScores(payload) {
  const categories = new Set(payload?.categories || []);
  const severity = payload?.severity || null;
  const verdict = payload?.verdict;
  const hit = (g) => RISK_CATS[g].some(c => categories.has(c));
  const sevW = { LOW: 25, MEDIUM: 55, HIGH: 78, CRITICAL: 95 }[severity] || 0;
  const base = verdict === "ALLOW" ? 8 : verdict === "REVIEW" ? 45 : sevW || 70;
  const s = {
    prompt: hit("prompt") ? Math.max(base, 60) : verdict === "ALLOW" ? 6 : 18,
    pii:    hit("pii")    ? Math.max(base, 80) : verdict === "ALLOW" ? 4 : 14,
    fraud:  hit("pii") || hit("output") || activePreset === "tampered" ? Math.max(base, 70) : verdict === "ALLOW" ? 6 : 16,
    output: hit("output") || activePreset === "offline" ? Math.max(base, 75) : verdict === "ALLOW" ? 8 : 20,
  };
  if (["passport","bankcard","payment"].includes(activePreset)) s.fraud = Math.max(s.fraud, 82);
  if (["deepfake","phishing"].includes(activePreset)) s.fraud = Math.max(s.fraud, 78);
  return s;
}
function pctLevel(pct) { if (pct >= 80) return "CRITICAL"; if (pct >= 60) return "HIGH"; if (pct >= 30) return "MEDIUM"; return "LOW"; }

function renderRisk(payload) {
  const scores = computeRiskScores(payload);
  const overall = Math.max(...Object.values(scores));
  const level = pctLevel(overall);
  const levelEl = document.querySelector("#risk-level");
  levelEl.textContent = level;
  levelEl.dataset.level = level;
  const fill = document.querySelector("#risk-bar-fill");
  fill.style.width = `${overall}%`;
  fill.dataset.level = level;

  document.querySelectorAll("#risk-list li").forEach(li => {
    const key = li.dataset.risk;
    const pct = scores[key];
    const lvl = pctLevel(pct);
    const bar = li.querySelector("i > b");
    bar.style.width = `${pct}%`;
    bar.dataset.level = lvl;
    li.querySelector("em").textContent = lvl;
  });
}

// ====== Passport ======
function renderPassport(payload) {
  const p = payload?.passport || {};
  passportEmpty.classList.add("hidden");
  passportKv.classList.remove("hidden");
  document.querySelector("#pp-artifact").textContent = payload.artifact_id || "—";
  document.querySelector("#pp-request").textContent = payload.request_id || "—";
  document.querySelector("#pp-policy").textContent = p.policy_version || "—";
  const dv = p.detector_versions ? Object.entries(p.detector_versions).map(([k,v]) => `${k}=${v}`).join(", ") : "—";
  document.querySelector("#pp-detector").textContent = dv;
  document.querySelector("#pp-sha").textContent = p.sha256 || "—";
  document.querySelector("#pp-decision").textContent = payload.verdict || "—";
  const sig = document.querySelector("#pp-signature");
  const sigState = payload.verdict === "ALLOW" ? "VALID" : payload.verdict === "REVIEW" ? "PENDING" : "N/A";
  sig.textContent = sigState;
  sig.dataset.state = sigState;
  exportButton.disabled = !payload.request_id;
}
function markSignatureInvalid() {
  const sig = document.querySelector("#pp-signature");
  sig.textContent = "INVALID";
  sig.dataset.state = "INVALID";
}

// ====== SOC ======
function renderSoc(payload) {
  const empty = document.querySelector("#soc-empty");
  const card = document.querySelector("#soc-card");
  const status = document.querySelector("#soc-status");
  if (payload.verdict === "ALLOW") {
    empty.classList.remove("hidden"); card.classList.add("hidden"); status.textContent = "НЕТ СОБЫТИЙ";
    return;
  }
  empty.classList.add("hidden"); card.classList.remove("hidden"); status.textContent = "АЛЕРТ";
  const severity = payload.severity || (payload.verdict === "BLOCK" ? "HIGH" : "MEDIUM");
  const sevEl = document.querySelector("#soc-severity");
  sevEl.textContent = severity; sevEl.dataset.sev = severity;
  document.querySelector("#soc-category").textContent = (payload.categories || []).join(", ") || (activePreset === "offline" ? "guardrail_offline" : "policy_violation");
  document.querySelector("#soc-title").textContent = activePreset === "offline" ? "FAIL CLOSED · ЦЕНЗОР НЕДОСТУПЕН" : "SOC ALERT";
  document.querySelector("#soc-event").textContent = `EVT-${(payload.request_id || "demo0001").slice(0, 8)}`;
  document.querySelector("#soc-state").textContent = "OPEN · ожидает аналитика";
  document.querySelector("#soc-time").textContent = new Date().toLocaleTimeString();
  socCount += 1;
  kpiSoc.textContent = String(socCount);
}

// ====== Timeline ======
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
  const t = new Date().toLocaleTimeString();
  const reason = payload.reason || "";
  if (activePreset === "offline" || (payload.categories || []).includes("detector_error")) {
    setTimeline({
      "prompt-received": { state: "done", note: t },
      "input-scan":      { state: "done", note: "чисто" },
      "generator":       { state: "done", note: "выполнено (в карантине)" },
      "output-scan":     { state: "blocked", note: `BLOCK · ${reason || "детектор недоступен"}` },
      "policy":          { state: "blocked", note: "FAIL CLOSED" },
      "download":        { state: "blocked", note: "отклонено" },
    });
    return;
  }
  if (payload.verdict === "ALLOW") {
    setTimeline({
      "prompt-received": { state: "done", note: t },
      "input-scan":      { state: "done", note: "чисто" },
      "generator":       { state: "done", note: "выполнено" },
      "output-scan":     { state: "done", note: "чисто" },
      "policy":          { state: "done", note: "ALLOW" },
      "passport":        { state: "done", note: "подписан (HMAC SHA-256)" },
      "download":        { state: "active", note: "готов · нужен токен" },
    });
    return;
  }
  const stage = inferBlockStage(payload);
  const map = { prompt: "prompt-received", input: "input-scan", output: "output-scan", policy: "policy" };
  const blockedStep = map[stage] || "policy";
  const states = {
    "prompt-received": { state: "done", note: t },
    "input-scan":      { state: "done", note: "проверено" },
    "generator":       { state: "done", note: "выполнено (в карантине)" },
    "output-scan":     { state: "done", note: "проверено" },
    "policy":          { state: "done", note: "оценено" },
    "download":        { state: "blocked", note: "отклонено" },
  };
  states[blockedStep] = { state: "blocked", note: `BLOCK · ${reason || stage}` };
  const order = ["prompt-received","input-scan","generator","output-scan","policy","passport","download"];
  const idx = order.indexOf(blockedStep);
  order.slice(idx + 1, order.length - 1).forEach(s => { delete states[s]; });
  setTimeline(states);
}

// ====== Decision render ======
function chipsHtml(items) {
  const values = items?.length ? items : ["no_categories"];
  return values.map(item => `<span class="chip">${escapeHtml(item)}</span>`).join("");
}

function resetUiState() {
  emptyState.classList.add("hidden");
  result.classList.remove("hidden");
  document.querySelector("#verdict-text").textContent = "…";
  document.querySelector("#verdict-text").dataset.v = "";
  document.querySelector("#verdict-reason").textContent = "";
  document.querySelector("#verdict-chips").innerHTML = "";
  document.querySelector("#decision-actions").innerHTML = "";
  decisionMeta.textContent = "ВЫПОЛНЕНИЕ";
}

function showPayload(payload) {
  lastPayload = payload;
  emptyState.classList.add("hidden");
  result.classList.remove("hidden");

  const offline = activePreset === "offline" || (payload.categories || []).includes("detector_error");
  const verdictDisplay = offline ? "FAIL CLOSED" : payload.verdict;
  const verdictKey = offline ? "OFFLINE" : payload.verdict;

  const verdictEl = document.querySelector("#verdict-text");
  verdictEl.textContent = verdictDisplay;
  verdictEl.dataset.v = verdictKey;

  document.querySelector("#verdict-reason").textContent = payload.reason || "—";
  document.querySelector("#verdict-chips").innerHTML = chipsHtml(payload.categories);

  decisionMeta.textContent = offline ? "FAIL CLOSED" : verdictDisplay;

  const actions = document.querySelector("#decision-actions");
  actions.innerHTML = "";
  if (offline) {
    actions.innerHTML = `<div class="offline-block">
      <p style="margin:0 0 4px;"><b>Цензор недоступен.</b> Генерация завершена в карантине.</p>
      <p style="margin:0;">Выдача запрещена. Статус системы: <b>FAIL CLOSED</b>.</p>
    </div>`;
  } else if (payload.verdict === "ALLOW" && payload.artifact_id) {
    const btn = document.createElement("button");
    btn.className = "download"; btn.type = "button";
    btn.textContent = "Скачать проверенный артефакт";
    btn.addEventListener("click", () => downloadArtifact(payload.artifact_id));
    actions.appendChild(btn);
    if (activePreset === "tampered") {
      const note = document.createElement("p");
      note.className = "download-note";
      note.innerHTML = `Перед скачиванием подмени файл локально:<br><code>printf tampered &gt; data/release/${escapeHtml(payload.artifact_id)}.png</code>`;
      actions.appendChild(note);
    }
  }

  // counters
  if (payload.verdict === "BLOCK") { blockedCount += 1; kpiBlocked.textContent = String(blockedCount); }
  if (payload.verdict === "REVIEW") { reviewCount += 1; kpiReview.textContent = String(reviewCount); }

  finalizePipeline(payload);
  renderRisk(payload);
  renderPassport(payload);
  renderSoc(payload);
  renderTimeline(payload);
}

function showError(message) {
  emptyState.classList.add("hidden");
  result.classList.remove("hidden");
  const v = document.querySelector("#verdict-text");
  v.textContent = "ERROR"; v.dataset.v = "ERROR";
  document.querySelector("#verdict-reason").textContent = message;
  document.querySelector("#verdict-chips").innerHTML = "";
  document.querySelector("#decision-actions").innerHTML = "";
  decisionMeta.textContent = "ОШИБКА";
  setPipelineStatus("ОШИБКА");
}

// ====== Download ======
async function downloadArtifact(artifactId) {
  const token = tokenInput.value.trim();
  if (!token) { showError("Введите токен загрузки для проверенной выдачи."); return; }
  try {
    const response = await fetch(`/v1/download/${encodeURIComponent(artifactId)}`, { headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      if (response.status === 409) {
        markSignatureInvalid();
        renderTimeline({ verdict: "BLOCK", reason: "HMAC mismatch на релизе", categories: ["integrity_violation"] });
        const dl = document.querySelector("#timeline li[data-step='download'] em");
        if (dl) dl.textContent = "HTTP 409 · подмена";
      }
      showError(`Загрузка отклонена: HTTP ${response.status}. ${payload.detail || "Неизвестная ошибка"}`);
      return;
    }
    const blob = await response.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${artifactId}.png`;
    link.click();
    URL.revokeObjectURL(link.href);
    const dlLi = document.querySelector("#timeline li[data-step='download']");
    if (dlLi) {
      dlLi.classList.remove("blocked","active");
      dlLi.classList.add("done");
      dlLi.querySelector("em").textContent = "проверено · HTTP 200";
    }
  } catch (error) {
    showError(`Сбой загрузки: ${error.message}`);
  }
}

// ====== Export passport JSON ======
exportButton.addEventListener("click", () => {
  if (!lastPayload) return;
  const blob = new Blob([JSON.stringify(lastPayload, null, 2)], { type: "application/json" });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `safety-passport-${lastPayload.request_id || "demo"}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
});

// ====== Tabs ======
document.querySelectorAll(".tab").forEach(tab => tab.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach(t => {
    t.classList.toggle("active", t === tab);
    t.setAttribute("aria-selected", t === tab ? "true" : "false");
  });
  const target = tab.dataset.tab;
  document.querySelectorAll(".case-grid").forEach(grid => grid.classList.toggle("hidden", grid.dataset.pane !== target));
}));

// ====== Submit ======
form.addEventListener("submit", async event => {
  event.preventDefault();
  submitButton.disabled = true;
  submitButton.textContent = "Проверяем…";

  resetUiState();
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
  } catch (error) {
    showError(error.message);
  } finally {
    submitButton.disabled = false;
    submitButton.innerHTML = "Запустить проверку <b>→</b>";
  }
});

// ====== Wire up ======
document.querySelectorAll(".case").forEach(b => b.addEventListener("click", () => choosePreset(b.dataset.preset)));
inputImage.addEventListener("change", () => { presetInputFile = null; updateFileLabels(); });
generatedImage.addEventListener("change", () => { presetGeneratedFile = null; updateFileLabels(); });
choosePreset("passport");
setPipelineState({ user: "done" });
setPipelineStatus("ОЖИДАНИЕ");
