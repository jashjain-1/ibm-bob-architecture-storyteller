/**
 * client.ts
 * ---------
 * Talks to the long-lived storyteller engine over localhost HTTP.
 *
 * The engine process is started once per session (`cli.py serve --port 0`), so
 * a hover, a map refresh or a context lookup is one HTTP request instead of a
 * fresh Python process. Requests are served from the engine's in-memory model,
 * which it rebuilds only when the working tree changed.
 */

import * as cp from 'child_process';
import * as http from 'http';
import * as vscode from 'vscode';

import {
    DepthLevel,
    DossierResult,
    HealthPayload,
    IndexReport,
    SymbolContext,
    TreePayload,
    UsagesPayload,
} from './types';

export interface EngineLaunchOptions {
    python: string;
    cliPath: string;
    repo: string;
    bobCommand?: string;
    llmUrl?: string;
    llmModel?: string;
}

interface CacheEntry<T> {
    at: number;
    value: T;
}

const CONTEXT_TTL_MS = 30_000;
const TREE_TTL_MS = 5_000;

export class EngineClient implements vscode.Disposable {
    private child?: cp.ChildProcess;
    private port?: number;
    private starting?: Promise<number>;
    private disposed = false;
    private stderrTail: string[] = [];

    private treeCache?: CacheEntry<TreePayload>;
    private contextCache = new Map<string, CacheEntry<SymbolContext>>();
    private usagesCache = new Map<string, CacheEntry<UsagesPayload>>();

    constructor(
        private readonly options: EngineLaunchOptions,
        private readonly output: vscode.OutputChannel
    ) {}

    // -- lifecycle ---------------------------------------------------------

    private async ensureStarted(): Promise<number> {
        if (this.disposed) {
            throw new Error('Storyteller engine has been disposed.');
        }
        if (this.port) {
            return this.port;
        }
        if (!this.starting) {
            this.starting = this.launch().finally(() => {
                this.starting = undefined;
            });
        }
        return this.starting;
    }

    private launch(): Promise<number> {
        return new Promise<number>((resolve, reject) => {
            const args = [
                this.options.cliPath,
                'serve',
                '--port', '0',
                '--repo', this.options.repo,
                // If this extension host dies without running its dispose path
                // (crashed or force-killed window), the engine must not linger.
                '--watch-parent',
                '--parent-pid', String(process.pid),
            ];
            this.output.appendLine(`[engine] ${this.options.python} ${args.join(' ')}`);

            const child = cp.spawn(this.options.python, args, {
                cwd: this.options.repo,
                windowsHide: true,
            });
            this.child = child;
            this.stderrTail = [];

            let settled = false;
            const timer = setTimeout(() => {
                if (!settled) {
                    settled = true;
                    child.kill();
                    reject(new Error(
                        'Storyteller engine did not report a port within 60s.\n' + this.stderrText()
                    ));
                }
            }, 60_000);

            let buffer = '';
            child.stdout?.on('data', (chunk: Buffer) => {
                buffer += chunk.toString('utf8');
                let index = buffer.indexOf('\n');
                while (index >= 0) {
                    const line = buffer.slice(0, index).trim();
                    buffer = buffer.slice(index + 1);
                    index = buffer.indexOf('\n');
                    if (!line) {
                        continue;
                    }
                    this.output.appendLine(`[engine] ${line}`);
                    try {
                        const parsed = JSON.parse(line) as { event?: string; port?: number };
                        if (parsed.event === 'listening' && typeof parsed.port === 'number') {
                            this.port = parsed.port;
                            if (!settled) {
                                settled = true;
                                clearTimeout(timer);
                                resolve(parsed.port);
                            }
                        }
                    } catch {
                        // Non-JSON stdout is just logging.
                    }
                }
            });

            child.stderr?.on('data', (chunk: Buffer) => {
                const text = chunk.toString('utf8').trimEnd();
                if (text) {
                    this.stderrTail.push(text);
                    this.stderrTail = this.stderrTail.slice(-20);
                    this.output.appendLine(`[engine:err] ${text}`);
                }
            });

            child.on('error', (error) => {
                if (!settled) {
                    settled = true;
                    clearTimeout(timer);
                    reject(error);
                }
            });

            child.on('exit', (code) => {
                this.port = undefined;
                this.child = undefined;
                this.output.appendLine(`[engine] exited with code ${code ?? 'null'}`);
                if (!settled) {
                    settled = true;
                    clearTimeout(timer);
                    reject(new Error(
                        `Storyteller engine exited before reporting a port (code ${code ?? 'null'}).\n` +
                        this.stderrText()
                    ));
                }
            });
        });
    }

    private stderrText(): string {
        return this.stderrTail.join('\n').slice(-800);
    }

    /** True once the engine answered a health check in this session. */
    public get isRunning(): boolean {
        return typeof this.port === 'number';
    }

    // -- HTTP --------------------------------------------------------------

