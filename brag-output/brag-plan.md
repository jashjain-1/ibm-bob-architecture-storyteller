# Brag Plan: Architecture Storyteller 2.0 & Ripple-Agent

## What is this app?
A VS Code / IBM Bob extension that reverse-engineers any polyglot codebase into an interactive live architecture map — and acts as a senior architect watching your shoulder: the moment you touch a function, Ripple-Agent fires parallel AST crawlers, assigns a blast-radius tier (🟢🟡🔴), and offers 1-click preventive patches before you break anything downstream.

## The angle
Senior architects cost $300/hr. This extension costs nothing. It reads every symbol in your repo, tracks who calls whom across Python, TypeScript, Go, and JavaScript, and when you dare change a core function it tells you exactly what dies — with the patch already written. The joke is that it's not a joke.

## Hook (first 4 seconds)
Big dark IDE background (`#0d1117`). Status bar at bottom pulses: **`🔥 Ripple: High Blast Radius (8 deps)`** — bright amber on near-black. A single headline fades in centered:
> **"What if your IDE knew**
> **what you were about to break?"**
Hold 2.5s then soft cut.

## Key moments (the middle — 10 scenes across ~74s)
1. **Problem Setup** — the pain of silent breakage: changing a function, nothing warns you, CI fails 20 minutes later.
2. **Explorer Badges** — the file tree gets colored: 🔴🟡🟢 badges cascade down the explorer. Every file ranked by blast radius.
3. **The Architecture Map** — Ctrl+Alt+M opens an interactive webview: glowing call-graph nodes, dark panel, live edges.
4. **Hover Intelligence** — hover over any symbol: callers, callees, cyclomatic complexity, and AI insights — instantly, zero lag.
5. **Ripple What-If** — right-click `verify_token` → "What If: Ripple Impact". Side-by-side diff opens. `// TODO(ripple-agent):` markers appear in every downstream file.
6. **Blast Radius Card** — `🔴 HIGH BLAST RADIUS · 8 dependents · 3 modules affected` slams in.
7. **1-Click Patch** — "Apply Preventive Patch" clicked. Files updated. Explorer badges flip 🔴→🟡→🟢.
8. **Dossier** — Ctrl+Alt+D opens the Publication Dossier: L1 Executive, L2 Engineering, L3 Forensic. Export PDF in one command.
9. **Security Hardening** — a scrolling table: CORS bypass, DNS rebinding, DoS, path traversal, RCE — all defended.
10. **Stats block** — `80 tests · 0 errors · 40-coin budget · zero drift` — four cards land one by one.

## Outro / punchline (12 seconds)
Logo lockup: **Architecture Storyteller 2.0** over `#12467b`. Subtitle: `+ Ripple-Agent`. Line: *"Built for VS Code & IBM Bob IDE."* Final beat: **"Your codebase has never been this understood."** Music fades. Hold on dark.

## User flow worth showing
Entry → Right-click symbol → "What If" ripple → Blast-radius tier + affected files → Side-by-side diff with `// TODO(ripple-agent):` → Click "Apply Preventive Patch" → Explorer badges update.

## Tone
- Preset: `polished`
- Creative direction: "senior architect unveils their weapon — no demos, just facts, with quiet authority"
- Interpretation: Slow, confident reveals. No frenetic cuts. Every screen holds long enough to read every claim. Typography is serious. The product earns credibility through restraint, not hype.

## Format: landscape — 1920×1080
## Duration: 90 seconds

## Visual identity (from the project)
- Background: `#0d1117` (GitHub dark / VS Code dark theme)
- Accent: `#12467b` (dossier blue), `#58a6ff` (dark-mode links / graph edges)
- Text primary: `#e6edf3`, muted: `#8b949e`
- Badge green: `#3fb950` · amber: `#d29922` · red: `#f85149`
- Display font: "Segoe UI", system-ui, sans-serif
- Code font: "Cascadia Mono", Consolas, monospace
- Strongest visual: 🟢🟡🔴 badge trinity, dark IDE panels, accent-blue call-graph edges

## Share copy (draft)
We built a VS Code + IBM Bob extension that thinks like a senior architect. Touch any function — it maps blast radius, writes preventive patches, and prints a publication-grade dossier. Architecture Storyteller 2.0 + Ripple-Agent. 🟢🟡🔴

