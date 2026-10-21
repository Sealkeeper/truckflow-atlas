import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "..");
const viewerRoot = path.join(repoRoot, "debug", "viewer");
const shotsDir = path.join(repoRoot, "debug", "shots");
const publicLiveDir = path.resolve(
  repoRoot,
  "..",
  "..",
  "all-sessions-can-see",
  "assets",
  "live"
);

const mimeTypes = {
  ".css": "text/css; charset=utf-8",
  ".html": "text/html; charset=utf-8",
  ".ico": "image/x-icon",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".js": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".png": "image/png",
  ".svg": "image/svg+xml"
};

function safeResolve(urlPath) {
  const decoded = decodeURIComponent((urlPath || "/").split("?")[0]);
  const requested = decoded === "/" ? "/debug/viewer/index.html" : decoded;
  const absolute = path.resolve(repoRoot, `.${requested}`);
  const relative = path.relative(repoRoot, absolute);
  if (relative.startsWith("..") || path.isAbsolute(relative)) {
    return null;
  }
  if (relative === ".env" || relative.startsWith(`.git${path.sep}`) || relative === ".git") {
    return null;
  }
  return absolute;
}

function createStaticServer() {
  return http.createServer((request, response) => {
    let target = safeResolve(request.url);
    if (!target) {
      response.writeHead(403, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("Forbidden");
      return;
    }

    try {
      if (fs.statSync(target).isDirectory()) {
        target = path.join(target, "index.html");
      }
      const body = fs.readFileSync(target);
      response.writeHead(200, {
        "Cache-Control": "no-store",
        "Content-Length": body.length,
        "Content-Type": mimeTypes[path.extname(target).toLowerCase()] || "application/octet-stream"
      });
      response.end(body);
    } catch {
      response.writeHead(404, { "Content-Type": "text/plain; charset=utf-8" });
      response.end("Not found");
    }
  });
}

function locateChrome() {
  const candidates = [
    process.env.CHROME_PATH,
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe"
  ].filter(Boolean);

  const found = candidates.find((candidate) => {
    try {
      return fs.statSync(candidate).isFile();
    } catch {
      return false;
    }
  });
  if (!found) {
    throw new Error("未找到 Chrome/Edge。请设置 CHROME_PATH 后重跑 debug/capture.ps1。");
  }
  return found;
}

async function waitForViewer(page) {
  await page.waitForLoadState("networkidle");
  await page.evaluate(async () => {
    await document.fonts.ready;
    await Promise.all(
      [...document.images].map((image) => {
        if (image.complete) return Promise.resolve();
        return new Promise((resolve) => {
          image.addEventListener("load", resolve, { once: true });
          image.addEventListener("error", resolve, { once: true });
        });
      })
    );
  });
  await page.waitForTimeout(250);
}

async function auditPage(page, errors, notFound) {
  return page.evaluate(({ consoleErrors, httpNotFounds }) => {
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const visible = (element) => {
      const style = getComputedStyle(element);
      const rect = element.getBoundingClientRect();
      return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
    };
    const describe = (element) => {
      const rect = element.getBoundingClientRect();
      return {
        tag: element.tagName.toLowerCase(),
        className: String(element.className || "").slice(0, 90),
        text: String(element.textContent || "").trim().replace(/\s+/g, " ").slice(0, 100),
        left: Number(rect.left.toFixed(1)),
        right: Number(rect.right.toFixed(1)),
        width: Number(rect.width.toFixed(1))
      };
    };

    const horizontalOverflow = [...document.body.querySelectorAll("*")]
      .filter(visible)
      .filter((element) => !element.closest(".ambient"))
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        return rect.right > viewportWidth + 1 || rect.left < -1;
      })
      .slice(0, 20)
      .map(describe);

    const clippedText = [...document.body.querySelectorAll("h1,h2,p,span,strong,small,code,button,label")]
      .filter(visible)
      .filter((element) => {
        const style = getComputedStyle(element);
        const hasText = String(element.textContent || "").trim().length > 0;
        const clipped = element.scrollWidth > element.clientWidth + 2 || element.scrollHeight > element.clientHeight + 2;
        return hasText && clipped && style.overflow !== "visible";
      })
      .slice(0, 30)
      .map(describe);

    const failedImages = [...document.images]
      .filter((image) => !image.complete || image.naturalWidth === 0)
      .map((image) => ({ src: image.getAttribute("src"), alt: image.alt }));

    const required = [
      ".camera-workspace",
      ".snapshot-card",
      ".load-card",
      ".timeline-panel",
      "[data-camera='north'] [data-frame]",
      "[data-camera='south'] [data-frame]",
      ".analysis-empty"
    ];

    return {
      viewport: { width: viewportWidth, height: viewportHeight },
      document: {
        width: document.documentElement.scrollWidth,
        height: document.documentElement.scrollHeight,
        hasHorizontalScroll: document.documentElement.scrollWidth > viewportWidth + 1
      },
      requiredElements: Object.fromEntries(
        required.map((selector) => [selector, Boolean(document.querySelector(selector))])
      ),
      counts: {
        north: document.querySelector("[data-camera='north'] [data-count]")?.textContent,
        south: document.querySelector("[data-camera='south'] [data-count]")?.textContent,
        load: document.querySelector("[data-load-value]")?.textContent
      },
      horizontalOverflow,
      clippedText,
      failedImages,
      consoleErrors,
      httpNotFounds
    };
  }, { consoleErrors: errors, httpNotFounds: notFound });
}

