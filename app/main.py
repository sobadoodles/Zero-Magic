from fastapi import FastAPI

from app.cards import router as cards_router


app = FastAPI(title="Zero Magic API")

app.include_router(cards_router)


@app.get("/health")
def health_check():
    return {"status": "ok"}