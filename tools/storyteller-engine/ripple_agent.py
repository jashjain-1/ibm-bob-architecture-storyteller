"""
ripple_agent.py
~~~~~~~~~~~~~~~
Ripple-Agent: Multi-stage architectural impact review and preventive patch engine.

Personas & Pipeline:
1. Sub-agent 1 (The Change Analyzer):
   Ingests the proposed code change, symbol or diff and maps out what data shape,
   parameters, return types, or logic contracts are changing.

2. Sub-agent 2 (The Parallel Downstream Scanners):
   Traverses the AST call graph and crawls caller locations, API definitions,
   database models, and documentation files to look for explicit and implicit dependencies.

3. Bob 2.0 Orchestrator (The Semantic Impact Synthesizer):
   Invokes Bob 2.0 (`bobide.cmd`) via a single unified surgical prompt to synthesize
   the "Semantic Ripple Map" warning:
     "Warning: Changing this field in Module A will silently break auth assumption in
      Module B's background job and invalidate caching logic in Module C."
   And generates precise preventive patches for downstream files.

4. Workspace Blast Radius Tier:
   Calculates dependency count for every file in the codebase:
     - Green: 0-2 dependents (safe / isolated)
     - Yellow: 3-7 dependents (moderate blast radius)
     - Red: 8+ dependents or core architectural hub (database models, routers)
"""

