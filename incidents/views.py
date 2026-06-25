# incidents/views.py

import json
import logging
import base64
from django.core.files.base import ContentFile

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.contrib.admin.views.decorators import staff_member_required
from django.views.decorators.http import require_POST
from django.views.decorators.cache import cache_page
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.utils.html import escape

from .forms import RegisterForm, IncidentForm, CommentForm, UserProfileForm, UserUpdateForm
from .models import Incident, Comment, UserProfile, IncidentMedia, SavedIncident, Area, Flag

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AREA API — feeds the cascading dropdowns + search on the report form
# ---------------------------------------------------------------------------

def area_children_view(request):
    """
    Return child areas of a given parent (or all countries if no parent).
      ?parent=<id>  → that area's children
      (no parent)   → all countries (level 1)
    """
    parent_id = request.GET.get('parent', '').strip()
    if parent_id:
        children = Area.objects.filter(parent_id=parent_id).order_by('name')
    else:
        children = Area.objects.filter(level=Area.LEVEL_COUNTRY).order_by('name')

    data = [{'id': a.id, 'name': a.name, 'level': a.level} for a in children]
    return JsonResponse({'areas': data})


def area_search_view(request):
    """
    Search areas by name across all levels.  ?q=<text>
    Returns matches with full path so the user can disambiguate.
    """
    query = request.GET.get('q', '').strip()
    if len(query) < 2:
        return JsonResponse({'areas': []})

    matches = (
        Area.objects
        .filter(name__icontains=query)
        .select_related('parent', 'parent__parent', 'parent__parent__parent')
        .order_by('level', 'name')[:15]
    )
    data = [
        {'id': a.id, 'name': a.name, 'level': a.level, 'slug': a.slug, 'full_path': a.full_path()}
        for a in matches
    ]
    return JsonResponse({'areas': data})


def _normalize_area_name(name):
    """
    Loosen a place name for matching: lowercase, strip common admin suffixes
    that differ between Nominatim and our seed (e.g. 'Lagos State' → 'lagos').
    """
    if not name:
        return ''
    n = name.strip().lower()
    # Strip parenthetical bits: 'Abuja (FCT)' → 'abuja'
    if '(' in n:
        n = n.split('(')[0].strip()
    # Strip trailing admin words
    for suffix in (' state', ' province', ' county', ' lga',
                   ' local government area', ' city', ' municipality',
                   ' district', ' region', ' territory'):
        if n.endswith(suffix):
            n = n[: -len(suffix)].strip()
    return n


def area_resolve_view(request):
    """
    Given place names from a dropped pin (reverse-geocoded by Nominatim),
    FIND-OR-CREATE the full chain top-down and return the resolved deepest area.

    This is the engine behind pin-driven auto-derived areas: the dataset grows
    itself as people report. Normalization-based dedup prevents 'Lagos' vs
    'Lagos State' from creating duplicates.

    POST params (any subset): country, state, city, local, lat, lng
    Auto-created areas are is_verified=True (usable now) + needs_review=True
    (flagged for admin audit).

    Returns the resolved chain + the deepest area's id/path.
    """
    from django.utils.text import slugify

    if request.method != 'POST':
        return JsonResponse({'error': 'POST required'}, status=405)

    names = {
        Area.LEVEL_COUNTRY: request.POST.get('country', '').strip(),
        Area.LEVEL_STATE:   request.POST.get('state', '').strip(),
        Area.LEVEL_CITY:    request.POST.get('city', '').strip(),
        Area.LEVEL_LOCAL:   request.POST.get('local', '').strip(),
    }
    # Coordinates (optional) — stored on the deepest created area as a centre hint
    try:
        lat = float(request.POST.get('lat', ''))
        lng = float(request.POST.get('lng', ''))
    except (ValueError, TypeError):
        lat = lng = None

    chain = []
    parent = None
    created_any = False

    for level in (Area.LEVEL_COUNTRY, Area.LEVEL_STATE, Area.LEVEL_CITY, Area.LEVEL_LOCAL):
        raw_name = names[level]
        if not raw_name:
            break  # no name for this level → stop the chain here

        norm = _normalize_area_name(raw_name)
        if not norm:
            break

        # DEDUP: look for an existing child of `parent` whose normalized name matches
        existing = None
        for cand in Area.objects.filter(level=level, parent=parent):
            if _normalize_area_name(cand.name) == norm:
                existing = cand
                break

        if existing:
            area = existing
        else:
            # CREATE — trusted but flagged for review
            base_slug = slugify(f"{parent.name}-{raw_name}" if parent else raw_name) or "area"
            slug, n = base_slug, 2
            while Area.objects.filter(slug=slug).exists():
                slug = f"{base_slug}-{n}"
                n += 1
            area = Area.objects.create(
                name=raw_name[:120],
                level=level,
                parent=parent,
                slug=slug[:160],
                created_by=request.user if request.user.is_authenticated else None,
                is_verified=True,    # usable immediately
                needs_review=True,   # but flagged for admin audit
            )
            created_any = True

        chain.append({'id': area.id, 'name': area.name, 'level': area.level})
        parent = area

    # Stamp coordinates onto the deepest area if it lacks them (centre hint)
    if chain and lat is not None and lng is not None:
        deepest = Area.objects.get(pk=chain[-1]['id'])
        if deepest.latitude is None or deepest.longitude is None:
            deepest.latitude = lat
            deepest.longitude = lng
            deepest.save(update_fields=['latitude', 'longitude'])

    if not chain:
        return JsonResponse({'resolved': False, 'chain': [], 'area_id': None})

    return JsonResponse({
        'resolved':    True,
        'chain':       chain,
        'area_id':     chain[-1]['id'],
        'full_path':   ' → '.join(c['name'] for c in chain),
        'created_new': created_any,
    })


