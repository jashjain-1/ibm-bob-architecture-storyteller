#!/usr/bin/env node
// render_pdf.mjs
// ~~~~~~~~~~~~~~
// Print an HTML dossier to PDF with the Chromium browser already installed on
// this machine (Edge, Chrome or Chromium). No npm dependencies: the browser is
// driven over the DevTools protocol through Node's built-in WebSocket, which
// gives real header/footer templates and page numbers.
//
// Notes from testing on Windows: `Application\msedge.exe` is a redirector that
// forwards to a running instance and exits, so this script resolves the real
// versioned binary (`Application\<version>\msedge.exe`) first. Edge does not
// always print its DevTools endpoint to stderr, so a free port is chosen up
// front and polled over HTTP.
//
// Contents page numbers are deliberately *not* printed. Chromium has no
// paged-layout API and does not implement CSS `target-counter`, and the obvious
// workaround (hide everything after a heading, print, count pages) is not sound:
// hiding the tail changes where Chromium breaks the earlier pages, so a heading
// can measure past the last page of the real document. Navigation the browser
// can prove instead: `generateDocumentOutline` gives the PDF real bookmarks per
// section, and the printed footer carries "Page N of M".
//
// Usage:
//   node scripts/render_pdf.mjs --input output/dossier-L2.html --output out.pdf
//   node scripts/render_pdf.mjs --input a.html --footer-title "Galaxium - L2"
//   node scripts/render_pdf.mjs --input a.html --no-footer
//
// Exit codes: 0 ok, 2 bad arguments / missing file, 3 no browser found,
//             4 render failed.

import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { createServer } from "node:net";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const BROWSER_CANDIDATES = [
  process.env.STORYTELLER_CHROMIUM || "",
  join(process.env.LOCALAPPDATA || "", "Microsoft/Edge/Application/msedge.exe"),
  "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe",
  "C:/Program Files/Microsoft/Edge/Application/msedge.exe",
  join(process.env.LOCALAPPDATA || "", "Google/Chrome/Application/chrome.exe"),
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/usr/bin/microsoft-edge",
  "/usr/bin/google-chrome",
  "/usr/bin/chromium",
  "/usr/bin/chromium-browser",
  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
].filter(Boolean);

function parseArgs(argv) {
  const opts = {
    input: "",
    output: "",
    footerTitle: "",
    headerTitle: "",
    footer: true,
    timeoutMs: 60000,
    keepHtmlTitle: true,
    browser: "",
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = () => argv[++i];
    if (arg === "--input" || arg === "-i") opts.input = next();
    else if (arg === "--output" || arg === "-o") opts.output = next();
    else if (arg === "--footer-title") opts.footerTitle = next();
    else if (arg === "--header-title") opts.headerTitle = next();
    else if (arg === "--browser") opts.browser = next();
    else if (arg === "--timeout") opts.timeoutMs = Number(next()) * 1000;
    else if (arg === "--no-footer") opts.footer = false;
    else if (arg === "--help" || arg === "-h") {
      console.log(readFileSync(new URL(import.meta.url)).toString().split("\n").slice(1, 22).join("\n"));
      process.exit(0);
    } else {
      console.error(`Unknown argument: ${arg}`);
      process.exit(2);
    }
  }
  return opts;
}

// Windows Edge keeps the real binary in a versioned directory; the sibling
// msedge.exe only forwards to a running browser and exits.
function resolveRealBinary(candidate) {
  const dir = dirname(candidate);
  const exeName = basename(candidate);
  if (!existsSync(dir)) return candidate;
  let entries = [];
  try {
    entries = readdirSync(dir, { withFileTypes: true });
  } catch {
    return candidate;
  }
  const versions = entries
    .filter((entry) => entry.isDirectory() && /^\d+(\.\d+)*$/.test(entry.name))
    .map((entry) => entry.name)
    .sort((a, b) => {
      const left = a.split(".").map(Number);
      const right = b.split(".").map(Number);
      for (let i = 0; i < Math.max(left.length, right.length); i += 1) {
        const diff = (right[i] || 0) - (left[i] || 0);
        if (diff) return diff;
      }
      return 0;
    });
  for (const version of versions) {
    const nested = join(dir, version, exeName);
    if (existsSync(nested)) return nested;
  }
  return candidate;
}

function findBrowser(explicit) {
  const candidates = explicit ? [explicit, ...BROWSER_CANDIDATES] : BROWSER_CANDIDATES;
  for (const candidate of candidates) {
    if (!candidate) continue;
    if (candidate.includes("/") || candidate.includes("\\")) {
      if (existsSync(candidate)) return resolveRealBinary(candidate);
    } else {
      const found = spawnSync(candidate, ["--version"], { stdio: "ignore" });
      if (!found.error) return candidate;
    }
  }
  return "";
}

function freePort() {
  return new Promise((resolvePromise, reject) => {
    const server = createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const { port } = server.address();
      server.close(() => resolvePromise(port));
    });
  });
}

