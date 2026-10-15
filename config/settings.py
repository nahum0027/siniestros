"""
Configuración de la plataforma de siniestros.

Todo lo que cambia entre tu compu y Railway se lee de variables de entorno.
Sin variables, funciona en modo desarrollo (DEBUG, SQLite local, correo en la terminal).
"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env_bool(nombre, defecto=False):
    return os.environ.get(nombre, str(defecto)).strip().lower() in ("1", "true", "si", "sí", "yes")


def env_lista(nombre, defecto=""):
    return [x.strip() for x in os.environ.get(nombre, defecto).split(",") if x.strip()]


# ---------------------------------------------------------------- seguridad
DEBUG = env_bool("DEBUG", True)
SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    # solo para desarrollo; en Railway SIEMPRE se define SECRET_KEY
    "django-insecure-rg&x(&0r3dbl_rm&&)t&2e1274y8c-s-2mg^qyj7xol%o(zq02",
)
if not DEBUG and SECRET_KEY.startswith("django-insecure"):
    raise RuntimeError("Falta la variable SECRET_KEY en producción")

# En tu compu: '*' para poder entrar desde el celular por la red local.
# En Railway: el dominio, p. ej. siniestros-production.up.railway.app
ALLOWED_HOSTS = env_lista("ALLOWED_HOSTS", "*")
CSRF_TRUSTED_ORIGINS = [f"https://{h}" for h in ALLOWED_HOSTS if h != "*" and not h.startswith(".")]

if not DEBUG:
    # Railway entrega https y reenvía a la app por http
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30
    SECURE_CONTENT_TYPE_NOSNIFF = True

# ---------------------------------------------------------------- apps
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'siniestros',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # sirve /static/ sin servidor aparte
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'siniestros.middleware.CambioContrasenaObligatorio',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# ---------------------------------------------------------------- datos
# DATA_DIR: en Railway apunta al volumen (/data) para que la BD y los reportes
# no se borren en cada deploy. En tu compu es la carpeta del proyecto.
DATA_DIR = Path(os.environ.get("DATA_DIR", BASE_DIR))
DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': DATA_DIR / 'db.sqlite3',
        'OPTIONS': {
            # más tolerante a dos usuarios guardando al mismo tiempo
            'timeout': 20,
            'init_command': 'PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;',
        },
    }
}

# Carpeta donde se guarda cada siniestro (un subfolder por folio)
SINIESTROS_DIR = DATA_DIR / 'salida'
# Las firmas y el croquis viajan en el JSON como imágenes; se sube el límite (25 MB)
DATA_UPLOAD_MAX_MEMORY_SIZE = 25 * 1024 * 1024

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'es-mx'
TIME_ZONE = 'America/Mexico_City'
USE_I18N = True
USE_TZ = True

# ---------------------------------------------------------------- archivos estáticos
STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

# ---------------------------------------------------------------- acceso
LOGIN_URL = 'entrar'
LOGIN_REDIRECT_URL = 'inicio'
LOGOUT_REDIRECT_URL = 'entrar'
# En campo no queremos que la sesión caduque a media semana (30 días)
SESSION_COOKIE_AGE = 60 * 60 * 24 * 30

# ---------------------------------------------------------------- correo
# Sin EMAIL_HOST: los correos se imprimen en la terminal (para pruebas).
# Con EMAIL_HOST (en Railway): se mandan de verdad por SMTP.
if os.environ.get("EMAIL_HOST"):
    MAILERS = {
        'default': {
            'BACKEND': 'django.core.mail.backends.smtp.EmailBackend',
            'OPTIONS': {
                'host': os.environ["EMAIL_HOST"],
                'port': int(os.environ.get("EMAIL_PORT", 587)),
                'username': os.environ.get("EMAIL_HOST_USER", ""),
                'password': os.environ.get("EMAIL_HOST_PASSWORD", ""),
                'use_tls': env_bool("EMAIL_USE_TLS", True),
                'timeout': 20,
            },
        },
    }
else:
    MAILERS = {
        'default': {
            'BACKEND': 'django.core.mail.backends.console.EmailBackend',
        },
    }

# A quién le llega cada siniestro capturado en campo (separados por coma)
SINIESTROS_CORREOS = env_lista("SINIESTROS_CORREOS")
DEFAULT_FROM_EMAIL = os.environ.get("SINIESTROS_REMITENTE",
                                    os.environ.get("EMAIL_HOST_USER") or "siniestros@localhost")

# ---------------------------------------------------------------- logs
# En Railway los errores aparecen en la pestaña "Deploy Logs"
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"consola": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["consola"], "level": "INFO" if not DEBUG else "WARNING"},
}
