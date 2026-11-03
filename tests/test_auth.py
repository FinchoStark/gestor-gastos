import base64

import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.auth import credenciales_validas
from app.main import app


def basic(usuario: str, contrasena: str) -> str:
    return "Basic " + base64.b64encode(f"{usuario}:{contrasena}".encode()).decode()


# ------------------------------------------------- comprobación de la cabecera
def test_credenciales_correctas():
    assert credenciales_validas(basic("admin", "s3creta"), "admin", "s3creta")


def test_contrasena_con_dos_puntos_y_tildes():
    assert credenciales_validas(basic("admin", "a:ñ:b"), "admin", "a:ñ:b")


@pytest.mark.parametrize("cabecera", [
    None,
    "",
    "Basic",
    "Basic !!!no-es-base64!!!",
    "Basic " + base64.b64encode(b"sin-dos-puntos").decode(),
    "Bearer abc",
    basic("admin", "mala"),
    basic("otro", "s3creta"),
    basic("", ""),
])
def test_credenciales_incorrectas(cabecera):
    assert not credenciales_validas(cabecera, "admin", "s3creta")


# ------------------------------------------------------------- toda la app
@pytest.fixture
def cliente(monkeypatch):
    monkeypatch.setattr(db, "comprobar", lambda: True)
    monkeypatch.setattr(config, "APP_USUARIO", "admin")
    monkeypatch.setattr(config, "APP_CONTRASENA", "s3creta")
    monkeypatch.setattr(config, "EN_VERCEL", False)
    return TestClient(app)  # sin "with": no ejecuta el arranque (no toca la BD)


@pytest.mark.parametrize("ruta", ["/", "/index.html", "/api/salud", "/api/gastos", "/api/exportar.csv", "/docs", "/openapi.json"])
def test_sin_credenciales_todo_devuelve_401(cliente, ruta):
    r = cliente.get(ruta)
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith("Basic")


def test_escritura_sin_credenciales_devuelve_401(cliente):
    assert cliente.delete("/api/gastos/1").status_code == 401


def test_con_credenciales_entra(cliente):
    cabeceras = {"Authorization": basic("admin", "s3creta")}
    assert cliente.get("/api/salud", headers=cabeceras).status_code == 200
    assert cliente.get("/", headers=cabeceras).status_code == 200


def test_en_vercel_sin_configurar_no_abre_la_app(cliente, monkeypatch):
    monkeypatch.setattr(config, "APP_CONTRASENA", "")
    monkeypatch.setattr(config, "APP_USUARIO", "")
    monkeypatch.setattr(config, "EN_VERCEL", True)
    assert cliente.get("/api/salud").status_code == 503


def test_configuracion_a_medias_no_abre_la_app(cliente, monkeypatch):
    monkeypatch.setattr(config, "APP_CONTRASENA", "")
    assert cliente.get("/api/salud").status_code == 503


def test_en_local_sin_configurar_queda_abierta(cliente, monkeypatch):
    monkeypatch.setattr(config, "APP_CONTRASENA", "")
    monkeypatch.setattr(config, "APP_USUARIO", "")
    assert cliente.get("/api/salud").status_code == 200
