const form = document.querySelector("#moderation-form");
const promptInput = document.querySelector("#prompt");
const inputImage = document.querySelector("#input-image");
const generatedImage = document.querySelector("#generated-image");
const tokenInput = document.querySelector("#token");
const submitButton = document.querySelector("#submit-button");
const result = document.querySelector("#result");
const emptyState = document.querySelector("#empty-state");
const hint = document.querySelector("#preset-hint");

let activePreset = "safe";
let presetInputFile = null;
let presetGeneratedFile = null;

const transparentPng = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=";
const presetConfig = {
  safe: { prompt: "draw a safe corporate illustration", hint: "Safe prompt → ALLOW → signed Safety Passport → verified download." },
  unsafe: { generated: "unsafe-violence.png", hint: "Existing mock marker in generated filename → BLOCK after quarantine." },
  pii: { input: "passport-card.png", hint: "Existing PII heuristic in input filename → BLOCK before generation and release." },
  failure: { generated: "detector_error.png", hint: "Existing mock detector error marker → fail closed → BLOCK." },
  tampered: { prompt: "draw a safe corporate illustration", hint: "Create ALLOW, then tamper data/release/<artifact_id>.png locally and press Download → HTTP 409." },
};

function pngFile(name) {
  const bytes = Uint8Array.from(atob(transparentPng), character => character.charCodeAt(0));
  return new File([bytes], name, { type: "image/png" });
}

function choosePreset(name) {
  activePreset = name;
  const preset = presetConfig[name];
  presetInputFile = preset.input ? pngFile(preset.input) : null;
  presetGeneratedFile = preset.generated ? pngFile(preset.generated) : null;
  promptInput.value = preset.prompt || "";
  inputImage.value = "";
  generatedImage.value = "";
  hint.textContent = preset.hint;
  updateFileLabels();
  document.querySelectorAll(".preset").forEach(button => button.classList.toggle("active", button.dataset.preset === name));
}

function updateFileLabels() {
  document.querySelector("#input-file-name").textContent = inputImage.files[0]?.name || presetInputFile?.name || "не выбран";
  document.querySelector("#generated-file-name").textContent = generatedImage.files[0]?.name || presetGeneratedFile?.name || "не выбран";
}

function escapeHtml(value) {
  return String(value ?? "—").replace(/[&<>"']/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;" })[character]);
}

function chips(items) {
  const values = items?.length ? items : ["no_categories"];
  return values.map(item => `<span class="chip">${escapeHtml(item)}</span>`).join("");
}

function detailsRow(label, value) {
  return `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`;
}

function showPayload(payload) {
  emptyState.classList.add("hidden");
  result.classList.remove("hidden");
  const passport = payload.passport || {};
  const detectorVersions = passport.detector_versions ? JSON.stringify(passport.detector_versions) : "—";
  const canDownload = payload.verdict === "ALLOW" && payload.artifact_id;
  const tamperedNote = activePreset === "tampered" && canDownload
    ? `<p class="download-note">Перед Download измените локальный файл:<br><code>printf tampered &gt; data/release/${escapeHtml(payload.artifact_id)}.png</code></p>`
    : "";
  result.innerHTML = `
    <h3 class="verdict ${escapeHtml(payload.verdict)}">${escapeHtml(payload.verdict)}</h3>
    <p class="reason">${escapeHtml(payload.reason)}</p>
    <div class="chips">${chips(payload.categories)}</div>
    <dl class="details">
      ${detailsRow("Severity", payload.severity)}
      ${detailsRow("Request ID", payload.request_id)}
      ${detailsRow("Artifact ID", payload.artifact_id)}
      ${detailsRow("Passport SHA-256", passport.sha256)}
      ${detailsRow("Policy version", passport.policy_version)}
      ${detailsRow("Detector versions", detectorVersions)}
    </dl>
    ${canDownload ? '<button class="download" id="download-button" type="button">Download verified artifact</button>' : ""}
    ${tamperedNote}
  `;
  document.querySelector("#download-button")?.addEventListener("click", () => downloadArtifact(payload.artifact_id));
}

function showError(message) {
  emptyState.classList.add("hidden");
  result.classList.remove("hidden");
  result.innerHTML = `<h3 class="verdict error">ERROR</h3><p class="reason">${escapeHtml(message)}</p>`;
}

async function downloadArtifact(artifactId) {
  const token = tokenInput.value.trim();
  if (!token) {
    showError("Введите Demo token для verified download.");
    return;
  }
  try {
    const response = await fetch(`/v1/download/${encodeURIComponent(artifactId)}`, { headers: { Authorization: `Bearer ${token}` } });
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}));
      showError(`Download denied: HTTP ${response.status}. ${payload.detail || "Unknown error"}`);
      return;
    }
    const blob = await response.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `${artifactId}.png`;
    link.click();
    URL.revokeObjectURL(link.href);
  } catch (error) {
    showError(`Download failed: ${error.message}`);
  }
}

form.addEventListener("submit", async event => {
  event.preventDefault();
  submitButton.disabled = true;
  submitButton.textContent = "Проверяем...";
  const body = new FormData();
  if (promptInput.value.trim()) body.append("prompt", promptInput.value.trim());
  const actualInput = inputImage.files[0] || presetInputFile;
  const actualGenerated = generatedImage.files[0] || presetGeneratedFile;
  if (actualInput) body.append("input_image", actualInput, actualInput.name);
  if (actualGenerated) body.append("generated_image", actualGenerated, actualGenerated.name);
  try {
    const response = await fetch("/v1/moderate", { method: "POST", body });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(`HTTP ${response.status}. ${payload.detail || "Moderation request failed"}`);
    showPayload(payload);
  } catch (error) {
    showError(error.message);
  } finally {
    submitButton.disabled = false;
    submitButton.innerHTML = "Проверить изображение <b>→</b>";
  }
});

document.querySelectorAll(".preset").forEach(button => button.addEventListener("click", () => choosePreset(button.dataset.preset)));
inputImage.addEventListener("change", () => { presetInputFile = null; updateFileLabels(); });
generatedImage.addEventListener("change", () => { presetGeneratedFile = null; updateFileLabels(); });
choosePreset("safe");
