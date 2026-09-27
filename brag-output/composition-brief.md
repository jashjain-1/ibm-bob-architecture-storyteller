# Hyperframes Composition Brief: Architecture Storyteller 2.0 & Ripple-Agent

## Objective
Create a 20-second polished launch video for Architecture Storyteller 2.0 — a VS Code / IBM Bob extension that maps polyglot codebases and fires Ripple-Agent blast-radius analysis with 1-click preventive patches.

## Output
- Composition directory: `brag-output/composition/`
- Rendered video: `brag-output/brag.mp4`
- Format: landscape — 1920×1080
- Duration: 20 seconds

## Source Material
- Project root: `c:/Users/Harsh/Desktop/ibm-bob-polyglot-navigator`
- Primary files read: `README.md`, `vscode-extension/package.json`, `vscode-extension/media/map.css`, `output/dossier-L1-galaxium.html`
- Product name: Architecture Storyteller 2.0 + Ripple-Agent
- Tagline / strongest claim: "Guaranteed zero drift — every consumer shares the same AST model. Blast radius assigned. Preventive patch ready. One click."
- Key UI or visual moment to recreate: The 🟢/🟡/🔴 badge system on VS Code file explorer + the side-by-side diff with `// TODO(ripple-agent):` markers
- Copy that must appear verbatim:
  - `🔥 Ripple: High Blast Radius (8 deps)`
  - `// TODO(ripple-agent): update auth call — verify_token signature changed (line 42)`
  - `Architecture Storyteller 2.0`
  - `"Your codebase has never been this understood."`

## Creative Direction
- Tone preset: `polished`
- Creative direction: "senior architect unveils their weapon — no demos, just facts"
- Interpretation: Slow, confident reveals. Each screen holds long enough to read every claim. Typography is serious. The product earns credibility through restraint, not hype. No rapid cuts. No flashy transitions. Every element arrives with purpose and stays.
- Angle: Senior architects cost $300/hr. This extension watches every function for free — tracking who calls whom across Python, TypeScript, Go, and JavaScript, assigning blast-radius tiers, and delivering preventive patches before you break anything downstream.
- Hook: Full dark IDE background. Status bar amber pill pulses: `🔥 Ripple: High Blast Radius (8 deps)`. One line fades in: "What if your IDE knew what you were about to break?"
- Outro / punchline: Logo lockup — Architecture Storyteller 2.0 — with final line: "Your codebase has never been this understood."
- Avoid:
  - Generic SaaS language ("streamline your workflow", "10x your productivity")
  - Abstract filler visuals or color washes
  - Unrelated visual redesign — keep the dark IDE aesthetic throughout

