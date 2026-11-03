from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.extractor import ESQUEMA, _ticket_demo, parsear_respuesta
from app.validacion import a_decimal, campos_fuera_de_rango, es_nif_valido, validar_ticket

HOY = date(2026, 11, 3)


def ticket(**cambios):
    base = {
        "comercio": "Restaurante Casa Pepe",
        "cif": "B12345674",
        "fecha": "2026-11-02",
        "base_imponible": 20.00,
        "tipo_iva": 10,
        "cuota_iva": 2.00,
        "total": 22.00,
        "categoria": "comida",
        "confianza": 0.95,
        "es_factura_completa": True,
    }
    base.update(cambios)
    return base


# ------------------------------------------------------------ importes
def test_a_decimal_formatos_espanoles():
    assert a_decimal("12,50 €") == Decimal("12.50")
    assert a_decimal("1.234,56") == Decimal("1234.56")
    assert a_decimal(7) == Decimal("7.00")
    assert a_decimal("") is None
    assert a_decimal("abc") is None


# ------------------------------------------------------------ NIF / CIF
def test_identificadores_validos():
    assert es_nif_valido("12345678Z")     # NIF
    assert es_nif_valido("X1234567L")     # NIE
    assert es_nif_valido("B12345674")     # CIF sociedad limitada
    assert es_nif_valido("b-1234567-4")   # con guiones y minúsculas
    assert es_nif_valido("ESB12345674")   # NIF intracomunitario


def test_identificadores_invalidos():
    assert not es_nif_valido("12345678A")
    assert not es_nif_valido("B12345675")
    assert not es_nif_valido("hola")
    assert not es_nif_valido(None)


# ------------------------------------------------------------ reglas
def test_ticket_correcto_queda_pendiente():
    t, avisos, estado = validar_ticket(ticket(), hoy=HOY)
    assert estado == "pendiente"
    assert avisos == []
    assert t["total"] == Decimal("22.00")


def test_importes_que_no_cuadran_van_a_revisar():
    _, avisos, estado = validar_ticket(ticket(total=30), hoy=HOY)
    assert estado == "revisar"
    assert any("no cuadran" in a for a in avisos)


def test_calcula_base_desde_total_y_tipo():
    t, avisos, estado = validar_ticket(ticket(base_imponible=None, cuota_iva=None, total=12.10, tipo_iva=21), hoy=HOY)
    assert t["base_imponible"] == Decimal("10.00")
    assert t["cuota_iva"] == Decimal("2.10")
    assert estado == "pendiente"
    assert any("calculados" in a for a in avisos)


def test_cif_invalido_va_a_revisar():
    _, avisos, estado = validar_ticket(ticket(cif="B12345675"), hoy=HOY)
    assert estado == "revisar"


def test_fecha_futura_va_a_revisar():
    _, _, estado = validar_ticket(ticket(fecha=(HOY + timedelta(days=3)).isoformat()), hoy=HOY)
    assert estado == "revisar"


def test_sin_total_va_a_revisar():
    _, avisos, estado = validar_ticket(ticket(total=None, base_imponible=None, cuota_iva=None), hoy=HOY)
    assert estado == "revisar"
    assert any("total" in a for a in avisos)


def test_supera_limite_de_categoria():
    limites = {"comida": Decimal("60.00")}
    _, avisos, estado = validar_ticket(ticket(base_imponible=90.91, cuota_iva=9.09, total=100), limites, hoy=HOY)
    assert estado == "revisar"
    assert any("límite" in a for a in avisos)


def test_poca_confianza_de_la_ia():
    _, _, estado = validar_ticket(ticket(confianza=0.4), hoy=HOY)
    assert estado == "revisar"


def test_categoria_desconocida_pasa_a_otros():
    t, _, _ = validar_ticket(ticket(categoria="caprichos"), hoy=HOY)
    assert t["categoria"] == "otros"


def test_ticket_simplificado_avisa_del_iva():
    _, avisos, estado = validar_ticket(ticket(es_factura_completa=False), hoy=HOY)
    assert estado == "pendiente"   # es solo informativo
    assert any("factura completa" in a for a in avisos)


