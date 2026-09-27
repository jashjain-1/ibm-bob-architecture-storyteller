/**
 * Reproduce the map webview outside the IDE.
 *
 * The plain preview script injects a payload straight into the page, which
 * hides everything about the host <-> webview protocol. This one instead serves
 * the *real* shell HTML produced by src/webview/shell.ts — same CSP, same nonce,
 * same module script tag, same `payload: undefined` boot state — and answers the
 * webview's `ready` message with a payload fetched from a live engine, exactly
 * as MapPanel.pushPayload does.
 *
 *   node scripts/preview_shell.mjs --engine http://127.0.0.1:PORT [--level 2] [--watch]
 */

import { createRequire } from "node:module";
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { shellHtml } = require("../dist/webview/shell.js");

const HERE = path.dirname(fileURLToPath(import.meta.url));
const EXT = path.resolve(HERE, "..");

function parseArgs(argv) {
    const opts = { engine: "", level: 2, watch: false, repo: EXT };
    for (let i = 0; i < argv.length; i += 1) {
        if (argv[i] === "--engine") opts.engine = argv[++i].replace(/\/$/, "");
        else if (argv[i] === "--level") opts.level = Number(argv[++i]);
        else if (argv[i] === "--repo") opts.repo = argv[++i];
        else if (argv[i] === "--watch") opts.watch = true;
    }
    if (!opts.engine) {
        console.error("--engine http://127.0.0.1:PORT is required");
        process.exit(2);
    }
    return opts;
}

const opts = parseArgs(process.argv.slice(2));
const NONCE = "PREVIEWNONCE";

const MIME = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".map": "application/json; charset=utf-8",
};

/** Stands in for acquireVsCodeApi and the extension host's message handling. */
const HOST_SHIM = `
(function () {
    const listeners = [];
    window.acquireVsCodeApi = function () {
        return {
            postMessage(message) {
                listeners.forEach((fn) => fn(message));
            },
            getState() { return undefined; },
            setState() {},
        };
    };
    window.__PREVIEW_LOG__ = [];
    window.__previewReceive = function (handler) { listeners.push(handler); };
    window.addEventListener("message", (event) => {
        window.__PREVIEW_LOG__.push("page->host: " + JSON.stringify(event.data).slice(0, 200));
    });
})();
`;

const HOST_DRIVER = `
(function () {
    const engine = ${JSON.stringify(opts.engine)};
    window.__previewReceive(async (message) => {
        if (!message || !message.command) return;
        if (message.command === "ready" || message.command === "refresh") {
            try {
                const response = await fetch(engine + "/tree?stale=1");
                const tree = await response.json();
                window.postMessage({
                    type: "payload",
                    payload: Object.assign({}, tree, { apiBase: engine, level: ${opts.level} }),
                    apiBase: engine,
                }, "*");
            } catch (error) {
                window.postMessage({ type: "status", message: "Engine unavailable: " + error, isError: true }, "*");
            }
        }
    });
    window.addEventListener("error", (event) => {
        window.__PREVIEW_LOG__.push("page error: " + (event.message || event.error));
    });
    window.addEventListener("unhandledrejection", (event) => {
        window.__PREVIEW_LOG__.push("unhandled rejection: " + event.reason);
    });
})();
`;

const server = createServer(async (request, response) => {
    const url = new URL(request.url ?? "/", "http://127.0.0.1");
    const base = `http://127.0.0.1:${server.address().port}`;

    if (url.pathname === "/" || url.pathname === "/index.html") {
        let html = shellHtml({
            title: "Architecture Storyteller",
            // Exactly what MapPanel boots with: no payload yet.
            payload: {
                payload: undefined,
                apiBase: "",
                level: opts.level,
                workspaceRoot: opts.repo,
                engine: "configured",
            },
            scriptUri: `${base}/dist/webview/map.js`,
            styleUri: `${base}/media/map.css`,
            cspSource: base,
            nonce: NONCE,
            // Mirror production exactly: the panel ships a classic script.
            moduleScript: false,
        });
        // Load the host shim before the UI bundle, with the same nonce.
        const shim = `<script nonce="${NONCE}" src="/host.js"></script>`;
        html = html.replace(`<script nonce="${NONCE}" src=`, `${shim}\n<script nonce="${NONCE}" src=`);
        response.writeHead(200, { "content-type": "text/html; charset=utf-8" });
        response.end(html);
        return;
    }

    if (url.pathname === "/host.js") {
        response.writeHead(200, { "content-type": MIME[".js"] });
        response.end(`${HOST_SHIM}\n${HOST_DRIVER}`);
        return;
    }

    const relative = url.pathname.replace(/^\/+/, "");
    if (!relative.startsWith("dist/") && !relative.startsWith("media/")) {
        response.writeHead(404).end("not found");
        return;
    }
    try {
        const body = await readFile(path.join(EXT, relative));
        response.writeHead(200, { "content-type": MIME[path.extname(relative)] ?? "application/octet-stream" });
        response.end(body);
    } catch (error) {
        console.error(`  missing resource: ${relative}`);
        response.writeHead(404).end(String(error));
    }
});

server.listen(0, "127.0.0.1", () => {
    const url = `http://127.0.0.1:${server.address().port}/`;
    console.log(JSON.stringify({ url, engine: opts.engine, level: opts.level, nonce: NONCE }, null, 2));
    console.log("Open the URL above and watch the console for blocked scripts or page errors.");
    if (!opts.watch) {
        // Keep serving; the caller drives the browser.
    }
});
