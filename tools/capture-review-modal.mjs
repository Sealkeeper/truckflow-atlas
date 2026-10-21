import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { chromium } from "playwright-core";

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, "..");
const chromePath = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const baseUrl = process.env.REVIEW_BASE_URL || "http://127.0.0.1:4178/";
const reviewKey = "truckflow.workspace.review.v2";

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function preparePage(browser, viewport) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  await context.addInitScript((key) => window.localStorage.removeItem(key), reviewKey);
  const page = await context.newPage();
  const errors = [];
  const badResponses = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("response", (response) => {
    if (response.status() >= 400) badResponses.push(`${response.status()} ${response.url()}`);
  });
  await page.goto(baseUrl, { waitUntil: "networkidle" });
  if (viewport.width >= 1200) {
    await page.screenshot({
      path: path.join(repoRoot, "review", "review-entry-desktop.png"),
      animations: "disabled"
    });
  }
  await page.click("#openReviewBtn");
  await page.waitForSelector("#reviewDialog[open]");
  await page.waitForFunction(() => {
    const images = [...document.querySelectorAll("#reviewSouthCrop, #reviewNorthCrop")];
    return images.length >= 2 && images.every((image) => image.complete && image.naturalWidth > 0);
  });
  await page.waitForTimeout(250);
  return { context, page, errors, badResponses };
}

async function auditModal(page) {
  return page.evaluate(() => {
    const modal = document.querySelector("#reviewDialog");
    const body = modal.querySelector(".review-modal-body");
    const rect = modal.getBoundingClientRect();
    const clipped = [...modal.querySelectorAll("h2, h3, strong, .review-field-label, .review-evidence-caption")]
      .filter((node) => node.clientWidth > 0 && node.scrollWidth > node.clientWidth + 2)
      .map((node) => ({
        tag: node.tagName,
        text: node.textContent.trim().slice(0, 80),
        clientWidth: node.clientWidth,
        scrollWidth: node.scrollWidth
      }));
    return {
      viewport: { width: innerWidth, height: innerHeight },
      documentScrollWidth: document.documentElement.scrollWidth,
      modal: {
        x: Math.round(rect.x),
        y: Math.round(rect.y),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
        scrollWidth: modal.scrollWidth,
        clientWidth: modal.clientWidth
      },
      bodyScrollHeight: body.scrollHeight,
      bodyClientHeight: body.clientHeight,
      clipped,
      cropSources: [...modal.querySelectorAll(".review-evidence-stage img")].map((image) => ({
        src: image.getAttribute("src"),
        naturalWidth: image.naturalWidth,
        naturalHeight: image.naturalHeight
      }))
    };
  });
}

