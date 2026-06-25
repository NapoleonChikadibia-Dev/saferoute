"""
news_service.py — Free, production-safe safety news via public RSS feeds.

Replaces NewsAPI (whose free tier forbids production use). Pulls from Nigerian
and international sources, filters by region/area name + safety keywords, and
caches results so we don't hammer the feeds on every request.

No API key. No per-request cost. Works in production.

Requires: feedparser  (pip install feedparser)
"""
import logging
from django.core.cache import cache

logger = logging.getLogger(__name__)

# Public RSS feeds — Nigerian + international. All free, no key.
RSS_FEEDS = [
    # --- Nigerian sources ---
    ('Punch',           'https://punchng.com/feed/'),
    ('Premium Times',   'https://www.premiumtimesng.com/feed'),
    ('Vanguard',        'https://www.vanguardngr.com/feed/'),
    ('The Guardian NG', 'https://guardian.ng/feed/'),
    ('Channels TV',     'https://www.channelstv.com/feed/'),
    # --- International (for global users) ---
    ('BBC Africa',      'https://feeds.bbci.co.uk/news/world/africa/rss.xml'),
    ('Al Jazeera',      'https://www.aljazeera.com/xml/rss/all.xml'),
    ('Reuters World',   'https://www.reutersagency.com/feed/?best-topics=world&post_type=best'),
]

# Keywords that mark an article as safety-relevant.
SAFETY_KEYWORDS = [
    'robbery', 'robbed', 'theft', 'stolen', 'burglary', 'kidnap', 'abduct',
    'attack', 'assault', 'murder', 'killed', 'shooting', 'gunmen', 'armed',
    'crime', 'criminal', 'violence', 'violent', 'security', 'police',
    'flood', 'flooding', 'fire', 'accident', 'crash', 'collapse', 'explosion',
    'protest', 'riot', 'unrest', 'cult', 'gang', 'fraud', 'scam', 'danger',
]

CACHE_TTL = 60 * 30   # 30 minutes — feeds don't change faster than this
FEED_TIMEOUT = 6      # seconds per feed


def _parse_all_feeds():
    """
    Fetch + parse every feed, returning a flat list of normalized articles.
    Cached for CACHE_TTL so repeated requests are cheap. Resilient: one bad
    feed never breaks the rest.
    """
    cached = cache.get('rss_all_articles')
    if cached is not None:
        return cached

    import feedparser

    articles = []
    for source_name, url in RSS_FEEDS:
        try:
            parsed = feedparser.parse(url)
            for entry in parsed.entries[:25]:   # cap per feed
                title = getattr(entry, 'title', '') or ''
                if not title:
                    continue

                # Try to find an image (RSS varies wildly on this)
                image = ''
                if getattr(entry, 'media_content', None):
                    image = entry.media_content[0].get('url', '')
                elif getattr(entry, 'media_thumbnail', None):
                    image = entry.media_thumbnail[0].get('url', '')
                elif getattr(entry, 'links', None):
                    for lnk in entry.links:
                        if lnk.get('type', '').startswith('image'):
                            image = lnk.get('href', '')
                            break

                summary = getattr(entry, 'summary', '') or ''
                # Strip HTML tags crudely from summary
                import re
                summary = re.sub(r'<[^>]+>', '', summary).strip()

                published = ''
                if getattr(entry, 'published', None):
                    published = entry.published[:16]
                elif getattr(entry, 'updated', None):
                    published = entry.updated[:16]

                articles.append({
                    'title':       title,
                    'description': summary[:160],
                    'url':         getattr(entry, 'link', ''),
                    'source':      source_name,
                    'image':       image,
                    'published':   published,
                    '_search_blob': (title + ' ' + summary).lower(),
                })
        except Exception as exc:
            logger.warning("RSS feed failed (%s): %s", source_name, exc)
            continue

    cache.set('rss_all_articles', articles, CACHE_TTL)
    return articles


def _is_safety_related(article):
    blob = article.get('_search_blob', '')
    return any(kw in blob for kw in SAFETY_KEYWORDS)


def get_safety_news(region: str = '', limit: int = 8) -> list:
    """
    Return safety-related news, optionally filtered to a region/area name.

    - region='' → all safety news across feeds (used by the map's general view)
    - region='Lekki' → only safety articles mentioning 'Lekki'

    Returns the same dict shape the old NewsAPI helper used, so it's a drop-in
    replacement. Returns [] on total failure (never raises).
    """
    try:
        all_articles = _parse_all_feeds()

        # Filter to safety-related first
        safety = [a for a in all_articles if _is_safety_related(a)]

        region = (region or '').strip().lower()
        if region:
            # Keep only articles mentioning the region/area name
            matched = [a for a in safety if region in a['_search_blob']]
            results = matched
        else:
            results = safety

        # Strip the internal search blob before returning
        cleaned = []
        for a in results[:limit]:
            cleaned.append({
                'title':       a['title'],
                'description': a['description'],
                'url':         a['url'],
                'source':      a['source'],
                'image':       a['image'],
                'published':   a['published'],
            })
        return cleaned
    except Exception as exc:
        logger.warning("get_safety_news failed: %s", exc)
        return []


def get_area_news(area, limit: int = 6) -> dict:
    """
    Tiered news lookup for area pages.

    Walks the area's ancestry from most specific to least:
        Lekki Phase 1 → Lekki → Lagos → Nigeria
    and returns news from the FIRST level that has any matches, along with
    which level actually matched — so the template can honestly say
    "Showing safety news for Lagos" when the specific area had none.

    Returns a dict:
        {
            'articles':     [...],          # the news (possibly empty)
            'matched_area': <Area or None>, # which level the news is for
            'is_widened':   bool,           # True if we fell back past the area itself
        }
    """
    try:
        # Build the chain: the area itself, then each ancestor up to country.
        chain = [area]
        node = area
        while getattr(node, 'parent', None):
            node = node.parent
            chain.append(node)

        # Try each level from most specific to least.
        for i, level_area in enumerate(chain):
            results = get_safety_news(region=level_area.name, limit=limit)
            if results:
                return {
                    'articles':     results,
                    'matched_area': level_area,
                    'is_widened':   i > 0,   # i==0 means the area itself matched
                }

        # Nothing anywhere in the chain.
        return {'articles': [], 'matched_area': None, 'is_widened': False}
    except Exception as exc:
        logger.warning("get_area_news failed: %s", exc)
        return {'articles': [], 'matched_area': None, 'is_widened': False}
