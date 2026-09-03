"""
pdf_export.py

UC9: builds a downloadable PDF containing all 3 candidate destinations
(with scores/rationale) plus the full itinerary and budget breakdown for
the chosen (and possibly refined) destination.
"""

from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)

OUTPUT_DIR = Path(__file__).parent / "pdf_exports"
OUTPUT_DIR.mkdir(exist_ok=True)

HEATMAP_HOURS = [f"{h:02d}:00" for h in range(9, 19)]


def _wind_color(knots):
    """Same color thresholds as the web app's wind_color(), in knots."""
    if knots is None:
        return colors.HexColor("#f0f0f0")
    if knots <= 10:
        return colors.HexColor("#cfe8f7")  # pale blue
    if knots <= 15:
        return colors.HexColor("#a5d6a7")  # green
    if knots <= 18:
        return colors.HexColor("#fff176")  # yellow
    if knots <= 25:
        return colors.HexColor("#ffb74d")  # orange
    if knots <= 30:
        return colors.HexColor("#ef5350")  # red
    return colors.HexColor("#ba68c8")      # purple


def _wind_heatmap_flowables(wind_heatmap: dict, styles) -> list:
    """
    Redraws the 5-year hourly wind heatmap as native colored PDF tables (one
    per year, newest first) - same color coding as the web app - instead of
    embedding a screenshot of the page.
    """
    flowables = []
    if not wind_heatmap:
        return flowables

    flowables.append(Paragraph("5-year hourly wind history (knots)", styles["Heading3"]))
    years = sorted(wind_heatmap.keys(), reverse=True)
    for year in years:
        data = wind_heatmap.get(year, {})
        avg_min = data.get("avg_min", {})
        avg_max = data.get("avg_max", {})
        hours = [h for h in HEATMAP_HOURS if h in avg_min or h in avg_max]
        if not hours:
            continue

        flowables.append(Paragraph(f"{year}", styles["SmallGray"]))
        header = ["Hour"] + [h for h in hours]
        min_row = ["Avg sustained"] + [avg_min.get(h, "") for h in hours]
        max_row = ["Avg gust"] + [avg_max.get(h, "") for h in hours]
        rows = [header, min_row, max_row]

        style_cmds = [
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2A44")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 6.5),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ALIGN", (1, 0), (-1, -1), "CENTER"),
            ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#e0e0e0")),
        ]
        for col, h in enumerate(hours, start=1):
            style_cmds.append(("BACKGROUND", (col, 1), (col, 1), _wind_color(avg_min.get(h))))
            style_cmds.append(("BACKGROUND", (col, 2), (col, 2), _wind_color(avg_max.get(h))))

        col_widths = [55] + [41] * len(hours)
        flowables.append(Table(rows, colWidths=col_widths, style=TableStyle(style_cmds)))
        flowables.append(Spacer(1, 4))

    return flowables


def _t(value) -> str:
    """
    reportlab's Paragraph uses a small XML parser, so raw agent-written text
    (which can contain &, <, > or stray characters) must be escaped before
    it's passed in - otherwise it can silently mis-render or overlap.
    """
    return xml_escape(str(value if value is not None else ""))


def _styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SmallGray", fontSize=9, textColor=colors.grey))
    styles.add(ParagraphStyle(name="CellText", fontSize=8, leading=10))
    return styles


# Usable width on a letter page with reportlab's default 1in margins on
# each side: 612pt - 72pt - 72pt = 468pt. Every table's colWidths below is
# sized to sum to <= this, and long free-text columns are wrapped in
# Paragraph flowables (not plain strings) so they wrap onto multiple lines
# INSIDE the cell instead of forcing the table wider than the page - that
# was what was cutting the accommodation/flight tables off at the page edge.
PAGE_USABLE_WIDTH = 468


def _cell(value, styles) -> Paragraph:
    """Wrap a value as a wrapping Paragraph cell (escaped for reportlab's XML parser)."""
    return Paragraph(_t(value), styles["CellText"])


