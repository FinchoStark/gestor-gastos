"""
Reglas de negocio para los tickets.

Este módulo NO depende de FastAPI ni de la base de datos: recibe un diccionario
con lo que ha leído la IA y devuelve los datos normalizados + una lista de avisos.
Así se puede testear de forma aislada (ver tests/test_validacion.py).
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

CATEGORIAS = {
    "comida", "alojamiento", "transporte", "combustible",
    "parking_peajes", "material_oficina", "formacion", "otros",
}

# Tipos de IVA vigentes en España (general, reducido, superreducido y exento)
TIPOS_IVA_VALIDOS = {Decimal("0"), Decimal("4"), Decimal("10"), Decimal("21")}

TOLERANCIA = Decimal("0.02")      # céntimos de diferencia admitidos por redondeos
CONFIANZA_MINIMA = Decimal("0.70")  # por debajo, el ticket va a "revisar"
DIAS_MAXIMOS_ANTIGUEDAD = 90


# ---------------------------------------------------------------------------
# Utilidades
# ---------------------------------------------------------------------------
def a_decimal(valor) -> Decimal | None:
    """Convierte números o textos tipo '12,50 €' a Decimal con 2 decimales."""
    if valor is None or valor == "":
        return None
    if isinstance(valor, (int, float, Decimal)):
        texto = str(valor)
    else:
        texto = str(valor).strip().replace("€", "").replace("EUR", "").replace(" ", "")
        # "1.234,56" -> "1234.56" ; "12,50" -> "12.50"
        if "," in texto and "." in texto:
            texto = texto.replace(".", "").replace(",", ".")
        else:
            texto = texto.replace(",", ".")
    try:
        return Decimal(texto).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def a_fecha(valor) -> date | None:
    if isinstance(valor, date):
        return valor
    if not valor:
        return None
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# NIF / NIE / CIF (comprobando el dígito de control)
# ---------------------------------------------------------------------------
_LETRAS_NIF = "TRWAGMYFPDXBNJZSQVHLCKE"


def limpiar_identificador(valor: str | None) -> str | None:
    if not valor:
        return None
    limpio = re.sub(r"[\s\-.]", "", str(valor)).upper()
    if limpio.startswith("ES") and len(limpio) == 11:   # NIF intracomunitario
        limpio = limpio[2:]
    return limpio or None


def es_nif_valido(valor: str | None) -> bool:
    """Valida NIF de persona física, NIE o CIF de empresa."""
    v = limpiar_identificador(valor)
    if not v or len(v) != 9:
        return False

    # NIF persona física: 8 dígitos + letra
    if re.fullmatch(r"\d{8}[A-Z]", v):
        return _LETRAS_NIF[int(v[:8]) % 23] == v[8]

    # NIE: X/Y/Z + 7 dígitos + letra
    if re.fullmatch(r"[XYZ]\d{7}[A-Z]", v):
        numero = "XYZ".index(v[0]) * 10_000_000 + int(v[1:8])
        return _LETRAS_NIF[numero % 23] == v[8]

    # CIF empresa: letra + 7 dígitos + control (dígito o letra)
    if re.fullmatch(r"[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]", v):
        digitos = v[1:8]
        suma_pares = sum(int(d) for d in digitos[1::2])
        suma_impares = 0
        for d in digitos[0::2]:
            doble = int(d) * 2
            suma_impares += doble // 10 + doble % 10
        control = (10 - (suma_pares + suma_impares) % 10) % 10
        letra_control = "JABCDEFGHI"[control]

        if v[0] in "PQRSNW":          # estas entidades llevan letra
            return v[8] == letra_control
        if v[0] in "ABEH":            # estas llevan número
            return v[8] == str(control)
        return v[8] in (str(control), letra_control)

    return False


# ---------------------------------------------------------------------------
# Validación principal
# ---------------------------------------------------------------------------
def validar_ticket(
    datos: dict,
    limites_categoria: dict[str, Decimal | None] | None = None,
    hoy: date | None = None,
) -> tuple[dict, list[str], str]:
    """
    Normaliza un ticket leído por la IA y aplica las reglas de negocio.

    Devuelve (ticket_normalizado, avisos, estado_inicial).
    estado_inicial es 'revisar' si hay algo dudoso y 'pendiente' si está limpio.
    """
    hoy = hoy or date.today()
    limites_categoria = limites_categoria or {}
    avisos: list[str] = []
    necesita_revision = False

    t = {
        "fecha": a_fecha(datos.get("fecha")),
        "comercio": (datos.get("comercio") or "").strip() or None,
        "cif": limpiar_identificador(datos.get("cif")),
        "numero_ticket": (str(datos.get("numero_ticket")).strip() if datos.get("numero_ticket") else None),
        "base_imponible": a_decimal(datos.get("base_imponible")),
        "tipo_iva": a_decimal(datos.get("tipo_iva")),
        "cuota_iva": a_decimal(datos.get("cuota_iva")),
        "total": a_decimal(datos.get("total")),
        "moneda": (datos.get("moneda") or "EUR").upper()[:3],
        "categoria": datos.get("categoria") if datos.get("categoria") in CATEGORIAS else "otros",
        "metodo_pago": datos.get("metodo_pago") or None,
        "es_factura_completa": bool(datos.get("es_factura_completa")),
        "confianza": a_decimal(datos.get("confianza")),
    }

    # --- Total y fecha son obligatorios -----------------------------------
    if t["total"] is None:
        avisos.append("No se ha podido leer el importe total.")
        necesita_revision = True
    if t["fecha"] is None:
        avisos.append("No se ha podido leer la fecha.")
        necesita_revision = True
    elif t["fecha"] > hoy:
        avisos.append("La fecha del ticket es futura.")
        necesita_revision = True
    elif t["fecha"] < hoy - timedelta(days=DIAS_MAXIMOS_ANTIGUEDAD):
        avisos.append(f"Ticket con más de {DIAS_MAXIMOS_ANTIGUEDAD} días de antigüedad.")

    # --- Coherencia de importes: base + IVA = total ------------------------
    base, tipo, cuota, total = t["base_imponible"], t["tipo_iva"], t["cuota_iva"], t["total"]

    if total is not None and base is None and tipo is not None:
        # Solo viene el total (típico en tickets): calculamos la base desde el tipo
        base = (total / (1 + tipo / 100)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        cuota = total - base
        t["base_imponible"], t["cuota_iva"] = base, cuota
        avisos.append("Base imponible e IVA calculados a partir del total.")
    elif total is not None and base is not None and cuota is None:
        cuota = total - base
        t["cuota_iva"] = cuota

    if total is not None and base is not None and cuota is not None:
        if abs(base + cuota - total) > TOLERANCIA:
            avisos.append(
                f"Los importes no cuadran: base {base} + IVA {cuota} ≠ total {total}."
            )
            necesita_revision = True

    if tipo is not None and tipo not in TIPOS_IVA_VALIDOS:
        avisos.append(f"Tipo de IVA poco habitual: {tipo}%.")
        necesita_revision = True

    # --- Identificación fiscal del emisor ----------------------------------
    if t["cif"] is None:
        avisos.append("El ticket no muestra CIF/NIF del emisor.")
    elif not es_nif_valido(t["cif"]):
        avisos.append(f"El CIF/NIF {t['cif']} no es válido (dígito de control).")
        necesita_revision = True

    if not t["es_factura_completa"] and t["cuota_iva"]:
        avisos.append("Ticket sin datos de la empresa: para deducir el IVA hace falta factura completa.")

    # --- Política de gastos -------------------------------------------------
    limite = limites_categoria.get(t["categoria"])
    if limite is not None and total is not None and total > limite:
        avisos.append(f"Supera el límite de {limite} € por ticket para '{t['categoria']}'.")
        necesita_revision = True

    if t["moneda"] != "EUR":
        avisos.append(f"Ticket en moneda extranjera ({t['moneda']}).")
        necesita_revision = True

    # --- Confianza de la IA -------------------------------------------------
    if t["confianza"] is not None and t["confianza"] < CONFIANZA_MINIMA:
        avisos.append(f"La IA tiene poca confianza en la lectura ({t['confianza']}).")
        necesita_revision = True

    estado = "revisar" if necesita_revision else "pendiente"
    return t, avisos, estado
