"""
app.py

Streamlit web app for the Kitesurfing Vacation Planner.
Run with:  uv run streamlit run app.py

Two tabs:
- New Plan  (UC1-UC4, UC9): generate 3 fully-costed candidates, compare,
  choose one, refine it, download PDF.
- History   (UC6-UC8): past trips, mark completed, leave a review.
"""

import os
from datetime import date, timedelta

from dotenv import load_dotenv
load_dotenv()

import streamlit as st

import db
import crew
from pdf_export import build_pdf
from airports import airport_options, code_from_label
from countries import all_countries
from theme import THEME_CSS, render_hero, render_form_header, render_page_banner

st.set_page_config(page_title="Kitesurf Vacation Planner", page_icon="🪁", layout="wide")
st.markdown(THEME_CSS, unsafe_allow_html=True)

REGION_OPTIONS = [
    "Anywhere", "Europe", "North Africa & Red Sea", "Caribbean & Americas",
    "Southeast Asia", "Africa", "Other",
]
MAX_OTHER_COUNTRIES = 5
ACCOMMODATION_OPTIONS = ["Double room (2 adults)", "Single room", "Villa", "Apartment"]
NIGHT_LIFE_OPTIONS = ["Quiet / chill", "Beach bars", "Lively nightlife / clubs", "Family-friendly", "Doesn't matter"]
CURRENCIES = ["USD", "NIS", "EUR"]
HEATMAP_HOURS = [f"{h:02d}:00" for h in range(9, 19)]


def safe_text(s) -> str:
    """
    Streamlit's markdown renderer treats $...$ as LaTeX math, which garbles
    any agent-written text containing dollar amounts (e.g. "$2,700 total").
    It also treats ~ as a strikethrough marker, which garbles agent text
    that casually uses "~$780" to mean "approximately $780" (two tildes in
    the same paragraph get read as a strikethrough span). Escape both before
    displaying any LLM-generated free text.
    """
    if not s:
        return ""
    return str(s).replace("$", "\\$").replace("~", "\\~")


def render_trace_output(agent_name: str, raw_output: str):
    """
    In hierarchical mode, the Manager's final synthesis for a structured
    task is a raw JSON blob (that's just what its "final answer" looks like
    when the task uses output_pydantic) - not useful to show verbatim since
    the same data already appears formatted elsewhere on the page, and the
    Activity Summary already recaps what happened. Replace it with a short
    note instead of a wall of JSON.
    """
    stripped = (raw_output or "").strip()
    looks_like_json = stripped.startswith("{") or stripped.startswith("[")
    if looks_like_json:
        st.write(
            "Compiled the final structured plan (itinerary, accommodation, flights, car rental, "
            "and costs) - see the sections above and the Activity Summary below for the readable version."
        )
    else:
        st.write(safe_text(raw_output))


def wind_color(knots) -> str:
    """Color thresholds per spec, in knots."""
    if knots is None:
        return "#f0f0f0"
    if knots <= 10:
        return "#cfe8f7"  # pale blue
    if knots <= 15:
        return "#a5d6a7"  # green
    if knots <= 18:
        return "#fff176"  # yellow
    if knots <= 25:
        return "#ffb74d"  # orange
    if knots <= 30:
        return "#ef5350"  # red
    return "#ba68c8"      # purple


