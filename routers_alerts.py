"""
routers/alerts.py
הרשמה לקבלת התראות מחיר — מייל ווואטסאפ
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from db import get_db

router = APIRouter(prefix="/api/alerts", tags=["Alerts"])

class AlertCreate(BaseModel):
    barcode: str
    contact: str          # מייל או מספר טלפון
    contact_type: str     # "email" | "whatsapp"
    target_price: float | None = None

@router.post("/subscribe")
async def subscribe(data: AlertCreate, db: AsyncSession = Depends(get_db)):
    """הירשם לקבלת התראה כשמחיר יורד."""
    # בדוק שהמוצר קיים
    r = await db.execute(text("SELECT product_name FROM products WHERE barcode=:b"),
                         {"b": data.barcode})
    row = r.fetchone()
    if not row:
        raise HTTPException(404, f"מוצר {data.barcode} לא נמצא")

    await db.execute(text("""
        INSERT INTO price_alerts (barcode, contact, contact_type, target_price)
        VALUES (:barcode, :contact, :contact_type, :target_price)
    """), data.model_dump())
    await db.commit()
    return {
        "status": "subscribed",
        "product_name": row.product_name,
        "message": f"תקבל התראה ב-{data.contact} כשהמחיר ירד"
                   + (f" מתחת ל-₪{data.target_price}" if data.target_price else "")
    }

@router.delete("/unsubscribe")
async def unsubscribe(contact: str, barcode: str, db: AsyncSession = Depends(get_db)):
    await db.execute(text(
        "DELETE FROM price_alerts WHERE contact=:c AND barcode=:b"
    ), {"c": contact, "b": barcode})
    await db.commit()
    return {"status": "unsubscribed"}

@router.get("/my/{contact}")
async def my_alerts(contact: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("""
        SELECT pa.barcode, p.product_name, pa.target_price, pa.contact_type, pa.last_sent_at
        FROM price_alerts pa JOIN products p ON p.barcode=pa.barcode
        WHERE pa.contact=:c
    """), {"c": contact})
    rows = result.fetchall()
    return {"alerts": [
        {"barcode": r.barcode, "product_name": r.product_name,
         "target_price": r.target_price, "contact_type": r.contact_type,
         "last_sent": str(r.last_sent_at) if r.last_sent_at else None}
        for r in rows
    ]}