def _table(rows, style, col_widths=None):
    return Table(rows, colWidths=col_widths, style=TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2A44")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))


def build_pdf(trip_id: int, candidates: list, chosen_destination: str, final_plan: dict) -> str:
    """
    candidates: list of dicts like {"candidate": {...}, "plan": {...}} (Phase 1+2 results)
    final_plan: the FullPlan dict for the chosen (possibly refined) destination
    Returns the path to the generated PDF.
    """
    styles = _styles()
    path = OUTPUT_DIR / f"trip_{trip_id}.pdf"
    doc = SimpleDocTemplate(str(path), pagesize=letter)
    story = []

    story.append(Paragraph("Kitesurfing Vacation Plan", styles["Title"]))
    story.append(Paragraph(f"Chosen destination: {_t(chosen_destination)}", styles["Heading2"]))
    story.append(Spacer(1, 12))

    # --- Chosen destination's full plan, in the requested order:
    # Budget -> 5-year wind history -> flights -> accommodation -> car
    # rental -> day-by-day itinerary. Candidates considered (the other 2)
    # move to the end of the document.
    currency = final_plan.get("currency", "")

    story.append(Paragraph("Budget", styles["Heading2"]))
    budget_rows = [
        ["Standard fare flight", f"{final_plan.get('standard_flight_price', 0):.0f} {currency}"],
        ["Flex fare flight", f"{final_plan.get('flex_flight_price', 0):.0f} {currency}"],
        ["Accommodation", f"{final_plan.get('accommodation_price', 0):.0f} {currency}"],
        ["Car rental", f"{final_plan.get('car_rental_price', 0):.0f} {currency}"],
        ["Other expenses", f"{final_plan.get('other_expenses_price', 0):.0f} {currency}"],
        ["Total (standard fare)", f"{final_plan.get('total_cost_standard_fare', 0):.0f} {currency}"],
        ["Total (flex fare)", f"{final_plan.get('total_cost_flex_fare', 0):.0f} {currency}"],
    ]
    story.append(_table([["Item", "Price"]] + budget_rows, styles, col_widths=[228, 240]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(_t(final_plan.get("cost_breakdown", "")), styles["Normal"]))
    story.append(Spacer(1, 12))

    chosen_candidate = next(
        (e["candidate"] for e in candidates if e["candidate"]["name"] == chosen_destination), None
    )
    if chosen_candidate and chosen_candidate.get("wind_heatmap"):
        story.extend(_wind_heatmap_flowables(chosen_candidate["wind_heatmap"], styles))
    else:
        story.append(Paragraph("5-year hourly wind history (knots)", styles["Heading3"]))
        story.append(Paragraph(
            _t((chosen_candidate or {}).get("wind_summary") or "No historical wind data available for this destination."),
            styles["SmallGray"],
        ))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Flight options", styles["Heading2"]))
    flight_rows = [["Fare type", "Price", "Airline", "Notes"]]
    for f in final_plan.get("flight_options", []):
        flight_rows.append([
            _cell(f["fare_type"], styles), _cell(f"{f['price']} {f['currency']}", styles),
            _cell(f["airline"], styles), _cell(f["notes"], styles),
        ])
    story.append(_table(flight_rows, styles, col_widths=[55, 65, 100, 248]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Accommodation options", styles["Heading2"]))
    acc_rows = [["Name", "Type", "Price/night", "Distance", "Rating"]]
    for a in final_plan.get("accommodation_options", []):
        acc_rows.append([
            _cell(a["name"], styles), _cell(a["type"], styles), _cell(f"{a['price_per_night']} {a['currency']}", styles),
            _cell(a["distance_to_spot"], styles), _cell(a.get("rating", ""), styles),
        ])
    story.append(_table(acc_rows, styles, col_widths=[90, 55, 65, 190, 68]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Car rental options", styles["Heading2"]))
    car_rows = [["Company", "Car type", "Price/day"]]
    for car in final_plan.get("car_rental_options", []):
        car_rows.append([_cell(car["company"], styles), _cell(car["car_type"], styles), _cell(f"{car['price_per_day']} {car['currency']}", styles)])
    story.append(_table(car_rows, styles, col_widths=[200, 150, 118]))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Day-by-day itinerary", styles["Heading2"]))
    itinerary_days = final_plan.get("itinerary") or []
    if itinerary_days:
        for day in itinerary_days:
            story.append(Paragraph(f"Day {_t(day['day'])}: {_t(day['description'])}", styles["Normal"]))
    else:
        story.append(Paragraph("No itinerary available for this plan.", styles["Normal"]))

    # --- Other candidates considered, moved to the end ---
    story.append(PageBreak())
    story.append(Paragraph("Other candidates considered", styles["Heading1"]))
    for entry in candidates:
        c = entry["candidate"]
        if c["name"] == chosen_destination:
            continue
        country = f", {c['country']}" if c.get("country") else ""
        story.append(Paragraph(f"{_t(c['name'])}{_t(country)} — score {c['score']['total']}/22", styles["Heading3"]))
        story.append(Paragraph(_t(c["rationale"]), styles["Normal"]))
        story.append(Paragraph(_t(c["wind_summary"]), styles["SmallGray"]))
        if c.get("wind_heatmap"):
            story.extend(_wind_heatmap_flowables(c["wind_heatmap"], styles))
        story.append(Spacer(1, 8))

    doc.build(story)
    return str(path)
