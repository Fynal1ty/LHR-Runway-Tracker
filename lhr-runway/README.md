# Heathrow runway tracker

Free, serverless, no API keys. A GitHub Action runs `tracker.py` every ~5 minutes and publishes `status.json` plus the dashboard to GitHub Pages.

## Setup
1. Create a public GitHub repo and push this folder to it.
2. Settings > Actions > General > Workflow permissions: Read and write.
3. Actions tab > "update" > Run workflow (first run creates the `gh-pages` branch).
4. Settings > Pages > Source: Deploy from branch `gh-pages` / root.
5. Your dashboard is at `https://<user>.github.io/<repo>/`.

## How it decides
1. Live ADS-B (adsb.lol, airplanes.live fallback): low, descending aircraft on the approach side are landings; low, climbing aircraft on the exit side are departures. North or south of the runway midline picks the runway. Votes over the last 15 minutes, minimum 3 aircraft.
2. Wind (EGLL METAR) is used only when there is no traffic to read the direction from.
3. Fallback rule: westerly runways swap at 15:00 and the order flips weekly. The weekly anchor re-calibrates itself whenever live departures contradict it.
4. Quiet hours (23:30 to 06:00): shows the last confirmed pattern unless aircraft are seen.
5. If the data goes stale (over 20 minutes), the page computes the rule-based prediction itself, so it still gives an answer.

## To check
- Thresholds (lat/lon windows, altitudes) are approximate. Compare against FlightRadar24 for a few days and tune `events()`.
- The easterly assumption (land 09L, depart 09R) is unverified; live traffic overrides it.
- GitHub can pause scheduled workflows on inactive repos; if the page says data is stale, re-run the workflow.
