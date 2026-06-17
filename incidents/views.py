# incidents/views.py

import json
import logging
import base64
from django.core.files.base import ContentFile

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, logout, authenticate
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.views.decorators.cache import cache_page
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.utils.html import escape

from .forms import RegisterForm, IncidentForm, CommentForm, UserProfileForm, UserUpdateForm
from .models import Incident, Comment, UserProfile, IncidentMedia, SavedIncident

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# LANDING
# ---------------------------------------------------------------------------

def landing_view(request):
    if request.user.is_authenticated:
        return redirect('map')
    return render(request, 'landing.html')


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
        .select_related('reported_by')
        .prefetch_related('confirmations')
        .all()
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

    news_articles = _fetch_news(request.GET.get('region', 'safety crime'))

    return render(request, 'map.html', {
        'incidents':      incidents,
        'incidents_json': json.dumps(incidents_data),
        'news_articles':  news_articles,
    })


def _fetch_news(region: str) -> list:
    """Fetch safety news from NewsAPI. Returns [] on any failure."""
    try:
        import requests
        from django.conf import settings

        api_key = getattr(settings, 'NEWS_API_KEY', '')
        if not api_key:
            return []

        resp = requests.get(
            'https://newsapi.org/v2/everything',
            params={
                'q':        f'{region} crime safety attack',
                'sortBy':   'publishedAt',
                'language': 'en',
                'pageSize': 8,
                'apiKey':   api_key,
            },
            timeout=5,
        )
        resp.raise_for_status()
        data = resp.json()

        if data.get('status') != 'ok':
            return []

        return [
            {
                'title':       a['title'],
                'description': (a.get('description') or '')[:120],
                'url':         a['url'],
                'source':      a['source']['name'],
                'image':       a.get('urlToImage', ''),
                'published':   (a.get('publishedAt') or '')[:10],
            }
            for a in data.get('articles', [])
            if a.get('title') and a.get('url')
        ]
    except Exception as exc:
        logger.warning("NewsAPI fetch failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# REPORT
# ---------------------------------------------------------------------------

@login_required
def report_view(request):
    if request.method == 'POST':
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
            incident.save()

            # Handle photo uploads
            photos = request.FILES.getlist('photos')
            for photo in photos[:5]:
                if photo.size <= 10 * 1024 * 1024:
                    IncidentMedia.objects.create(
                        incident    = incident,
                        uploaded_by = request.user,
                        media_type  = 'photo',
                        file        = photo,
                    )

            messages.success(request, 'Incident reported successfully!')
            return redirect('feed')  # send user to feed after reporting

            messages.success(request, '✅ Incident reported successfully!')
            return redirect('incident_detail', pk=incident.id)
        else:
            messages.error(request, '⚠️ Please fix the errors below.')
    else:
        form = IncidentForm()
    return render(request, 'report.html', {'form': form})


# ---------------------------------------------------------------------------
# INCIDENT LIST
# ---------------------------------------------------------------------------

@login_required
def incident_list_view(request):
    qs = (
        Incident.objects
        .select_related('reported_by')
        .prefetch_related('confirmations')
        .all()
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
    comments      = incident.comments.all()
    comment_form  = CommentForm()
    has_confirmed = incident.confirmations.filter(id=request.user.id).exists()
    has_disputed  = incident.disputes.filter(id=request.user.id).exists()

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


# ---------------------------------------------------------------------------
# USER PROFILE
# ---------------------------------------------------------------------------

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
        .select_related('reported_by', 'reported_by__profile')
        .prefetch_related('confirmations', 'disputes', 'media', 'comments')
        .order_by('-timestamp')
    )

    # Build feed data
    feed_items = []
    for inc in incidents:
        photo         = inc.primary_photo()
        has_confirmed = inc.confirmations.filter(id=request.user.id).exists() if request.user.is_authenticated else False
        has_disputed  = inc.disputes.filter(id=request.user.id).exists() if request.user.is_authenticated else False
        is_saved = False
        if request.user.is_authenticated:
            is_saved = SavedIncident.objects.filter(user=request.user, incident=inc).exists()

        feed_items.append({
            'incident':       inc,
            'photo':          photo,
            'has_confirmed':  has_confirmed,
            'has_disputed':   has_disputed,
            'is_saved':       is_saved,
            'confirm_count':  inc.confirmations.count(),
            'dispute_count':  inc.disputes.count(),
            'net_score':      inc.net_score(),
            'total_comments': inc.comments.count(),
            'total_saves':    inc.saved_by.count(),
            'comment_form':   CommentForm(),
        })

    return render(request, 'feed.html', {
        'feed_items': feed_items,
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


