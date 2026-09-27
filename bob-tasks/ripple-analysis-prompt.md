# Ripple-Agent Change Analysis & Impact Synthesis Task

Run this prompt in **IBM Bob IDE** under **Agent Mode**:

```markdown
Analyze the proposed code change for `TripService` in `booking_system/services/trip.py`.
1. Dispatch Sub-agent 1 (Change Analyzer) to determine if this change affects parameter types or method signatures.
2. Dispatch Sub-agent 2 (Parallel Downstream Scanners) to crawl workspace callers across `booking_system/routes.py` and `billing/processor.go`.
3. Check caller dependency tiers:
   - Green (0-2 dependents)
   - Yellow (3-7 dependents)
   - Red (8+ dependents)
4. Synthesize contract breach warnings and generate surgical preventive patches with language-tailored TODO tags.
5. Record 1 Bob coin expenditure in `.agents/coin_budget_ledger.json`.
```
