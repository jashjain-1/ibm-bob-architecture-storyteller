# 🎯 IBM Bob Execution Prompt: VS Code Extension for Architecture Storyteller & Archival Context

You are acting as an expert VS Code Extension architect and TypeScript execution engine.
Your mission is to construct the **complete, fully functioning, strictly typed VS Code Extension** inside the `vscode-extension/` directory of this workspace.

This extension natively bridges the existing Python backend engines:
- `tools/storyteller-engine/cli.py` (`mindmap`, `context`, `pdf`)
- `orchestrator/generate_dossier.py` (ReportLab Platypus publication PDF generator)

Follow this specification to generate all files with zero omissions, strict types, and robust error handling.

---

## 📁 TARGET DIRECTORY STRUCTURE

```
vscode-extension/
├── package.json
├── tsconfig.json
└── src/
    ├── types.ts
    ├── terminalWatcher.ts
    ├── depthModal.ts
    ├── engineBridge.ts
    ├── webviewPanel.ts
    └── extension.ts
```

---

## 🛠️ FILE 1: `vscode-extension/package.json`

Create `vscode-extension/package.json` with the following configuration:

```json
{
  "name": "architecture-storyteller",
  "displayName": "Architecture Storyteller & Archival Context",
  "description": "Interactive visual mindmap, 5-minute plain-English onboarding storyboard, archival context popups, and PDF dossier generator.",
  "version": "1.0.0",
  "publisher": "ibm-bob",
  "engines": {
    "vscode": "^1.88.0"
  },
  "categories": [
    "Visualization",
    "Programming Languages",
    "Other"
  ],
  "main": "./dist/extension.js",
  "activationEvents": [
    "onCommand:storyteller.mindmap",
    "onCommand:storyteller.context",
    "onCommand:storyteller.pdf",
    "onCommand:storyteller.exportDossier",
    "onTerminal"
  ],
  "contributes": {
    "commands": [
      {
        "command": "storyteller.mindmap",
        "title": "Open Architecture Storyboard & Mindmap (/mindmap)",
        "category": "Architecture Storyteller",
        "icon": "$(type-hierarchy-sub)"
      },
      {
        "command": "storyteller.context",
        "title": "Inspect Archival Context & Backstory (/context)",
        "category": "Architecture Storyteller",
        "icon": "$(history)"
      },
      {
        "command": "storyteller.pdf",
        "title": "Export Architecture Dossier to PDF (/pdf)",
        "category": "Architecture Storyteller",
        "icon": "$(file-pdf)"
      },
      {
        "command": "storyteller.exportDossier",
        "title": "Generate Deep Publication PDF (ReportLab Platypus)",
        "category": "Architecture Storyteller",
        "icon": "$(book)"
      }
    ],
    "menus": {
      "editor/context": [
        {
          "command": "storyteller.context",
          "group": "7_modification@1",
          "when": "editorHasSelection || editorTextFocus"
        }
      ],
      "commandPalette": [
        { "command": "storyteller.mindmap" },
        { "command": "storyteller.context" },
        { "command": "storyteller.pdf" },
        { "command": "storyteller.exportDossier" }
      ]
    },
    "configuration": {
      "title": "Architecture Storyteller",
      "properties": {
        "storyteller.pythonPath": {
          "type": "string",
          "default": "",
          "description": "Custom path to Python interpreter. If empty, automatically discovers workspace venv or system python."
        },
        "storyteller.defaultDepth": {
          "type": "number",
          "default": 1,
          "enum": [1, 2, 3],
          "description": "Default technical depth level (1=High-level story, 2=Flow dynamics, 3=Archival forensic)."
        }
      }
    }
  },
  "scripts": {
    "vscode:prepublish": "npm run compile",
    "compile": "tsc -p ./",
    "watch": "tsc -watch -p ./"
  },
  "devDependencies": {
    "@types/node": "^20.11.24",
    "@types/vscode": "^1.88.0",
    "typescript": "^5.4.2"
  }
}
```

---

## 🛠️ FILE 2: `vscode-extension/tsconfig.json`

```json
{
  "compilerOptions": {
    "module": "commonjs",
    "target": "ES2022",
    "lib": ["ES2022", "DOM"],
    "outDir": "./dist",
    "rootDir": "./src",
    "strict": true,
    "esModuleInterop": true,
    "skipLibCheck": true,
    "forceConsistentCasingInFileNames": true,
    "sourceMap": true
  },
  "include": ["src/**/*"],
  "exclude": ["node_modules", ".vscode-test"]
}
```

---

## 🛠️ FILE 3: `vscode-extension/src/types.ts`

