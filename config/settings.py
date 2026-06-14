from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env(
    DEBUG=(bool, False),
)
environ.Env.read_env(BASE_DIR / ".env")

SECRET_KEY = env("DJANGO_SECRET_KEY", default="unsafe-dev-key-change-me")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env.list("ALLOWED_HOSTS", default=["*"])

# Trust Railway's forwarded HTTPS headers and configured public hostnames.
USE_X_FORWARDED_HOST = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

_default_trusted_origins = []
for host in ALLOWED_HOSTS:
    cleaned_host = host.strip()
    if cleaned_host and cleaned_host != "*":
        _default_trusted_origins.append(f"https://{cleaned_host}")
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=_default_trusted_origins)

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "auditlog",
    "django_q",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "core.security.role_context",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}"),
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_REDIRECT_URL = "/ops/inventory/orders/"
LOGOUT_REDIRECT_URL = "/accounts/login/"

SHOPIFY_API_SECRET = env("SHOPIFY_API_SECRET", default=env("SHOPIFY_WEBHOOK_SECRET", default=""))
SHOPIFY_WEBHOOK_SECRET = SHOPIFY_API_SECRET
GOOGLE_DRIVE_PUBLIC_PREFIX = env("GOOGLE_DRIVE_PUBLIC_PREFIX", default="https://drive.google.com")
NTFY_TOPIC = env("NTFY_TOPIC", default="")
RESEND_API_KEY = env("RESEND_API_KEY", default="")
OPS_EMAIL_TO = env("OPS_EMAIL_TO", default="")
RESEND_FROM_EMAIL = env("RESEND_FROM_EMAIL", default="")
INTERNAL_API_TOKEN = env("INTERNAL_API_TOKEN", default="")
SENTRY_DSN = env("SENTRY_DSN", default="")

Q_CLUSTER = {
    "name": "bolderp",
    "workers": env.int("Q2_WORKERS", default=4),
    "timeout": env.int("Q2_TIMEOUT", default=120),
    "retry": 180,
    "queue_limit": 500,
    "bulk": 10,
    "orm": "default",
}

# Initialize Sentry only if a valid DSN is configured
if SENTRY_DSN and "project-id" not in SENTRY_DSN and "your-sentry" not in SENTRY_DSN.lower():
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        traces_sample_rate=env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.1),
    )