# ---------------------------------------------------------------------------
# AREA DASHBOARD
# ---------------------------------------------------------------------------

def _descendant_area_ids(area):
    """All area ids for `area` plus every descendant (walks the tree down)."""
    ids = [area.id]
    frontier = [area.id]
    while frontier:
        kids = list(Area.objects.filter(parent_id__in=frontier).values_list('id', flat=True))
        ids.extend(kids)
        frontier = kids
    return ids


def _area_stats(incidents_qs):
    """
    Build honest descriptive stats from an incident queryset.
    Returns a dict; the template decides how to present + when to warn.
    """
    from django.utils import timezone
    from datetime import timedelta

    total = incidents_qs.count()

    # By danger level
    danger = {1: 0, 2: 0, 3: 0}
    for lvl in incidents_qs.values_list('danger_level', flat=True):
        danger[lvl] = danger.get(lvl, 0) + 1

    # By type (top types)
    type_counts = {}
    for inc in incidents_qs.values('type'):
        t = inc['type']
        type_counts[t] = type_counts.get(t, 0) + 1
    top_types = sorted(type_counts.items(), key=lambda kv: kv[1], reverse=True)[:6]

    # Verified count
    verified = incidents_qs.filter(verified=True).count()

    # Recent (last 7 days)
    week_ago = timezone.now() - timedelta(days=7)
    recent = incidents_qs.filter(timestamp__gte=week_ago).count()

    # Thin-data signal — fewer than 5 reports is not enough to judge
    THIN_THRESHOLD = 5
    is_thin = total < THIN_THRESHOLD

    return {
        'total':       total,
        'danger_high': danger.get(3, 0),
        'danger_med':  danger.get(2, 0),
        'danger_low':  danger.get(1, 0),
        'top_types':   top_types,
        'verified':    verified,
        'recent':      recent,
        'is_thin':     is_thin,
        'thin_threshold': THIN_THRESHOLD,
    }


def area_detail_view(request, slug):
    """
    Dashboard for one area: header (path), honest stats, map, incident list.
    Toggle via ?scope=sub (default, includes descendants) or ?scope=exact.
    """
    area = get_object_or_404(Area, slug=slug)

    scope = request.GET.get('scope', 'sub')  # default to broad/inclusive view
    if scope == 'exact':
        area_ids = [area.id]
    else:
        scope = 'sub'
        area_ids = _descendant_area_ids(area)

    incidents = (
        Incident.objects
        .filter(area_id__in=area_ids, is_hidden=False)   # exclude hidden content
        .select_related('reported_by', 'area')
        .prefetch_related('confirmations')
        .order_by('-timestamp')
    )

    stats = _area_stats(incidents)

    # Map data (XSS-safe), only incidents with coordinates
    incidents_json = [
        {
            'id':           inc.id,
            'title':        escape(inc.title),
            'type':         inc.type,
            'latitude':     inc.latitude,
            'longitude':    inc.longitude,
            'danger_level': inc.danger_level,
            'verified':     inc.verified,
            'detail_url':   f'/incidents/{inc.id}/',
        }
        for inc in incidents
    ]

    # Related safety news for this area (free RSS, production-safe).
    # Tiered: tries this area, then walks up (city → state → country) to the
    # first level with news, and reports which level matched so the template
    # can be honest about how local the news actually is.
    from . import news_service
    news_result = news_service.get_area_news(area, limit=6)

    return render(request, 'area_detail.html', {
        'area':           area,
        'ancestors':      area.ancestors(),
        'scope':          scope,
        'incidents':      incidents,
        'stats':          stats,
        'incidents_json': json.dumps(incidents_json),
        'center_lat':     area.latitude,
        'center_lng':     area.longitude,
        'area_news':         news_result['articles'],
        'news_matched_area': news_result['matched_area'],
        'news_is_widened':   news_result['is_widened'],
    })