Define all data contracts mapping 1:1 to the output of `tools/storyteller-engine/synthesizer.py`:

```typescript
export interface CallSite {
    caller_file: string;
    line_number: number;
    enclosing_symbol: string;
    snippet: string;
    arguments?: string[];
}

export interface Backstory {
    symbol_name: string;
    pr_number: number | string;
    pr_title: string;
    author: string;
    date: string;
    commit_sha: string;
    discussion_summary: string;
    why_it_was_written: string;
    data_source_tier: string;
    raw_discussion_excerpts?: string[];
}

export interface ContextPopup {
    symbol_name: string;
    definition_file: string;
    definition_line: number;
    call_sites_count: number;
    call_sites: CallSite[];
    complexity: number;
    unusual_flags: string[];
    backstory: Backstory;
}

export interface StoryChapter {
    title: string;
    content: string;
}

export interface ArchitectureStoryboard {
    project_name: string;
    executive_summary: string;
    five_minute_story: StoryChapter[];
    mermaid_diagram: string;
    context_popups: ContextPopup[];
    total_routes: number;
    total_models: number;
    total_service_calls: number;
    technical_depth: number;
    active_layers: string[];
}

export interface AnalysisScopeOptions {
    depth: number;
    layers: string[];
    artifact: 'mindmap' | 'context' | 'pdf' | 'dossier';
    symbol?: string;
}
```

---

## 🛠️ FILE 4: `vscode-extension/src/terminalWatcher.ts`

Implement the slash-command watcher with dual support:
1. `vscode.window.onDidStartTerminalShellExecution` (VS Code 1.88+ shell integration).
2. Command input interceptor / terminal creation banner guiding the developer to use `/mindmap`, `/context`, and `/pdf`.

```typescript
import * as vscode from 'vscode';

export function registerTerminalSlashWatcher(context: vscode.ExtensionContext): void {
    // 1. Hook into Terminal Shell Execution (VS Code 1.88+ Shell Integration)
    if ('onDidStartTerminalShellExecution' in vscode.window) {
        const shellExecWatcher = (vscode.window as any).onDidStartTerminalShellExecution(
            async (event: any) => {
                const cmd = event.execution?.commandLine?.value?.trim() || '';
                if (!cmd) return;

                if (cmd === '/mindmap') {
                    vscode.commands.executeCommand('storyteller.mindmap');
                } else if (cmd === '/pdf') {
                    vscode.commands.executeCommand('storyteller.pdf');
                } else if (cmd.startsWith('/context')) {
                    const parts = cmd.split(/\s+/);
                    const symbol = parts.length > 1 ? parts[1] : undefined;
                    vscode.commands.executeCommand('storyteller.context', symbol);
                }
            }
        );
        context.subscriptions.push(shellExecWatcher);
    }

    // 2. Terminal creation listener with helpful quick-action hint
    const terminalOpenWatcher = vscode.window.onDidOpenTerminal((terminal) => {
        // Optional subtle terminal greeting or status notification
    });
    context.subscriptions.push(terminalOpenWatcher);
}
```

---

## 🛠️ FILE 5: `vscode-extension/src/depthModal.ts`

Implement a multi-step interactive modal using VS Code's `showQuickPick` and `showInputBox`:
- **Step 1: Technical Depth (Levels 1–3)**
  - Level 1: "Level 1: High-Level Architecture Story (5-min onboarding overview)"
  - Level 2: "Level 2: Service & Flow Dynamics (Call graph & data contracts)"
  - Level 3: "Level 3: Deep Archival Forensic (Cross-referenced call-sites & PR # backstory)"
- **Step 2: Granular Layer Filters (Multi-select)**
  - Frontend Services (`frontend`)
  - Backend API Routes (`backend`)
  - Database Models (`db`)
  - Archival PR Backstory (`git`)
- **Step 3: Target Artifact Selection**
  - "Interactive Mindmap & Storyboard"
  - "Archival Context Popups"
  - "PDF Architecture Dossier (Chromium / ReportLab)"

