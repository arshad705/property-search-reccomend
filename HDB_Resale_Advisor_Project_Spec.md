# HDB Resale Flat Advisor — Project Spec

## Overview

A multi-agent system built on IBM watsonx Orchestrate that takes a buyer's free-text housing request (e.g. "4-room flat near Bishan MRT under $850k") and returns a ranked shortlist of live HDB resale listings with reasoning attached — not just a filtered list.

The system combines live property listings, historical price benchmarking, and geospatial amenity data, reasoning across all three to help a buyer judge whether a listing is a good fit and fairly priced.

**Beyond the housing use case itself**, this project is a proof of concept for a "parse intent → retrieve from multiple sources → reason → explain" pattern, directly relevant to eligibility/compliance matching use cases pitched to government and bank clients in presales (IBM Data & AI team context).

---

## Agent Architecture

```
User (React chat UI)
    │  free-text message, e.g. "4-room flat near Bishan MRT under $850k"
    ▼
FastAPI  POST /chat/message
  - Resolves supervisor_agent's id by name (cached)
  - Creates a run via watsonx Orchestrate's REST API and polls for completion
  - Fetches the final assistant message from the thread and returns it
    (thread_id is round-tripped so follow-up messages continue the conversation)
    │
    ▼
Supervisor Agent  (watsonx Orchestrate, style: react)
  - Parses free-text request into structured filters
    (flat_type, town, max_price, preferences)
  - Delegates to 3 collaborator agents
  - Synthesizes their outputs into one ranked, explained recommendation
    │
    ├──► Listing Agent      → 99.co API        → live matching listings
    ├──► Valuation Agent    → data.gov.sg API  → historical price comparison
    └──► Geospatial Agent   → OneMap API       → nearby amenities & distances
```

**No vector database is required.** All three tools operate on structured, filterable data (numeric ranges, categories, coordinates) — no semantic/similarity search is needed anywhere in this pipeline.

**Why the backend sits between the chat UI and Orchestrate, rather than the frontend calling Orchestrate directly:** calling the `/v1/orchestrate/runs` REST API requires a bearer token minted from a WXO API key. That key must never reach the browser, so the FastAPI backend holds it (server-side `.env` only) and proxies chat messages through to Orchestrate on the frontend's behalf.

---

## Public APIs

