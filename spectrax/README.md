# SpectraX — AI powered EV journeys
Run: `python server.py` → open http://127.0.0.1:8000 (no pip install). Put your NVIDIA and Tavily keys in the included `.env` (hidden file: Cmd+Shift+. in macOS Finder, 'Hidden items' on Windows) and restart, or paste them on the app's System tab (saved only to the local `.env`). Never commit `.env`.

**Flow:** enter From (◎ = my location) and To → route is set → pre-trip check (Open-Meteo weather, 4 Tavily searches, Nemotron briefing; needs the server and keys) → START TRIP → turn-by-turn screen.
- **Real data:** map tiles (Esri/OSM), places (Nominatim), roads and turns (OSRM public server), charger locations (OpenStreetMap/Overpass), weather (Open-Meteo, feeds the energy model), news search (Tavily), LLM replies (NVIDIA Nemotron).
- **Simulated:** battery, traffic, charger availability/price/reliability, reservations, collision. The trip is a simulated drive along the real route (not live GPS following). The Demo Sim panel is for demonstration only.
- **Agent:** server.py runs a bounded tool loop (get_route_weather, tavily_search, estimate_energy, find_chargers, update_journey_plan); plan changes are validated on the server and again in the browser.
- **Nebius:** the hackathon needs Nebius Token Factory — set LLM_BASE_URL, LLM_API_KEY, LLM_MODEL to the Nebius values.
- **Tests:** `python -m unittest discover -s tests`. **License:** not chosen yet (owner to pick an OSI license).
