# Property Advisor

A multi-agent property recommendation system built on **IBM watsonx Orchestrate**. Takes a buyer's free-text request and returns a ranked shortlist of live Singapore property listings with price fairness analysis and nearby amenity data — not just a filtered list.

> **Example:** *"4-room flat near Bishan MRT under $850k"* → 3 ranked listings, each with a valuation verdict, MRT distance, nearby schools and hawker centres, and a direct link to the 99.co listing.

---

## Features

- **Natural language search** — describe what you want in plain English, including flat type, town, budget, floor level, and amenity preferences
- **Live property listings** — fetches real HDB resale flats, condos, executive condos, and landed homes from 99.co via RapidAPI
- **Price fairness valuation** — compares each listing's asking price against the last 5 years of HDB resale transactions from data.gov.sg; returns a verdict of fairly priced, overpriced, or underpriced with a % premium/discount
- **Floor-level aware search** — finds listings on the requested floor tier (low/mid/high) and adjusts the valuation comparison to same-floor comparable transactions
- **Nearby amenities** — geocodes each listing and finds nearby MRT stations, schools, hawker centres, convenience stores, shopping malls, and places of worship via Google Places API
- **Live thinking panel** — shows real-time progress as each agent runs (listings → valuation → geospatial), collapses to a "Thought for Ns" summary after the response
- **Multi-turn conversation** — follow-up questions continue the same conversation thread
- **Offline demo mode** — `USE_FIXTURES=true` runs entirely on sample data with no API keys needed

---

## Architecture

```
User (React chat UI)
    │
    ▼
FastAPI backend  →  POST /chat/message
    │
    ▼
Supervisor Agent  (IBM watsonx Orchestrate — ReAct)
    │
    ├──► Listing Agent      →  POST /tools/listings    →  99.co API (live listings)
    ├──► Valuation Agent    →  POST /tools/valuation   →  data.gov.sg (HDB transactions)
    └──► Geospatial Agent   →  POST /tools/geospatial  →  Google Places + Geocoding API
```

The backend exposes the tool endpoints as an OpenAPI spec imported into watsonx Orchestrate. The frontend never calls Orchestrate directly — the backend proxies all chat requests server-side to keep the WXO API key out of the browser.

---

## Prerequisites

### Accounts and API keys required

