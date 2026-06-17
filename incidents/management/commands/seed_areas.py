# incidents/management/commands/seed_areas.py
#
# Seeds a GLOBAL SKELETON of areas:
#   • All major countries at level 1
#   • Meaningful state/city depth for a selection of countries
#   • Deep coverage for Nigeria (project's home base): states + major cities + sample local areas
#
# Safe to run multiple times — uses get_or_create, so it never duplicates.
# Run with:  python manage.py seed_areas
#
# This is a STARTING SKELETON, not a complete planetary dataset. The Area model
# supports infinite depth; users (and you) extend from here. For a truly
# exhaustive global set, import a geo-dataset like GeoNames later.

from django.core.management.base import BaseCommand
from django.utils.text import slugify
from django.db import transaction

from incidents.models import Area


# ---------------------------------------------------------------------------
# SEED DATA
# Structure: nested dicts. Each level becomes an Area with the right `level`.
# Format:
#   "Country": {
#       "_coords": (lat, lng),              # optional country centre
#       "State": {
#           "_coords": (lat, lng),          # optional
#           "City": ["Local Area", ...]     # list of leaf local areas
#       }
#   }
# A city can map to [] if we don't have local areas for it yet.
# ---------------------------------------------------------------------------

SEED = {
    # ===================== NIGERIA (deep coverage) =====================
    "Nigeria": {
        "_coords": (9.0820, 8.6753),
        "Lagos": {
            "_coords": (6.5244, 3.3792),
            "Ikeja":        ["Allen Avenue", "Computer Village", "Opebi", "GRA Ikeja"],
            "Lekki":        ["Lekki Phase 1", "Chevron Drive", "Ikate", "Agungi"],
            "Victoria Island": ["Oniru", "Adeola Odeku", "Saka Tinubu"],
            "Surulere":     ["Aguda", "Bode Thomas", "Adeniran Ogunsanya"],
            "Yaba":         ["Akoka", "Sabo", "Tejuosho"],
            "Ikorodu":      ["Ijede", "Igbogbo", "Ebute"],
            "Apapa":        ["Ajegunle", "Tincan", "Wharf Road"],
        },
        "Abuja (FCT)": {
            "_coords": (9.0579, 7.4951),
            "Garki":        ["Area 1", "Area 11", "Garki II"],
            "Wuse":         ["Wuse Zone 2", "Wuse Zone 5", "Wuse II"],
            "Maitama":      ["Maitama District"],
            "Gwarinpa":     ["3rd Avenue", "6th Avenue", "Kafe"],
            "Kubwa":        ["Phase 1", "Phase 2", "Byazhin"],
        },
        "Rivers": {
            "_coords": (4.8156, 7.0498),
            "Port Harcourt": ["Old GRA", "New GRA", "Diobu", "Trans Amadi", "D-Line"],
            "Obio-Akpor":   ["Rumuokoro", "Rumuola", "Choba", "Rumuokwurushi"],
            "Eleme":        ["Akpajo", "Aleto"],
        },
        "Kano": {
            "_coords": (12.0022, 8.5920),
            "Kano Municipal": ["Sabon Gari", "Fagge", "Bompai"],
            "Nassarawa":    ["Hotoro", "Tarauni"],
        },
        "Oyo": {
            "_coords": (8.1574, 3.6147),
            "Ibadan":       ["Bodija", "Dugbe", "Mokola", "Ring Road", "Challenge"],
        },
        "Kaduna": {
            "_coords": (10.5105, 7.4165),
            "Kaduna North": ["Ungwan Rimi", "Malali"],
            "Kaduna South": ["Barnawa", "Kakuri"],
        },
        "Enugu": {
            "_coords": (6.5244, 7.5186),
            "Enugu North":  ["Independence Layout", "GRA", "New Haven"],
        },
        "Delta": {
            "_coords": (5.7040, 5.9339),
            "Warri":        ["Effurun", "Airport Road", "Enerhen"],
            "Asaba":        ["Okpanam", "Cable Point"],
        },
    },

    # ===================== OTHER MAJOR COUNTRIES (skeleton) =====================
    "United States": {
        "_coords": (37.0902, -95.7129),
        "California": {
            "_coords": (36.7783, -119.4179),
            "Los Angeles":  ["Downtown", "Hollywood", "Venice", "Koreatown"],
            "San Francisco": ["Mission", "SoMa", "Tenderloin", "Marina"],
        },
        "New York": {
            "_coords": (40.7128, -74.0060),
            "New York City": ["Manhattan", "Brooklyn", "Queens", "The Bronx"],
        },
        "Texas": {
            "_coords": (31.9686, -99.9018),
            "Houston":      ["Downtown", "Midtown", "The Heights"],
            "Austin":       ["Downtown", "East Austin"],
        },
    },
    "United Kingdom": {
        "_coords": (55.3781, -3.4360),
        "England": {
            "_coords": (52.3555, -1.1743),
            "London":       ["Westminster", "Camden", "Hackney", "Shoreditch", "Brixton"],
            "Manchester":   ["City Centre", "Salford", "Didsbury"],
            "Birmingham":   ["City Centre", "Edgbaston"],
        },
        "Scotland": {
            "_coords": (56.4907, -4.2026),
            "Edinburgh":    ["Old Town", "New Town", "Leith"],
            "Glasgow":      ["City Centre", "West End"],
        },
    },
    "Ghana": {
        "_coords": (7.9465, -1.0232),
        "Greater Accra": {
            "_coords": (5.6037, -0.1870),
            "Accra":        ["Osu", "Labadi", "Cantonments", "East Legon"],
            "Tema":         ["Community 1", "Community 25"],
        },
        "Ashanti": {
            "_coords": (6.7470, -1.5209),
            "Kumasi":       ["Adum", "Asokwa", "Bantama"],
        },
    },
    "South Africa": {
        "_coords": (-30.5595, 22.9375),
        "Gauteng": {
            "_coords": (-26.2708, 28.1123),
            "Johannesburg": ["Sandton", "Soweto", "Rosebank", "Hillbrow"],
            "Pretoria":     ["Centurion", "Hatfield"],
        },
        "Western Cape": {
            "_coords": (-33.2278, 21.8569),
            "Cape Town":    ["City Bowl", "Sea Point", "Khayelitsha", "Camps Bay"],
        },
    },
    "Kenya": {
        "_coords": (-0.0236, 37.9062),
        "Nairobi County": {
            "_coords": (-1.2921, 36.8219),
            "Nairobi":      ["Westlands", "Kibera", "Karen", "Eastleigh"],
        },
    },
    "Canada": {
        "_coords": (56.1304, -106.3468),
        "Ontario": {
            "_coords": (51.2538, -85.3232),
            "Toronto":      ["Downtown", "Scarborough", "North York", "Etobicoke"],
        },
    },
    "India": {
        "_coords": (20.5937, 78.9629),
        "Maharashtra": {
            "_coords": (19.7515, 75.7139),
            "Mumbai":       ["Andheri", "Bandra", "Colaba", "Dharavi"],
        },
        "Delhi": {
            "_coords": (28.7041, 77.1025),
            "New Delhi":    ["Connaught Place", "Saket", "Dwarka"],
        },
    },

    # ===================== COUNTRIES-ONLY (level 1 placeholders) =====================
    # These give global breadth; depth can be added later by users/admin.
    "France":        {"_coords": (46.2276, 2.2137)},
    "Germany":       {"_coords": (51.1657, 10.4515)},
    "Brazil":        {"_coords": (-14.2350, -51.9253)},
    "China":         {"_coords": (35.8617, 104.1954)},
    "Japan":         {"_coords": (36.2048, 138.2529)},
    "Australia":     {"_coords": (-25.2744, 133.7751)},
    "Egypt":         {"_coords": (26.8206, 30.8025)},
    "Mexico":        {"_coords": (23.6345, -102.5528)},
    "Spain":         {"_coords": (40.4637, -3.7492)},
    "Italy":         {"_coords": (41.8719, 12.5674)},
    "United Arab Emirates": {"_coords": (23.4241, 53.8478)},
    "Saudi Arabia":  {"_coords": (23.8859, 45.0792)},
    "Ethiopia":      {"_coords": (9.1450, 40.4897)},
    "Tanzania":      {"_coords": (-6.3690, 34.8888)},
    "Uganda":        {"_coords": (1.3733, 32.2903)},
    "Cameroon":      {"_coords": (7.3697, 12.3547)},
    "Senegal":       {"_coords": (14.4974, -14.4524)},
    "Ivory Coast":   {"_coords": (7.5400, -5.5471)},
    "Morocco":       {"_coords": (31.7917, -7.0926)},
    "Netherlands":   {"_coords": (52.1326, 5.2913)},
}