    private requestRaw(
        method: 'GET' | 'POST',
        route: string,
        body?: unknown,
        timeoutMs = 30_000
    ): Promise<{ status: number; text: string }> {
        return this.ensureStarted().then((port) => new Promise((resolve, reject) => {
            const payload = body === undefined ? undefined : Buffer.from(JSON.stringify(body), 'utf8');
            const request = http.request(
                {
                    host: '127.0.0.1',
                    port,
                    path: route,
                    method,
                    headers: payload
                        ? { 'Content-Type': 'application/json', 'Content-Length': payload.length }
                        : {},
                },
                (response) => {
                    const chunks: Buffer[] = [];
                    response.on('data', (chunk: Buffer) => chunks.push(chunk));
                    response.on('end', () => {
                        const text = Buffer.concat(chunks).toString('utf8');
                        const status = response.statusCode ?? 0;
                        if (status < 200 || status >= 300) {
                            let message = text.slice(0, 400);
                            try {
                                const parsed = JSON.parse(text) as { error?: string };
                                if (parsed.error) {
                                    message = parsed.error;
                                }
                            } catch {
                                // keep the raw body
                            }
                            reject(new Error(`${route} -> ${status}: ${message}`));
                            return;
                        }
                        resolve({ status, text });
                    });
                }
            );
            request.setTimeout(timeoutMs, () => {
                request.destroy(new Error(`${route} timed out after ${Math.round(timeoutMs / 1000)}s`));
            });
            request.on('error', reject);
            if (payload) {
                request.write(payload);
            }
            request.end();
        }));
    }

    private async request<T>(method: 'GET' | 'POST', route: string, body?: unknown, timeoutMs = 30_000): Promise<T> {
        const { text } = await this.requestRaw(method, route, body, timeoutMs);
        try {
            return JSON.parse(text) as T;
        } catch (error) {
            throw new Error(`${route} returned non-JSON: ${String(error)}`);
        }
    }

    /** Base URL of the running engine, starting it if needed. */
    public async baseUrl(): Promise<string> {
        const port = await this.ensureStarted();
        return `http://127.0.0.1:${port}`;
    }

    public async health(): Promise<HealthPayload> {
        return this.request<HealthPayload>('GET', '/health');
    }

    public async tree(force = false): Promise<TreePayload> {
        const now = Date.now();
        if (!force && this.treeCache && now - this.treeCache.at < TREE_TTL_MS) {
            return this.treeCache.value;
        }
        const payload = await this.request<TreePayload>('GET', '/tree');
        this.treeCache = { at: now, value: payload };
        return payload;
    }

    public async context(symbol: string, lines = 40, force = false): Promise<SymbolContext> {
        const key = `${symbol}|${lines}`;
        const cached = this.contextCache.get(key);
        const now = Date.now();
        if (!force && cached && now - cached.at < CONTEXT_TTL_MS) {
            return cached.value;
        }
        const value = await this.request<SymbolContext>(
            'GET', `/context?symbol=${encodeURIComponent(symbol)}&lines=${lines}`
        );
        this.contextCache.set(key, { at: now, value });
        return value;
    }

    public async usages(symbol: string): Promise<UsagesPayload> {
        const cached = this.usagesCache.get(symbol);
        const now = Date.now();
        if (cached && now - cached.at < CONTEXT_TTL_MS) {
            return cached.value;
        }
        const value = await this.request<UsagesPayload>(
            'GET', `/usages?symbol=${encodeURIComponent(symbol)}`
        );
        this.usagesCache.set(symbol, { at: now, value });
        return value;
    }

    public async index(force = false): Promise<IndexReport> {
        const report = await this.request<IndexReport>('POST', '/index',
            { force, bob_command: this.options.bobCommand, llm_url: this.options.llmUrl, llm_model: this.options.llmModel },
            600_000);
        this.invalidate();
        return report;
    }

    /** Provider settings for dossier builds (Bob writes the prose when configured). */
    private providerSettings(): { bob_command: string; llm_url: string; llm_model: string } {
        return {
            bob_command: this.options.bobCommand ?? '',
            llm_url: this.options.llmUrl ?? '',
            llm_model: this.options.llmModel ?? '',
        };
    }

    public async dossierHtml(level: DepthLevel): Promise<string> {
        // POST, not GET: the build carries the provider settings so the
        // narrative can be written by Bob / the local LLM when configured.
        const result = await this.request<{ level: number; html: string; bytes: number }>(
            'POST', '/dossier?format=json',
            { level, ...this.providerSettings() }, 300_000
        );
        return result.html;
    }

    public async dossierPdf(level: DepthLevel, output?: string): Promise<DossierResult> {
        return this.request<DossierResult>('POST', '/dossier',
            { level, pdf: true, output, ...this.providerSettings() }, 900_000);
    }

    public invalidate(): void {
        this.treeCache = undefined;
        this.contextCache.clear();
        this.usagesCache.clear();
    }

    public dispose(): void {
        this.disposed = true;
        if (this.child) {
            this.output.appendLine('[engine] stopping');
            this.child.kill();
            this.child = undefined;
        }
        this.port = undefined;
    }
}