# ------------------------------------------------------------ extractor
def respuesta_ia(*bloques, stop_reason="end_turn"):
    return SimpleNamespace(stop_reason=stop_reason, content=list(bloques))


def bloque_texto(texto):
    return SimpleNamespace(type="text", text=texto)


def test_parsear_respuesta_json():
    tickets = parsear_respuesta(respuesta_ia(bloque_texto('{"tickets": [{"comercio": "A"}, {"comercio": "B"}]}')))
    assert [t["comercio"] for t in tickets] == ["A", "B"]


def test_parsear_respuesta_ignora_el_razonamiento():
    razonamiento = SimpleNamespace(type="thinking", thinking="")
    tickets = parsear_respuesta(respuesta_ia(razonamiento, bloque_texto('{"tickets": [{"comercio": "A"}]}')))
    assert len(tickets) == 1


def test_parsear_respuesta_sin_tickets():
    assert parsear_respuesta(respuesta_ia(bloque_texto('{"tickets": []}'))) == []


@pytest.mark.parametrize("respuesta", [
    respuesta_ia(stop_reason="refusal"),
    respuesta_ia(bloque_texto('{"tickets": [{"com'), stop_reason="max_tokens"),
    respuesta_ia(),
])
def test_parsear_respuesta_no_utilizable_da_error(respuesta):
    with pytest.raises(ValueError):
        parsear_respuesta(respuesta)


def test_esquema_cumple_lo_que_exige_la_api():
    """Cada objeto debe cerrar sus propiedades y marcarlas todas como obligatorias."""
    item = ESQUEMA["properties"]["tickets"]["items"]
    for objeto in (ESQUEMA, item):
        assert objeto["additionalProperties"] is False
        assert set(objeto["required"]) == set(objeto["properties"])


def test_ticket_demo_es_coherente():
    for _ in range(30):
        t, avisos, _ = validar_ticket(_ticket_demo())
        assert not any("no cuadran" in a or "no es válido" in a for a in avisos), avisos


# ------------------------------------------------- valores que no caben en la BD
def test_total_que_no_cabe_se_anula_y_pasa_a_revisar():
    t, avisos, estado = validar_ticket(ticket(total=99999999999), hoy=HOY)
    assert t["total"] is None
    assert estado == "revisar"
    assert any("fuera de rango" in a for a in avisos)


def test_mayor_importe_admitido_se_conserva():
    t, avisos, _ = validar_ticket(ticket(total="99999999.99"), hoy=HOY)
    assert t["total"] == Decimal("99999999.99")
    assert not any("fuera de rango" in a for a in avisos)


def test_cuota_calculada_que_no_cabe_se_anula():
    t, avisos, estado = validar_ticket(
        ticket(base_imponible="-99999999.00", cuota_iva=None, total="99999999.00"), hoy=HOY
    )
    assert t["cuota_iva"] is None
    assert estado == "revisar"
    assert any("fuera de rango" in a for a in avisos)


def test_tipo_iva_negativo_o_enorme_se_anula():
    for tipo in (-100, 1000):  # -100 además dividiría entre cero al calcular la base
        t, avisos, estado = validar_ticket(ticket(tipo_iva=tipo, base_imponible=None, cuota_iva=None), hoy=HOY)
        assert t["tipo_iva"] is None
        assert estado == "revisar"
        assert any("fuera de rango" in a for a in avisos)


def test_confianza_como_porcentaje_se_anula():
    t, avisos, estado = validar_ticket(ticket(confianza=95), hoy=HOY)
    assert t["confianza"] is None
    assert estado == "revisar"
    assert any("fuera de rango" in a for a in avisos)


def test_a_decimal_descarta_valores_no_finitos():
    assert a_decimal("NaN") is None
    assert a_decimal("Infinity") is None


def test_campos_fuera_de_rango_lista_los_campos():
    assert campos_fuera_de_rango({"total": "99999999999", "tipo_iva": 21, "cuota_iva": None}) == ["total"]
    assert campos_fuera_de_rango({"total": "12.10"}) == []