## Audio direction
- Role: warm corporate bed — steady, professional, never urgent
- Music: `happy-beats-business-moves-vol-12-by-ende-dot-app.mp3` (117s track, covers full 90s)
- Music treatment: fade in 0→0.32 over first 2s, hold at 0.32 through body, duck to 0.13 under voiceover, fade to 0 over last 3s. Track is 117s so no loop needed.
- Music cue guidance: bundled preset covers 0–25s. Use `npx hyperframes beats` after music is wired to get full 90s beat grid. Target strong cues near: badge cascade start (~8.7s), blast-radius card (~20–22s), dossier open (~50s), logo land (~82s). Beat-grid for all sequential card/badge reveals.
- Audio-reactive treatment: subtle; RMS/bass modulates accent-blue glow on status bar and graph edges (±3% opacity). No waveforms, no pulsing text.
- SFX posture: sparse–moderate, professional. ~20 SFX events total across 90s. Low HF-risk only.
- Audio-coupled moments: badge arrivals (drop sounds), right-click (click), blast-radius card (impact bell), patch apply (success bell), stat cards (drop sounds per card), final logo (impact bell).
- Restraint rule: no SFX while voiceover is active unless it precisely matches a visible action. Never two SFX within 0.5s under VO.

---

## Storyboard (90 seconds total)

### Scene 1 — Hook — 0–5s (5s)
**Visual:** Full dark IDE background (`#0d1117`). Center bottom: status bar amber pill `🔥 Ripple: High Blast Radius (8 deps)` fades in at 0.5s and pulses once (1.02× scale). At 1.5s, large centered headline fades in:
> **"What if your IDE knew**
> **what you were about to break?"**
Font: Segoe UI, 52px, `#e6edf3`, weight 600. Holds until 5s.

Sequential/interaction: none.
Audio intent: cold open — the question before anyone answers.
VO (0–4.5s): *"Every change you make ripples. Most developers find out too late."*
Audio-coupled: `interface/bong_001.ogg` (vol 0.55) at 1.4s on the status bar pulse. Music fades in 0→0.32 over 0–2s.
Transition: soft crossfade → Scene 2

---

### Scene 2 — Problem: Silent Breakage — 5–14s (9s)
**Visual:** Simulated editor pane: `routes.py` open. A function `def verify_token(token):` visible. Developer "types" a parameter rename: `token` → `tok`. No warnings. Cursor moves away. Status bar shows green `✓`. Then — at 9s — the status bar flips to red: `✗ CI Failed — 4 tests broken`. A shocked-face emoji appears in a small toast notification.

Sub-headline at 11s (fades in, muted text, 18px):
> *"You changed one function. Four tests broke. You found out 20 minutes later."*

Sequential/interaction: yes — typing animation, then status bar flip.
Audio intent: the familiar dread.
VO (5–13s): *"Architecture Storyteller maps your entire codebase — every symbol, every call, every dependency — across Python, TypeScript, Go, and JavaScript."*
Audio-coupled: `keyboard/keypress-007.wav` per keystroke during typing (sparse, not every char); `interface/glitch_002.ogg` (vol 0.55) when CI fails.
Transition: hard cut → Scene 3

---

### Scene 3 — Explorer Badges — 14–22s (8s)
**Visual:** Dark VS Code file explorer panel. File list:
- `engine_server.py`, `ripple_agent.py`, `model_builder.py`, `cache_store.py`, `extension.ts`, `coin_ledger.py`

Badges appear one by one, left of each filename, staggered 0.6s:
- 🔴 `engine_server.py` (High Blast Radius)
- 🔴 `ripple_agent.py`
- 🟡 `model_builder.py` (Moderate)
- 🟡 `cache_store.py`
- 🟢 `extension.ts` (Safe)
- 🟢 `coin_ledger.py`

After all badges: label fades in at right:
> **"Every file. Ranked by blast radius."**
`#e6edf3`, 22px. Holds 2.5s.

Sequential/interaction: yes — 6 badges, staggered.
Audio intent: satisfying, systematic rhythm.
VO (14–21s): *"Every file in your repo is automatically ranked — green for safe, yellow for moderate, red for high blast radius. You always know where the danger is."*
Audio-coupled: `interface/drop_001.ogg` (vol 0.65) per badge. Beat-grid window ~14–18s.
Transition: clean wipe → Scene 4

---

