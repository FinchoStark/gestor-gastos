"""Configuración leída de variables de entorno (o de un fichero .env en local)."""
import os

try:  # en local cargamos .env; en Vercel las variables vienen del panel
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/gastos")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")

# Almacenamiento de fotos: si hay bucket se usa S3; si no, carpeta local
S3_BUCKET = os.getenv("S3_BUCKET", "")
# Ojo: Vercel reserva los nombres AWS_*, por eso usamos S3_* para las credenciales
S3_REGION = os.getenv("S3_REGION", "eu-south-2")  # región de AWS en España (Aragón)
S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID", "")
S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY", "")
CARPETA_LOCAL = os.getenv("CARPETA_FOTOS", "uploads")

# Acceso con contraseña compartida. En Vercel son obligatorias; en local, opcionales.
APP_USUARIO = os.getenv("APP_USUARIO", "")
APP_CONTRASENA = os.getenv("APP_CONTRASENA", "")

EN_VERCEL = bool(os.getenv("VERCEL"))
TAMANO_MAXIMO_FOTO = 4 * 1024 * 1024  # Vercel limita el cuerpo de la petición a 4,5 MB
