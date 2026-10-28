#!/bin/sh
set -e
python manage.py migrate --noinput
python manage.py load_bank_holidays
python manage.py seed_demo
exec gunicorn config.wsgi --bind 0.0.0.0:8000 --workers 2 --threads 4 --access-logfile -
