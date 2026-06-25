# incidents/models.py

from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


# ---------------------------------------------------------------------------
# AREA  — hierarchical place model (Country → State → City → Local Area)
# Self-referencing: every Area points to its parent, except countries.
# (Restored to match migration 0008 — table already exists with 227 rows.)
# ---------------------------------------------------------------------------

class Area(models.Model):
    LEVEL_COUNTRY = 1
    LEVEL_STATE   = 2
    LEVEL_CITY    = 3
    LEVEL_LOCAL   = 4
    LEVEL_CHOICES = [
        (LEVEL_COUNTRY, 'Country'),
        (LEVEL_STATE,   'State'),
        (LEVEL_CITY,    'City'),
        (LEVEL_LOCAL,   'Local Area'),
    ]

    name        = models.CharField(max_length=120, db_index=True)
    level       = models.IntegerField(choices=LEVEL_CHOICES, db_index=True)
    parent      = models.ForeignKey(
                      'self',
                      on_delete=models.CASCADE,
                      null=True, blank=True,
                      related_name='children'
                  )
    slug        = models.SlugField(max_length=160)

    latitude    = models.FloatField(null=True, blank=True)
    longitude   = models.FloatField(null=True, blank=True)

    created_by  = models.ForeignKey(
                      User, on_delete=models.SET_NULL,
                      null=True, blank=True, related_name='created_areas'
                  )
    is_verified = models.BooleanField(default=False, db_index=True)
    # Auto-created (from a dropped pin via geocoding) areas are usable immediately
    # but flagged so an admin can audit what geocoding produced.
    needs_review = models.BooleanField(default=False, db_index=True,
                                       help_text='Auto-created from a pin; awaiting admin audit.')
    created_at  = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering        = ['level', 'name']
        unique_together = (('name', 'parent'),)
        indexes = [
            models.Index(fields=['level', 'name'],   name='incidents_a_level_c3ef6e_idx'),
            models.Index(fields=['parent', 'level'], name='incidents_a_parent__36434b_idx'),
            models.Index(fields=['slug'],            name='incidents_a_slug_4bddf7_idx'),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_level_display()})"

    def ancestors(self):
        """Return list of ancestors from country down to this area's parent."""
        chain, node = [], self.parent
        while node is not None:
            chain.append(node)
            node = node.parent
        return list(reversed(chain))

    def full_path(self):
        """Human-readable breadcrumb: 'Nigeria → Lagos → Ikeja → Allen Avenue'."""
        return ' → '.join([a.name for a in self.ancestors()] + [self.name])

    @property
    def country(self):
        node = self
        while node and node.level > self.LEVEL_COUNTRY:
            node = node.parent
        return node

    def incident_count(self):
        """Total incidents in this area AND all its descendants."""
        ids = [self.id]
        frontier = [self.id]
        while frontier:
            kids = list(Area.objects.filter(parent_id__in=frontier).values_list('id', flat=True))
            ids.extend(kids)
            frontier = kids
        return Incident.objects.filter(area_id__in=ids).count()


# ---------------------------------------------------------------------------
# USER PROFILE
# ---------------------------------------------------------------------------

class UserProfile(models.Model):
    user       = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    bio        = models.TextField(blank=True, default='')
    avatar     = models.ImageField(upload_to='avatars/', blank=True, null=True)
    sos_phone  = models.CharField(max_length=20, blank=True, default='',
                                  help_text='Emergency contact number for SOS alerts')
    location   = models.CharField(max_length=100, blank=True, default='',
                                  help_text='City or neighbourhood')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Profile({self.user.username})"

    def total_reports(self):
        return self.user.incident_set.count()


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, 'profile'):
        instance.profile.save()


# ---------------------------------------------------------------------------
# INCIDENT
# ---------------------------------------------------------------------------

