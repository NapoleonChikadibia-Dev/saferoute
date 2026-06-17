"""
SafeRoute Django Settings
-------------------------
Reads all secrets from environment variables via python-decouple.
Never hardcode SECRET_KEY, API keys, or DB passwords here.

Install dependency:
    pip install python-decouple

Usage:
    - Development:  copy .env.example to .env and fill in values
    - Production:   set environment variables on your host (Render / Railway / etc.)
"""

from pathlib import Path
from decouple import config, Csv
import os

# ─────────────────────────────────────────────
# BASE
# ─────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent


# ─────────────────────────────────────────────
# SECURITY
# ─────────────────────────────────────────────
SECRET_KEY = config('SECRET_KEY')   # required — no default, will crash if missing

DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = config(
    'ALLOWED_HOSTS',
    default='127.0.0.1,localhost',
    cast=Csv(),
)


# ─────────────────────────────────────────────
# APPLICATIONS
# ─────────────────────────────────────────────
DJANGO_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

THIRD_PARTY_APPS = [
    # 'livereload',  # dev only — enable locally, never in production
]

LOCAL_APPS = [
    'incidents',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS


# ─────────────────────────────────────────────
# MIDDLEWARE
# ─────────────────────────────────────────────
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',       # serves static files in prod
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]


# ─────────────────────────────────────────────
# URLS & WSGI
# ─────────────────────────────────────────────
ROOT_URLCONF = 'saferoute.urls'
WSGI_APPLICATION = 'saferoute.wsgi.application'


# ─────────────────────────────────────────────
# TEMPLATES
# ─────────────────────────────────────────────
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]


# ─────────────────────────────────────────────
# DATABASE
# ─────────────────────────────────────────────
# Development: SQLite (default)
# Production:  set DATABASE_URL in your environment, e.g.
#              postgres://user:pass@host:5432/dbname
#
# To use dj-database-url in production:
#   pip install dj-database-url psycopg2-binary
#   then uncomment the block below and remove the sqlite block.

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

# ── Production PostgreSQL (uncomment when deploying) ──────────────────────────
# import dj_database_url
# DATABASES = {
#     'default': dj_database_url.config(
#         default=config('DATABASE_URL'),
#         conn_max_age=600,
#         ssl_require=not DEBUG,
#     )
# }


# ─────────────────────────────────────────────
# PASSWORD VALIDATION
# ─────────────────────────────────────────────
AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ─────────────────────────────────────────────
# INTERNATIONALISATION
# ─────────────────────────────────────────────
LANGUAGE_CODE = 'en-us'
TIME_ZONE     = 'Africa/Lagos'   # ← updated from UTC — matches your user base
USE_I18N      = True
USE_TZ        = True


# ─────────────────────────────────────────────
# STATIC FILES
# ─────────────────────────────────────────────
STATIC_URL  = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# WhiteNoise compressed static files (production)
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'


# ─────────────────────────────────────────────
# MEDIA FILES  (user uploads — future use)
# ─────────────────────────────────────────────
MEDIA_URL  = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# ─────────────────────────────────────────────
# AUTH REDIRECTS
# ─────────────────────────────────────────────
LOGIN_URL           = '/login/'
LOGIN_REDIRECT_URL  = '/map/'
LOGOUT_REDIRECT_URL = '/login/'


# ─────────────────────────────────────────────
# DEFAULT PRIMARY KEY
# ─────────────────────────────────────────────
DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ─────────────────────────────────────────────
# THIRD-PARTY API KEYS
# ─────────────────────────────────────────────
NEWS_API_KEY = config('NEWS_API_KEY', default='')


# ─────────────────────────────────────────────
# SECURITY HEADERS  (production only)
# ─────────────────────────────────────────────
if not DEBUG:
    # Force HTTPS
    SECURE_SSL_REDIRECT             = True
    SECURE_HSTS_SECONDS             = 31536000   # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS  = True
    SECURE_HSTS_PRELOAD             = True

    # Secure cookies
    SESSION_COOKIE_SECURE           = True
    CSRF_COOKIE_SECURE              = True

    # Content security
    SECURE_CONTENT_TYPE_NOSNIFF     = True
    SECURE_BROWSER_XSS_FILTER       = True
    X_FRAME_OPTIONS                 = 'DENY'


# ─────────────────────────────────────────────
# SESSION
# ─────────────────────────────────────────────
SESSION_COOKIE_AGE      = 60 * 60 * 24 * 7   # 7 days
SESSION_COOKIE_HTTPONLY = True                # JS cannot read session cookie


# ─────────────────────────────────────────────
# LOGGING  (production)
# ─────────────────────────────────────────────
if not DEBUG:
    LOGGING = {
        'version': 1,
        'disable_existing_loggers': False,
        'handlers': {
            'console': {
                'class': 'logging.StreamHandler',
            },
        },
        'root': {
            'handlers': ['console'],
            'level': 'WARNING',
        },
        'loggers': {
            'django': {
                'handlers': ['console'],
                'level': 'ERROR',
                'propagate': False,
            },
        },
    }

# News API
NEWS_API_KEY = config('NEWS_API_KEY', default='')

# ---------------------------------------------------------------------------
# EMAIL
# ---------------------------------------------------------------------------
EMAIL_BACKEND       = config('EMAIL_BACKEND', default='django.core.mail.backends.console.EmailBackend')
EMAIL_HOST          = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT          = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS       = True
EMAIL_HOST_USER     = config('EMAIL_HOST_USER', default='')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
DEFAULT_FROM_EMAIL  = config('EMAIL_HOST_USER', default='')