```typescript
import * as vscode from 'vscode';
import { AnalysisScopeOptions } from './types';

export async function promptUserForAnalysisScope(initialSymbol?: string): Promise<AnalysisScopeOptions | undefined> {
    // Step 1: Technical Depth
    const depthItems: (vscode.QuickPickItem & { depth: number })[] = [
        {
            label: "$(book) Level 1: High-Level Architecture Story",
            description: "5-minute onboarding overview for fast ramp-up",
            depth: 1,
            picked: true
        },
        {
            label: "$(git-merge) Level 2: Service & Flow Dynamics",
            description: "Detailed call-graph, API contracts & database couplings",
            depth: 2
        },
        {
            label: "$(shield) Level 3: Deep Archival Forensic",
            description: "Cross-referenced call-sites, PR backstories & unusual logic barriers",
            depth: 3
        }
    ];

    const selectedDepth = await vscode.window.showQuickPick(depthItems, {
        title: "Architecture Storyteller: Select Technical Depth",
        placeHolder: "Choose technical depth level (1-3)"
    });
    if (!selectedDepth) return undefined;

    // Step 2: Layer Filters (Multi-select)
    const layerItems: (vscode.QuickPickItem & { layerId: string })[] = [
        { label: "Frontend Services & UI Handlers", layerId: "frontend", picked: true },
        { label: "Backend API Routes & Handlers", layerId: "backend", picked: true },
        { label: "Database Models & Schemas", layerId: "db", picked: true },
        { label: "Git PR History & Archival Backstories", layerId: "git", picked: true }
    ];

    const selectedLayers = await vscode.window.showQuickPick(layerItems, {
        title: "Architecture Storyteller: Select Granular Layers",
        placeHolder: "Choose layers to include in graph & storyboard",
        canPickMany: true
    });
    if (!selectedLayers || selectedLayers.length === 0) return undefined;

    // Step 3: Target Artifact
    const artifactItems: (vscode.QuickPickItem & { artifact: 'mindmap' | 'context' | 'pdf' | 'dossier' })[] = [
        {
            label: "$(type-hierarchy-sub) Interactive Mindmap & 5-Min Storyboard",
            description: "Visual Mermaid flowchart with interactive pan/zoom & context popups",
            artifact: 'mindmap'
        },
        {
            label: "$(history) Archival Context Inspector",
            description: "Pivotal function call-site cross-references and PR backstory",
            artifact: 'context'
        },
        {
            label: "$(file-pdf) PDF Architecture Dossier",
            description: "Chromium print or publication-grade Platypus PDF",
            artifact: 'pdf'
        }
    ];

    const selectedArtifact = await vscode.window.showQuickPick(artifactItems, {
        title: "Architecture Storyteller: Select Deliverable Artifact",
        placeHolder: "Choose primary view or export target"
    });
    if (!selectedArtifact) return undefined;

    let targetSymbol = initialSymbol;
    if (selectedArtifact.artifact === 'context' && !targetSymbol) {
        targetSymbol = await vscode.window.showInputBox({
            title: "Archival Context: Target Symbol",
            prompt: "Enter function, method, or class name to inspect backstory",
            placeHolder: "e.g. synthesize, extract_repo_ast, acquire_lock"
        });
    }

    return {
        depth: selectedDepth.depth,
        layers: selectedLayers.map(l => l.layerId),
        artifact: selectedArtifact.artifact,
        symbol: targetSymbol
    };
}
```

---

## 🛠️ FILE 6: `vscode-extension/src/engineBridge.ts`

Implement the execution bridge to spawn `tools/storyteller-engine/cli.py` and `orchestrator/generate_dossier.py`:
- Locate Python interpreter: check `storyteller.pythonPath`, `.venv/Scripts/python.exe` (Windows), `.venv/bin/python` (Unix), or `python`/`python3`.
- Execute with subcommands:
  - `python tools/storyteller-engine/cli.py mindmap --depth <d> --layers <l> --json [--symbol <s>] [--repo <root>]`
  - `python tools/storyteller-engine/cli.py context <symbol> --depth <d> --json [--repo <root>]`
  - `python orchestrator/generate_dossier.py --target <root> --output-dir <output>`