class Incident(models.Model):
    INCIDENT_TYPES = [
        ('robbery',       'Robbery'),
        ('harassment',    'Harassment'),
        ('accident',      'Accident'),
        ('poor_lighting', 'Poor Lighting'),
        ('suspicious',    'Suspicious Activity'),
        ('flood',         'Flood'),
        ('fire',          'Fire'),
        ('assault',       'Assault'),
        ('vandalism',     'Vandalism'),
        ('kidnapping',    'Kidnapping'),
        ('other',         'Other'),
    ]

    DANGER_LEVELS = [
        (1, 'Low'),
        (2, 'Medium'),
        (3, 'High'),
    ]

    title        = models.CharField(max_length=200)
    type         = models.CharField(max_length=50, choices=INCIDENT_TYPES, db_index=True)
    description  = models.TextField()
    latitude     = models.FloatField()
    longitude    = models.FloatField()
    location     = models.CharField(max_length=200)
    area         = models.ForeignKey(
                       'Area',
                       on_delete=models.SET_NULL,
                       null=True, blank=True,
                       related_name='incidents',
                       help_text='Structured area this incident belongs to'
                   )
    danger_level = models.IntegerField(choices=DANGER_LEVELS, default=1, db_index=True)
    reported_by  = models.ForeignKey(User, on_delete=models.CASCADE,
                                     related_name='incidents')
    timestamp    = models.DateTimeField(auto_now_add=True, db_index=True)
    verified     = models.BooleanField(default=False, db_index=True)

    # Admin override: if set, it WINS over the auto-verification logic.
    #   None  → no override, use automatic confirmation-based logic
    #   True  → force verified regardless of counts
    #   False → force un-verified regardless of counts
    verified_override = models.BooleanField(null=True, blank=True, default=None,
                                            help_text='Admin override. Null = automatic.')

    # MODERATION (soft-hide — reversible, auditable)
    # is_hidden=True removes the incident from all public views (feed, map,
    # areas, detail) but keeps the record in the database. Reversible.
    is_hidden       = models.BooleanField(default=False,
                                          help_text='Hidden by moderation. Removed from public views but kept.')
    hidden_at       = models.DateTimeField(null=True, blank=True)
    hidden_by       = models.ForeignKey(User, null=True, blank=True,
                                        on_delete=models.SET_NULL,
                                        related_name='hidden_incidents')
    hidden_reason   = models.CharField(max_length=200, blank=True, default='')

    # TRUST SIGNALS
    # confirmations: users who witnessed / can confirm this happened (truth signal)
    # disputes:      users who believe this report is inaccurate / false
    # A user may confirm OR dispute, never both (enforced in the views).
    confirmations = models.ManyToManyField(
                        User,
                        related_name='confirmed_incidents',
                        blank=True
                    )
    disputes      = models.ManyToManyField(
                        User,
                        related_name='disputed_incidents',
                        blank=True
                    )

    def __str__(self):
        return f"[{self.get_type_display()}] {self.title} — {self.location}"

    def confirmation_count(self):
        return self.confirmations.count()

    def dispute_count(self):
        return self.disputes.count()

    def net_score(self):
        """Trust score = confirmations minus disputes."""
        return self.confirmations.count() - self.disputes.count()

    # Backwards-compat shim: some old code/templates may still call total_likes.
    # Maps to confirmation_count so nothing breaks during the transition.
    def total_likes(self):
        return self.confirmation_count()

    def recompute_verified(self):
        """
        Decide verified status. Admin override always wins; otherwise the
        automatic rule applies: net score (confirmations - disputes) must
        reach the configured threshold.

        New information can REVOKE verification — if disputes pull the net
        score back below threshold, the badge is removed. For a safety app,
        being able to take back a 'verified' badge matters.

        Saves only if the value actually changed. Returns the new bool.
        """
        from django.conf import settings
        threshold = getattr(settings, 'VERIFICATION_THRESHOLD', 3)

        if self.verified_override is not None:
            new_value = self.verified_override
        else:
            new_value = self.net_score() >= threshold

        if new_value != self.verified:
            self.verified = new_value
            self.save(update_fields=['verified'])
        return new_value

    def primary_photo(self):
        """Return the first photo attached to this incident, or None."""
        return self.media.filter(media_type='photo').first()

    def primary_video(self):
        """Return the first video attached to this incident, or None."""
        return self.media.filter(media_type='video').first()

    def primary_media(self):
        """Return the first media item (video preferred for feed), or None."""
        return self.media.filter(media_type='video').first() or self.media.filter(media_type='photo').first()

    def has_video(self):
        return self.media.filter(media_type='video').exists()

    class Meta:
        ordering = ['-timestamp']
        indexes  = [
            models.Index(fields=['type', '-timestamp']),
            models.Index(fields=['danger_level', '-timestamp']),
        ]