def render_wind_heatmap_html(wind_heatmap: dict) -> str:
    """Builds one color-coded HTML table per year, newest year first."""
    if not wind_heatmap:
        return "<p>No hourly wind data available.</p>"

    years = sorted(wind_heatmap.keys(), reverse=True)
    parts = []
    for year in years:
        data = wind_heatmap[year]
        avg_min = data.get("avg_min", {})
        avg_max = data.get("avg_max", {})
        hours = [h for h in HEATMAP_HOURS if h in avg_min or h in avg_max]
        if not hours:
            continue

        header_cells = "".join(f"<th style='padding:6px 10px;border:1px solid #ccc;'>{h}</th>" for h in hours)

        def row(label, values):
            cells = ""
            for h in hours:
                v = values.get(h)
                color = wind_color(v)
                text = v if v is not None else "-"
                cells += f"<td style='padding:6px 10px;border:1px solid #ccc;background:{color};text-align:center;'>{text}</td>"
            return f"<tr><th style='padding:6px 10px;border:1px solid #ccc;background:#e0e0e0;'>{label}</th>{cells}</tr>"

        table = (
            # On a narrow (phone) screen this 11-column table is wider than
            # the viewport - without its own overflow-x:auto wrapper, that
            # would force the WHOLE PAGE to scroll sideways instead of just
            # this table. Wrapping it keeps the scrolling contained here.
            f"<div style='overflow-x:auto;margin-bottom:14px;'>"
            f"<table style='border-collapse:collapse;font-size:13px;'>"
            f"<tr><th colspan='{len(hours)+1}' style='padding:6px;border:1px solid #ccc;background:#d0d0d0;'>{year}</th></tr>"
            f"<tr><th style='padding:6px 10px;border:1px solid #ccc;background:#e0e0e0;'>Time</th>{header_cells}</tr>"
            f"{row('Avg Min', avg_min)}"
            f"{row('Avg Max', avg_max)}"
            f"</table>"
            f"</div>"
        )
        parts.append(table)
    return "".join(parts)


def build_activity_summary(candidate, plan) -> list:
    """
    Deterministic plain-language process recap - what each agent did during
    this candidate's research, NOT a restatement of the data itself (which
    is already shown elsewhere on the page).
    """
    lines = [
        f"Destination Scout proposed {candidate.name} and Weather Analyst scored it "
        f"{candidate.score.total}/22 against the rubric, using real 5-year wind history.",
        f"Accommodation Finder searched for stays and returned {len(plan.accommodation_options)} "
        f"option(s) matching the requested room type(s).",
        f"Travel Agent searched for flights and returned {len(plan.flight_options)} fare option(s) "
        f"(standard and flex), including kite gear baggage fees.",
        f"Car Rental Agent searched for rental cars and returned {len(plan.car_rental_options)} "
        f"option(s) at the destination.",
        f"Budget & Itinerary Planner compiled a {len(plan.itinerary)}-day itinerary covering the "
        f"outbound trip, the stay, and the return trip, then the system computed the final costs.",
    ]
    return lines


# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------
for key, default in {
    "stage": "landing",       # landing -> form -> compare -> refine
    "trip_id": None,
    "results": None,          # list of {candidate, plan, agent_trace}
    "shared_trace": None,     # Destination Scout + Weather Analyst output (applies to all candidates)
    "chosen": None,           # index into results
    "inputs": None,
    "last_refine_seconds": None,  # how long the most recent "Regenerate" tweak took
}.items():
    if key not in st.session_state:
        st.session_state[key] = default


def missing_keys():
    return [
        k for k in ("ANTHROPIC_API_KEY", "SERPER_API_KEY")
        if not os.getenv(k) or "your_" in os.getenv(k, "")
    ]


# ---------------------------------------------------------------------------
# New Plan tab
# ---------------------------------------------------------------------------

def region_multiselect():
    """Anywhere is mutually exclusive with everything else."""
    prev = st.session_state.get("region_select", ["Anywhere"])
    selected = st.multiselect("Region preference", REGION_OPTIONS, default=prev, key="region_select_widget")

    if "Anywhere" in selected and len(selected) > 1:
        if prev == ["Anywhere"]:
            selected = [r for r in selected if r != "Anywhere"]
        else:
            selected = ["Anywhere"]
    if not selected:
        selected = ["Anywhere"]

    st.session_state["region_select"] = selected
    return selected


def render_landing():
    """The app's cover page: hero + a single CTA. Clicking it moves to the
    trip-details form on its own page, rather than showing the form stacked
    directly under the hero."""
    render_hero()

    keys_missing = missing_keys()
    if keys_missing:
        st.warning(f"Missing/placeholder API key(s): {', '.join(keys_missing)}. Fill them in your `.env` file before generating a plan.")

    if st.button("Generate Vacation Plans 🪁", type="primary"):
        st.session_state["stage"] = "form"
        st.rerun()


