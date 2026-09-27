/**
 * patchContentProvider.ts
 * -----------------------
 * Virtual Document Provider for side-by-side diff previews of preventive patches.
 * Scheme: `ripple-patch`
 */

import * as vscode from 'vscode';
import { PreventivePatch } from '../engine/types';

export class RipplePatchContentProvider implements vscode.TextDocumentContentProvider, vscode.Disposable {
    public static readonly scheme = 'ripple-patch';

    private readonly _onDidChange = new vscode.EventEmitter<vscode.Uri>();
    public readonly onDidChange = this._onDidChange.event;

    private readonly patches = new Map<string, PreventivePatch>();
    private readonly registration: vscode.Disposable;

    constructor() {
        this.registration = vscode.workspace.registerTextDocumentContentProvider(
            RipplePatchContentProvider.scheme,
            this
        );
    }

    public registerPatch(patch: PreventivePatch): vscode.Uri {
        // Path key normalized
        const key = patch.file.replace(/\\/g, '/');
        this.patches.set(key, patch);
        const uri = vscode.Uri.from({
            scheme: RipplePatchContentProvider.scheme,
            path: '/' + key,
            query: `t=${Date.now()}`,
        });
        this._onDidChange.fire(uri);
        return uri;
    }

    public getPatch(key: string): PreventivePatch | undefined {
        return this.patches.get(key.replace(/\\/g, '/').replace(/^\//, ''));
    }

    public getAllPatches(): PreventivePatch[] {
        return Array.from(this.patches.values());
    }

    public provideTextDocumentContent(uri: vscode.Uri): string {
        const key = uri.path.replace(/^\//, '');
        const patch = this.patches.get(key);
        return patch?.patched_content ?? '// No patch content available';
    }

    public dispose(): void {
        this.registration.dispose();
        this._onDidChange.dispose();
    }
}