def area_search_page_view(request):
    """Landing page with a search bar to find an area, plus top-level browse."""
    # Show countries as browse entry points
    countries = Area.objects.filter(level=Area.LEVEL_COUNTRY).order_by('name')
    return render(request, 'area_search.html', {
        'countries': countries,
    })


# ---------------------------------------------------------------------------
# LANDING
# ---------------------------------------------------------------------------

def landing_view(request):
    if request.user.is_authenticated:
        return redirect('map')
    return render(request, 'landing.html')


def guidelines_view(request):
    """Community guidelines — public page, linked from the report form."""
    return render(request, 'guidelines.html')


# ---------------------------------------------------------------------------
# AUTH
# ---------------------------------------------------------------------------

def register_view(request):
    if request.user.is_authenticated:
        return redirect('map')
    if request.method == 'POST':
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, f'Welcome to SafeRoute, {user.username}!')
            return redirect('map')
    else:
        form = RegisterForm()
    return render(request, 'register.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('map')
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)

            # Remember Me — extend session to 30 days, else expire on browser close
            if request.POST.get('remember'):
                request.session.set_expiry(2592000)  # 30 days in seconds
            else:
                request.session.set_expiry(0)  # expires when browser closes

            next_url = request.POST.get('next') or request.GET.get('next', 'map')
            if not next_url.startswith('/'):
                next_url = 'map'
            return redirect(next_url)
        else:
            messages.error(request, 'Invalid username or password.')
    return render(request, 'login.html')

@require_POST   # Logout MUST be POST to prevent CSRF logout attacks
def logout_view(request):
    logout(request)
    return redirect('login')


# ---------------------------------------------------------------------------
# MAP
# ---------------------------------------------------------------------------

@login_required
def map_view(request):
    # select_related avoids N+1 on reported_by; prefetch_related on confirmations
    incidents = (
        Incident.objects
        .filter(is_hidden=False)          # exclude moderation-hidden content
        .select_related('reported_by')
        .prefetch_related('confirmations')
    )

    incidents_data = [
        {
            'id':           inc.id,
            'title':        escape(inc.title),          # XSS-safe for JS
            'type':         inc.type,
            'description':  escape(inc.description),
            'location':     escape(inc.location),
            'latitude':     inc.latitude,
            'longitude':    inc.longitude,
            'danger_level': inc.danger_level,
            'timestamp':    inc.timestamp.strftime('%B %d, %Y %H:%M'),
            'reported_by':  escape(inc.reported_by.username),
            'verified':     inc.verified,
            'confirmations': inc.confirmations.count(),   # prefetched — no extra query
            'detail_url':   f'/incidents/{inc.id}/',
        }
        for inc in incidents
    ]

    # Safety news via free RSS feeds (production-safe, no API key).
    # region='' shows general safety news; a typed region filters it.
    from . import news_service
    news_articles = news_service.get_safety_news(
        region=request.GET.get('region', ''),
        limit=8,
    )

    return render(request, 'map.html', {
        'incidents':      incidents,
        'incidents_json': json.dumps(incidents_data),
        'news_articles':  news_articles,
    })


def news_api_view(request):
    """
    AJAX endpoint: returns safety news as JSON for a given region.
    Used by the map's location search to refresh the news sidebar in place
    (no page reload) when someone searches/selects a neighbourhood.
    """
    from . import news_service
    region = request.GET.get('region', '').strip()
    articles = news_service.get_safety_news(region=region, limit=8)
    return JsonResponse({
        'region':   region,
        'count':    len(articles),
        'articles': articles,
    })


# ---------------------------------------------------------------------------
# REPORT
# ---------------------------------------------------------------------------

# Allowed video formats + size caps
VIDEO_EXTENSIONS = ('.mp4', '.mov', '.webm', '.m4v', '.ogg', '.ogv')
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.heic', '.bmp')
MAX_PHOTO_BYTES = 10 * 1024 * 1024   # 10MB per photo
MAX_VIDEO_BYTES = 50 * 1024 * 1024   # 50MB per video
MAX_MEDIA_ITEMS = 5                  # total photos + videos per report


def _detect_media_type(uploaded_file):
    """Return 'photo', 'video', or None based on content type / extension."""
    name = (uploaded_file.name or '').lower()
    ctype = (getattr(uploaded_file, 'content_type', '') or '').lower()

    if ctype.startswith('video/') or name.endswith(VIDEO_EXTENSIONS):
        return 'video'
    if ctype.startswith('image/') or name.endswith(IMAGE_EXTENSIONS):
        return 'photo'
    return None


