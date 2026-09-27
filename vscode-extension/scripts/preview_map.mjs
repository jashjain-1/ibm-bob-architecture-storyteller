#!/usr/bin/env node
// preview_map.mjs
// ~~~~~~~~~~~~~~~
// Renders the map webview against a live engine into one self-contained HTML
// file, so the UI can be inspected in a normal browser without launching the
// IDE. The engine server is started detached and its pid is printed; stop it
// with `taskkill /PID <pid> /T /F` (Windows) or `kill <pid>`.
//
// Usage:
//   node scripts/preview_map.mjs --repo .. --level 2 --output ../output/map-preview.html

import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const here = dirname(fileURLToPath(import.meta.url));
const extensionRoot = resolve(here, "..");

function parseArgs(argv) {
  const opts = {
    repo: resolve(extensionRoot, ".."),
    level: 2,
    output: "",
    python: "python",
    apiBase: "",
  };
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--repo") opts.repo = resolve(argv[++i]);
    else if (arg === "--level") opts.level = Number(argv[++i]);
    else if (arg === "--output" || arg === "-o") opts.output = resolve(argv[++i]);
    else if (arg === "--python") opts.python = argv[++i];
    else if (arg === "--api-base") opts.apiBase = argv[++i].replace(/\/$/, "");
  }
  if (!opts.output) {
    opts.output = join(opts.repo, "output", "map-preview.html");
  }
  return opts;
}

function findCli(repo) {
  const candidates = [
    join(repo, "tools", "storyteller-engine", "cli.py"),
    join(extensionRoot, "tools", "storyteller-engine", "cli.py"),
    join(extensionRoot, "..", "tools", "storyteller-engine", "cli.py"),
  ];
  return candidates.find((candidate) => existsSync(candidate));
}

function startEngine(python, cliPath, repo) {
  return new Promise((resolvePromise, reject) => {
    const child = spawn(python, [cliPath, "serve", "--port", "0", "--repo", repo], {
      cwd: repo,
      detached: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    let buffer = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error(`engine did not report a port: ${stderr.slice(-300)}`));
    }, 60000);
    child.stderr.on("data", (chunk) => {
      stderr += chunk.toString();
    });
    child.stdout.on("data", (chunk) => {
      buffer += chunk.toString();
      let index = buffer.indexOf("\n");
      while (index >= 0) {
        const line = buffer.slice(0, index).trim();
        buffer = buffer.slice(index + 1);
        index = buffer.indexOf("\n");
        if (!line) continue;
        try {
          const parsed = JSON.parse(line);
          if (parsed.event === "listening") {
            clearTimeout(timer);
            // The engine keeps running, but its pipes must not hold this
            // script open: detach the streams before unreferencing the child.
            child.stdout.destroy();
            child.stderr.destroy();
            child.unref();
            resolvePromise({ child, port: parsed.port });
          }
        } catch {
          // logging only
        }
      }
    });
    child.on("error", reject);
    child.on("exit", (code) => {
      clearTimeout(timer);
      reject(new Error(`engine exited with code ${code}`));
    });
  });
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${url} -> ${response.status}`);
  }
  return response.json();
}

async function main() {
  const opts = parseArgs(process.argv.slice(2));
  const cliPath = findCli(opts.repo);
  if (!cliPath) {
    console.error("cli.py not found; pass --repo pointing at the project root");
    process.exit(2);
  }

  // Reuse a running engine when one is given, so the preview can be refreshed
  // without leaving another server behind.
  let child = null;
  let apiBase = opts.apiBase;
  if (!apiBase) {
    const started = await startEngine(opts.python, cliPath, opts.repo);
    child = started.child;
    apiBase = `http://127.0.0.1:${started.port}`;
  }
  const [tree, health] = await Promise.all([
    fetchJson(`${apiBase}/tree`),
    fetchJson(`${apiBase}/health`),
  ]);

  const { shellHtml } = require(join(extensionRoot, "dist", "webview", "shell.js"));
  const script = readFileSync(join(extensionRoot, "dist", "webview", "map.js"), "utf8");
  const css = readFileSync(join(extensionRoot, "media", "map.css"), "utf8");

  const html = shellHtml({
    title: `${tree.repo.name} - architecture map`,
    payload: {
      payload: { ...tree, apiBase },
      apiBase,
      level: opts.level,
      workspaceRoot: opts.repo,
      engine: "workspace",
    },
    inlineScript: `${script}\n//# sourceURL=map.js`,
    moduleScript: true,
  });

  // Inline the stylesheet so the preview is one portable file.
  const withCss = html.replace(
    "</head>",
    `<style>${css}</style>\n<style>body { height: 100vh; } .app { height: 100vh; }</style>\n</head>`
  );

  writeFileSync(opts.output, withCss, "utf8");
  console.log(JSON.stringify({
    output: opts.output,
    apiBase,
    enginePid: child ? child.pid : null,
    stop: child ? `taskkill /PID ${child.pid} /T /F` : "engine was already running",
    symbols: health.stats.symbols,
    files: health.stats.files,
    level: opts.level,
  }, null, 2));
  // Let Node drain its keep-alive sockets instead of forcing exit, which
  // trips a libuv assertion on Windows while handles are still closing.
  process.exitCode = 0;
}

main().catch((error) => {
  console.error(String(error.message ?? error));
  process.exit(1);
});
