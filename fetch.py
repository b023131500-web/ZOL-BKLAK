"""
services/fetch.py
שליפה יומית מכל 19 רשתות הסופרמרקט המחויבות לפי חוק שקיפות המחירים.
"""
from __future__ import annotations
import asyncio, gzip, json, logging, re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterator
import httpx
from lxml import etree
from sqlalchemy import text
from tenacity import retry, stop_after_attempt, wait_exponential
from db import get_session

log = logging.getLogger("fetch")

# ─── הגדרת כל הרשתות ────────────────────────────────────────

@dataclass
class Chain:
    name: str
    provider: str        # cerberus | nibit | shufersal | xml
    chain_id: str = ""
    index_url: str = ""

CHAINS: list[Chain] = [
    # Cerberus
    Chain("רמי לוי",      "cerberus", chain_id="7290058140886"),
    Chain("אושר עד",      "cerberus", chain_id="7290103152017"),
    Chain("יוחננוף",      "cerberus", chain_id="7290803800003"),
    Chain("דור אלון",     "cerberus", chain_id="7290492000005"),
    Chain("חצי חינם",     "cerberus", chain_id="7290700100008"),
    Chain("קשת טעמים",    "cerberus", chain_id="7290785400000"),
    Chain("סופר דוש",     "cerberus", chain_id="7290873900009"),
    # Nibit
    Chain("ויקטורי",      "nibit",    chain_id="7290696200003"),
    Chain("מחסני השוק",   "nibit",    chain_id="7290661400001"),
    Chain("מחסני להב",    "nibit",    chain_id="7290058179503"),
    # שופרסל
    Chain("שופרסל", "shufersal",
          index_url="https://prices.shufersal.co.il/FileObject/UpdateCategory"
                    "?catID=2&storeId=0&page=1&pageSize=300"),
    # XML פרטי
    Chain("יינות ביתן", "xml",
          index_url="https://url.retail.pe.il/api/raw/YeinotBitan/?FileType=prices&MainBranch=0"),
    Chain("טיב טעם",    "xml",
          index_url="https://url.retail.pe.il/api/raw/TivTaam/?FileType=prices&MainBranch=0"),
    Chain("מגה",        "xml",
          index_url="https://url.retail.pe.il/api/raw/Mega/?FileType=prices&MainBranch=0"),
    Chain("קואופ",      "xml",
          index_url="https://url.retail.pe.il/api/raw/Coop/?FileType=prices&MainBranch=0"),
    Chain("עדן טבע",    "xml",
          index_url="https://url.retail.pe.il/api/raw/EdenTeva/?FileType=prices&MainBranch=0"),
    Chain("זול ובגדול", "xml",
          index_url="https://url.retail.pe.il/api/raw/ZolVeBegadol/?FileType=prices&MainBranch=0"),
    Chain("סופר ברקט",  "xml",
          index_url="https://url.retail.pe.il/api/raw/SuperBareket/?FileType=prices&MainBranch=0"),
    Chain("כשר ביתן",   "xml",
          index_url="https://url.retail.pe.il/api/raw/KesherBitan/?FileType=prices&MainBranch=0"),
]

HEADERS = {"User-Agent": "ZOL-PriceBot/2.0"}
TIMEOUT  = httpx.Timeout(90.0, connect=15.0)
FILE_RE  = re.compile(r"PriceFull", re.IGNORECASE)
BATCH    = 5_000

# ─── HTTP helpers ────────────────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=4, max=30), reraise=True)
async def _get_bytes(client: httpx.AsyncClient, url: str) -> bytes:
    r = await client.get(url, headers=HEADERS, timeout=TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    return r.content

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=4, max=30), reraise=True)
async def _get_json(client: httpx.AsyncClient, url: str):
    r = await client.get(url, headers=HEADERS, timeout=TIMEOUT, follow_redirects=True)
    r.raise_for_status()
    return r.json()