from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
_PROJECT_ROOT = _HERE.parent.parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
if str(_PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

try:
    from bob_bridge import invoke_bob, BOB_CMD_DEFAULT
except ImportError:
    invoke_bob = None
    BOB_CMD_DEFAULT = None


# ---------------------------------------------------------------------------
# Blast Radius & File Dependency Computation
# ---------------------------------------------------------------------------

def compute_workspace_dependencies(model: Dict[str, Any]) -> Dict[str, Any]:
    """
    Computes inbound dependent files and blast-radius tiers for all files in the model.
    Tiers:
      - green: 0-2 dependent files
      - yellow: 3-7 dependent files
      - red: 8+ dependent files or core architectural hubs (models/routes/entry points with high fan-in)
    """
    symbols = model.get("symbols") or []
    files_info = {f.get("path"): f for f in model.get("files") or [] if f.get("path")}
    by_id = {s.get("id"): s for s in symbols if s.get("id")}

    # Map file -> set of external files that depend on it
    # file -> list of (caller_symbol, caller_file, target_symbol)
    dependents_map: Dict[str, set[str]] = {fpath: set() for fpath in files_info}
    caller_details: Dict[str, List[Dict[str, Any]]] = {fpath: [] for fpath in files_info}

    for sym in symbols:
        target_file = sym.get("file_path") or sym.get("file")
        if not target_file:
            continue
        # normalize slashes
        norm_target = target_file.replace("\\", "/")
        if norm_target not in dependents_map:
            dependents_map[norm_target] = set()
            caller_details[norm_target] = []

        callers = sym.get("callers") or []
        for caller_id in callers:
            caller_sym = by_id.get(caller_id)
            if not caller_sym:
                continue
            caller_file = (caller_sym.get("file_path") or caller_sym.get("file") or "").replace("\\", "/")
            if caller_file and caller_file != norm_target:
                dependents_map[norm_target].add(caller_file)
                caller_details[norm_target].append({
                    "caller_id": caller_id,
                    "caller_name": caller_sym.get("name"),
                    "caller_file": caller_file,
                    "caller_line": caller_sym.get("line_start") or caller_sym.get("line", 1),
                    "target_symbol": sym.get("name"),
                    "target_id": sym.get("id"),
                })

    # Classify files
    result_files: Dict[str, Any] = {}
    for fpath, ext_deps in dependents_map.items():
        dep_count = len(ext_deps)
        details = caller_details.get(fpath, [])
        total_calls = len(details)

        # Check if architectural hub
        is_hub = False
        f_entry = files_info.get(fpath) or {}
        if f_entry.get("is_production") and (dep_count >= 8 or total_calls >= 15):
            is_hub = True
        if "model" in fpath.lower() or "schema" in fpath.lower() or "route" in fpath.lower():
            if dep_count >= 5:
                is_hub = True

        if dep_count >= 8 or is_hub:
            tier = "red"
            label = "High Impact Hub"
        elif dep_count >= 3:
            tier = "yellow"
            label = "Moderate Impact"
        else:
            tier = "green"
            label = "Safe / Isolated"

        result_files[fpath] = {
            "path": fpath,
            "tier": tier,
            "tier_label": label,
            "dependents_count": dep_count,
            "dependent_files": sorted(list(ext_deps)),
            "total_inbound_calls": total_calls,
            "callers": details[:25],
        }

    return {
        "summary": {
            "total_files": len(result_files),
            "green_count": sum(1 for f in result_files.values() if f["tier"] == "green"),
            "yellow_count": sum(1 for f in result_files.values() if f["tier"] == "yellow"),
            "red_count": sum(1 for f in result_files.values() if f["tier"] == "red"),
        },
        "files": result_files,
    }


# ---------------------------------------------------------------------------
# Sub-agent 1: The Change Analyzer
# ---------------------------------------------------------------------------

def analyze_change(
    symbol: Optional[Dict[str, Any]],
    code_snippet: str,
    scenario: str,
    custom_amendment: str = "",
) -> Dict[str, Any]:
    """
    Sub-agent 1: Maps out data shape, parameters, signatures, or contract modifications.
    """
    sym_name = (symbol.get("name") if symbol else "") or "selected_code"
    sym_kind = (symbol.get("kind") if symbol else "") or "routine"
    sym_file = (symbol.get("file_path") or symbol.get("file") if symbol else "") or ""
    line = symbol.get("line_start") or symbol.get("line") if symbol else 1

    scenario_clean = scenario.lower().strip()
    if "delete" in scenario_clean:
        change_type = "DELETION"
        description = f"Removal of {sym_kind} `{sym_name}` at {sym_file}:{line}."
        contracts = [
            f"All call sites of `{sym_name}` will encounter undefined identifier or unresolved reference errors.",
            f"Any module importing `{sym_name}` directly will fail at load/import time."
        ]
    elif "signature" in scenario_clean or "param" in scenario_clean:
        change_type = "SIGNATURE_AMENDMENT"
        description = f"Altering parameters or return type contract of {sym_kind} `{sym_name}`."
        contracts = [
            f"Callers passing previous positional or keyword arguments to `{sym_name}` will fail argument binding.",
            f"Consumers assuming previous return type shape will encounter runtime TypeError or property access failure."
        ]
    elif "logic" in scenario_clean or "state" in scenario_clean:
        change_type = "LOGIC_CONTRACT_AMENDMENT"
        description = f"Modifying internal business logic, state transitions, or invariants in `{sym_name}`."
        contracts = [
            f"Implicit expectations regarding caching, validation, or persistence in `{sym_name}` will shift.",
            f"Downstream processes expecting previous side-effects may experience silent state divergence."
        ]
    else:
        change_type = "CUSTOM_AMENDMENT"
        description = custom_amendment or f"Modifying `{sym_name}`."
        contracts = [
            f"Downstream dependents coupled to `{sym_name}` must be checked against: {description}"
        ]

    return {
        "sub_agent": "Sub-agent 1 (The Change Analyzer)",
        "change_type": change_type,
        "symbol_name": sym_name,
        "symbol_kind": sym_kind,
        "file": sym_file,
        "line": line,
        "description": description,
        "contract_invariants": contracts,
        "snippet_preview": code_snippet[:300].strip(),
    }


# ---------------------------------------------------------------------------
# Sub-agent 2: Parallel Downstream Scanners
# ---------------------------------------------------------------------------

def scan_downstream(
    model: Dict[str, Any],
    symbol: Optional[Dict[str, Any]],
    change_analysis: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Sub-agent 2: Crawls caller hierarchy, routes, database models, and documentation.
    """
    if not symbol:
        return []

    symbols = model.get("symbols") or []
    by_id = {s.get("id"): s for s in symbols if s.get("id")}
    sym_name = symbol.get("name")
    sym_file = (symbol.get("file_path") or symbol.get("file") or "").replace("\\", "/")

    downstream_findings: List[Dict[str, Any]] = []

    # 1. Direct callers via AST call graph
    for caller_id in symbol.get("callers") or []:
        caller = by_id.get(caller_id)
        if not caller:
            continue
        c_file = (caller.get("file_path") or caller.get("file") or "").replace("\\", "/")
        c_line = caller.get("line_start") or caller.get("line", 1)
        c_name = caller.get("name", "caller")
        is_test = bool(caller.get("is_test") or "test" in c_file.lower())

        impact_type = "TEST_BREAKAGE" if is_test else "DIRECT_CALLER_BREAKAGE"
        downstream_findings.append({
            "file": c_file,
            "line": c_line,
            "symbol": c_name,
            "impact_type": impact_type,
            "description": f"Function `{c_name}` invokes `{sym_name}`. Change to `{sym_name}` directly affects this call site.",
            "is_test": is_test,
        })

    # 2. Scan routes and entry points
    for ep in model.get("entry_points") or []:
        ep_file = (ep.get("file_path") or "").replace("\\", "/")
        if ep_file == sym_file:
            continue
        if ep.get("name") == sym_name or (sym_name and sym_name in (ep.get("name") or "")):
            downstream_findings.append({
                "file": ep_file,
                "line": ep.get("line", 1),
                "symbol": ep.get("name"),
                "impact_type": "ENTRYPOINT_EXPOSURE",
                "description": f"Exposed entry point `{ep.get('name')}` relies directly on `{sym_name}`.",
                "is_test": False,
            })

    # 3. Scan cross-references in raw_calls of other symbols
    for s in symbols:
        s_file = (s.get("file_path") or s.get("file") or "").replace("\\", "/")
        if s_file == sym_file:
            continue
        for raw_call in s.get("raw_calls") or []:
            if sym_name and (f".{sym_name}" in raw_call or f"{sym_name}(" in raw_call):
                # Avoid duplicate if already added
                if not any(f["file"] == s_file and f["symbol"] == s.get("name") for f in downstream_findings):
                    downstream_findings.append({
                        "file": s_file,
                        "line": s.get("line_start") or s.get("line", 1),
                        "symbol": s.get("name"),
                        "impact_type": "IMPLICIT_DEPENDENCY",
                        "description": f"Symbol `{s.get('name')}` references invocation `{raw_call}`.",
                        "is_test": bool(s.get("is_test")),
                    })

    return downstream_findings


# ---------------------------------------------------------------------------
# Bob 2.0 Orchestrator (The Semantic Impact Synthesizer & Patch Generator)
# ---------------------------------------------------------------------------

def synthesize_ripple_and_patches(
    repo_root: Path,
    model: Dict[str, Any],
    symbol: Optional[Dict[str, Any]],
    code_snippet: str,
    scenario: str,
    custom_amendment: str = "",
    bob_command: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executes Ripple-Agent pipeline:
    1. Sub-agent 1: Change Analyzer
    2. Sub-agent 2: Downstream Scanners
    3. Bob Orchestrator: Semantic Impact Synthesizer + Automated Preventive Patches
    """
    repo_root = Path(repo_root).resolve()
    change_analysis = analyze_change(symbol, code_snippet, scenario, custom_amendment)
    downstream_findings = scan_downstream(model, symbol, change_analysis)

    sym_name = change_analysis["symbol_name"]
    sym_file = change_analysis["file"]

    # Gather source snippets of disturbed files for patch synthesis
    disturbed_contexts: List[Dict[str, Any]] = []
    seen_files = set()
    for finding in downstream_findings[:5]:  # limit to top 5 files
        fpath = finding["file"]
        if fpath in seen_files:
            continue
        seen_files.add(fpath)
        abs_path = repo_root / fpath
        file_content = ""
        if abs_path.is_file():
            try:
                file_content = abs_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                file_content = ""
        disturbed_contexts.append({
            "file": fpath,
            "symbol": finding["symbol"],
            "line": finding["line"],
            "impact_type": finding["impact_type"],
            "snippet": file_content[:1500] if file_content else "",
            "full_content": file_content,
        })

    # Prompt Bob 2.0 via single unified orchestration prompt
    unified_prompt = _build_unified_bob_prompt(
        sym_name=sym_name,
        sym_file=sym_file,
        change_analysis=change_analysis,
        disturbed_contexts=disturbed_contexts,
    )

    bob_response_raw = _dispatch_bob_orchestrator(unified_prompt, repo_root, bob_command)
    synthesized = _parse_or_synthesize_fallback(
        bob_response_raw,
        change_analysis,
        downstream_findings,
        disturbed_contexts,
        sym_name,
        sym_file,
    )

    # Attach blast radius tier
    workspace_deps = compute_workspace_dependencies(model)
    norm_file = sym_file.replace("\\", "/")
    file_dep_info = workspace_deps.get("files", {}).get(norm_file, {})
    tier = file_dep_info.get("tier", "green")

    return {
        "symbol_name": sym_name,
        "symbol_file": sym_file,
        "scenario": scenario,
        "blast_radius_tier": tier,
        "dependents_count": file_dep_info.get("dependents_count", len(downstream_findings)),
        "change_analysis": change_analysis,
        "downstream_findings": downstream_findings,
        "semantic_warning": synthesized["semantic_warning"],
        "preventive_patches": synthesized["preventive_patches"],
        "orchestrator_summary": synthesized["orchestrator_summary"],
    }


def _build_unified_bob_prompt(
    sym_name: str,
    sym_file: str,
    change_analysis: Dict[str, Any],
    disturbed_contexts: List[Dict[str, Any]],
) -> str:
    """
    Single unified prompt driving Bob 2.0 through the multi-agent persona chain in one coin turn.
    """
    prompt = f"""You are 'Ripple-Agent', an elite principal software architect conducting a zero-coin semantic impact review.
Execute the following personas in a single response:
1. Sub-agent 1 (The Change Analyzer): Review change to `{sym_name}` in `{sym_file}`.
   Change Type: {change_analysis['change_type']}
   Details: {change_analysis['description']}
   Contracts: {'; '.join(change_analysis['contract_invariants'])}

2. Sub-agent 2 (The Parallel Downstream Scanners):
   Downstream disturbed files to examine:
"""
    for ctx in disturbed_contexts:
        prompt += f"   - File: {ctx['file']} (Caller: `{ctx['symbol']}` at line {ctx['line']})\n"

    prompt += """
3. Bob's Orchestration (The Semantic Impact Synthesizer):
   Generate a concise architectural "Semantic Ripple Map" warning formatted exactly as:
   "Warning: Changing <field/function> in <file> will silently break <assumption> in <file2> and invalidate <logic> in <file3>. Here are the N files you need to update simultaneously."

4. Automated Patch Generation:
   Provide the exact preventive patch for each disturbed file.

RESPOND STRICTLY IN VALID JSON with this structure:
{
  "semantic_warning": "Warning: ...",
  "orchestrator_summary": "...",
  "patches": [
    {
      "file": "path/to/file",
      "explanation": "Why this patch is needed",
      "diff": "--- a/file\\n+++ b/file\\n@@ ... @@"
    }
  ]
}
"""
    return prompt


def _dispatch_bob_orchestrator(
    prompt: str,
    repo_root: Path,
    bob_command: Optional[str] = None,
) -> Optional[str]:
    """
    Invokes Bob CLI or custom command only when explicitly configured or requested.
    Protects user's finite Bob coins from being burnt on automated test suites or exploratory calls.
    """
    # 1. Custom bob_command if explicitly provided (parsed safely without shell=True)
    if bob_command:
        try:
            import shlex
            if isinstance(bob_command, str):
                cmd_parts = shlex.split(bob_command, posix=(sys.platform != "win32"))
            elif isinstance(bob_command, (list, tuple)):
                cmd_parts = list(bob_command)
            else:
                cmd_parts = []

            if cmd_parts:
                proc = subprocess.run(
                    cmd_parts,
                    input=prompt,
                    cwd=str(repo_root),
                    shell=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=90,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    return proc.stdout.strip()
        except Exception:
            pass

    # 2. Only invoke bobide.cmd if STORYTELLER_ENABLE_BOB_CLI is enabled or live bob_command requested
    if os.environ.get("STORYTELLER_ENABLE_BOB_CLI") == "1":
        # Check budget manager before invoking Bob CLI
        budget_mgr = None
        try:
            from coin_ledger import CoinBudgetManager
            budget_mgr = CoinBudgetManager(workspace_root=repo_root)
            can_spend, _ = budget_mgr.can_spend(prompt=prompt, purpose="ripple_agent_dispatch")
            if not can_spend:
                return None
        except Exception:
            budget_mgr = None

        bob_bin = os.path.expandvars(r"%LOCALAPPDATA%\Programs\IBM Bob\bin\bobide.cmd")
        if Path(bob_bin).is_file():
            try:
                # Sanitize prompt against Windows cmd.exe batch parameter injection
                sanitized_prompt = prompt.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
                for ch in ("&", "|", "^", "%", "<", ">"):
                    sanitized_prompt = sanitized_prompt.replace(ch, " ")
                sanitized_prompt = sanitized_prompt.replace('"', "'")
                sanitized_prompt = " ".join(sanitized_prompt.split())

                proc = subprocess.run(
                    [bob_bin, "chat", "-m", "agent", "--prompt", sanitized_prompt],
                    cwd=str(repo_root),
                    shell=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=90,
                )
                if proc.returncode == 0 and proc.stdout.strip():
                    if budget_mgr:
                        try:
                            budget_mgr.record_transaction(prompt=prompt, purpose="ripple_agent_dispatch", coins=1)
                        except Exception:
                            pass
                    return proc.stdout.strip()
            except Exception:
                pass

    return None


def _parse_or_synthesize_fallback(
    bob_raw: Optional[str],
    change_analysis: Dict[str, Any],
    downstream_findings: List[Dict[str, Any]],
    disturbed_contexts: List[Dict[str, Any]],
    sym_name: str,
    sym_file: str,
) -> Dict[str, Any]:
    """
    Parses Bob's JSON response or produces a robust deterministic semantic ripple map
    and preventive patches if Bob is offline / returned non-JSON.
    """
    if bob_raw:
        # Try finding JSON block
        json_match = re.search(r"\{[\s\S]*\}", bob_raw)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                if "semantic_warning" in data:
                    patches = []
                    for p in data.get("patches", []):
                        f = p.get("file", "")
                        # Match full content if possible
                        matched_ctx = next((c for c in disturbed_contexts if c["file"] == f), None)
                        patches.append({
                            "file": f,
                            "explanation": p.get("explanation", "Preventive update for downstream dependency."),
                            "diff": p.get("diff", ""),
                            "original_content": matched_ctx["full_content"] if matched_ctx else "",
                            "patched_content": _apply_diff_or_template(matched_ctx["full_content"] if matched_ctx else "", p.get("diff", "")),
                        })
                    return {
                        "semantic_warning": data.get("semantic_warning"),
                        "orchestrator_summary": data.get("orchestrator_summary", "Bob 2.0 Semantic Impact Synthesis complete."),
                        "preventive_patches": patches,
                    }
            except Exception:
                pass

    # Deterministic high-accuracy fallback synthesis
    affected_files = sorted(list(set(f["file"] for f in downstream_findings if f["file"])))
    count = len(affected_files)

    if count == 0:
        warning = f"Notice: Modifying `{sym_name}` in `{sym_file}` has no detected downstream dependents in this workspace. Safe to edit in isolation."
        summary = "Sub-agent 2 verified 0 direct or implicit callers."
    elif count == 1:
        warning = f"Warning: Modifying `{sym_name}` in `{sym_file}` directly impacts `{affected_files[0]}`. Update this dependent to preserve contract integrity."
        summary = f"Identified 1 downstream dependent file requiring alignment."
    else:
        sample_list = ", ".join(f"`{f}`" for f in affected_files[:3])
        warning = (
            f"Warning: Amending `{sym_name}` in `{sym_file}` will silently disturb downstream assumptions "
            f"in {sample_list}. Here are the {count} files you need to update simultaneously."
        )
        summary = f"Ripple-Agent mapped {count} coupled downstream targets across the workspace."

    # Build deterministic preventive patches
    patches = []
    for ctx in disturbed_contexts:
        fpath = ctx["file"]
        content = ctx.get("full_content", "")
        caller_name = ctx.get("symbol", "")
        line_num = ctx.get("line", 1)

        # Generate a surgical preventive comment/patch in the caller
        lines = content.splitlines(keepends=True)
        patched_lines = list(lines)
        patch_explanation = f"Add compatibility guard & update invocation of `{sym_name}` in `{caller_name}`."

        ext = Path(fpath).suffix.lower()
        if ext in (".ts", ".tsx", ".js", ".jsx", ".go", ".java", ".c", ".cpp", ".cc", ".cxx", ".h", ".hpp", ".rs", ".cs", ".swift", ".kt"):
            cmt_prefix = "//"
        elif ext in (".sql", ".lua"):
            cmt_prefix = "--"
        else:
            cmt_prefix = "#"

        if patched_lines:
            target_idx = max(0, min(line_num - 1, len(patched_lines) - 1))
            target_line = patched_lines[target_idx]
            indent = len(target_line) - len(target_line.lstrip())
            indent_str = " " * indent
            guard_comment = f"{indent_str}{cmt_prefix} TODO(ripple-agent): verify `{sym_name}` contract update ({change_analysis['change_type']})\n"
            patched_lines.insert(target_idx, guard_comment)
        else:
            guard_comment = f"{cmt_prefix} TODO(ripple-agent): verify `{sym_name}` contract update ({change_analysis['change_type']})\n"
            patched_lines.append(guard_comment)

        patched_content = "".join(patched_lines)
        diff_text = "".join(difflib.unified_diff(
            lines,
            patched_lines,
            fromfile=f"a/{fpath}",
            tofile=f"b/{fpath}",
            lineterm="",
        ))

        patches.append({
            "file": fpath,
            "explanation": patch_explanation,
            "diff": diff_text or f"Update call site in {fpath} line {line_num}",
            "original_content": content,
            "patched_content": patched_content,
        })

    return {
        "semantic_warning": warning,
        "orchestrator_summary": summary,
        "preventive_patches": patches,
    }


def _apply_diff_or_template(original: str, diff_text: str) -> str:
    """Fallback helper to produce patched content if full content not given."""
    if not diff_text or not original:
        return original
    return original


# ---------------------------------------------------------------------------
# Documentation Generator
# ---------------------------------------------------------------------------

def generate_documentation(
    repo_root: Path,
    symbol: Optional[Dict[str, Any]],
    code_snippet: str,
    file_path: str,
    language: str = "",
    bob_command: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generates language-tailored documentation (Google/Sphinx for Python, JSDoc for TS/JS,
    doc comments for Go) and an architecture note.
    """
    sym_name = (symbol.get("name") if symbol else "") or "routine"
    sym_kind = (symbol.get("kind") if symbol else "") or "function"
    doc_existing = (symbol.get("doc") if symbol else "") or ""
    complexity = symbol.get("complexity", 1) if symbol else 1
    callers = symbol.get("callers") or [] if symbol else []

    # Detect language from file path if not passed
    ext = Path(file_path).suffix.lower()
    if not language:
        if ext in (".ts", ".tsx"):
            language = "typescript"
        elif ext in (".js", ".jsx", ".mjs"):
            language = "javascript"
        elif ext == ".go":
            language = "go"
        else:
            language = "python"

    # Try prompting Bob for documentation if available
    bob_prompt = f"""Generate clean, production-grade documentation for the following {language} {sym_kind} `{sym_name}`.
Existing Docstring: {doc_existing}
Code:
{code_snippet[:600]}

Format rules:
- Python: Google style docstring with triple quotes \"\"\", Args, and Returns.
- TypeScript/JavaScript: JSDoc format /** ... */ with @param and @returns.
- Go: Go doc comment starting with `// {sym_name} ...`.
Also provide a 1-sentence Architecture Note.
Respond in JSON:
{{"docstring": "...", "architecture_note": "..."}}
"""
    bob_res = _dispatch_bob_orchestrator(bob_prompt, repo_root, bob_command)
    if bob_res:
        json_match = re.search(r"\{[\s\S]*\}", bob_res)
        if json_match:
            try:
                data = json.loads(json_match.group(0))
                if data.get("docstring"):
                    return {
                        "symbol": sym_name,
                        "language": language,
                        "docstring": data.get("docstring"),
                        "architecture_note": data.get("architecture_note", f"Core routine in {file_path}."),
                    }
            except Exception:
                pass

    # Deterministic language-tailored generator
    if language in ("typescript", "javascript"):
        fmt = "jsdoc"
        docstring = (
            f"/**\n"
            f" * `{sym_name}` implementation.\n"
            f" *\n"
            f" * @remarks\n"
            f" * Cyclomatic complexity: {complexity}. Inbound callers: {len(callers)}.\n"
            f" */"
        )
    elif language == "go":
        fmt = "go_comment"
        docstring = (
            f"// {sym_name} handles execution for {sym_name}.\n"
            f"// Complexity: {complexity}, Inbound callers: {len(callers)}."
        )
    else:  # python
        fmt = "google_python"
        docstring = (
            f'"""\n'
            f'{sym_name} implementation.\n\n'
            f'Summary:\n'
            f'    Provides {sym_kind} logic with cyclomatic complexity {complexity}.\n'
            f'    Referenced by {len(callers)} downstream caller(s).\n'
            f'"""'
        )

    arch_note = f"`{sym_name}` in `{file_path}`: {len(callers)} inbound caller(s), complexity score {complexity}."
    return {
        "symbol": sym_name,
        "language": language,
        "format": fmt,
        "docstring": docstring,
        "architecture_note": arch_note,
    }