async function main() {
  const browser = await chromium.launch({ executablePath: chromePath, headless: true });
  const report = {};

  const desktop = await preparePage(browser, { width: 1440, height: 1000 });
  const { page } = desktop;
  await page.screenshot({
    path: path.join(repoRoot, "review", "review-modal-desktop.png"),
    animations: "disabled"
  });
  report.desktop = await auditModal(page);

  await page.fill("#reviewSouthCount", "3");
  await page.fill("#reviewNorthCount", "5");
  await page.fill("#reviewOverlapCount", "2");
  const autoTotal = await page.inputValue("#reviewTotalCount");
  assert(autoTotal === "6", `自动去重总数应为 6，实际为 ${autoTotal}`);
  assert((await page.textContent("#reviewFormula")).includes("南 3 + 北 5 − 重合 2 = 6 辆"), "公式文本不正确");

  await page.fill("#reviewTotalCount", "7");
  assert((await page.textContent("#reviewTotalMode")).trim() === "手填", "手填总数未切换状态");
  assert(await page.isVisible("#reviewFormulaWarning"), "手填总数与公式不一致时未显示警告");
  await page.click("#reviewFormulaReset");
  assert((await page.inputValue("#reviewTotalCount")) === "6", "按公式重算未恢复 6");

  await page.click("#reviewSaveBtn");
  await page.waitForTimeout(150);
  assert((await page.textContent("#reviewDraftState")).includes("共 1 次记录"), "保存记录数未更新");
  assert((await page.textContent("#auditUniqueTotal")).includes("6 辆"), "主页面跨机位唯一数未更新");

  await page.setInputFiles("#reviewAttachmentInput", path.join(repoRoot, "review", "crops", "south_600.jpg"));
  await page.waitForSelector("#reviewAttachmentPreview:not([hidden])");
  assert((await page.textContent("#reviewAttachmentName")).includes("south_600.jpg"), "标注图文件名未显示");

  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.click("#reviewExportBtn")
  ]);
  const exportPath = path.join(repoRoot, "review", "_review-export-check.json");
  await download.saveAs(exportPath);
  const exported = JSON.parse(fs.readFileSync(exportPath, "utf8"));
  const reviewedRow = exported.samples.find((row) => row.time === 600);
  assert(exported.schema === "truckflow-final-review-v2", "导出 schema 不是 v2");
  assert(reviewedRow.camera_counts.south === 3 && reviewedRow.camera_counts.north === 5, "导出南北计数错误");
  assert(reviewedRow.overlap === 2 && reviewedRow.unique_total === 6, "导出重合/去重计数错误");
  assert(reviewedRow.attachment_file === "south_600.jpg", "导出未记录标注图文件名");
  assert(reviewedRow.completed === true, "完整记录未标记 completed");
  report.exportCheck = {
    schema: exported.schema,
    reviewed_samples: exported.reviewed_samples,
    completed_samples: exported.completed_samples,
    row: reviewedRow
  };

  await page.click('#reviewDialog [data-review-original="south"]');
  await page.waitForSelector("#reviewEvidenceDialog[open]");
  const evidenceAudit = await page.evaluate(() => {
    const original = document.querySelector(".review-original-image");
    return {
      tabs: [...document.querySelectorAll("[data-evidence-tab]")].map((button) => button.textContent.trim()),
      original: original ? { width: original.naturalWidth, height: original.naturalHeight } : null
    };
  });
  assert(evidenceAudit.tabs.length === 3, "连续证据标签页不完整");
  assert(evidenceAudit.original?.width === 1280, "原图未按 1280 宽加载");
  await page.click('[data-evidence-tab="frames"]');
  const frameCount = await page.locator(".review-frame-strip img").count();
  assert(frameCount === 5, `连续帧应有 5 张，实际 ${frameCount}`);
  await page.screenshot({
    path: path.join(repoRoot, "review", "review-evidence-desktop.png"),
    animations: "disabled"
  });
  await page.click('[data-evidence-tab="video"]');
  const videoAudit = await page.evaluate(() => {
    const video = document.querySelector("#reviewEvidenceBody video");
    return video ? { src: video.getAttribute("src"), duration: video.duration } : null;
  });
  assert(videoAudit?.src?.includes("south_600.mp4"), "南机位 00:10:00 的 30 秒视频未加载");
  report.desktopEvidence = { ...evidenceAudit, frameCount, video: videoAudit };
  await page.locator("#reviewEvidenceDialog [data-close-evidence]").last().click();
  await page.waitForFunction(() => !document.querySelector("#reviewEvidenceDialog").open);

  await page.click("#reviewNextBtn");
  await page.waitForFunction(() => document.querySelector("#reviewVideoTime")?.textContent === "15:00");
  assert((await page.textContent("#reviewDraftState")).includes("共 1 次记录"), "切换时刻后记录数不应丢失");
  assert((await page.inputValue("#reviewSouthCount")) === "", "新时刻不应复用上一时刻的数量");
  await page.click("#reviewPrevBtn");
  await page.waitForFunction(() => document.querySelector("#reviewVideoTime")?.textContent === "10:00");
  assert((await page.inputValue("#reviewSouthCount")) === "3", "返回上一时刻后未恢复已保存数值");
  assert((await page.textContent("#reviewAttachmentName")).includes("south_600.jpg"), "返回上一时刻后标注图记录丢失");

  await page.click("#reviewDialog [data-close-review]");
  await page.waitForFunction(() => !document.querySelector("#reviewDialog").open);
  await page.click("#openSampleReviewBtn");
  await page.waitForSelector("#reviewDialog[open]");
  assert(!(await page.locator("#evidenceDrawer").isVisible()), "校验卡入口不应同时打开旧证据侧栏");
  await page.click("#reviewDialog [data-close-review]");
  await page.waitForFunction(() => !document.querySelector("#reviewDialog").open);
  await page.click("#dedupReviewBtn");
  await page.waitForSelector("#reviewDialog[open]");
  report.desktopNavigation = {
    next_time: "15:00",
    previous_restored_south: 3,
    drawer_opened: false
  };

  const sampleTimes = await page.evaluate(() => window.TRUCKFLOW_REVIEW_CONTEXT.getSamples().map((sample) => sample.time).sort((a, b) => a - b));
  await page.click("#reviewDialog [data-close-review]");
  await page.waitForFunction(() => !document.querySelector("#reviewDialog").open);
  await page.evaluate(() => window.TRUCKFLOW_REVIEW_CONTEXT.setSampleTime(5));
  await page.click("#openReviewBtn");
  await page.waitForFunction(() => document.querySelector("#reviewVideoTime")?.textContent === "00:05");
  const visited = [];
  for (let index = 1; index < sampleTimes.length; index += 1) {
    await page.click("#reviewNextBtn");
    const expected = await page.evaluate((time) => {
      const minutes = Math.floor(time / 60);
      const seconds = time % 60;
      return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
    }, sampleTimes[index]);
    await page.waitForFunction((time) => document.querySelector("#reviewVideoTime")?.textContent === time, expected);
    await page.waitForFunction(() => {
      const images = [...document.querySelectorAll("#reviewSouthCrop, #reviewNorthCrop")];
      return images.length === 2 && images.every((image) => image.complete && image.naturalWidth > 0);
    });
    const cropState = await page.evaluate(() => {
      const images = [...document.querySelectorAll("#reviewSouthCrop, #reviewNorthCrop")];
      return images.map((image) => ({
        src: image.getAttribute("src"),
        width: image.naturalWidth,
        height: image.naturalHeight
      }));
    });
    assert(cropState.length === 2 && cropState.every((item) => item.width > 0), `时刻 ${expected} 的机位裁剪图未加载`);
    visited.push(expected);
  }
  report.desktopAllSamples = { visited: visited.length + 1, lastTime: visited.at(-1) };

  report.desktop.errors = desktop.errors;
  report.desktop.badResponses = desktop.badResponses;
  await desktop.context.close();

  const mobile = await preparePage(browser, { width: 390, height: 844 });
  await mobile.page.screenshot({
    path: path.join(repoRoot, "review", "review-modal-mobile.png"),
    animations: "disabled"
  });
  report.mobile = await auditModal(mobile.page);
  await mobile.page.locator(".review-modal-body").evaluate((node) => {
    node.scrollTop = node.scrollHeight;
  });
  await mobile.page.screenshot({
    path: path.join(repoRoot, "review", "review-modal-mobile-bottom.png"),
    animations: "disabled"
  });
  report.mobile.errors = mobile.errors;
  report.mobile.badResponses = mobile.badResponses;
  await mobile.context.close();

  assert(report.desktop.documentScrollWidth <= 1440, "桌面页面出现横向滚动");
  assert(report.mobile.documentScrollWidth <= 390, "手机页面出现横向滚动");
  assert(report.desktop.errors.length === 0, `桌面控制台错误：${report.desktop.errors.join(" | ")}`);
  assert(report.mobile.errors.length === 0, `手机控制台错误：${report.mobile.errors.join(" | ")}`);
  assert(report.desktop.badResponses.length === 0, `桌面 4xx/5xx：${report.desktop.badResponses.join(" | ")}`);
  assert(report.mobile.badResponses.length === 0, `手机 4xx/5xx：${report.mobile.badResponses.join(" | ")}`);

  fs.writeFileSync(
    path.join(repoRoot, "review", "review-modal-audit.json"),
    `${JSON.stringify(report, null, 2)}\n`,
    "utf8"
  );
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
  process.exit();
});
