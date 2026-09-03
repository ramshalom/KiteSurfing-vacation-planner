"""
crew.py

The kitesurfing vacation planning crew: one Manager agent orchestrating six
specialist agents, in two phases:

  Phase 1 - generate_candidates(inputs)
      1. Destination Scout finds EXACTLY 3 candidate destinations (name,
         country, rationale, photos) - no scoring yet.
      2. Python calls fetch_wind_data() DIRECTLY (not via LLM transcription)
         for each candidate and attaches the real 5-year data. This is
         deliberate: letting an LLM transcribe tool output into structured
         JSON was producing numbers that didn't match the tool's real data.
      3. Weather Analyst scores each candidate against the rubric, given the
         real wind data as ground truth text (it doesn't need to re-fetch or
         transcribe it, just reason over it).
      4. Python re-sums each score's total from its 7 sub-scores, overriding
         whatever total the LLM stated - guarantees the number shown always
         matches the displayed breakdown.

  Phase 2 - cost_candidate(destination_name, inputs)
      Manager delegates to Accommodation Finder, Travel Agent, and Car Rental
      Agent, then Budget & Itinerary Planner drafts a day-by-day plan.
      Python then computes the actual totals from the structured option
      prices (flights + hotel, and full trip incl. car + food) rather than
      trusting the LLM's arithmetic - guarantees the summary always matches
      the line items, and keeps gear/lesson costs OUT of the total as
      requested.

  Refine - refine_plan(destination_name, inputs, overrides)
      Re-runs phase 2 for a single destination with updated parameters.
"""

import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date as date_cls

from crewai import Agent, Task, Crew, Process, LLM
from crewai_tools import SerperDevTool
from crewai.utilities.converter import ConverterError

from tools import fetch_wind_data, ImageSearchTool, WindHistoryTool
from models import (
    CandidateList, CandidateScoreList, ScoreBreakdown, YearlyWind, FullPlan,
    AccommodationOptionList, FlightOptionList, CarRentalOptionList, DayPlan,
)

# ---------------------------------------------------------------------------
# LLM + shared tools
# ---------------------------------------------------------------------------

llm = LLM(model=os.getenv("CREW_MODEL", "anthropic/claude-sonnet-5"))

search_tool = SerperDevTool()
image_tool = ImageSearchTool()
wind_tool = WindHistoryTool()

FOOD_ESTIMATE_PER_DAY = 30  # flat estimate, used only in the deterministic total (not shown as a line item)

SCORING_RUBRIC = """
Score every candidate destination against this rubric (max 22 points):
- Wind reliability: 0-5 points, based on the real 5-year wind data provided to you
- Travel accessibility: 0-4 points, based on flight time/connections from the departure city
- Budget feasibility: 0-4 points, based on whether FLIGHTS + HOTEL ONLY (not car rental, not food)
  realistically fit the traveler's stated budget - the budget figure covers flights and hotel only
- Night life style match: 0-3 points, based on how well the destination matches the traveler's
  requested night life style(s)
- Skill level match: 0-2 points, based on whether the spot suits the traveler's skill level
- Surf type match: 0-2 points, based on whether the spot supports the requested surf type
  (Freestyle / Waves / Freestyle & Waves)
- Region match: 0-2 points, only scored if the traveler picked specific region(s) (not "Anywhere")
Report each sub-score plus the total for every candidate.
"""


def _month_day(iso_date: str) -> str:
    """'2026-10-14' -> '10-14'"""
    return iso_date[5:]


def _nights(start_date: str, end_date: str) -> int:
    d1 = date_cls.fromisoformat(start_date)
    d2 = date_cls.fromisoformat(end_date)
    return max((d2 - d1).days, 1)


