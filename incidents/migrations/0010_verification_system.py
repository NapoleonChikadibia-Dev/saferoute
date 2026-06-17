# Round 2a — Verification system migration (DATA-PRESERVING)
#
# IMPORTANT: This is a hand-corrected version of what `makemigrations` produces.
# The auto-generated version does RemoveField(likes) FIRST, which DROPS all
# existing likes data before `confirmations` exists. This version instead:
#
#   1. Adds `confirmations`, `disputes`, `verified_override` (new empty fields)
#   2. COPIES every existing like into `confirmations` (data preserved!)
#   3. THEN removes the old `likes` field
#
# So your existing likes become confirmations with zero data loss.
#
# PLACEMENT:
#   - Rename this file to follow your numbering. Your latest is 0009, so this
#     becomes:  0010_verification_system.py
#   - Put it in incidents/migrations/
#   - The dependency below points at 0009 (your auto-match migration).

from django.conf import settings
from django.db import migrations, models


def copy_likes_to_confirmations(apps, schema_editor):
    """Copy every existing like into the new confirmations M2M."""
    Incident = apps.get_model('incidents', 'Incident')
    count = 0
    for incident in Incident.objects.all():
        likers = list(incident.likes.all())
        if likers:
            incident.confirmations.add(*likers)
            count += len(likers)
    print(f"\n  [verification] Migrated {count} like(s) into confirmations.")


def reverse_copy(apps, schema_editor):
    """Reverse: copy confirmations back into likes."""
    Incident = apps.get_model('incidents', 'Incident')
    for incident in Incident.objects.all():
        confirmers = list(incident.confirmations.all())
        if confirmers:
            incident.likes.add(*confirmers)


class Migration(migrations.Migration):

    dependencies = [
        # TODO: confirm this matches your latest migration filename (without .py)
        ('incidents', '0009_automatch_incident_areas'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # 1. Add the new fields FIRST (so confirmations exists before we copy)
        migrations.AddField(
            model_name='incident',
            name='confirmations',
            field=models.ManyToManyField(blank=True, related_name='confirmed_incidents', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='incident',
            name='disputes',
            field=models.ManyToManyField(blank=True, related_name='disputed_incidents', to=settings.AUTH_USER_MODEL),
        ),
        migrations.AddField(
            model_name='incident',
            name='verified_override',
            field=models.BooleanField(blank=True, default=None, help_text='Admin override. Null = automatic.', null=True),
        ),

        # 2. Copy existing likes -> confirmations (DATA PRESERVATION)
        migrations.RunPython(copy_likes_to_confirmations, reverse_copy),

        # 3. NOW it's safe to remove the old likes field
        migrations.RemoveField(
            model_name='incident',
            name='likes',
        ),
    ]
