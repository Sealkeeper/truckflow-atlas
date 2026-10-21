const { chromium } = require("playwright");
const path = require("path");
const fs = require("fs");

const baseUrl = process.env.UI_BASE_URL || "http://127.0.0.1:4173/";
const root = path.resolve(__dirname, "..");
const screenshotDir = path.join(root, "assets", "ui");
fs.mkdirSync(screenshotDir, { recursive: true });

function invariant(condition, message) {
  if (!condition) throw new Error(message);
}

async function attachAudit(page, label, failures) {
  page.on("console", (message) => {
    if (message.type() === "error") failures.push(`${label} console: ${message.text()}`);
  });
  page.on("pageerror", (error) => failures.push(`${label} pageerror: ${error.message}`));
  page.on("requestfailed", (request) => {
    failures.push(`${label} request failed: ${request.url()} (${request.failure()?.errorText || "unknown"})`);
  });
  page.on("response", (response) => {
    if (response.status() >= 400) failures.push(`${label} HTTP ${response.status()}: ${response.url()}`);
  });
}

async function assertLayout(page, label, expectedViewportWidth) {
  const layout = await page.evaluate(() => ({
    viewportWidth: window.innerWidth,
    scrollWidth: document.documentElement.scrollWidth,
    bodyScrollWidth: document.body.scrollWidth,
    missingImages: Array.from(document.images)
      .filter((image) => !image.complete || image.naturalWidth === 0)
      .map((image) => image.currentSrc || image.src),
    unnamedButtons: Array.from(document.querySelectorAll("button"))
      .filter((button) => {
        const text = button.textContent.trim();
        const aria = button.getAttribute("aria-label");
        const title = button.getAttribute("title");
        return !text && !aria && !title;
      })
      .map((button) => button.outerHTML.slice(0, 160))
  }));
  invariant(layout.viewportWidth === expectedViewportWidth, `${label}: unexpected viewport ${layout.viewportWidth}`);
  invariant(layout.scrollWidth <= layout.viewportWidth + 1, `${label}: page overflows horizontally (${layout.scrollWidth}px)`);
  invariant(layout.scrollWidth <= layout.viewportWidth + 1, `${label}: document overflows horizontally (${layout.scrollWidth}px)`);
  invariant(layout.missingImages.length === 0, `${label}: broken images: ${layout.missingImages.join(", ")}`);
  invariant(layout.unnamedButtons.length === 0, `${label}: buttons without accessible names: ${layout.unnamedButtons.join(" | ")}`);
  return layout;
}

