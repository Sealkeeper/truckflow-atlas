import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "..");
const shotsDir = path.join(repoRoot, "debug", "shots");
const archiveDir = path.join(shotsDir, "archive");
const publicLiveDir = path.resolve(repoRoot, "..", "..", "all-sessions-can-see", "assets", "live");

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
  const requested = decoded === "/" ? "/debug/viewer/lab.html" : decoded;
  const absolute = path.resolve(repoRoot, `.${requested}`);
  const relative = path.relative(repoRoot, absolute);
  if (relative.startsWith("..") || path.isAbsolute(relative)) return null;
  if (relative === ".env" || relative === ".git" || relative.startsWith(`.git${path.sep}`)) return null;
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
      if (fs.statSync(target).isDirectory()) target = path.join(target, "index.html");
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
  if (!found) throw new Error("未找到 Chrome/Edge。请设置 CHROME_PATH。");
  return found;
}

async function waitReady(page) {
  await page.waitForLoadState("networkidle");
  await page.waitForFunction(() => document.querySelector(".model-button"), null, { timeout: 15000 });
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
  await page.waitForTimeout(200);
}

async function audit(page, consoleErrors, httpErrors) {
  return page.evaluate(
    ({ consoleErrors, httpErrors }) => {
      const width = window.innerWidth;
      const visible = (element) => {
        const style = getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
      };
      const describe = (element) => {
        const rect = element.getBoundingClientRect();
        return {
          tag: element.tagName.toLowerCase(),
          className: String(element.className || "").slice(0, 80),
          text: String(element.textContent || "").trim().replace(/\s+/g, " ").slice(0, 80),
          left: Number(rect.left.toFixed(1)),
          right: Number(rect.right.toFixed(1))
        };
      };
      return {
        viewport: { width, height: window.innerHeight },
        document: {
          width: document.documentElement.scrollWidth,
          height: document.documentElement.scrollHeight,
          hasHorizontalScroll: document.documentElement.scrollWidth > width + 1
        },
        values: {
          model: document.querySelector("#modelTitle")?.textContent,
          exact: document.querySelector("#metricExact")?.textContent,
          graded: document.querySelector("#metricGraded")?.textContent,
          mae: document.querySelector("#metricMae")?.textContent,
          sample: document.querySelector("#stageKey")?.textContent,
          predicted: document.querySelector("#predCount")?.textContent,
          gold: document.querySelector("#goldCount")?.textContent,
          delta: document.querySelector("#deltaValue")?.textContent,
          boxes: document.querySelectorAll(".vehicle-box").length
        },
        horizontalOverflow: [...document.body.querySelectorAll("*")]
          .filter(visible)
          .filter((element) => !element.closest(".glow"))
          .filter((element) => {
            const rect = element.getBoundingClientRect();
            return rect.right > width + 1 || rect.left < -1;
          })
          .slice(0, 15)
          .map(describe),
        clippedText: [...document.body.querySelectorAll("h1,h2,p,span,strong,small,code,button,label")]
          .filter(visible)
          .filter((element) => {
            const hasText = String(element.textContent || "").trim().length > 0;
            const style = getComputedStyle(element);
            const clipped =
              element.scrollWidth > element.clientWidth + 2 || element.scrollHeight > element.clientHeight + 2;
            return hasText && clipped && style.overflow !== "visible";
          })
          .slice(0, 20)
          .map(describe),
        failedImages: [...document.images]
          .filter((image) => !image.complete || image.naturalWidth === 0)
          .map((image) => ({ src: image.getAttribute("src"), alt: image.alt })),
        consoleErrors,
        httpErrors
      };
    },
    { consoleErrors, httpErrors }
  );
}

async function exercise(page, mobile) {
  const result = {};
  await page.locator(".model-button").nth(2).click();
  await page.waitForTimeout(120);
  result.aiboxModel = await page.evaluate(() => ({
    model: document.querySelector("#modelTitle")?.textContent,
    predicted: document.querySelector("#predCount")?.textContent,
    gold: document.querySelector("#goldCount")?.textContent,
    delta: document.querySelector("#deltaValue")?.textContent
  }));
  await page.locator(".model-button").nth(0).click();
  await page.waitForTimeout(120);
  if (!mobile) {
    await page.locator('.sample-button').nth(3).click();
    await page.waitForTimeout(120);
    result.afterSampleClick = await page.evaluate(() => ({
      sample: document.querySelector("#stageKey")?.textContent,
      predicted: document.querySelector("#predCount")?.textContent
    }));
  }
  await page.evaluate(() => {
    const target = [...document.querySelectorAll(".sample-button")].find((button) =>
      button.textContent.includes("10:00")
    );
    target?.click();
  });
  await waitReady(page);
  result.final = await page.evaluate(() => ({
    sample: document.querySelector("#stageKey")?.textContent,
    predicted: document.querySelector("#predCount")?.textContent,
    gold: document.querySelector("#goldCount")?.textContent
  }));
  return result;
}

