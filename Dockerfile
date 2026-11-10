FROM python:3.12-slim

# Evitar archivos .pyc y habilitar salida sin buffer
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Instalar actualizaciones de seguridad del sistema y dependencias mínimas
RUN apt-get update && apt-get upgrade -y && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias de Python (actualizando pip, setuptools y wheel por seguridad)
COPY requirements.txt /app/
RUN pip install --upgrade pip setuptools wheel && pip install -r requirements.txt

# Crear usuario no root por seguridad
RUN adduser --disabled-password --gecos "" appuser

# Copiar el código del proyecto
COPY . /app/

# Crear directorios para archivos estáticos y multimedia y asignar permisos al usuario no root
RUN mkdir -p /app/staticfiles /app/media/uploads /app/media/avatares \
    && python manage.py collectstatic --no-input \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Comando por defecto: aplicar migraciones y levantar Gunicorn
CMD ["sh", "-c", "python manage.py migrate --no-input && gunicorn config.wsgi:application --bind 0.0.0.0:8000 --workers 3"]