```typescript
import * as vscode from 'vscode';
import * as path from 'path';
import * as fs from 'fs';
import { spawn } from 'child_process';
import { ArchitectureStoryboard, AnalysisScopeOptions } from './types';

export class EngineBridge {
    private workspaceRoot: string;

    constructor() {
        this.workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || process.cwd();
    }

    public getPythonPath(): string {
        const configPath = vscode.workspace.getConfiguration('storyteller').get<string>('pythonPath');
        if (configPath && fs.existsSync(configPath)) {
            return configPath;
        }

        // Virtual environment detection
        const winVenv = path.join(this.workspaceRoot, '.venv', 'Scripts', 'python.exe');
        if (fs.existsSync(winVenv)) return winVenv;

        const unixVenv = path.join(this.workspaceRoot, '.venv', 'bin', 'python');
        if (fs.existsSync(unixVenv)) return unixVenv;

        return process.platform === 'win32' ? 'python' : 'python3';
    }

    public async executeMindmap(options: AnalysisScopeOptions): Promise<ArchitectureStoryboard> {
        const cliPath = path.join(this.workspaceRoot, 'tools', 'storyteller-engine', 'cli.py');
        const args = [
            cliPath,
            'mindmap',
            '--repo', this.workspaceRoot,
            '--depth', String(options.depth),
            '--layers', options.layers.join(','),
            '--json'
        ];
        if (options.symbol) {
            args.push('--symbol', options.symbol);
        }

        const rawOutput = await this.spawnProcess(this.getPythonPath(), args);
        try {
            return JSON.parse(rawOutput) as ArchitectureStoryboard;
        } catch (err: any) {
            throw new Error(`Failed to parse storyteller output JSON: ${err.message}\nRaw: ${rawOutput.slice(0, 300)}`);
        }
    }

    public async executeContext(symbol: string, depth: number = 3): Promise<ArchitectureStoryboard> {
        const cliPath = path.join(this.workspaceRoot, 'tools', 'storyteller-engine', 'cli.py');
        const args = [
            cliPath,
            'context',
            symbol,
            '--repo', this.workspaceRoot,
            '--depth', String(depth),
            '--json'
        ];

        const rawOutput = await this.spawnProcess(this.getPythonPath(), args);
        try {
            return JSON.parse(rawOutput) as ArchitectureStoryboard;
        } catch (err: any) {
            throw new Error(`Failed to parse archival context JSON: ${err.message}\nRaw: ${rawOutput.slice(0, 300)}`);
        }
    }

    public async executeDossier(outputDir?: string): Promise<string> {
        const scriptPath = path.join(this.workspaceRoot, 'orchestrator', 'generate_dossier.py');
        const outDir = outputDir || path.join(this.workspaceRoot, 'output');
        const args = [
            scriptPath,
            '--target', this.workspaceRoot,
            '--output-dir', outDir
        ];

        return await this.spawnProcess(this.getPythonPath(), args);
    }

    private spawnProcess(command: string, args: string[]): Promise<string> {
        return new Promise((resolve, reject) => {
            const proc = spawn(command, args, { cwd: this.workspaceRoot });
            let stdout = '';
            let stderr = '';

            proc.stdout.on('data', (d) => { stdout += d.toString(); });
            proc.stderr.on('data', (d) => { stderr += d.toString(); });

            proc.on('close', (code) => {
                if (code === 0) {
                    resolve(stdout.trim());
                } else {
                    reject(new Error(`Command failed with code ${code}.\nSTDERR: ${stderr}\nSTDOUT: ${stdout}`));
                }
            });

            proc.on('error', (err) => {
                reject(new Error(`Failed to spawn Python process: ${err.message}. Ensure Python is installed.`));
            });
        });
    }
}
```

---

## 🛠️ FILE 7: `vscode-extension/src/webviewPanel.ts`

