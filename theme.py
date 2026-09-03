import base64
import html
from pathlib import Path

import streamlit as st

# ---------------------------------------------------------------------------
# Visual identity - v2
#
# v1 used a dark navy hero (full-bleed photo with a dark scrim, then a
# navy/photo split panel) - too moody. v2 moved to a full-bleed bright photo
# with a cream "postcard" card - better, but the cream read as disconnected/
# beige next to the photo's vivid blues. 3 card options were tried head to
# head (deep teal + gold accent, plain white, frosted glass) - frosted glass
# won: a translucent blurred white panel that lets the photo's color show
# through instead of sitting on top of it as a separate colored block.
#
#   ink    #123B47  deep teal-ink - body text on light surfaces
#   cream  #FDF6EC  warm sand-white - page ground, stat chips
#   card   rgba(255,255,255,0.72) + blur - hero card background (frosted
#          glass over the photo, not a flat color - see .kvp-hero__card)
#   coral  #FF6B47  kite-sail orange - primary accent / CTA
#   teal   #14B8A6  lagoon water - secondary accent
#   gold   #FFB833  sunshine - sparing highlight use
#   line   #E9DFC9  warm sand-grey - borders on light surfaces
#
# Type unchanged: Bricolage Grotesque (display) + Manrope (body/UI) +
# IBM Plex Mono (numerals).
#
# Hero photo: assets/hero_kites.jpg - Rami's own pick: two riders on a
# turquoise lagoon, yellow and blue/pink kites, a small palm island and a
# sailboat on the horizon. Already landscape (~1.8:1) and well-balanced
# left-to-right, so it drops straight into the hero with no custom crop.
# ---------------------------------------------------------------------------

_ASSETS_DIR = Path(__file__).parent / "assets"
HERO_PHOTO_FILE = "hero_kites.jpg"


def _image_data_uri(filename: str) -> str:
    path = _ASSETS_DIR / filename
    data = base64.b64encode(path.read_bytes()).decode()
    ext = path.suffix.lstrip(".").lower()
    mime = "jpeg" if ext in ("jpg", "jpeg") else ext
    return f"data:image/{mime};base64,{data}"


HERO_PHOTO_URI = _image_data_uri(HERO_PHOTO_FILE)

THEME_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,400..800&family=Manrope:wght@400..800&family=IBM+Plex+Mono:wght@500;600&display=swap');

:root {
    --kvp-ink: #123B47;
    --kvp-cream: #FDF6EC;
    --kvp-coral: #FF6B47;
    --kvp-teal: #14B8A6;
    --kvp-gold: #FFB833;
    --kvp-line: #E9DFC9;
}

.stApp {
    background-color: #FBF9F4;
}
/* Cap content width. Streamlit's "wide" layout stretches the block
   container to the full browser width - on a large monitor that meant the
   hero photo (native ~1056px) was being upscaled 1.7-1.8x, which is what
   was making it look soft, and the page read as a thin strip of content
   floating at the top of a mostly-empty screen. Capping and centering it
   keeps the wide layout's benefit for the 3-way compare screen while
   stopping the hero from being stretched past its own resolution. */
.stApp .block-container {
    max-width: 1200px;
    margin-left: auto;
    margin-right: auto;
}
.stApp, .stApp p, .stApp li, .stApp label {
    font-family: 'Manrope', 'Segoe UI', sans-serif;
}
/* Deliberately NOT touching span here - Streamlit renders icons (the
   expander chevron, alert icons, etc.) as ligature text inside <span>,
   e.g. literal text "arrow_right" that a dedicated icon font turns into a
   glyph. ".stApp span { font-family: Manrope }" out-specifies that icon
   font's own rule and forces the ligature text to render as literal
   readable text instead of an icon - that's what caused the garbled
   "arrow_right" text overlapping "Score breakdown" on the compare screen.
   .stApp already sets font-family and every span inherits it normally;
   only an *explicit* span rule was the problem. */
.stApp h1, .stApp h2, .stApp h3 {
    font-family: 'Bricolage Grotesque', 'Manrope', sans-serif;
    font-weight: 700;
    letter-spacing: -0.01em;
    color: var(--kvp-ink);
}
.stApp code, .stApp [data-testid="stMetricValue"], .stApp [data-testid="stMetricDelta"] {
    font-family: 'IBM Plex Mono', ui-monospace, monospace;
}