// Page objects are written flat by Chromium, so counting them is enough; the
// page-tree `/Count` is a fallback for documents that nest their pages.
function countPdfPages(buffer) {
  const text = buffer.toString("latin1");
  const objects = text.match(/\/Type\s*\/Page(?![s])/g);
  if (objects && objects.length) return objects.length;
  const counts = [...text.matchAll(/\/Count\s+(\d+)/g)].map((match) => Number(match[1]));
  return counts.length ? Math.max(...counts) : 0;
}

function documentTitle(htmlPath) {
  try {
    const match = readFileSync(htmlPath, "utf8").match(/<title>([^<]*)<\/title>/i);
    return match ? match[1].trim() : "";
  } catch {
    return "";
  }
}

async function waitForDevTools(port, timeoutMs = 25000) {
  const deadline = Date.now() + timeoutMs;
  let lastError = "no response";
  while (Date.now() < deadline) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/json/version`, { signal: AbortSignal.timeout(2000) });
      if (res.ok) return true;
    } catch (error) {
      lastError = String(error.message || error);
    }
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`DevTools endpoint did not come up on port ${port}: ${lastError}`);
}

async function launchBrowser(browser, profileDir, port) {
  const args = [
    "--headless=new",
    "--disable-gpu",
    "--hide-scrollbars",
    "--disable-extensions",
    "--disable-sync",
    "--no-first-run",
    "--no-default-browser-check",
    "--disable-background-networking",
    "--disable-component-update",
    "--user-data-dir=" + profileDir,
    "--remote-debugging-port=" + port,
    "about:blank",
  ];
  const child = spawn(browser, args, { stdio: ["ignore", "ignore", "pipe"] });
  let stderr = "";
  child.stderr.on("data", (chunk) => {
    stderr += chunk.toString();
  });
  child.on("error", () => {});
  try {
    await waitForDevTools(port);
  } catch (error) {
    throw new Error(`${error.message}\nBrowser stderr: ${stderr.slice(-300) || "(empty)"}`);
  }
  return child;
}

function killTree(child) {
  if (!child || child.exitCode !== null) return;
  try {
    if (process.platform === "win32") {
      spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    } else {
      child.kill("SIGTERM");
    }
  } catch {
    try {
      child.kill();
    } catch {
      /* already gone */
    }
  }
}

async function pageTarget(port) {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/json/list`, { signal: AbortSignal.timeout(2000) });
      const targets = await res.json();
      const page = targets.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
      if (page) return page.webSocketDebuggerUrl;
    } catch {
      /* still starting */
    }
    await new Promise((r) => setTimeout(r, 150));
  }
  throw new Error("No page target appeared on the DevTools endpoint.");
}

function connect(wsUrl) {
  const socket = new WebSocket(wsUrl);
  let nextId = 1;
  const pending = new Map();
  const listeners = new Map();
  const ready = new Promise((resolvePromise, reject) => {
    socket.addEventListener("open", () => resolvePromise());
    socket.addEventListener("error", () => reject(new Error("DevTools WebSocket failed to open.")));
  });
  socket.addEventListener("message", (event) => {
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      return;
    }
    if (message.id && pending.has(message.id)) {
      const handlers = pending.get(message.id);
      pending.delete(message.id);
      if (message.error) handlers.reject(new Error(message.error.message));
      else handlers.resolve(message.result || {});
      return;
    }
    if (message.method && listeners.has(message.method)) {
      for (const listener of [...listeners.get(message.method)]) listener(message.params);
    }
  });
  const send = (method, params = {}) => new Promise((resolvePromise, reject) => {
    const id = nextId++;
    pending.set(id, { resolve: resolvePromise, reject });
    socket.send(JSON.stringify({ id, method, params }));
  });
  const once = (method, timeoutMs) => new Promise((resolvePromise, reject) => {
    const timer = timeoutMs ? setTimeout(() => reject(new Error(`Timed out waiting for ${method}`)), timeoutMs) : null;
    const handler = (params) => {
      if (timer) clearTimeout(timer);
      listeners.get(method).delete(handler);
      resolvePromise(params);
    };
    if (!listeners.has(method)) listeners.set(method, new Set());
    listeners.get(method).add(handler);
  });
  return { socket, ready, send, once };
}

