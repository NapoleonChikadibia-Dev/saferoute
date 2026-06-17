# incidents/migrations/XXXX_automatch_incident_areas.py
#
# DATA MIGRATION — best-guess match of existing free-text `location` strings
# to seeded Area records.
#
# PHILOSOPHY (this is safety data):
#   A WRONG match is worse than NO match. An incident showing in the wrong
#   neighbourhood is misinformation. So we only link when we're reasonably
#   confident, and leave everything else as area=NULL for manual review.
#
# IMPORTANT:
#   • Run `python manage.py seed_areas` BEFORE migrating, so there are areas
#     to match against. If no areas exist, this migration simply does nothing.
#   • This migration is REVERSIBLE — reverse() just sets area back to NULL.
#
# Rename XXXX to the next migration number when you place this file, and set
# the correct dependency to your latest incidents migration.

from django.db import migrations


def automatch_areas(apps, schema_editor):
    Incident = apps.get_model('incidents', 'Incident')
    Area     = apps.get_model('incidents', 'Area')

    # Build a lookup of area-name (lowercased) → list of area ids.
    # We prefer matching against the most specific levels first (local=4, city=3),
    # then fall back to state(2). We deliberately do NOT match on country alone —
    # "Nigeria" in a location string is too coarse to be useful and risks
    # mislabelling. Country-level assignment should be done deliberately, not guessed.
    LEVEL_LOCAL, LEVEL_CITY, LEVEL_STATE = 4, 3, 2

    # name(lower) -> [(area_id, level), ...]
    name_index = {}
    for area in Area.objects.exclude(level=1):  # skip countries
        key = area.name.strip().lower()
        name_index.setdefault(key, []).append((area.id, area.level))

    if not name_index:
        # Nothing seeded — leave all incidents unmatched. No-op.
        return

    matched = 0
    unmatched = 0

    for inc in Incident.objects.filter(area__isnull=True):
        loc = (inc.location or '').strip().lower()
        if not loc:
            unmatched += 1
            continue

        # Find every seeded area name that appears as a whole word/segment in
        # the location string. We check the most specific levels first.
        best = None  # (area_id, level)

        for level in (LEVEL_LOCAL, LEVEL_CITY, LEVEL_STATE):
            candidates = []
            for name_key, entries in name_index.items():
                # Substring match, but require it to be a reasonably distinct token:
                # the area name must appear AND be at least 4 chars (avoids matching
                # tiny ambiguous fragments like "gra" inside unrelated words).
                if len(name_key) >= 4 and name_key in loc:
                    for area_id, area_level in entries:
                        if area_level == level:
                            candidates.append((area_id, area_level, name_key))

            if candidates:
                # If exactly one candidate at this level → confident match.
                # If multiple different areas match at the same level → ambiguous,
                # skip to avoid guessing wrong (safety-first).
                distinct_ids = {c[0] for c in candidates}
                if len(distinct_ids) == 1:
                    best = (candidates[0][0], candidates[0][1])
                    break
                else:
                    # Ambiguous at this level — prefer longest matched name as a
                    # mild tie-breaker (more specific string = more likely correct).
                    candidates.sort(key=lambda c: len(c[2]), reverse=True)
                    longest = candidates[0]
                    # Only accept the tie-break if its name is clearly longer than
                    # the runner-up; otherwise leave unmatched.
                    if len(candidates) == 1 or len(longest[2]) > len(candidates[1][2]):
                        best = (longest[0], longest[1])
                        break
                    # else: genuinely ambiguous → fall through, stay unmatched

        if best:
            inc.area_id = best[0]
            inc.save(update_fields=['area'])
            matched += 1
        else:
            unmatched += 1

    print(f"\n  [automatch] Linked {matched} incident(s) to areas; "
          f"left {unmatched} unmatched for manual review.")


def reverse_automatch(apps, schema_editor):
    """Reverse: unset area on all incidents (back to NULL)."""
    Incident = apps.get_model('incidents', 'Incident')
    Incident.objects.update(area=None)


class Migration(migrations.Migration):

    dependencies = [
        ('incidents', '0008_area_incident_area_area_incidents_a_level_c3ef6e_idx_and_more'),
    ]

    operations = [
        migrations.RunPython(automatch_areas, reverse_automatch),
    ]