/* --- Hero: full-bleed bright photo, no dark tint, cream card floats over it --- */
.kvp-hero {
    position: relative;
    overflow: hidden;
    border-radius: 24px;
    margin-bottom: 1.9rem;
    min-height: 460px;
    background-image:
        linear-gradient(0deg, rgba(18,59,71,0.10) 0%, rgba(18,59,71,0) 30%),
        url("__HERO_PHOTO_URI__");
    background-size: cover;
    background-position: center;
}
.kvp-hero__topbar {
    display: flex;
    align-items: center;
    gap: 0.7rem;
    padding: 1.7rem 2rem 0;
}
.kvp-hero__eyebrow {
    font-family: 'IBM Plex Mono', ui-monospace, monospace;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--kvp-cream);
    text-shadow: 0 1px 6px rgba(18,59,71,0.6);
}
.kvp-hero__card {
    position: absolute;
    left: 2rem;
    bottom: 2rem;
    max-width: 460px;
    background: rgba(255,255,255,0.72);
    backdrop-filter: blur(14px);
    -webkit-backdrop-filter: blur(14px);
    border-radius: 18px;
    border: 1px solid rgba(255,255,255,0.5);
    padding: 1.9rem 2.1rem 1.7rem;
    box-shadow: 0 18px 40px rgba(10,37,55,0.25);
}
.stApp h1.kvp-hero__title {
    font-family: 'Bricolage Grotesque', sans-serif;
    font-weight: 700;
    font-size: clamp(1.6rem, 2.6vw, 2.1rem);
    line-height: 1.12;
    letter-spacing: -0.015em;
    margin: 0 0 0.6rem 0;
    color: #0B2E3D;
    text-wrap: balance;
}
.kvp-hero__sub {
    font-family: 'Manrope', sans-serif;
    font-size: 0.98rem;
    font-weight: 400;
    line-height: 1.5;
    color: #0B2E3D;
    opacity: 0.85;
    margin: 0;
    max-width: 46ch;
}
.kvp-stats {
    display: flex;
    flex-wrap: wrap;
    gap: 0.7rem;
    margin-top: 1.7rem;
}
.kvp-stat {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    padding: 0.7rem 1.1rem;
    border-radius: 12px;
    background: var(--kvp-cream);
    border: 1px solid var(--kvp-line);
    min-width: 168px;
}
.kvp-stat__num {
    font-family: 'IBM Plex Mono', ui-monospace, monospace;
    font-weight: 600;
    font-size: 1.02rem;
    color: var(--kvp-teal);
}
.kvp-stat__label {
    font-size: 0.78rem;
    color: var(--kvp-ink);
    opacity: 0.72;
}

/* --- Sub-hero: compact themed banner for the trip-details form page.
   Same photo as the landing hero (zoomed in, kept short) so the branding
   carries over instead of dropping to a plain black Streamlit title -
   Rami's note was "no clue we're dealing with kitesurfing" on this page. --- */
.kvp-subhero {
    display: flex;
    align-items: center;
    gap: 1rem;
    border-radius: 18px;
    padding: 1.9rem 2rem;
    margin-bottom: 1.7rem;
    min-height: 108px;
    background-image:
        linear-gradient(100deg, rgba(11,46,61,0.95) 0%, rgba(11,46,61,0.95) 46%, rgba(11,46,61,0.55) 78%, rgba(11,46,61,0.25) 100%),
        url("__HERO_PHOTO_URI__");
    background-size: cover;
    background-position: center 30%;
}
.kvp-subhero__text { display: flex; flex-direction: column; gap: 0.15rem; }
.stApp h1.kvp-subhero__title {
    font-family: 'Bricolage Grotesque', sans-serif;
    font-weight: 700;
    font-size: 1.5rem;
    color: #FFFFFF;
    margin: 0;
}
.kvp-subhero__sub {
    font-family: 'Manrope', sans-serif;
    font-size: 0.92rem;
    color: #D7ECEA;
    opacity: 0.95;
    margin: 0;
}

/* --- Buttons --- */
.stApp .stButton > button, .stApp [data-testid="stFormSubmitButton"] button {
    background: var(--kvp-coral);
    color: #FFFFFF;
    border: none;
    border-radius: 10px;
    font-weight: 600;
    padding: 0.55rem 1.3rem;
    transition: transform 0.12s ease, box-shadow 0.12s ease;
}
.stApp .stButton > button:hover, .stApp [data-testid="stFormSubmitButton"] button:hover {
    background: #E85A38;
    box-shadow: 0 4px 14px rgba(255,107,71,0.28);
}
.stApp .stDownloadButton > button {
    background: var(--kvp-teal);
    color: #FFFFFF;
    border: none;
    border-radius: 10px;
    font-weight: 600;
}

/* --- Tabs --- */
.stApp .stTabs [data-baseweb="tab"] {
    font-family: 'Bricolage Grotesque', sans-serif;
    font-weight: 600;
    color: var(--kvp-ink);
    opacity: 0.55;
}
.stApp .stTabs [aria-selected="true"] {
    color: var(--kvp-coral) !important;
    opacity: 1;
}
.stApp .stTabs [data-baseweb="tab-highlight"] {
    background-color: var(--kvp-coral) !important;
}

