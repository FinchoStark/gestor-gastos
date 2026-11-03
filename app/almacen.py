"""
Dónde se guardan las fotos de los tickets.

- Con S3_BUCKET configurado: se suben a Amazon S3 (bucket privado) y se sirven
  con URLs firmadas que caducan a los 10 minutos.
- Sin S3 y en local: se guardan en la carpeta ./uploads
- Sin S3 y en Vercel: no se guardan (el disco de Vercel es temporal).
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import config

EXTENSIONES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}


def modo() -> str:
    if config.S3_BUCKET:
        return "s3"
    return "ninguno" if config.EN_VERCEL else "local"


def _s3():
    import boto3
    from botocore.config import Config
    return boto3.client(
        "s3",
        region_name=config.S3_REGION,
        # Host de la región, no el global: eu-south-2 se activa a mano y el host
        # global (s3.amazonaws.com) puede no llegar a sus buckets.
        endpoint_url=f"https://s3.{config.S3_REGION}.amazonaws.com",
        config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}),
        # si están vacías, boto3 usa las credenciales del sistema (~/.aws, rol IAM...)
        aws_access_key_id=config.S3_ACCESS_KEY_ID or None,
        aws_secret_access_key=config.S3_SECRET_ACCESS_KEY or None,
    )


def guardar(contenido: bytes, hash_sha256: str, tipo_mime: str) -> str | None:
    """Guarda la foto y devuelve su ruta/clave, o None si no hay almacenamiento."""
    ahora = datetime.now()
    clave = f"tickets/{ahora:%Y/%m}/{hash_sha256}.{EXTENSIONES.get(tipo_mime, 'bin')}"

    if modo() == "s3":
        _s3().put_object(Bucket=config.S3_BUCKET, Key=clave, Body=contenido, ContentType=tipo_mime)
        return clave
    if modo() == "local":
        ruta = Path(config.CARPETA_LOCAL) / clave
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta.write_bytes(contenido)
        return clave
    return None


def url_firmada(clave: str) -> str:
    return _s3().generate_presigned_url(
        "get_object", Params={"Bucket": config.S3_BUCKET, "Key": clave}, ExpiresIn=600
    )


def ruta_local(clave: str) -> Path | None:
    base = Path(config.CARPETA_LOCAL).resolve()
    ruta = (base / clave).resolve()
    # evita que alguien pida ../../etc/passwd
    if base not in ruta.parents or not ruta.is_file():
        return None
    return ruta
