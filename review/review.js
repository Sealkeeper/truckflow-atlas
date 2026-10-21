const STORAGE_KEY = "truckflow.review.final.v1";

const state = {
  data: null,
  answers: {}
};

function loadDraft() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
  } catch {
    return {};
  }
}

function saveDraft() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.answers));
}

function answerFor(key, sample) {
  if (!state.answers[key]) {
    state.answers[key] = {
      count: sample.provisionalTotal,
      corridorEdge: "unset",
      reviewed: false,
      note: ""
    };
  }
  return state.answers[key];
}

function updateProgress() {
  const total = state.data.samples.length;
  const done = state.data.samples.filter(
    (sample) => state.answers[sample.key]?.reviewed
  ).length;
  document.querySelector("#progressPill").textContent = `已复核 ${done} / ${total}`;
  document.querySelector("#barProgress").textContent = `${done} / ${total}`;
}

function renderCard(sample) {
  const answer = answerFor(sample.key, sample);
  const card = document.createElement("article");
  card.className = "card";
  card.dataset.key = sample.key;
  card.dataset.review = String(sample.reviewFlag);

  const cameraLabel = sample.camera === "north" ? "天花北" : "天花南";
  const timeLabel = formatTime(sample.time);
  const badge = sample.reviewFlag
    ? `<span class="badge review">初标待重点复核</span>`
    : `<span class="badge">初标 ${sample.provisionalTotal} 辆</span>`;

  const frames = sample.frames
    .map(
      (frame) => `
        <figure data-src="${frame.path}">
          <img src="${frame.path}" alt="${sample.key} ${frame.offset}s" loading="lazy">
          <figcaption>${frame.offset > 0 ? "+" : ""}${frame.offset}s</figcaption>
        </figure>`
    )
    .join("");

  const video = sample.clip
    ? `<video controls preload="metadata" poster="${sample.frames[2].path}" src="${sample.clip}"></video>
       <div class="meta">视频从 ${formatTime(sample.clipStart)} 开始；采样时刻在视频第 ${formatTime(sample.time - sample.clipStart)}。</div>`
    : `<div class="meta">该时刻没有单独视频片段；可看五张连续帧判断车体是否持续存在。</div>`;

  const corridor =
    sample.camera === "south"
      ? `
        <label>底边红色货厢：
          <select class="corridor">
            <option value="unset">未判断</option>
            <option value="included">计入本通道</option>
            <option value="excluded">不计入</option>
            <option value="not_visible">本帧未出现</option>
          </select>
        </label>`
      : "";

  card.innerHTML = `
    <div class="card-head">
      <div>
        <h2>${cameraLabel} · ${timeLabel}</h2>
        <div class="meta">${sample.key} · 视频时间 ${formatTime(sample.time)} · 初标 ${sample.provisionalTotal} 辆</div>
      </div>
      ${badge}
    </div>
    <div class="strip">${frames}</div>
    ${video}
    <div class="ask">请确认此刻画面内的独立货车数量。相邻帧用来区分“同一辆车持续存在”与“把车头/货厢拆成两辆”。</div>
    <div class="controls">
      <label>复核数量 <input type="number" class="count" min="0" max="20" value="${answer.count}"></label>
      <button class="ghost same">沿用初标 ${sample.provisionalTotal}</button>
      ${corridor}
    </div>
    <label class="check"><input type="checkbox" class="reviewed done" ${answer.reviewed ? "checked" : ""}> 我已复核此帧</label>
    <textarea class="note" placeholder="可选：哪几辆是什么车、哪辆被遮挡、边界货厢怎么判断">${answer.note}</textarea>
  `;

  card.querySelector(".count").addEventListener("input", (event) => {
    answer.count = Number(event.target.value);
    saveDraft();
  });
  card.querySelector(".same").addEventListener("click", () => {
    answer.count = sample.provisionalTotal;
    card.querySelector(".count").value = sample.provisionalTotal;
    saveDraft();
  });
  const corridorSelect = card.querySelector(".corridor");
  if (corridorSelect) {
    corridorSelect.value = answer.corridorEdge;
    corridorSelect.addEventListener("change", (event) => {
      answer.corridorEdge = event.target.value;
      saveDraft();
    });
  }
  card.querySelector(".reviewed").addEventListener("change", (event) => {
    answer.reviewed = event.target.checked;
    saveDraft();
    updateProgress();
  });
  card.querySelector(".note").addEventListener("input", (event) => {
    answer.note = event.target.value;
    saveDraft();
  });
  card.querySelectorAll("figure").forEach((figure) => {
    figure.addEventListener("click", () => {
      const lightbox = document.querySelector("#lightbox");
      document.querySelector("#lightboxImage").src = figure.dataset.src;
      lightbox.classList.add("open");
    });
  });

  return card;
}

function formatTime(seconds) {
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(rest).padStart(2, "0")}`;
}

function exportAnswers() {
  const rows = state.data.samples.map((sample) => {
    const answer = answerFor(sample.key, sample);
    return {
      key: sample.key,
      camera: sample.camera,
      time: sample.time,
      provisional_total: sample.provisionalTotal,
      final_total: answer.count,
      delta_from_provisional: answer.count - sample.provisionalTotal,
      corridor_edge: answer.corridorEdge,
      reviewed: answer.reviewed,
      note: answer.note
    };
  });
  const payload = {
    schema: "truckflow-final-review-v1",
    exported_at: new Date().toISOString(),
    reviewer: "user-final-review",
    source_status: state.data.status,
    definition: state.data.countDefinition,
    complete: rows.every((row) => row.reviewed),
    samples: rows
  };
  const blob = new Blob([`${JSON.stringify(payload, null, 2)}\n`], {
    type: "application/json"
  });
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = `truckflow-final-review-${Date.now()}.json`;
  link.click();
  URL.revokeObjectURL(link.href);
}

async function boot() {
  const response = await fetch("./review-data.json", { cache: "no-store" });
  if (!response.ok) throw new Error(`review-data.json 加载失败：${response.status}`);
  state.data = await response.json();
  const saved = loadDraft();
  Object.assign(state.answers, saved);
  const grid = document.querySelector("#grid");
  const ordered = [...state.data.samples].sort(
    (left, right) =>
      Number(right.reviewFlag) - Number(left.reviewFlag) ||
      left.time - right.time ||
      left.camera.localeCompare(right.camera)
  );
  ordered.forEach((sample) => grid.appendChild(renderCard(sample)));
  updateProgress();

  const focus = document.querySelector("#focus");
  focus.addEventListener("click", () => {
    const active = document.body.classList.toggle("focus-review");
    focus.textContent = active ? "查看全部 20 个时刻" : "只看待重点复核";
  });
  document.querySelector("#lightbox").addEventListener("click", () => {
    document.querySelector("#lightbox").classList.remove("open");
  });
  document.querySelector("#export").addEventListener("click", exportAnswers);
}

boot().catch((error) => {
  document.querySelector("#grid").innerHTML =
    `<div class="warn">复核台加载失败：${error.message}</div>`;
});
