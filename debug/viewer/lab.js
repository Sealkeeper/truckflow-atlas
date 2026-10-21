const state = { modelId: null, sampleKey: "north_600", data: null };

const $ = (selector) => document.querySelector(selector);

const formatTime = (seconds) => {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return [h, m, s].map((value) => String(value).padStart(2, "0")).join(":");
};

const cameraName = (camera) => (camera === "north" ? "天花北" : "天花南");

function currentModel() {
  return state.data.models.find((model) => model.id === state.modelId);
}

function currentResult() {
  const model = currentModel();
  return model.results.find((result) => result.key === state.sampleKey) || model.results[0];
}

function renderMetrics() {
  const model = currentModel();
  const metrics = model.metrics;
  $("#metricExact").textContent = String(metrics.exact);
  $("#metricExactRate").textContent = `/ ${metrics.graded} · ${metrics.exactRate}%`;
  $("#metricGraded").textContent = `已评分 ${metrics.graded} 帧 · 共 ${metrics.total} 帧`;
  $("#metricMae").textContent = metrics.mae === null ? "–" : metrics.mae.toFixed(2);
  $("#metricMissing").textContent = String(metrics.missing);
  $("#metricExtra").textContent = String(metrics.extra);
  $("#metricFailed").textContent = String(metrics.failed);
  $("#modelTitle").textContent = model.label;
  $("#modelDetail").textContent = model.detail;
}

function renderModels() {
  const root = $("#modelList");
  root.textContent = "";
  for (const model of state.data.models) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "model-button";
    button.role = "tab";
    button.classList.toggle("is-active", model.id === state.modelId);
    button.setAttribute("aria-selected", String(model.id === state.modelId));
    const metrics = model.metrics;
    const summary = `${metrics.exact}/${metrics.graded}`;
    button.innerHTML = `<span>${model.short}</span><span>${summary}</span>`;
    button.title = model.label;
    button.addEventListener("click", () => {
      state.modelId = model.id;
      state.sampleKey = model.results.some((result) => result.key === state.sampleKey)
        ? state.sampleKey
        : model.results[0].key;
      renderAll();
    });
    root.append(button);
  }
}

function statusClass(result) {
  if (!result.ok) return "is-fail";
  if (result.delta === 0) return "is-exact";
  if (result.delta < 0) return "is-miss";
  return "is-extra";
}

function renderSamples() {
  const model = currentModel();
  const root = $("#sampleGrid");
  root.textContent = "";
  for (const result of model.results) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `sample-button ${statusClass(result)}`;
    button.classList.toggle("is-active", result.key === state.sampleKey);
    button.setAttribute("aria-pressed", String(result.key === state.sampleKey));
    const predicted = result.ok ? result.count : "×";
    const side = result.camera === "north" ? "北" : "南";
    button.innerHTML = `<span class="s-time">${side} ${formatTime(result.time).slice(3)}</span><span class="s-count">${predicted}/${result.gold}</span>`;
    button.setAttribute(
      "aria-label",
      `${cameraName(result.camera)} ${formatTime(result.time)} 预测 ${predicted} 人工 ${result.gold}`
    );
    button.addEventListener("click", () => {
      state.sampleKey = result.key;
      renderAll();
    });
    root.append(button);
  }
  $("#sampleCount").textContent = String(model.results.length);
}

function renderBoxes(result) {
  const layer = $("#boxLayer");
  layer.textContent = "";
  const boxes = (result.boxes || []).filter((box) => box.bbox.every((value) => Number.isFinite(value)));
  for (const [index, box] of boxes.entries()) {
    const [x1, y1, x2, y2] = box.bbox.map((value) => Math.max(0, Math.min(1, value)));
    const node = document.createElement("div");
    node.className = `vehicle-box${box.uncertain ? " is-uncertain" : ""}`;
    node.style.left = `${x1 * 100}%`;
    node.style.top = `${y1 * 100}%`;
    node.style.width = `${Math.max(0.4, (x2 - x1) * 100)}%`;
    node.style.height = `${Math.max(0.4, (y2 - y1) * 100)}%`;
    node.title = box.identity || box.evidence || "";
    const badge = document.createElement("span");
    badge.className = "box-id";
    badge.textContent = String(box.sequence ?? index + 1);
    node.append(badge);
    layer.append(node);
  }
  return boxes;
}

function renderBoxList(boxes) {
  const root = $("#boxList");
  root.textContent = "";
  if (!boxes.length) {
    const empty = document.createElement("span");
    empty.className = "box-empty";
    empty.textContent = "该模型未返回可用框；只展示计数，不补画位置。";
    root.append(empty);
    return;
  }
  for (const box of boxes) {
    const chip = document.createElement("span");
    chip.className = `box-chip${box.uncertain ? " is-uncertain" : ""}`;
    chip.textContent = `#${box.sequence} ${box.size}${box.visible === "trailer_only" ? " · 仅货厢" : ""}`;
    chip.title = box.identity || "";
    root.append(chip);
  }
}

