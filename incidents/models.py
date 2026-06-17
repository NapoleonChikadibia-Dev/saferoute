# incidents/models.py

from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver


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
    ]

    incident    = models.ForeignKey(
                      Incident,
                      on_delete=models.CASCADE,
                      related_name='media'
                  )
    uploaded_by = models.ForeignKey(User, on_delete=models.CASCADE,
                                    related_name='incident_media')
    media_type  = models.CharField(max_length=10, choices=MEDIA_TYPES, default='photo')
    file        = models.ImageField(upload_to='incident_media/')
    caption     = models.CharField(max_length=300, blank=True, default='')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.media_type} on '{self.incident.title}'"

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
