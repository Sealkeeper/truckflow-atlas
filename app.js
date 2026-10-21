(function () {
  "use strict";

  const DEMO = window.TRUCKFLOW_DEMO;
  const REVIEW_KEY = "truckflow.workspace.reviews.v1";
  const CAPACITY_KEY = "truckflow.workspace.capacity.v1";
  const BUSINESS_TIME_ZONE_OFFSET_MS = 8 * 60 * 60 * 1000;
  const TYPE_META = {
    large: { label: "大型", short: "L", color: "cyan" },
    medium: { label: "中型", short: "M", color: "blue" },
    small: { label: "小型", short: "S", color: "neutral" },
    unknown: { label: "待定", short: "U", color: "amber" }
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  if (!DEMO || !Array.isArray(DEMO.samples) || !DEMO.samples.length) {
    $("#fatalState").hidden = false;
    $$(".workspace > section, .workspace > footer").forEach((node) => {
      node.hidden = true;
    });
    return;
  }

  let activeData = DEMO;
  let playing = false;
  let playTimer = null;
  let lastTick = 0;
  let selectedEvidence = null;
  let uploadFiles = [];
  let pollTimer = null;
  let pollToken = 0;
  let lastJobPayload = null;

  const capacityDefaults = {
    large: DEMO.capacityDefaults.large,
    medium: DEMO.capacityDefaults.medium,
    small: DEMO.capacityDefaults.small
  };

  const state = {
    time: 600,
    speed: 1,
    viewMode: "original",
    evidenceFilter: "all",
    bucketSeconds: 600,
    capacities: readStorage(CAPACITY_KEY, { ...capacityDefaults, status: "pending" }),
    reviews: readStorage(REVIEW_KEY, {})
  };

  const el = {
    playBtn: $("#playBtn"),
    prevBtn: $("#prevBtn"),
    nextBtn: $("#nextBtn"),
    scrubber: $("#scrubber"),
    speedSelect: $("#speedSelect"),
    videoClock: $("#videoClock"),
    businessClock: $("#businessClock"),
    sampleLockText: $("#sampleLockText"),
    sampleNote: $("#sampleNote"),
    northImage: $("#northImage"),
    southImage: $("#southImage"),
    northCount: $("#northCount"),
    southCount: $("#southCount"),
    northTimestamp: $("#northTimestamp"),
    southTimestamp: $("#southTimestamp"),
    northAnalysis: $("#northAnalysis"),
    southAnalysis: $("#southAnalysis"),
    visibleTotal: $("#visibleTotal"),
    largeCount: $("#largeCount"),
    mediumCount: $("#mediumCount"),
    smallCount: $("#smallCount"),
    unknownCount: $("#unknownCount"),
    largeDetail: $("#largeDetail"),
    mediumDetail: $("#mediumDetail"),
    smallDetail: $("#smallDetail"),
    loadPercent: $("#loadPercent"),
    loadState: $("#loadState"),
    loadMeterFill: $("#loadMeterFill"),
    largeRate: $("#largeRate"),
    mediumRate: $("#mediumRate"),
    smallRate: $("#smallRate"),
    largeBar: $("#largeBar"),
    mediumBar: $("#mediumBar"),
    smallBar: $("#smallBar"),
    formulaNumbers: $("#formulaNumbers"),
    evidenceRail: $("#evidenceRail"),
    evidenceEmpty: $("#evidenceEmpty"),
    allEvidenceCount: $("#allEvidenceCount"),
    reviewEvidenceCount: $("#reviewEvidenceCount"),
    confirmedEvidenceCount: $("#confirmedEvidenceCount"),
    localSaveState: $("#localSaveState"),
    sampleIndexTag: $("#sampleIndexTag"),
    auditVideoTime: $("#auditVideoTime"),
    auditBusinessTime: $("#auditBusinessTime"),
    auditDelta: $("#auditDelta"),
    auditCameraCounts: $("#auditCameraCounts"),
    auditCallout: $("#auditCallout"),
    statsBody: $("#statsBody"),
    statsMeta: $("#statsMeta"),
    countChart: $("#countChart"),
    chartTooltip: $("#chartTooltip"),
    capacityDrawer: $("#capacityDrawer"),
    evidenceDrawer: $("#evidenceDrawer"),
    drawerBackdrop: $("#drawerBackdrop"),
    capacityLarge: $("#capacityLarge"),
    capacityMedium: $("#capacityMedium"),
    capacitySmall: $("#capacitySmall"),
    capacityConfirmed: $("#capacityConfirmed"),
    drawerEvidenceImage: $("#drawerEvidenceImage"),
    drawerEvidenceCamera: $("#drawerEvidenceCamera"),
    drawerEvidenceId: $("#drawerEvidenceId"),
    drawerEvidenceStatus: $("#drawerEvidenceStatus"),
    drawerCameraName: $("#drawerCameraName"),
    drawerVideoTime: $("#drawerVideoTime"),
    drawerBusinessTime: $("#drawerBusinessTime"),
    drawerVehicleType: $("#drawerVehicleType"),
    truckVotes: $("#truckVotes"),
    typeVotes: $("#typeVotes"),
    crossVotes: $("#crossVotes"),
    voteReason: $("#voteReason"),
    localReviewNote: $("#localReviewNote"),
    reclassifySelect: $("#reclassifySelect"),
    uploadDialog: $("#uploadDialog"),
    infoDialog: $("#infoDialog"),
    uploadForm: $("#uploadForm"),
    uploadStep: $("#uploadStep"),
    uploadProgress: $("#uploadProgress"),
    videoInput: $("#videoInput"),
    dropzone: $("#dropzone"),
    fileList: $("#fileList"),
    fileError: $("#fileError"),
    submitUploadBtn: $("#submitUploadBtn"),
    progressStage: $("#progressStage"),
    progressPercent: $("#progressPercent"),
    progressMessage: $("#progressMessage"),
    jobProgressFill: $("#jobProgressFill"),
    jobIdText: $("#jobIdText"),
    uploadError: $("#uploadError"),
    uploadErrorMessage: $("#uploadErrorMessage"),
    retryUploadBtn: $("#retryUploadBtn"),
    modePill: $("#modePill")
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
      toast("浏览器阻止了本地存储，操作仅保留在当前页面。", true);
      return false;
    }
  }

  function pad(value, length = 2) {
    return String(value).padStart(length, "0");
  }

  function formatVideoTime(seconds) {
    const safe = Math.max(0, Math.round(Number(seconds) || 0));
    const minutes = Math.floor(safe / 60);
    const secs = safe % 60;
    return `${pad(minutes)}:${pad(secs)}`;
  }

  function formatBusinessTime(seconds) {
    const base = new Date(activeData.dataset.startTime || DEMO.dataset.startTime);
    const date = new Date(base.getTime() + (Number(seconds) || 0) * 1000 + BUSINESS_TIME_ZONE_OFFSET_MS);
    const iso = date.toISOString();
    return `${iso.slice(0, 10)} ${iso.slice(11, 19)}`;
  }

  function formatBusinessClock(seconds) {
    return formatBusinessTime(seconds).slice(11);
  }

  function nearestSample(time = state.time) {
    return activeData.samples.reduce((best, sample) => {
      const distance = Math.abs(sample.time - time);
      const bestDistance = Math.abs(best.time - time);
      if (distance < bestDistance || (distance === bestDistance && sample.time > best.time)) {
        return sample;
      }
      return best;
    }, activeData.samples[0]);
  }

  function sampleIndex(sample) {
    return activeData.samples.findIndex((item) => item.time === sample.time);
  }

  function sampleCamera(sample, cameraId) {
    return sample[cameraId] || {
      total: 0,
      large: 0,
      medium: 0,
      small: 0,
      unknown: 0,
      review: false,
      boxes: [],
      absent: true
    };
  }

  function totalCountForSample(sample) {
    return activeData.cameras.reduce((sum, camera) => sum + Number(sampleCamera(sample, camera.id).total || 0), 0);
  }

  function typeCountsForSample(sample) {
    return ["large", "medium", "small", "unknown"].reduce((total, type) => {
      total[type] = activeData.cameras.reduce((sum, camera) => sum + Number(sampleCamera(sample, camera.id)[type] || 0), 0);
      return total;
    }, {});
  }

  function getCapacities() {
    return {
      large: clampNumber(state.capacities.large, 1, 999, capacityDefaults.large),
      medium: clampNumber(state.capacities.medium, 1, 999, capacityDefaults.medium),
      small: clampNumber(state.capacities.small, 1, 999, capacityDefaults.small)
    };
  }

  function clampNumber(value, min, max, fallback) {
    const number = Number(value);
    return Number.isFinite(number) ? Math.min(max, Math.max(min, number)) : fallback;
  }

  function computeLoad(counts) {
    const capacities = getCapacities();
    const rates = {
      large: (Number(counts.large || 0) / capacities.large) * 100,
      medium: (Number(counts.medium || 0) / capacities.medium) * 100,
      small: (Number(counts.small || 0) / capacities.small) * 100
    };
    return {
      ...rates,
      total: rates.large + rates.medium + rates.small
    };
  }

  function loadLabel(value) {
    if (value >= 100) return "超过演示容量";
    if (value >= 85) return "接近容量";
    if (value >= 55) return "负载偏高";
    return "余量可控";
  }

  function setPlayState(next) {
    playing = next;
    const iconUse = $("use", el.playBtn);
    iconUse.setAttribute("href", playing ? "#i-pause" : "#i-play");
    el.playBtn.setAttribute("aria-label", playing ? "暂停" : "播放");
    el.playBtn.setAttribute("title", playing ? "暂停（空格）" : "播放（空格）");

    if (playing) {
      lastTick = performance.now();
      window.clearInterval(playTimer);
      playTimer = window.setInterval(tickPlayback, 250);
    } else {
      window.clearInterval(playTimer);
      playTimer = null;
    }
  }

  function tickPlayback() {
    const now = performance.now();
    const delta = ((now - lastTick) / 1000) * state.speed;
    lastTick = now;
    const duration = activeData.dataset.durationSeconds;
    state.time = Math.min(duration, state.time + delta);
    if (state.time >= duration) {
      state.time = duration;
      setPlayState(false);
      toast("已到达展示窗口末尾 44:19。");
    }
    renderTimeDependent({ chart: false });
  }

  function setTime(seconds) {
    const duration = activeData.dataset.durationSeconds;
    state.time = Math.min(duration, Math.max(0, Number(seconds) || 0));
    renderTimeDependent({ chart: true });
  }

  function jumpToSample(direction) {
    const current = nearestSample();
    const index = sampleIndex(current);
    let targetIndex = index;
    if (Math.abs(current.time - state.time) > 0.5) {
      targetIndex = direction > 0 ? index : index;
    } else {
      targetIndex = Math.min(activeData.samples.length - 1, Math.max(0, index + direction));
    }
    const target = activeData.samples[targetIndex];
    setTime(target.time);
  }

  function renderAll() {
    const duration = activeData.dataset.durationSeconds;
    el.scrubber.max = String(duration);
    el.scrubber.value = String(Math.min(duration, state.time));
    renderTimeDependent({ chart: true, all: true });
  }

  function renderTimeDependent(options = {}) {
    const sample = nearestSample();
    const sampleCounts = typeCountsForSample(sample);
    const visibleTotal = totalCountForSample(sample);
    const diff = Math.abs(state.time - sample.time);
    const index = sampleIndex(sample);
    const duration = activeData.dataset.durationSeconds;

    el.scrubber.value = String(Math.round(state.time));
    el.scrubber.style.setProperty("--scrub-progress", `${Math.max(0, Math.min(100, (state.time / duration) * 100))}%`);
    el.videoClock.textContent = formatVideoTime(state.time);
    el.businessClock.textContent = `业务 ${formatBusinessClock(sample.time)}`;
    el.sampleLockText.textContent = formatVideoTime(sample.time);
    el.sampleNote.textContent = diff < 0.6
      ? `当前画面锁定 ${formatVideoTime(sample.time)} 真实采样帧；相邻采样间隔约 5 分钟。`
      : `当前播放位于 ${formatVideoTime(state.time)}，数据沿用最近真实采样 ${formatVideoTime(sample.time)}（相差 ${Math.round(diff)} 秒），未做逐帧推断。`;

    activeData.cameras.forEach((camera) => {
      const cameraState = sampleCamera(sample, camera.id);
      const image = camera.id === "north" ? el.northImage : el.southImage;
      const count = camera.id === "north" ? el.northCount : el.southCount;
      const timestamp = camera.id === "north" ? el.northTimestamp : el.southTimestamp;
      const analysis = camera.id === "north" ? el.northAnalysis : el.southAnalysis;
      const fallbackImage = camera.imagePath ? camera.imagePath.replace("{time}", String(sample.time)) : makeFramePlaceholder(camera.name);
      const source = cameraState.frameUrl || fallbackImage;
      if (image.getAttribute("src") !== source) {
        image.setAttribute("src", source);
      }
      image.alt = `${camera.name}机位 ${formatVideoTime(sample.time)} 的真实采样画面`;
      count.textContent = cameraState.absent ? "—" : String(cameraState.total ?? 0);
      timestamp.textContent = `${formatBusinessTime(sample.time)} · ${formatVideoTime(sample.time)}`;
      renderAnalysisLayer(analysis, cameraState, camera);
    });

    el.visibleTotal.textContent = String(visibleTotal);
    el.largeCount.textContent = String(sampleCounts.large);
    el.mediumCount.textContent = String(sampleCounts.medium);
    el.smallCount.textContent = String(sampleCounts.small);
    el.unknownCount.textContent = String(sampleCounts.unknown);
    el.largeDetail.textContent = `${cameraBreakdown(sample, "large")}`;
    el.mediumDetail.textContent = `${cameraBreakdown(sample, "medium")}`;
    el.smallDetail.textContent = `${cameraBreakdown(sample, "small")}`;

    renderLoad(sampleCounts);
    renderEvidence();
    renderAudit(sample, index, diff);
    if (options.chart !== false) {
      renderChart();
    }

    el.prevBtn.disabled = index <= 0;
    el.prevBtn.title = index <= 0 ? "已到首个真实采样帧" : "上一样本（←）";
    el.nextBtn.disabled = index >= activeData.samples.length - 1;
    el.nextBtn.title = index >= activeData.samples.length - 1 ? "已到最后一个真实采样帧" : "下一样本（→）";
  }

  function cameraBreakdown(sample, type) {
    return activeData.cameras.map((camera) => {
      const cameraState = sampleCamera(sample, camera.id);
      const letter = camera.id.toLowerCase().startsWith("north") || camera.code?.endsWith("-N") ? "北" : "南";
      return `${letter} ${Number(cameraState[type] || 0)}`;
    }).join(" · ");
  }

  function renderAnalysisLayer(layer, cameraState, camera) {
    layer.hidden = state.viewMode !== "analysis";
    if (state.viewMode !== "analysis") return;

    const boxes = Array.isArray(cameraState.boxes) ? cameraState.boxes.filter(isReliableBox) : [];
    layer.innerHTML = "";
    if (boxes.length) {
      boxes.forEach((box, index) => {
        const rect = box?.rect || box;
        const node = document.createElement("div");
        node.className = "bbox";
        node.style.left = `${rect.x * 100}%`;
        node.style.top = `${rect.y * 100}%`;
        node.style.width = `${rect.w * 100}%`;
        node.style.height = `${rect.h * 100}%`;
        const label = document.createElement("span");
        label.textContent = box.id || `${TYPE_META[box.type]?.short || "V"}-${pad(index + 1)}`;
        node.appendChild(label);
        layer.appendChild(node);
      });
      return;
    }

    const notice = document.createElement("div");
    notice.className = "analysis-unavailable";
    const icon = document.createElement("span");
    icon.className = "analysis-empty-icon";
    const title = document.createElement("strong");
    title.textContent = activeData.dataset.boxMessage || "框待后端返回";
    const detail = document.createElement("span");
    detail.textContent = `${camera.name} · 当前数据源无可靠车辆框，不绘制推测位置`;
    notice.append(icon, title, detail);
    layer.appendChild(notice);
  }

  function isReliableBox(box) {
    const rect = box?.rect || box;
    return rect
      && [rect.x, rect.y, rect.w, rect.h].every((value) => Number.isFinite(Number(value)))
      && Number(rect.w) > 0
      && Number(rect.h) > 0;
  }

  function renderLoad(counts) {
    const rates = computeLoad(counts);
    const capacities = getCapacities();
    el.loadPercent.textContent = `${rates.total.toFixed(1)}%`;
    el.loadState.textContent = loadLabel(rates.total);
    el.loadMeterFill.style.width = `${Math.min(100, rates.total)}%`;
    el.loadMeterFill.style.background = rates.total >= 100
      ? "linear-gradient(90deg, #f5d171, #ff847a)"
      : "linear-gradient(90deg, var(--cyan), #a6e986 68%, var(--amber))";
    el.largeRate.textContent = `${rates.large.toFixed(1)}%`;
    el.mediumRate.textContent = `${rates.medium.toFixed(1)}%`;
    el.smallRate.textContent = `${rates.small.toFixed(1)}%`;
    el.largeBar.style.width = `${Math.min(100, rates.large)}%`;
    el.mediumBar.style.width = `${Math.min(100, rates.medium)}%`;
    el.smallBar.style.width = `${Math.min(100, rates.small)}%`;
    el.formulaNumbers.textContent = `${counts.large}/${capacities.large} + ${counts.medium}/${capacities.medium} + ${counts.small}/${capacities.small} = ${rates.total.toFixed(1)}%`;
  }

  function renderAudit(sample, index, diff) {
    el.sampleIndexTag.textContent = `${index + 1} / ${activeData.samples.length}`;
    el.auditVideoTime.textContent = formatVideoTime(sample.time);
    el.auditBusinessTime.textContent = formatBusinessClock(sample.time);
    el.auditDelta.textContent = diff < 1 ? "0 秒" : `${Math.round(diff)} 秒`;
    el.auditCameraCounts.textContent = activeData.cameras.map((camera) => {
      const cameraState = sampleCamera(sample, camera.id);
      const letter = camera.id.toLowerCase().startsWith("north") || camera.code?.endsWith("-N") ? "北" : "南";
      return `${letter} ${cameraState.absent ? "—" : cameraState.total}`;
    }).join(" · ");
    el.auditCallout.textContent = sample.note || "该采样帧没有附加复核说明；跨机位唯一车辆数仍需另行确认。";
  }

  function evidenceItems() {
    const sample = nearestSample();
    const items = [];
    const storedReviews = state.reviews || {};

    activeData.cameras.forEach((camera) => {
      const cameraState = sampleCamera(sample, camera.id);
      if (cameraState.vehicles?.length) {
        cameraState.vehicles.forEach((vehicle, index) => {
          const baseId = vehicle.evidence_id || vehicle.id || `${camera.code || camera.id}-${sample.time}-${index + 1}`;
          const stored = storedReviews[baseId];
          const type = stored?.vehicleType || vehicle.type || "unknown";
          items.push({
            id: baseId,
            sampleTime: sample.time,
            cameraId: camera.id,
            cameraCode: camera.code || camera.id.toUpperCase(),
            cameraName: camera.name,
            type,
            defaultStatus: vehicle.review ? "review" : "confirmed",
            stored,
            crop: vehicle.crop_url || vehicle.cropUrl || vehicle.frame_url || cameraState.frameUrl || makeFramePlaceholder(camera.name),
            votes: vehicle.votes || {},
            reason: vehicle.reason || sample.note,
            note: sample.note
          });
        });
        return;
      }

      Object.keys(TYPE_META).forEach((type) => {
        const count = Number(cameraState[type] || 0);
        for (let index = 0; index < count; index += 1) {
          const id = `${camera.code || camera.id.toUpperCase()}-${sample.time}-${TYPE_META[type].short}-${pad(index + 1)}`;
          const stored = storedReviews[id];
          const crop = activeData.remote
            ? cameraState.frameUrl || makeFramePlaceholder(camera.name)
            : activeData.crops?.[camera.id]?.[type] || cameraState.frameUrl || makeFramePlaceholder(camera.name);
          items.push({
            id,
            sampleTime: sample.time,
            cameraId: camera.id,
            cameraCode: camera.code || camera.id.toUpperCase(),
            cameraName: camera.name,
            type: stored?.vehicleType || type,
            defaultStatus: cameraState.review || type === "unknown" ? "review" : "confirmed",
            stored,
            crop,
            votes: cameraState.review
              ? { truck: "2 / 3", type: type === "large" ? "2 / 3" : "2 / 3", cross: "0 / 3" }
              : { truck: "3 / 3", type: "3 / 3", cross: "—" },
            reason: sample.note,
            note: sample.note
          });
        }
      });
    });

    return items.map((item) => ({
      ...item,
      status: item.stored?.status || item.defaultStatus
    }));
  }

  function evidenceFilterGroup(status) {
    if (status === "confirmed" || status === "reclassified") return "confirmed";
    if (status === "rejected" || status === "unknown") return "rejected";
    return "review";
  }

  function statusLabel(status) {
    return {
      review: "待复核",
      confirmed: "已确认",
      rejected: "已删除",
      unknown: "未知",
      merged: "已合并",
      split: "待拆分",
      reclassified: "已改判"
    }[status] || "待复核";
  }

  function renderEvidence() {
    const items = evidenceItems();
    const filter = state.evidenceFilter;
    const visibleItems = items.filter((item) => filter === "all" || evidenceFilterGroup(item.status) === filter);
    const reviewCount = items.filter((item) => evidenceFilterGroup(item.status) === "review").length;
    const confirmedCount = items.filter((item) => evidenceFilterGroup(item.status) === "confirmed").length;
    const rejectedCount = items.filter((item) => evidenceFilterGroup(item.status) === "rejected").length;

    el.allEvidenceCount.textContent = String(items.length);
    el.reviewEvidenceCount.textContent = String(reviewCount);
    el.confirmedEvidenceCount.textContent = String(confirmedCount);
    const rejectedTabCount = $('[data-evidence-filter="rejected"] span');
    if (rejectedTabCount) rejectedTabCount.textContent = String(rejectedCount);

    el.evidenceRail.innerHTML = "";
    visibleItems.forEach((item) => {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "evidence-card";
      card.dataset.evidenceId = item.id;
      const typeLabel = TYPE_META[item.type]?.label || "待定";
      const group = evidenceFilterGroup(item.status);
      card.innerHTML = `
        <span class="evidence-thumb"><img src="${escapeAttribute(item.crop)}" alt=""></span>
        <span class="evidence-card-body">
          <span class="evidence-card-top">
            <span class="evidence-camera">${escapeHtml(item.cameraCode)} · ${escapeHtml(formatVideoTime(item.sampleTime))}</span>
            <span class="status-chip ${group === "confirmed" ? "is-confirmed" : group === "rejected" ? "is-rejected" : ""}">${escapeHtml(statusLabel(item.status))}</span>
          </span>
          <strong>${escapeHtml(item.id)}</strong>
          <span class="evidence-card-meta"><span>${escapeHtml(typeLabel)}货车</span><span>查看证据 →</span></span>
        </span>
      `;
      card.addEventListener("click", () => openEvidence(item));
      el.evidenceRail.appendChild(card);
    });

    el.evidenceEmpty.hidden = visibleItems.length > 0;
    el.evidenceRail.hidden = visibleItems.length === 0;
    $("[data-reset-evidence]", el.evidenceEmpty)?.addEventListener("click", () => setEvidenceFilter("all"), { once: true });
  }

  function setEvidenceFilter(filter) {
    state.evidenceFilter = filter;
    $$("[data-evidence-filter]").forEach((button) => {
      const active = button.dataset.evidenceFilter === filter;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
    renderEvidence();
  }

  function dedupEvidence() {
    const sample = nearestSample();
    const stored = state.reviews[`MERGE-${sample.time}`];
    return {
      id: `MERGE-${sample.time}`,
      sampleTime: sample.time,
      cameraName: "天花北 × 天花南",
      cameraCode: "CROSS-CAM",
      type: "unknown",
      status: stored?.status || "review",
      stored,
      crop: activeData.remote
        ? sampleCamera(sample, activeData.cameras[0].id).frameUrl || makeFramePlaceholder("跨机位核对")
        : activeData.crops?.south?.review || "assets/frames/crops/south-review.jpg",
      votes: { truck: "—", type: "—", cross: "0 / 3" },
      reason: "南北画面中仍可能出现同一辆物理车；本数据只提供画面级计数，没有可靠目标框与成对裁剪，无法安全给出唯一 ID。",
      note: sample.note,
      isDedup: true
    };
  }

  function openEvidence(item) {
    selectedEvidence = item;
    el.drawerEvidenceImage.src = item.crop;
    el.drawerEvidenceImage.alt = `${item.cameraName} ${formatVideoTime(item.sampleTime)} 的真实画面裁剪`;
    el.drawerEvidenceCamera.textContent = item.cameraCode;
    el.drawerEvidenceId.textContent = item.id;
    setStatusChip(el.drawerEvidenceStatus, item.status);
    el.drawerCameraName.textContent = item.cameraName;
    el.drawerVideoTime.textContent = formatVideoTime(item.sampleTime);
    el.drawerBusinessTime.textContent = formatBusinessClock(item.sampleTime);
    el.drawerVehicleType.textContent = item.isDedup ? "跨机位匹配" : `${TYPE_META[item.type]?.label || "待定"}货车`;
    el.truckVotes.textContent = item.votes?.truck || "—";
    el.typeVotes.textContent = item.votes?.type || "—";
    el.crossVotes.textContent = item.votes?.cross || "—";
    el.voteReason.textContent = item.reason || "当前模型票数不足以形成确定结论。";
    el.reclassifySelect.value = ["large", "medium", "small", "unknown"].includes(item.type) ? item.type : "unknown";

    const isLocked = Boolean(item.isDedup);
    $$("[data-review-action]").forEach((button) => {
      button.disabled = isLocked;
      button.title = isLocked ? "跨机位去重缺少可靠目标框与成对身份，不能在此直接合并" : actionHint(button.dataset.reviewAction);
    });
    $("#reclassifyBtn").disabled = isLocked;
    $("#reclassifyBtn").title = isLocked ? "跨机位复核项不适用单车车型改判" : "将人工改判写入当前浏览器";
    el.reclassifySelect.disabled = isLocked;

    const lastAction = item.stored;
    el.localReviewNote.textContent = lastAction
      ? `本地记录：${statusLabel(lastAction.status)}${lastAction.vehicleType ? ` · ${TYPE_META[lastAction.vehicleType]?.label || lastAction.vehicleType}` : ""}${lastAction.targetId ? ` · 目标 ${lastAction.targetId}` : ""} · ${lastAction.updatedAt || ""}`
      : item.isDedup
        ? "该去重项无可靠目标框，操作按钮已禁用；请等待后端返回成对证据。"
        : "尚未提交人工复核。操作只保存在当前浏览器，不回写原始开发集。";
    el.localReviewNote.classList.toggle("is-saved", Boolean(lastAction));
    openDrawer("evidence");
  }

  function setStatusChip(node, status) {
    const group = evidenceFilterGroup(status);
    node.textContent = statusLabel(status);
    node.classList.toggle("is-confirmed", group === "confirmed");
    node.classList.toggle("is-rejected", group === "rejected");
  }

  function actionHint(action) {
    return {
      confirm: "将当前证据标记为人工确认",
      delete: "从本机复核记录中标记为重复/删除",
      unknown: "标记为无法判断",
      merge: "输入目标编号并记录合并决定",
      split: "输入拆分编号并记录拆分决定"
    }[action] || "";
  }

  function applyReviewAction(action) {
    if (!selectedEvidence || selectedEvidence.isDedup) return;
    const id = selectedEvidence.id;
    const previous = state.reviews[id] || {};
    const next = {
      ...previous,
      action,
      status: previous.status || selectedEvidence.defaultStatus,
      vehicleType: previous.vehicleType || selectedEvidence.type,
      updatedAt: new Date().toLocaleString("zh-CN", { hour12: false })
    };

    if (action === "confirm") next.status = "confirmed";
    if (action === "delete") next.status = "rejected";
    if (action === "unknown") next.status = "unknown";
    if (action === "merge") {
      const target = window.prompt("输入要合并到的目标编号（本操作只写入本机复核记录）：", "T-001");
      if (target === null || !target.trim()) return;
      next.status = "merged";
      next.targetId = target.trim();
    }
    if (action === "split") {
      const target = window.prompt("输入拆分后的新编号（本操作只写入本机复核记录）：", `${id}-B`);
      if (target === null || !target.trim()) return;
      next.status = "split";
      next.targetId = target.trim();
    }
    state.reviews[id] = next;
    writeStorage(REVIEW_KEY, state.reviews);
    updateLocalSaveState();
    renderEvidence();
    openEvidence({ ...selectedEvidence, stored: next, status: next.status });
    toast(`已写入本机复核：${statusLabel(next.status)}。原始计数未改写。`);
    syncReviewToApi(action, next);
  }

  function applyReclassification() {
    if (!selectedEvidence || selectedEvidence.isDedup) return;
    const type = el.reclassifySelect.value;
    const previous = state.reviews[selectedEvidence.id] || {};
    const next = {
      ...previous,
      action: "reclassify",
      status: previous.status || "review",
      vehicleType: type,
      updatedAt: new Date().toLocaleString("zh-CN", { hour12: false })
    };
    state.reviews[selectedEvidence.id] = next;
    writeStorage(REVIEW_KEY, state.reviews);
    updateLocalSaveState();
    renderEvidence();
    openEvidence({ ...selectedEvidence, stored: next, type });
    toast(`已改判为${TYPE_META[type]?.label || "待定"}；等待审核汇总。`);
    syncReviewToApi("reclassify", next);
  }

  function syncReviewToApi(action, review) {
    if (!activeData.remote || !activeData.dataset.apiBase || !activeData.dataset.jobId || !selectedEvidence) return;
    const endpoint = `${activeData.dataset.apiBase}/api/jobs/${encodeURIComponent(activeData.dataset.jobId)}/reviews/${encodeURIComponent(selectedEvidence.id)}`;
    const payload = {
      action,
      size: review.vehicleType,
      target_id: review.targetId || undefined,
      note: "Submitted from static workspace"
    };
    fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    }).then((response) => {
      if (!response.ok) throw new Error(`POST review 返回 ${response.status}`);
      toast("复核决定已同步到后端。");
    }).catch((error) => {
      toast(`本地记录已保存，但后端同步失败：${error.message}`, true);
    });
  }

  function updateLocalSaveState() {
    const count = Object.keys(state.reviews || {}).length;
    el.localSaveState.textContent = count
      ? `本地复核 ${count} 项 · ${new Date().toLocaleTimeString("zh-CN", { hour12: false, hour: "2-digit", minute: "2-digit" })}`
      : "本地复核记录已同步";
  }

  function renderChart() {
    const svg = el.countChart;
    const width = 900;
    const height = 330;
    const margin = { top: 26, right: 22, bottom: 45, left: 43 };
    const chartWidth = width - margin.left - margin.right;
    const chartHeight = height - margin.top - margin.bottom;
    const duration = activeData.dataset.durationSeconds;
    const maxCount = Math.max(4, ...activeData.samples.map(totalCountForSample));
    const yMax = Math.ceil((maxCount + 1) / 2) * 2;
    const points = activeData.samples.map((sample) => {
      const count = totalCountForSample(sample);
      return {
        sample,
        count,
        x: margin.left + (sample.time / duration) * chartWidth,
        y: margin.top + chartHeight - (count / yMax) * chartHeight,
        hasReview: activeData.cameras.some((camera) => sampleCamera(sample, camera.id).review)
      };
    });
    const linePath = points.map((point, index) => `${index === 0 ? "M" : "L"}${point.x.toFixed(2)},${point.y.toFixed(2)}`).join(" ");
    const areaPath = `M${points[0].x.toFixed(2)},${(margin.top + chartHeight).toFixed(2)} ${linePath.replace(/^M/, "L")} L${points[points.length - 1].x.toFixed(2)},${(margin.top + chartHeight).toFixed(2)} Z`;
    const current = nearestSample();
    const currentPoint = points.find((point) => point.sample.time === current.time) || points[0];
    const currentX = margin.left + (state.time / duration) * chartWidth;
    const xTicks = [0, 600, 1200, 1800, 2400, 2659].filter((time) => time <= duration);
    const tickMarkup = Array.from({ length: yMax / 2 + 1 }, (_value, index) => {
      const value = index * 2;
      const y = margin.top + chartHeight - (value / yMax) * chartHeight;
      return `
        <line class="grid-line" x1="${margin.left}" y1="${y}" x2="${width - margin.right}" y2="${y}"></line>
        <text class="axis-label" x="${margin.left - 11}" y="${y + 3}" text-anchor="end">${value}</text>
      `;
    }).join("");
    const xMarkup = xTicks.map((time) => {
      const x = margin.left + (time / duration) * chartWidth;
      return `<text class="axis-label" x="${x}" y="${height - 16}" text-anchor="middle">${formatVideoTime(time)}</text>`;
    }).join("");
    const pointMarkup = points.map((point) => `
      <circle class="sample-point ${point.hasReview ? "has-review" : ""} ${point.sample.time === current.time ? "is-current" : ""}"
        cx="${point.x.toFixed(2)}" cy="${point.y.toFixed(2)}" r="${point.sample.time === current.time ? 5 : 3.5}"
        data-chart-time="${point.sample.time}" tabindex="0" role="button"
        aria-label="${formatVideoTime(point.sample.time)}，画面内合计 ${point.count} 辆次">
        <title>${formatVideoTime(point.sample.time)} · ${point.count} 辆次</title>
      </circle>
    `).join("");

    svg.innerHTML = `
      <defs>
        <linearGradient id="chartArea" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stop-color="#48e3c5" stop-opacity="0.17"></stop>
          <stop offset="1" stop-color="#48e3c5" stop-opacity="0"></stop>
        </linearGradient>
      </defs>
      ${tickMarkup}
      ${xMarkup}
      <path class="chart-area" d="${areaPath}"></path>
      <path class="chart-line" d="${linePath}"></path>
      <line class="current-line" x1="${currentX.toFixed(2)}" y1="${margin.top}" x2="${currentX.toFixed(2)}" y2="${margin.top + chartHeight}"></line>
      ${pointMarkup}
      <circle class="current-dot" cx="${currentPoint.x.toFixed(2)}" cy="${currentPoint.y.toFixed(2)}" r="7" opacity="0.28"></circle>
      <circle class="current-dot" cx="${currentPoint.x.toFixed(2)}" cy="${currentPoint.y.toFixed(2)}" r="3"></circle>
      <text class="axis-label" x="${margin.left}" y="13">可见辆次</text>
    `;

    $$("[data-chart-time]", svg).forEach((point) => {
      const jump = () => setTime(Number(point.dataset.chartTime));
      point.addEventListener("click", jump);
      point.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          jump();
        }
      });
      point.addEventListener("pointerenter", (event) => showChartTooltip(event, point));
      point.addEventListener("pointermove", (event) => moveChartTooltip(event));
      point.addEventListener("pointerleave", hideChartTooltip);
    });
  }

  function showChartTooltip(event, point) {
    const time = Number(point.dataset.chartTime);
    const sample = activeData.samples.find((item) => item.time === time);
    const counts = typeCountsForSample(sample);
    el.chartTooltip.hidden = false;
    $("strong", el.chartTooltip).textContent = `${formatVideoTime(time)} · ${totalCountForSample(sample)} 辆次`;
    $("span", el.chartTooltip).textContent = `大 ${counts.large} / 中 ${counts.medium} / 小 ${counts.small}`;
    moveChartTooltip(event);
  }

  function moveChartTooltip(event) {
    if (el.chartTooltip.hidden) return;
    const wrapper = $(".chart-wrap");
    const rect = wrapper.getBoundingClientRect();
    el.chartTooltip.style.left = `${Math.max(55, Math.min(rect.width - 55, event.clientX - rect.left))}px`;
    el.chartTooltip.style.top = `${Math.max(55, event.clientY - rect.top)}px`;
  }

  function hideChartTooltip() {
    el.chartTooltip.hidden = true;
  }

  function renderStats() {
    const duration = activeData.dataset.durationSeconds;
    const bucket = Number(state.bucketSeconds);
    const groups = [];
    if (bucket === 0) {
      groups.push({ start: 0, end: duration, samples: activeData.samples.slice() });
    } else {
      for (let start = 0; start < duration; start += bucket) {
        const end = Math.min(duration, start + bucket);
        const samples = activeData.samples.filter((sample) => sample.time >= start && sample.time < end);
        if (samples.length) groups.push({ start, end, samples });
      }
    }

    el.statsBody.innerHTML = "";
    groups.forEach((group) => {
      const count = group.samples.length;
      const avg = count ? group.samples.reduce((sum, sample) => sum + totalCountForSample(sample), 0) / count : 0;
      const types = ["large", "medium", "small"].reduce((result, type) => {
        result[type] = count
          ? group.samples.reduce((sum, sample) => sum + Number(typeCountsForSample(sample)[type] || 0), 0) / count
          : 0;
        return result;
      }, {});
      const avgLoad = count
        ? group.samples.reduce((sum, sample) => sum + computeLoad(typeCountsForSample(sample)).total, 0) / count
        : 0;
      const row = document.createElement("tr");
      row.innerHTML = `
        <td data-label="时间段">${escapeHtml(formatVideoTime(group.start))}–${escapeHtml(formatVideoTime(group.end))}</td>
        <td data-label="采样帧">${count} 帧</td>
        <td data-label="平均可见辆次">${avg.toFixed(1)} 辆次</td>
        <td data-label="大 / 中 / 小"><span class="type-split"><span class="large">${types.large.toFixed(1)}</span><span class="medium">${types.medium.toFixed(1)}</span><span class="small">${types.small.toFixed(1)}</span></span></td>
        <td data-label="平均叠加负载"><span class="table-load">${avgLoad.toFixed(1)}%</span></td>
        <td data-label="去重状态"><span class="table-pending">待复核</span></td>
      `;
      el.statsBody.appendChild(row);
    });
    el.statsMeta.textContent = `共 ${activeData.samples.length} 个采样帧`;
  }

  function exportCsv() {
    const headers = [
      "sample_video_time",
      "sample_video_clock",
      "business_time",
      "north_total",
      "north_large",
      "north_medium",
      "north_small",
      "north_unknown",
      "south_total",
      "south_large",
      "south_medium",
      "south_small",
      "south_unknown",
      "visible_total",
      "overlay_load_percent",
      "dedup_status",
      "data_status",
      "review_note"
    ];
    const lines = [headers.join(",")];
    activeData.samples.forEach((sample) => {
      const north = sampleCamera(sample, "north");
      const south = sampleCamera(sample, "south");
      const counts = typeCountsForSample(sample);
      const values = [
        sample.time,
        formatVideoTime(sample.time),
        formatBusinessClock(sample.time),
        north.total,
        north.large,
        north.medium,
        north.small,
        north.unknown,
        south.total,
        south.large,
        south.medium,
        south.small,
        south.unknown,
        totalCountForSample(sample),
        computeLoad(counts).total.toFixed(1),
        "pending_review",
        "DEMO_unvalidated",
        sample.note || ""
      ];
      lines.push(values.map(csvCell).join(","));
    });
    const blob = new Blob(["\uFEFF", lines.join("\r\n")], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `truckflow_visible_counts_demo_${new Date().toISOString().slice(0, 10)}.csv`;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1200);
    toast("CSV 已导出；去重状态明确标为 pending_review。");
  }

  function csvCell(value) {
    const text = String(value ?? "");
    return `"${text.replace(/"/g, '""')}"`;
  }

  function openDrawer(name) {
    const target = name === "capacity" ? el.capacityDrawer : el.evidenceDrawer;
    const other = name === "capacity" ? el.evidenceDrawer : el.capacityDrawer;
    other.classList.remove("is-open");
    other.setAttribute("aria-hidden", "true");
    other.hidden = true;
    el.drawerBackdrop.hidden = false;
    document.body.classList.add("is-drawer-open");
    target.hidden = false;
    window.requestAnimationFrame(() => {
      el.drawerBackdrop.classList.add("is-visible");
      target.classList.add("is-open");
      target.setAttribute("aria-hidden", "false");
      $("button", target)?.focus({ preventScroll: true });
    });
  }

  function closeDrawers() {
    [el.capacityDrawer, el.evidenceDrawer].forEach((drawer) => {
      drawer.classList.remove("is-open");
      drawer.setAttribute("aria-hidden", "true");
    });
    el.drawerBackdrop.classList.remove("is-visible");
    document.body.classList.remove("is-drawer-open");
    window.setTimeout(() => {
      if (!el.capacityDrawer.classList.contains("is-open") && !el.evidenceDrawer.classList.contains("is-open")) {
        el.drawerBackdrop.hidden = true;
        el.capacityDrawer.hidden = true;
        el.evidenceDrawer.hidden = true;
      }
    }, 240);
  }

  function fillCapacityInputs() {
    const capacities = getCapacities();
    el.capacityLarge.value = String(capacities.large);
    el.capacityMedium.value = String(capacities.medium);
    el.capacitySmall.value = String(capacities.small);
    el.capacityConfirmed.textContent = state.capacities.status === "saved"
      ? "当前状态：本机已保存 · 验收前仍待正式确认"
      : "当前状态：待用户确认";
    const tag = $("#capacityInlineBtn");
    tag.textContent = state.capacities.status === "saved" ? "本机已保存" : "容量待确认";
  }

  function saveCapacity() {
    const capacities = {
      large: clampNumber(el.capacityLarge.value, 1, 999, capacityDefaults.large),
      medium: clampNumber(el.capacityMedium.value, 1, 999, capacityDefaults.medium),
      small: clampNumber(el.capacitySmall.value, 1, 999, capacityDefaults.small),
      status: "saved",
      savedAt: new Date().toISOString()
    };
    state.capacities = capacities;
    writeStorage(CAPACITY_KEY, capacities);
    fillCapacityInputs();
    renderTimeDependent({ chart: false });
    renderStats();
    toast("容量已保存到本机；正式验收前仍需项目经理确认。");
    closeDrawers();
  }

  function resetCapacity() {
    state.capacities = { ...capacityDefaults, status: "pending" };
    writeStorage(CAPACITY_KEY, state.capacities);
    fillCapacityInputs();
    renderTimeDependent({ chart: false });
    renderStats();
    toast("已恢复演示容量基线；状态仍为“待用户确认”。");
  }

  function toast(message, isError = false) {
    const node = document.createElement("div");
    node.className = `toast${isError ? " is-error" : ""}`;
    node.textContent = message;
    $("#toastStack").appendChild(node);
    window.setTimeout(() => node.remove(), 3600);
  }

  function showDialog(dialog) {
    if (!dialog.open) dialog.showModal();
  }

  function closeDialog(dialog) {
    if (dialog?.open) dialog.close();
  }

  function setFiles(files) {
    const accepted = Array.from(files).filter((file) => file.type.startsWith("video/") || /\.(mp4|mov|webm)$/i.test(file.name));
    const merged = [...uploadFiles, ...accepted].filter((file, index, list) => {
      return list.findIndex((item) => item.name === file.name && item.size === file.size) === index;
    }).slice(0, 2);
    uploadFiles = merged;
    el.fileError.hidden = true;
    if (files.length && accepted.length < files.length) {
      el.fileError.textContent = "已忽略非视频文件；支持 MP4、MOV、WebM。";
      el.fileError.hidden = false;
    }
    renderFileList();
  }

  function renderFileList() {
    el.fileList.hidden = uploadFiles.length === 0;
    el.fileList.innerHTML = "";
    uploadFiles.forEach((file, index) => {
      const row = document.createElement("div");
      row.className = "file-row";
      row.innerHTML = `
        <div class="file-row-copy">
          <strong>${escapeHtml(file.name)}</strong>
          <span>${index === 0 ? "CAM-01" : "CAM-02"} · ${formatBytes(file.size)}</span>
        </div>
        <button class="file-remove" type="button" aria-label="移除 ${escapeAttribute(file.name)}">×</button>
      `;
      $(".file-remove", row).addEventListener("click", () => {
        uploadFiles.splice(index, 1);
        renderFileList();
      });
      el.fileList.appendChild(row);
    });
    toggleCameraConfig(1, uploadFiles.length > 1);
    el.submitUploadBtn.disabled = uploadFiles.length === 0;
    el.submitUploadBtn.title = uploadFiles.length ? "提交至本地 API，或在服务离线时显示错误原因" : "请先选择至少一段视频";
  }

  function toggleCameraConfig(index, enabled) {
    const fieldset = $(`[data-camera-config="${index}"]`);
    fieldset.classList.toggle("is-disabled", !enabled);
    $$("input", fieldset).forEach((input) => {
      input.disabled = !enabled;
    });
  }

  function formatBytes(bytes) {
    if (!bytes) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    const index = Math.min(units.length - 1, Math.floor(Math.log(bytes) / Math.log(1024)));
    return `${(bytes / Math.pow(1024, index)).toFixed(index ? 1 : 0)} ${units[index]}`;
  }

  function resetUploadUi() {
    el.uploadStep.hidden = false;
    el.uploadProgress.hidden = true;
    el.uploadError.hidden = true;
    el.jobProgressFill.style.width = "0%";
    el.progressPercent.textContent = "0%";
    el.progressStage.textContent = "正在创建任务";
    el.progressMessage.textContent = "上传文件到本地 API…";
    el.submitUploadBtn.disabled = uploadFiles.length === 0;
    el.submitUploadBtn.title = uploadFiles.length ? "提交至本地 API" : "请先选择至少一段视频";
    $("span", el.submitUploadBtn).textContent = "开始分析";
  }

  async function submitUpload(event) {
    event.preventDefault();
    if (!uploadFiles.length) {
      el.fileError.textContent = "请先选择 1–2 段视频。";
      el.fileError.hidden = false;
      return;
    }
    const apiBase = $("#apiBaseInput").value.trim().replace(/\/+$/, "");
    if (!apiBase) {
      el.fileError.textContent = "请填写本地 API 地址。";
      el.fileError.hidden = false;
      return;
    }
    const cameraConfigs = uploadFiles.map((_file, index) => ({
      name: $(`#cameraName${index}`).value.trim() || `机位${index + 1}`,
      start_time: $(`#cameraStart${index}`).value || null,
      offset_seconds: Number($(`#cameraOffset${index}`).value || 0)
    }));
    const capacities = getCapacities();
    const formData = new FormData();
    uploadFiles.forEach((file) => formData.append("files", file, file.name));
    formData.append("cameras", JSON.stringify(cameraConfigs));
    formData.append("config", JSON.stringify({
      sampling_interval_seconds: Number($("#sampleIntervalInput").value),
      capacities,
      capacity_status: "pending_user_confirmation",
      corridor_description: $("#corridorInput").value.trim(),
      include_boxes: true,
      output_contract: "api_contract_v1"
    }));

    el.submitUploadBtn.disabled = true;
    $("span", el.submitUploadBtn).textContent = "正在提交";
    el.uploadStep.hidden = true;
    el.uploadProgress.hidden = false;
    el.uploadError.hidden = true;
    el.progressStage.textContent = "正在创建任务";
    el.progressMessage.textContent = "上传文件到本地 API…";
    el.jobIdText.textContent = "等待返回";

    try {
      const response = await fetch(`${apiBase}/api/jobs`, {
        method: "POST",
        body: formData
      });
      if (!response.ok) {
        throw new Error(`POST /api/jobs 返回 ${response.status} ${response.statusText}`);
      }
      const payload = await response.json();
      if (!payload.job_id) throw new Error("API 响应缺少 job_id。");
      lastJobPayload = { apiBase, payload };
      el.jobIdText.textContent = payload.job_id;
      updateProgress({ progress: 0, stage: "queued", message: "任务已创建，等待分析引擎。", job_id: payload.job_id });
      pollJob(apiBase, payload.job_id, ++pollToken);
    } catch (error) {
      showUploadError(error, apiBase);
    }
  }

  function updateProgress(payload) {
    const progress = Math.max(0, Math.min(1, Number(payload.progress) || 0));
    const percent = Math.round(progress * 100);
    el.jobProgressFill.style.width = `${percent}%`;
    el.progressPercent.textContent = `${percent}%`;
    el.progressStage.textContent = payload.stage || payload.status || "分析中";
    el.progressMessage.textContent = payload.message || "正在等待后端返回进度…";
    if (payload.job_id) el.jobIdText.textContent = payload.job_id;
  }

  async function pollJob(apiBase, jobId, token) {
    if (token !== pollToken) return;
    try {
      const response = await fetch(`${apiBase}/api/jobs/${encodeURIComponent(jobId)}`, { cache: "no-store" });
      if (!response.ok) throw new Error(`GET /api/jobs/${jobId} 返回 ${response.status}`);
      const payload = await response.json();
      updateProgress({ ...payload, job_id: jobId });
      if (["needs_review", "complete"].includes(payload.status)) {
        await finishRemoteJob(apiBase, jobId, payload, token);
        return;
      }
      if (payload.status === "failed") {
        throw new Error(payload.message || "后端将任务标记为 failed。");
      }
      pollTimer = window.setTimeout(() => pollJob(apiBase, jobId, token), 1200);
    } catch (error) {
      showUploadError(error, apiBase);
    }
  }

  async function finishRemoteJob(apiBase, jobId, jobPayload, token) {
    if (token !== pollToken) return;
    el.progressStage.textContent = "正在载入时间轴";
    el.progressMessage.textContent = "读取 GET /api/jobs/{job_id}/timeline…";
    const response = await fetch(`${apiBase}/api/jobs/${encodeURIComponent(jobId)}/timeline`, { cache: "no-store" });
    if (!response.ok) throw new Error(`GET /timeline 返回 ${response.status}`);
    const payload = await response.json();
    const adapted = adaptRemoteTimeline(payload, apiBase, { ...jobPayload, job_id: jobPayload.job_id || jobId });
    if (!adapted || !adapted.samples.length) {
      throw new Error("timeline 已返回，但没有可识别的视频时间/机位计数字段。");
    }
    activeData = adapted;
    state.time = adapted.samples[0].time;
    state.reviews = {};
    state.evidenceFilter = "all";
    el.modePill.innerHTML = '<span class="status-dot"></span><span>API JOB · LIVE</span>';
    if (playing) setPlayState(false);
    renderAll();
    renderStats();
    closeDialog(el.uploadDialog);
    toast("后端时间轴已载入；未复核项保持待复核状态。");
  }

  function adaptRemoteTimeline(payload, apiBase, jobPayload) {
    let rows = Array.isArray(payload)
      ? payload
      : payload?.timeline || payload?.points || payload?.samples || payload?.data;
    if (!Array.isArray(rows) || !rows.length) return null;

    const cameras = DEMO.cameras.map((camera, index) => ({
      ...camera,
      id: camera.id,
      code: camera.code || `CAM-${index + 1}`
    }));
    const grouped = new Map();
    rows.forEach((row) => {
      const time = parseTimelineTime(row);
      if (!Number.isFinite(time)) return;
      const cameraId = inferCameraId(row, cameras);
      if (!cameraId) return;
      if (!grouped.has(time)) {
        grouped.set(time, { time, note: row.note || row.message || "后端时间轴样本。" });
      }
      const target = grouped.get(time);
      const counts = row.counts || row;
      const reviewCount = Number(row.review_count ?? row.reviews ?? 0);
      const vehicles = Array.isArray(row.vehicles) ? row.vehicles : [];
      const boxes = vehicles.map(normaliseRemoteBox).filter(Boolean);
      target[cameraId] = {
        total: Number(counts.total ?? sumTypeCounts(counts)),
        large: Number(counts.large ?? 0),
        medium: Number(counts.medium ?? 0),
        small: Number(counts.small ?? 0),
        unknown: Number(counts.unknown ?? 0),
        review: reviewCount > 0 || vehicles.some((vehicle) => vehicle.review || vehicle.status === "review"),
        boxes,
        vehicles: vehicles.map((vehicle) => ({
          ...vehicle,
          crop_url: absoluteUrl(vehicle.crop_url || vehicle.cropUrl, apiBase),
          frame_url: absoluteUrl(row.frame_url || row.snapshot_url || row.image_url, apiBase)
        })),
        frameUrl: absoluteUrl(row.frame_url || row.snapshot_url || row.image_url, apiBase)
      };
    });
    const samples = Array.from(grouped.values()).sort((a, b) => a.time - b.time);
    const maxTime = Math.max(...samples.map((sample) => sample.time));
    const duration = Number(jobPayload.duration_seconds || payload.duration_seconds || maxTime || 2659);
    const startTime = jobPayload.start_time || payload.start_time || DEMO.dataset.startTime;
    return {
      ...DEMO,
      remote: true,
      cameras,
      samples,
      dataset: {
        ...DEMO.dataset,
        id: jobPayload.job_id || payload.job_id || "remote-job",
        label: "后端分析任务",
        status: jobPayload.status === "complete" ? "API / complete" : "API / needs review",
        source: "GET /api/jobs/{job_id}/timeline",
        startTime,
        durationSeconds: duration,
        apiBase,
        jobId: jobPayload.job_id || payload.job_id,
        boxStatus: samples.some((sample) => cameras.some((camera) => sampleCamera(sample, camera.id).boxes.length)) ? "available" : "unavailable",
        boxMessage: samples.some((sample) => cameras.some((camera) => sampleCamera(sample, camera.id).boxes.length)) ? "" : "框待后端返回"
      }
    };
  }

  function parseTimelineTime(row) {
    if (Number.isFinite(Number(row.video_seconds))) return Number(row.video_seconds);
    if (Number.isFinite(Number(row.time_seconds))) return Number(row.time_seconds);
    if (Number.isFinite(Number(row.time)) && !String(row.time).includes(":")) return Number(row.time);
    if (Number.isFinite(Number(row.video_time)) && !String(row.video_time).includes(":")) return Number(row.video_time);
    const raw = String(row.video_time || row.video_clock || "");
    const parts = raw.split(":").map(Number);
    if (parts.every(Number.isFinite) && parts.length >= 2) {
      return parts.length === 3
        ? parts[0] * 3600 + parts[1] * 60 + parts[2]
        : parts[0] * 60 + parts[1];
    }
    return NaN;
  }

  function inferCameraId(row, cameras) {
    const cameraValue = row.camera_id || row.camera?.id || row.camera?.name || row.camera || row.cameraId || "";
    const raw = String(cameraValue).toLowerCase();
    if (raw.includes("north") || raw.includes("北")) return "north";
    if (raw.includes("south") || raw.includes("南")) return "south";
    return cameras[0]?.id;
  }

  function sumTypeCounts(counts) {
    return ["large", "medium", "small", "unknown"].reduce((sum, type) => sum + Number(counts[type] || 0), 0);
  }

  function normaliseRemoteBox(vehicle) {
    if (!vehicle) return null;
    const raw = vehicle.box || vehicle.bbox || vehicle.rect;
    if (!raw) return null;
    let rect = raw;
    if (Array.isArray(raw) && raw.length >= 4) {
      const [x1, y1, x2, y2] = raw.map(Number);
      const normalized = x2 <= 1 && y2 <= 1;
      rect = normalized
        ? { x: x1, y: y1, w: x2 - x1, h: y2 - y1 }
        : { x: x1 / 1280, y: y1 / 960, w: (x2 - x1) / 1280, h: (y2 - y1) / 960 };
    } else {
      const x = Number(raw.x);
      const y = Number(raw.y);
      const w = Number(raw.w ?? raw.width);
      const h = Number(raw.h ?? raw.height);
      const normalized = [x, y, w, h].every((value) => value >= 0 && value <= 1);
      rect = normalized
        ? { x, y, w, h }
        : { x: x / 1280, y: y / 960, w: w / 1280, h: h / 960 };
    }
    if (!isReliableBox(rect)) return null;
    return {
      id: vehicle.vehicle_id || vehicle.id,
      type: vehicle.size || vehicle.type || "unknown",
      rect
    };
  }

  function absoluteUrl(url, base) {
    if (!url) return "";
    try {
      return new URL(url, `${base}/`).toString();
    } catch (_error) {
      return url;
    }
  }

  function showUploadError(error, apiBase) {
    el.progressStage.textContent = "分析服务未连接";
    el.progressPercent.textContent = "—";
    el.progressMessage.textContent = "静态演示数据仍然保留，下面是后端连接原因。";
    el.uploadError.hidden = false;
    const reason = String(error?.message || "请求失败").replace(/[。.!！]+$/, "");
    el.uploadErrorMessage.textContent = `${reason}。请启动本地服务并检查 ${apiBase} 的 CORS 设置。`;
    el.submitUploadBtn.disabled = false;
    $("span", el.submitUploadBtn).textContent = "重试提交";
    el.retryUploadBtn.textContent = "返回表单重试";
  }

  function makeFramePlaceholder(label) {
    const text = String(label || "无样帧").replace(/[<>&"']/g, "");
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="960"><rect width="100%" height="100%" fill="#07151c"/><path d="M0 0h1280v960H0z" fill="none" stroke="#28434a" stroke-width="2"/><text x="640" y="470" fill="#6e8b90" font-family="sans-serif" font-size="28" text-anchor="middle">后端未返回样帧</text><text x="640" y="512" fill="#48e3c5" font-family="sans-serif" font-size="20" text-anchor="middle">${text}</text></svg>`;
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  }

  function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;"
    }[char]));
  }

  function escapeAttribute(value) {
    return escapeHtml(value);
  }

  function bindEvents() {
    el.playBtn.addEventListener("click", () => {
      if (!playing && state.time >= activeData.dataset.durationSeconds) state.time = 0;
      setPlayState(!playing);
      renderTimeDependent({ chart: false });
    });
    el.prevBtn.addEventListener("click", () => jumpToSample(-1));
    el.nextBtn.addEventListener("click", () => jumpToSample(1));
    el.scrubber.addEventListener("input", (event) => {
      setTime(event.target.value);
    });
    el.speedSelect.addEventListener("change", (event) => {
      state.speed = Number(event.target.value);
      toast(`播放速度 ${state.speed}×。`);
    });

    $$("[data-view-mode]").forEach((button) => {
      button.addEventListener("click", () => {
        state.viewMode = button.dataset.viewMode;
        $$("[data-view-mode]").forEach((item) => {
          const active = item.dataset.viewMode === state.viewMode;
          item.classList.toggle("is-active", active);
          item.setAttribute("aria-pressed", active ? "true" : "false");
        });
        renderTimeDependent({ chart: false });
      });
    });

    [$("#aboutBtn"), $("#noticeAboutBtn"), $("#footerAboutBtn")].forEach((button) => {
      button.addEventListener("click", () => showDialog(el.infoDialog));
    });
    [$("#capacityBtn"), $("#capacityInlineBtn")].forEach((button) => {
      button.addEventListener("click", () => {
        fillCapacityInputs();
        openDrawer("capacity");
      });
    });
    $("#saveCapacityBtn").addEventListener("click", saveCapacity);
    $("#resetCapacityBtn").addEventListener("click", resetCapacity);

    $$("[data-type-filter]").forEach((button) => {
      button.addEventListener("click", () => {
        const items = evidenceItems().filter((item) => item.type === button.dataset.typeFilter);
        if (!items.length) {
          toast(`当前采样帧没有${TYPE_META[button.dataset.typeFilter]?.label || ""}车辆证据。`);
          return;
        }
        setEvidenceFilter("all");
        openEvidence(items[0]);
      });
    });
    $$("[data-evidence-filter]").forEach((button) => {
      button.addEventListener("click", () => setEvidenceFilter(button.dataset.evidenceFilter));
    });
    $("#dedupReviewBtn").addEventListener("click", () => openEvidence(dedupEvidence()));
    $("#openSampleReviewBtn").addEventListener("click", () => {
      const sample = nearestSample();
      const items = evidenceItems().filter((item) => evidenceFilterGroup(item.status) === "review");
      if (items.length) {
        openEvidence(items[0]);
      } else {
        openEvidence(dedupEvidence());
      }
    });

    $$("[data-review-action]").forEach((button) => {
      button.addEventListener("click", () => applyReviewAction(button.dataset.reviewAction));
    });
    $("#reclassifyBtn").addEventListener("click", applyReclassification);

    $$("[data-bucket]").forEach((button) => {
      button.addEventListener("click", () => {
        state.bucketSeconds = Number(button.dataset.bucket);
        $$("[data-bucket]").forEach((item) => {
          const active = item.dataset.bucket === button.dataset.bucket;
          item.classList.toggle("is-active", active);
          item.setAttribute("aria-pressed", active ? "true" : "false");
        });
        renderStats();
      });
    });
    $("#exportBtn").addEventListener("click", exportCsv);
    $("#jumpLatestBtn").addEventListener("click", () => {
      setTime(activeData.samples[activeData.samples.length - 1].time);
      toast(`已跳到最后一个真实采样帧 ${formatVideoTime(state.time)}。`);
    });

    el.drawerBackdrop.addEventListener("click", closeDrawers);
    $$("[data-close-drawer]").forEach((button) => button.addEventListener("click", closeDrawers));

    $("#uploadBtn").addEventListener("click", () => {
      resetUploadUi();
      renderFileList();
      showDialog(el.uploadDialog);
    });
    $$("[data-close-dialog]").forEach((button) => {
      button.addEventListener("click", () => {
        const id = button.dataset.closeDialog;
        closeDialog(id === "upload" ? el.uploadDialog : el.infoDialog);
        if (id === "upload") {
          pollToken += 1;
          window.clearTimeout(pollTimer);
        }
      });
    });
    el.uploadDialog.addEventListener("close", () => {
      pollToken += 1;
      window.clearTimeout(pollTimer);
    });
    $("#cancelUploadBtn").addEventListener("click", () => {
      closeDialog(el.uploadDialog);
      resetUploadUi();
    });

    el.videoInput.addEventListener("change", () => {
      setFiles(el.videoInput.files);
      el.videoInput.value = "";
    });
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
    el.dropzone.addEventListener("drop", (event) => setFiles(event.dataTransfer.files));
    el.uploadForm.addEventListener("submit", submitUpload);
    el.retryUploadBtn.addEventListener("click", () => {
      resetUploadUi();
      pollToken += 1;
      window.clearTimeout(pollTimer);
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeDrawers();
      const tag = document.activeElement?.tagName;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag) || el.uploadDialog.open || el.infoDialog.open) return;
      if (event.code === "Space") {
        event.preventDefault();
        el.playBtn.click();
      }
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        jumpToSample(-1);
      }
      if (event.key === "ArrowRight") {
        event.preventDefault();
        jumpToSample(1);
      }
    });
  }

  function init() {
    fillCapacityInputs();
    updateLocalSaveState();
    bindEvents();
    const firstSamples = activeData.samples.filter((sample) => sample.time <= 600);
    if (firstSamples.some((sample) => sample.time === 600)) state.time = 600;
    renderAll();
    renderStats();
    toggleCameraConfig(1, false);
  }

  init();
})();
