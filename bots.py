"""
routers/bots.py
IVR (ימות המשיח) + וואטסאפ (Make.com)
"""
from fastapi import APIRouter, Depends, Query, Body, HTTPException, Header
from fastapi.responses import PlainTextResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from db import get_db

router = APIRouter(tags=["Bots"])

def _fmt(p) -> str:
    return f"{float(p):.2f}".rstrip("0").rstrip(".")

def _is_barcode(s: str) -> bool:
    return s.strip().isdigit() and len(s.strip()) >= 4

MEDALS = ["🥇","🥈","🥉"]

# ─── IVR ────────────────────────────────────────────────────

@router.get("/api/ivr/search", response_class=PlainTextResponse, tags=["IVR"])
async def ivr_search(
    barcode: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    if not _is_barcode(barcode):
        return "read=t-ברקוד שגוי. אנא נסה שנית."
    r = await db.execute(text("""
        SELECT p.product_name, bp.chain_name, bp.price
        FROM branch_prices bp JOIN products p ON p.barcode=bp.barcode
        WHERE bp.barcode=:b ORDER BY bp.price ASC LIMIT 1
    """), {"b": barcode.strip()})
    row = r.fetchone()
    if not row:
        return f"read=t-לא נמצא מחיר לברקוד {barcode}."
    return (f"read=t-עבור {row.product_name}, "
            f"המחיר הזול ביותר הוא {_fmt(row.price)} שקלים ברשת {row.chain_name}")

# ─── וואטסאפ ────────────────────────────────────────────────

@router.post("/api/whatsapp/search", tags=["WhatsApp"])
async def whatsapp_search(
    body: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    q = (body.get("message") or "").strip()
    if not q:
        raise HTTPException(400, "message is empty")

    if _is_barcode(q):
        result = await db.execute(text("""
            SELECT p.product_name, p.image_url, bp.chain_name, bp.branch_name, bp.price
            FROM branch_prices bp JOIN products p ON p.barcode=bp.barcode
            WHERE bp.barcode=:q ORDER BY bp.price ASC LIMIT 3
        """), {"q": q})
    else:
        result = await db.execute(text("""
            WITH matched AS (
                SELECT barcode FROM products
                WHERE product_name ILIKE '%'||:q||'%' OR similarity(product_name,:q)>0.2
                ORDER BY similarity(product_name,:q) DESC LIMIT 20
            )
            SELECT DISTINCT ON (bp.barcode)
                p.product_name, p.image_url,
                bp.chain_name, bp.branch_name, bp.price
            FROM branch_prices bp
            JOIN products p ON p.barcode=bp.barcode
            JOIN matched m ON m.barcode=bp.barcode
            ORDER BY bp.barcode, bp.price ASC
            LIMIT 3
        """), {"q": q})

    rows = result.fetchall()
    if not rows:
        return {"status":"not_found","reply":f"😕 לא נמצאו תוצאות עבור: _{q}_"}

    name = rows[0].product_name
    lines = [f"🛒 *{name}*", f"📊 *3 המחירים הזולים ביותר:*\n"]
    for i, r in enumerate(rows):
        lines.append(f"{MEDALS[i]} *{r.chain_name}* — {r.branch_name}")
        lines.append(f"   💰 ₪{_fmt(r.price)}\n")

    if len(rows) > 1:
        saving = float(rows[-1].price) - float(rows[0].price)
        if saving > 0:
            lines.append(f"💡 *חיסכון פוטנציאלי:* ₪{saving:.2f}")

    image_url = rows[0].image_url or ""
    lines.append("\n_מחירים מתעדכנים מדי יום_ 🔄")

    return {
        "status": "found",
        "reply": "\n".join(lines),
        "image_url": image_url,
        "product_name": name,
        "results": [
            {"chain": r.chain_name, "branch": r.branch_name, "price": _fmt(r.price)}
            for r in rows
        ]
    }

# ─── Web (Lovable Frontend) ──────────────────────────────────

@router.post("/api/web/search", tags=["Web"])
async def web_search(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    q = (payload.get("query") or "").strip()
    if not q:
        return {"status":"not_found","query":q,"results":[]}

    if _is_barcode(q):
        result = await db.execute(text("""
            SELECT p.product_name,p.manufacturer,p.category,p.image_url,p.unit_qty,
                   bp.chain_name,bp.branch_name,bp.city,bp.price,bp.barcode
            FROM branch_prices bp JOIN products p ON p.barcode=bp.barcode
            WHERE bp.barcode=:q ORDER BY bp.price ASC LIMIT 10
        """), {"q": q})
    else:
        result = await db.execute(text("""
            WITH matched AS (
                SELECT barcode FROM products
                WHERE product_name ILIKE '%'||:q||'%' OR similarity(product_name,:q)>0.2
                ORDER BY similarity(product_name,:q) DESC LIMIT 30
            )
            SELECT DISTINCT ON (bp.barcode)
                p.product_name,p.manufacturer,p.category,p.image_url,p.unit_qty,
                bp.chain_name,bp.branch_name,bp.city,bp.price,bp.barcode
            FROM branch_prices bp
            JOIN products p ON p.barcode=bp.barcode
            JOIN matched m ON m.barcode=bp.barcode
            ORDER BY bp.barcode, bp.price ASC
            LIMIT 10
        """), {"q": q})

    rows = result.fetchall()
    return {
        "status": "found" if rows else "not_found",
        "query": q,
        "results": [
            {
                "barcode":      r.barcode,
                "product_name": r.product_name,
                "manufacturer": r.manufacturer,
                "category":     r.category,
                "image_url":    r.image_url,
                "unit_qty":     r.unit_qty,
                "chain_name":   r.chain_name,
                "branch_name":  r.branch_name,
                "city":         r.city,
                "price":        round(float(r.price),2),
            }
            for r in rows
        ]
    }
