"""
models.py

Pydantic data models shared across the app. Using structured output_pydantic
on CrewAI Tasks means each agent's final answer comes back as one of these
objects (not just raw text), so the Streamlit UI can render clean cards/
tables instead of parsing free-form markdown.
"""

from typing import Any, Dict, List
from pydantic import BaseModel, Field


class ScoreBreakdown(BaseModel):
    wind_reliability: int = Field(default=0, description="0-5 points")
    travel_accessibility: int = Field(default=0, description="0-4 points")
    budget_feasibility: int = Field(default=0, description="0-4 points")
    night_life_match: int = Field(default=0, description="0-3 points")
    skill_level_match: int = Field(default=0, description="0-2 points")
    surf_type_match: int = Field(default=0, description="0-2 points")
    region_match: int = Field(default=0, description="0-2 points")
    total: int = Field(default=0, description="Sum of all criteria, max 22")


class YearlyWind(BaseModel):
    year: int = Field(default=0)
    avg_wind_min_knots: float = Field(default=0.0, description="Average of each day's minimum wind speed that year")
    avg_wind_max_knots: float = Field(default=0.0, description="Average of each day's maximum wind speed that year")
    kitesurfable_days: int = Field(default=0, description="Days meeting the kitesurfable wind threshold")
    total_days: int = Field(default=0, description="Total days in the travel window that year")


class Candidate(BaseModel):
    name: str = Field(description="Destination name, e.g. 'Dakhla, Morocco'")
    country: str = Field(default="")
    rationale: str = Field(default="", description="Short explanation of why this candidate fits")
    score: ScoreBreakdown = Field(default_factory=ScoreBreakdown)
    wind_summary: str = Field(default="", description="One-line summary of 5-year historical wind reliability")
    wind_history: List[YearlyWind] = Field(
        default_factory=list,
        description="Year-by-year breakdown, one row per of the last 5 years - computed directly from real data, not LLM-written",
    )
    wind_heatmap: Dict[str, Any] = Field(
        default_factory=dict,
        description="year (as string) -> {'avg_min': {'09:00': knots, ...}, 'avg_max': {...}} - hour-by-hour, computed directly from real data",
    )
    photo_urls: List[str] = Field(default_factory=list)


class CandidateList(BaseModel):
    candidates: List[Candidate]


class CandidateScore(BaseModel):
    name: str = Field(description="Must exactly match the candidate's name")
    score: ScoreBreakdown = Field(default_factory=ScoreBreakdown)


class CandidateScoreList(BaseModel):
    scores: List[CandidateScore]


class FlightOption(BaseModel):
    fare_type: str = Field(default="standard", description="'standard' or 'flex'")
    price: float = Field(default=0.0)
    currency: str = Field(default="USD")
    airline: str = Field(default="")
    notes: str = Field(default="", description="Include kitesurfing gear baggage fee details here")


class AccommodationOption(BaseModel):
    name: str = Field(default="")
    type: str = Field(default="", description="Double room / Single room / Villa / Apartment")
    price_per_night: float = Field(default=0.0)
    currency: str = Field(default="USD")
    distance_to_spot: str = Field(default="")
    amenities: str = Field(default="")
    rating: str = Field(default="", description="e.g. '4.5 stars (320 reviews)', if found")
    photo_urls: List[str] = Field(default_factory=list)
    source_url: str = Field(default="", description="Link to the hotel's OWN OFFICIAL website (not a booking aggregator or review site), if found")


class CarRentalOption(BaseModel):
    company: str = Field(default="")
    car_type: str = Field(default="")
    price_per_day: float = Field(default=0.0)
    currency: str = Field(default="USD")


# Thin "list" wrappers so each research task (accommodation/travel/car) can
# have its OWN output_pydantic and return reliable structured data directly.
# The Budget & Itinerary Planner is still asked to carry these lists over
# into its own FullPlan JSON for its own reasoning, but crew.py overrides
# plan.accommodation_options / flight_options / car_rental_options with these
# tasks' own outputs afterward - re-serializing lists through a second LLM
# call (budget_task) was silently dropping or zeroing values.
class AccommodationOptionList(BaseModel):
    options: List[AccommodationOption] = Field(default_factory=list)


class FlightOptionList(BaseModel):
    options: List[FlightOption] = Field(default_factory=list)


class CarRentalOptionList(BaseModel):
    options: List[CarRentalOption] = Field(default_factory=list)


class DayPlan(BaseModel):
    day: int = Field(default=0)
    description: str = Field(default="")


class FullPlan(BaseModel):
    destination: str = Field(default="")
    itinerary: List[DayPlan] = Field(default_factory=list)
    accommodation_options: List[AccommodationOption] = Field(default_factory=list)
    flight_options: List[FlightOption] = Field(default_factory=list)
    car_rental_options: List[CarRentalOption] = Field(default_factory=list)
    flights_and_hotel_standard: float = Field(
        default=0.0, description="Flights + hotel only (standard fare) - this is what the traveler's budget input is measured against"
    )
    flights_and_hotel_flex: float = Field(
        default=0.0, description="Flights + hotel only (flex fare) - this is what the traveler's budget input is measured against"
    )
    total_cost_standard_fare: float = Field(default=0.0, description="Full trip: flights + hotel + car rental + other expenses (standard fare)")
    total_cost_flex_fare: float = Field(default=0.0, description="Full trip: flights + hotel + car rental + other expenses (flex fare)")

    # Itemized line items feeding into the totals above (computed deterministically, not LLM arithmetic)
    standard_flight_price: float = Field(default=0.0)
    flex_flight_price: float = Field(default=0.0)
    accommodation_price: float = Field(default=0.0, description="Hotel cost for the full stay (cheapest option x nights)")
    car_rental_price: float = Field(default=0.0, description="Car rental cost for the full stay (cheapest option x days)")
    other_expenses_price: float = Field(default=0.0, description="Food/misc flat estimate for the trip")

    currency: str = Field(default="USD")
    cost_breakdown: str = Field(default="", description="Readable text explaining what's included (not the totals themselves)")
