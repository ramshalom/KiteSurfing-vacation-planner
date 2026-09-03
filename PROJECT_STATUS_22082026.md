# Kitesurfing Vacation Planner — Project Status (2026-08-22)

**Status: All use cases confirmed working by Rami as of this date.** This document is a handoff snapshot so a new chat can pick up the project without re-deriving context. Project files live in `kitesurf-vacation-crew/` inside the "Graduate AI Project" folder.

## What this is

A graduate AI course final project: a multi-agent system (CrewAI + uv + Streamlit) that plans a kitesurfing vacation. A set of specialist agents research and cost 3 candidate destinations in parallel, the user compares and picks one, then can tweak and regenerate it, and finally export a PDF and track the trip in a history log.

Stack: CrewAI, uv (Python env/dependency management), Streamlit (UI), Anthropic Claude Sonnet 5 (`anthropic/claude-sonnet-5`) as the LLM for every agent, Serper.dev (web + image search), Open-Meteo (free historical weather, no key), SQLite (trip history), ReportLab (PDF export).

## Architecture

### Phase 1 — `generate_candidates(inputs)` in `crew.py`
1. **Destination Scout** (agent, tools: web search + image search) finds EXACTLY 3 candidate destinations matching the traveler's profile (skill level, surf type, dates, budget, region(s), departure city, night life preference(s)). No scoring or wind data yet.
2. Python calls `fetch_wind_data()` **directly** (not via LLM tool-call transcription) for each candidate — pulls 5 years of real hourly wind data from Open-Meteo and computes both a per-year summary and an hourly heatmap (09:00–18:00, "avg sustained" + "avg gust" per hour). This is deterministic and never touches the LLM, so it can't be garbled by transcription.
3. **Weather Analyst** (agent) scores each candidate against the 22-point rubric below, using the real wind data as given ground truth text (not re-derived).
4. Python re-sums each candidate's score total from its 7 sub-scores — the header number can never disagree with the displayed breakdown.

**Scoring rubric (max 22, locked by Rami, all criteria scored not hard-filtered):**
- Wind reliability — 5 pts
- Travel accessibility — 4 pts
- Budget feasibility (flights + hotel only) — 4 pts
- Night life style match — 3 pts
- Skill level match — 2 pts
- Surf type match — 2 pts
- Region match — 2 pts (only scored if specific region(s) picked, not "Anywhere")

### Phase 2 — `cost_candidate(destination_name, inputs, overrides=None)` in `crew.py`
Runs once per candidate: **Accommodation Finder**, **Travel Agent**, **Car Rental Agent** (optional — see below), then **Budget & Itinerary Planner** (day-by-day itinerary spanning outbound travel day → stay → return travel day). Runs as `Process.sequential` (not hierarchical — removes redundant Manager delegation LLM calls since each task already names its agent explicitly).

The 3 candidates' `cost_candidate()` calls run **in parallel** via `ThreadPoolExecutor` (`generate_full_plans()`), each with its **own fresh set of agent instances** (`_build_cost_agents()`) — CrewAI's agent executor isn't safe to share across threads.

Each research task (accommodation/travel/car) has its **own** `output_pydantic` (`AccommodationOptionList`, `FlightOptionList`, `CarRentalOptionList`), and Python overrides the final plan's option lists from these directly rather than trusting the Budget Planner's re-transcription of them — this was the fix for a `$0` flight/car cost bug.

Python then computes all costs deterministically from the structured option data: standard/flex flight price, accommodation price (cheapest option × nights), car rental price (0 if opted out), food estimate (flat per-day), and all totals. **Kitesurfing lessons and gear rental are intentionally excluded** from every total. Flight pricing includes kitesurfing gear as sports/oversized baggage, and both a standard and flex/changeable fare are shown side by side.