async function run() {
  const failures = [];
  const notes = [];
  const browser = await chromium.launch({ channel: "chrome", headless: true });
  const desktopContext = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    acceptDownloads: true
  });
  const desktop = await desktopContext.newPage();
  await attachAudit(desktop, "desktop", failures);
  await desktop.goto(baseUrl, { waitUntil: "networkidle" });
  await desktop.evaluate(() => localStorage.clear());
  await desktop.reload({ waitUntil: "networkidle" });

  await assertLayout(desktop, "desktop", 1440);
  await desktop.screenshot({ path: path.join(screenshotDir, "desktop-1440x1000.png") });
  await desktop.screenshot({ path: path.join(screenshotDir, "desktop-full.png"), fullPage: true });
  await desktop.locator(".metrics-grid").screenshot({ path: path.join(screenshotDir, "metrics-1440.png") });

  invariant(await desktop.locator("#visibleTotal").textContent() === "9", "Expected visible total 9 at 10:00");
  await desktop.locator('[data-view-mode="analysis"]').click();
  invariant(await desktop.locator("#northAnalysis .analysis-unavailable").isVisible(), "Analysis mode must show box-unavailable state");
  invariant((await desktop.locator("#northAnalysis").textContent()).includes("框待后端返回"), "Missing explicit box fallback text");
  invariant(await desktop.locator(".bbox").count() === 0, "No invented vehicle boxes are allowed");
  await desktop.locator(".camera-grid").screenshot({ path: path.join(screenshotDir, "analysis-mode.png") });
  await desktop.locator('[data-view-mode="original"]').click();

  await desktop.locator(".evidence-card").first().click();
  await desktop.waitForTimeout(280);
  invariant(await desktop.locator("#evidenceDrawer").evaluate((node) => node.classList.contains("is-open")), "Evidence drawer did not open");
  await desktop.locator('[data-review-action="confirm"]').click();
  const storedReviews = await desktop.evaluate(() => JSON.parse(localStorage.getItem("truckflow.workspace.reviews.v1") || "{}"));
  invariant(Object.keys(storedReviews).length === 1, "Review action did not write localStorage");
  await desktop.evaluate(() => { document.querySelector("#toastStack").innerHTML = ""; });
  await desktop.locator("#evidenceDrawer").screenshot({ path: path.join(screenshotDir, "evidence-drawer.png") });
  await desktop.locator('[data-close-drawer="evidence"]').click();

  await desktop.locator("#capacityBtn").click();
  await desktop.waitForTimeout(250);
  invariant((await desktop.locator("#capacityConfirmed").textContent()).includes("待用户确认"), "Capacity default is not marked pending");
  await desktop.evaluate(() => { document.querySelector("#toastStack").innerHTML = ""; });
  await desktop.locator("#capacityDrawer").screenshot({ path: path.join(screenshotDir, "capacity-drawer.png") });
  await desktop.locator('[data-close-drawer="capacity"]').click();

  await desktop.locator("#uploadBtn").click();
  invariant(await desktop.locator("#uploadDialog").evaluate((node) => node.open), "Upload modal did not open");
  invariant(await desktop.locator("#submitUploadBtn").isDisabled(), "Upload submit must be disabled without files");
  await desktop.locator("#uploadDialog").screenshot({ path: path.join(screenshotDir, "upload-modal.png") });
  await desktop.locator("#cancelUploadBtn").click();

  await desktop.locator('[data-evidence-filter="rejected"]').click();
  invariant(await desktop.locator("#evidenceEmpty").isVisible(), "Rejected filter should expose an empty state");
  await desktop.locator('[data-reset-evidence]').click();
  invariant(await desktop.locator(".evidence-card").first().isVisible(), "Reset filter did not restore evidence cards");

  await desktop.locator("#nextBtn").click();
  invariant((await desktop.locator("#videoClock").textContent()).includes("15:00"), "Next sample did not move to 15:00");
  const beforePlay = Number(await desktop.locator("#scrubber").inputValue());
  await desktop.locator("#playBtn").click();
  await desktop.waitForTimeout(700);
  await desktop.locator("#playBtn").click();
  const afterPlay = Number(await desktop.locator("#scrubber").inputValue());
  invariant(afterPlay > beforePlay, "Playback did not advance the timeline");
  await desktop.locator("#scrubber").evaluate((input) => {
    input.value = "1800";
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  invariant((await desktop.locator("#videoClock").textContent()).includes("30:00"), "Scrubber did not update the visible time");
  await desktop.locator('[data-bucket="300"]').click();
  invariant(await desktop.locator("#statsBody tr").count() > 5, "5-minute aggregation rows were not rendered");
  const [download] = await Promise.all([
    desktop.waitForEvent("download"),
    desktop.locator("#exportBtn").click()
  ]);
  invariant(download.suggestedFilename().endsWith(".csv"), "CSV export did not produce a CSV file");
  notes.push(`desktop layout ${await desktop.evaluate(() => document.documentElement.scrollWidth)}px; CSV ${download.suggestedFilename()}`);

  const mobileContext = await browser.newContext({
    viewport: { width: 390, height: 844 },
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai"
  });
  const mobile = await mobileContext.newPage();
  await attachAudit(mobile, "mobile", failures);
  await mobile.goto(baseUrl, { waitUntil: "networkidle" });
  await assertLayout(mobile, "mobile", 390);
  await mobile.screenshot({ path: path.join(screenshotDir, "narrow-390x844.png") });
  await mobile.screenshot({ path: path.join(screenshotDir, "narrow-full.png"), fullPage: true });
  notes.push(`mobile layout ${await mobile.evaluate(() => document.documentElement.scrollWidth)}px`);

  await mobile.locator("#capacityBtn").click();
  await mobile.waitForTimeout(250);
  invariant(await mobile.locator("#capacityDrawer").evaluate((node) => node.getBoundingClientRect().width <= 390), "Mobile drawer exceeds viewport");
  await mobile.locator('[data-close-drawer="capacity"]').click();

  const errorPage = await mobileContext.newPage();
  await errorPage.goto(baseUrl, { waitUntil: "networkidle" });
  await errorPage.locator("#uploadBtn").click();
  await errorPage.locator("#apiBaseInput").fill("http://127.0.0.1:1");
  await errorPage.locator("#videoInput").setInputFiles({
    name: "sample.mp4",
    mimeType: "video/mp4",
    buffer: Buffer.from("ui-check-placeholder")
  });
  invariant(!(await errorPage.locator("#submitUploadBtn").isDisabled()), "Upload submit stayed disabled after file selection");
  await errorPage.locator("#submitUploadBtn").click();
  await errorPage.locator("#uploadError").waitFor({ state: "visible", timeout: 8000 });
  invariant((await errorPage.locator("#uploadError").textContent()).includes("分析服务不可用"), "Backend failure state is not explicit");
  notes.push("backend-offline error state verified");

  const apiContext = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai"
  });
  const apiPage = await apiContext.newPage();
  await attachAudit(apiPage, "api-mock", failures);
  const apiCalls = { job: 0, status: 0, timeline: 0, review: 0 };
  await apiPage.route("**/api/jobs", async (route) => {
    apiCalls.job += 1;
    await route.fulfill({
      status: 202,
      contentType: "application/json",
      headers: { "access-control-allow-origin": "*" },
      body: JSON.stringify({ job_id: "job_test", status: "queued", created_at: "2026-10-21T10:00:00+08:00" })
    });
  });
  await apiPage.route(/\/api\/jobs\/job_test$/, async (route) => {
    apiCalls.status += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "access-control-allow-origin": "*" },
      body: JSON.stringify({
        job_id: "job_test",
        status: "needs_review",
        progress: 1,
        stage: "needs_review",
        message: "分析完成，存在待复核项",
        review_count: 2
      })
    });
  });
  await apiPage.route("**/api/jobs/job_test/timeline", async (route) => {
    apiCalls.timeline += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "access-control-allow-origin": "*" },
      body: JSON.stringify({
        job_id: "job_test",
        duration_seconds: 600,
        points: [
          {
            camera: "north",
            video_time: 5,
            counts: { total: 2, large: 1, medium: 1, small: 0, unknown: 0 },
            review_count: 1,
            frame_url: `${baseUrl}assets/frames/north_5.jpg`,
            vehicles: [
              {
                id: "N-API-001",
                type: "large",
                review: true,
                box: { x: 0.42, y: 0.24, w: 0.16, h: 0.3 },
                crop_url: `${baseUrl}assets/frames/crops/north-large.jpg`,
                votes: { truck: "2 / 3", type: "2 / 3", cross: "0 / 3" },
                reason: "API fixture review"
              }
            ]
          },
          {
            camera: "south",
            video_time: 5,
            counts: { total: 1, large: 1, medium: 0, small: 0, unknown: 0 },
            review_count: 0,
            frame_url: `${baseUrl}assets/frames/south_5.jpg`,
            vehicles: [{ id: "S-API-001", type: "large", box: { x: 0.33, y: 0.3, w: 0.18, h: 0.28 } }]
          },
          {
            camera: "north",
            video_time: 300,
            counts: { total: 1, large: 1, medium: 0, small: 0, unknown: 0 },
            frame_url: `${baseUrl}assets/frames/north_300.jpg`
          }
        ]
      })
    });
  });
  await apiPage.route("**/api/jobs/job_test/reviews/**", async (route) => {
    if (route.request().method() === "OPTIONS") {
      await route.fulfill({
        status: 204,
        headers: {
          "access-control-allow-origin": "*",
          "access-control-allow-methods": "POST, OPTIONS",
          "access-control-allow-headers": "content-type"
        }
      });
      return;
    }
    apiCalls.review += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "access-control-allow-origin": "*" },
      body: JSON.stringify({ ok: true })
    });
  });
  await apiPage.goto(baseUrl, { waitUntil: "networkidle" });
  await apiPage.locator("#uploadBtn").click();
  await apiPage.locator("#videoInput").setInputFiles({
    name: "north.mp4",
    mimeType: "video/mp4",
    buffer: Buffer.from("ui-check-api-fixture")
  });
  await apiPage.locator("#submitUploadBtn").click();
  try {
    await apiPage.waitForFunction(() => !document.querySelector("#uploadDialog").open, null, { timeout: 8000 });
  } catch (error) {
    const debug = await apiPage.evaluate(() => ({
      dialogOpen: document.querySelector("#uploadDialog").open,
      progressStage: document.querySelector("#progressStage").textContent,
      progressMessage: document.querySelector("#progressMessage").textContent,
      uploadErrorHidden: document.querySelector("#uploadError").hidden,
      uploadError: document.querySelector("#uploadError").textContent
    }));
    console.error("API mock debug", apiCalls, debug);
    throw error;
  }
  invariant(apiCalls.job === 1 && apiCalls.status >= 1 && apiCalls.timeline === 1, "API job/status/timeline contract was not exercised");
  invariant((await apiPage.locator("#modePill").textContent()).includes("API JOB"), "Remote job did not replace static mode");
  invariant((await apiPage.locator("#visibleTotal").textContent()) === "3", "Remote timeline counts were not rendered");
  await apiPage.locator('[data-view-mode="analysis"]').click();
  invariant(await apiPage.locator(".bbox").count() === 2, "JSON-driven remote boxes were not rendered");
  await apiPage.locator(".evidence-card").first().click();
  await apiPage.locator('[data-review-action="confirm"]').click();
  await apiPage.waitForTimeout(200);
  invariant(apiCalls.review === 1, "Remote review action was not posted to the contract endpoint");
  notes.push("API mock: job → status → timeline → boxes → review POST verified");

  await browser.close();
  if (failures.length) {
    console.error("UI CHECK FAILED");
    failures.forEach((failure) => console.error(`- ${failure}`));
    process.exitCode = 1;
    return;
  }
  console.log("UI CHECK PASSED");
  notes.forEach((note) => console.log(`- ${note}`));
}

run().catch((error) => {
  console.error("UI CHECK FAILED");
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
