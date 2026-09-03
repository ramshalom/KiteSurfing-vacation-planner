"""
airports.py

A small reference list of airports (IATA code + city) for the departure
city dropdown. Not exhaustive - covers common departure points and popular
kitesurfing-adjacent hubs. Displayed as "City (CODE)", default is TLV.
"""

AIRPORTS = [
    ("TLV", "Tel Aviv"),
    ("LCA", "Larnaca"),
    ("ATH", "Athens"),
    ("IST", "Istanbul"),
    ("CAI", "Cairo"),
    ("DXB", "Dubai"),
    ("LHR", "London"),
    ("CDG", "Paris"),
    ("AMS", "Amsterdam"),
    ("FRA", "Frankfurt"),
    ("MAD", "Madrid"),
    ("BCN", "Barcelona"),
    ("LIS", "Lisbon"),
    ("FCO", "Rome"),
    ("MXP", "Milan"),
    ("ZRH", "Zurich"),
    ("VIE", "Vienna"),
    ("MUC", "Munich"),
    ("JFK", "New York"),
    ("MIA", "Miami"),
    ("LAX", "Los Angeles"),
    ("YYZ", "Toronto"),
    ("GRU", "Sao Paulo"),
    ("CPT", "Cape Town"),
    ("SIN", "Singapore"),
    ("BKK", "Bangkok"),
    ("HKT", "Phuket"),
    ("DPS", "Bali (Denpasar)"),
    ("SSH", "Sharm El Sheikh"),
    ("HRG", "Hurghada"),
    ("RAK", "Marrakesh"),
    ("AGA", "Agadir"),
]


def airport_label(code: str, city: str) -> str:
    return f"{city} ({code})"


def airport_options() -> list[str]:
    return [airport_label(code, city) for code, city in AIRPORTS]


def code_from_label(label: str) -> str:
    """Extract the IATA code from a 'City (CODE)' label."""
    return label.rsplit("(", 1)[-1].rstrip(")")
