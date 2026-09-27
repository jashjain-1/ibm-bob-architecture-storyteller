#!/usr/bin/env python3
"""
scripts/install_extension.py
============================
Installs the Architecture Storyteller extension into both:
1. Microsoft Visual Studio Code (~/.vscode/extensions/)
2. IBM Bob IDE (~/.bobide/extensions/)

Enables instant loading without manual VSIX bundling.

The extension deliberately bundles no copy of the engine. It contains compiled
JavaScript plus its webview assets, and resolves the Python engine from the
workspace at runtime (<workspace>/tools/storyteller-engine/cli.py, or the
storyteller.enginePath setting). Copying the engine, the orchestrator, or the
root scripts into the extension package is what previously produced a second,
ambiguous engine tree inside vscode-extension/, so this installer never does it
and .vscodeignore refuses to ship those directories.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Everything the extension needs at runtime. Anything not listed here is either
# development-only (src, tsconfig, scripts) or lives in the workspace.
PAYLOAD = ["package.json", "dist", "media"]

def _find_repo_root(start: Path) -> Path:
    """Locate the repository root by walking up to the extension manifest."""
    for candidate in [start, *start.parents]:
        if (candidate / "vscode-extension" / "package.json").exists():
            return candidate
    raise SystemExit(
        "Could not locate the repository root: no vscode-extension/package.json "
        f"found at or above {start}"
    )


WORKSPACE_ROOT = _find_repo_root(Path(__file__).resolve().parent)
EXT_DIR = WORKSPACE_ROOT / "vscode-extension"

# Identity comes from the manifest so a version bump never leaves the installer
# pointing at a stale artifact or a wrong extension directory.
MANIFEST = json.loads((EXT_DIR / "package.json").read_text(encoding="utf-8"))
EXT_ID = f"{MANIFEST['publisher']}.{MANIFEST['name']}"
EXT_DIRNAME = f"{EXT_ID}-{MANIFEST['version']}"
VSIX_NAME = f"{MANIFEST['name']}-{MANIFEST['version']}.vsix"

USER_HOME = Path.home()
VSCODE_EXT_DIR = USER_HOME / ".vscode" / "extensions" / EXT_DIRNAME
BOBIDE_EXT_DIR = USER_HOME / ".bobide" / "extensions" / EXT_DIRNAME


def ensure_dependencies():
    print("[0/4] Verifying extension build dependencies...")
    node_modules = EXT_DIR / "node_modules"
    if not node_modules.exists():
        print("  Installing npm dependencies in vscode-extension...")
        res = subprocess.run(
            "npm install",
            cwd=EXT_DIR,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        if res.returncode != 0:
            print(f"[ERROR] npm install failed:\n{res.stderr}")
            sys.exit(res.returncode)
        print("  [OK] npm dependencies installed.")


def check_payload():
    missing = [name for name in PAYLOAD if not (EXT_DIR / name).exists()]
    if missing:
        print(f"[ERROR] Missing from {EXT_DIR}: {', '.join(missing)}")
        sys.exit(1)
    engine = WORKSPACE_ROOT / "tools" / "storyteller-engine" / "cli.py"
    if engine.exists():
        print(f"  [OK] Payload complete. Engine resolves from {engine}")
    else:
        print("  [WARN] No engine at tools/storyteller-engine/cli.py.")
        print("         Install anyway, but set 'storyteller.enginePath' at runtime.")


def compile_extension():
    print("[1/4] Compiling VS Code / IBM Bob extension TypeScript...")
    res = subprocess.run(
        "npm run compile",
        cwd=EXT_DIR,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )
    if res.returncode != 0:
        print(f"[ERROR] Compilation failed:\n{res.stderr}")
        sys.exit(res.returncode)
    print("Compilation successful.")


def remove_stale_versions(parent: Path):
    """Drop older versions of this extension so only one copy can load."""
    for sibling in sorted(parent.glob(f"{EXT_ID}-*")):
        if sibling.name == EXT_DIRNAME:
            continue
        shutil.rmtree(sibling, ignore_errors=True)
        print(f"  Removed stale version: {sibling.name}")


def install_to(target_dir: Path, name: str):
    print(f"\nInstalling to {name}: {target_dir}")
    remove_stale_versions(target_dir.parent)
    if target_dir.exists():
        print(f"  Cleaning previous installation at {target_dir}...")
        shutil.rmtree(target_dir, ignore_errors=True)

    target_dir.mkdir(parents=True, exist_ok=True)

    for entry in PAYLOAD:
        src = EXT_DIR / entry
        if not src.exists():
            continue
        if src.is_dir():
            shutil.copytree(src, target_dir / entry)
        else:
            shutil.copy2(src, target_dir / entry)

    # Copy README.md if present
    readme = EXT_DIR / "README.md"
    if readme.exists():
        shutil.copy2(readme, target_dir / "README.md")

    print(f"  [OK] Successfully installed in {name}!")


def package_vsix() -> Path:
    print("[2/4] Packaging extension VSIX...")
    res = subprocess.run(
        "npx --yes @vscode/vsce package --allow-missing-repository",
        cwd=EXT_DIR,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )
    vsix_path = EXT_DIR / VSIX_NAME
    if not vsix_path.exists():
        print(f"[WARN] VSIX packaging note:\n{res.stderr or res.stdout}")
    else:
        print(f"  [OK] Packaged VSIX: {vsix_path.name} ({vsix_path.stat().st_size // 1024} KB)")
    return vsix_path


def install_via_cli(vsix_path: Path):
    print(f"\n[3/4] Installing {EXT_DIRNAME} via IDE CLI runners...")

    # 1. VS Code CLI
    if vsix_path.exists():
        res_code = subprocess.run(
            f'code --install-extension "{vsix_path}" --force',
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        if res_code.returncode == 0:
            print("  [OK] Successfully installed in Microsoft VS Code via CLI!")
        else:
            print(f"  [WARN] VS Code CLI install note: {res_code.stderr.strip() or res_code.stdout.strip()}")

    # 2. IBM Bob IDE CLI
    bob_cmd = os.path.expandvars(r"%LOCALAPPDATA%\Programs\IBM Bob\bin\bobide.cmd")
    bob_exec = f'"{bob_cmd}"' if os.path.exists(bob_cmd) else "bobide.cmd"
    if vsix_path.exists():
        res_bob = subprocess.run(
            f'{bob_exec} --install-extension "{vsix_path}" --force',
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace"
        )
        if res_bob.returncode == 0:
            print("  [OK] Successfully installed in IBM Bob IDE via CLI!")
        else:
            print(f"  [WARN] IBM Bob IDE CLI install note: {res_bob.stderr.strip() or res_bob.stdout.strip()}")


def verify_installations():
    print("\n[4/4] Verifying installations...")

    # Check VS Code CLI
    code_res = subprocess.run(
        "code --list-extensions",
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )
    if EXT_ID in code_res.stdout.lower():
        print(f"  [OK] Verified in VS Code CLI: {EXT_ID}")
    else:
        print(f"  [INFO] VS Code directory fallback: {VSCODE_EXT_DIR}")

    # Check IBM Bob CLI
    bob_cmd = os.path.expandvars(r"%LOCALAPPDATA%\Programs\IBM Bob\bin\bobide.cmd")
    bob_exec = f'"{bob_cmd}"' if os.path.exists(bob_cmd) else "bobide.cmd"
    bob_res = subprocess.run(
        f"{bob_exec} --list-extensions",
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )
    if EXT_ID in bob_res.stdout.lower():
        print(f"  [OK] Verified in IBM Bob IDE CLI: {EXT_ID}")
    else:
        print(f"  [INFO] IBM Bob IDE directory fallback: {BOBIDE_EXT_DIR}")


def main():
    print("=" * 60)
    print("Architecture Storyteller - Polyglot IDE Installer")
    print("=" * 60)

    ensure_dependencies()
    compile_extension()
    check_payload()
    vsix_path = package_vsix()

    # Direct VSIX installation (standard IDE registry)
    install_via_cli(vsix_path)

    # Directory copy fallback (local development)
    install_to(VSCODE_EXT_DIR, "Microsoft VS Code")
    install_to(BOBIDE_EXT_DIR, "IBM Bob IDE")

    verify_installations()

    print("\n" + "=" * 60)
    print("Installation Complete!")
    print("Restart or reload VS Code & IBM Bob IDE to activate.")
    print("Open a workspace containing tools/storyteller-engine/ to use the engine.")
    print("=" * 60)


if __name__ == "__main__":
    main()
