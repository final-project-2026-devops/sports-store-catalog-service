import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes import internal, products

logger = logging.getLogger("catalog-service")

app = FastAPI(title="Sports Store — Catalog Service")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(products.router, prefix="/api")
app.include_router(internal.router, prefix="/api")


@app.get("/health")
def health():
    return {"status": "ok", "service": "catalog-service"}
