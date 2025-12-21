from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.endpoints import upload, chat

app = FastAPI(title="ISTQB RAG System")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # For development, allow all. Restrict in production.
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(upload.router, prefix="/api", tags=["Admin"])
app.include_router(chat.router, prefix="/api", tags=["Client"])

@app.get("/")
async def root():
    return {"message": "Welcome to ISTQB RAG System API"}