def _save_incident_media(request, incident):
    """
    Save uploaded photos AND videos for an incident.
    Accepts files from both 'photos' (legacy) and 'media' field names.
    Enforces per-type size caps and a total item cap. Skips invalid files
    silently (a bad file shouldn't kill a valid report); flags oversize ones
    via a message.
    """
    files = request.FILES.getlist('media') + request.FILES.getlist('photos')
    saved = 0
    skipped_big = 0

    for f in files:
        if saved >= MAX_MEDIA_ITEMS:
            break

        kind = _detect_media_type(f)
        if kind is None:
            continue  # unknown type — skip

        cap = MAX_VIDEO_BYTES if kind == 'video' else MAX_PHOTO_BYTES
        if f.size > cap:
            skipped_big += 1
            continue

        IncidentMedia.objects.create(
            incident    = incident,
            uploaded_by = request.user,
            media_type  = kind,
            file        = f,
        )
        saved += 1

    if skipped_big:
        messages.warning(
            request,
            f'{skipped_big} file(s) were too large and skipped '
            f'(max {MAX_PHOTO_BYTES // (1024*1024)}MB photo, '
            f'{MAX_VIDEO_BYTES // (1024*1024)}MB video).'
        )
    return saved


# ── Reporting rate limits (per user) ──────────────────────────────────────
# Generous enough that genuine users never hit them, tight enough to stop
# spam/flooding from a single account. Cache-based (no DB writes).
RATE_LIMIT_PER_HOUR = 5
RATE_LIMIT_PER_DAY  = 15

# Number of live news channels shown in the feed (after reports).
# IMPORTANT: keep this equal to the length of NEWS_CHANNELS in feed.html.
NEWS_CHANNEL_COUNT = 4


def _check_report_rate_limit(user):
    """
    Returns (allowed: bool, message: str). Counts this user's recent reports
    using the cache. Does NOT increment — call _record_report() only after a
    report actually succeeds, so failed/invalid submissions don't burn quota.
    """
    from django.core.cache import cache

    hour_key = f'ratelimit:report:hour:{user.id}'
    day_key  = f'ratelimit:report:day:{user.id}'

    hour_count = cache.get(hour_key, 0)
    day_count  = cache.get(day_key, 0)

    if hour_count >= RATE_LIMIT_PER_HOUR:
        return False, (
            f"You've reached the limit of {RATE_LIMIT_PER_HOUR} reports per hour. "
            f"This helps keep SafeRoute free of spam. Please try again later — "
            f"your information is safe."
        )
    if day_count >= RATE_LIMIT_PER_DAY:
        return False, (
            f"You've reached the daily limit of {RATE_LIMIT_PER_DAY} reports. "
            f"This helps keep SafeRoute trustworthy. Please try again tomorrow."
        )
    return True, ''


def _record_report(user):
    """Increment this user's report counters after a successful report."""
    from django.core.cache import cache

    hour_key = f'ratelimit:report:hour:{user.id}'
    day_key  = f'ratelimit:report:day:{user.id}'

    # add() sets the key with TTL only if absent; then incr() bumps it.
    cache.add(hour_key, 0, 60 * 60)        # 1 hour TTL
    cache.add(day_key, 0, 60 * 60 * 24)    # 24 hour TTL
    try:
        cache.incr(hour_key)
        cache.incr(day_key)
    except ValueError:
        # Key expired between add and incr — reset safely
        cache.set(hour_key, 1, 60 * 60)
        cache.set(day_key, 1, 60 * 60 * 24)


@login_required
def report_view(request):
    if request.method == 'POST':
        # Rate-limit check BEFORE processing — stops spam/flooding per account.
        allowed, limit_msg = _check_report_rate_limit(request.user)
        if not allowed:
            messages.error(request, limit_msg)
            return render(request, 'report.html', {'form': IncidentForm(request.POST)})

        # Guidelines acknowledgement is required (also enforced client-side).
        if not request.POST.get('guidelines_ack'):
            messages.error(request, 'Please confirm your report follows the community guidelines.')
            return render(request, 'report.html', {'form': IncidentForm(request.POST)})

        form = IncidentForm(request.POST)

        # Handle custom type — if type not in valid choices, save as-is
        if form.data.get('type') and form.data['type'] not in dict(Incident.INCIDENT_TYPES):
            # Custom type entered — bypass the choices validation
            data          = request.POST.copy()
            # Truncate to max field length and slugify
            custom_type   = data['type'][:50].lower().replace(' ', '_')
            data['type']  = custom_type
            form          = IncidentForm(data)

        if form.is_valid():
            incident             = form.save(commit=False)
            incident.reported_by = request.user

            # Attach structured area (existing pick, new area, or None → free-text fallback)
            incident.area = _resolve_area(request)

            incident.save()

            # Handle media uploads (photos + videos in one batch)
            _save_incident_media(request, incident)

            # Only now count it against the rate limit (successful report).
            _record_report(request.user)

            messages.success(request, 'Incident reported successfully!')
            return redirect('feed')  # send user to feed after reporting
        else:
            messages.error(request, '⚠️ Please fix the errors below.')
    else:
        form = IncidentForm()
    return render(request, 'report.html', {'form': form})


