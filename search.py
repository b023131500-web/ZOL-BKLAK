"""
routers/search.py
כל נקודות הקצה לחיפוש, סינון והשוואת מחירים
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from db import get_db

router = APIRouter(prefix="/api/search", tags=["Search"])

# ─── עזרים ──────────────────────────────────────────────────

def _is_barcode(s: str) -> bool:
    return bool(s.strip().isdigit() and len(s.strip()) >= 4)

def _fmt(price) -> float:
    return round(float(price), 2) if price else 0.0

# ─── 1. חיפוש ראשי (ברקוד או שם) ───────────────────────────

@router.get("/")
async def search(
    q: str = Query(..., description="ברקוד או שם מוצר"),
    chain: str | None = Query(None, description="סנן לפי רשת"),
    city: str | None = Query(None, description="סנן לפי עיר"),
    category: str | None = Query(None, description="סנן לפי קטגוריה"),
    max_price: float | None = Query(None, description="מחיר מקסימלי"),
    limit: int = Query(10, le=50),
    db: AsyncSession = Depends(get_db),
):
    """
    חיפוש מוצר לפי ברקוד או שם חלקי, עם אפשרויות סינון.
    מחזיר את הזולים ביותר.
    """
    q = q.strip()

    # בניית תנאי WHERE דינמי
    filters = []
    params: dict = {"q": q, "limit": limit}

    if _is_barcode(q):
        base_where = "bp.barcode = :q"
    else:
        base_where = "(p.product_name ILIKE '%' || :q || '%' OR similarity(p.product_name, :q) > 0.2)"

    filters.append(base_where)

    if chain:
        filters.append("bp.chain_name = :chain")
        params["chain"] = chain
    if city:
        filters.append("bp.city ILIKE :city")
        params["city"] = f"%{city}%"
    if category:
        filters.append("p.category ILIKE :category")
        params["category"] = f"%{category}%"
    if max_price:
        filters.append("bp.price <= :max_price")
        params["max_price"] = max_price

    where = " AND ".join(filters)

    result = await db.execute(text(f"""
        SELECT DISTINCT ON (bp.barcode)
            bp.barcode,
            p.product_name,
            p.manufacturer,
            p.category,
            p.image_url,
            p.unit_qty,
            bp.chain_name,
            bp.branch_name,
            bp.city,
            bp.price
        FROM branch_prices bp
        JOIN products p ON p.barcode = bp.barcode
        WHERE {where}
        ORDER BY bp.barcode, bp.price ASC
        LIMIT :limit
    """), params)

    rows = result.fetchall()
    return {
        "query": q,
        "count": len(rows),
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
                "price":        _fmt(r.price),
            }
            for r in rows
        ]
    }

# ─── 2. השוואת מחירים לפי ברקוד בכל הרשתות ─────────────────

@router.get("/compare/{barcode}")
async def compare_prices(
    barcode: str,
    db: AsyncSession = Depends(get_db),
):
    """
    מחזיר את המחיר של מוצר ספציפי בכל הרשתות,
    כולל ממוצע, מינימום, מקסימום וחיסכון פוטנציאלי.
    """
    result = await db.execute(text("""
        SELECT
            p.product_name, p.manufacturer, p.image_url, p.unit_qty,
            bp.chain_name,
            MIN(bp.price) AS min_price,
            ROUND(AVG(bp.price)::numeric, 2) AS avg_price,
            COUNT(*) AS branch_count
        FROM branch_prices bp
        JOIN products p ON p.barcode = bp.barcode
        WHERE bp.barcode = :barcode
        GROUP BY p.product_name, p.manufacturer, p.image_url, p.unit_qty, bp.chain_name
        ORDER BY min_price ASC
    """), {"barcode": barcode})

    rows = result.fetchall()
    if not rows:
        return {"barcode": barcode, "found": False, "chains": []}

    chains = [
        {
            "chain_name":   r.chain_name,
            "min_price":    _fmt(r.min_price),
            "avg_price":    _fmt(r.avg_price),
            "branch_count": r.branch_count,
        }
        for r in rows
    ]

    cheapest = chains[0]["min_price"]
    priciest = chains[-1]["min_price"]

    return {
        "barcode":       barcode,
        "found":         True,
        "product_name":  rows[0].product_name,
        "manufacturer":  rows[0].manufacturer,
        "image_url":     rows[0].image_url,
        "unit_qty":      rows[0].unit_qty,
        "cheapest":      cheapest,
        "priciest":      priciest,
        "potential_saving": round(priciest - cheapest, 2),
        "chains":        chains,
    }

# ─── 3. Top 3 זול לפי מוצר (לוואטסאפ ו-IVR) ────────────────

@router.get("/top3/{barcode}")
async def top3(barcode: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(text("""
        SELECT p.product_name, p.image_url, bp.chain_name, bp.branch_name, bp.city, bp.price
        FROM branch_prices bp
        JOIN products p ON p.barcode = bp.barcode
        WHERE bp.barcode = :barcode
        ORDER BY bp.price ASC
        LIMIT 3
    """), {"barcode": barcode})
    rows = result.fetchall()
    if not rows:
        return {"found": False}
    return {
        "found": True,
        "product_name": rows[0].product_name,
        "image_url": rows[0].image_url,
        "results": [
            {"chain_name": r.chain_name, "branch_name": r.branch_name,
             "city": r.city, "price": _fmt(r.price)}
            for r in rows
        ]
    }

# ─── 4. חיפוש לפי קטגוריה ───────────────────────────────────

@router.get("/category/{category}")
async def by_category(
    category: str,
    chain: str | None = None,
    limit: int = Query(20, le=100),
    db: AsyncSession = Depends(get_db),
):
    params: dict = {"cat": f"%{category}%", "limit": limit}
    extra = ""
    if chain:
        extra = "AND bp.chain_name = :chain"
        params["chain"] = chain

    result = await db.execute(text(f"""
        SELECT DISTINCT ON (bp.barcode)
            bp.barcode, p.product_name, p.manufacturer,
            p.image_url, p.unit_qty, p.category,
            bp.chain_name, bp.price
        FROM branch_prices bp
        JOIN products p ON p.barcode = bp.barcode
        WHERE p.category ILIKE :cat {extra}
        ORDER BY bp.barcode, bp.price ASC
        LIMIT :limit
    """), params)

    rows = result.fetchall()
    return {
        "category": category,
        "count": len(rows),
        "results": [
            {"barcode": r.barcode, "product_name": r.product_name,
             "manufacturer": r.manufacturer, "image_url": r.image_url,
             "unit_qty": r.unit_qty, "chain_name": r.chain_name,
             "price": _fmt(r.price)}
            for r in rows
        ]
    }

# ─── 5. היסטוריית מחירים לגרף ───────────────────────────────

@router.get("/history/{barcode}")
async def price_history(
    barcode: str,
    chain: str | None = None,
    days: int = Query(30, le=365),
    db: AsyncSession = Depends(get_db),
):
    params: dict = {"barcode": barcode, "days": days}
    extra = ""
    if chain:
        extra = "AND chain_name = :chain"
        params["chain"] = chain

    result = await db.execute(text(f"""
        SELECT chain_name, price, recorded_at
        FROM price_history
        WHERE barcode = :barcode
          AND recorded_at >= CURRENT_DATE - :days
          {extra}
        ORDER BY recorded_at ASC
    """), params)

    rows = result.fetchall()
    return {
        "barcode": barcode,
        "days": days,
        "history": [
            {"chain": r.chain_name, "price": _fmt(r.price), "date": str(r.recorded_at)}
            for r in rows
        ]
    }

# ─── 6. רשימת רשתות וקטגוריות ──────────────────────────────

@router.get("/meta/chains")
async def list_chains(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text(
        "SELECT DISTINCT chain_name, COUNT(*) as cnt FROM branch_prices GROUP BY chain_name ORDER BY cnt DESC"
    ))
    return {"chains": [{"name": r.chain_name, "count": r.cnt} for r in result.fetchall()]}

@router.get("/meta/categories")
async def list_categories(db: AsyncSession = Depends(get_db)):
    result = await db.execute(text(
        "SELECT DISTINCT category, COUNT(*) as cnt FROM products WHERE category IS NOT NULL GROUP BY category ORDER BY cnt DESC LIMIT 50"
    ))
    return {"categories": [{"name": r.category, "count": r.cnt} for r in result.fetchall()]}
