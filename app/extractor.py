"""
Lectura de tickets con IA (Claude con visión).

Se usan salidas estructuradas (output_config.format): en vez de pedirle al modelo
que escriba JSON a mano, le damos un esquema JSON y la API garantiza que la
respuesta lo cumple. Así siempre llega con los campos que esperamos.

Si no hay ANTHROPIC_API_KEY configurada, funciona en MODO DEMO devolviendo
un ticket inventado, para poder probar la aplicación entera sin coste.
"""
from __future__ import annotations

import base64
import json
import random
from datetime import date, timedelta

from . import config
from .validacion import CATEGORIAS

# Todos los campos son obligatorios: lo que no se lea debe llegar como null, no omitido.
_CAMPOS_TICKET = {
    "comercio": {"type": ["string", "null"], "description": "Nombre del establecimiento"},
    "cif": {"type": ["string", "null"], "description": "CIF/NIF del EMISOR del ticket"},
    "fecha": {"type": ["string", "null"], "description": "Fecha en formato YYYY-MM-DD"},
    "numero_ticket": {"type": ["string", "null"]},
    "base_imponible": {"type": ["number", "null"]},
    "tipo_iva": {"type": ["number", "null"], "description": "Porcentaje, ej. 10 o 21"},
    "cuota_iva": {"type": ["number", "null"]},
    "total": {"type": ["number", "null"]},
    "moneda": {"type": "string", "description": "Código ISO, ej. EUR"},
    "categoria": {"type": "string", "enum": sorted(CATEGORIAS)},
    "metodo_pago": {"anyOf": [{"type": "string", "enum": ["tarjeta", "efectivo", "otro"]}, {"type": "null"}]},
    "es_factura_completa": {
        "type": "boolean",
        "description": "true solo si aparecen nombre y NIF del CLIENTE (factura completa); false si es un ticket o factura simplificada",
    },
    "confianza": {"type": "number", "description": "De 0 a 1, cuánta seguridad tienes en la lectura"},
    "notas": {"type": ["string", "null"], "description": "Cualquier cosa dudosa o ilegible"},
}

ESQUEMA = {
    "type": "object",
    "properties": {
        "tickets": {
            "type": "array",
            "description": "Un elemento por cada ticket distinto visible en la foto.",
            "items": {
                "type": "object",
                "properties": _CAMPOS_TICKET,
                "required": list(_CAMPOS_TICKET),
                "additionalProperties": False,
            },
        }
    },
    "required": ["tickets"],
    "additionalProperties": False,
}

INSTRUCCIONES = """Eres un asistente de administración que lee tickets y facturas españolas.
Extrae los datos de CADA ticket visible en la imagen (puede haber uno o varios).
Reglas:
- No inventes datos: si algo no se lee, devuélvelo como null y baja la confianza.
- Importes como números con punto decimal (12.50), sin símbolo de moneda.
- Si hay varios tipos de IVA, usa la suma de bases y cuotas y pon en tipo_iva el principal.
- El CIF es el del establecimiento que emite el ticket, no el del cliente.
- Categoriza según el tipo de comercio (restaurante -> comida, gasolinera -> combustible, hotel -> alojamiento...).
Si la imagen no contiene ningún ticket, devuelve una lista vacía."""


def modo() -> str:
    return "claude" if config.ANTHROPIC_API_KEY else "demo"


def extraer_tickets(imagen: bytes, tipo_mime: str) -> list[dict]:
    """Devuelve una lista de diccionarios, uno por ticket encontrado en la imagen."""
    if modo() == "demo":
        return [_ticket_demo()]

    import anthropic  # import aquí para que el modo demo no necesite la librería

    cliente = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    respuesta = cliente.beta.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=16000,
        output_config={"format": {"type": "json_schema", "schema": ESQUEMA}},
        # Si el modelo rechaza la petición, la API la repite en otro modelo
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": tipo_mime,
                        "data": base64.standard_b64encode(imagen).decode(),
                    },
                },
                {"type": "text", "text": INSTRUCCIONES},
            ],
        }],
    )
    return parsear_respuesta(respuesta)


def parsear_respuesta(respuesta) -> list[dict]:
    """Saca la lista de tickets de la respuesta. Lanza ValueError si no es utilizable."""
    if respuesta.stop_reason == "refusal":
        raise ValueError("La IA ha rechazado leer esta foto.")
    if respuesta.stop_reason == "max_tokens":
        raise ValueError("La respuesta de la IA ha quedado cortada: prueba con menos tickets por foto.")
    texto = next((b.text for b in respuesta.content if b.type == "text"), None)
    if texto is None:
        raise ValueError("La IA no ha devuelto ningún dato.")
    return json.loads(texto)["tickets"]


def _ticket_demo() -> dict:
    """Ticket inventado y coherente para probar sin API key."""
    comercios = [
        ("Restaurante Casa Pepe", "B12345674", "comida", 10),
        ("Gasolinera Repsol Ctra. N-VI", "A28047223", "combustible", 21),
        ("Taxi Madrid Licencia 1234", "12345678Z", "transporte", 10),
        ("Parking Centro", "B87654323", "parking_peajes", 21),
    ]
    nombre, cif, categoria, tipo = random.choice(comercios)
    total = round(random.uniform(8, 90), 2)
    base = round(total / (1 + tipo / 100), 2)
    return {
        "comercio": nombre,
        "cif": cif,
        "fecha": (date.today() - timedelta(days=random.randint(0, 10))).isoformat(),
        "numero_ticket": f"T-{random.randint(1000, 9999)}",
        "base_imponible": base,
        "tipo_iva": tipo,
        "cuota_iva": round(total - base, 2),
        "total": total,
        "moneda": "EUR",
        "categoria": categoria,
        "metodo_pago": "tarjeta",
        "es_factura_completa": False,
        "confianza": 0.95,
        "notas": "MODO DEMO: datos inventados (no hay ANTHROPIC_API_KEY)",
    }
