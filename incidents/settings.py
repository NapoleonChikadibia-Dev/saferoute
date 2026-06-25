"""
Django settings for saferoute project.
Hardened for both development and production.
"""

from pathlib import Path
import os
from decouple import config, Csv

BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# CORE SECURITY
# ---------------------------------------------------------------------------

SECRET_KEY = config('SECRET_KEY')

DEBUG = config('DEBUG', default=False, cast=bool)

ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='127.0.0.1,localhost', cast=Csv())

RENDER_EXTERNAL_HOSTNAME = os.environ.get('RENDER_EXTERNAL_HOSTNAME')
if RENDER_EXTERNAL_HOSTNAME:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)
    CSRF_TRUSTED_ORIGINS = [f'https://{RENDER_EXTERNAL_HOSTNAME}']


# ---------------------------------------------------------------------------
# APPLICATIONS
# ---------------------------------------------------------------------------

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'incidents',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',          # static files in prod
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'saferoute.urls'

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

WSGI_APPLICATION = 'saferoute.wsgi.application'


# ---------------------------------------------------------------------------
# DATABASE
# ---------------------------------------------------------------------------

import dj_database_url

DATABASE_URL = config('DATABASE_URL', default='')

if DATABASE_URL:
    DATABASES = {
        'default': dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            ssl_require=True,
        )
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': config('DB_ENGINE', default='django.db.backends.sqlite3'),
            'NAME': config('DB_NAME', default=str(BASE_DIR / 'db.sqlite3')),
            'USER': config('DB_USER', default=''),
            'PASSWORD': config('DB_PASSWORD', default=''),
            'HOST': config('DB_HOST', default=''),
            'PORT': config('DB_PORT', default=''),
        }
    }

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# ---------------------------------------------------------------------------
# PASSWORD VALIDATION
# ---------------------------------------------------------------------------

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# ---------------------------------------------------------------------------
# INTERNATIONALISATION
# ---------------------------------------------------------------------------

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Africa/Lagos'   # project is Nigeria-based
USE_I18N = True
USE_TZ = True


# ---------------------------------------------------------------------------
# STATIC FILES
# ---------------------------------------------------------------------------

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'

# WhiteNoise — compressed, cached static files in production
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'


# ---------------------------------------------------------------------------
# MEDIA FILES (user uploads — future use)
# ---------------------------------------------------------------------------

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'


# ---------------------------------------------------------------------------
# AUTH REDIRECTS
# ---------------------------------------------------------------------------

LOGIN_URL = '/login/'
LOGIN_REDIRECT_URL = '/map/'
LOGOUT_REDIRECT_URL = '/login/'


# ---------------------------------------------------------------------------
# THIRD-PARTY API KEYS
# ---------------------------------------------------------------------------

NEWS_API_KEY = config('NEWS_API_KEY', default='')


# ---------------------------------------------------------------------------
# VERIFICATION
# ---------------------------------------------------------------------------

# Net trust score (confirmations - disputes) required to auto-verify an
# incident. Tune as the community grows: 3 is sensible at launch; you may
# want a higher bar (e.g. 10) once you have more users.
VERIFICATION_THRESHOLD = config('VERIFICATION_THRESHOLD', default=3, cast=int)


# ---------------------------------------------------------------------------
# SECURITY HEADERS (only active when DEBUG=False)
# ---------------------------------------------------------------------------

if not DEBUG:
    SECURE_HSTS_SECONDS = 31536000           # 1 year
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_BROWSER_XSS_FILTER = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'


# ---------------------------------------------------------------------------
# SESSION
# ---------------------------------------------------------------------------

SESSION_COOKIE_AGE = 1209600          # 2 weeks
SESSION_COOKIE_HTTPONLY = True


# ---------------------------------------------------------------------------
# LOGGING
# ---------------------------------------------------------------------------

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'formatters': {
        'verbose': {
            'format': '[{levelname}] {asctime} {module}: {message}',
            'style': '{',
        },
    },
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
            'formatter': 'verbose',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'WARNING',
    },
    'loggers': {
        'django': {
            'handlers': ['console'],
            'level': config('DJANGO_LOG_LEVEL', default='INFO'),
            'propagate': False,
        },
    },
}


# Upload limits — videos up to 50MB, so allow headroom above that.
# DATA_UPLOAD_MAX_MEMORY_SIZE guards form POST size; FILE_UPLOAD_MAX_MEMORY_SIZE
# controls when a file is streamed to a temp file vs kept in memory.
DATA_UPLOAD_MAX_MEMORY_SIZE = 60 * 1024 * 1024  # 60MB (headroom over 50MB video cap)
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024   # files >5MB stream to disk (saves RAM)