def _resolve_area(request):
    """
    Figure out which Area an incident belongs to, from the POST data.
      • area_id present       → use that existing area
      • new_area_name present → create a new (unverified) area under the
                                 chosen parent (new_area_parent)
      • otherwise             → None (free-text location is the fallback)
    Returns an Area instance or None. Never raises.
    """
    from django.utils.text import slugify

    area_id = request.POST.get('area_id', '').strip()
    if area_id:
        try:
            return Area.objects.get(pk=int(area_id))
        except (Area.DoesNotExist, ValueError):
            pass  # fall through

    new_name = request.POST.get('new_area_name', '').strip()
    if new_name:
        parent_id = request.POST.get('new_area_parent', '').strip()
        parent = None
        if parent_id:
            try:
                parent = Area.objects.get(pk=int(parent_id))
            except (Area.DoesNotExist, ValueError):
                parent = None

        # New area's level = parent.level + 1 (capped at LOCAL); no parent → country
        if parent:
            new_level = min(parent.level + 1, Area.LEVEL_LOCAL)
        else:
            new_level = Area.LEVEL_LOCAL

        # Dedup: reuse if same name+parent already exists
        existing = Area.objects.filter(name__iexact=new_name, parent=parent).first()
        if existing:
            return existing

        base_slug = slugify(f"{parent.name}-{new_name}" if parent else new_name) or "area"
        slug, n = base_slug, 2
        while Area.objects.filter(slug=slug).exists():
            slug = f"{base_slug}-{n}"
            n += 1

        return Area.objects.create(
            name=new_name[:120],
            level=new_level,
            parent=parent,
            slug=slug[:160],
            created_by=request.user,
            is_verified=False,   # user-submitted → needs admin review
        )

    return None


# ---------------------------------------------------------------------------
# INCIDENT LIST
# ---------------------------------------------------------------------------

@login_required
def incident_list_view(request):
    qs = (
        Incident.objects
        .filter(is_hidden=False)          # exclude moderation-hidden content
        .select_related('reported_by')
        .prefetch_related('confirmations')
    )

    incident_type = request.GET.get('type', '').strip()
    if incident_type:
        qs = qs.filter(type=incident_type)

    paginator  = Paginator(qs, 12)               # 12 cards per page
    page_num   = request.GET.get('page', 1)
    incidents  = paginator.get_page(page_num)

    # Build filter tag active-state context
    valid_types = [t[0] for t in Incident.INCIDENT_TYPES]
    active_type = incident_type if incident_type in valid_types else ''

    return render(request, 'incidents.html', {
        'incidents':    incidents,
        'active_type':  active_type,
        'page_obj':     incidents,
    })


# ---------------------------------------------------------------------------
# INCIDENT DETAIL
# ---------------------------------------------------------------------------

@login_required
def incident_detail_view(request, pk):
    incident = get_object_or_404(
        Incident.objects.select_related('reported_by').prefetch_related('confirmations', 'disputes', 'comments__author'),
        pk=pk
    )

    # Hidden incidents are not viewable by the public — only staff (for moderation).
    if incident.is_hidden and not request.user.is_staff:
        messages.error(request, 'This report is no longer available.')
        return redirect('feed')
    comments      = incident.comments.all()
    comment_form  = CommentForm()
    has_confirmed = incident.confirmations.filter(id=request.user.id).exists()
    has_disputed  = incident.disputes.filter(id=request.user.id).exists()
    has_flagged   = incident.flags.filter(flagged_by=request.user).exists() if request.user.is_authenticated else False

    if request.method == 'POST':
        comment_form = CommentForm(request.POST)
        if comment_form.is_valid():
            comment          = comment_form.save(commit=False)
            comment.incident = incident
            comment.author   = request.user
            comment.save()
            messages.success(request, '💬 Comment added!')
            return redirect('incident_detail', pk=pk)

    return render(request, 'incident_detail.html', {
        'incident':       incident,
        'comments':       comments,
        'comment_form':   comment_form,
        'has_confirmed':  has_confirmed,
        'has_disputed':   has_disputed,
        'has_flagged':    has_flagged,
        'confirm_count':  incident.confirmations.count(),
        'dispute_count':  incident.disputes.count(),
        'net_score':      incident.net_score(),
    })