## Visual Identity
- Background: `#0d1117` (GitHub dark, matches the extension's dark theme)
- Text primary: `#e6edf3`
- Text muted: `#8b949e`
- Accent blue: `#12467b` (dossier), `#58a6ff` (links/graph edges)
- Badge green: `#3fb950` · Badge amber: `#d29922` · Badge red: `#f85149`
- Display font: "Segoe UI", system-ui, sans-serif
- Code font: "Cascadia Mono", Consolas, monospace
- Visual references from the project: the VS Code dark panel aesthetic; colored explorer badges (🟢🟡🔴); accent-blue call-graph edges; amber status bar indicator; side-by-side diff panels

## Storyboard
Use the full storyboard in `brag-output/brag-plan.md` as the creative contract.

Scene summary:
1. **Hook** — 3s — Status bar amber pulse; headline "What if your IDE knew what you were about to break?"
2. **Explorer Badges** — 4s — 6 file badges (🔴🔴🟡🟡🟢🟢) appearing one by one with staggered pop; label "Every file. Ranked by blast radius."
3. **What If / Ripple** — 5s — Simulated right-click → "What If" → side-by-side diff → `🔴 HIGH BLAST RADIUS · 8 dependents` card slams in; "1-click preventive patch ready ↓"
4. **Architecture Map** — 4s — Interactive webview with call-graph node glow; 4 stat blocks appear sequentially: `80 tests · 0 errors · 40-coin budget · zero drift`
5. **Outro / Logo** — 4s — Clean dark lockup: Architecture Storyteller 2.0 + tagline

## Audio
- Audio role: warm corporate bed — steady, professional, never urgent
- Audio arc: fade in at Scene 1 → hold 0.32 through Scenes 2–4 → fade to 0 over last 1.5s of Scene 5; SFX accent key moments only
- Music: `assets/music/happy-beats-business-moves-vol-12-by-ende-dot-app.mp3`
- Music treatment: start at 0s (composition start), volume 0.32, fade to 0 beginning at 18.5s (ending by 20.0s)
- Music cue guidance: bundled preset at `assets/music/cues/happy-beats-business-moves-vol-12-by-ende-dot-app.music-cues.json`. Strong cue locks: 8.74s → first explorer badge; 13.11s → blast-radius card; 17.47s → logo title land. Beat-grid windows: badges 8.74–11.46s (6 consecutive beats), stats 14.73–16.38s (4 beats).
- Audio-reactive treatment: subtle; use music RMS/bass energy to make the accent-blue `#12467b`/`#58a6ff` glow on the status bar and call-graph edges breathe very slightly (scale ±2%, opacity ±5%). No waveform/equalizer visuals. No text scaling.
- Audio-coupled moments:
  - Scene 1 status bar pulse → `interface/bong_001.ogg` at 1.1s
  - Scene 2 each badge arrival → `interface/drop_001.ogg` (or `drop_002.ogg` for first/last) per badge
  - Scene 3 simulated right-click → `interface/click_003.ogg`
  - Scene 3 blast-radius card slam → `impact/impactSoft_medium_001.ogg` at ~13.11s
  - Scene 4 each stat block → `interface/drop_001.ogg` per stat
  - Scene 5 logo title land → `impact/impactBell_heavy_000.ogg` at ~17.47s
- SFX selection guidance: all SFX must be low high-frequency risk (see `sfx-analysis.md`). Polished restraint — never two SFX within 0.3s.
- SFX analysis guidance: `c:/Users/Harsh/.bob/skills/brag/assets/sfx/sfx-analysis.md`
- Exact SFX choice: Hyperframes chooses exact filenames, timestamps, density, and volume based on the implemented animation.
- Audio files: copy the chosen music and SFX into `brag-output/composition/assets/`

## Voiceover
Voice is enabled (`--voice`). Use Kokoro via Hyperframes (`npx hyperframes tts`).

Generate voiceover audio with:
```bash
npx hyperframes tts "assets/voiceover-script.txt" --voice af_heart --output assets/voiceover.wav
```

Wire into the composition on its own track (track-index 3), volume 1.0. Duck music to 0.13 for the duration of the voiceover, then return to 0.32.

Voiceover script (also written to `assets/voiceover-script.txt`):

> Scene 1 (0–3s): "Every change you make ripples. Most developers find out too late."

> Scene 2 (3–7s): "Architecture Storyteller maps your entire codebase — every file ranked by blast radius."

> Scene 3 (7–12s): "Touch a function. Ripple-Agent fires. You see exactly what breaks — and the patch is already written."

> Scene 4 (12–16s): "Eighty tests passing. Zero TypeScript errors. Zero drift — ever."

> Scene 5 (16–20s): "Architecture Storyteller 2.0. Your codebase has never been this understood."

Scene durations must flex to match the generated WAV duration. Adjust `data-duration` values after generation.

## Hyperframes Instructions
Load `hyperframes-core`, `hyperframes-animation`, `hyperframes-creative`, `hyperframes-keyframes`, and `hyperframes-cli`. /brag is its own workflow — do not enter the hyperframes entry-point intent interview.

Requirements:
- Show at least one real UI, copy, or visual element from the source project (the `// TODO(ripple-agent):` comment and the status-bar line must appear verbatim).
- Keep all text readable in the final render (WCAG contrast on dark background).
- Keep the video within 20 seconds.
- Include music, SFX, and voiceover as specified.
- Treat /brag audio notes as guidance, not a fixed cue sheet — choose SFX after the visual animation exists.
- Treat music cue metadata as optional timing hints; readability and scene pacing are primary.
- Use local relative asset paths throughout — no absolute paths.
- Run `hyperframes check` before render.