### Scene 4 — Architecture Map (Ctrl+Alt+M) — 22–32s (10s)
**Visual:** Keyboard shortcut hint fades in top-right: `Ctrl+Alt+M`. Then the interactive webview opens: dark panel, radial call-graph. Nodes: `engine_server`, `ripple_agent`, `model_builder`, `cache_store`. Edges animate in as thin `#58a6ff` lines. The tree glows subtly with audio-reactive energy. At 26s, a sidebar shows the symbol tree — collapsible rows of Python/TS/Go functions.

At 28s, a panel label fades in:
> **"Interactive architecture map.**
> **Every symbol. Every call. Zero lag."**
`#e6edf3`, 20px. Holds until cut.

Sequential/interaction: graph edges animate in sequence, then symbol tree expands.
Audio intent: discovery — the whole codebase laid out.
VO (22–31s): *"Hit Ctrl+Alt+M and your entire repository becomes a living map. Call graphs, dependency chains, complexity scores — all driven by the same real-time AST engine."*
Audio-coupled: soft `interface/drop_002.ogg` (vol 0.55) as each graph edge connects.
Transition: soft crossfade → Scene 5

---

### Scene 5 — Hover Intelligence — 32–40s (8s)
**Visual:** Editor pane: `ripple_agent.py` open. Cursor moves over `def analyze_change(symbol, file, code):`. A rich hover card appears:
```
analyze_change
──────────────
Callers: 3 (engine_server.py · cli.py · test_ripple_agent.py)
Callees: scan_downstream, invoke_bob
Cyclomatic complexity: 7
AI insight: "Core orchestration entry-point. High ripple risk."
```
Dark panel, monospace font for code sections, accent-blue for symbol names.

At 36s, a label slides in:
> **"Hover any symbol. Get callers, callees, complexity, and AI insight — instantly."**
18px, `#8b949e`.

Sequential/interaction: yes — cursor move, hover card materialises.
Audio intent: surgical intelligence, quiet authority.
VO (32–39s): *"Hover over any function and Architecture Storyteller tells you who calls it, what it calls, and exactly how complex it is — with an AI-generated architectural insight ready to read."*
Audio-coupled: `interface/click_003.ogg` (vol 0.55) at cursor hover moment.
Transition: soft crossfade → Scene 6

---

### Scene 6 — Ripple What-If — 40–52s (12s)
**Visual:** Editor pane: `ripple_agent.py`, cursor on `verify_token`. Right-click context menu fades in. Cursor moves to:
> **What If: Ripple Impact & Preventive Patches**
Click sound. Then — side-by-side diff:
- Left panel: `ripple_agent.py · before` — function unchanged.
- Right panel: `routes.py · preventive patch` — injected line highlighted:
  ```
  # TODO(ripple-agent): update auth call — verify_token signature changed (line 42)
  ```

At 46s, a list of affected files fades in below the diff:
- `routes.py` · 1 call site
- `test_ripple_agent.py` · 3 assertions
- `engine_server.py` · 2 imports

Label at 49s:
> **"Every downstream file. Every call site. Patches written before you ask."**
`#e6edf3`, 20px.

Sequential/interaction: yes — right-click sim, diff materialises, affected files list appears one by one.
Audio intent: revelation — the machine has already done the thinking.
VO (40–51s): *"Right-click any function and ask 'What If'. Ripple-Agent fires two parallel AST crawlers — one maps the change, one traces every downstream caller. The result: a full impact report with preventive patches already written."*
Audio-coupled: `interface/click_003.ogg` (vol 0.70) at right-click; `interface/drop_001.ogg` per affected file row; `impact/impactSoft_medium_001.ogg` (vol 0.70) when diff panel lands.
Transition: hard cut → Scene 7

---

### Scene 7 — Blast Radius Card — 52–59s (7s)
**Visual:** Clean dark background. Center stage, a large card slams in:

```
🔴  HIGH BLAST RADIUS
────────────────────────────────
8 dependents  ·  3 modules  ·  4 test assertions
```
Card: dark panel `#161b22`, border `#f85149`, red glow. At 54s a sub-row appears:
```
🟡  MODERATE (model_builder.py · cache_store.py)
🟢  SAFE (coin_ledger.py · types.ts)
```
At 56s a label below:
> **"Blast radius assigned. Tier by tier."**

Then at 57.5s the card transforms — an animated swap — to a green card:
```
🟢  PATCH APPLIED — 8 files updated
```
With a soft success glow.

