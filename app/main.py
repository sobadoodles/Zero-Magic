from fastapi import FastAPI

app = FastAPI(title="Zero Magic API")


@app.get("/health")
def health_check():
    return {"status": "ok"}