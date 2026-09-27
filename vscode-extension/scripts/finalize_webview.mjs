/**
 * Make the compiled webview bundle loadable as a *classic* script.
 *
 * src/webview/map.ts imports only types, so the emitted file has no imports at
 * all — just the `export {};` marker TypeScript appends to keep the file a
 * module. That marker is what forced `<script type="module">`, and module
 * scripts inside an IDE webview are fetched with CORS rules that are easy to
 * trip over (a blocked module means a silently blank panel with no visible
 * error). Removing the marker lets the panel use a plain nonce'd script tag.
 */

import { readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const target = fileURLToPath(new URL("../dist/webview/map.js", import.meta.url));

let code = await readFile(target, "utf8");
const stripped = code.length;

code = code.replace(/\n\s*export\s*\{\s*\}\s*;?\s*\n/g, "\n");

const moduleSyntax = code.match(/^[ \t]*(?:import|export)\s/m);
if (moduleSyntax) {
    console.error(`webview bundle still contains module syntax: ${JSON.stringify(moduleSyntax[0])}`);
    process.exit(1);
}

if (!/post\(\{\s*command:\s*'ready'\s*\}\)/.test(code)) {
    console.error("webview bundle is missing the ready handshake; refusing to finalize");
    process.exit(1);
}

await writeFile(target, code, "utf8");
console.log(`finalized dist/webview/map.js as a classic script (${stripped} -> ${code.length} bytes)`);