| API | Purpose | Auth | Key details |
|---|---|---|---|
| **99.co API** (RapidAPI, provider: Happy Endpoint, slug `99-co-sg-api`) | Live property listings | RapidAPI key via `X-RapidAPI-Key` header | Free tier: 500 requests/month — cache responses in Postgres to conserve quota. Confirmed live against a real account: `/search-property` takes `listing_type` (required: `sale`/`rent`), `main_category` (`hdb`/`condo`/`landed`), `rooms` (bedroom range `"min,max"` — **not** the same as HDB flat_type nomenclature, see note below), `price_min`/`price_max`, `page_size`/`page_num`, and `query_ids` (a location id from `/autocomplete` — no confirmed way to scope to a specific town without that extra call, so we search island-wide (`query_ids=singapore`) and filter by town client-side instead). Response listings are nested at `data.results.listings`, with fields `id`, `address`, `price`, `beds`, `floorAreaSqft` (**sqft, not sqm**), `lat`/`lng`, `neighbourhood`, `region`, and a bonus `nearestMrt` object — no flat_type, storey/floor, or town field at all. |
| **data.gov.sg** | Historical HDB resale transaction data | None required | Dataset: "Resale flat prices based on registration date from Jan-2017 onwards", resource_id `d_8b84c4ee58e3cfc0ece0d773c8ca6abc`. Test with: `GET https://data.gov.sg/api/action/datastore_search?resource_id=d_8b84c4ee58e3cfc0ece0d773c8ca6abc&limit=5`. `town` values are always one of the 26 official HDB planning areas (e.g. `BISHAN`) — see note below on reconciling this with 99.co's finer-grained neighbourhoods. |
| **Google Maps Platform** (Places API New + Geocoding API) | Geocoding + nearby amenities (MRT stations, schools, hawker centres) | API key via `X-Goog-Api-Key` header (Places) / `key` query param (Geocoding) | **Replaced OneMap entirely** (OneMap's Themes catalog had no MRT/school data — only hawker centres). Requires a Google Cloud project with billing enabled — mandatory even for free-tier usage, no call succeeds without it. Geocoding: `GET https://maps.googleapis.com/maps/api/geocode/json?address=...&key=...`. Amenities: `POST https://places.googleapis.com/v1/places:searchNearby` with `X-Goog-FieldMask` restricted to Basic-tier fields (`places.displayName,places.location,places.types`) to stay in the cheaper/more generous free-quota SKU (10,000/mo Essentials for Geocoding; Places New Nearby Search free quota depends on which fields you request — Basic-only keeps cost down vs. requesting Pro-tier fields like ratings/hours). No Singapore-specific "MRT"/"hawker centre" place types exist — mapped to Google's generic `subway_station` (confirmed correct via live testing; `train_station` looked plausible but actually matched SMRT's corporate office, not a real station) and `food_court` respectively (the latter also catches individual stalls/mall food courts, not just distinct hawker centre buildings — a known imprecision). |

**Notes on reconciling data across sources (found while testing live mode, not just reading docs):**
- **HDB flat_type ↔ 99.co bedroom count**: 99.co has no flat_type concept, only a `rooms` (bedroom count) range filter. We map `"4-room"` → `rooms=3,3` etc. — an approximation, since HDB "X-room" counts all rooms (living/dining included), not just bedrooms. Worth spot-checking against real listings.
- **Town name mismatch between 99.co and data.gov.sg**: 99.co's `neighbourhood` field returns marketing-area names like `"Bishan East"`, while data.gov.sg's `town` field only uses the 26 official HDB planning areas (`"BISHAN"`). An exact-match filter silently returned zero comparable transactions for real listings until this was caught live — `valuation_service.py` now normalizes by checking which official HDB town name is *contained in* whatever town string it's given, rather than requiring an exact match.

---

## Environments Needed

- **RapidAPI account** — subscribed to 99.co API (slug: `99-co-sg-api`, provider: `happyendpoint`)
- **Google Cloud account with billing enabled** — a project with Places API (New) and Geocoding API enabled, plus an API key (see Public APIs section for the confirmed setup steps). Billing is mandatory even for free-tier usage.
- **watsonx Orchestrate** — using an existing **TechZone/SaaS environment** (not local Developer Edition, to avoid local container/VM setup overhead)
- **ADK CLI** — installed locally, pointed at the `techzone` (or equivalent SaaS) environment via `orchestrate env add` / `orchestrate env activate`
- **WXO API key** — the same key used for `orchestrate env activate <env>`; the backend's `/chat/message` endpoint needs it (as `WXO_API_KEY` in `backend/.env`, never committed) to authenticate its own calls to Orchestrate's REST API
- **PostgreSQL** — local instance for development (caching API responses, logging queries)
- **GitHub repository** — with Actions enabled for CI/CD
- **IBM Cloud account** — only required if pursuing full production deployment (Code Engine, Databases for PostgreSQL, Container Registry, Object Storage)

---

## Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Frontend | React (chat UI) | A single conversational view — message history + text input, no structured search form. Renders the agent's markdown replies (tables, bold, bullets) via `react-markdown` + `remark-gfm`. Calls the backend's `/chat/message` endpoint, not Orchestrate directly (see Agent Architecture note on why) |
| Backend | FastAPI | Two roles: (1) exposes `/tools/*` as REST endpoints with clear `operationId`/`description`, auto-generating the OpenAPI spec imported into Orchestrate as agent tools; (2) exposes `/chat/message`, which the frontend calls, and which itself calls Orchestrate's REST API server-side using `ibm-watsonx-orchestrate-clients` (`RunClient`, `ThreadsClient`, `AgentClient`) with IAM auth |
| Agent layer | watsonx Orchestrate ADK | 4 agent YAML definitions (1 supervisor + 3 collaborators), imported into the SaaS/TechZone environment |
| Tool integration | OpenAPI import (`orchestrate tools import -k openapi`) | Primary integration method. MCP is possible (remote or local-command based) but optional — adds no functional benefit for custom in-house tools like these; only worth it if demonstrating MCP specifically is a goal |
| Database | PostgreSQL (plain — no pgvector) | Caching layer for API responses + query logging. No vector extension needed since there's no semantic search in this architecture |
| CI/CD | GitHub Actions | Lint/test/build on every push; optional deploy workflow to IBM Cloud if pursuing full production deployment |
| Dev workflow | Claude / Claude Code | Coding, testing, and PR management (replacing IBM Bob) |

---

## Folder Structure

```
project-property-search/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app entry point
│   │   ├── config.py                # Env-var loading (pydantic-settings)
│   │   ├── database.py              # SQLAlchemy engine + session
│   │   ├── models.py                # ORM models (cache, query_log)
│   │   ├── routers/
│   │   │   ├── listings.py          # /tools/listings endpoint — also publishes live progress events (see event_bus.py)
│   │   │   ├── valuation.py         # /tools/valuation endpoint — same
│   │   │   ├── geospatial.py        # /tools/geospatial endpoint — same
│   │   │   ├── chat.py              # /chat/message endpoint (frontend-facing, excluded from the OpenAPI tool import)
│   │   │   └── events.py            # GET /chat/events — SSE relay of live tool-call progress (frontend-facing)
│   │   ├── services/
│   │   │   ├── listing_service.py    # 99.co API client
│   │   │   ├── valuation_service.py  # data.gov.sg API client
│   │   │   ├── geo_service.py        # Google Places (New) + Geocoding API client + Haversine
│   │   │   ├── orchestrate_service.py # Calls Orchestrate's REST API (RunClient/ThreadsClient/AgentClient) to run supervisor_agent
│   │   │   └── event_bus.py          # Single-process asyncio.Queue bridging /tools/* (sync) → /chat/events (async SSE)
│   │   └── schemas/
│   │       ├── listing.py
│   │       ├── valuation.py
│   │       ├── geospatial.py
│   │       └── chat.py
│   ├── tests/
│   │   ├── test_listings.py
│   │   ├── test_valuation.py
│   │   ├── test_geospatial.py
│   │   └── test_chat.py             # mocks orchestrate_service — no fixture path makes sense for a live-agent call
│   ├── fixtures/                    # Sample API responses for offline demo
│   ├── requirements.txt
│   ├── .env.example
│   └── Dockerfile
├── agents/
│   ├── supervisor_agent.yaml
│   ├── listing_agent.yaml
│   ├── valuation_agent.yaml
│   └── geospatial_agent.yaml
├── .github/
│   └── workflows/
│       ├── backend-ci.yml
│       └── frontend-ci.yml
├── frontend/
│   ├── src/
│   │   ├── App.tsx                  # renders ChatPage — single conversational view, no routing
│   │   ├── components/
│   │   │   ├── ChatMessageBubble.tsx # renders one message (markdown for assistant replies)
│   │   │   └── ThinkingPanel.tsx     # collapsible live/persisted tool-call trace, see Key Decisions
│   │   ├── pages/
│   │   │   └── ChatPage.tsx         # message history + input bar; owns thread_id + thinkingEvents state
│   │   ├── api/
│   │   │   └── client.ts            # sendChatMessage() → POST /chat/message; openChatEventStream() → GET /chat/events (SSE)
│   │   └── types/
│   │       └── index.ts             # ChatMessage (+ optional thinking trace), ChatApiResponse, ThinkingEvent
│   ├── package.json
│   └── .env.example
├── .gitignore
└── README.md
```

---

## FastAPI Endpoint Signatures

### `POST /tools/listings` — `searchListings`
**Request:**
```json
{
  "flat_type": "4-room",
  "town": "Bishan",
  "max_price": 850000,
  "min_floor_area_sqm": null
}
```
**Response:**
```json
{
  "listings": [
    {
      "listing_id": "string",
      "address": "string",
      "flat_type": "string",
      "asking_price": 820000,
      "floor_area_sqm": 93,
      "storey_range": "10 TO 12",
      "town": "Bishan",
      "coordinates": { "lat": 1.3501, "lng": 103.8480 },
      "nearest_mrt_name": "Bishan MRT",
      "nearest_mrt_distance_m": 420,
      "listing_url": "https://www.99.co/singapore/sale/property/{slug}-{id}?utm_medium=referral&utm_source=user&utm_campaign=ldp",
      "floor_level": "mid"
    }
  ],
  "source": "cache | live | fixture",
  "retrieved_at": "ISO-8601 timestamp"
}
```
*(Note: field names above are illustrative — confirm exact 99.co response schema from RapidAPI's interactive tester before finalizing.)*

**How `listing_url` is obtained:** neither `/search-property` nor `/listing-details` returns a listing URL or slug field (confirmed by inspecting both responses directly). A first attempt guessed the URL pattern from a public web search result (`/singapore/sale/hdb/{slug}-{id}`) — this was **confirmed wrong** by the user click-testing 3 generated links (all 404s), which is exactly the "never guess URLs" risk playing out in practice. The reliable fix: `/listing-details-by-url` is confirmed live to only care about the ID at the end of whatever URL string you pass it (slug text is ignored), and its response includes a real, official `shareUrl` field. So for each listing that survives the price/area filter, `listing_service.py` makes one extra call to `/listing-details-by-url` with a throwaway placeholder URL just to carry the real ID, and uses the `shareUrl` 99.co itself returns. Confirmed working end-to-end: user click-tested 2 real generated links, both resolved correctly.

**Town scoping — a second real bug found via live testing (not just reading docs):** `/search-property`'s `query_ids` param needs a resolved location id — passing `query_ids=singapore` (unscoped, "search everything") and filtering by town client-side was the only option before `/autocomplete`'s parameters were known. This turned out to be **non-deterministic**: the exact same query for "Clementi" returned real Clementi listings on one call and zero on the next, because 99.co's default "relevance" sort across all of Singapore isn't stable between identical calls. Fixed by calling `/autocomplete?query={town}` first, taking the first location from its "HDB Town" group (e.g. `htclementi`, type `hdb_town`), and passing both `query_ids` and `query_type` explicitly to `/search-property` — this properly scopes results server-side and is deterministic. One side effect: the client-side town substring filter that existed as a workaround was actively wrong and got removed — it excluded real matches like "Sunset Way" and "West Coast Drive" (both legitimately part of Clementi's HDB town per 99.co's own scoping) just because their names don't contain the word "Clementi".

**`page_size` is capped at 3, not higher, for two compounding reasons found by pushing the fixed scoping to its real limits:** (1) each matching listing costs one extra RapidAPI call for its `shareUrl` — at `page_size=50` that's up to 50 extra calls (~32s, most of the 500/month free-tier quota) for a single chat query; (2) `supervisor_agent` delegates to `valuation_agent` AND `geospatial_agent` per listing (~6 reasoning steps each including tool calls) — 5 listings alone hit Orchestrate's 30-step react-agent recursion limit and the whole run failed outright (`GRAPH_RECURSION_LIMIT`). 3 listings stays safely under that budget while still being a reasonable "shortlist."

### `POST /tools/valuation` — `checkValuation`
**Request:**
```json
{
  "town": "Bishan",
  "flat_type": "4-room",
  "floor_area_sqm": 93,
  "asking_price": 820000,
  "floor_level": "high"
}
```
`floor_level` is optional (`"low"` / `"mid"` / `"high"`, from a listing's own `floor_level` field — see `/tools/listings` below). Plain string, not a strict enum — an unrecognized value is ignored rather than rejected.

**Response:**
```json
{
  "median_transacted_price": 798000,
  "comparable_transactions": 12,
  "valuation_verdict": "fairly_priced | overpriced | underpriced",
  "premium_pct": 2.8,
  "lookback_years": 5,
  "floor_level_matched": true
}
```

**A critical, silent staleness bug found by testing the "past 5 years" request that prompted this section:** data.gov.sg's `datastore_search` returns records in a fixed default order (apparently insertion/`_id` order) when no `sort` is given — for a common town+flat_type combo, an unsorted `limit=100` query returned *only* 2017-01 to 2017-07 data out of 1,977 total matches since 2017. That silently produced a median **41% lower** than the same query with `sort=month desc` ($557,500 vs. $788,000 for one real Bishan 4-room check) — every valuation this app had computed before this fix was based on stale, years-old prices, not current ones. Fixed by adding `sort=month desc` to the data.gov.sg query, then filtering client-side to the last `LOOKBACK_YEARS` (5) to keep it honest for rare town+flat_type combos that might not have 100 transactions within that window.

**Floor-level matching**: 99.co's `/listing-details-by-url` (already called once per listing for the `shareUrl`, see above) also has a `details["Floor Level"]` field (e.g. `"Mid"`) — captured at no extra cost as `Listing.floor_level`. data.gov.sg has no equivalent categorical field, only a 3-storey `storey_range` band (e.g. `"10 TO 12"`); `valuation_service.py` approximates by bucketing the band's starting storey into low (1-6) / mid (7-15) / high (16+) — a building-height-agnostic heuristic, not an official cutoff. If fewer than 5 comparable transactions match the requested floor tier, falls back to the unfiltered (still recency-filtered) set rather than trust a median from a handful of data points — `floor_level_matched` tells the caller which happened, and `valuation_agent`'s instructions require it to say so honestly either way.

### `POST /tools/geospatial` — `lookupAmenities`
**Request:**
```json
{
  "address": "123 Bishan Street 12",
  "amenity_types": ["mrt", "school", "hawker_centre"],
  "radius_m": 1000
}
```
**Response:**
```json
{
  "coordinates": { "lat": 1.3501, "lng": 103.8480 },
  "amenities": [
    { "name": "Bishan MRT", "type": "mrt", "distance_m": 420 }
  ],
  "amenity_summary": "2 MRT stations within 500m, 1 hawker centre within 800m"
}
```

### `POST /chat/message` — frontend-facing, not an agent tool (excluded from the OpenAPI import)
**Request:**
```json
{
  "message": "4-room flat near Bishan MRT under $850k",
  "thread_id": null
}
```
**Response:**
```json
{
  "reply": "Shortlist of 4-room Bishan flats... (markdown, incl. a table of ranked listings)",
  "thread_id": "9f2c1e40-....."
}
```
`thread_id` starts `null` for a new conversation; the frontend stores whatever comes back and sends it on subsequent messages so watsonx Orchestrate treats them as one continuing conversation.

**What happens server-side** (`app/services/orchestrate_service.py`):
1. Resolve `supervisor_agent`'s id by name via `AgentClient.get_draft_by_name` (cached after first call — the id is stable across `orchestrate agents import` updates, only changes if the agent is deleted and recreated).
2. `RunClient.create_run(message, agent_id, thread_id)` → `POST {WXO_INSTANCE_URL}/v1/orchestrate/runs`.
3. `RunClient.wait_for_run_completion(run_id)` — polls `GET .../runs/{run_id}` every 2s (bounded to ~3 minutes, since the full supervisor → 3 collaborators → tools chain can take a while).
4. `ThreadsClient.get_thread_messages(thread_id)` → `GET .../threads/{thread_id}/messages`; take the last `role: "assistant"` message and concatenate its `text` content parts.
5. Auth: `IAMAuthenticator(apikey=WXO_API_KEY)` — IBM Cloud IAM, inferred from the instance URL containing `cloud.ibm.com` (confirmed by reading the installed ADK CLI's own auth-inference logic; a URL without `cloud.ibm.com` would infer MCSP instead).

---

## Key Decisions Already Locked In

- **3 collaborator agents** (listing, valuation, geospatial) — an earlier CPF/grants eligibility agent idea was dropped to keep scope manageable within a 5-6 week timeline
- **No vector database** — all data is structured/filterable, no semantic search needed
- **SaaS/TechZone environment** over local ADK Developer Edition — avoids Lima VM/container setup issues encountered previously
- **Custom React frontend confirmed compatible** with either local or SaaS Orchestrate — the REST API (not the built-in chat widget) is what the frontend calls, so there's no "boring fixed chatbot" limitation
- **Data sourced via official APIs only** — no web scraping, for both reliability and ToS reasons
- **MCP is optional, not required** — OpenAPI import is simpler and sufficient for custom in-house tools; MCP could be added for one tool as a demo-value addition if desired, but isn't necessary
- **Valuation uses data.gov.sg only** — the authoritative, free, no-auth government dataset is sufficient on its own; 99.co's own `/transactions` endpoint was considered as a cross-validation source but dropped to keep the Valuation Agent simple and avoid extra RapidAPI quota usage
- **99.co integration uses 3 endpoints**: `/search-property` (main search), `/listing-details-by-url` (fetches each matching listing's real `shareUrl`, one extra call per matching listing — see FastAPI Endpoint Signatures for why), and `/project-nearby` remains unused. The other 11 of 99.co's 14 endpoints are documented as available but out of scope, to avoid scope creep
- **Listing links use 99.co's own `shareUrl`, not a constructed guess** — a first attempt guessed the URL pattern from a public web search result and shipped it without live verification; the user click-tested 3 generated links and got 404s on all of them. Reverted immediately rather than leaving broken links live. The working fix (`/listing-details-by-url` ignores slug text, only cares about the trailing ID) was found by testing candidate URLs against the real API instead of guessing further — confirmed via 2 real user click-tests afterward
- **Frontend is a chat interface, not a structured search form** — a free-text box and message history, matching how the real supervisor_agent works (free text in, reasoned recommendation out). An earlier version used a flat_type/town/max_price form that called the 3 tool endpoints directly from the browser, bypassing the agents entirely — that was replaced because it didn't exercise the actual multi-agent reasoning the project is meant to demonstrate
- **Backend proxies chat to Orchestrate, frontend never calls Orchestrate directly** — the WXO API key must stay server-side; the backend mints its own IAM bearer token via `ibm-watsonx-orchestrate-clients` and calls `/v1/orchestrate/runs` on the frontend's behalf
- **Google Places API (New) replaced OneMap entirely for amenities** — chosen over keeping a hybrid (OneMap for hawker centres + Google for MRT/schools) for simplicity of a single provider, accepting the tradeoffs of a mandatory Google Cloud billing account and losing OneMap's authoritative NEA-tagged hawker centre data in favor of Google's generic (and occasionally imprecise) `food_court` category
- **Live "thinking" panel observes our own `/tools/*` endpoints, not Orchestrate's internals** — verified by reading the installed `ibm-watsonx-orchestrate-clients` SDK source directly: Orchestrate has no SSE/HTTP streaming, no `step_details` type `"thinking"`, and its delta/token streaming events are dead code in this SDK version (registered but never dispatched). The detailed "Called tool X → responded Y" trace only exists *after* a run completes (`step_history` on the final thread message), never incrementally. Since our own FastAPI backend is what the 3 collaborator agents actually call, `/tools/listings|valuation|geospatial` each publish a real event (via `backend/app/services/event_bus.py`, a single-process `asyncio.Queue`) the instant Orchestrate invokes them, relayed to the browser over SSE (`GET /chat/events`) — genuinely live, not simulated. Accepted limitation: a single global "current session" queue, not multi-tenant-safe (a second browser tab or user resets/steals it) — acceptable since this app runs single-session today.

---

## Open Items / To Verify

- [x] Exact 99.co API request/response field names for `/search-property` — confirmed live against a real RapidAPI account and account owner's own tester screenshot (see Public APIs section for the full field list). `/project-nearby` remains unconfirmed since it's not currently called by `listing_service.py`.
- [x] Listing URL / link-out to the real 99.co page — resolved via `/listing-details-by-url`'s `shareUrl` field, confirmed working by 2 real user click-tests (see Public APIs section and the Key Decisions entry on this). `/listing-details` itself (queried by ID directly rather than by URL) remains unconfirmed — its exact query param name is still unknown.
- [x] Current OneMap base URL and auth flow — **corrected live**: `developers.onemap.sg` (previously documented, sourced from public web search) turned out not to resolve at all when actually tested; the real, working domain is `www.onemap.gov.sg`, confirmed by hitting the auth, geocoding, and themes endpoints directly with a real account token. Lesson: for API details, prefer testing against the real endpoint over trusting search results, even when the search results look authoritative.
- [x] Orchestrate ADK YAML schema for collaborator agent references — confirmed directly against the installed ADK CLI (v2.11.0)'s `AgentSpec`/`BaseAgentSpec` Pydantic models (`ibm_watsonx_orchestrate/agent_builder/agents/types.py`) and validated all 4 `agents/*.yaml` files against `Agent.from_spec()`. Required top-level fields: `spec_version: v1`, `kind: native`, `name`, `description`; optional but used here: `llm`, `style`, `instructions`, `collaborators` (list of agent names), `tools` (list of tool `operationId`s).
- [x] `llm` model id — `orchestrate models list` showed this tenant only has `groq/openai/gpt-oss-120b` (default) and `bedrock/openai.gpt-oss-120b-1:0` available; all 4 agents use the former. A placeholder `watsonx/meta-llama/...` id was tried first and failed live with `model_not_supported` — worth remembering that `models list` is tenant-specific and should always be checked before picking an `llm` value on a new instance.
- [x] Live agent chat verified end-to-end via `orchestrate chat ask` — supervisor_agent correctly delegated to all 3 collaborators and returned a ranked, reasoned shortlist. Required tunneling the local backend through ngrok first, since watsonx Orchestrate SaaS can't reach `localhost` — the imported OpenAPI spec's `servers` entry must point at a publicly reachable URL. Also note: `orchestrate chat ask` loops infinitely on stdin EOF when run non-interactively without piped input (a CLI bug) — pipe `exit\n` via stdin if scripting it.
- [x] watsonx Orchestrate REST API + auth for the chat endpoint — found by reading the installed `ibm-watsonx-orchestrate-clients` SDK source directly rather than guessing. Real call chain: `POST {instance_url}/v1/orchestrate/runs` → poll `GET .../runs/{run_id}` → `GET .../threads/{thread_id}/messages`. Auth type is inferred from the instance URL the same way the CLI does it (`cloud.ibm.com` in the URL → IBM Cloud IAM via `IAMAuthenticator`; otherwise → MCSP). The standalone `ibm-watsonx-orchestrate-clients` PyPI package (no need for the full ADK package) provides `RunClient`, `ThreadsClient`, and `AgentClient` ready-made.
- [x] MRT/school amenity data source — resolved by replacing OneMap entirely with Google Places API (New) + Geocoding API. **Verified live end-to-end** with a real API key: geocoding, schools, and hawker centres all returned correct real data immediately, but the initial `mrt` → `train_station` type mapping was wrong — it matched "Smrt Trains Ltd" (SMRT's corporate office) instead of an actual station. Empirically tested alternatives directly against the Places API and found `subway_station` is correct (returns real station names like "Bishan", "Braddell"); `transit_station` was ruled out as too broad (pulls in bus stops). Fixed in `geo_service.py`'s `AMENITY_TYPE_TO_GOOGLE_TYPE` map. Full chat flow re-verified — reply now includes real MRT distance, real school names, and real hawker centre names, with the agent's own closing line confirming "no additional information has been invented."
- [x] Google Places `hawker_centre` → `food_court` mapping — verified live: returns genuine hawker centre names (e.g. "Kim San Leng Food Centre") mixed with individual stalls/stores tagged as food courts (e.g. "Al-Hossain North Indian & South Indian Cuisine") rather than only distinct hawker centre buildings. Not wrong, but coarser-grained than OneMap's authoritative NEA hawker centre list was — results read more like "food options nearby" than "hawker centres" strictly. Acceptable for this use case, worth knowing if precision matters later.
- [x] `rooms` (bedroom count) ↔ HDB flat_type mapping is an approximation (`_ROOM_RANGE_BY_FLAT_TYPE` in `listing_service.py`) — spot-checked live per the two entries below: 99.co's `beds` field turned out to be an unreliable HDB flat_type proxy on its own (beds=3 alone spanned 63-125 sqm across multiple real flat_types). `rooms` is now only a coarse, deliberately-widened server-side pre-filter; real precision comes from `_flat_type_matches`'s `subCategory`/title/floor-area fallback chain — see the `subCategory` entry below for the full story.
- [x] Two real bugs found by testing a "5-room flat near Clementi under $2,000,000" query that (wrongly) returned zero results: (1) `_FLAT_TYPE_BY_BEDS` reverse-mapped a `beds=3` match found via the intentionally-wide "5-room" search back to the label `"4-room"`, making a real match look like a non-match — fixed by echoing back the requested `flat_type` instead of re-deriving one from `beds`; (2) unscoped `query_ids=singapore` + client-side town filtering was non-deterministic (same query, same params, different results between calls) — fixed by resolving the town via `/autocomplete`'s "HDB Town" group first. See the FastAPI Endpoint Signatures section for the full story, including the `page_size=3` cap this fix made necessary.
- [x] "Filter to the past 5 years" + "account for floor level" (both user requests) — prompted discovery of a critical, previously-silent staleness bug in `checkValuation`: data.gov.sg's default (unsorted) record order meant every valuation this app had ever computed was based on 2017-era prices, ~41% below current. Fixed with `sort=month desc` + a 5-year client-side cutoff. Floor level is now captured from 99.co's `/listing-details-by-url` (`details["Floor Level"]`, free — already calling this endpoint for the `shareUrl`) and optionally narrows the valuation comparison to same-tier (low/mid/high) transactions, falling back honestly to all-floors if fewer than 5 tier-matched comparables exist. See the FastAPI Endpoint Signatures section for full detail.
- [x] Raw HTML (`<br>`, `<a href="...">`) appearing as literal text in chat replies instead of rendering, and links not opening in a new tab — root cause: `supervisor_agent` was mixing raw HTML into Markdown table cells (a common workaround since Markdown table cells can't contain literal line breaks), which `react-markdown` doesn't render by default. Fixed on both sides: `supervisor_agent.yaml` now requires plain `[text](url)` Markdown only and single-line cells; the frontend also added `rehype-raw` + `rehype-sanitize` (renders any HTML that still slips through, but strips anything unsafe, since this text ultimately includes third-party listing/business names) and a custom link component forcing `target="_blank" rel="noopener noreferrer"`. Also added a `.table-scroll` wrapper so wide tables scroll horizontally within the chat bubble instead of clipping.
- [x] Live "thinking" panel — verified end-to-end in a real browser against the real running server: the panel showed genuinely live intermediate status ("Thinking..." → "Found 3 matching listing(s) (cache)" → "Underpriced — ...") while a real chat query was in flight, then collapsed to an accurate "Thought for 16s" that persists on that message and re-expands to the full real trace (12 events, including the floor-level detail) afterward. One thing NOT done: an automated pytest for the SSE relay — attempted via `TestClient(app).stream(...)` + a concurrent `client.post(...)` in a background thread, but it hangs. Root cause: `event_bus.py`'s single-persistent-loop design (correct for a real uvicorn process) doesn't hold under `TestClient`, where each call appears to get its own isolated event loop, so `call_soon_threadsafe` from the POST's loop never reaches the GET stream's queue. Real curl + real Playwright browser testing against the actual server (which matches production topology) already verified this thoroughly — a more faithful check than a `TestClient`-based unit test would have been anyway, so this was a deliberate call not to force a synthetic, fragile test into the suite.
- [x] `valuation_agent` silently never being invoked — reported by the user as "somehow the valuation agent not fetching properly." Confirmed via backend access logs that zero `/tools/valuation` requests were ever made for a query ("5-room flat near Clementi under $1300000") that should have triggered 3, and via direct curl to `/tools/listings` that `floor_area_sqm` was genuinely present on every listing (91.0, 92.0, 80.0 sqm) — so `supervisor_agent`'s stated excuse ("floor area not disclosed") was factually false at the data layer. Root cause: information loss in the natural-language hand-off from `listing_agent` to `supervisor_agent` — everything passed between agents is free-form LLM text, not structured JSON (JSON only exists at the actual tool-call boundary), and `listing_agent`'s old instructions ("return the matching listings as-is") didn't guarantee every numeric field survived that paraphrase. Fixed by rewriting `agents/listing_agent.yaml` to require restating each listing's `listing_id, address, town, flat_type, asking_price, floor_area_sqm, listing_url, floor_level, nearest_mrt_name, nearest_mrt_distance_m` explicitly and individually, and by strengthening `agents/supervisor_agent.yaml` to explicitly forbid skipping `valuation_agent` on "data not disclosed" grounds. Re-imported both agents and re-ran the identical live query after truncating the cache: all 3 listings came back with real valuation verdicts (underpriced -9.8%, -49.5%, -36.8%), and the access log confirmed 3 real `POST /tools/valuation` calls (all 200 OK). Full test suite (13 tests) still passes.
- [x] A stated floor-level preference (e.g. "mid floor") never actually influenced which listings were returned — reported by the user as "it never show listings with mid floor it just show low and high." Confirmed via direct curl to `/tools/listings` (3 listings back: low, high, high) that this wasn't random bad luck: (1) 99.co's `/search-property` has no floor-level parameter at all (only `rooms`/`price`/`page_size`/`query_ids` — confirmed against the real API), and (2) `ListingSearchRequest` had no `floor_level` field, confirmed by inspecting `searchListings`'s actual tool schema in `openapi.json`. So a stated floor preference was only ever used *after the fact*, for `valuation_agent`'s floor-aware price comparison — never to search for or prefer listings of that tier; with only `page_size=3` raw candidates sampled (a cap already required for RapidAPI quota + Orchestrate's 30-step recursion limit), the odds of a mid-floor one showing up were pure chance. Fixed by adding an optional `floor_level` field to `ListingSearchRequest`/`searchListings`; when set, `listing_service.py` samples a wider raw pool and fetches listing details progressively, stopping as soon as `RESULT_COUNT` (3) tier-matches are found, honestly backfilling remaining slots with other-tier listings (never silently returning fewer than 3) if too few exist. Updated `agents/listing_agent.yaml` and `agents/supervisor_agent.yaml` so the buyer's stated floor preference is now passed to `searchListings`, not only to `checkValuation`. Added 2 new tests (`test_search_listings_filters_by_floor_level`, `test_search_listings_floor_level_falls_back_when_tier_unavailable`). **Also found and fixed in the process**: regenerating `openapi.json` from a live `curl localhost:8001/openapi.json` silently drops the `servers` field FastAPI never sets by default — since watsonx Orchestrate SaaS can only reach the backend through the public ngrok tunnel, a missing `servers` entry makes every tool call fail invisibly (no request ever reaches the backend, so nothing shows in its access log; the agent just reports a generic "search service is experiencing an error"). Whenever `openapi.json` is regenerated from a running server, the `servers` field must be re-patched in with the current ngrok URL before `orchestrate tools import` — confirmed by reproducing the silent failure, then fixing it and re-verifying real `/tools/listings` + `/tools/valuation` + `/tools/geospatial` calls all succeeded for the live "mid floor" query, with the reply correctly identifying which listings matched the tier and which didn't.
- [x] Unrealistically cheap "underpriced" verdicts on a real "5-room flat in Clementi, mid floor, max $1.1M" query — user asked "why it giving me flat with very low value i already told max budget 1.1 million." Investigated by querying 99.co's `/search-property` directly (bypassing our backend): confirmed its `beds` field is not a reliable HDB flat_type proxy on its own — a "5-room" search (`rooms=3,4`) returned `beds=3` listings ranging from **80 sqm to 125 sqm**, i.e. genuinely 4-room-sized units mixed in with real 5-room ones. Since a listing's `flat_type` is echoed back as whatever was requested (a deliberate earlier fix, see the `_FLAT_TYPE_BY_BEDS` entry above) rather than re-derived from `beds`, an undersized match silently masqueraded as "5-room" and got compared against the *real* 5-room valuation median (~$950k) — making a correctly-priced ~91 sqm flat look "underpriced by 49.5%" when it was actually just the wrong flat_type entirely. First fix attempt: added a floor-area sanity filter (`_MIN_FLOOR_AREA_SQM_BY_FLAT_TYPE`) rejecting listings too small to plausibly be the requested flat_type — later superseded, see below. **A second bug surfaced while fixing the first**: applying this sanity filter against the old `page_size=3` default (used when no floor preference was stated) caused 99.co's front-loaded, all-undersized top-3 results to get completely rejected, silently returning **zero** listings for a plain "5-room flat in Clementi" query — a regression caught via live re-test before it shipped. Fixed at the time by always oversampling the raw page (`SAMPLE_SIZE = 10`) regardless of whether a floor preference is given.
- [x] User separately reported "4-room flat" searches sometimes returning 3-room flats, and asked to check whether searching by an actual property-type field (rather than bedroom count) was possible — this directly explained the *cause* of the previous entry's mislabeling too, not just a coincidence. Inspected a raw `/search-property` listing object field-by-field and found `subCategory` (e.g. `"hdb_4r"`) — 99.co's own authoritative HDB flat_type classification, confirmed to agree with the listing's own `title` text (e.g. `"4 Room (4A) HDB for Sale"`) across dozens of inspected listings, unlike `beds` which was seen to disagree wildly (beds=3 spanned 63-121 sqm across 3-room/4-room/5-room listings; beds=4 spanned 5-room and executive maisonettes). No server-side filter param for it was found (`sub_category`/`subCategory`/`hdb_type` were all silently ignored by `/search-property`), so it must be applied client-side. Replaced the floor-area-only heuristic with a proper 3-tier `_flat_type_matches` check in `listing_service.py`: (1) authoritative `subCategory` match via `_HDB_SUBCATEGORY_BY_FLAT_TYPE`, (2) fallback to parsing the listing's own `title` text (e.g. `"3 Room HDB for Sale..."`) for the small fraction of listings where `subCategory` comes back `"unknown"` (confirmed live, e.g. some Toa Payoh listings) — the title still reliably states the room count even then, and (3) the old floor-area heuristic as a last resort only if neither signal is available. `_ROOM_RANGE_BY_FLAT_TYPE`'s `rooms` search param is now explicitly just a coarse, deliberately-widened pre-filter (never trusted alone) since the real precision now comes from `_flat_type_matches`. Replaced the old floor-area-only test with 3 new tests covering all 3 tiers of the fallback chain; full suite now 18/18. Re-verified live end-to-end across multiple flat_types/towns: 4-room Bishan listings now consistently ~109-112 sqm (correct), 5-room Clementi ~121-125 sqm (correct), 3-room Toa Payoh ~67 sqm (correct) — no more cross-type mismatches observed.
- [x] User reported listing links giving a real 404 after the `subCategory` fix above and asked to revert it — investigated before reverting, since the two symptoms ("wrong link", "search not fetching properly") had no evidence connecting them to that change. Direct backend calls and a real (non-headless-fingerprinted) browser session showed our `/tools/listings` endpoint's `listing_url` values resolving correctly (200, correct title) for several flat_types/towns — so the flat_type fix itself wasn't implicated. Asked the user for the exact broken link; it was `https://www.99.co/sale/property/214-bishan-street-23-hdb-...` — missing the `/singapore/` segment that our backend's own URL for that exact listing includes (confirmed via curl: `https://www.99.co/singapore/sale/property/214-bishan-street-23-hdb-...`). Loaded both in a real browser: the backend's URL is a real 200, the one missing `/singapore/` is a genuine `404 Page not found | 99.co`. Root cause: `supervisor_agent`'s LLM was silently rewriting/shortening the URL when composing its Markdown reply — the same category of natural-language hand-off information loss as the earlier valuation-skip bug, just on a URL instead of a number. Both `agents/listing_agent.yaml` and `agents/supervisor_agent.yaml` already said "include unchanged," which wasn't strong enough — a model can consider dropping what looks like a redundant path segment a harmless paraphrase. Fixed by making both instructions explicitly demand a character-for-character copy, calling out that `/singapore/` specifically is a real, load-bearing segment (not decorative) and that omitting any segment produces a genuine 404 — confirmed live. Re-imported both agents and re-ran the same query end-to-end: both returned URLs now include `/singapore/` intact, and loading the actual URL from the reply in a real browser confirmed 200 with the correct listing title. No revert was needed — the flat_type/subCategory fix was correct all along; the actual bug was upstream of it, in how the agent formats links.
- [x] Two further bugs found chasing "why does 4-room flat near Punggol MRT under $999k give no results" (the same query behind the "search not fetching properly" report above): (1) **The URL-mangling bug from the previous entry was stochastic, not fully fixed** — a follow-up live run showed one of two listing_urls in the same reply missing `/singapore/` again despite the strengthened instructions, confirmed as a genuine 404 in a real browser. Prompt instructions alone can't guarantee 100% compliance from a stochastic LLM. Fixed with a deterministic server-side safety net instead of relying further on prompting: `orchestrate_service.py`'s `_fix_mangled_listing_urls` regex-replaces any `https://www.99.co/sale/property/` (missing the segment) with the correct `https://www.99.co/singapore/sale/property/` on every reply before it's returned to the frontend — since every genuine 99.co listing URL has this exact prefix, any occurrence without it is unambiguously mangled and safe to repair. (2) **The real cause of "no results" itself**: pulled the actual `step_history` tool-call trace for the failing run directly from watsonx Orchestrate (via `RunClient`/`ThreadsClient`), and separately queried `listing_agent` directly with the exact same message the supervisor sent it — confirmed `listing_agent` correctly reported both real listings with every field intact (town: "Waterway East"/"Northshore"). The bug was entirely in `supervisor_agent`'s own reasoning: its final reply explicitly stated "the search returned only listings in other towns (Waterway East and Northshore), which do not meet your location requirement of being near Punggol MRT" — rejecting real, in-town matches because their `town` field showed a finer-grained neighbourhood name instead of literally "Punggol". This is the exact same false-mismatch phenomenon already documented and fixed at the backend level for Clementi/Sunset Way (`_matches_request`'s comment) — just now recurring at the agent-reasoning layer, since the domain knowledge that 99.co's neighbourhood-level `town` field is finer-grained than the buyer's requested HDB town was never given to `supervisor_agent` itself. Fixed by adding an explicit clarification to `supervisor_agent.yaml`: listing_agent's search is already town-scoped server-side, so any listing it returns satisfies the town filter by construction regardless of what its own `town` field says, and the agent must never reject a listing or tell the buyer "no listings were found in [town]" on that basis. Reproduced the failure twice via direct Orchestrate API calls before fixing (confirming it wasn't a one-off flake), then re-imported the agent and re-ran the identical query end-to-end: the supervisor now correctly presents both real listings with full valuation/amenity data instead of a false "no listings found" apology, and both listing_urls include `/singapore/` intact. Added `test_fix_mangled_listing_urls_repairs_missing_singapore_segment` and `test_fix_mangled_listing_urls_leaves_correct_urls_unchanged`; full suite now 20/20.
- [x] User asked "is the valuation agent working properly why everything put 0% cannot be what" after noticing every listing's valuation showed exactly "+0.0% vs [asking price] median across 0 transaction(s)" — a sharp catch, since a 0% match against 0 real transactions is a red flag, not a real result. Root-caused via a direct data.gov.sg query: passing "MARYMOUNT" or "UPPER THOMSON" (99.co's neighbourhood-level `town` labels for these Bishan-area listings) returns **zero** records — data.gov.sg's resale transaction dataset only recognizes official HDB town names like "BISHAN". This is the same neighbourhood-vs-official-town mismatch fixed for `listing_agent`'s search scoping and `supervisor_agent`'s reasoning in the two entries above, but here it was `supervisor_agent` passing each listing's own finer-grained neighbourhood field to `valuation_agent` instead of the buyer's originally-requested official town — reliably producing zero comparables. Compounding this, `valuation_service.py`'s `check_valuation` had a real, separate bug: when zero comparable transactions were found, it silently defaulted `median_price` to the listing's own `asking_price`, making `premium_pct` compute to exactly 0% and the verdict always "fairly_priced" — fabricating a confident-looking result from a complete absence of data, indistinguishable from a real match. Fixed both: (1) `supervisor_agent.yaml` now explicitly requires passing the buyer's originally-requested official town to `valuation_agent`, never a listing's neighbourhood field; (2) added a new `"insufficient_data"` value to `ValuationResponse.valuation_verdict` (schema change — required regenerating `openapi.json`, re-patching the `servers` URL, and re-importing the tool), and `check_valuation` now returns that verdict directly (with `premium_pct=0.0` as an explicit placeholder, not a real figure) whenever `comparable_transactions == 0`, instead of computing a fake self-referential premium. Updated `valuation_agent.yaml` and `supervisor_agent.yaml` to treat `insufficient_data` as distinct from `fairly_priced` — never state a percentage or call the price "fair" when it's returned, and rank such listings below ones with a real comparison. Added `test_check_valuation_reports_insufficient_data_with_zero_comparables`; full suite now 21/21. Re-verified live end-to-end with the same "4-room near Bishan MRT" query that originally surfaced this: valuation now shows real data — 47 comparable transactions, -25.2% and +2.2% genuine premium/discount figures — instead of the fabricated "0% vs 0 transactions" for both listings.
- [x] "4-room flat near Clementi under $1200000, mid floor" returned only 1 listing across three consecutive re-tries at ever-higher price ceilings (up to $2M) — user pushed back "cannot be it only get 1 result tho," rightly suspicious since Clementi is a large, common HDB town. Root-caused as a self-inflicted regression from the `subCategory` fix a few entries above: querying 99.co directly with no `rooms` filter showed **~11 genuine `hdb_4r` listings** in Clementi within budget — but with the widened `rooms=2,4` mapping introduced alongside that fix (intended defensively, to avoid excluding edge-case matches), the extra "beds=2" net pulled in far more numerous real 3-room listings that drowned out true 4-room ones within the fixed `page_size=10` raw sample — only 1 of the top 10 raw results was a genuine 4-room match. Reverting to the original, tighter `rooms=3,3` (beds=3 is what real `hdb_4r` listings consistently carry, confirmed live) raised that to 8 genuine matches out of the same 10. Since `_flat_type_matches`'s `subCategory` check now does the real flat_type precision work, the `rooms` param's only remaining job is maximizing genuine-match density within a fixed-size raw sample — a tight range that matches the common case densely beats a wide range that dilutes it with mostly-irrelevant results, so `_ROOM_RANGE_BY_FLAT_TYPE` was reverted to its original narrow values for all flat_types. Re-verified live: the same query now returns 3 genuine mid-floor 4-room listings (91-92 sqm) instead of 1. Also could not reproduce a separately-reported malformed Markdown table (a blank "Link" column with the link text misplaced under "Nearby Hawker Centre") once real multi-row data was flowing — the well-formed 3-row table this fix produced suggests that glitch was a symptom of the earlier sparse 1-result edge case rather than a separate systemic bug; worth reopening if it recurs with healthy data.
- [x] Follow-up on the fix above: user noticed the returned 3 listings were still all cheap ($480k/$600k/$669k) despite a $1.2M budget, and asked "is it cuz of the 3 search limit?" — correct instinct. Root cause: `_fetch_live`'s floor-level branch fetched listing details progressively and **stopped as soon as it found `RESULT_COUNT` (3) tier-matches**, taking them in whatever order 99.co's `/search-property` happened to return (confirmed live, not price-sorted) — so genuine 4-room matches priced at $1,070,000/$1,128,000/$1,150,000 existed in the very same raw sample but were never even checked, because 3 cheaper tier-matches were found first and the loop gave up early. The no-floor-preference path had the identical bug via a plain `candidates[:RESULT_COUNT]` slice. Fixed by adding `_select_price_diverse(candidates, count)` — sorts by `asking_price` and picks evenly-spaced indices across the full range rather than the first N found — applied to both paths; the floor-level path now fetches details for every candidate up to `SAMPLE_SIZE` (already the sampling cap, so no worst-case quota increase) instead of stopping early, so it can consider the full tier-matching set before selecting a spread. Added `test_select_price_diverse_spreads_across_the_price_range` and `test_select_price_diverse_returns_all_when_fewer_than_count`; full suite now 23/23. Re-verified live: **with no floor constraint**, the same Clementi/4-room/$1.2M query now spans $480k/$600k/$1,150,000 instead of clustering cheap — confirming the fix works. **With the "mid floor" constraint re-added**, the result was unchanged (still $480k/$600k/$669k) — traced this down directly (fetched real floor levels for every genuine 4-room candidate in the sample) and confirmed it's not a bug: the $1,128,000 and $1,150,000 listings are genuinely **high floor**, not mid, so within the buyer's actual stated constraint there simply is no higher-priced mid-floor option in this sample to surface — the low-price clustering in that specific case reflects real market data, not an algorithmic bias.
- [x] "5-room flat in Yew Tee under $2 million" showed no results — user asked if it's a location-mapping issue. Investigated directly: `/autocomplete` returned **empty** even for "Bishan" (previously confirmed working) with a `429` — the RapidAPI free-tier **monthly quota was fully exhausted** ("You have exceeded the MONTHLY quota for Requests... BASIC"), unrelated to "Yew Tee" specifically. Separately confirmed `/tools/listings` was surfacing this as a raw, undiagnosable `500 Internal Server Error` (an unhandled `httpx.HTTPStatusError` from `response.raise_for_status()`), which explains why the agent perceived "no results" rather than "search is down." User pushed back on the quota exhaustion itself, correctly noting the `RESULT_COUNT=3` cap should have kept usage low — right instinct: that cap only bounds the *final* output, not the actual per-search API call cost, which the previous fixes had quietly grown: 1 `/autocomplete` + 1 `/search-property` + up to **10** `/listing-details-by-url` calls per single search with a floor preference (the price-diversity fix above removed the early-stop, so every candidate's floor level now gets checked) = up to 12 calls for one search, not 3 — plus this session's own extensive live diagnostic querying (bypassing the app's cache entirely) across many bug investigations today. Implemented three concrete optimizations: (1) **`TOWN_LOCATION_CACHE_TTL` (30 days)** — town name → 99.co location id is effectively static, so `_resolve_town_location` now caches it (including "not found" results) via the existing `ApiCache` table instead of re-querying `/autocomplete` on every distinct search for the same town; (2) **`MAX_DETAIL_FETCHES_FOR_FLOOR_FILTER = 2 × RESULT_COUNT` (6)** — caps the floor-preference path's detail-fetch loop at 6 candidates instead of the full `SAMPLE_SIZE` (10), keeping most of the price-diversity benefit (a spread across up to 6 known candidates) while meaningfully cutting the worst-case quota cost; (3) **`ListingSourceUnavailableError`** — `_resolve_town_location` and `_fetch_live` now explicitly catch `401`/`403`/`429` responses and raise this distinctly from "town not found," and the `/tools/listings` router translates it into a clear `503` ("Listings source temporarily unavailable: ...") instead of an opaque `500` — verified live (quota was still exhausted at the time) that the endpoint now returns a clean, actionable 503 with the real RapidAPI message instead of a raw crash. Added `test_resolve_town_location_caches_across_calls` and `test_resolve_town_location_raises_on_quota_exhaustion` (using a fake httpx client, since the test suite runs in fixture mode); full suite now 25/25. Live end-to-end re-verification of the search-quality fixes is blocked until the monthly quota resets or the RapidAPI plan is upgraded — the optimizations are unit-tested and the 503 path is live-confirmed, but the underlying "search returns real results" behavior can't be re-tested against live data until quota is available again.
- [x] Standing instruction (2026-07-16): **never make live calls to the metered APIs (99.co via RapidAPI, Google Places) without the user's explicit permission** — the quota exhaustion above was caused largely by unprompted live diagnostic testing. Default verification is the pytest suite in fixture mode (zero live calls); when live verification would genuinely help, state the expected call cost and ask first. The user replaced the exhausted RapidAPI key with a new one on this date.
- [x] Batch of four user-requested changes (2026-07-16), all verified via the fixture-mode test suite only (no live calls, per the instruction above): (1) **Thinking panel now appears with content immediately** — previously the first visible event only arrived when Orchestrate made its first tool call (5-15s of bare "Thinking..." on a fresh chat, while the supervisor's LLM parsed the request and transferred to a collaborator); `/chat/message` now publishes a real `supervisor`-agent event ("Analyzing your request and coordinating the advisor agents...") the instant the request lands, and the frontend's `ThinkingEvent` type/label map gained the `supervisor` ("Advisor") agent. (2) **Condo / executive condo / landed support** — `flat_type` now also accepts `"condo"`, `"executive-condo"`, `"landed"` (deliberately the same field, not a new `property_type` one — one less value for the fragile LLM hand-off to garble), mapped to 99.co's confirmed `main_category` values (`condo`/`landed`; ECs live under `condo` and are narrowed client-side by subCategory-or-title match — **the exact condo/EC subCategory vocabulary is NOT yet live-verified**, unlike `hdb_Nr`, flagged in code comments); new optional `bedrooms` filter for non-HDB searches (99.co `beds` is the true bedroom count there, unlike for HDB); `Listing.floor_area_sqm` became nullable (landed listings can lack it) with `_matches_request`/`_map_99co_listing` guarded accordingly. (3) **Valuation is now explicitly HDB-only** — `check_valuation` short-circuits to `insufficient_data` (no API call) for non-HDB flat_types since data.gov.sg has no condo/EC/landed transactions; `ValuationRequest.floor_area_sqm` became optional (it was never used in the median computation anyway); the valuation thinking-panel "done" event now says "No comparable transactions found — pricing fairness can't be assessed" instead of the misleading "Insufficient Data — +0.0% vs ... 0 transaction(s)" phrasing. (4) **Six new amenity types** — `convenience_store`, `shopping_mall`, `mosque`, `church`, `temple` (→ Google `hindu_temple`), `synagogue` added to `AMENITY_TYPE_TO_GOOGLE_TYPE`; all six use documented Places API (New) Table A types but are **not yet verified against live Singapore data** the way `subway_station` was — check result quality on first real use; there is no generic queryable "place_of_worship" type, so agents route generic requests to the specific type(s). All four agent YAMLs updated (supervisor renamed conceptually to "Property Advisor", parses property categories + bedrooms, presents missing valuation honestly without ranking penalty, maps buyer phrasing onto the exact supported amenity vocabulary) and re-imported along with the regenerated tool schemas (`bedrooms` field, nullable `floor_area_sqm`, ngrok `servers` URL re-patched per the earlier lesson). Fixtures gained condo/EC listings and new-amenity entries; 6 new tests; full suite 31/31; frontend type-checks clean.