def _branch_from_url(url: str) -> str:
    m = re.search(r"[_\-](\d{3,6})(?:[_\-.]|$)", url)
    return m.group(1) if m else "כללי"

def _decompress(raw: bytes, url: str) -> bytes:
    return gzip.decompress(raw) if url.lower().endswith(".gz") else raw

# ─── אינדקסים לפי ספק ───────────────────────────────────────

async def _urls_cerberus(client, chain: Chain) -> list[tuple[str,str]]:
    try:
        url = f"https://url.retail.pe.il/api/raw/{chain.chain_id}/?FileType=prices&MainBranch=0"
        data = await _get_json(client, url)
        files = data if isinstance(data, list) else data.get("files", [])
        return [(f.get("url",""), str(f.get("storeId","כללי")))
                for f in files if FILE_RE.search(str(f.get("url","")))]
    except Exception as e:
        log.warning("cerberus %s: %s", chain.name, e); return []

async def _urls_nibit(client, chain: Chain) -> list[tuple[str,str]]:
    try:
        url = f"https://www.nibit.co.il/NBCompetitionRegulations.aspx?chainId={chain.chain_id}&type=prices"
        body = (await _get_bytes(client, url)).decode("utf-8", errors="replace")
        urls = re.findall(r'https?://[^\s"\'<>]+', body)
        return [(u, _branch_from_url(u)) for u in urls if FILE_RE.search(u)]
    except Exception as e:
        log.warning("nibit %s: %s", chain.name, e); return []

async def _urls_shufersal(client, chain: Chain) -> list[tuple[str,str]]:
    try:
        data = await _get_json(client, chain.index_url)
        items = data if isinstance(data, list) else data.get("FileList", [])
        return [(i.get("URL",""), str(i.get("StoreId","כללי")))
                for i in items if FILE_RE.search(str(i.get("URL","")))]
    except Exception as e:
        log.warning("shufersal: %s", e); return []

async def _urls_xml(client, chain: Chain) -> list[tuple[str,str]]:
    try:
        raw = await _get_bytes(client, chain.index_url)
        try:
            data = json.loads(raw)
            items = data if isinstance(data, list) else data.get("files", [])
            result = [(i.get("url",""), str(i.get("storeId","כללי")))
                      for i in items if FILE_RE.search(str(i.get("url","")))]
            if result: return result
        except Exception:
            pass
        body = raw.decode("utf-8", errors="replace")
        urls = re.findall(r'https?://[^\s"\'<>]+', body)
        return [(u, _branch_from_url(u)) for u in urls
                if FILE_RE.search(u) and u.endswith((".gz",".xml",".XML"))]
    except Exception as e:
        log.warning("xml %s: %s", chain.name, e); return []

async def get_file_urls(client, chain: Chain) -> list[tuple[str,str]]:
    if chain.provider == "cerberus": return await _urls_cerberus(client, chain)
    if chain.provider == "nibit":    return await _urls_nibit(client, chain)
    if chain.provider == "shufersal":return await _urls_shufersal(client, chain)
    return await _urls_xml(client, chain)

# ─── פירוס XML ──────────────────────────────────────────────

def parse_xml(xml_bytes: bytes, chain_name: str, branch: str) -> Iterator[dict]:
    try:
        root = etree.fromstring(xml_bytes)
    except etree.XMLSyntaxError as e:
        log.warning("XML error %s/%s: %s", chain_name, branch, e); return

    items = root.findall(".//Item") or root.findall(".//Product") or root.findall(".//Row")
    for item in items:
        def t(*tags, fb=""):
            for tag in tags:
                el = item.find(tag)
                if el is not None and el.text:
                    return el.text.strip()
            return fb

        barcode = t("ItemCode","Barcode","EAN","MktItemCode")
        price_s = t("ItemPrice","Price","UnitOfMeasurePrice")
        name    = t("ItemName","ProductDescription","Name","Description")
        mfr     = t("ManufacturerName","Manufacturer","ManufacturerDesc")
        cat     = t("ItemSection","Category","Department")
        qty     = t("UnitQty","Quantity","PackageQuantity")

        if not barcode or not price_s or not name:
            continue
        try:
            price = float(price_s)
        except ValueError:
            continue
        if price <= 0:
            continue

        yield {
            "barcode": barcode, "product_name": name,
            "manufacturer": mfr or None, "category": cat or None,
            "unit_qty": qty or None, "chain_name": chain_name,
            "branch_name": branch, "price": price,
        }