async function render({ browser, htmlPath, outputPath, footerTitle, headerTitle, footer, timeoutMs }) {
  const profileDir = mkdtempSync(join(tmpdir(), "storyteller-render-"));
  let child = null;
  try {
    const port = await freePort();
    child = await launchBrowser(browser, profileDir, port);
    const cdp = connect(await pageTarget(port));
    await cdp.ready;
    await cdp.send("Page.enable");
    const loaded = cdp.once("Page.loadEventFired", timeoutMs);
    await cdp.send("Page.navigate", { url: pathToFileURL(htmlPath).href });
    await loaded;
    await cdp.send("Runtime.evaluate", {
      awaitPromise: true,
      expression: "document.fonts && document.fonts.ready ? document.fonts.ready.then(() => document.readyState) : document.readyState",
    });
    await new Promise((r) => setTimeout(r, 300));

    const footerTemplate = footer
      ? `<div style="width:100%;font-family:Segoe UI,Arial,sans-serif;font-size:7pt;color:#5b6673;padding:0 12mm;display:flex;justify-content:space-between;">
           <span>${footerTitle || "Architecture Storyteller"}</span>
           <span>Page <span class="pageNumber"></span> of <span class="totalPages"></span></span>
         </div>`
      : "<div></div>";
    const headerTemplate = headerTitle
      ? `<div style="width:100%;font-family:Segoe UI,Arial,sans-serif;font-size:7pt;color:#5b6673;padding:0 12mm;">${headerTitle}</div>`
      : "<div></div>";

    const printParams = {
      printBackground: true,
      preferCSSPageSize: true,
      displayHeaderFooter: true,
      headerTemplate,
      footerTemplate,
      // Kept in step with the `@page` rule in dossier.py, so the measured and the
      // printed geometry are the same and the page numbers stay honest.
      marginTop: 17 / 25.4,
      marginBottom: 15 / 25.4,
      marginLeft: 15 / 25.4,
      marginRight: 15 / 25.4,
      transferMode: "ReturnAsBase64",
    };

    let result;
    try {
      result = await cdp.send("Page.printToPDF", { ...printParams, generateDocumentOutline: true });
    } catch {
      // Older Chromium builds reject the bookmark flag; the PDF still prints.
      result = await cdp.send("Page.printToPDF", printParams);
    }
    const buffer = Buffer.from(result.data, "base64");
    writeFileSync(outputPath, buffer);
    cdp.socket.close();
    return { bytes: buffer.length, browser, pages: countPdfPages(buffer) };
  } finally {
    killTree(child);
    try {
      rmSync(profileDir, { recursive: true, force: true });
    } catch {
      /* profile cleanup is best-effort */
    }
  }
}

function renderWithCli(browser, htmlPath, outputPath) {
  // Fallback: Chromium's own print-to-pdf. No header/footer control, but it
  // keeps the dossier usable when the DevTools protocol path is unavailable.
  const profileDir = mkdtempSync(join(tmpdir(), "storyteller-render-"));
  const args = [
    "--headless=new",
    "--disable-gpu",
    "--no-first-run",
    "--no-default-browser-check",
    "--user-data-dir=" + profileDir,
    "--print-to-pdf=" + outputPath,
    pathToFileURL(htmlPath).href,
  ];
  try {
    let result = spawnSync(browser, args, { stdio: ["ignore", "ignore", "pipe"], timeout: 120000 });
    if (result.status !== 0 || !existsSync(outputPath)) {
      const withFlag = [...args.slice(0, -1), "--no-pdf-header-footer", args.at(-1)];
      result = spawnSync(browser, withFlag, { stdio: ["ignore", "ignore", "pipe"], timeout: 120000 });
    }
    if (result.status !== 0 || !existsSync(outputPath)) {
      throw new Error("CLI print failed: " + String(result.stderr || "").slice(-300));
    }
    return { bytes: statSync(outputPath).size, browser, mode: "cli" };
  } finally {
    try {
      rmSync(profileDir, { recursive: true, force: true });
    } catch {
      /* best-effort */
    }
  }
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  if (!opts.input) {
    console.error("Usage: node scripts/render_pdf.mjs --input dossier.html [--output dossier.pdf]");
    process.exit(2);
  }
  const htmlPath = resolve(opts.input);
  if (!existsSync(htmlPath)) {
    console.error(`Input not found: ${htmlPath}`);
    process.exit(2);
  }
  const outputPath = resolve(opts.output || htmlPath.replace(/\.html?$/i, ".pdf"));
  const browser = findBrowser(opts.browser);
  if (!browser) {
    console.error("No Chromium/Edge/Chrome installation found. Set STORYTELLER_CHROMIUM to its path.");
    process.exit(3);
  }
  const footerTitle = opts.footerTitle
    || (opts.keepHtmlTitle ? documentTitle(htmlPath) : "")
    || "Architecture Storyteller";
  try {
    const summary = await render({
      browser,
      htmlPath,
      outputPath,
      footerTitle,
      headerTitle: opts.headerTitle,
      footer: opts.footer,
      timeoutMs: opts.timeoutMs,
    });
    console.log(JSON.stringify({ output: outputPath, ...summary, mode: "cdp" }, null, 2));
  } catch (error) {
    try {
      const summary = renderWithCli(browser, htmlPath, outputPath);
      console.log(JSON.stringify({ output: outputPath, ...summary, warning: String(error.message).slice(0, 300) }, null, 2));
    } catch (fallbackError) {
      console.error(JSON.stringify({ error: String(error.message), fallback: String(fallbackError.message) }, null, 2));
      process.exit(4);
    }
  }
}

main();
