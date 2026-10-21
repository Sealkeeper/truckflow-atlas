const sampleTimes = [5, 300, 600, 900, 1200, 1500, 1800, 2100, 2400, 2600];

const cameraCounts = {
  north: [
    { total: 3, large: 3, medium: 0, small: 0, review: false },
    { total: 3, large: 3, medium: 0, small: 0, review: false },
    { total: 4, large: 4, medium: 0, small: 0, review: false },
    { total: 3, large: 3, medium: 0, small: 0, review: false },
    { total: 3, large: 3, medium: 0, small: 0, review: false },
    { total: 2, large: 2, medium: 0, small: 0, review: false },
    { total: 2, large: 2, medium: 0, small: 0, review: false },
    { total: 2, large: 2, medium: 0, small: 0, review: false },
    { total: 3, large: 3, medium: 0, small: 0, review: false },
    { total: 2, large: 2, medium: 0, small: 0, review: false }
  ],
  south: [
    { total: 3, large: 2, medium: 1, small: 0, review: true },
    { total: 4, large: 3, medium: 1, small: 0, review: false },
    { total: 5, large: 3, medium: 2, small: 0, review: true },
    { total: 5, large: 3, medium: 2, small: 0, review: true },
    { total: 5, large: 3, medium: 2, small: 0, review: true },
    { total: 5, large: 3, medium: 2, small: 0, review: true },
    { total: 4, large: 2, medium: 2, small: 0, review: true },
    { total: 4, large: 2, medium: 2, small: 0, review: true },
    { total: 3, large: 2, medium: 1, small: 0, review: true },
    { total: 3, large: 2, medium: 1, small: 0, review: true }
  ]
};

const formatTime = (seconds) => {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return [h, m, s].map((value) => String(value).padStart(2, "0")).join(":");
};

const shortTime = (seconds) => formatTime(seconds).replace(/^00:/, "");

let selectedIndex = 4;
let currentView = "original";
let toastTimer;

const workspace = document.querySelector(".camera-workspace");
const range = document.querySelector("#timeRange");
const samplesRoot = document.querySelector("#timelineSamples");
const toast = document.querySelector("#toast");

const capacityInputs = {
  large: document.querySelector("#capLarge"),
  medium: document.querySelector("#capMedium"),
  small: document.querySelector("#capSmall")
};

function showToast(message) {
  window.clearTimeout(toastTimer);
  toast.textContent = message;
  toast.classList.add("is-visible");
  toastTimer = window.setTimeout(() => toast.classList.remove("is-visible"), 2400);
}

function currentCounts() {
  const north = cameraCounts.north[selectedIndex];
  const south = cameraCounts.south[selectedIndex];
  return {
    north,
    south,
    combined: {
      total: north.total + south.total,
      large: north.large + south.large,
      medium: north.medium + south.medium,
      small: north.small + south.small
    }
  };
}

function updateLoad() {
  const { combined } = currentCounts();
  const capacities = {
    large: Math.max(1, Number(capacityInputs.large.value) || 1),
    medium: Math.max(1, Number(capacityInputs.medium.value) || 1),
    small: Math.max(1, Number(capacityInputs.small.value) || 1)
  };
  const ratio =
    combined.large / capacities.large +
    combined.medium / capacities.medium +
    combined.small / capacities.small;
  const percentage = Math.round(ratio * 100);

  document.querySelector("[data-load-value]").textContent = String(percentage);
  document.querySelector("[data-load-bar]").style.width = `${Math.min(percentage, 100)}%`;
  document.querySelector("[data-formula-large]").textContent = String(combined.large);
  document.querySelector("[data-formula-medium]").textContent = String(combined.medium);
  document.querySelector("[data-formula-small]").textContent = String(combined.small);
  document.querySelector('[data-capacity-value="large"]').textContent = String(capacities.large);
  document.querySelector('[data-capacity-value="medium"]').textContent = String(capacities.medium);
  document.querySelector('[data-capacity-value="small"]').textContent = String(capacities.small);
}

