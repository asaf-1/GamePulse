# main.py — GamePulse News Microservice (Python/FastAPI, Render-ready)

import os, re, asyncio, hashlib
from datetime import datetime
from typing import List, Optional, Dict, Any

import httpx, feedparser, bleach
from cachetools import TTLCache
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="GamePulse News Service", version="1.0.0")

# CORS פתוח (לפרודקשן אפשר להגביל לדומיין שלך)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# קונפיג
PORT = int(os.getenv("PORT", "3000"))

SOURCES = [
    {"name": "IGN",       "env": "IGN_RSS",       "default": "https://feeds.ign.com/ign/all"},
    {"name": "Eurogamer", "env": "EUROGAMER_RSS", "default": "https://www.eurogamer.net/?format=rss"},
    {"name": "GameSpot",  "env": "GAMESPOT_RSS",  "default": "https://www.gamespot.com/feeds/mashup/"},
    {"name": "RPS",       "env": "RPS_RSS",       "default": "https://www.rockpapershotgun.com/feed"},
    {"name": "Escapist",  "env": "ESCAPIST_RSS",  "default": "https://www.escapistmagazine.com/v2/feed/"},
]

# Cache + Store
cache = TTLCache(maxsize=32, ttl=int(os.getenv("CACHE_TTL", "600")))  # ברירת מחדל 10 דק'
ITEM_STORE: Dict[str, Dict[str, Any]] = {}

ALLOWED_TAGS = ["p","ul","ol","li","br","strong","em","blockquote","code","pre","a"]
ALLOWED_ATTRS = {"a": ["href","title","target","rel"]}

def sanitize_html(html: Optional[str]) -> str:
    return bleach.clean(html or "", tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRS, strip=True)

def parse_date(entry: dict) -> Optional[str]:
    for key in ("published", "updated", "pubDate"):
        if entry.get(key):
            try:
                # feedparser מוסיף parsed
                if entry.get(key + "_parsed"):
                    dt = datetime(*entry[key + "_parsed"][:6])
                else:
                    dt = datetime.fromisoformat(entry[key])
                return dt.isoformat()
            except Exception:
                pass
    return None

def extract_image(entry: dict) -> Optional[str]:
    # media:content / media:thumbnail
    for field in ("media_content", "media_thumbnail"):
        if entry.get(field):
            try:
                url = entry[field][0].get("url")
                if url:
                    return url
            except Exception:
                pass
    # enclosure
    for link in entry.get("links", []):
        if link.get("rel") == "enclosure" and link.get("type", "").startswith("image"):
            return link.get("href")
    # img בתוך summary/content
    html = (entry.get("summary") or "") + "".join([c.get("value","") for c in entry.get("content", [])])
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', html, flags=re.I)
    return m.group(1) if m else None

async def fetch_feed(url: str) -> List[dict]:
    headers = {"User-Agent": "GamePulseBot/1.0 (+https://gamepulse-site)"}  # UA מנומס
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return feedparser.parse(r.text).entries

def make_id(link: str) -> str:
    return hashlib.md5(link.encode("utf-8")).hexdigest()

@app.get("/api/ping")
def ping():
    return {"ok": True, "ts": datetime.utcnow().isoformat() + "Z"}

@app.get("/api/news")
async def news(limit: int = Query(20, ge=1, le=100), q: Optional[str] = None) -> List[dict]:
    """
    מאחד RSS ממקורות, מחזיר רשימה אחודה ממוינת לפי תאריך.
    """
    items: List[dict] = []
    query = (q or "").strip().lower()

    for src in SOURCES:
        url = os.getenv(src["env"], src["default"])
        entries = cache.get(url)
        if entries is None:
            try:
                entries = await fetch_feed(url)
                cache[url] = entries
            except Exception:
                entries = []

        for e in entries:
            link = e.get("link")
            title = e.get("title", "").strip()
            if not link or not title:
                continue
            desc = e.get("summary") or e.get("description") or ""
            content_html = ""
            if e.get("content"):
                try:
                    content_html = e["content"][0].get("value", "") or ""
                except Exception:
                    pass

            # סינון חיפוש (על הכותרת + תיאור)
            if query:
                text = (title + " " + desc).lower()
                if query not in text:
                    continue

            img = extract_image(e)
            pub = parse_date(e)
            _id = make_id(link)

            # נשמור עותק "מורחב" להצגה במודאל (עם HTML מסונן)
            ITEM_STORE[_id] = {
                "id": _id,
                "title": title,
                "link": link,
                "source": src["name"],
                "pubDate": pub,
                "image": img,
                "description": desc,
                "content_html": sanitize_html(content_html or desc)[:4000],  # בטוח + מוגבל
            }

            # ברספונס הרשימה אין צורך בכל ה-HTML
            items.append({
                "id": _id,
                "title": title,
                "link": link,
                "source": src["name"],
                "pubDate": pub,
                "image": img,
                "description": desc,
            })

    # מיון לפי תאריך ולקיחת limit
    def sort_key(x):  # None דוחף לסוף
        return x["pubDate"] or ""
    items.sort(key=sort_key, reverse=True)
    return items[:limit]

@app.get("/api/article/{item_id}")
def get_article(item_id: str) -> dict:
    """
    מחזיר פרטי כתבה להצגה במודאל באתר (תוכן מתוך ה-RSS בלבד, מסונן).
    """
    item = ITEM_STORE.get(item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "id": item["id"],
        "title": item["title"],
        "source": item["source"],
        "link": item["link"],
        "pubDate": item["pubDate"],
        "image": item.get("image"),
        "content_html": item.get("content_html") or f"<p>{sanitize_html(item.get('description'))}</p>",
        "attribution": f"Preview from {item['source']} (RSS). Full story at the source.",
    }

# אופציונלי: שורש ידידותי
@app.get("/", tags=["meta"])
def root():
    return {"status": "ok", "docs": "/docs", "ping": "/api/ping", "news": "/api/news?limit=5"}
