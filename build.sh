#!/usr/bin/env bash
# Salir inmediatamente si algún comando falla
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --no-input
python manage.py migrate --no-input