def render_form():
    render_form_header()

    keys_missing = missing_keys()
    if keys_missing:
        st.warning(f"Missing/placeholder API key(s): {', '.join(keys_missing)}. Fill them in your `.env` file before generating a plan.")

    # Region (and, when "Other" is picked, the country picker) lives OUTSIDE
    # st.form on purpose: widgets inside a form don't trigger a script rerun
    # until the whole form is submitted, so a conditional widget like the
    # country picker would only ever appear a run late (i.e. after you'd
    # already submitted once with nothing selected). Keeping it outside lets
    # it react immediately when you pick "Other".
    regions = region_multiselect()
    other_countries = []
    if "Other" in regions:
        other_countries = st.multiselect(
            f"Choose up to {MAX_OTHER_COUNTRIES} countries",
            all_countries(),
            max_selections=MAX_OTHER_COUNTRIES,
        )

    with st.form("trip_form"):
        col1, col2 = st.columns(2)
        with col1:
            skill_level = st.selectbox("Skill level", ["Beginner", "Intermediate", "Advanced"])
            surf_type = st.selectbox("Surfing type", ["Freestyle", "Waves", "Freestyle & Waves"])
            date_range = st.date_input(
                "Travel dates",
                value=(date.today() + timedelta(days=60), date.today() + timedelta(days=67)),
            )
            departure_label = st.selectbox("Departure city", airport_options(), index=0)
        with col2:
            budget_col, currency_col = st.columns([2, 1])
            budget = budget_col.number_input("Budget (flights + hotel only)", min_value=0, value=2000, step=100)
            currency = currency_col.selectbox("Currency", CURRENCIES)
            st.caption("This budget covers flights and hotel only - car rental and food are estimated separately.")
            accommodation_types = st.multiselect("Accommodation type", ACCOMMODATION_OPTIONS, default=[ACCOMMODATION_OPTIONS[0]])
            night_life = st.multiselect("Night life style", NIGHT_LIFE_OPTIONS)

        submitted = st.form_submit_button("Find the Best Spots for Me 🪁")

    if submitted:
        errors = []
        if not accommodation_types:
            errors.append("Pick at least one accommodation type.")
        if not isinstance(date_range, tuple) or len(date_range) != 2:
            errors.append("Pick a full date range.")
        if errors:
            for e in errors:
                st.error(e)
            return

        final_regions = regions
        if "Other" in regions and other_countries:
            final_regions = [r for r in regions if r != "Other"] + other_countries

        inputs = {
            "skill_level": skill_level,
            "surf_type": surf_type,
            "start_date": str(date_range[0]),
            "end_date": str(date_range[1]),
            "budget": budget,
            "currency": currency,
            "regions": [] if final_regions == ["Anywhere"] else final_regions,
            "departure_city": code_from_label(departure_label),
            "accommodation_types": accommodation_types,
            "night_life": night_life,
        }

        with st.spinner("Generating and fully costing 3 candidate destinations... this can take several minutes."):
            results, shared_trace = crew.generate_full_plans(inputs)
            trip_id = db.save_trip(inputs, [
                {"candidate": r["candidate"].model_dump(), "plan": r["plan"].model_dump()} for r in results
            ])

        st.session_state["results"] = results
        st.session_state["shared_trace"] = shared_trace
        st.session_state["trip_id"] = trip_id
        st.session_state["inputs"] = inputs
        st.session_state["stage"] = "compare"
        st.rerun()


def render_cost_breakdown(plan):
    """Itemized breakdown used both in compare view and refine view."""
    st.write(f"Standard fare flight: {plan.standard_flight_price:.0f} {plan.currency}")
    st.write(f"Flex fare flight: {plan.flex_flight_price:.0f} {plan.currency}")
    st.write(f"Accommodation: {plan.accommodation_price:.0f} {plan.currency}")
    st.write(f"Car rental: {plan.car_rental_price:.0f} {plan.currency}")
    st.write(f"Other expenses: {plan.other_expenses_price:.0f} {plan.currency}")
    st.markdown(f"**Total (standard fare): {plan.total_cost_standard_fare:.0f} {plan.currency}**")
    st.markdown(f"**Total (flex fare): {plan.total_cost_flex_fare:.0f} {plan.currency}**")


