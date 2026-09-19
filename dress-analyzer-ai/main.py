from fastapi import FastAPI
from router import router

app = FastAPI(
    title="Dress Analyzer API",
    description="Detects garment type, gender, color, pattern and brand from dress images",
    version="1.0.0"
)

app.include_router(router)


@app.get("/")
def health_check():
    return {"status": "ok", "service": "dress-analyzer"}