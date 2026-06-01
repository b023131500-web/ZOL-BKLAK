"""
main.py — ZOL Price Bot API
"""
from __future__ import annotations
import asyncio, logging, os
from contextlib import asynccontextmanager
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db import get_db
from routers.search import router as search_router
from routers.bots   import router as bots_router
from routers.alerts import router as alerts_router
from services.fetch  import run_daily_job
from services.images import enrich_products_with_images
from services.alerts import check_and_send_alerts

logging.basicConfig(
    level=settings.LOG_LEVEL.upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
log = logging.getLogger("main")

scheduler = AsyncIOScheduler(timezone="Asia/Jerusalem")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # עדכון מחירים יומי
    scheduler.add_job(run_daily_job, "cron",
                      hour=settings.CRON_HOUR, minute=settings.CRON_MINUTE,
                      id="daily_fetch", replace_existing=True)
    # העשרת תמונות — שעה אחרי עדכון המחירים
    scheduler.add_job(
        lambda: asyncio.create_task(_enrich_images()),
        "cron", hour=settings.CRON_HOUR + 1, minute=settings.CRON_MINUTE,
        id="enrich_images", replace_existing=True,
    )
    # בדיקת התראות — כל שעה
    scheduler.add_job(check_and_send_alerts, "interval", hours=1, id="alerts")
    scheduler.start()
    log.info("Scheduler started — daily fetch at %02d:%02d IL",
             settings.CRON_HOUR, settings.CRON_MINUTE)
    yield
    scheduler.shutdown(wait=False)

async def _enrich_images():
    from db import get_session
    async with get_session() as session:
        await enrich_products_with_images(session)

app = FastAPI(
    title="ZOL — מחיר השוואה ישראל",
    description="API לשוואת מחירי סופרמרקטים בישראל — כל 19 הרשתות",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS — מאפשר ל-Lovable להתחבר
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routers
app.include_router(search_router)
app.include_router(bots_router)
app.include_router(alerts_router)

# ─── Health ─────────────────────────────────────────────────

@app.get("/health", tags=["Admin"])
async def health(db: AsyncSession = Depends(get_db)):
    r = await db.execute(text("""
        SELECT
            (SELECT COUNT(*) FROM products)      AS products,
            (SELECT COUNT(*) FROM branch_prices) AS prices,
            (SELECT COUNT(*) FROM price_alerts)  AS alerts,
            (SELECT MAX(updated_at) FROM branch_prices) AS last_update
    """))
    row = r.fetchone()
    return {
        "status": "ok",
        "products":    row.products,
        "price_rows":  row.prices,
        "alerts":      row.alerts,
        "last_update": str(row.last_update) if row.last_update else None,
    }

# ─── Admin ──────────────────────────────────────────────────

def _check_token(x_admin_token: str = Header(None)):
    if x_admin_token != settings.ADMIN_TOKEN:
        raise HTTPException(401, "Unauthorized")

@app.post("/api/admin/trigger-fetch", tags=["Admin"])
async def trigger_fetch(_=Depends(_check_token)):
    asyncio.create_task(run_daily_job())
    return {"status": "fetch_started"}

@app.post("/api/admin/trigger-images", tags=["Admin"])
async def trigger_images(_=Depends(_check_token)):
    asyncio.create_task(_enrich_images())
    return {"status": "image_enrichment_started"}

@app.post("/api/admin/trigger-alerts", tags=["Admin"])
async def trigger_alerts(_=Depends(_check_token)):
    asyncio.create_task(check_and_send_alerts())
    return {"status": "alerts_check_started"}

@app.get("/api/admin/stats", tags=["Admin"])
async def stats(_=Depends(_check_token), db: AsyncSession = Depends(get_db)):
    r = await db.execute(text("""
        SELECT chain_name, COUNT(*) as rows, MIN(price) as min_p, MAX(price) as max_p
        FROM branch_prices GROUP BY chain_name ORDER BY rows DESC
    """))
    return {"chains": [
        {"chain": row.chain_name, "rows": row.rows,
         "min_price": float(row.min_p), "max_price": float(row.max_p)}
        for row in r.fetchall()
    ]}