| Service | Purpose | Free tier |
|---|---|---|
| [RapidAPI](https://rapidapi.com) — subscribe to `99-co-sg-api` (provider: Happy Endpoint) | Live property listings | 500 requests/month |
| [Google Cloud](https://console.cloud.google.com) — enable Places API (New) + Geocoding API | Amenity lookup + geocoding | ~10,000 requests/month |
| [IBM watsonx Orchestrate](https://www.ibm.com/products/watsonx-orchestrate) — SaaS or TechZone instance | Multi-agent orchestration | TechZone trial available |
| [IBM Cloud IAM](https://cloud.ibm.com/iam/apikeys) — API key for your WXO instance | Backend auth to WXO | Included with WXO |

> **Note:** Google Cloud requires billing to be enabled even for free-tier usage. RapidAPI requires subscribing to the Basic (free) plan for the 99.co API.

### Local tools required

- **Docker** — runs the whole stack (Postgres, backend, frontend). If you'd rather run backend/frontend natively, you'll also need:
  - **Python 3.11+**
  - **Node.js 18+**
- **watsonx Orchestrate ADK CLI** — `pip install ibm-watsonx-orchestrate` — for importing agents and tools

---

## Quick start with Docker

The full stack — Postgres, FastAPI backend, React frontend — runs as three Docker Compose services, no local Python/Node install required.

```bash
git clone <repo-url>
cd project-property-recommendation

cp backend/.env.example backend/.env      # optional — fill in API keys, or leave USE_FIXTURES=true
cp frontend/.env.example frontend/.env    # optional — defaults already match the Docker port mapping

docker compose up --build
```

Open **http://localhost:5173**. The backend is reachable at **http://localhost:8001** (used for `ngrok http 8001` in [step 4](#4-import-agents-and-tools-into-watsonx-orchestrate) below).

`docker compose up` auto-merges `docker-compose.override.yml`, which gives hot-reloading dev containers: backend source is mounted in with `uvicorn --reload`, and the frontend runs the Vite dev server instead of a static build — edit code on your host and both pick it up live.

For a production-style run instead (built static frontend served by nginx, backend without `--reload`, no source mounts):

```bash
docker compose -f docker-compose.yml up --build
```

To run only Postgres in Docker and everything else natively, see the manual setup below.

---

## Manual setup (run services natively)

Use this if you want to debug the backend/frontend directly on your host instead of in containers.

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd project-property-recommendation
```

**Backend:**
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Frontend:**
```bash
cd frontend
npm install
```

### 2. Start PostgreSQL

`docker-compose.yml` also defines `backend` and `frontend` services now (see [Quick start with Docker](#quick-start-with-docker) above) — to start Postgres only, name the service explicitly:

```bash
docker compose up -d postgres
```

This starts a PostgreSQL instance on port `5433` used for caching API responses.

### 3. Configure environment variables

**Backend:**
```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env` and fill in:

```env
RAPIDAPI_KEY=your_rapidapi_key_here
GOOGLE_MAPS_API_KEY=your_google_maps_api_key_here
WXO_INSTANCE_URL=https://api.au-syd.watson-orchestrate.cloud.ibm.com/instances/YOUR_INSTANCE_ID
WXO_API_KEY=your_wxo_api_key_here
USE_FIXTURES=false
```

> Set `USE_FIXTURES=true` to skip live API calls and use sample data instead — useful for offline demos.

**Frontend:**
```bash
cp frontend/.env.example frontend/.env
```

The default `VITE_API_BASE_URL=http://localhost:8001` works out of the box.

### 4. Import agents and tools into watsonx Orchestrate

First, expose your local backend publicly using [ngrok](https://ngrok.com):

```bash
ngrok http 8001
```

Copy the ngrok HTTPS URL (e.g. `https://abc123.ngrok-free.app`), then update the `servers` entry in `backend/openapi.json`:

```json
"servers": [{ "url": "https://abc123.ngrok-free.app" }]
```

Then import tools and agents:

```bash
orchestrate env activate <your-env-name>

orchestrate tools import -k openapi -f backend/openapi.json

orchestrate agents import -f agents/listing_agent.yaml
orchestrate agents import -f agents/valuation_agent.yaml
orchestrate agents import -f agents/geospatial_agent.yaml
orchestrate agents import -f agents/supervisor_agent.yaml
```

---

## Running the app

**Terminal 1 — Backend:**
```bash
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8001
```

**Terminal 2 — Frontend:**
```bash
cd frontend && npm run dev
```

Open **http://localhost:5173** in your browser.

---

## Running tests

```bash
cd backend
.venv/bin/pytest tests/ -v
```

All tests run in fixture mode (no live API calls, no external dependencies).

---

## Tech stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite |
| Backend | Python 3.11, FastAPI, SQLAlchemy |
| Database | PostgreSQL 16 (API response cache) |
| Agent runtime | IBM watsonx Orchestrate (ReAct supervisor + 3 collaborator agents) |
| LLM | `groq/openai/gpt-oss-120b` (via WXO) |
| Listings | 99.co API via RapidAPI |
| Valuation data | data.gov.sg HDB resale transactions |
| Amenities | Google Places API (New) + Geocoding API |
| Real-time events | Server-Sent Events (SSE) |
| Containerisation | Docker Compose (Postgres, backend, frontend; hot-reload dev override) |

---

## API endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/chat/message` | Send a message to the supervisor agent, returns the reply |
| `GET` | `/chat/events` | SSE stream of live tool-call progress events |
| `POST` | `/tools/listings` | Search live property listings (`searchListings` tool) |
| `POST` | `/tools/valuation` | Check price fairness against historical transactions (`checkValuation` tool) |
| `POST` | `/tools/geospatial` | Geocode an address and find nearby amenities (`lookupAmenities` tool) |
| `GET` | `/health` | Health check |
| `GET` | `/docs` | Interactive API documentation (Swagger UI) |