### Refine — `refine_plan(destination_name, inputs, overrides)`
Re-runs `cost_candidate()` for just the chosen destination with overrides:
- `accommodation_types` — change room type(s)
- `start_date` / `end_date` — change travel dates
- `rent_car` — opt out of a rental car entirely (skips the Car Rental Agent/task, forces car cost to 0, itinerary won't mention a car)

## UI flow (`app.py`)

**New Plan tab:** form → compare (3 fully-costed candidates, side-by-side score summary + stacked full detail sections) → refine (chosen destination, tweak panel + full plan). The full-plan display order (both on the refine page and in the PDF) is: **Budget → 5-year wind history → flights → accommodation → car rental → day-by-day itinerary**, with "other candidates considered" moved to the end.

**History tab:** SQLite-backed trip log, manual "Mark as taken" button, review form (1–5 stars across Spot/Wind/Beach Services/Food/Cost/Hotel/Atmosphere + would-come-back yes/no + free text).

**Timers:** each agent task's duration is measured via CrewAI task-completion callbacks (`crew.py`) and surfaced in the UI: total time to generate all 3 offers, per-candidate cost time, per-agent time in the "See how each agent contributed" trace, and a single "last regeneration took Xs" caption on the refine/tweak panel.

**PDF export (`pdf_export.py`):** same section order as above; the 5-year wind heatmap is redrawn as a native color-coded ReportLab table (not a screenshot) using the same thresholds as the web UI; long text fields wrap inside table cells (fixed sizing to page width) instead of overflowing.

## Recurring design pattern (important for future work)

LLM structured output (`output_pydantic`) is **unreliable for anything requiring numeric or referential consistency** — it silently drops fields, zeroes prices, or fails to echo back known values. The fix pattern used everywhere in this codebase:
1. Every Pydantic field has a safe default (never strictly required) so partial output never crashes the pipeline.
2. Anything requiring arithmetic or consistency (wind stats, score totals, cost totals, the destination name itself) is computed/set deterministically in Python from already-structured sub-data, never trusted from the LLM's own arithmetic or transcription.
3. Each research task gets its own narrow `output_pydantic` rather than asking a later task to "carry over" earlier results into its own JSON.

## Bug history (fixed, for reference)

- Missing/incorrectly-required Pydantic fields → `ConverterError` crashes (fixed: safe defaults everywhere, including `FullPlan.destination`).
- Scores of 0/22 or mismatched header vs. breakdown → Python always re-sums from sub-scores.
- Only 2 of 3 candidates returned → task description now says "EXACTLY 3".
- Missing hotel images/links → added `image_tool` to Accommodation Finder, required official hotel website (not aggregator) with retry instruction, required ≥2 options with retry instruction.
- `$` and `~` in agent text breaking Streamlit's markdown (LaTeX math / strikethrough) → escaped in `safe_text()`.
- Wind data missing for obscure spot names (e.g. "Boracay (Bulabog Beach)", "Pak Nam Pran") → `_geocode()` fallback chain (full string → strip parens → comma segments) **and** passing `"name, country"` instead of just the name to geocoding.
- A single bad year's request wiping out all 5 years of wind data for a candidate → each year now fetched in its own try/except (skip, don't abort).
- Empty itinerary from the LLM → deterministic Python fallback itinerary (outbound/stay/return) if the agent's list comes back empty.
- Raw JSON dumped in the agent-trace panel (hierarchical mode artifact) → replaced with a short note; later, trace text for Accommodation/Travel/Car reformatted from their own structured output for consistent styling across candidates.
- `RuntimeError: Executor is already running` when the 3 candidates ran in parallel threads sharing the same Agent objects → each `cost_candidate()` call now builds its own fresh agents.
- PDF tables overflowing the page width → explicit `colWidths` + `Paragraph`-wrapped cells.
- Slow runtime → `Process.sequential` (not hierarchical) + `ThreadPoolExecutor` parallelizing the 3 candidates' costing. Got this down to under 6 minutes for all 3 fully-costed candidates in Rami's testing.

## Explicitly deferred (not started)

1. **Web page / landing page design** — theme, hero section, branding, imagery. Rami's stated sequencing: functionality first (now done), design second. **This is the next phase.**
2. **Presentation materials** for the university presentation day — a PPTX deck with architecture diagram + real screenshots.
3. **Design doc v4** — `Kitesurf_Vacation_Planner_Design_Document.docx` v1/v2/v3 exist in the Graduate AI Project folder but haven't been updated to reflect the final implementation; not yet requested but may be worth doing before the presentation.
4. **Public deployment** — discussed but not started. Recommended path: Streamlit Community Cloud (free, public `*.streamlit.app` URL, deploys from GitHub). Caveats flagged to Rami: API costs are billed to his own Anthropic/Serper keys regardless of who uses the public link (worth a spending cap + considering a simple access-code gate before going fully public), the free tier sleeps after 12h idle and caps ~1GB memory, and SQLite trip history / saved PDFs are **not persistent** on that platform's ephemeral filesystem — would need a real fix (e.g. external DB/storage) before relying on history for real shared use, not just a demo.

## File map

- `crew.py` — agents, tasks, phase orchestration, timing, deterministic cost/data overrides.
- `models.py` — Pydantic models (all fields defaulted; list-wrapper models for reliable per-task structured output).
- `tools.py` — `fetch_wind_data()` (Open-Meteo), `_geocode()` fallback chain, `WindHistoryTool`, `ImageSearchTool`.
- `app.py` — Streamlit UI (New Plan + History tabs), `safe_text()`, wind heatmap HTML renderer, activity summary builder.
- `pdf_export.py` — ReportLab PDF export, colored wind heatmap table, itemized budget table.
- `db.py` — SQLite CRUD for trip history/reviews.
- `airports.py` — IATA airport list for the departure city dropdown.
- `README.md` — setup/run instructions (`uv sync`, `uv run streamlit run app.py`).

## How to resume in a new chat

Point Claude at this file (`PROJECT_STATUS_22082026.md` in the project folder) and state the goal for the next phase (e.g. "let's design the landing page now"). No need to re-explain the requirements history above — it's all captured here.