Sequential/interaction: yes — card slam, sub-rows appear, then card flips to green.
Audio intent: tension → resolution.
VO (52–58s): *"The blast radius is calculated automatically. Green, yellow, red — by inbound call count. And the patch? Already in your diff view, one click away."*
Audio-coupled: `impact/impactBell_heavy_000.ogg` (vol 0.65) on card slam; `impact/impactSoft_medium_001.ogg` (vol 0.55) on green card swap.
Transition: soft crossfade → Scene 8

---

### Scene 8 — Dossier (Ctrl+Alt+D) — 59–70s (11s)
**Visual:** Keyboard hint: `Ctrl+Alt+D`. The Publication Dossier HTML opens: dark professional layout, `#12467b` accent. Cover page: **"Architecture Storyteller 2.0 — Executive Dossier"**. Three depth tabs appear: `L1 Executive`, `L2 Engineering`, `L3 Forensic`. At 63s, the L2 Engineering section scrolls — KPI cards visible: `80 tests · Cyclomatic avg: 4.2 · Top hub: engine_server`. At 65s, a terminal-style command fades in bottom-left:
```bash
python cli.py dossier --level 2 --pdf
```
A PDF icon appears with: `architecture-storyteller-2.1.1-dossier.pdf`.

At 67s a label:
> **"Three dossier depths. Print-grade PDF. One command."**
`#e6edf3`, 20px.

Sequential/interaction: yes — tabs animate in, KPI cards slide up, command types out.
Audio intent: corporate gravitas — this is a publication, not a log.
VO (59–69s): *"Need a report? Hit Ctrl+Alt+D. Architecture Storyteller generates a publication-grade dossier — executive summary, engineering deep-dive, or full forensic audit — and exports a PDF via headless Chromium. All in one command."*
Audio-coupled: `interface/drop_002.ogg` per tab; `interface/click_003.ogg` on PDF icon; `keyboard/keypress-007.wav` sparse on command typing.
Transition: soft crossfade → Scene 9

---

### Scene 9 — Security Hardening — 70–78s (8s)
**Visual:** A clean table scrolls in (dark background, `#161b22` rows, `#e6edf3` text):

| Security Vector | Status |
|---|---|
| CORS Origin Bypass | 🟢 Defended |
| DNS Rebinding | 🟢 Defended |
| Denial of Service | 🟢 Defended |
| Path Traversal | 🟢 Defended |
| Remote Code Execution | 🟢 Defended |

Rows appear one by one, each with a green checkmark sound. At 75s a label:
> **"5 attack vectors. All closed. Penetration-audited."**
`#e6edf3`, 22px.

Then at 76.5s the table fades and a large centered stat:
> **`80 tests · 100% passing`**
`#3fb950`, 36px.

Sequential/interaction: yes — 5 rows staggered.
Audio intent: confident lock-down.
VO (70–77s): *"And it's hardened. CORS, DNS rebinding, denial-of-service, path traversal, remote code execution — all audited, all closed. Eighty tests. A hundred percent passing."*
Audio-coupled: `interface/drop_001.ogg` per table row.
Transition: clean wipe → Scene 10

---

### Scene 10 — Stats & Zero Drift — 78–84s (6s)
**Visual:** Four stat cards appear one by one on dark background:
```
80         |  0         |  40-coin   |  zero
tests      |  TS errors |  budget    |  drift
passing    |            |            |
```
Each card: `#161b22` background, `#58a6ff` large number, `#8b949e` label. They pop in sequentially on beat grid.

At 82s a label:
> **"Guaranteed zero drift. Every consumer shares the same AST model."**
`#e6edf3`, 20px, italic.

Sequential/interaction: yes — 4 stat cards on beat grid.
Audio intent: authoritative résumé.
VO (78–83s): *"Zero TypeScript errors. A forty-coin budget cap. And zero drift — because every hover, every map, every dossier reads from the same live AST model."*
Audio-coupled: `interface/drop_002.ogg` (vol 0.65) per stat card; beat-grid lock on 4 beats.
Transition: slow crossfade → Scene 11

---

### Scene 11 — Outro / Logo — 84–90s (6s)
**Visual:** Clean dark background (`#0d1117`). Centered, stacked:
- Kicker (muted, spaced uppercase, 11px): `IBM BOB · VS CODE EXTENSION`
- Rule (3px `#12467b`, 48px wide, centered)
- Title: **Architecture Storyteller 2.0** (`#e6edf3`, 40px, weight 650)
- Subtitle: `+ Ripple-Agent` (`#58a6ff`, 22px)
- Pause, then at 87s: *"Your codebase has never been this understood."* (`#8b949e`, 14px, italic)

