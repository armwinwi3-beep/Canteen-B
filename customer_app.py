"""Isolated customer API; legacy order endpoints are not exposed here."""
import os
from pathlib import Path
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

load_dotenv(Path(__file__).with_name(".env"))
from customer_auth import router

app = FastAPI(title="Canteen Customer API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.getenv("CUSTOMER_ORIGINS", "http://localhost:5173").split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET"],
    allow_headers=["Authorization"],
)
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}