Create the rich Webview panel that renders:
- Executive Summary & Metrics Header.
- Interactive Mermaid flowchart with mouse drag-to-pan and wheel zoom.
- 5-Minute Plain-English Storyboard accordion.
- Clickable Archival Context cards:
  - Total call sites count, complexity, logic flags.
  - Team backstory (PR #, Author, Date, Commit SHA, Why it was written).
  - Cross-referenced call-sites list: clicking any call site sends a message to the extension to open the file at that exact line.
- Top Action Bar:
  - "Print to PDF (Chromium)": invokes `window.print()` using VS Code's Chromium engine.
  - "Deep Dossier (ReportLab)": sends message to run `orchestrator/generate_dossier.py`.
  - "Refilter Scope": prompts modal again.

```typescript
import * as vscode from 'vscode';
import * as path from 'path';
import { ArchitectureStoryboard, ContextPopup } from './types';

export class StorytellerWebviewPanel {
    public static currentPanel: StorytellerWebviewPanel | undefined;
    private readonly panel: vscode.WebviewPanel;
    private disposables: vscode.Disposable[] = [];

    private constructor(panel: vscode.WebviewPanel, private extensionUri: vscode.Uri) {
        this.panel = panel;
        this.panel.onDidDispose(() => this.dispose(), null, this.disposables);

        // Bi-directional message router
        this.panel.webview.onDidReceiveMessage(
            async (message) => {
                switch (message.command) {
                    case 'openLocation': {
                        await this.openFileAtLine(message.file, message.line);
                        return;
                    }
                    case 'exportReportLabPdf': {
                        vscode.commands.executeCommand('storyteller.exportDossier');
                        return;
                    }
                    case 'refreshAnalysis': {
                        vscode.commands.executeCommand('storyteller.mindmap');
                        return;
                    }
                }
            },
            null,
            this.disposables
        );
    }

    public static render(extensionUri: vscode.Uri, data: ArchitectureStoryboard): StorytellerWebviewPanel {
        const column = vscode.window.activeTextEditor ? vscode.window.activeTextEditor.viewColumn : undefined;

        if (StorytellerWebviewPanel.currentPanel) {
            StorytellerWebviewPanel.currentPanel.panel.reveal(column);
            StorytellerWebviewPanel.currentPanel.update(data);
            return StorytellerWebviewPanel.currentPanel;
        }

        const panel = vscode.window.createWebviewPanel(
            'storytellerStoryboard',
            `Architecture Storyboard: ${data.project_name}`,
            column || vscode.ViewColumn.One,
            {
                enableScripts: true,
                retainContextWhenHidden: true,
                localResourceRoots: [extensionUri]
            }
        );

        StorytellerWebviewPanel.currentPanel = new StorytellerWebviewPanel(panel, extensionUri);
        StorytellerWebviewPanel.currentPanel.update(data);
        return StorytellerWebviewPanel.currentPanel;
    }

    public update(data: ArchitectureStoryboard): void {
        this.panel.title = `Storyboard: ${data.project_name}`;
        this.panel.webview.html = this.getHtmlForWebview(data);
    }

    private async openFileAtLine(filePath: string, line: number): Promise<void> {
        const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath || '';
        const fullPath = path.isAbsolute(filePath) ? filePath : path.join(root, filePath);
        const docUri = vscode.Uri.file(fullPath);

        try {
            const doc = await vscode.workspace.openTextDocument(docUri);
            const editor = await vscode.window.showTextDocument(doc, {
                viewColumn: vscode.ViewColumn.Beside,
                preview: true
            });
            const pos = new vscode.Position(Math.max(0, line - 1), 0);
            editor.selection = new vscode.Selection(pos, pos);
            editor.revealRange(new vscode.Range(pos, pos), vscode.TextEditorRevealType.InCenter);
        } catch (err: any) {
            vscode.window.showErrorMessage(`Cannot open file ${filePath}: ${err.message}`);
        }
    }

    public dispose(): void {
        StorytellerWebviewPanel.currentPanel = undefined;
        this.panel.dispose();
        while (this.disposables.length) {
            const x = this.disposables.pop();
            if (x) x.dispose();
        }
    }

    private getHtmlForWebview(data: ArchitectureStoryboard): string {
        const popupsJson = JSON.stringify(data.context_popups || []).replace(/</g, '\\u003c');
        const mermaidCode = data.mermaid_diagram || 'graph LR\n  A[Empty Diagram]';

        return `<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>${data.project_name} - Architecture Storyboard</title>
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <style>
        :root {
            --bg-color: #0d1117;
            --card-bg: #161b22;
            --border-color: #30363d;
            --text-color: #c9d1d9;
            --accent-cyan: #38bdf8;
            --accent-purple: #a855f7;
            --accent-green: #10b981;
            --accent-rose: #f43f5e;
            --badge-bg: #21262d;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            margin: 0;
            padding: 24px;
            line-height: 1.5;
        }
        .header-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 16px;
            margin-bottom: 20px;
        }
        .title-block h1 {
            margin: 0 0 6px 0;
            font-size: 22px;
            color: var(--accent-cyan);
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .badges-row {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }
        .badge {
            background: var(--badge-bg);
            border: 1px solid var(--border-color);
            padding: 3px 8px;
            border-radius: 6px;
            font-size: 12px;
            font-weight: 500;
        }
        .badge.cyan { border-color: var(--accent-cyan); color: var(--accent-cyan); }
        .badge.purple { border-color: var(--accent-purple); color: var(--accent-purple); }
        .badge.green { border-color: var(--accent-green); color: var(--accent-green); }
        .badge.rose { border-color: var(--accent-rose); color: var(--accent-rose); }
        
        .action-buttons {
            display: flex;
            gap: 10px;
        }
        .btn {
            background: #238636;
            color: #ffffff;
            border: 1px solid rgba(240, 246, 252, 0.1);
            padding: 6px 14px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 13px;
            font-weight: 600;
            transition: background 0.15s;
        }
        .btn:hover { background: #2ea043; }
        .btn.secondary { background: #21262d; border-color: #363b42; color: #c9d1d9; }
        .btn.secondary:hover { background: #30363d; }

        .card {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 8px;
            padding: 16px 20px;
            margin-bottom: 20px;
        }
        .card h2 {
            margin-top: 0;
            font-size: 16px;
            color: var(--accent-cyan);
            border-bottom: 1px solid rgba(255,255,255,0.06);
            padding-bottom: 8px;
        }

        /* Pan & Zoom Container */
        .diagram-container {
            position: relative;
            overflow: hidden;
            background: #090d13;
            border-radius: 6px;
            border: 1px solid var(--border-color);
            min-height: 420px;
            cursor: grab;
            display: flex;
            justify-content: center;
            align-items: center;
        }
        .diagram-container:active { cursor: grabbing; }
        .diagram-viewport {
            transform-origin: center center;
            transition: transform 0.05s ease-out;
        }
        .diagram-controls {
            position: absolute;
            bottom: 12px;
            right: 12px;
            display: flex;
            gap: 6px;
            z-index: 10;
        }
        .ctrl-btn {
            background: rgba(33, 38, 45, 0.85);
            border: 1px solid var(--border-color);
            color: #fff;
            width: 28px;
            height: 28px;
            border-radius: 4px;
            cursor: pointer;
            font-weight: bold;
        }

        /* 5-minute story accordion */
        .story-accordion details {
            background: #11161d;
            border: 1px solid var(--border-color);
            border-radius: 6px;
            margin-bottom: 10px;
            padding: 10px 14px;
        }
        .story-accordion summary {
            font-weight: 600;
            color: #58a6ff;
            cursor: pointer;
            outline: none;
        }
        .story-accordion p {
            margin: 10px 0 4px 0;
            font-size: 13.5px;
            color: #8b949e;
        }

        /* Archival context cards */
        .popups-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
            gap: 16px;
        }
        .context-card {
            background: #11161d;
            border: 1px solid var(--border-color);
            border-left: 4px solid var(--accent-rose);
            border-radius: 6px;
            padding: 14px;
        }
        .context-card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }
        .symbol-title {
            font-family: monospace;
            font-size: 15px;
            font-weight: bold;
            color: #f0883e;
        }
        .backstory-box {
            background: #161b22;
            border: 1px solid rgba(244, 63, 94, 0.3);
            border-radius: 4px;
            padding: 10px;
            margin: 10px 0;
            font-size: 12.5px;
        }
        .backstory-quote {
            font-style: italic;
            color: #ff7b72;
            margin: 4px 0;
        }
        .call-sites-list {
            margin-top: 8px;
            max-height: 140px;
            overflow-y: auto;
            font-size: 12px;
        }
        .call-site-link {
            display: block;
            padding: 3px 6px;
            color: #58a6ff;
            text-decoration: none;
            cursor: pointer;
            border-radius: 3px;
        }
        .call-site-link:hover {
            background: #21262d;
            text-decoration: underline;
        }

        @media print {
            body { background: #ffffff !important; color: #000000 !important; }
            .header-bar, .action-buttons, .diagram-controls { display: none !important; }
            .card { border: 1px solid #ddd !important; background: #fff !important; }
            .diagram-container { border: none !important; background: #fff !important; }
        }
    </style>
</head>
<body>
    <div class="header-bar">
        <div class="title-block">
            <h1>🗺️ Architecture Storyboard: ${data.project_name}</h1>
            <div class="badges-row">
                <span class="badge cyan">Routes: ${data.total_routes}</span>
                <span class="badge purple">Models: ${data.total_models}</span>
                <span class="badge green">Frontend Calls: ${data.total_service_calls}</span>
                <span class="badge rose">Depth: Level ${data.technical_depth}</span>
                <span class="badge">Layers: ${data.active_layers.join(', ')}</span>
            </div>
        </div>
        <div class="action-buttons">
            <button class="btn secondary" onclick="vscode.postMessage({ command: 'refreshAnalysis' })">🔄 Re-analyze</button>
            <button class="btn secondary" onclick="vscode.postMessage({ command: 'exportReportLabPdf' })">📖 Deep Dossier</button>
            <button class="btn" onclick="window.print()">🖨️ Export PDF</button>
        </div>
    </div>

    <div class="card">
        <h2>Executive Architecture Story</h2>
        <p>${data.executive_summary}</p>
    </div>

    <div class="card">
        <h2>Visual Architecture Map (Pan & Zoom)</h2>
        <div class="diagram-container" id="diagramContainer">
            <div class="diagram-viewport" id="diagramViewport">
                <div class="mermaid" id="mermaidGraph">
${mermaidCode}
                </div>
            </div>
            <div class="diagram-controls">
                <button class="ctrl-btn" onclick="zoomIn()">+</button>
                <button class="ctrl-btn" onclick="zoomOut()">-</button>
                <button class="ctrl-btn" onclick="resetZoom()">⟲</button>
            </div>
        </div>
    </div>

    <div class="card">
        <h2>📖 5-Minute Plain-English Storyboard</h2>
        <div class="story-accordion">
            ${data.five_minute_story.map((chap, i) => `
                <details ${i === 0 ? 'open' : ''}>
                    <summary>${chap.title}</summary>
                    <p>${chap.content}</p>
                </details>
            `).join('')}
        </div>
    </div>

    <div class="card">
        <h2>🔍 Archival Context & Backstories (${data.context_popups.length} Pivotal Symbols)</h2>
        <div class="popups-grid">
            ${data.context_popups.map(p => `
                <div class="context-card">
                    <div class="context-card-header">
                        <span class="symbol-title">${p.symbol_name}</span>
                        <span class="badge ${p.complexity > 5 ? 'rose' : 'green'}">Complexity: ${p.complexity}</span>
                    </div>
                    <div style="font-size:12px; color:#8b949e;">
                        Defined in: <code>${p.definition_file}:${p.definition_line}</code>
                    </div>
                    ${p.unusual_flags.length ? `<div style="font-size:11.5px; color:#e3b341; margin-top:4px;">⚠️ ${p.unusual_flags.join(', ')}</div>` : ''}

                    <div class="backstory-box">
                        <strong>PR #${p.backstory.pr_number}:</strong> ${p.backstory.pr_title}<br/>
                        <span style="color:#8b949e">Author: @${p.backstory.author} (${p.backstory.date})</span>
                        <div class="backstory-quote">"${p.backstory.why_it_was_written}"</div>
                    </div>

                    <div style="font-size:12px; font-weight:600; margin-top:6px;">
                        📍 Cross-Referenced Call Sites (${p.call_sites_count} total):
                    </div>
                    <div class="call-sites-list">
                        ${p.call_sites.slice(0, 8).map(cs => `
                            <a class="call-site-link" onclick="openFile('${cs.caller_file}', ${cs.line_number})">
                                🔗 <code>${cs.caller_file}:${cs.line_number}</code> in <i>${cs.enclosing_symbol}()</i>
                            </a>
                        `).join('')}
                    </div>
                </div>
            `).join('')}
        </div>
    </div>

    <script>
        const vscode = acquireVsCodeApi();
        mermaid.initialize({ startOnLoad: true, theme: 'dark' });

        function openFile(file, line) {
            vscode.postMessage({ command: 'openLocation', file: file, line: line });
        }

        // Pan and Zoom logic
        let scale = 1.0;
        let translateX = 0;
        let translateY = 0;
        let isDragging = false;
        let startX = 0, startY = 0;

        const container = document.getElementById('diagramContainer');
        const viewport = document.getElementById('diagramViewport');

        function updateTransform() {
            viewport.style.transform = \`translate(\${translateX}px, \${translateY}px) scale(\${scale})\`;
        }

        function zoomIn() { scale = Math.min(3.0, scale + 0.15); updateTransform(); }
        function zoomOut() { scale = Math.max(0.3, scale - 0.15); updateTransform(); }
        function resetZoom() { scale = 1.0; translateX = 0; translateY = 0; updateTransform(); }

        container.addEventListener('wheel', (e) => {
            e.preventDefault();
            const delta = e.deltaY > 0 ? -0.1 : 0.1;
            scale = Math.max(0.3, Math.min(3.0, scale + delta));
            updateTransform();
        });

        container.addEventListener('mousedown', (e) => {
            if (e.target.tagName.toLowerCase() === 'button') return;
            isDragging = true;
            startX = e.clientX - translateX;
            startY = e.clientY - translateY;
        });

        window.addEventListener('mousemove', (e) => {
            if (!isDragging) return;
            translateX = e.clientX - startX;
            translateY = e.clientY - startY;
            updateTransform();
        });

        window.addEventListener('mouseup', () => { isDragging = false; });
    </script>
</body>
</html>`;
    }
}
```

---

## 🛠️ FILE 8: `vscode-extension/src/extension.ts`

Tie together all components into the extension activation lifecycle:

```typescript
import * as vscode from 'vscode';
import { registerTerminalSlashWatcher } from './terminalWatcher';
import { promptUserForAnalysisScope } from './depthModal';
import { EngineBridge } from './engineBridge';
import { StorytellerWebviewPanel } from './webviewPanel';

export function activate(context: vscode.ExtensionContext) {
    const bridge = new EngineBridge();

    // 1. Register Terminal Slash-Command Watcher (/mindmap, /pdf, /context)
    registerTerminalSlashWatcher(context);

    // 2. Register 'storyteller.mindmap'
    const cmdMindmap = vscode.commands.registerCommand('storyteller.mindmap', async () => {
        try {
            const scope = await promptUserForAnalysisScope();
            if (!scope) return;

            await vscode.window.withProgress(
                {
                    location: vscode.ProgressLocation.Notification,
                    title: `Synthesizing Architecture Storyboard (Depth Level ${scope.depth})...`,
                    cancellable: false
                },
                async () => {
                    const storyboard = await bridge.executeMindmap(scope);
                    StorytellerWebviewPanel.render(context.extensionUri, storyboard);
                }
            );
        } catch (err: any) {
            vscode.window.showErrorMessage(`Storyteller Error: ${err.message}`);
        }
    });

    // 3. Register 'storyteller.context'
    const cmdContext = vscode.commands.registerCommand('storyteller.context', async (symbolArg?: string) => {
        try {
            let symbol = symbolArg;
            if (!symbol) {
                // If text is selected in the active editor, use it as default
                const editor = vscode.window.activeTextEditor;
                if (editor && !editor.selection.isEmpty) {
                    symbol = editor.document.getText(editor.selection).trim();
                }
            }

            if (!symbol) {
                symbol = await vscode.window.showInputBox({
                    title: "Archival Context Inspector",
                    prompt: "Enter function, class, or method name to inspect backstory",
                    placeHolder: "e.g. synthesize, extract_repo_ast, DeadlockDetector"
                });
            }
            if (!symbol) return;

            await vscode.window.withProgress(
                {
                    location: vscode.ProgressLocation.Notification,
                    title: `Mining Archival Context for '${symbol}'...`,
                    cancellable: false
                },
                async () => {
                    const storyboard = await bridge.executeContext(symbol, 3);
                    StorytellerWebviewPanel.render(context.extensionUri, storyboard);
                }
            );
        } catch (err: any) {
            vscode.window.showErrorMessage(`Archival Context Error: ${err.message}`);
        }
    });

    // 4. Register 'storyteller.pdf' (Dual mode: Reveals webview with print prompt or triggers ReportLab)
    const cmdPdf = vscode.commands.registerCommand('storyteller.pdf', async () => {
        const choice = await vscode.window.showQuickPick(
            [
                {
                    label: "$(device-camera-video) Chromium Print-to-PDF (Webview)",
                    description: "Instant vector PDF print of the active mindmap and storyboard",
                    id: "chromium"
                },
                {
                    label: "$(book) Deep ReportLab Platypus PDF Dossier",
                    description: "Run backend publication generator (orchestrator/generate_dossier.py)",
                    id: "reportlab"
                }
            ],
            { title: "Select PDF Export Mode" }
        );

        if (!choice) return;

        if (choice.id === "chromium") {
            vscode.commands.executeCommand('storyteller.mindmap');
        } else {
            vscode.commands.executeCommand('storyteller.exportDossier');
        }
    });

    // 5. Register 'storyteller.exportDossier' (ReportLab Engine)
    const cmdDossier = vscode.commands.registerCommand('storyteller.exportDossier', async () => {
        try {
            await vscode.window.withProgress(
                {
                    location: vscode.ProgressLocation.Notification,
                    title: "Generating Publication-Grade PDF Dossier via ReportLab...",
                    cancellable: false
                },
                async () => {
                    const outputLog = await bridge.executeDossier();
                    vscode.window.showInformationMessage("Dossier generated successfully in output/ directory!");
                }
            );
        } catch (err: any) {
            vscode.window.showErrorMessage(`Dossier Generation Error: ${err.message}`);
        }
    });

    // 6. Status Bar Item for 1-Click Access
    const statusBar = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
    statusBar.command = 'storyteller.mindmap';
    statusBar.text = '$(type-hierarchy-sub) Storyboard';
    statusBar.tooltip = 'Architecture Storyteller & Archival Context';
    statusBar.show();

    context.subscriptions.push(
        cmdMindmap,
        cmdContext,
        cmdPdf,
        cmdDossier,
        statusBar
    );
}

export function deactivate() {}
```

---

## 🔒 VERIFICATION & COMPILATION INSTRUCTIONS FOR BOB
1. Create all 8 files in `vscode-extension/` with the exact paths and contents specified above.
2. In `vscode-extension/`, ensure `npm install` and `npm run compile` succeed with zero TypeScript errors.
3. Verify that `dist/extension.js` is generated.
4. Test running `python tools/storyteller-engine/cli.py mindmap --depth 1 --json` to confirm the backend bridge contract resolves cleanly.
