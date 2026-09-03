"""
Throwaway Streamlit page to run fetch_wind_data() the same way app.py itself
launches (via `uv run streamlit run ...`), since direct `python.exe`
invocation is blocked by an Application Control policy on this machine.

Run with:
    uv run streamlit run test_wind_st.py

Then copy the JSON shown on the page back into the chat.
"""

import json

import streamlit as st

from tools import fetch_wind_data

st.title("Wind data test - Mui Ne, Vietnam (Jan 14-27)")

with st.spinner("Fetching 5 years of Open-Meteo data..."):
    result = fetch_wind_data("Mui Ne, Vietnam", "01-14", "01-27")

st.code(json.dumps(result, indent=2), language="json")
