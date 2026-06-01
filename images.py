"""
services/images.py
שליפת תמונות מוצרים מ-Open Food Facts (חינמי, ללא API key)
"""
import logging
import httpx

log = logging.getLogger("images")
OFF_URL = "https://world.openfoodfacts.org/api/v2/product"

async def get_product_image(barcode: str) -> str | None:
    """מחזיר URL לתמונת המוצר או None אם לא נמצא."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(
                f"{OFF_URL}/{barcode}.json",
                params={"fields": "image_front_url,image_url"},
                headers={"User-Agent": "ZOL-PriceBot/2.0"},
            )
            if r.status_code != 200:
                return None
            data = r.json()
            product = data.get("product", {})
            return (
                product.get("image_front_url")
                or product.get("image_url")
            )
    except Exception as e:
        log.warning("Open Food Facts error (%s): %s", barcode, e)
        return None

async def enrich_products_with_images(session) -> int:
    """
    מעדכן תמונות לכל המוצרים שאין להם עדיין תמונה.
    נקרא אחרי run_daily_job.
    """
    from sqlalchemy import text
    result = await session.execute(text(
        "SELECT barcode FROM products WHERE image_url IS NULL LIMIT 500"
    ))
    barcodes = [r[0] for r in result.fetchall()]
    updated = 0
    for barcode in barcodes:
        img = await get_product_image(barcode)
        if img:
            await session.execute(text(
                "UPDATE products SET image_url=:img WHERE barcode=:b"
            ), {"img": img, "b": barcode})
            updated += 1
    await session.commit()
    log.info("תמונות: עודכנו %d מוצרים", updated)
    return updated