# ---------------------------------------------------------------------------
# Deterministic trace formatting for the "See how each agent contributed"
# panel. The agent's own free-form prose answer varies in style from run to
# run (bullet list one time, a paragraph the next), which looked
# inconsistent across candidates. Since we already have each task's OWN
# reliable structured output (see the override block in cost_candidate),
# render THAT instead of the raw prose - same clean format every time.
# ---------------------------------------------------------------------------

def _fmt_accommodation_options(options) -> str:
    if not options:
        return "No accommodation options found."
    lines = []
    for o in options:
        bits = [f"{o.price_per_night} {o.currency}/night", o.distance_to_spot]
        if o.rating:
            bits.append(f"rating {o.rating}")
        if o.source_url:
            bits.append(f"website: {o.source_url}")
        lines.append(f"- {o.name} ({o.type}): " + " — ".join(b for b in bits if b))
    return "\n".join(lines)


def _fmt_flight_options(options) -> str:
    if not options:
        return "No flight options found."
    lines = []
    for o in options:
        notes = f" — {o.notes}" if o.notes else ""
        lines.append(f"- {o.fare_type.title()} fare: {o.price} {o.currency} ({o.airline}){notes}")
    return "\n".join(lines)


def _fmt_car_options(options) -> str:
    if not options:
        return "No car rental options found."
    return "\n".join(f"- {o.company} ({o.car_type}): {o.price_per_day} {o.currency}/day" for o in options)


def _default_itinerary(destination_name: str, departure_city: str, start_date: str, end_date: str) -> list:
    """
    Deterministic fallback itinerary (day 1 = outbound, last day = return,
    middle days = stay), used only if the Budget Planner's own itinerary
    comes back empty - same "never leave the user with a blank section"
    principle as the other Pydantic-default fixes. A generic fallback is
    better than nothing, even though it's less specific than what the agent
    would normally write.
    """
    total_days = max((date_cls.fromisoformat(end_date) - date_cls.fromisoformat(start_date)).days + 1, 2)
    days = [DayPlan(day=1, description=f"Outbound travel day: depart {departure_city} for {destination_name}.")]
    for d in range(2, total_days):
        days.append(DayPlan(day=d, description=f"Day at {destination_name}: kitesurfing, exploring, and relaxing."))
    days.append(DayPlan(
        day=total_days,
        description=f"Return travel day: depart {destination_name} back to {departure_city}.",
    ))
    return days


# ---------------------------------------------------------------------------
# Agents
# ---------------------------------------------------------------------------

manager = Agent(
    role="Kitesurfing Vacation Manager",
    goal="Orchestrate the specialist team to deliver accurate, well-scored, fully-costed kitesurfing vacation options.",
    backstory=(
        "A veteran travel operations manager who has planned kitesurfing trips worldwide. "
        "Skilled at delegating to the right specialist and combining their output into one "
        "clean, non-redundant result."
    ),
    allow_delegation=True,
    llm=llm,
    verbose=True,
)

destination_scout = Agent(
    role="Kitesurfing Destination Scout",
    goal="Find candidate kitesurfing destinations matching the traveler's profile.",
    backstory=(
        "You've kitesurfed at over 50 spots worldwide and know which destinations suit which "
        "skill levels, surf styles, and travel preferences."
    ),
    tools=[search_tool, image_tool],
    llm=llm,
    verbose=True,
)

weather_analyst = Agent(
    role="Wind & Weather Analyst",
    goal="Score each candidate destination against the rubric, using real 5-year wind data as ground truth.",
    backstory=(
        "A meteorologist specialized in coastal wind patterns relevant to kitesurfing. You are "
        "given real historical wind statistics and your job is to reason over them (and the rest "
        "of the traveler's profile) to produce a rigorous, consistent score - not to re-derive or "
        "restate the wind numbers yourself."
    ),
    tools=[wind_tool, search_tool],
    llm=llm,
    verbose=True,
)