async function exerciseInteractions(page) {
  const results = {};
  await page.locator('.sample-button[data-time="600"]').click();
  await waitForViewer(page);
  results.afterSampleClick = await page.evaluate(() => ({
    time: document.querySelector("[data-current-time]")?.textContent,
    north: document.querySelector("[data-camera='north'] [data-count]")?.textContent,
    south: document.querySelector("[data-camera='south'] [data-count]")?.textContent,
    northFrame: document.querySelector("[data-camera='north'] [data-frame]")?.getAttribute("src"),
    southFrame: document.querySelector("[data-camera='south'] [data-frame]")?.getAttribute("src")
  }));

  await page.locator('[data-view="analysis"]').click();
  results.analysisMode = await page.evaluate(() => ({
    activeTab: document.querySelector(".segment.is-active")?.textContent,
    overlayDisplay: getComputedStyle(document.querySelector(".analysis-empty")).display,
    caption: document.querySelector("[data-camera='north'] [data-camera-label]")?.textContent
  }));

  await page.locator('[data-view="original"]').click();
  await page.locator('.sample-button[data-time="1200"]').click();
  await waitForViewer(page);
  results.resetToDefault = await page.evaluate(() => ({
    time: document.querySelector("[data-current-time]")?.textContent,
    north: document.querySelector("[data-camera='north'] [data-count]")?.textContent,
    south: document.querySelector("[data-camera='south'] [data-count]")?.textContent,
    activeTab: document.querySelector(".segment.is-active")?.textContent
  }));
  return results;
}

async function captureOne(browser, name, viewport, interactions) {
  const context = await browser.newContext({
    viewport,
    deviceScaleFactor: 1,
    isMobile: viewport.width < 600,
    hasTouch: viewport.width < 600,
    colorScheme: "dark"
  });
  const page = await context.newPage();
  const consoleErrors = [];
  const httpNotFounds = [];

  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));
  page.on("requestfailed", (request) => {
    consoleErrors.push(`REQUEST_FAILED ${request.url()} ${request.failure()?.errorText || ""}`);
  });
  page.on("response", (response) => {
    if (response.status() >= 400) {
      httpNotFounds.push({ status: response.status(), url: response.url() });
    }
  });

  await page.goto(interactions.url, { waitUntil: "networkidle" });
  await waitForViewer(page);
  const interactionResults = name === "desktop" ? await exerciseInteractions(page) : await (async () => {
    await page.locator('.sample-button[data-time="600"]').click();
    await waitForViewer(page);
    await page.locator('.sample-button[data-time="1200"]').click();
    await waitForViewer(page);
    return {};
  })();

  const screenshotPath = path.join(shotsDir, `latest-${name}.png`);
  await page.evaluate(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "instant" });
    document.querySelector("#toast")?.classList.remove("is-visible");
  });
  await page.waitForTimeout(150);
  await page.screenshot({ path: screenshotPath, fullPage: false });
  const audit = await auditPage(page, consoleErrors, httpNotFounds);
  await context.close();
  return {
    name,
    screenshotPath,
    interactions: interactionResults,
    audit
  };
}