/* --- Metrics --- */
.stApp [data-testid="stMetric"] {
    background: var(--kvp-cream);
    border: 1px solid var(--kvp-line);
    border-radius: 12px;
    padding: 0.8rem 1rem;
}
.stApp [data-testid="stMetricLabel"] {
    color: var(--kvp-ink);
    opacity: 0.7;
}
.stApp [data-testid="stMetricValue"] {
    color: var(--kvp-teal);
}

hr {
    border-color: var(--kvp-line) !important;
}
</style>
""".replace("__HERO_PHOTO_URI__", HERO_PHOTO_URI)

KITE_MARK_SVG = """
<svg width="38" height="38" viewBox="0 0 44 44" fill="none" xmlns="http://www.w3.org/2000/svg">
  <path d="M3 13C9 13 9 7 15 7C21 7 21 13 27 13" stroke="#FFB833" stroke-width="2" stroke-linecap="round" opacity="0.9"/>
  <path d="M1 21C9 21 9 14 19 14C29 14 29 21 39 21" stroke="#14B8A6" stroke-width="2.5" stroke-linecap="round" opacity="0.95"/>
  <path d="M5 29C13 29 13 23 21 23" stroke="#FF6B47" stroke-width="2" stroke-linecap="round" opacity="0.85"/>
  <path d="M22 6L34 22L22 38L14 22Z" fill="#FF6B47" stroke="#FDF6EC" stroke-width="1.4" stroke-linejoin="round"/>
  <line x1="22" y1="24" x2="22" y2="43" stroke="#FDF6EC" stroke-width="1" opacity="0.6"/>
</svg>
"""


def _flatten_html(html: str) -> str:
    """Streamlit's markdown renderer treats a blank line inside otherwise-raw
    HTML as the end of the HTML block; normal Markdown parsing then resumes,
    and any indented lines after that (inevitable with Python's own
    indentation) get read as a Markdown code block and shown as literal text
    instead of being rendered. That's what broke the hero: KITE_MARK_SVG has
    a leading/trailing blank line, which reset parsing right after the icon
    and dumped everything past it as visible code. Collapsing to one line
    with no blank lines or leading whitespace sidesteps this regardless of
    how the source is indented.
    """
    return " ".join(line.strip() for line in html.strip().splitlines() if line.strip())


def render_hero():
    """Landing hero for the New Plan form - the app's one true 'landing' moment.
    Downstream screens (compare/refine) intentionally stay quiet; they're
    working screens, not landing moments, and inherit the theme via THEME_CSS.
    """
    html = f"""
        <div class="kvp-hero">
            <div class="kvp-hero__topbar">
                {KITE_MARK_SVG}
                <span class="kvp-hero__eyebrow">Kitesurfing Vacation Planner</span>
            </div>
            <div class="kvp-hero__card">
                <h1 class="kvp-hero__title">Chase the wind to the edge of the map.</h1>
                <p class="kvp-hero__sub">
                    Six specialist agents research, cost, and score three real kite spots in
                    parallel — five years of real hourly wind data, not vibes.
                </p>
            </div>
        </div>
        <div class="kvp-stats">
            <div class="kvp-stat">
                <span class="kvp-stat__num">3 spots</span>
                <span class="kvp-stat__label">researched &amp; costed in parallel</span>
            </div>
            <div class="kvp-stat">
                <span class="kvp-stat__num">22-pt rubric</span>
                <span class="kvp-stat__label">wind, budget, skill &amp; style scored</span>
            </div>
            <div class="kvp-stat">
                <span class="kvp-stat__num">5-yr wind history</span>
                <span class="kvp-stat__label">real hourly data, not estimates</span>
            </div>
        </div>
        """
    st.markdown(_flatten_html(html), unsafe_allow_html=True)


def render_page_banner(title: str, subtitle: str = ""):
    """Compact themed banner reused on every non-landing screen (trip form,
    compare, refine) - carries the kitesurfing branding through the whole
    flow instead of it only showing up on the landing page. title/subtitle
    are HTML-escaped since compare/refine pass in LLM-generated destination
    names, which could otherwise contain characters that break the markup.
    """
    safe_title = html.escape(title)
    sub_html = f'<p class="kvp-subhero__sub">{html.escape(subtitle)}</p>' if subtitle else ""
    page_html = f"""
        <div class="kvp-subhero">
            {KITE_MARK_SVG}
            <div class="kvp-subhero__text">
                <h1 class="kvp-subhero__title">{safe_title}</h1>
                {sub_html}
            </div>
        </div>
        """
    st.markdown(_flatten_html(page_html), unsafe_allow_html=True)


def render_form_header():
    """Trip-details form page banner."""
    render_page_banner(
        "Tell us about your trip",
        "A manager agent orchestrates 6 specialist agents to build 3 fully-costed vacation options.",
    )