def _unique_slug(base, used):
    """Generate a slug unique within this run."""
    slug = slugify(base) or "area"
    candidate, n = slug, 2
    while candidate in used:
        candidate = f"{slug}-{n}"
        n += 1
    used.add(candidate)
    return candidate


class Command(BaseCommand):
    help = "Seed a global skeleton of areas (countries → states → cities → local areas)."

    def handle(self, *args, **options):
        used_slugs = set(Area.objects.values_list('slug', flat=True))
        created = {'country': 0, 'state': 0, 'city': 0, 'local': 0}

        with transaction.atomic():
            for country_name, country_data in SEED.items():
                coords = country_data.get('_coords', (None, None))
                country, was_new = Area.objects.get_or_create(
                    name=country_name,
                    parent=None,
                    defaults={
                        'level':       Area.LEVEL_COUNTRY,
                        'slug':        _unique_slug(country_name, used_slugs),
                        'latitude':    coords[0],
                        'longitude':   coords[1],
                        'is_verified': True,   # admin-seeded → trusted
                    },
                )
                if was_new:
                    created['country'] += 1

                for state_name, state_data in country_data.items():
                    if state_name == '_coords':
                        continue
                    s_coords = state_data.get('_coords', (None, None)) if isinstance(state_data, dict) else (None, None)
                    state, was_new = Area.objects.get_or_create(
                        name=state_name,
                        parent=country,
                        defaults={
                            'level':       Area.LEVEL_STATE,
                            'slug':        _unique_slug(f"{country_name}-{state_name}", used_slugs),
                            'latitude':    s_coords[0],
                            'longitude':   s_coords[1],
                            'is_verified': True,
                        },
                    )
                    if was_new:
                        created['state'] += 1

                    for city_name, locals_list in state_data.items():
                        if city_name == '_coords':
                            continue
                        city, was_new = Area.objects.get_or_create(
                            name=city_name,
                            parent=state,
                            defaults={
                                'level':       Area.LEVEL_CITY,
                                'slug':        _unique_slug(f"{state_name}-{city_name}", used_slugs),
                                'is_verified': True,
                            },
                        )
                        if was_new:
                            created['city'] += 1

                        for local_name in (locals_list or []):
                            _, was_new = Area.objects.get_or_create(
                                name=local_name,
                                parent=city,
                                defaults={
                                    'level':       Area.LEVEL_LOCAL,
                                    'slug':        _unique_slug(f"{city_name}-{local_name}", used_slugs),
                                    'is_verified': True,
                                },
                            )
                            if was_new:
                                created['local'] += 1

        total = sum(created.values())
        self.stdout.write(self.style.SUCCESS(
            f"✅ Seed complete. Added {total} new areas "
            f"({created['country']} countries, {created['state']} states, "
            f"{created['city']} cities, {created['local']} local areas). "
            f"Existing areas were left untouched."
        ))