# NOTE: accommodation_finder / travel_agent / car_rental_agent / budget_planner
# are intentionally NOT created as module-level singletons like the agents
# above. cost_candidate() runs 3-at-a-time in parallel threads (one per
# candidate) via ThreadPoolExecutor, and CrewAI's Agent/AgentExecutor holds
# internal executor state that isn't safe to invoke concurrently from
# multiple threads on the SAME Agent instance ("Executor is already running"
# RuntimeError). Each cost_candidate() call instead builds its own fresh set
# of these 4 agents via _build_cost_agents() below, so the 3 concurrent
# threads never touch the same Agent object.

def _build_cost_agents():
    accommodation_finder = Agent(
        role="Accommodation & Kite Camp Finder",
        goal="Find kite camps, hotels, apartments, or villas matching the traveler's requested room type(s) and budget, with photos and ratings.",
        backstory="You've stayed at kite camps worldwide and know how to match a traveler's budget and style to the right stay.",
        tools=[search_tool, image_tool],
        llm=llm,
        verbose=True,
    )

    travel_agent = Agent(
        role="Travel Agent",
        goal=(
            "Find realistic flight prices from the traveler's departure city to the destination, "
            "quoting BOTH a standard fare and a flex/changeable fare, each including the extra fee "
            "for checking kitesurfing gear as sports equipment baggage."
        ),
        backstory=(
            "An experienced travel agent who always accounts for real-world extras: sports "
            "equipment baggage fees for kite gear, and the value of a changeable ticket for "
            "travelers who might shift dates if the wind forecast looks bad close to departure."
        ),
        tools=[search_tool],
        llm=llm,
        verbose=True,
    )

    car_rental_agent = Agent(
        role="Car Rental Agent",
        goal="Find rental car options at the destination for the trip duration.",
        backstory="You know how to match a traveler's needs (budget, group size) to the right rental car.",
        tools=[search_tool],
        llm=llm,
        verbose=True,
    )

    budget_planner = Agent(
        role="Budget & Itinerary Planner",
        goal="Merge all research into one clear day-by-day itinerary.",
        backstory="A meticulous trip planner who turns scattered research into a polished, bookable day-by-day plan.",
        tools=[search_tool],
        llm=llm,
        verbose=True,
    )

    return accommodation_finder, travel_agent, car_rental_agent, budget_planner


# ---------------------------------------------------------------------------
# Phase 1 - candidate generation + scoring
# ---------------------------------------------------------------------------