def render_compare():
    results = st.session_state["results"]
    shared_trace = st.session_state.get("shared_trace") or []
    render_page_banner(
        f"Compare your {len(results)} candidate destination{'s' if len(results) != 1 else ''}",
        "Each one was researched, wind-scored, and fully costed by the agent team.",
    )
    if len(results) != 3:
        st.caption("Note: the agent team returned a different number of candidates than the usual 3 for this request.")

    # The "Total (full run...)" entry is a synthetic timing marker, not a
    # real agent step - pull it out for a headline metric instead of
    # showing it inline in the agent trace.
    total_entry = next((t for t in shared_trace if t["agent"].startswith("Total (full run")), None)
    step_trace = [t for t in shared_trace if not t["agent"].startswith("Total (full run")]
    if total_entry:
        st.metric("Total time to generate all 3 offers", f"{total_entry['duration_sec']}s")

    with st.expander("See how the Destination Scout & Weather Analyst worked (applies to all 3 candidates - they were researched and scored together)"):
        for t in step_trace:
            dur = f" ({t['duration_sec']}s)" if t.get("duration_sec") is not None else ""
            st.markdown(f"**{t['agent']}**{dur}")
            render_trace_output(t["agent"], t["output"])
            st.divider()

    # --- Quick side-by-side glance: name, country, score, score breakdown only ---
    cols = st.columns(max(len(results), 1))
    for col, entry in zip(cols, results):
        c = entry["candidate"]
        with col:
            st.subheader(c.name)
            if c.country:
                st.caption(c.country)
            st.metric("Score", f"{c.score.total} / 22")
            with st.expander("Score breakdown"):
                s = c.score
                st.table([
                    {"Criterion": "Wind reliability", "Points": f"{s.wind_reliability} / 5"},
                    {"Criterion": "Travel accessibility", "Points": f"{s.travel_accessibility} / 4"},
                    {"Criterion": "Budget feasibility", "Points": f"{s.budget_feasibility} / 4"},
                    {"Criterion": "Night life match", "Points": f"{s.night_life_match} / 3"},
                    {"Criterion": "Skill level match", "Points": f"{s.skill_level_match} / 2"},
                    {"Criterion": "Surf type match", "Points": f"{s.surf_type_match} / 2"},
                    {"Criterion": "Region match", "Points": f"{s.region_match} / 2"},
                    {"Criterion": "Total", "Points": f"{s.total} / 22"},
                ])

    st.divider()

    # --- Full detail per candidate, stacked one after another (not side by side) ---
    for i, entry in enumerate(results):
        c, plan = entry["candidate"], entry["plan"]
        candidate_total = next(
            (t for t in entry["agent_trace"] if t["agent"] == "Total (this destination)"), None
        )
        header = f"{c.name}" + (f" — {c.country}" if c.country else "")
        if candidate_total:
            header += f"  ⏱ {candidate_total['duration_sec']}s to cost this offer"
        st.header(header)

        if c.photo_urls:
            st.image(c.photo_urls[0], width=500)
        st.caption(safe_text(c.wind_summary))
        st.write(safe_text(c.rationale))

        if c.wind_heatmap:
            with st.expander("5-year hourly wind heatmap (knots)"):
                st.markdown(render_wind_heatmap_html(c.wind_heatmap), unsafe_allow_html=True)

        with st.expander("Full trip total (incl. car rental & food)"):
            render_cost_breakdown(plan)

        with st.expander(f"See how each agent contributed for {c.name}"):
            for t in entry["agent_trace"]:
                if t["agent"] == "Total (this destination)":
                    continue
                dur = f" ({t['duration_sec']}s)" if t.get("duration_sec") is not None else ""
                st.markdown(f"**{t['agent']}**{dur}")
                render_trace_output(t["agent"], t["output"])
                st.divider()

        with st.expander(f"Activity summary for {c.name}"):
            for line in build_activity_summary(c, plan):
                st.write(f"- {line}")

        if st.button(f"Choose {c.name}", key=f"choose_{i}"):
            st.session_state["chosen"] = i
            db.update_selection(st.session_state["trip_id"], c.name, plan.model_dump())
            st.session_state["stage"] = "refine"
            st.rerun()

        st.divider()

    if st.button("Start over"):
        for key in ("stage", "trip_id", "results", "shared_trace", "chosen", "inputs", "last_refine_seconds"):
            st.session_state[key] = None if key != "stage" else "landing"
        st.rerun()


