(function () {
  "use strict";

  const REVIEW_KEY = "truckflow.workspace.review.v2";
  const REVIEW_DATA_URL = "review/review-data.json";
  const OFFSETS = [-2, -1, 0, 1, 2];

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const dialog = $("#reviewDialog");
  const evidenceDialog = $("#reviewEvidenceDialog");
  if (!dialog || !evidenceDialog) return;

  const ctx = window.TRUCKFLOW_REVIEW_CONTEXT;
  if (!ctx) return;

  const el = {
    form: $("#reviewForm"),
    videoTime: $("#reviewVideoTime"),
    sampleMeta: $("#reviewSampleMeta"),
    draftState: $("#reviewDraftState"),
    prevBtn: $("#reviewPrevBtn"),
    nextBtn: $("#reviewNextBtn"),
    southCrop: $("#reviewSouthCrop"),
    northCrop: $("#reviewNorthCrop"),
    southCaption: $("#reviewSouthCaption"),
    northCaption: $("#reviewNorthCaption"),
    southCount: $("#reviewSouthCount"),
    northCount: $("#reviewNorthCount"),
    overlapCount: $("#reviewOverlapCount"),
    totalCount: $("#reviewTotalCount"),
    southNote: $("#reviewSouthNote"),
    northNote: $("#reviewNorthNote"),
    overlapNote: $("#reviewOverlapNote"),
    totalNote: $("#reviewTotalNote"),
    generalNote: $("#reviewGeneralNote"),
    totalMode: $("#reviewTotalMode"),
    formula: $("#reviewFormula"),
    formulaWarning: $("#reviewFormulaWarning"),
    formulaReset: $("#reviewFormulaReset"),
    saveNote: $("#reviewSaveNote"),
    attachmentInput: $("#reviewAttachmentInput"),
    attachmentBtn: $("#reviewAttachmentBtn"),
    attachmentPreview: $("#reviewAttachmentPreview"),
    attachmentImage: $("#reviewAttachmentImage"),
    attachmentName: $("#reviewAttachmentName"),
    attachmentRemove: $("#reviewAttachmentRemove"),
    dropzone: $("#reviewDropzone"),
    evidenceBody: $("#reviewEvidenceBody")
  };

  const state = {
    reviewData: null,
    records: readStorage(REVIEW_KEY, {}),
    currentTime: null,
    record: null,
    attachmentPreviews: new Map(),
    dataPromise: null
  };

  function readStorage(key, fallback) {
    try {
      const raw = window.localStorage.getItem(key);
      return raw ? JSON.parse(raw) : fallback;
    } catch (_error) {
      return fallback;
    }
  }

  function writeStorage(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch (_error) {
      showToast("浏览器阻止了本地存储；本次复核只保留在当前页面。", true);
      return false;
    }
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
      "'": "&#39;"
    }[character]));
  }

  function showToast(message, isError = false) {
    const stack = $("#toastStack");
    if (!stack) return;
    const node = document.createElement("div");
    node.className = `toast${isError ? " is-error" : ""}`;
    node.textContent = message;
    stack.appendChild(node);
    window.setTimeout(() => node.remove(), 3600);
  }

  function blankRecord(time) {
    return {
      sample_key: `t${time}`,
      time,
      video_time: ctx.formatVideoTime(time),
      south: null,
      north: null,
      overlap: null,
      total: null,
      total_source: "auto",
      notes: { south: "", north: "", overlap: "", total: "", general: "" },
      attachment: null,
      status: "draft",
      completed: false,
      formula_mismatch: false,
      saved_at: null,
      reviewed_at: null
    };
  }

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function recordFor(time) {
    const stored = state.records[String(time)];
    return stored ? { ...blankRecord(time), ...clone(stored), notes: { ...blankRecord(time).notes, ...(stored.notes || {}) } } : blankRecord(time);
  }

  function hasAnyContent(record) {
    return ["south", "north", "overlap", "total"].some((key) => Number.isInteger(record[key]))
      || Object.values(record.notes || {}).some((value) => String(value || "").trim())
      || Boolean(record.attachment?.name);
  }

  function recordCount() {
    return Object.values(state.records).filter(hasAnyContent).length;
  }

  function parseCount(input) {
    if (!input || input.value.trim() === "") return null;
    const value = Number(input.value);
    if (!Number.isFinite(value) || value < 0) return null;
    return Math.min(99, Math.round(value));
  }

  function formulaTotal(record) {
    if (![record.south, record.north, record.overlap].every(Number.isInteger)) return null;
    return Math.max(0, record.south + record.north - record.overlap);
  }

  function isComplete(record) {
    return [record.south, record.north, record.overlap, record.total].every(Number.isInteger);
  }

  async function ensureReviewData() {
    if (state.reviewData) return state.reviewData;
    if (!state.dataPromise) {
      state.dataPromise = fetch(REVIEW_DATA_URL, { cache: "no-store" })
        .then((response) => {
          if (!response.ok) throw new Error(`HTTP ${response.status}`);
          return response.json();
        })
        .then((payload) => {
          state.reviewData = payload;
          return payload;
        })
        .catch((error) => {
          console.warn("连续帧与视频元数据加载失败", error);
          state.reviewData = { samples: [] };
          return state.reviewData;
        });
    }
    return state.dataPromise;
  }

  function sampleForTime(time) {
    return ctx.getSamples().find((sample) => sample.time === time) || ctx.getCurrentSample();
  }

  function reviewItemFor(camera, time) {
    return (state.reviewData?.samples || []).find((item) => item.camera === camera && item.time === time) || null;
  }

  function cameraName(camera) {
    return camera?.id === "north" ? "北机位" : "南机位";
  }

  function cameraInitial(camera) {
    return camera?.id === "north" ? "北" : "南";
  }

  function updateDraftState() {
    el.draftState.textContent = `已暂存，待处理，共 ${recordCount()} 次记录`;
  }

  function updateMainAudit() {
    const current = ctx.getCurrentSample();
    if (!current || current.time !== state.currentTime || !state.record) return;
    const target = $("#auditUniqueTotal");
    if (!target) return;
    const completed = isComplete(state.record);
    target.textContent = completed ? `${state.record.total} 辆` : "待复核";
    target.classList.toggle("value-pending", !completed);
  }

  function renderFormula() {
    const record = state.record;
    const valuesReady = [record.south, record.north, record.overlap].every(Number.isInteger);
    const computed = formulaTotal(record);
    const total = record.total;
    const mismatch = valuesReady && Number.isInteger(total) && total !== computed;
    const impossibleOverlap = valuesReady && record.overlap > Math.min(record.south, record.north);

    el.totalMode.textContent = record.total_source === "manual" ? "手填" : "自动";
    el.totalMode.classList.toggle("is-manual", record.total_source === "manual");

    if (valuesReady) {
      const suffix = mismatch ? `（当前填写 ${total} 辆）` : "";
      el.formula.textContent = `去重总数 = 南 ${record.south} + 北 ${record.north} − 重合 ${record.overlap} = ${computed} 辆${suffix}`;
    } else {
      el.formula.textContent = "去重总数 = 南 ? + 北 ? − 重合 ?（数量不全，暂不计算）";
    }

    let warning = "";
    if (impossibleOverlap) {
      warning = "重合车辆不能超过任一机位的可见数量。请核对后再保存。";
    } else if (mismatch) {
      warning = `手填总数与公式结果 ${computed} 辆不一致；请确认补充说明已写清原因。`;
    }
    el.formulaWarning.textContent = warning;
    el.formulaWarning.hidden = !warning;
    el.formulaWarning.classList.toggle("is-error", impossibleOverlap);
    record.formula_mismatch = mismatch || impossibleOverlap;
    return { computed, mismatch, impossibleOverlap };
  }

  function syncTotalFromFormula() {
    if (state.record.total_source !== "auto") return;
    const computed = formulaTotal(state.record);
    state.record.total = computed;
    el.totalCount.value = computed == null ? "" : String(computed);
  }

  function commitDraft() {
    if (!state.record) return;
    const key = String(state.record.time);
    if (hasAnyContent(state.record)) {
      state.records[key] = state.record;
    } else {
      delete state.records[key];
    }
    writeStorage(REVIEW_KEY, state.records);
    updateDraftState();
  }

  function fillFields() {
    const record = state.record;
    el.southCount.value = record.south == null ? "" : String(record.south);
    el.northCount.value = record.north == null ? "" : String(record.north);
    el.overlapCount.value = record.overlap == null ? "" : String(record.overlap);
    el.totalCount.value = record.total == null ? "" : String(record.total);
    el.southNote.value = record.notes.south || "";
    el.northNote.value = record.notes.north || "";
    el.overlapNote.value = record.notes.overlap || "";
    el.totalNote.value = record.notes.total || "";
    el.generalNote.value = record.notes.general || "";
    renderFormula();
    renderAttachment();
  }

  function renderAttachment() {
    const preview = state.attachmentPreviews.get(String(state.currentTime));
    const attachment = state.record?.attachment;
    const visible = Boolean(attachment?.name || preview);
    el.attachmentPreview.hidden = !visible;
    if (!visible) {
      el.attachmentImage.removeAttribute("src");
      el.attachmentImage.hidden = true;
      el.attachmentName.textContent = "";
      return;
    }
    el.attachmentImage.hidden = !preview;
    if (preview) {
      el.attachmentImage.src = preview;
    } else {
      el.attachmentImage.removeAttribute("src");
    }
    el.attachmentName.textContent = attachment?.name || "本页临时图片";
  }

  function renderEvidenceImages() {
    const southItem = reviewItemFor("south", state.currentTime);
    const northItem = reviewItemFor("north", state.currentTime);
    const southCamera = ctx.getCamera("south");
    const northCamera = ctx.getCamera("north");
    const southState = ctx.getCameraState(sampleForTime(state.currentTime), "south");
    const northState = ctx.getCameraState(sampleForTime(state.currentTime), "north");

    const southCrop = southItem?.crop || `crops/south_${state.currentTime}.jpg`;
    const northCrop = northItem?.crop || `crops/north_${state.currentTime}.jpg`;
    el.southCrop.src = `review/${southCrop}?v=2`;
    el.northCrop.src = `review/${northCrop}?v=2`;

    const southTotal = southItem?.provisionalTotal ?? southState.total ?? 0;
    const northTotal = northItem?.provisionalTotal ?? northState.total ?? 0;
    el.southCaption.textContent = `${cameraName(southCamera)} · AI 初标 ${southTotal} 辆（待终审）`;
    el.northCaption.textContent = `${cameraName(northCamera)} · AI 初标 ${northTotal} 辆（待终审）`;
  }

  function renderHeader() {
    const samples = [...ctx.getSamples()].sort((left, right) => left.time - right.time);
    const index = samples.findIndex((sample) => sample.time === state.currentTime);
    el.videoTime.textContent = ctx.formatVideoTime(state.currentTime);
    el.sampleMeta.textContent = `第 ${index + 1} / ${samples.length} 个采样时刻`;
    el.prevBtn.disabled = index <= 0;
    el.nextBtn.disabled = index >= samples.length - 1;
    updateDraftState();
    updateMainAudit();
  }

  function renderModal() {
    renderHeader();
    renderEvidenceImages();
    fillFields();
    const record = state.record;
    el.saveNote.textContent = record.status === "saved"
      ? `本帧已于 ${formatClock(record.saved_at)} 保存${record.completed ? "（四项完整）" : "（仍有留空，待补全）"}。`
      : "草稿自动保存在本机；点击保存后计入复核记录。";
  }

  function formatClock(iso) {
    if (!iso) return "未知时间";
    const date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "未知时间";
    return date.toLocaleString("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false
    });
  }

  async function openAt(time) {
    await ensureReviewData();
    state.currentTime = time;
    state.record = recordFor(time);
    renderModal();
    if (!dialog.open) dialog.showModal();
  }

  function openCurrent() {
    const sample = ctx.getCurrentSample();
    if (sample) openAt(sample.time);
  }

  function moveSample(direction) {
    const samples = [...ctx.getSamples()].sort((left, right) => left.time - right.time);
    const index = samples.findIndex((sample) => sample.time === state.currentTime);
    const next = samples[index + direction];
    if (!next) return;
    commitDraft();
    ctx.setSampleTime(next.time);
    openAt(next.time);
  }

  function applyInputsToRecord() {
    if (!state.record) return;
    state.record.south = parseCount(el.southCount);
    state.record.north = parseCount(el.northCount);
    state.record.overlap = parseCount(el.overlapCount);
    state.record.notes.south = el.southNote.value;
    state.record.notes.north = el.northNote.value;
    state.record.notes.overlap = el.overlapNote.value;
    state.record.notes.total = el.totalNote.value;
    state.record.notes.general = el.generalNote.value;
    syncTotalFromFormula();
    renderFormula();
    updateMainAudit();
    commitDraft();
  }

  function saveReview(event) {
    event.preventDefault();
    if (!state.record) return;
    applyInputsToRecord();

    if (!hasAnyContent(state.record)) {
      showToast("还没有可保存的复核结果；请先填写至少一项能确认的内容。", true);
      return;
    }
    if (state.record.total_source === "auto") {
      state.record.total = formulaTotal(state.record);
      el.totalCount.value = state.record.total == null ? "" : String(state.record.total);
    }
    state.record.status = "saved";
    state.record.completed = isComplete(state.record);
    state.record.reviewed_at = new Date().toISOString();
    state.record.saved_at = state.record.reviewed_at;
    renderFormula();
    commitDraft();
    updateMainAudit();
    el.saveNote.textContent = state.record.completed
      ? `本帧已于 ${formatClock(state.record.saved_at)} 保存；南 ${state.record.south}、北 ${state.record.north}、重合 ${state.record.overlap}、去重 ${state.record.total}。`
      : `本帧已于 ${formatClock(state.record.saved_at)} 暂存为待补全记录；留空项不会自动猜数。`;
    showToast(state.record.completed ? "本帧复核已保存，四项数量完整。" : "本帧已暂存；留空项仍待补全。");
  }

  function handleAttachment(file) {
    if (!file) return;
    if (!["image/png", "image/jpeg", "image/webp"].includes(file.type)) {
      showToast("只支持 PNG、JPG、WebP 图片。", true);
      return;
    }
    if (file.size > 10 * 1024 * 1024) {
      showToast("图片超过 10 MB，请压缩后再选择。", true);
      return;
    }
    const reader = new FileReader();
    reader.addEventListener("load", () => {
      const preview = String(reader.result || "");
      state.attachmentPreviews.set(String(state.currentTime), preview);
      state.record.attachment = {
        name: file.name,
        type: file.type,
        size: file.size,
        last_modified: file.lastModified
      };
      renderAttachment();
      commitDraft();
      showToast("标注图已加入本页预览，不会上传到服务器。");
    });
    reader.readAsDataURL(file);
  }

  function clearAttachment() {
    state.attachmentPreviews.delete(String(state.currentTime));
    if (state.record) state.record.attachment = null;
    el.attachmentInput.value = "";
    renderAttachment();
    commitDraft();
  }

  function tabButton(tab, active) {
    return `<button class="review-evidence-tab${active ? " is-active" : ""}" type="button" data-evidence-tab="${tab}">${tab === "original" ? "原图" : tab === "frames" ? "连续帧 ±2s" : "30 秒视频"}</button>`;
  }

  function openEvidence(camera) {
    const sample = sampleForTime(state.currentTime);
    const cameraState = ctx.getCameraState(sample, camera);
    const item = reviewItemFor(camera, state.currentTime);
    const key = `${camera}_${state.currentTime}`;
    const original = cameraState.frameUrl || item?.original || `assets/frames/${key}.jpg`;
    const frames = item?.frames || OFFSETS.map((offset) => ({
      offset,
      path: `frames/${key}_${offset === 0 ? "0" : offset > 0 ? `+${offset}` : offset}.jpg`,
      exists: true
    }));
    const clip = item?.clip || null;
    const clipStart = item?.clipStart ?? Math.max(0, state.currentTime - 15);
    const cameraTitle = `${cameraName(ctx.getCamera(camera))} · ${ctx.formatVideoTime(state.currentTime)}`;

    $("#reviewEvidenceTitle").textContent = cameraTitle;
    const frameHtml = frames.map((frame) => `
      <figure>
        <img src="review/${escapeHtml(frame.path)}" alt="${escapeHtml(key)} ${frame.offset} 秒" loading="lazy">
        <figcaption>${frame.offset > 0 ? "+" : ""}${frame.offset}s</figcaption>
      </figure>`).join("");
    const videoHtml = clip
      ? `<video controls preload="metadata" poster="review/${escapeHtml(frames[2]?.path || "")}" src="review/${escapeHtml(clip)}"></video>
         <p class="review-evidence-help">视频从 ${ctx.formatVideoTime(clipStart)} 开始；采样时刻位于第 ${ctx.formatVideoTime(state.currentTime - clipStart)}。</p>`
      : `<div class="review-evidence-empty">该时刻没有单独的 30 秒视频；请用五张连续帧判断车体是否持续存在。</div>`;

    el.evidenceBody.innerHTML = `
      <div class="review-evidence-tabs" role="tablist" aria-label="证据类型">
        ${tabButton("original", true)}
        ${tabButton("frames", false)}
        ${tabButton("video", false)}
      </div>
      <div class="review-evidence-pane" data-evidence-pane="original">
        <img class="review-original-image" src="${escapeHtml(original)}" alt="${escapeHtml(cameraTitle)} 原图">
        <p class="review-evidence-help">原图 1280 × 960。固定通道裁剪图只帮助定位，不改变原图内容。</p>
      </div>
      <div class="review-evidence-pane" data-evidence-pane="frames" hidden>
        <div class="review-frame-strip">${frameHtml}</div>
        <p class="review-evidence-help">相邻帧用于区分“同一辆车持续存在”和“把车头与货厢拆成两辆”。</p>
      </div>
      <div class="review-evidence-pane" data-evidence-pane="video" hidden>${videoHtml}</div>
    `;

    $$("[data-evidence-tab]", el.evidenceBody).forEach((button) => {
      button.addEventListener("click", () => {
        $$("[data-evidence-tab]", el.evidenceBody).forEach((itemButton) => {
          itemButton.classList.toggle("is-active", itemButton === button);
        });
        $$("[data-evidence-pane]", el.evidenceBody).forEach((pane) => {
          pane.hidden = pane.dataset.evidencePane !== button.dataset.evidenceTab;
        });
      });
    });

    if (!evidenceDialog.open) evidenceDialog.showModal();
  }

  function exportReview() {
    const samples = [...ctx.getSamples()].sort((left, right) => left.time - right.time);
    const rows = samples.map((sample) => {
      const record = recordFor(sample.time);
      const completed = isComplete(record);
      const computed = formulaTotal(record);
      const visibleTotal = [record.south, record.north].every(Number.isInteger)
        ? record.south + record.north
        : null;
      return {
        sample_key: sample.key || `t${sample.time}`,
        time: sample.time,
        video_time: ctx.formatVideoTime(sample.time),
        camera_counts: {
          south: record.south,
          north: record.north
        },
        visible_total: visibleTotal,
        overlap: record.overlap,
        unique_total: record.total,
        formula_total: computed,
        total_source: record.total_source,
        formula_mismatch: Boolean(record.formula_mismatch),
        notes: { ...record.notes },
        attachment: record.attachment ? { ...record.attachment } : null,
        attachment_file: record.attachment?.name || null,
        reviewed_at: record.reviewed_at,
        saved_at: record.saved_at,
        completed
      };
    });
    const completeCount = rows.filter((row) => row.completed).length;
    const payload = {
      schema: "truckflow-final-review-v2",
      exported_at: new Date().toISOString(),
      reviewer: "user-final-review",
      source_status: state.reviewData?.status || "ai-single-annotator-provisional",
      source_warning: state.reviewData?.warning || "AI 初标仅作导航参考，不是人工金标准。",
      definition: state.reviewData?.countDefinition || "独立可辨货车；叉车、轿车、面包车、行人不计；牵引车与挂车计一辆。",
      complete: completeCount === rows.length,
      reviewed_samples: rows.filter((row) => row.saved_at).length,
      completed_samples: completeCount,
      samples: rows
    };
    const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], { type: "application/json" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `truckflow-final-review-v2-${Date.now()}.json`;
    link.click();
    URL.revokeObjectURL(link.href);
    showToast(`已导出 ${payload.reviewed_samples} 条暂存记录；完整 ${completeCount} / ${rows.length} 个时刻。`);
  }

  function bind() {
    $("#openReviewBtn").addEventListener("click", openCurrent);
    document.addEventListener("truckflow:open-review", openCurrent);
    $$("[data-close-review]").forEach((button) => button.addEventListener("click", () => {
      commitDraft();
      dialog.close();
    }));
    dialog.addEventListener("close", commitDraft);
    evidenceDialog.addEventListener("close", () => {
      el.evidenceBody.innerHTML = "";
    });
    $$("[data-close-evidence]").forEach((button) => button.addEventListener("click", () => evidenceDialog.close()));

    el.prevBtn.addEventListener("click", () => moveSample(-1));
    el.nextBtn.addEventListener("click", () => moveSample(1));
    el.form.addEventListener("submit", saveReview);
    $("#reviewExportBtn").addEventListener("click", exportReview);
    $$("[data-review-original]").forEach((button) => {
      button.addEventListener("click", () => openEvidence(button.dataset.reviewOriginal));
    });

    [el.southCount, el.northCount, el.overlapCount].forEach((input) => {
      input.addEventListener("input", applyInputsToRecord);
    });
    [el.southNote, el.northNote, el.overlapNote, el.totalNote, el.generalNote].forEach((input) => {
      input.addEventListener("input", applyInputsToRecord);
    });
    el.totalCount.addEventListener("input", () => {
      state.record.total = parseCount(el.totalCount);
      state.record.total_source = "manual";
      renderFormula();
      updateMainAudit();
      commitDraft();
    });
    el.formulaReset.addEventListener("click", () => {
      state.record.total_source = "auto";
      syncTotalFromFormula();
      renderFormula();
      updateMainAudit();
      commitDraft();
    });

    el.attachmentBtn.addEventListener("click", () => el.attachmentInput.click());
    el.dropzone.addEventListener("click", (event) => {
      if (event.target.closest("button")) return;
      el.attachmentInput.click();
    });
    el.attachmentInput.addEventListener("change", () => handleAttachment(el.attachmentInput.files?.[0]));
    el.attachmentRemove.addEventListener("click", clearAttachment);
    ["dragenter", "dragover"].forEach((type) => {
      el.dropzone.addEventListener(type, (event) => {
        event.preventDefault();
        el.dropzone.classList.add("is-dragging");
      });
    });
    ["dragleave", "drop"].forEach((type) => {
      el.dropzone.addEventListener(type, (event) => {
        event.preventDefault();
        el.dropzone.classList.remove("is-dragging");
      });
    });
    el.dropzone.addEventListener("drop", (event) => handleAttachment(event.dataTransfer?.files?.[0]));
    document.addEventListener("paste", (event) => {
      if (!dialog.open) return;
      const file = Array.from(event.clipboardData?.files || []).find((item) => item.type.startsWith("image/"));
      if (file) handleAttachment(file);
    });
  }

  bind();
  ensureReviewData();
})();