function renderCompare(result) {
  const root = $("#compare");
  root.textContent = "";
  let rows = 0;
  for (const model of state.data.models) {
    const other = model.results.find((item) => item.key === result.key);
    if (!other) continue;
    rows += 1;
    const row = document.createElement("div");
    row.className = "compare-row";
    if (!other.ok) {
      row.classList.add("is-fail");
      row.innerHTML = `<span>${model.short}</span><strong>失败</strong>`;
    } else {
      row.classList.add(other.delta === 0 ? "is-exact" : other.delta < 0 ? "is-miss" : "is-extra");
      if (other.delta === 0) row.classList.add("is-best");
      const deltaText = other.delta === 0 ? "一致" : other.delta > 0 ? `多 ${other.delta}` : `漏 ${-other.delta}`;
      row.innerHTML = `<span>${model.short}</span><strong>${other.count} 辆 · ${deltaText}</strong>`;
    }
    root.append(row);
  }
  $("#compareFoot").textContent = rows
    ? `同一帧、不同提示词/模型的实测结果；AI 初标 ${result.gold} 辆。`
    : "该样本暂无其他模型对照。";
}

function renderDetail() {
  const result = currentResult();
  $("#stageCamera").textContent = cameraName(result.camera);
  $("#stageTime").textContent = formatTime(result.time);
  $("#stageKey").textContent = result.key;

  const image = $("#frameImage");
  image.src = `/assets/frames/${result.camera}_${result.time}.jpg`;
  image.alt = `${cameraName(result.camera)} ${formatTime(result.time)} 真实画面`;

  const boxes = renderBoxes(result);
  $("#frameCaptionBoxes").textContent = result.ok
    ? `${boxes.length} 个候选框${result.uncertainCount ? ` · ${result.uncertainCount} 个存疑` : ""}`
    : "无结果";
  $("#boxSource").textContent = boxes.length ? "真实候选框" : "无可用框";
  $("#boxSource").classList.toggle("mode-muted", boxes.length === 0);
  $("#promptChip").textContent = result.promptVersion || "整帧基线提示词";

  $("#predCount").textContent = result.ok ? String(result.count) : "×";
  $("#goldCount").textContent = String(result.gold);
  const deltaCell = $("#deltaCell");
  const note = $("#verdictNote");
  deltaCell.classList.toggle("is-exact", result.ok && result.delta === 0);
  note.className = "verdict-note";
  if (!result.ok) {
    $("#deltaValue").textContent = "–";
    note.classList.add("is-fail");
    note.textContent = `本帧接口失败，不计入准确率分母：${result.error || "未知错误"}`;
  } else {
    const delta = result.delta;
    $("#deltaValue").textContent = delta > 0 ? `+${delta}` : String(delta);
    if (delta === 0) {
      note.classList.add("is-exact");
      note.textContent = "与 AI 初标完全一致。框位置仅供核对，本轮不计算 IoU。";
    } else if (delta < 0) {
      note.textContent = `漏计 ${-delta} 辆。优先检查远端小目标与相邻货厢是否被合并。`;
    } else {
      note.textContent = `多计 ${delta} 辆。优先检查同一牵引车/挂车是否被拆成两个候选。`;
    }
  }

  $("#sceneNotes").textContent = result.ok
    ? result.notes || "模型未返回场景说明。"
    : `失败信息：${result.error || "未知错误"}`;
  renderBoxList(boxes);
  renderCompare(result);

  const metaBits = [];
  if (result.modelId) metaBits.push(result.modelId);
  if (result.latency !== null && result.latency !== undefined) metaBits.push(`${result.latency.toFixed(1)} 秒`);
  if (result.attempts) metaBits.push(`尝试 ${result.attempts} 次`);
  $("#stageKey").title = metaBits.join(" · ");
  $("#generatedAt").textContent = `数据生成 ${state.data.generatedAtLocal}`;

  const aibox = state.data.models.find((model) => model.id === "aibox-v2");
  const aiboxRow = aibox?.results.find((item) => item.key === state.sampleKey);
  const baseRow = state.data.models[0].results.find((item) => item.key === state.sampleKey);
  const finding = $("#findingText");
  if (state.sampleKey === "north_600" && aiboxRow?.ok && baseRow?.ok) {
    finding.textContent =
      `AI 初标 4 辆。整帧基线只找到 ${baseRow.count} 辆，Aibox 本轮为 ${aiboxRow.count} 辆。` +
      "Aibox 曾在单次实验返回 4，但全量 20 帧只有 10/20 与初标一致、9 帧多计，故该单次结果不可复现，不能升为主力。";
  } else if (state.sampleKey === "south_300" && aiboxRow?.ok && baseRow?.ok) {
    finding.textContent =
      `AI 初标 4 辆。整帧基线 ${baseRow.count} 辆，Aibox ${aiboxRow.count} 辆。` +
      "近景多计是 Aibox 的系统性问题，复核时必须检查画面底边与相邻车体是否被拆成两辆。";
  } else {
    finding.textContent =
      `当前模型在 ${result.key} 上预测 ${result.ok ? result.count : "失败"} 辆，AI 初标 ${result.gold} 辆。` +
      "差值可直接定位漏计与多计，最终以人工复核为准。";
  }
}

function renderAll() {
  renderMetrics();
  renderModels();
  renderSamples();
  renderDetail();
}

async function boot() {
  const response = await fetch("./lab-data.json", { cache: "no-store" });
  if (!response.ok) throw new Error(`lab-data.json 加载失败：${response.status}`);
  state.data = await response.json();
  state.modelId = state.data.models[0].id;
  const baseline = state.data.models[0].results;
  if (!baseline.some((result) => result.key === state.sampleKey)) {
    state.sampleKey = baseline[0].key;
  }
  $("#modelCount").textContent = String(state.data.models.length);
  renderAll();
}

boot().catch((error) => {
  document.body.innerHTML = `<pre style="padding:24px;color:#ff8f9c">${error.message}</pre>`;
});