function pngSize(filePath) {
  const buffer = fs.readFileSync(filePath);
  return {
    width: buffer.readUInt32BE(16),
    height: buffer.readUInt32BE(20)
  };
}

async function runCapture() {
  fs.mkdirSync(shotsDir, { recursive: true });
  const server = createStaticServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const { port } = server.address();
  const url = `http://127.0.0.1:${port}/debug/viewer/`;
  const chromePath = locateChrome();
  let browser;

  try {
    browser = await chromium.launch({
      executablePath: chromePath,
      headless: true,
      args: ["--hide-scrollbars", "--force-color-profile=srgb"]
    });
    const desktop = await captureOne(browser, "desktop", { width: 1440, height: 1000 }, { url });
    const mobile = await captureOne(browser, "mobile", { width: 390, height: 844 }, { url });

    fs.mkdirSync(publicLiveDir, { recursive: true });
    for (const result of [desktop, mobile]) {
      fs.copyFileSync(result.screenshotPath, path.join(publicLiveDir, path.basename(result.screenshotPath)));
      result.outputSize = pngSize(result.screenshotPath);
    }

    const report = {
      generatedAt: new Date().toISOString(),
      generatedAtLocal: new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "medium",
        timeStyle: "long",
        timeZone: "Asia/Shanghai"
      }).format(new Date()),
      pageVersion: "debug-viewer@0.1.0",
      sourceUrl: url,
      chromePath,
      publicLiveDir,
      screenshots: [desktop, mobile]
    };
    fs.writeFileSync(path.join(shotsDir, "report.json"), `${JSON.stringify(report, null, 2)}\n`, "utf8");

    const failures = report.screenshots.flatMap((shot) => {
      const checks = [];
      if (shot.audit.document.hasHorizontalScroll) checks.push(`${shot.name}: 页面横向溢出`);
      if (shot.audit.consoleErrors.length) checks.push(`${shot.name}: 控制台错误`);
      if (shot.audit.httpNotFounds.length) checks.push(`${shot.name}: HTTP 4xx/5xx`);
      if (shot.audit.failedImages.length) checks.push(`${shot.name}: 图片加载失败`);
      if (shot.audit.horizontalOverflow.length) checks.push(`${shot.name}: ${shot.audit.horizontalOverflow.length} 个元素横向越界`);
      if (shot.audit.clippedText.length) checks.push(`${shot.name}: ${shot.audit.clippedText.length} 个文本裁切`);
      return checks;
    });

    console.log(`截图完成：${desktop.screenshotPath} (${desktop.outputSize.width}x${desktop.outputSize.height})`);
    console.log(`截图完成：${mobile.screenshotPath} (${mobile.outputSize.width}x${mobile.outputSize.height})`);
    console.log(`公共副本：${publicLiveDir}`);
    if (failures.length) {
      console.log(`发现 ${failures.length} 项需要检查：`);
      failures.forEach((failure) => console.log(`- ${failure}`));
    } else {
      console.log("自动检查通过：无横向滚动、控制台错误、HTTP 错误或图片失败。");
    }
  } finally {
    if (browser) await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
}

if (process.argv.includes("--serve-only")) {
  const server = createStaticServer();
  const previewPort = Number(process.env.CAPTURE_PORT || 4173);
  server.listen(previewPort, "127.0.0.1", () => {
    console.log(`当前效果页：http://127.0.0.1:${server.address().port}/debug/viewer/`);
    console.log("按 Ctrl+C 停止本地静态服务器。");
  });
} else {
  runCapture().catch((error) => {
    console.error(error.stack || error.message);
    process.exitCode = 1;
  });
}
