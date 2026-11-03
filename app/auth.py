"""
Acceso con contraseña compartida (HTTP Basic).

Protege la web y la API por igual. Es una barrera mínima para no dejar la
aplicación abierta en internet: todavía no hay usuarios ni roles.
"""
from __future__ import annotations

import base64
import binascii
import secrets


def credenciales_validas(cabecera: str | None, usuario: str, contrasena: str) -> bool:
    """Comprueba la cabecera Authorization contra el usuario y la contraseña esperados."""
    if not cabecera or not usuario or not contrasena:
        return False
    esquema, _, codificado = cabecera.partition(" ")
    if esquema.lower() != "basic":
        return False
    try:
        recibido = base64.b64decode(codificado, validate=True)
    except (binascii.Error, ValueError):
        return False
    usuario_rx, separador, contrasena_rx = recibido.partition(b":")
    if not separador:
        return False
    # compare_digest evita filtrar información por el tiempo de respuesta.
    # Se evalúan las dos comparaciones siempre (& en vez de and).
    return secrets.compare_digest(usuario_rx, usuario.encode()) & secrets.compare_digest(
        contrasena_rx, contrasena.encode()
    )