def generate_candidates(inputs: dict) -> tuple[CandidateList, list]:
    """
    inputs keys: skill_level, surf_type, start_date, end_date, budget, currency,
                 regions (list[str]), departure_city, accommodation_types (list[str]),
                 night_life (list[str])
    """
    # --- Step 1: Scout finds 3 candidates (no scoring/wind yet) ---
    scout_task = Task(
        description=(
            f"Traveler profile:\n"
            f"- Skill level: {inputs['skill_level']}\n"
            f"- Surf type: {inputs['surf_type']}\n"
            f"- Travel dates: {inputs['start_date']} to {inputs['end_date']}\n"
            f"- Budget (flights + hotel only): {inputs['budget']} {inputs['currency']}\n"
            f"- Region preference(s): {', '.join(inputs['regions']) or 'Anywhere'}\n"
            f"- Departure city: {inputs['departure_city']}\n"
            f"- Night life style preference(s): {', '.join(inputs['night_life']) or 'no preference'}\n\n"
            f"Find EXACTLY 3 candidate kitesurfing destinations matching this profile - not 2, not 4, "
            f"exactly 3. For each, write a short rationale and find 1-3 real photo URLs using the "
            f"image_search tool. Do not score or research wind yet - that happens in the next step.\n\n"
            f"When your rationale refers to the traveler's surf-style preference, use the exact term "
            f"'{inputs['surf_type']}' as given - do not paraphrase or reword it."
        ),
        expected_output=(
            "A JSON object with a 'candidates' list of EXACTLY 3 destinations, each with name, "
            "country, rationale, and photo_urls."
        ),
        agent=destination_scout,
        output_pydantic=CandidateList,
    )
    scout_crew = Crew(agents=[destination_scout], tasks=[scout_task], process=Process.sequential, verbose=True)
    _t0 = time.time()
    scout_result = scout_crew.kickoff()
    scout_duration = time.time() - _t0
    candidates = scout_result.pydantic.candidates
    scout_trace = [{"agent": t.agent, "output": t.raw, "duration_sec": round(scout_duration, 1)} for t in scout_result.tasks_output]

    # --- Step 2: Python fetches REAL wind data directly (deterministic, no LLM transcription) ---
    start_md, end_md = _month_day(inputs["start_date"]), _month_day(inputs["end_date"])
    wind_context_lines = []
    for c in candidates:
        # Include the country in the geocoding query, not just the spot
        # name - small/obscure kite spots (e.g. "Pak Nam Pran") often aren't
        # in Open-Meteo's gazetteer on their own, but "Pak Nam Pran, Thailand"
        # gives _geocode's fallback chain (full string -> name -> country) a
        # real shot at resolving it instead of failing outright.
        geocode_location = f"{c.name}, {c.country}" if c.country else c.name
        data = fetch_wind_data(geocode_location, start_md, end_md)
        if "error" in data:
            c.wind_summary = data["error"]
            c.wind_history = []
            c.wind_heatmap = {}
        else:
            c.wind_history = [YearlyWind(**y) for y in data["yearly"]]
            c.wind_heatmap = data["heatmap"]
            c.wind_summary = data["summary"]
        wind_context_lines.append(f"- {c.name}: {c.wind_summary}")

    # --- Step 3: Weather Analyst scores each candidate using the real wind data as context ---
    scoring_task = Task(
        description=(
            f"Score each of the following candidates against the rubric below. Real 5-year wind data "
            f"has ALREADY been computed for each - use it as-is for the wind reliability sub-score, "
            f"do not re-derive or contradict it:\n" + "\n".join(wind_context_lines) + "\n\n"
            f"Candidates to score (use these EXACT names in your answer): "
            f"{[c.name for c in candidates]}\n\n"
            f"Traveler profile: skill level {inputs['skill_level']}, surf type {inputs['surf_type']}, "
            f"budget (flights + hotel only) {inputs['budget']} {inputs['currency']}, departure city "
            f"{inputs['departure_city']}, region preference(s) {', '.join(inputs['regions']) or 'Anywhere'}, "
            f"night life preference(s) {', '.join(inputs['night_life']) or 'no preference'}.\n\n"
            f"{SCORING_RUBRIC}\n"
            f"Your final answer MUST be a JSON object with a 'scores' list containing EXACTLY "
            f"{len(candidates)} entries - one per candidate listed above, using its exact name. "
            f"EVERY entry MUST have all 7 sub-scores filled with real numbers (0 is only valid if that "
            f"criterion genuinely scored zero, never leave a field blank or skip a candidate)."
        ),
        expected_output=(
            f"A 'scores' list with exactly {len(candidates)} entries, each with 'name' (matching a "
            f"candidate above) and a fully-filled 7-field score breakdown."
        ),
        agent=weather_analyst,
        output_pydantic=CandidateScoreList,
    )
    score_crew = Crew(agents=[weather_analyst], tasks=[scoring_task], process=Process.sequential, verbose=True)
    _t0 = time.time()
    score_result = score_crew.kickoff()
    score_duration = time.time() - _t0
    scoring_trace = [{"agent": t.agent, "output": t.raw, "duration_sec": round(score_duration, 1)} for t in score_result.tasks_output]

    scores_by_name = {s.name: s.score for s in score_result.pydantic.scores}
    for c in candidates:
        score = scores_by_name.get(c.name, ScoreBreakdown())
        # Always re-sum the total in Python so the header number can never
        # disagree with the sub-scores shown in the breakdown.
        score.total = (
            score.wind_reliability + score.travel_accessibility + score.budget_feasibility
            + score.night_life_match + score.skill_level_match + score.surf_type_match + score.region_match
        )
        c.score = score

    return CandidateList(candidates=candidates), scout_trace + scoring_trace