# ---------------------------------------------------------------------------
# CONFIRM / DISPUTE (AJAX — POST only)
# A user may confirm OR dispute, never both. Each action recomputes whether
# the incident is auto-verified.
# ---------------------------------------------------------------------------

@login_required
@require_POST
def confirm_incident_view(request, pk):
    incident = get_object_or_404(Incident, pk=pk)
    user     = request.user

    if incident.confirmations.filter(id=user.id).exists():
        # Toggle off — un-confirm
        incident.confirmations.remove(user)
        confirmed = False
    else:
        # Confirm, and clear any existing dispute (can't be both)
        incident.confirmations.add(user)
        incident.disputes.remove(user)
        confirmed = True

    verified = incident.recompute_verified()

    return JsonResponse({
        'confirmed':      confirmed,
        'disputed':       False,
        'confirm_count':  incident.confirmations.count(),
        'dispute_count':  incident.disputes.count(),
        'net_score':      incident.net_score(),
        'verified':       verified,
    })


@login_required
@require_POST
def dispute_incident_view(request, pk):
    incident = get_object_or_404(Incident, pk=pk)
    user     = request.user

    if incident.disputes.filter(id=user.id).exists():
        # Toggle off — un-dispute
        incident.disputes.remove(user)
        disputed = False
    else:
        # Dispute, and clear any existing confirmation (can't be both)
        incident.disputes.add(user)
        incident.confirmations.remove(user)
        disputed = True

    verified = incident.recompute_verified()

    return JsonResponse({
        'confirmed':      False,
        'disputed':       disputed,
        'confirm_count':  incident.confirmations.count(),
        'dispute_count':  incident.disputes.count(),
        'net_score':      incident.net_score(),
        'verified':       verified,
    })


@login_required
@require_POST
def flag_incident_view(request, pk):
    """
    Flag an incident as abusive/inappropriate (distinct from dispute).
    One flag per user per incident; flagging again removes the flag (toggle).
    Records to the moderation queue; content stays visible until reviewed.
    """
    incident = get_object_or_404(Incident, pk=pk)
    reason   = request.POST.get('reason', '')
    note     = request.POST.get('note', '')[:300]

    valid_reasons = dict(Flag.REASON_CHOICES)
    if reason not in valid_reasons:
        return JsonResponse({'error': 'Invalid reason.'}, status=400)

    existing = Flag.objects.filter(incident=incident, flagged_by=request.user).first()
    if existing:
        # Toggle off — withdraw the flag
        existing.delete()
        return JsonResponse({
            'flagged':     False,
            'flag_count':  incident.flags.count(),
            'message':     'Your report has been withdrawn.',
        })

    Flag.objects.create(
        incident   = incident,
        flagged_by = request.user,
        reason     = reason,
        note       = note,
    )
    return JsonResponse({
        'flagged':     True,
        'flag_count':  incident.flags.count(),
        'message':     'Thank you. This report has been sent for review.',
    })


# ---------------------------------------------------------------------------
# MODERATION QUEUE  (staff only)
# ---------------------------------------------------------------------------

@staff_member_required
def moderation_queue_view(request):
    """
    The moderation queue: incidents that have been flagged, with their flags,
    so staff can review and act (dismiss flags or hide content).
    Shows pending-flag incidents by default; can also show hidden content.
    """
    from django.db.models import Count, Q

    view = request.GET.get('view', 'pending')  # 'pending' | 'hidden' | 'all'

    if view == 'hidden':
        # Currently hidden incidents
        incidents = (
            Incident.objects.filter(is_hidden=True)
            .select_related('reported_by', 'hidden_by', 'area')
            .prefetch_related('flags__flagged_by', 'media')
            .order_by('-hidden_at')
        )
    else:
        # Incidents with at least one PENDING flag, not already hidden
        incidents = (
            Incident.objects
            .filter(flags__status='pending', is_hidden=False)
            .annotate(pending_flag_count=Count('flags', filter=Q(flags__status='pending')))
            .select_related('reported_by', 'area')
            .prefetch_related('flags__flagged_by', 'media')
            .distinct()
            .order_by('-pending_flag_count', '-timestamp')
        )

    # Counts for the tab badges
    pending_count = (
        Incident.objects.filter(flags__status='pending', is_hidden=False)
        .distinct().count()
    )
    hidden_count = Incident.objects.filter(is_hidden=True).count()

    return render(request, 'moderation.html', {
        'incidents':     incidents,
        'view':          view,
        'pending_count': pending_count,
        'hidden_count':  hidden_count,
    })


