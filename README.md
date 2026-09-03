# Kitesurfing Vacation Planner

A multi-agent AI crew (1 Manager + 6 specialists) that plans a kitesurfing
vacation: it generates 3 fully-costed candidate destinations, lets you
compare and pick one, then refine it — all through a Streamlit web page.

See `Kitesurf_Vacation_Planner_Design_Document_v3.docx` for the full design
(use cases, architecture, scoring rubric).

## 1. Install uv (one-time)

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**Mac/Linux:**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

## 2. Get your API keys

- **Anthropic** (Claude): https://console.anthropic.com -> Settings -> API Keys -> Create Key
- **Serper** (web + image search): https://serper.dev -> sign up -> API key is on your dashboard (free tier, no card needed)

## 3. Configure

Copy `.env.example` to `.env` and fill in your keys:

```
ANTHROPIC_API_KEY=sk-ant-api...
SERPER_API_KEY=...
CREW_MODEL=anthropic/claude-sonnet-5
```

## 4. Install dependencies

From inside the `kitesurf-vacation-crew` folder:

```bash
uv sync
```

This creates a virtual environment and installs everything automatically -
no manual venv activation needed.

## 5. Run the app

```bash
uv run streamlit run app.py
```

This opens the app in your browser (usually http://localhost:8501).

## How it works

1. **New Plan tab** - fill out the trip form (skill level, surf type, dates,
   budget, region, departure city, accommodation type, night life style).
   Clicking "Generate" runs the full agent pipeline **three times** (once
   per candidate destination), so this can take a few minutes - that's
   expected, not a bug (see design doc UC1 note).
2. You'll see **3 fully-costed candidate plans** side by side, each scored
   out of 22 points. Expand "See how each agent contributed" to see the
   raw output from each specialist agent - useful for demonstrating the
   orchestration.
3. Click **"Choose this destination"** on one, then optionally tweak the
   accommodation type and **regenerate** just that destination.
4. **Download the PDF** with all 3 candidates + the full chosen itinerary.
5. The **History tab** lists every trip you've generated. Mark a trip
   "Completed" once you've actually taken it to unlock the review form
   (7 category ratings, would-you-come-back, free text).

## Project files

| File | Purpose |
|---|---|
| `crew.py` | Agents (Manager + 6 specialists), scoring rubric, orchestration |
| `tools.py` | Custom tools: 5-year wind history (Open-Meteo), image search (Serper) |
| `models.py` | Pydantic data models for structured agent output |
| `db.py` | SQLite persistence for trip history and reviews |
| `pdf_export.py` | Builds the downloadable vacation plan PDF |
| `airports.py` | Departure city dropdown (IATA codes) |
| `app.py` | Streamlit web app (New Plan + History tabs) |

## Troubleshooting

- **"Missing/placeholder API key" warning on the page** - check your `.env`
  file has real keys, not the placeholder text.
- **401/authentication errors** - your Anthropic or Serper key is invalid;
  regenerate it from the respective dashboard.
- **Generation takes several minutes** - expected. The pipeline runs the
  full costing sub-crew 3 times (once per candidate).
