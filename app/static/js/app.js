const state = {
  file: null,
  previewUrl: null,
  busy: false,
};

const elements = {
  dropzone: document.querySelector("#dropzone"),
  fileInput: document.querySelector("#fileInput"),
  previewCard: document.querySelector("#previewCard"),
  previewImage: document.querySelector("#previewImage"),
  fileName: document.querySelector("#fileName"),
  fileSize: document.querySelector("#fileSize"),
  fullCheckButton: document.querySelector("#fullCheckButton"),
  llamaOnlyButton: document.querySelector("#llamaOnlyButton"),
  resetButton: document.querySelector("#resetButton"),
  statusBadge: document.querySelector("#statusBadge"),
  verdictHeadline: document.querySelector("#verdictHeadline"),
  verdictMessage: document.querySelector("#verdictMessage"),
  reasonLine: document.querySelector("#reasonLine"),
  timeline: document.querySelector("#timeline"),
  ocrStatus: document.querySelector("#ocrStatus"),
  ocrText: document.querySelector("#ocrText"),
  suspiciousStatus: document.querySelector("#suspiciousStatus"),
  suspiciousDetails: document.querySelector("#suspiciousDetails"),
  llamaStatus: document.querySelector("#llamaStatus"),
  llamaDetails: document.querySelector("#llamaDetails"),
  rawJson: document.querySelector("#rawJson"),
};