@staff_member_required
@require_POST
def moderation_hide_view(request, pk):
    """Hide an incident (soft — reversible). Marks its flags as actioned."""
    from django.utils import timezone

    incident = get_object_or_404(Incident, pk=pk)
    incident.is_hidden     = True
    incident.hidden_at     = timezone.now()
    incident.hidden_by     = request.user
    incident.hidden_reason = request.POST.get('reason', '')[:200]
    incident.save()

    # Mark all this incident's flags as actioned
    incident.flags.filter(status='pending').update(
        status='actioned', reviewed_at=timezone.now()
    )

    messages.success(request, f'"{incident.title}" has been hidden from public view.')
    return redirect('moderation_queue')


@staff_member_required
@require_POST
def moderation_unhide_view(request, pk):
    """Un-hide an incident — restore it to public view."""
    incident = get_object_or_404(Incident, pk=pk)
    incident.is_hidden     = False
    incident.hidden_at     = None
    incident.hidden_by     = None
    incident.hidden_reason = ''
    incident.save()

    messages.success(request, f'"{incident.title}" has been restored to public view.')
    return redirect('moderation_queue')


@staff_member_required
@require_POST
def moderation_dismiss_view(request, pk):
    """Dismiss the flags on an incident — content is fine, leave it up."""
    from django.utils import timezone

    incident = get_object_or_404(Incident, pk=pk)
    incident.flags.filter(status='pending').update(
        status='reviewed', reviewed_at=timezone.now()
    )

    messages.success(request, f'Flags on "{incident.title}" dismissed — content kept.')
    return redirect('moderation_queue')

@login_required
def profile_view(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)

    if request.method == 'POST':
        user_form    = UserUpdateForm(request.POST, instance=request.user)
        profile_form = UserProfileForm(request.POST, request.FILES, instance=profile)

        if user_form.is_valid() and profile_form.is_valid():
            user_form.save()
            prof = profile_form.save(commit=False)

            # Handle avatar removal ← ADD THIS BLOCK
            if request.POST.get('remove_avatar') == '1':
                if prof.avatar:
                    prof.avatar.delete(save=False)
                    prof.avatar = None

            # Handle cropped base64 avatar if provided
            cropped_data = request.POST.get('avatar_cropped', '')

            
            if cropped_data and cropped_data.startswith('data:image'):
                try:
                    # Strip the data:image/jpeg;base64, prefix
                    format, imgstr = cropped_data.split(';base64,')
                    ext = format.split('/')[-1]  # jpeg or png
                    filename = f"avatar_{request.user.id}.{ext}"
                    prof.avatar = ContentFile(base64.b64decode(imgstr), name=filename)
                except Exception:
                    pass  # If decode fails, keep existing avatar

            prof.save()
            messages.success(request, '✅ Profile updated!')
            return redirect('profile')
    else:
        user_form    = UserUpdateForm(instance=request.user)
        profile_form = UserProfileForm(instance=profile)

    user_incidents = (
        Incident.objects
        .filter(reported_by=request.user)
        .select_related('reported_by')
        .order_by('-timestamp')[:10]
    )

    return render(request, 'profile.html', {
        'user_form':      user_form,
        'form':           profile_form,
        'profile':        profile,
        'user_incidents': user_incidents,
        'total_reports':  Incident.objects.filter(reported_by=request.user).count(),
        'total_confirmations': sum(inc.confirmation_count() for inc in user_incidents),
    })



@login_required
def edit_incident_view(request, pk):
    incident = get_object_or_404(Incident, pk=pk)

    # Only the owner can edit
    if incident.reported_by != request.user:
        messages.error(request, '⛔ You can only edit your own reports.')
        return redirect('incident_detail', pk=pk)

    if request.method == 'POST':
        form = IncidentForm(request.POST, instance=incident)
        if form.is_valid():
            form.save()
            messages.success(request, '✅ Incident updated successfully!')
            return redirect('incident_detail', pk=pk)
        else:
            messages.error(request, '⚠️ Please fix the errors below.')
    else:
        form = IncidentForm(instance=incident)

    return render(request, 'edit_incident.html', {
        'form':     form,
        'incident': incident,
    })


@login_required
@require_POST
def delete_incident_view(request, pk):
    incident = get_object_or_404(Incident, pk=pk)

    # Only the owner can delete
    if incident.reported_by != request.user:
        messages.error(request, '⛔ You can only delete your own reports.')
        return redirect('incident_detail', pk=pk)

    incident.delete()
    messages.success(request, '🗑️ Incident deleted successfully.')
    return redirect('incidents')

