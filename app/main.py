import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.api.routes import router
from app.config import settings

app = FastAPI(
    title="Document-Agnostic RAG System",
    description="A modular RAG system that ingests arbitrary document types, answers queries with citations, and evaluates quality.",
    version="1.0.0"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router, prefix="/api")

# Mount static folder for the frontend UI
static_dir = os.path.join(os.path.dirname(__file__), "static")
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

@app.on_event("startup")
def startup_event():
    # Ensure workspace storage directories exist
    os.makedirs("data", exist_ok=True)
    os.makedirs("temp_uploads", exist_ok=True)