function formatFileSize(bytes) {
  if (!bytes) return "0 KB";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function setBusy(isBusy) {
  state.busy = isBusy;
  elements.fullCheckButton.disabled = isBusy || !state.file;
  elements.llamaOnlyButton.disabled = isBusy || !state.file;
  elements.resetButton.disabled = isBusy;
}

function setStatus(status, label) {
  elements.statusBadge.className = `status-badge ${status}`;
  elements.statusBadge.textContent = label;
}

function resetTimeline() {
  elements.timeline.querySelectorAll("li").forEach((item) => {
    item.className = "";
  });
}

function markStep(step, status) {
  const item = elements.timeline.querySelector(`[data-step="${step}"]`);
  if (item) item.className = status;
}

function setLoading(mode) {
  setBusy(true);
  setStatus("loading", "Проверка");
  elements.verdictHeadline.textContent = "Изображение анализируется...";
  elements.verdictMessage.textContent = mode === "direct"
    ? "Отправляем изображение напрямую в Llama Guard."
    : "Запускаем полный пайплайн модерации.";
  elements.reasonLine.textContent = "";
  resetTimeline();
  markStep("validation", "running");
  if (mode === "direct") {
    markStep("llama", "running");
  } else {
    markStep("suspicious", "running");
    markStep("ocr", "running");
    markStep("llama", "running");
  }
}

function setSelectedFile(file) {
  if (!file) return;

  if (!file.type.startsWith("image/")) {
    showClientError("Можно проверять только файлы изображений.");
    return;
  }

  state.file = file;
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.previewUrl = URL.createObjectURL(file);

  elements.previewImage.src = state.previewUrl;
  elements.previewCard.hidden = false;
  elements.fileName.textContent = file.name;
  elements.fileSize.textContent = formatFileSize(file.size);
  setBusy(false);
}

function resetUi() {
  state.file = null;
  if (state.previewUrl) URL.revokeObjectURL(state.previewUrl);
  state.previewUrl = null;

  elements.fileInput.value = "";
  elements.previewImage.removeAttribute("src");
  elements.previewCard.hidden = true;
  elements.fileName.textContent = "Файл не выбран";
  elements.fileSize.textContent = "0 KB";
  setStatus("idle", "Ожидание");
  elements.verdictHeadline.textContent = "Загрузите изображение, чтобы начать проверку.";
  elements.verdictMessage.textContent = "Консоль покажет итоговый вердикт, OCR-текст и диагностические данные модели.";
  elements.reasonLine.textContent = "";
  elements.ocrStatus.textContent = "Не проверено";
  elements.ocrText.textContent = "OCR-текста пока нет.";
  elements.suspiciousStatus.textContent = "Не проверено";
  elements.suspiciousDetails.innerHTML = "";
  elements.llamaStatus.textContent = "Не проверено";
  elements.llamaDetails.innerHTML = "";
  elements.rawJson.textContent = "{}";
  resetTimeline();
  setBusy(false);
}

function showClientError(message) {
  setStatus("error", "Ошибка");
  elements.verdictHeadline.textContent = "Запрос не отправлен";
  elements.verdictMessage.textContent = message;
  elements.reasonLine.textContent = "";
}

function createKv(label, value) {
  const row = document.createElement("div");
  row.className = "kv";
  const key = document.createElement("strong");
  key.textContent = label;
  const val = document.createElement("span");
  val.textContent = value ?? "Нет данных";
  row.append(key, val);
  return row;
}

function renderKeyValues(container, entries) {
  container.innerHTML = "";
  entries.forEach(([label, value]) => {
    container.appendChild(createKv(label, typeof value === "object" ? JSON.stringify(value) : value));
  });
}

function humanReason(reason, fallback) {
  const map = {
    suspicious_perturbation_detected: "Обнаружены подозрительные perturbation-like паттерны.",
    unsafe_content_detected: "Llama Guard классифицировал изображение как небезопасное.",
    llama_guard_failed: "Проверка Llama Guard не выполнилась, поэтому изображение отклонено по умолчанию.",
  };
  return map[reason] || fallback || "";
}

function getAnalysis(response) {
  return response.analysis || {
    suspicious_perturbation: null,
    ocr: null,
    llama_guard: response.llama_guard || null,
  };
}

function renderOcr(ocr) {
  if (!ocr) {
    elements.ocrStatus.textContent = "Пропущено";
    elements.ocrText.textContent = "OCR не запускался для этого запроса.";
    return;
  }

  elements.ocrStatus.textContent = ocr.has_text ? "Текст найден" : "Текста нет";
  elements.ocrText.textContent = ocr.text || ocr.error || "OCR-текст не найден.";
}

function renderSuspicious(details) {
  if (!details) {
    elements.suspiciousStatus.textContent = "Пропущено";
    elements.suspiciousDetails.innerHTML = "";
    return;
  }

  elements.suspiciousStatus.textContent = details.is_suspicious ? "Подозрительно" : "Чисто";
  renderKeyValues(elements.suspiciousDetails, [
    ["Подозрительно", String(details.is_suspicious)],
    ["Score", details.score],
    ["Порог", details.threshold],
    ["Метод", details.method],
    ["Пояснение", details.explanation],
    ["Признаки", details.features || {}],
  ]);
}

function renderLlama(details) {
  if (!details) {
    elements.llamaStatus.textContent = "Пропущено";
    elements.llamaDetails.innerHTML = "";
    return;
  }

  elements.llamaStatus.textContent = details.is_safe ? "Безопасно" : details.verdict || "Небезопасно";
  renderKeyValues(elements.llamaDetails, [
    ["Безопасно", String(details.is_safe)],
    ["Вердикт", details.verdict],
    ["Причина", details.reason],
    ["Детали причин", details.unsafe_reason_details || []],
    ["Провайдер", details.provider],
    ["Модель", details.model],
    ["Raw", details.raw_response],
  ]);
}

function renderTimeline(response, mode) {
  resetTimeline();
  markStep("validation", "done");

  const analysis = getAnalysis(response);
  if (mode === "direct") {
    markStep("suspicious", "");
    markStep("ocr", "");
    markStep("llama", analysis.llama_guard?.is_safe ? "done" : "failed");
    markStep("final", analysis.llama_guard?.is_safe ? "done" : "failed");
    return;
  }

  markStep("suspicious", analysis.suspicious_perturbation?.is_suspicious ? "failed" : "done");
  markStep("ocr", analysis.ocr ? "done" : "");
  markStep("llama", analysis.llama_guard ? (analysis.llama_guard.is_safe ? "done" : "failed") : "");
  markStep("final", response.status === "success" ? "done" : "failed");
}

function renderResponse(response, mode) {
  const analysis = getAnalysis(response);
  const isSuccess = mode === "direct"
    ? response.llama_guard?.is_safe === true
    : response.status === "success";
  const isRejected = mode === "direct"
    ? response.llama_guard?.is_safe === false
    : response.status === "rejected";

  setStatus(isSuccess ? "success" : isRejected ? "rejected" : "error", isSuccess ? "Одобрено" : "Отклонено");
  elements.verdictHeadline.textContent = isSuccess ? "Изображение одобрено" : "Изображение отклонено";
  elements.verdictMessage.textContent = isSuccess
    ? "Изображение прошло настроенные проверки безопасности и может использоваться."
    : humanReason(response.reason, response.message || response.llama_guard?.reason);
  elements.reasonLine.textContent = response.reason ? `Причина: ${response.reason}` : "";

  renderTimeline(response, mode);
  renderOcr(analysis.ocr);
  renderSuspicious(analysis.suspicious_perturbation);
  renderLlama(analysis.llama_guard);
  elements.rawJson.textContent = JSON.stringify(response, null, 2);
}

async function submit(endpoint, mode) {
  if (!state.file) {
    showClientError("Выберите изображение перед запуском проверки.");
    return;
  }

  if (!state.file.type.startsWith("image/")) {
    showClientError("Можно проверять только файлы изображений.");
    return;
  }

  setLoading(mode);
  const formData = new FormData();
  formData.append("file", state.file);

  try {
    const response = await fetch(endpoint, {
      method: "POST",
      body: formData,
    });
    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.detail || `Запрос завершился ошибкой HTTP ${response.status}`);
    }

    renderResponse(data, mode);
  } catch (error) {
    setStatus("error", "Ошибка");
    elements.verdictHeadline.textContent = "Проверка не выполнена";
    elements.verdictMessage.textContent = error.message || "Неожиданная сетевая ошибка.";
    elements.reasonLine.textContent = "";
    markStep("final", "failed");
  } finally {
    setBusy(false);
  }
}

elements.dropzone.addEventListener("dragover", (event) => {
  event.preventDefault();
  elements.dropzone.classList.add("drag-active");
});

elements.dropzone.addEventListener("dragleave", () => {
  elements.dropzone.classList.remove("drag-active");
});

elements.dropzone.addEventListener("drop", (event) => {
  event.preventDefault();
  elements.dropzone.classList.remove("drag-active");
  setSelectedFile(event.dataTransfer.files[0]);
});

elements.fileInput.addEventListener("change", (event) => {
  setSelectedFile(event.target.files[0]);
});

elements.fullCheckButton.addEventListener("click", () => {
  submit("/upload-image", "full");
});

elements.llamaOnlyButton.addEventListener("click", () => {
  submit("/llama-guard/check-image", "direct");
});

elements.resetButton.addEventListener("click", resetUi);

resetUi();