# ---------------------------------------------------------------------------
# Phase 2 - full costing for ONE candidate
# ---------------------------------------------------------------------------

def _kickoff_with_retry(crew: Crew, retries: int = 1):
    """
    CrewAI's structured-output parsing (output_pydantic) occasionally fails
    when an agent's JSON answer comes back double-encoded - the whole JSON
    object wrapped in an extra layer of string quoting - which raises
    ConverterError deep inside Task._execute_core and would otherwise crash
    the whole page (it propagates straight up through crew.kickoff()).

    This is a one-off LLM formatting fluke, not a real data problem - same
    "one bad attempt shouldn't wipe out the whole run" philosophy as the
    per-year try/except in fetch_wind_data(). Re-running crew.kickoff()
    almost always gets a clean response the second time, so we retry once
    before letting the error surface for real.
    """
    last_err = None
    for attempt in range(retries + 1):
        try:
            return crew.kickoff()
        except ConverterError as e:
            last_err = e
            continue
    raise last_err


def cost_candidate(destination_name: str, inputs: dict, overrides: dict | None = None) -> tuple[FullPlan, list]:
    """
    Runs Accommodation Finder + Travel Agent + [Car Rental Agent] + Budget
    Planner for a single destination. `overrides` lets the refine step (UC3)
    change accommodation type, travel dates, and/or whether to include a
    rental car at all - without touching the other candidates.
    """
    overrides = overrides or {}
    accommodation_types = overrides.get("accommodation_types", inputs["accommodation_types"])
    start_date = overrides.get("start_date", inputs["start_date"])
    end_date = overrides.get("end_date", inputs["end_date"])
    rent_car = overrides.get("rent_car", True)

    # Fresh agent instances for this call - see note above _build_cost_agents().
    accommodation_finder, travel_agent, car_rental_agent, budget_planner = _build_cost_agents()

    # Per-task timing: since these 4 tasks run sequentially within ONE crew,
    # each Task's callback (fired the instant that task finishes, before the
    # next one starts) lets us measure that task's own duration as the delta
    # from the previous checkpoint - no need to split into separate crews.
    _durations = {}
    _clock = {"t": None}  # set to time.time() right before crew.kickoff()

    def _mk_timer(label):
        def _cb(_output):
            now = time.time()
            _durations[label] = round(now - _clock["t"], 1)
            _clock["t"] = now
        return _cb

    accommodation_task = Task(
        description=(
            f"Find AT LEAST 2 (ideally 3) accommodation options in/near {destination_name} for these "
            f"room type(s): {', '.join(accommodation_types)}. Budget: {inputs['budget']} {inputs['currency']} "
            f"for flights + hotel combined. Travel dates: {start_date} to {end_date}.\n\n"
            f"1 option is NOT enough - if your first search only turns up one good match, run at least "
            f"one more search with a different query (e.g. a broader area, a different room type, or "
            f"'kite camp' vs 'hotel') before giving up, so the traveler has something to compare.\n\n"
            f"For EACH option, find using web search: name, type, price per night, distance to the "
            f"kite spot, amenities, and its rating/review count if you can find one (e.g. '4.5 stars, "
            f"320 reviews'). Then use the image_search tool to find 1-2 real photo URLs for each "
            f"option (search e.g. '<hotel name> <destination>'). Do not skip the photo search - every "
            f"option should have photo_urls filled in if any image is found.\n\n"
            f"For source_url, find the hotel/camp's OWN OFFICIAL WEBSITE specifically (its own domain, "
            f"e.g. 'sourcekiteboarding.com') - NOT a booking aggregator like Booking.com, Expedia, "
            f"TripAdvisor, or Google listings. Try at least 2 search phrasings (e.g. '<hotel name> "
            f"official website' and '<hotel name> <destination> homepage') before giving up. If truly "
            f"no official site can be found for an option after trying, leave source_url empty rather "
            f"than using an aggregator link."
        ),
        expected_output=(
            "AT LEAST 2 accommodation options (3 preferred), each with: name, type, price_per_night, "
            "currency, distance_to_spot, amenities, rating (if found), photo_urls (1-2 real image URLs "
            "each), and source_url pointing to the hotel's own official website (not an aggregator)."
        ),
        agent=accommodation_finder,
        output_pydantic=AccommodationOptionList,
        callback=_mk_timer("Accommodation & Kite Camp Finder"),
    )

    travel_task = Task(
        description=(
            f"Find flight prices from {inputs['departure_city']} to {destination_name} for "
            f"{start_date} to {end_date}. Quote BOTH a standard fare and a "
            f"flex/changeable fare, each including the extra fee for checking kitesurfing gear as "
            f"sports equipment baggage. Report both clearly, with fare_type exactly 'standard' or 'flex'.\n\n"
            f"Your final answer must be a single raw JSON object matching the schema - do NOT wrap it "
            f"in quotes, markdown code fences, or any extra commentary."
        ),
        expected_output="Two flight options (fare_type='standard' and fare_type='flex'), each with price, airline, and baggage fee notes.",
        agent=travel_agent,
        output_pydantic=FlightOptionList,
        callback=_mk_timer("Travel Agent"),
    )

    # Car rental is optional - the traveler can opt out entirely (e.g. when
    # refining a plan). When skipped, car_task is simply not created/run at
    # all, and plan.car_rental_options / car_rental_price are forced to
    # empty/0 further down rather than left to the LLM to reason about.
    car_task = None
    if rent_car:
        car_task = Task(
            description=f"Find rental car options at/near {destination_name} for the trip duration ({start_date} to {end_date}).",
            expected_output="2-3 rental car options with company, car type, and price per day.",
            agent=car_rental_agent,
            output_pydantic=CarRentalOptionList,
            callback=_mk_timer("Car Rental Agent"),
        )

    car_note = (
        "car rental options" if rent_car
        else "NO car rental (the traveler explicitly opted out of renting a car - do not mention "
             "renting a car in the itinerary, assume they'll use taxis/transfers/on foot instead)"
    )
    budget_task = Task(
        description=(
            f"Using the accommodation options, flight options (standard + flex), and {car_note} "
            f"for {destination_name}, build a day-by-day itinerary for "
            f"{start_date} to {end_date}. Do NOT include kitesurfing lessons or "
            f"gear rental costs anywhere - they are intentionally excluded from this plan's budget.\n\n"
            f"The itinerary MUST span the full round trip, not just the stay: day 1 must be the "
            f"OUTBOUND travel day (departing {inputs['departure_city']}), the middle days are the "
            f"actual stay at {destination_name}, and the LAST day must be the RETURN travel day "
            f"(traveling back to {inputs['departure_city']}). Do not omit the return travel day.\n\n"
            f"Your final answer MUST be a single JSON object with EXACTLY these top-level fields, all "
            f"of them, none omitted:\n"
            f"- destination (string)\n"
            f"- itinerary (list of {{day: int, description: string}}, no cost figures needed here)\n"
            f"- accommodation_options (list, carried over from the accommodation research INCLUDING each "
            f"option's rating and photo_urls - do not drop those sub-fields)\n"
            f"- flight_options (list, carried over from the travel research - do not drop this)\n"
            f"- car_rental_options (list, carried over from the car rental research if any was done, "
            f"otherwise [])\n"
            f"- cost_breakdown (string, readable text explaining what's included - do NOT put final "
            f"totals here, just explain the components; totals are computed separately)\n"
            f"Leave numeric totals to the system - just carry over the option lists accurately and "
            f"write the itinerary and cost_breakdown explanation. Use [] for any list you can't fill, "
            f"never omit a field."
        ),
        expected_output=(
            "A single JSON object with: destination, itinerary, accommodation_options, flight_options, "
            "car_rental_options, cost_breakdown - all option lists carried over accurately from prior tasks."
        ),
        agent=budget_planner,
        context=[accommodation_task, travel_task] + ([car_task] if car_task else []),
        output_pydantic=FullPlan,
        callback=_mk_timer("Budget & Itinerary Planner"),
    )

    # Sequential, not hierarchical: each task already names its own agent
    # explicitly, so a Manager "deciding" who does what would just be
    # redundant LLM calls that only slow things down without changing the
    # outcome. This is the main runtime fix - removes ~4 extra LLM calls
    # per candidate.
    crew_agents = [accommodation_finder, travel_agent, budget_planner]
    crew_tasks = [accommodation_task, travel_task]
    if car_task:
        crew_agents.insert(2, car_rental_agent)
        crew_tasks.append(car_task)
    crew_tasks.append(budget_task)
    crew = Crew(
        agents=crew_agents,
        tasks=crew_tasks,
        process=Process.sequential,
        verbose=True,
    )
    candidate_start = time.time()
    _clock["t"] = candidate_start
    result = _kickoff_with_retry(crew)
    candidate_duration = round(time.time() - candidate_start, 1)
    raw_outputs = [
        {"agent": t.agent, "output": t.raw, "duration_sec": _durations.get(t.agent)}
        for t in result.tasks_output
    ]
    plan = result.pydantic
    # Never trust the LLM to echo the destination name back correctly (or at
    # all - this is what was crashing the pipeline) - we already know it.
    plan.destination = destination_name
    if not plan.itinerary:
        plan.itinerary = _default_itinerary(destination_name, inputs["departure_city"], start_date, end_date)

    # --- Trust each research task's OWN structured output for its option
    # list, not budget_task's re-transcription of it. Asking one more LLM
    # call (budget_task) to copy these lists into its own JSON was silently
    # dropping or zeroing values for some candidates (e.g. flight/car prices
    # coming back as 0) - same root cause as the earlier wind-data and score
    # bugs. Overriding here guarantees the numbers actually used for costing
    # match what Accommodation/Travel/Car actually found.
    if accommodation_task.output and accommodation_task.output.pydantic:
        plan.accommodation_options = accommodation_task.output.pydantic.options
    if travel_task.output and travel_task.output.pydantic:
        plan.flight_options = travel_task.output.pydantic.options
    if car_task and car_task.output and car_task.output.pydantic:
        plan.car_rental_options = car_task.output.pydantic.options
    elif not car_task:
        plan.car_rental_options = []  # traveler opted out - never let the LLM invent one anyway

    # Replace each research task's raw prose in the trace with a
    # consistently-formatted summary built from its own structured output
    # (see comment above _fmt_accommodation_options).
    _trace_formatters = {
        accommodation_finder.role: lambda: _fmt_accommodation_options(plan.accommodation_options),
        travel_agent.role: lambda: _fmt_flight_options(plan.flight_options),
        car_rental_agent.role: lambda: _fmt_car_options(plan.car_rental_options),
    }
    for entry in raw_outputs:
        fmt = _trace_formatters.get(entry["agent"])
        if fmt:
            entry["output"] = fmt()

    # --- Compute totals deterministically from the structured option prices ---
    # (never trust the LLM's arithmetic for the numbers actually shown as totals)
    nights = _nights(start_date, end_date)

    standard_flight = next((f.price for f in plan.flight_options if f.fare_type.lower() == "standard"), None)
    flex_flight = next((f.price for f in plan.flight_options if f.fare_type.lower() == "flex"), None)
    if standard_flight is None and plan.flight_options:
        standard_flight = plan.flight_options[0].price
    if flex_flight is None and plan.flight_options:
        flex_flight = plan.flight_options[-1].price
    standard_flight = standard_flight or 0.0
    flex_flight = flex_flight or standard_flight

    cheapest_hotel_per_night = min((a.price_per_night for a in plan.accommodation_options), default=0.0)
    hotel_cost = cheapest_hotel_per_night * nights

    cheapest_car_per_day = min((c.price_per_day for c in plan.car_rental_options), default=0.0)
    car_cost = cheapest_car_per_day * nights
    food_cost = FOOD_ESTIMATE_PER_DAY * nights

    plan.standard_flight_price = round(standard_flight, 2)
    plan.flex_flight_price = round(flex_flight, 2)
    plan.accommodation_price = round(hotel_cost, 2)
    plan.car_rental_price = round(car_cost, 2)
    plan.other_expenses_price = round(food_cost, 2)

    plan.flights_and_hotel_standard = round(standard_flight + hotel_cost, 2)
    plan.flights_and_hotel_flex = round(flex_flight + hotel_cost, 2)
    plan.total_cost_standard_fare = round(standard_flight + hotel_cost + car_cost + food_cost, 2)
    plan.total_cost_flex_fare = round(flex_flight + hotel_cost + car_cost + food_cost, 2)
    if plan.flight_options:
        plan.currency = plan.flight_options[0].currency or plan.currency

    # Append a synthetic "Total" entry (not a real agent) so the trace/UI can
    # show how long this destination's own costing took, in seconds -
    # duration_sec on this entry is the wall-clock total; app.py knows to
    # treat "output" here as a plain label, not JSON to be cleaned up.
    raw_outputs.append({
        "agent": "Total (this destination)",
        "output": f"{candidate_duration}s",
        "duration_sec": candidate_duration,
    })

    return plan, raw_outputs


