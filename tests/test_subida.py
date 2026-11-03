from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from app import almacen, config, db, extractor
from app.main import app


@pytest.fixture
def cliente(monkeypatch):
    """App sin contraseña, con la BD y la IA simuladas (no toca nada real)."""
    monkeypatch.setattr(config, "APP_USUARIO", "")
    monkeypatch.setattr(config, "APP_CONTRASENA", "")
    monkeypatch.setattr(config, "EN_VERCEL", False)

    @contextmanager
    def conexion_falsa():
        yield None

    monkeypatch.setattr(db, "conexion", conexion_falsa)
    monkeypatch.setattr(db, "existe_empleado", lambda con, empleado_id: True)
    monkeypatch.setattr(db, "limites_categoria", lambda con: {})
    monkeypatch.setattr(db, "foto_por_hash", lambda con, huella: None)
    monkeypatch.setattr(db, "buscar_duplicado", lambda con, ticket: None)
    monkeypatch.setattr(db, "insertar_foto", lambda con, *args: 1)
    monkeypatch.setattr(db, "insertar_gasto", lambda con, *args: {"id": 1, "total": "10.00"})
    monkeypatch.setattr(extractor, "extraer_tickets", lambda imagen, tipo: [{"total": 10}])
    return TestClient(app)


def subir(cliente, *fotos):
    archivos = [("archivos", (nombre, contenido, "image/jpeg")) for nombre, contenido in fotos]
    return cliente.post("/api/tickets", data={"empleado_id": 1}, files=archivos)


def test_fallo_de_almacenamiento_no_tumba_la_tanda(cliente, monkeypatch):
    def guardar(contenido, huella, tipo):
        if contenido == b"mala":
            raise RuntimeError("clave-secreta-de-s3")
        return "tickets/foto.jpg"

    monkeypatch.setattr(almacen, "guardar", guardar)

    r = subir(cliente, ("mala.jpg", b"mala"), ("buena.jpg", b"buena"))

    assert r.status_code == 201
    mala, buena = r.json()["resultados"]
    assert mala["archivo"] == "mala.jpg"
    assert "No se pudo guardar la foto" in mala["error"]
    assert "clave-secreta-de-s3" not in mala["error"]  # el detalle va al log, no al usuario
    assert buena["gastos"]


def test_si_no_se_guarda_la_foto_no_se_registra_el_gasto(cliente, monkeypatch):
    def guardar(contenido, huella, tipo):
        raise RuntimeError("fallo de S3")

    def insertar_foto(con, *args):
        pytest.fail("No debe registrarse una foto que no se ha guardado")

    monkeypatch.setattr(almacen, "guardar", guardar)
    monkeypatch.setattr(db, "insertar_foto", insertar_foto)

    assert "error" in subir(cliente, ("foto.jpg", b"foto")).json()["resultados"][0]
