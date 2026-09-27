/**
 * locate.ts
 * ---------
 * Finds the Python interpreter and the storyteller engine.
 *
 * There is exactly one engine source: `tools/storyteller-engine/cli.py` in the
 * open workspace (or wherever `storyteller.enginePath` points). The extension
 * deliberately does not ship a copy — a bundled duplicate would drift from the
 * analysed source and would be scanned as if it were project code.
 */

import * as fs from 'fs';
import * as path from 'path';

export const ENGINE_RELATIVE = path.join('tools', 'storyteller-engine', 'cli.py');

export interface EngineLocation {
    /** Absolute path to cli.py. */
    cliPath: string;
    /** Where it came from, for the output channel and the status bar. */
    origin: 'configured' | 'workspace';
}

const POSIX_PYTHONS = [
    '.venv/bin/python3',
    '.venv/bin/python',
    'venv/bin/python',
    'env/bin/python',
    '.conda/bin/python',
];

const WINDOWS_PYTHONS = [
    '.venv/Scripts/python.exe',
    'venv/Scripts/python.exe',
    'env/Scripts/python.exe',
    '.conda/python.exe',
];

function resolveConfiguredPath(target: string, workspaceRoots: string[]): string {
    const trimmed = (target || '').trim().replace(/^["']|["']$/g, '');
    if (!trimmed) {
        return '';
    }
    const root = workspaceRoots[0] ?? '';
    const expanded = trimmed.replace(/\$\{workspaceFolder\}/g, root);
    if (!path.isAbsolute(expanded) && root) {
        return path.resolve(root, expanded);
    }
    return expanded;
}

/** Configured interpreter first, then active env, then workspace virtualenv, then system/PATH. */
export function findPython(workspaceRoots: string[], configured: string): string {
    const resolvedConfig = resolveConfiguredPath(configured, workspaceRoots);
    if (resolvedConfig) {
        return resolvedConfig;
    }

    if (process.env.VIRTUAL_ENV) {
        const venvPy = path.join(
            process.env.VIRTUAL_ENV,
            process.platform === 'win32' ? path.join('Scripts', 'python.exe') : path.join('bin', 'python')
        );
        if (fs.existsSync(venvPy)) {
            return venvPy;
        }
    }

    if (process.env.CONDA_PREFIX) {
        const condaPy = path.join(
            process.env.CONDA_PREFIX,
            process.platform === 'win32' ? 'python.exe' : path.join('bin', 'python')
        );
        if (fs.existsSync(condaPy)) {
            return condaPy;
        }
    }

    const relative = process.platform === 'win32' ? WINDOWS_PYTHONS : POSIX_PYTHONS;
    for (const root of workspaceRoots) {
        for (const candidate of relative) {
            const absolute = path.join(root, candidate);
            if (fs.existsSync(absolute)) {
                return absolute;
            }
        }
    }

    if (process.platform === 'win32') {
        const localAppData = process.env.LOCALAPPDATA;
        if (localAppData) {
            const programsPython = path.join(localAppData, 'Programs', 'Python');
            if (fs.existsSync(programsPython)) {
                try {
                    const entries = fs.readdirSync(programsPython, { withFileTypes: true });
                    const pythonDirs = entries
                        .filter(e => e.isDirectory() && /^Python3\d*$/i.test(e.name))
                        .map(e => e.name)
                        .sort((a, b) => b.localeCompare(a, undefined, { numeric: true }));
                    for (const dir of pythonDirs) {
                        const candidate = path.join(programsPython, dir, 'python.exe');
                        if (fs.existsSync(candidate)) {
                            return candidate;
                        }
                    }
                } catch {
                    // Ignore directory read errors
                }
            }
        }
        const windir = process.env.WINDIR || 'C:\\Windows';
        const pyLauncher = path.join(windir, 'py.exe');
        if (fs.existsSync(pyLauncher)) {
            return pyLauncher;
        }
        return 'python';
    }

    return 'python3';
}

/**
 * The repository root holding the engine, found by walking up from a file.
 *
 * Used when no folder is open (or when the open folder has no engine): the user
 * may still have a source file from an engine repository in front of them.
 */
export function enclosingEngineRoot(filePath: string, maxLevels = 8): string | undefined {
    let current = path.dirname(filePath);
    for (let level = 0; level < maxLevels; level += 1) {
        if (fs.existsSync(path.join(current, ENGINE_RELATIVE))) {
            return current;
        }
        const parent = path.dirname(current);
        if (parent === current) {
            break;
        }
        current = parent;
    }
    return undefined;
}

/** Every location the extension will accept, in priority order. */
export function engineCandidates(workspaceRoots: string[], configuredEnginePath: string): string[] {
    const candidates: string[] = [];
    const resolvedConfig = resolveConfiguredPath(configuredEnginePath, workspaceRoots);
    if (resolvedConfig) {
        candidates.push(
            resolvedConfig.endsWith('cli.py') ? resolvedConfig : path.join(resolvedConfig, 'cli.py')
        );
    }
    for (const root of workspaceRoots) {
        candidates.push(path.join(root, ENGINE_RELATIVE));
        if (path.basename(root).toLowerCase() === 'vscode-extension') {
            candidates.push(path.resolve(root, '..', ENGINE_RELATIVE));
        }
    }
    return [...new Set(candidates)];
}

export function findEngine(
    workspaceRoots: string[],
    configuredEnginePath: string
): EngineLocation | undefined {
    const resolvedConfig = resolveConfiguredPath(configuredEnginePath, workspaceRoots);
    for (const candidate of engineCandidates(workspaceRoots, configuredEnginePath)) {
        if (!fs.existsSync(candidate)) {
            continue;
        }
        const normCandidate = path.normalize(candidate).toLowerCase();
        const normConfig = resolvedConfig ? path.normalize(resolvedConfig).toLowerCase() : '';
        const fromSetting = Boolean(normConfig) && normCandidate.startsWith(normConfig);
        return { cliPath: candidate, origin: fromSetting ? 'configured' : 'workspace' };
    }
    return undefined;
}

/** One-line reason, short enough for an error dialog. */
export function engineMissingReason(workspaceRoots: string[], configuredEnginePath: string): string {
    const attempted = engineCandidates(workspaceRoots, configuredEnginePath);
    if (attempted.length === 0) {
        return 'No folder is open in this window, so there was nothing to search.';
    }
    return `No cli.py at ${attempted[0]}`;
}

/** Full diagnostic text: what was looked for, and how to fix it. */
export function engineMissingMessage(workspaceRoots: string[], configuredEnginePath: string): string {
    const attempted = engineCandidates(workspaceRoots, configuredEnginePath);
    const lines = ['Architecture Storyteller could not find its engine (cli.py).', ''];

    if (attempted.length === 0) {
        // Never print a heading with nothing under it: with no folder open there
        // genuinely was nowhere to look.
        lines.push(
            'No folder is open in this window, so there was nothing to search.',
            '',
            'Open the repository that contains tools/storyteller-engine, or run ' +
                '"Storyteller: Set Engine Directory" to point at an existing engine.'
        );
        return lines.join('\n');
    }

    lines.push('Looked in:', ...attempted.map((candidate) => `  - ${candidate}`), '');
    lines.push(
        workspaceRoots.length === 0
            ? 'Only the open file was searched. Open the repository folder, or run ' +
                  '"Storyteller: Set Engine Directory".'
            : 'Run "Storyteller: Set Engine Directory" if the engine lives elsewhere, ' +
                  'then reload the window.'
    );
    return lines.join('\n');
}

/** Open a workspace-relative path (used by the webview file links). */
export function resolveFilePath(workspaceRoot: string, filePath: string): string {
    return path.isAbsolute(filePath) ? filePath : path.join(workspaceRoot, filePath);
}