# ─── DB ─────────────────────────────────────────────────────

async def _upsert_products(session, rows):
    if not rows: return
    await session.execute(text("""
        INSERT INTO products (barcode,product_name,manufacturer,category,unit_qty)
        VALUES (:barcode,:product_name,:manufacturer,:category,:unit_qty)
        ON CONFLICT (barcode) DO UPDATE SET
            product_name=EXCLUDED.product_name,
            manufacturer=COALESCE(EXCLUDED.manufacturer,products.manufacturer),
            category=COALESCE(EXCLUDED.category,products.category),
            unit_qty=COALESCE(EXCLUDED.unit_qty,products.unit_qty),
            updated_at=NOW()
    """), rows)

async def _insert_prices(session, rows):
    if not rows: return
    now = datetime.now(timezone.utc)
    for r in rows:
        r["updated_at"] = now
    await session.execute(text("""
        INSERT INTO branch_prices (barcode,chain_name,branch_name,price,updated_at)
        VALUES (:barcode,:chain_name,:branch_name,:price,:updated_at)
    """), rows)

async def _save_history(session):
    """שמור snapshot יומי של המחירים לגרף היסטורי"""
    await session.execute(text("""
        INSERT INTO price_history (barcode, chain_name, price, recorded_at)
        SELECT DISTINCT ON (barcode, chain_name)
            barcode, chain_name, price, CURRENT_DATE
        FROM branch_prices
        ON CONFLICT DO NOTHING
    """))

# ─── Pipeline ────────────────────────────────────────────────

async def _ingest_chain(client, chain: Chain, session) -> int:
    urls = await get_file_urls(client, chain)
    if not urls:
        log.warning("%s — אין קבצים", chain.name); return 0

    log.info("%s — %d קבצים", chain.name, len(urls))
    total = 0
    for url, branch in urls:
        try:
            raw = await _get_bytes(client, url)
            xml = _decompress(raw, url)
        except Exception as e:
            log.warning("  דילוג %s: %s", url, e); continue

        prods, prices = [], []
        for row in parse_xml(xml, chain.name, branch):
            prods.append({k: row[k] for k in ["barcode","product_name","manufacturer","category","unit_qty"]})
            prices.append({k: row[k] for k in ["barcode","chain_name","branch_name","price"]})
            if len(prices) >= BATCH:
                await _upsert_products(session, prods)
                await _insert_prices(session, prices)
                await session.commit()
                total += len(prices)
                prods.clear(); prices.clear()
        if prices:
            await _upsert_products(session, prods)
            await _insert_prices(session, prices)
            await session.commit()
            total += len(prices)

    log.info("%s — %d שורות", chain.name, total)
    return total

async def run_daily_job() -> int:
    log.info("═══ עדכון יומי התחיל ═══")
    start = datetime.now(timezone.utc)

    async with httpx.AsyncClient() as client:
        async with get_session() as session:
            await session.execute(text("TRUNCATE TABLE branch_prices RESTART IDENTITY"))
            await session.commit()

            total = 0
            for chain in CHAINS:
                try:
                    total += await _ingest_chain(client, chain, session)
                except Exception as e:
                    log.error("רשת %s נכשלה: %s", chain.name, e)

            await _save_history(session)
            await session.commit()

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    log.info("═══ הושלם — %d שורות ב-%.0fs ═══", total, elapsed)
    return total