function updateTimelineState() {
  document.querySelectorAll(".sample-button").forEach((button, index) => {
    const active = index === selectedIndex;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}

function updateCamera(camera) {
  const card = document.querySelector(`[data-camera="${camera}"]`);
  const counts = cameraCounts[camera][selectedIndex];
  const seconds = sampleTimes[selectedIndex];
  const image = card.querySelector("[data-frame]");
  const cameraName = camera === "north" ? "天花北" : "天花南";
  const review = counts.review || (camera === "south" && seconds !== 300);
  const reviewLabel = card.querySelector("[data-review-state]");

  image.src = `/assets/frames/${camera}_${seconds}.jpg`;
  image.alt = `${cameraName}机位 ${formatTime(seconds)} 真实画面`;
  card.querySelector("[data-count]").textContent = String(counts.total);
  card.querySelector('[data-type="large"]').textContent = String(counts.large);
  card.querySelector('[data-type="medium"]').textContent = String(counts.medium);
  card.querySelector('[data-type="small"]').textContent = String(counts.small);
  card.querySelector("[data-timecode]").textContent = formatTime(seconds);
  card.querySelector("[data-camera-label]").textContent = `${cameraName} · ${currentView === "original" ? "原始画面" : "分析画面"}`;
  reviewLabel.classList.toggle("is-review", review);
  reviewLabel.querySelector("span:last-child").textContent = review ? "通道边界待复核" : "AI 初标已记录（待终审）";
}

function render(seconds, shouldToast = false) {
  const nextIndex = sampleTimes.indexOf(seconds);
  if (nextIndex === -1) return;
  selectedIndex = nextIndex;
  const { north, south, combined } = currentCounts();

  range.value = String(selectedIndex);
  range.style.background = `linear-gradient(90deg, var(--teal) ${selectedIndex * (100 / 9)}%, rgba(143, 166, 170, 0.22) ${selectedIndex * (100 / 9)}%)`;
  document.querySelectorAll("[data-current-time]").forEach((node) => {
    node.textContent = formatTime(seconds);
  });
  document.querySelector("[data-sample-index]").textContent = String(selectedIndex + 1).padStart(2, "0");
  document.querySelector("[data-north-count]").textContent = String(north.total);
  document.querySelector("[data-south-count]").textContent = String(south.total);
  document.querySelector('[data-total-type="large"]').textContent = String(combined.large);
  document.querySelector('[data-total-type="medium"]').textContent = String(combined.medium);
  document.querySelector('[data-total-type="small"]').textContent = String(combined.small);

  updateCamera("north");
  updateCamera("south");
  updateTimelineState();
  updateLoad();

  if (shouldToast) {
    showToast(`已切换到 ${formatTime(seconds)} 的真实双机位帧`);
  }
}

function createSampleButtons() {
  sampleTimes.forEach((seconds, index) => {
    const button = document.createElement("button");
    button.className = "sample-button";
    button.type = "button";
    button.dataset.time = String(seconds);
    button.setAttribute("aria-label", `切换到 ${formatTime(seconds)}`);
    button.innerHTML = `<span>${shortTime(seconds)}</span><span>${cameraCounts.north[index].total}/${cameraCounts.south[index].total}</span>`;
    button.addEventListener("click", () => render(seconds, true));
    samplesRoot.append(button);
  });
}

range.addEventListener("input", () => render(sampleTimes[Number(range.value)]));

document.querySelectorAll(".segment").forEach((button) => {
  button.addEventListener("click", () => {
    currentView = button.dataset.view;
    document.querySelectorAll(".segment").forEach((segment) => {
      const active = segment === button;
      segment.classList.toggle("is-active", active);
      segment.setAttribute("aria-selected", String(active));
    });
    workspace.classList.toggle("is-analysis", currentView === "analysis");
    updateCamera("north");
    updateCamera("south");
    if (currentView === "analysis") {
      showToast("分析图层尚未接入；车辆框待后端返回");
    }
  });
});

document.querySelector("#analysisButton").addEventListener("click", () => {
  document.querySelector('[data-view="analysis"]').click();
  workspace.scrollIntoView({ behavior: "smooth", block: "start" });
});

document.querySelector("#evidenceButton").addEventListener("click", () => {
  showToast("口径：画面内可辨识货车逐机位计数；牵引车与挂车合为一辆。跨机位唯一身份尚未合并。");
});

document.querySelector("#playButton").addEventListener("click", () => {
  const nextIndex = (selectedIndex + 1) % sampleTimes.length;
  render(sampleTimes[nextIndex]);
  showToast("样例时间轴推进到下一个抽样时刻");
});

Object.values(capacityInputs).forEach((input) => {
  input.addEventListener("input", updateLoad);
  input.addEventListener("change", () => {
    input.value = String(Math.max(1, Math.min(30, Math.round(Number(input.value) || 1))));
    updateLoad();
  });
});

createSampleButtons();
render(sampleTimes[selectedIndex]);
