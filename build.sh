#!/usr/bin/env bash
set -o errexit

pip install -r requirements.txt
python manage.py collectstatic --no-input
python manage.py migrate

# Create a superuser from env vars if it doesn't exist yet
python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
import os
u = os.environ.get('DJANGO_SUPERUSER_USERNAME')
e = os.environ.get('DJANGO_SUPERUSER_EMAIL')
p = os.environ.get('DJANGO_SUPERUSER_PASSWORD')
if u and p and not User.objects.filter(username=u).exists():
    User.objects.create_superuser(username=u, email=e, password=p)
    print('Superuser created:', u)
else:
    print('Superuser already exists or env vars missing')
"