# ---------------------------------------------------------------------------
# FEED VIEW — TikTok-style
# Accessible to all, but comment/save requires login
# ---------------------------------------------------------------------------

def feed_view(request):
    incidents = (
        Incident.objects
        .filter(is_hidden=False)          # exclude moderation-hidden content
        .select_related('reported_by', 'reported_by__profile')
        .prefetch_related('confirmations', 'disputes', 'media', 'comments')
        .order_by('-timestamp')
    )

    # Build a SINGLE mixed feed: incident cards and live-news cards blended
    # together. Each entry is tagged by 'kind' so the template renders the
    # right card. News is sprinkled throughout (not glued after every incident,
    # not clumped at the end) and keeps flowing even when incidents are few.
    feed_stream = []
    news_counter = 0   # rotates through the channels

    def add_news_card():
        nonlocal news_counter
        feed_stream.append({
            'kind':        'news',
            'news_index':  news_counter,
        })
        news_counter += 1

    for inc in incidents:
        photo         = inc.primary_photo()
        video         = inc.primary_video()
        has_confirmed = inc.confirmations.filter(id=request.user.id).exists() if request.user.is_authenticated else False
        has_disputed  = inc.disputes.filter(id=request.user.id).exists() if request.user.is_authenticated else False
        is_saved = False
        if request.user.is_authenticated:
            is_saved = SavedIncident.objects.filter(user=request.user, incident=inc).exists()
        has_flagged = inc.flags.filter(flagged_by=request.user).exists() if request.user.is_authenticated else False

        feed_stream.append({
            'kind':           'incident',
            'incident':       inc,
            'photo':          photo,
            'video':          video,
            'has_confirmed':  has_confirmed,
            'has_disputed':   has_disputed,
            'has_flagged':    has_flagged,
            'is_saved':       is_saved,
            'confirm_count':  inc.confirmations.count(),
            'dispute_count':  inc.disputes.count(),
            'net_score':      inc.net_score(),
            'total_comments': inc.comments.count(),
            'total_saves':    inc.saved_by.count(),
            'comment_form':   CommentForm(),
        })

        # Strict alternating: a live-news card after EVERY incident.
        add_news_card()

    # Once incidents run out, keep the news flowing through the rest of the
    # feed (channels rotate). No hard cap — a long run so it never feels empty.
    for _ in range(12):
        add_news_card()

    return render(request, 'feed.html', {
        'feed_stream': feed_stream,
    })


# ---------------------------------------------------------------------------
# SAVE INCIDENT — toggle bookmark
# ---------------------------------------------------------------------------

@require_POST
def save_incident_view(request, pk):
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'login_required', 'message': 'Login to save incidents'}, status=401)

    incident = get_object_or_404(Incident, pk=pk)
    saved, created = SavedIncident.objects.get_or_create(user=request.user, incident=incident)

    if not created:
        saved.delete()
        is_saved = False
    else:
        is_saved = True

    return JsonResponse({
        'saved':       is_saved,
        'total_saves': incident.saved_by.count(),
    })


# ---------------------------------------------------------------------------
# ADD PHOTO — attach photo to existing incident
# ---------------------------------------------------------------------------

@login_required
@require_POST
def add_photo_view(request, pk):
    incident = get_object_or_404(Incident, pk=pk)

    if incident.reported_by != request.user:
        return JsonResponse({'error': 'Permission denied'}, status=403)

    photo = request.FILES.get('photo')
    if not photo:
        return JsonResponse({'error': 'No photo provided'}, status=400)

    # Max 20MB per photo
    if photo.size > 20 * 1024 * 1024:
        return JsonResponse({'error': 'Photo too large. Max 20MB.'}, status=400)

    media = IncidentMedia.objects.create(
        incident    = incident,
        uploaded_by = request.user,
        media_type  = 'photo',
        file        = photo,
        caption     = request.POST.get('caption', ''),
    )

    return JsonResponse({
        'success': True,
        'url':     media.file.url,
        'id':      media.id,
    })


# ---------------------------------------------------------------------------
# FEED COMMENT — AJAX endpoint used by feed.html
# ---------------------------------------------------------------------------

@login_required
@require_POST
def feed_comment_view(request, pk):
    incident = get_object_or_404(Incident, pk=pk)
    body     = request.POST.get('body', '').strip()

    if not body:
        return JsonResponse({'error': 'Empty comment'}, status=400)
    if len(body) > 2000:
        return JsonResponse({'error': 'Comment too long'}, status=400)

    comment = Comment.objects.create(
        incident = incident,
        author   = request.user,
        body     = body,
    )

    return JsonResponse({
        'success': True,
        'author':  request.user.username,
        'body':    comment.body,
        'time':    comment.timestamp.isoformat(),
    })


