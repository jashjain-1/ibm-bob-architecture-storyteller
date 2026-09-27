/**
 * Checks for engine discovery (src/engine/locate.ts), runnable with
 * `npm run test:locate`.
 *
 * These cover the two reported dead ends: a window with no folder open, which
 * used to print a "Looked in:" heading with nothing under it, and a folder that
 * simply does not contain the engine, which used to give no way forward.
 */

import { createRequire } from "node:module";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { tmpdir } from "node:os";

const require = createRequire(import.meta.url);
const locate = require("../dist/engine/locate.js");

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const ENGINE_DIR = path.join(REPO, "tools", "storyteller-engine");
const DEMO = path.join(tmpdir(), "storyteller-foreign-workspace-mock");

let failures = 0;

function check(label, condition, detail) {
    if (condition) {
        console.log(`  ok   ${label}`);
    } else {
        failures += 1;
        console.log(`  FAIL ${label}${detail ? `\n       ${detail}` : ""}`);
    }
}

console.log("engine discovery");

// --- the engine repository itself -----------------------------------------
const enclosing = locate.enclosingEngineRoot(path.join(ENGINE_DIR, "cli.py"));
check("finds the repo root from an engine file", enclosing === REPO, `got ${enclosing}`);

const fromSourceFile = locate.enclosingEngineRoot(path.join(ENGINE_DIR, "model_builder.py"));
check("finds the repo root from a source file", fromSourceFile === REPO, `got ${fromSourceFile}`);

check("returns nothing for a repo without an engine",
    locate.enclosingEngineRoot(path.join(DEMO, "src", "main.py")) === undefined);

// --- a window with no folder open ------------------------------------------
const emptyMessage = locate.engineMissingMessage([], "");
check("empty window explains there was nothing to search",
    emptyMessage.includes("No folder is open in this window"), emptyMessage);
check("empty window prints no dangling 'Looked in:' heading",
    !emptyMessage.includes("Looked in:"), emptyMessage);
check("empty window points at the recovery command",
    emptyMessage.includes("Set Engine Directory"), emptyMessage);

const emptyReason = locate.engineMissingReason([], "");
check("empty window reason is one line without a path",
    emptyReason === "No folder is open in this window, so there was nothing to search.", emptyReason);

// --- a folder that has no engine (the demo repository) ---------------------
const demoMessage = locate.engineMissingMessage([DEMO], "");
check("folder without an engine lists the path it tried",
    demoMessage.includes(path.join(DEMO, "tools", "storyteller-engine", "cli.py")), demoMessage);
check("folder without an engine still prints the heading",
    demoMessage.includes("Looked in:"), demoMessage);
check("folder without an engine names the recovery command",
    demoMessage.includes("Set Engine Directory"), demoMessage);

const demoReason = locate.engineMissingReason([DEMO], "");
check("folder without an engine has a one-line reason",
    demoReason.startsWith("No cli.py at "), demoReason);

// --- pointing at an existing engine ---------------------------------------
const configured = locate.findEngine([DEMO], ENGINE_DIR);
check("enginePath resolves against a foreign workspace",
    configured?.origin === "configured" && configured?.cliPath === path.join(ENGINE_DIR, "cli.py"),
    JSON.stringify(configured));

const fromWorkspace = locate.findEngine([REPO], "");
check("workspace engine resolves with origin=workspace",
    fromWorkspace?.origin === "workspace" && fromWorkspace?.cliPath === path.join(ENGINE_DIR, "cli.py"),
    JSON.stringify(fromWorkspace));

check("missing engine in a foreign workspace returns undefined",
    locate.findEngine([DEMO], "") === undefined);

// --- python resolution ------------------------------------------------------
const python = locate.findPython([REPO], "");
check("finds a python interpreter", typeof python === "string" && python.length > 0, python);
check("honours a configured interpreter",
    locate.findPython([REPO], "C:\\custom\\python.exe") === "C:\\custom\\python.exe" &&
    locate.findPython([REPO], '"C:\\custom\\python.exe"') === "C:\\custom\\python.exe");

check("the engine directory actually exists on this machine", existsSync(path.join(ENGINE_DIR, "cli.py")));

console.log(failures === 0 ? "\nall checks passed" : `\n${failures} check(s) failed`);
process.exit(failures === 0 ? 0 : 1);
