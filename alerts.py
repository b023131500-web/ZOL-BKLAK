"""
services/alerts.py
שליחת התראות מחיר למנויים — מייל ווואטסאפ דרך Make.com webhook
"""
import logging
import httpx
from sqlalchemy import text
from config import settings
from db import get_session

log = logging.getLogger("alerts")

async def send_webhook(payload: dict) -> bool:
    """שולח payload ל-Make.com שמנתב למייל / וואטסאפ."""
    if not settings.MAKE_WEBHOOK_URL:
        return False
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.post(settings.MAKE_WEBHOOK_URL, json=payload)
            return r.status_code < 300
    except Exception as e:
        log.error("Webhook error: %s", e)
        return False

async def check_and_send_alerts() -> int:
    """
    בודק את כל המנויים — אם המחיר הנוכחי נמוך מה-target שלהם, שולח התראה.
    """
    sent = 0
    async with get_session() as session:
        result = await session.execute(text("""
            SELECT
                pa.id, pa.barcode, pa.contact, pa.contact_type, pa.target_price,
                p.product_name, p.image_url,
                MIN(bp.price) AS current_price,
                bp.chain_name, bp.branch_name
            FROM price_alerts pa
            JOIN products p ON p.barcode = pa.barcode
            JOIN branch_prices bp ON bp.barcode = pa.barcode
            WHERE (pa.target_price IS NULL OR MIN(bp.price) <= pa.target_price)
              AND (pa.last_sent_at IS NULL OR pa.last_sent_at < NOW() - INTERVAL '23 hours')
            GROUP BY pa.id, pa.barcode, pa.contact, pa.contact_type, pa.target_price,
                     p.product_name, p.image_url, bp.chain_name, bp.branch_name
            LIMIT 100
        """))
        alerts = result.fetchall()

        for row in alerts:
            payload = {
                "type":          row.contact_type,
                "contact":       row.contact,
                "product_name":  row.product_name,
                "barcode":       row.barcode,
                "current_price": float(row.current_price),
                "chain_name":    row.chain_name,
                "branch_name":   row.branch_name,
                "image_url":     row.image_url or "",
                "message": (
                    f"🔔 התראת מחיר!\n"
                    f"*{row.product_name}*\n"
                    f"מחיר כעת: ₪{row.current_price:.2f}\n"
                    f"ברשת {row.chain_name} — סניף {row.branch_name}"
                )
            }
            ok = await send_webhook(payload)
            if ok:
                await session.execute(text(
                    "UPDATE price_alerts SET last_sent_at=NOW() WHERE id=:id"
                ), {"id": row.id})
                sent += 1

        await session.commit()

    log.info("התראות נשלחו: %d", sent)
    return sent