async function captureOne(browser, name, viewport, url) {
  const context = await browser.newContext({
    viewport,
    deviceScaleFactor: 1,
    isMobile: viewport.width < 600,
    hasTouch: viewport.width < 600,
    colorScheme: "dark"
  });
  const page = await context.newPage();
  const consoleErrors = [];
  const httpErrors = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));
  page.on("requestfailed", (request) =>
    consoleErrors.push(`REQUEST_FAILED ${request.url()} ${request.failure()?.errorText || ""}`)
  );
  page.on("response", (response) => {
    if (response.status() >= 400) httpErrors.push({ status: response.status(), url: response.url() });
  });

  await page.goto(url, { waitUntil: "networkidle" });
  await waitReady(page);
  const interactions = await exercise(page, viewport.width < 600);
  await page.evaluate(() => window.scrollTo({ top: 0, left: 0, behavior: "instant" }));
  await page.waitForTimeout(180);
  const screenshotPath = path.join(shotsDir, `latest-${name}.png`);
  await page.screenshot({ path: screenshotPath, fullPage: false });
  const auditResult = await audit(page, consoleErrors, httpErrors);
  await context.close();
  return { name, viewport, screenshotPath, interactions, audit: auditResult };
}

function pngSize(filePath) {
  const buffer = fs.readFileSync(filePath);
  return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
}

async function run() {
  fs.mkdirSync(archiveDir, { recursive: true });
  const server = createStaticServer();
  await new Promise((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  const url = `http://127.0.0.1:${server.address().port}/debug/viewer/lab.html`;
  const chromePath = locateChrome();
  let browser;
  try {
    browser = await chromium.launch({
      executablePath: chromePath,
      headless: true,
      args: ["--hide-scrollbars", "--force-color-profile=srgb"]
    });
    const desktop = await captureOne(browser, "desktop", { width: 1440, height: 1000 }, url);
    const mobile = await captureOne(browser, "mobile", { width: 390, height: 844 }, url);

    const stamp = new Date().toISOString().replace(/[:.]/g, "-");
    fs.mkdirSync(publicLiveDir, { recursive: true });
    for (const shot of [desktop, mobile]) {
      shot.outputSize = pngSize(shot.screenshotPath);
      fs.copyFileSync(shot.screenshotPath, path.join(publicLiveDir, path.basename(shot.screenshotPath)));
      fs.copyFileSync(shot.screenshotPath, path.join(archiveDir, `${stamp}-${shot.name}.png`));
    }

    const report = {
      generatedAt: new Date().toISOString(),
      generatedAtLocal: new Intl.DateTimeFormat("zh-CN", {
        dateStyle: "medium",
        timeStyle: "long",
        timeZone: "Asia/Shanghai"
      }).format(new Date()),
      pageVersion: "debug-lab@1.0.0",
      sourceUrl: url,
      chromePath,
      publicLiveDir,
      screenshots: [desktop, mobile]
    };
    fs.writeFileSync(path.join(shotsDir, "report.json"), `${JSON.stringify(report, null, 2)}\n`, "utf8");

    const failures = report.screenshots.flatMap((shot) => {
      const list = [];
      if (shot.audit.document.hasHorizontalScroll) list.push(`${shot.name}: 页面横向溢出`);
      if (shot.audit.consoleErrors.length) list.push(`${shot.name}: 控制台错误`);
      if (shot.audit.httpErrors.length) list.push(`${shot.name}: HTTP 4xx/5xx`);
      if (shot.audit.failedImages.length) list.push(`${shot.name}: 图片加载失败`);
      if (shot.audit.horizontalOverflow.length) list.push(`${shot.name}: ${shot.audit.horizontalOverflow.length} 个元素越界`);
      if (shot.audit.clippedText.length) list.push(`${shot.name}: ${shot.audit.clippedText.length} 个文本裁切`);
      return list;
    });

    for (const shot of report.screenshots) {
      console.log(
        `${shot.name}: ${shot.outputSize.width}x${shot.outputSize.height}, ` +
          `样本 ${shot.audit.values.sample}, 预测 ${shot.audit.values.predicted}/人工 ${shot.audit.values.gold}, ` +
          `框 ${shot.audit.values.boxes}`
      );
    }
    console.log(failures.length ? `需要检查：\n- ${failures.join("\n- ")}` : "自动检查通过。");
    if (failures.length) process.exitCode = 2;
  } finally {
    if (browser) await browser.close();
    await new Promise((resolve) => server.close(resolve));
  }
}

run().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = 1;
});
