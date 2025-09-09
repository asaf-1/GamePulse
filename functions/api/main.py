# main.py — GamePulse News Microservice (Python/FastAPI, Render-ready)
import os, re, asyncio
from datetime import datetime
from typing import List, Optional, Dict, Any

import httpx, feedparser
from cachetools import TTLCache
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="GamePulse News Service", version="1.0.0")

# CORS פתוח לפיתוח; אחר כך אפשר להגביל לדומיין שלך
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],     # פתוח – לפרודקשן אפשר להגביל לדומיין הסטטי שלך
    allow_credentials=False, # חשוב: אל תשאיר True יחד עם "*"
    allow_methods=["*"],
    allow_headers=["*"],
)


PORT = int(os.getenv("PORT", "3000"))

# מקורות RSS (ניתן לשנות דרך ENV ב-Render בלי לגעת בקוד)
SOURCES = [
    {"name": "IGN",       "env": "IGN_RSS",       "default": "https://feeds.ign.com/ign/all"},
    {"name": "Eurogamer", "env": "EUROGAMER_RSS", "default": "https://www.eurogamer.net/?format=rss"},
    {"name": "GameSpot",  "env": "GAMESPOT_RSS",  "default": "https://www.gamespot.com/feeds/mashup/"},
    {"name": "RPS",       "env": "RPS_RSS",       "default": "https://www.rockpapershotgun.com/feed"},
    {"name": "Escapist",  "env": "ESCAPIST_RSS",  "default": "https://www.escapistmagazine.com/v2/feed/"},
]

def build_sources() -> List[Dict[str, str]]:
    return [{"name": s["name"], "url": os.getenv(s["env"], s["default"])} for s in SOURCES]

# Cache בזיכרון — ברירת מחדל 10 דק׳ (600 שניות). אפשר לצמצם:
cache = TTLCache(maxsize=32, ttl=600)

IMG_TAG_RE = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)

def pick_image(entry: Dict[str, Any]) -> Optional[str]:
    # media:content של RSS
    mc = entry.get("media_content")
    if isinstance(mc, list) and mc and mc[0].get("url"):
        return mc[0]["url"]
    # enclosure
    en = entry.get("enclosures") or []
    if en:
        return en[0].get("href") or en[0].get("url")
    # לחלץ <img src="..."> מה-HTML
    html = ""
    if entry.get("content"):
        html = entry["content"][0].get("value", "")
    elif entry.get("summary"):
        html = entry["summary"]
    if html:
        m = IMG_TAG_RE.search(html)
        if m:
            return m.group(1)
    return None

def normalize(entry: Dict[str, Any], source_name: str) -> Dict[str, Any]:
    # תאריך ISO
    iso_date = None
    for key in ("published_parsed", "updated_parsed"):
        if entry.get(key):
            iso_date = datetime(*entry[key][:6]).isoformat()
            break
    return {
        "id": entry.get("id") or entry.get("guid") or entry.get("link"),
        "title": (entry.get("title") or "").strip(),
        "description": (entry.get("summary") or "").strip(),
        "link": entry.get("link"),
        "image": pick_image(entry),
        "pubDate": iso_date,
        "source": source_name,
    }

async def fetch_feed(client: httpx.AsyncClient, name: str, url: str) -> List[Dict[str, Any]]:
    try:
        r = await client.get(url, timeout=20.0)
        r.raise_for_status()
        parsed = feedparser.parse(r.content)
        return [normalize(e, name) for e in parsed.get("entries", [])[:20]]
    except Exception as exc:
        print(f"[Feed Error] {name}: {exc}")
        return []

async def get_all_news() -> List[Dict[str, Any]]:
    key = "news:all"
    if key in cache:
        return cache[key]

    sources = build_sources()
    async with httpx.AsyncClient(
        follow_redirects=True, headers={"User-Agent": "GamePulseBot/1.0"}
    ) as client:
        tasks = [fetch_feed(client, s["name"], s["url"]) for s in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    all_items: List[Dict[str, Any]] = []
    for res in results:
        if isinstance(res, list):
            all_items.extend(res)

    # מיון לפי תאריך
    def sort_key(x):
        try:
            return datetime.fromisoformat(x.get("pubDate") or "1970-01-01T00:00:00")
        except Exception:
            return datetime(1970, 1, 1)
    all_items.sort(key=sort_key, reverse=True)

    cache[key] = all_items
    return all_items

@app.get("/api/ping")
async def ping():
    return {"ok": True, "service": "gamepulse-news", "time": datetime.utcnow().isoformat()}

@app.get("/api/news")
async def news(
    q: Optional[str] = Query(None, description="חיפוש בכותרת/תיאור"),
    limit: int = Query(20, ge=1, le=100, description="כמות תוצאות"),
    source: Optional[str] = Query(None, description="פילטר מקורות: IGN,Eurogamer,..."),
):
    items = await get_all_news()

    if source:
        wanted = {s.strip().lower() for s in source.split(",")}
        items = [i for i in items if (i.get("source") or "").lower() in wanted]

    if q:
        term = q.lower()
        items = [
            i for i in items
            if term in (i.get("title") or "").lower() or term in (i.get("description") or "").lower()
        ]

    return items[:limit]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=PORT, reload=True)
