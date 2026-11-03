from urllib.parse import parse_qs, urlparse

from app import almacen, config


def test_url_firmada_usa_el_host_de_la_region(monkeypatch):
    monkeypatch.setattr(config, "S3_BUCKET", "mi-bucket")
    monkeypatch.setattr(config, "S3_REGION", "eu-south-2")
    monkeypatch.setattr(config, "S3_ACCESS_KEY_ID", "CLAVE-DE-PRUEBA")
    monkeypatch.setattr(config, "S3_SECRET_ACCESS_KEY", "secreto-de-prueba")

    url = urlparse(almacen.url_firmada("tickets/2026/11/foto.jpg"))
    parametros = parse_qs(url.query)

    assert url.netloc == "mi-bucket.s3.eu-south-2.amazonaws.com"
    assert url.path == "/tickets/2026/11/foto.jpg"
    assert parametros["X-Amz-Algorithm"] == ["AWS4-HMAC-SHA256"]
    assert parametros["X-Amz-Expires"] == ["600"]
    assert "eu-south-2" in parametros["X-Amz-Credential"][0]
