# Wellness Tracker

A self-hosted web application for tracking personal health metrics (weight, blood pressure, etc.) over time. It provides data entry, trend visualization with exponential moving averages, and statistical summaries with a bilingual (English/Chinese) UI.

Built with Flask, SQLite, Chart.js, and W3.CSS. Served via Waitress.

## Authentication

This application does not handle authentication itself. If deployed behind a reverse proxy (e.g., Nginx, Caddy) that forwards the username via HTTP Basic Auth headers, the app will use that username. If no auth headers are present, it falls back to the `default_user` value from `settings.json` (or `"default"` if unset). This means it works out of the box for local use without any proxy.

## Setup

Install dependencies with `pip install -r requirements.txt`. Create a `settings.json` in the project root to configure the app (host, port, CDN address, users, trackable items, etc.). See `src/plugins_router_sample.py` for how to wire up plugins. Run with `cd src && python app.py`.

Data is stored in a `database.sqlite` file created automatically in the project root on first run.
