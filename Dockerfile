FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# LibreOffice (sin interfaz) para convertir los formatos a PDF, con fuentes compatibles
# con Calibri/Arial/Times para que el PDF salga igual que en Word/Excel
RUN apt-get update \
 && apt-get install -y --no-install-recommends libreoffice-writer-nogui libreoffice-calc-nogui \
    fonts-crosextra-carlito fonts-crosextra-caladea fonts-liberation fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Los estáticos se juntan al construir la imagen (no necesitan la BD)
RUN DEBUG=1 python manage.py collectstatic --noinput

# Al arrancar: aplica migraciones (crea tablas y roles), crea el admin si se
# definieron DJANGO_SUPERUSER_*, y levanta gunicorn en el puerto que da Railway.
CMD python manage.py migrate --noinput \
 && (python manage.py createsuperuser --noinput 2>/dev/null || true) \
 && gunicorn config.wsgi:application --bind 0.0.0.0:${PORT:-8000} --workers 2 --timeout 90 --access-logfile -
