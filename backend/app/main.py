from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.database import Base, engine
from app.routers import chat, events, geospatial, listings, valuation

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="HDB Resale Advisor Tools API",
    description="FastAPI tool backend for the HDB Resale Flat Advisor watsonx Orchestrate agents.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(listings.router)
app.include_router(valuation.router)
app.include_router(geospatial.router)
app.include_router(chat.router)
app.include_router(events.router)


@app.get("/health", include_in_schema=False)
def health() -> dict[str, str]:
    return {"status": "ok"}