def render_refine():
    results = st.session_state["results"]
    chosen = results[st.session_state["chosen"]]
    c, plan = chosen["candidate"], chosen["plan"]
    inputs = st.session_state["inputs"]

    render_page_banner(f"{c.name} — your plan", c.country or "")

    tweak_col, view_col = st.columns([1, 2])
    with tweak_col:
        st.subheader("Tweak this destination")
        new_accommodation = st.multiselect("Accommodation type", ACCOMMODATION_OPTIONS, default=inputs["accommodation_types"])
        new_dates = st.date_input(
            "Travel dates",
            value=(date.fromisoformat(inputs["start_date"]), date.fromisoformat(inputs["end_date"])),
        )
        new_rent_car = st.checkbox("Rent a car", value=True)
        if st.button("Regenerate for this destination"):
            overrides = {"accommodation_types": new_accommodation, "rent_car": new_rent_car}
            if isinstance(new_dates, tuple) and len(new_dates) == 2:
                overrides["start_date"] = new_dates[0].isoformat()
                overrides["end_date"] = new_dates[1].isoformat()
            else:
                st.warning("Pick both a start and end date - using the original dates for this run.")
            with st.spinner("Refining this destination's plan..."):
                new_plan, trace = crew.refine_plan(c.name, inputs, overrides)
                db.update_refinement(st.session_state["trip_id"], overrides, new_plan.model_dump())
            results[st.session_state["chosen"]]["plan"] = new_plan
            results[st.session_state["chosen"]]["agent_trace"] = trace
            st.session_state["results"] = results
            # Pull the one overall timing figure for this regeneration (not
            # a per-agent breakdown - just how long the whole tweak took) so
            # it survives the rerun below and can be shown near the button.
            total_entry = next((t for t in trace if t["agent"] == "Total (this destination)"), None)
            st.session_state["last_refine_seconds"] = total_entry["duration_sec"] if total_entry else None
            st.rerun()

        if st.session_state.get("last_refine_seconds") is not None:
            st.caption(f"⏱ Last regeneration took {st.session_state['last_refine_seconds']}s.")

        st.divider()
        if st.button("Download PDF"):
            pdf_candidates = [{"candidate": r["candidate"].model_dump(), "plan": r["plan"].model_dump()} for r in results]
            path = build_pdf(st.session_state["trip_id"], pdf_candidates, c.name, plan.model_dump())
            db.update_pdf_path(st.session_state["trip_id"], path)
            with open(path, "rb") as f:
                st.download_button("Save PDF", f, file_name=f"{c.name}_vacation_plan.pdf", mime="application/pdf")

        if st.button("Back to comparison"):
            st.session_state["stage"] = "compare"
            st.rerun()

    with view_col:
        # Same order as the PDF export: Budget -> 5-year wind history ->
        # flights -> accommodation -> car rental -> day-by-day itinerary.
        st.subheader("Full trip total (incl. car rental & food)")
        render_cost_breakdown(plan)
        st.write(safe_text(plan.cost_breakdown))

        st.subheader("5-year hourly wind history (knots)")
        if c.wind_heatmap:
            st.markdown(render_wind_heatmap_html(c.wind_heatmap), unsafe_allow_html=True)
        else:
            st.caption(safe_text(c.wind_summary) or "No historical wind data available.")

        st.subheader("Flights")
        for f in plan.flight_options:
            st.write(safe_text(f"- **{f.fare_type.title()} fare**: {f.price} {f.currency} ({f.airline}) — {f.notes}"))

        st.subheader("Accommodation options")
        for a in plan.accommodation_options:
            acc_photo_col, acc_info_col = st.columns([1, 3])
            with acc_photo_col:
                if a.photo_urls:
                    st.image(a.photo_urls[0], use_container_width=True)
            with acc_info_col:
                st.markdown(f"**{safe_text(a.name)}** ({safe_text(a.type)})")
                st.write(safe_text(f"{a.price_per_night} {a.currency}/night — {a.distance_to_spot}"))
                if a.rating:
                    st.write(safe_text(f"Rating: {a.rating}"))
                if a.amenities:
                    st.caption(safe_text(a.amenities))
                if a.source_url:
                    st.markdown(f"[Official hotel website]({a.source_url})")
            st.divider()

        st.subheader("Car rental")
        if plan.car_rental_options:
            for car in plan.car_rental_options:
                st.write(safe_text(f"- {car.company} ({car.car_type}) — {car.price_per_day} {car.currency}/day"))
        else:
            st.caption("No rental car included in this plan.")

        st.subheader("Day-by-day itinerary")
        for day in plan.itinerary:
            st.write(safe_text(f"**Day {day.day}:** {day.description}"))

        with st.expander(f"Activity summary for {c.name}"):
            for line in build_activity_summary(c, plan):
                st.write(f"- {line}")