# ---------------------------------------------------------------------------
# INCIDENT MEDIA
# Photos attached to an incident — Phase 1 (photos only)
# ---------------------------------------------------------------------------

class IncidentMedia(models.Model):
    MEDIA_TYPES = [
        ('photo', 'Photo'),
        ('video', 'Video'),
    ]

    incident    = models.ForeignKey(
                      Incident,
                      on_delete=models.CASCADE,
                      related_name='media'
                  )
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE,
                                    related_name='incident_media')
    media_type  = models.CharField(max_length=10, choices=MEDIA_TYPES, default='photo')
    # FileField (not ImageField) so it accepts both images and videos.
    file        = models.FileField(upload_to='incident_media/')
    caption     = models.CharField(max_length=300, blank=True, default='')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.media_type} on '{self.incident.title}'"

    def is_video(self):
        return self.media_type == 'video'

    def is_photo(self):
        return self.media_type == 'photo'

    class Meta:
        ordering = ['uploaded_at']


# ---------------------------------------------------------------------------
# SAVED INCIDENT
# Users bookmarking incidents from the feed
# ---------------------------------------------------------------------------

class SavedIncident(models.Model):
    user      = models.ForeignKey(User, on_delete=models.CASCADE,
                                  related_name='saved_incidents')
    incident  = models.ForeignKey(Incident, on_delete=models.CASCADE,
                                  related_name='saved_by')
    saved_at  = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} saved '{self.incident.title}'"

    class Meta:
        unique_together = ('user', 'incident')  # can't save same twice
        ordering        = ['-saved_at']


# ---------------------------------------------------------------------------
# COMMENT
# ---------------------------------------------------------------------------

class Comment(models.Model):
    incident   = models.ForeignKey(
                     Incident,
                     on_delete=models.CASCADE,
                     related_name='comments'
                 )
    author     = models.ForeignKey(User, on_delete=models.CASCADE,
                                   related_name='comments')
    body       = models.TextField()
    timestamp  = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Comment by {self.author.username} on '{self.incident.title}'"

    class Meta:
        ordering = ['timestamp']


# ---------------------------------------------------------------------------
# FLAG  (abuse / inappropriate reporting — distinct from dispute)
# ---------------------------------------------------------------------------

class Flag(models.Model):
    """
    A user flagging an incident as abusive or inappropriate.

    Distinct from 'dispute' (which means "I don't think this is accurate").
    A flag means "this content shouldn't be here" — fake/spam or inappropriate.
    Flags feed the admin moderation queue; content stays visible until an
    admin reviews it.
    """
    REASON_CHOICES = [
        ('fake',          'Fake or spam'),
        ('inappropriate', 'Inappropriate or harmful'),
    ]

    STATUS_CHOICES = [
        ('pending',   'Pending review'),
        ('reviewed',  'Reviewed — no action'),
        ('actioned',  'Reviewed — content removed'),
    ]

    incident    = models.ForeignKey(
                      Incident,
                      on_delete=models.CASCADE,
                      related_name='flags'
                  )
    flagged_by  = models.ForeignKey(User, on_delete=models.CASCADE,
                                    related_name='flags_raised')
    reason      = models.CharField(max_length=20, choices=REASON_CHOICES)
    note        = models.CharField(max_length=300, blank=True, default='')
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES,
                                   default='pending')
    created_at  = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.get_reason_display()} flag on '{self.incident.title}' by {self.flagged_by.username}"

    class Meta:
        # One flag per user per incident — no flag-spamming.
        unique_together = ('incident', 'flagged_by')
        ordering        = ['-created_at']