def generate_full_plans(inputs: dict) -> tuple[list[dict], list]:
    """
    Full Phase 1 + Phase 2 pipeline. Returns (results, shared_trace):
      - results: one dict per candidate: {"candidate": Candidate, "plan": FullPlan,
        "agent_trace": [...]} where agent_trace is ONLY that candidate's own
        Accommodation/Travel/Car/Budget agent output (not shared with the others).
      - shared_trace: the Destination Scout + Weather Analyst output, which
        genuinely applies to all 3 candidates together (they were researched
        and scored in one pass), shown once above the comparison.
    """
    run_start = time.time()
    candidate_list, shared_trace = generate_candidates(inputs)

    # The 3 candidates' costing crews are fully independent of each other,
    # so run them concurrently instead of one after another - this is the
    # other half of the runtime fix (alongside the sequential-process change
    # in cost_candidate itself). Each thread runs its own Crew.kickoff(),
    # which is I/O-bound (LLM + search API calls), so threads - not
    # processes - are the right tool here.
    with ThreadPoolExecutor(max_workers=len(candidate_list.candidates)) as pool:
        futures = [
            pool.submit(cost_candidate, c.name, inputs)
            for c in candidate_list.candidates
        ]
        outcomes = [f.result() for f in futures]

    total_seconds = round(time.time() - run_start, 1)
    shared_trace = shared_trace + [{
        "agent": "Total (full run: all 3 candidates)",
        "output": f"{total_seconds}s",
        "duration_sec": total_seconds,
    }]

    results = [
        {"candidate": c, "plan": plan, "agent_trace": cost_trace}
        for c, (plan, cost_trace) in zip(candidate_list.candidates, outcomes)
    ]
    return results, shared_trace


def refine_plan(destination_name: str, inputs: dict, overrides: dict) -> tuple[FullPlan, list]:
    """UC3: re-cost a single already-chosen destination with updated parameters."""
    return cost_candidate(destination_name, inputs, overrides=overrides)