# ---------------------------------------------------------------------------
# History tab
# ---------------------------------------------------------------------------

def render_history():
    st.title("📜 Trip history")
    trips = db.list_trips()
    if not trips:
        st.info("No trips generated yet. Create one in the New Plan tab.")
        return

    with st.expander("🗑 Clear history"):
        st.caption(
            "Delete everything at once, or check individual trips below (inside each "
            "trip's expander) and use \"Delete selected\" at the bottom of the list."
        )
        confirm_clear = st.checkbox("I understand this cannot be undone", key="confirm_clear_all")
        if st.button("Clear ALL history", type="primary", disabled=not confirm_clear):
            db.delete_all_trips()
            st.session_state.pop("confirm_clear_all", None)
            st.success("History cleared.")
            st.rerun()

    selected_ids = []
    for trip in trips:
        with st.expander(f"Trip #{trip['id']} — {trip['selected_destination'] or 'no destination chosen'} — {trip['status']} — {trip['created_at'][:10]}"):
            if st.checkbox("Select for deletion", key=f"select_trip_{trip['id']}"):
                selected_ids.append(trip["id"])
            st.write(f"Status: **{trip['status']}**")
            if trip["pdf_path"] and os.path.exists(trip["pdf_path"]):
                with open(trip["pdf_path"], "rb") as f:
                    st.download_button("Download PDF", f, file_name=f"trip_{trip['id']}.pdf", key=f"dl_{trip['id']}")

            if trip["status"] != "Completed":
                if st.button("Mark as taken", key=f"complete_{trip['id']}"):
                    db.mark_completed(trip["id"])
                    st.rerun()
            else:
                st.subheader("Review this trip")
                categories = ["spot", "wind", "beach_services", "food", "cost", "hotel", "atmosphere"]
                labels = ["Spot", "Wind Conditions", "Beach Services", "Food", "Cost", "Hotel", "Atmosphere"]
                ratings = {}
                cols = st.columns(len(categories))
                for cat, label, col in zip(categories, labels, cols):
                    with col:
                        ratings[cat] = st.slider(label, 1, 5, 3, key=f"{cat}_{trip['id']}")
                would_return = st.radio("Would you come back?", ["Yes", "No"], key=f"return_{trip['id']}")
                review_text = st.text_area("Your opinion", key=f"review_{trip['id']}")
                if st.button("Save review", key=f"save_review_{trip['id']}"):
                    db.save_review(trip["id"], ratings, would_return, review_text)
                    st.success("Review saved.")

    if selected_ids:
        st.divider()
        if st.button(f"🗑 Delete {len(selected_ids)} selected trip(s)", type="primary"):
            db.delete_trips(selected_ids)
            for tid in selected_ids:
                st.session_state.pop(f"select_trip_{tid}", None)
            st.success(f"Deleted {len(selected_ids)} trip(s).")
            st.rerun()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

tab_new, tab_history = st.tabs(["🪁 New Plan", "📜 History"])

with tab_new:
    if st.session_state["stage"] == "landing":
        render_landing()
    elif st.session_state["stage"] == "form":
        render_form()
    elif st.session_state["stage"] == "compare":
        render_compare()
    elif st.session_state["stage"] == "refine":
        render_refine()

with tab_history:
    render_history()