Music fades 0.32→0 from 87s→90s.

Sequential/interaction: stacked fade-in, elements arrive sequentially.
Audio intent: authoritative landing.
VO (84–89.5s): *"Architecture Storyteller 2.0 and Ripple-Agent. For VS Code and IBM Bob IDE. Your codebase has never been this understood."*
Audio-coupled: `impact/impactBell_heavy_000.ogg` (vol 0.60) when title fully lands (~85.5s). Music fade begins 87s.
Transition: — (end)

---

**Duration check:**
Scene 1: 5s + Scene 2: 9s + Scene 3: 8s + Scene 4: 10s + Scene 5: 8s + Scene 6: 12s + Scene 7: 7s + Scene 8: 11s + Scene 9: 8s + Scene 10: 6s + Scene 11: 6s = **90 seconds** ✓

**Music mood:** warm corporate — steady, clean, never urgent
**Audio summary:** Vol-12 bed (117s track, no loop) fades in at 0s, holds 0.32 through body, ducks to 0.13 under VO throughout, returns to 0.32 between VO gaps, fades out 87–90s. Sparse professional SFX accent action moments (~20 events total). VO on af_heart voice, track-index 3, vol 1.0.

---

## Voiceover script (per scene)

| Scene | Time | Line |
|---|---|---|
| 1 | 0–4.5s | "Every change you make ripples. Most developers find out too late." |
| 2 | 5–13s | "Architecture Storyteller maps your entire codebase — every symbol, every call, every dependency — across Python, TypeScript, Go, and JavaScript." |
| 3 | 14–21s | "Every file in your repo is automatically ranked — green for safe, yellow for moderate, red for high blast radius. You always know where the danger is." |
| 4 | 22–31s | "Hit Ctrl+Alt+M and your entire repository becomes a living map. Call graphs, dependency chains, complexity scores — all driven by the same real-time AST engine." |
| 5 | 32–39s | "Hover over any function and Architecture Storyteller tells you who calls it, what it calls, and exactly how complex it is — with an AI-generated architectural insight ready to read." |
| 6 | 40–51s | "Right-click any function and ask 'What If'. Ripple-Agent fires two parallel AST crawlers — one maps the change, one traces every downstream caller. The result: a full impact report with preventive patches already written." |
| 7 | 52–58s | "The blast radius is calculated automatically. Green, yellow, red — by inbound call count. And the patch? Already in your diff view, one click away." |
| 8 | 59–69s | "Need a report? Hit Ctrl+Alt+D. Architecture Storyteller generates a publication-grade dossier — executive summary, engineering deep-dive, or full forensic audit — and exports a PDF via headless Chromium. All in one command." |
| 9 | 70–77s | "And it's hardened. CORS, DNS rebinding, denial-of-service, path traversal, remote code execution — all audited, all closed. Eighty tests. A hundred percent passing." |
| 10 | 78–83s | "Zero TypeScript errors. A forty-coin budget cap. And zero drift — because every hover, every map, every dossier reads from the same live AST model." |
| 11 | 84–89.5s | "Architecture Storyteller 2.0 and Ripple-Agent. For VS Code and IBM Bob IDE. Your codebase has never been this understood." |

---

## Music cue guidance
- Track: `happy-beats-business-moves-vol-12-by-ende-dot-app.mp3` (117.36s — no loop needed for 90s)
- Tempo: ~110 BPM, beat interval ~0.545s
- Bundled preset covers 0–25s: strong cues at 8.74s, 13.11s, 17.47s, 22.93s, 24.56s
- Full 90s beat grid: run `npx hyperframes beats brag-output/composition` after music is wired
- Strong cue locks (use these for major visual moments):
  - ~8.74s → first explorer badge (Scene 3)
  - ~17.47s → architecture map graph reveal (Scene 4)
  - ~22.93s → diff panel land (Scene 6 entry)
  - Full-track beats: derive from hyperframes beats output
- Beat-grid windows: badge cascade (Sc3), stat cards (Sc10), security table rows (Sc9)
- Restraint: duck music under VO throughout; cue locks are secondary to VO pacing
