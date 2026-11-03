"""
API del gestor de gastos de empleados.

Flujo principal (POST /api/tickets):
  foto(s) -> hash (evitar duplicados) -> IA lee los tickets -> validaciones
  contables -> guardar foto (S3/local) -> insertar en PostgreSQL en una transacción
"""
from __future__ import annotations

import csv
import hashlib
import io
import logging
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal

import psycopg
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import almacen, config, db, extractor
from .validacion import validar_ticket

log = logging.getLogger("gastos")

TIPOS_ADMITIDOS = {"image/jpeg", "image/png", "image/webp", "image/gif"}
Estado = Literal["revisar", "pendiente", "aprobado", "rechazado"]


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        db.inicializar()  # crea tablas si no existen (idempotente)
    except Exception as e:  # la app arranca igual y /api/salud mostrará el problema
        log.error("No se pudo inicializar la base de datos: %s", e)
    yield


app = FastAPI(
    title="Gestor de gastos de empleados",
    description="Fotos de tickets -> IA -> PostgreSQL",
    version="1.0.0",
    lifespan=lifespan,
)


@app.exception_handler(psycopg.OperationalError)
async def error_bd(_, exc):
    log.error("Error de conexión con PostgreSQL: %s", exc)
    return JSONResponse(status_code=503, content={"detail": "No hay conexión con la base de datos."})


# ------------------------------------------------------------------ modelos
class EmpleadoNuevo(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    email: str | None = None
    departamento: str | None = None


class GastoEditado(BaseModel):
    """Todos opcionales: solo se cambian los campos que se envían (PATCH)."""
    fecha: date | None = None
    comercio: str | None = None
    cif: str | None = None
    numero_ticket: str | None = None
    base_imponible: Decimal | None = None
    tipo_iva: Decimal | None = None
    cuota_iva: Decimal | None = None
    total: Decimal | None = Field(default=None, ge=0)
    moneda: str | None = None
    categoria: str | None = None
    metodo_pago: str | None = None
    es_factura_completa: bool | None = None


class Rechazo(BaseModel):
    motivo: str | None = None


# ------------------------------------------------------------------- estado
@app.get("/api/salud")
def salud():
    try:
        bd_ok = db.comprobar()
    except Exception:
        bd_ok = False
    return {"base_datos": bd_ok, "ia": extractor.modo(), "almacenamiento": almacen.modo()}


# ---------------------------------------------------------------- catálogos
@app.get("/api/empleados")
def empleados():
    with db.conexion() as con:
        return db.listar_empleados(con)


@app.post("/api/empleados", status_code=201)
def nuevo_empleado(datos: EmpleadoNuevo):
    with db.conexion() as con:
        try:
            return db.crear_empleado(con, datos.nombre.strip(), datos.email, datos.departamento)
        except psycopg.errors.UniqueViolation:
            raise HTTPException(409, "Ya existe un empleado con ese email.")


@app.get("/api/categorias")
def categorias():
    with db.conexion() as con:
        return db.listar_categorias(con)


# ------------------------------------------------------- subida de tickets
@app.post("/api/tickets", status_code=201)
def subir_tickets(empleado_id: int = Form(...), archivos: list[UploadFile] = File(...)):
    """Recibe una o varias fotos. Cada foto puede contener uno o varios tickets."""
    with db.conexion() as con:
        if not db.existe_empleado(con, empleado_id):
            raise HTTPException(404, "Empleado no encontrado.")
        limites = db.limites_categoria(con)

    resultados = []
    for archivo in archivos:
        resultados.append(_procesar_foto(archivo, empleado_id, limites))
    return {"resultados": resultados}


def _procesar_foto(archivo: UploadFile, empleado_id: int, limites: dict) -> dict:
    nombre = archivo.filename or "foto"
    tipo = (archivo.content_type or "").lower()
    contenido = archivo.file.read()

    if tipo not in TIPOS_ADMITIDOS:
        return {"archivo": nombre, "error": f"Formato no admitido ({tipo or 'desconocido'}). Usa JPG, PNG o WEBP."}
    if len(contenido) > config.TAMANO_MAXIMO_FOTO:
        return {"archivo": nombre, "error": "La foto pesa más de 4 MB."}

    huella = hashlib.sha256(contenido).hexdigest()

    # 1) ¿Ya se subió esta misma foto?
    with db.conexion() as con:
        existente = db.foto_por_hash(con, huella)
        if existente:
            return {
                "archivo": nombre,
                "duplicada": True,
                "aviso": "Esta foto ya se había subido; no se ha vuelto a registrar.",
                "gastos": db.gastos_de_foto(con, existente["id"]),
            }

    # 2) La IA lee los tickets (fuera de la transacción: puede tardar unos segundos)
    try:
        tickets_ia = extractor.extraer_tickets(contenido, tipo)
    except Exception as e:
        log.exception("Fallo leyendo el ticket")
        return {"archivo": nombre, "error": f"No se pudo leer la foto con la IA: {e}"}

    if not tickets_ia:
        return {"archivo": nombre, "error": "No se ha detectado ningún ticket en la foto."}

    # 3) Guardar la foto (S3 / local)
    ruta = almacen.guardar(contenido, huella, tipo)

    # 4) Validar e insertar todo en UNA transacción
    with db.conexion() as con:
        foto_id = db.insertar_foto(con, empleado_id, huella, nombre, tipo, ruta)
        gastos = []
        for datos in tickets_ia:
            ticket, avisos, estado = validar_ticket(datos, limites)
            duplicado = db.buscar_duplicado(con, ticket)
            if duplicado:
                avisos.append(f"Posible duplicado del gasto #{duplicado}.")
                estado = "revisar"
            gastos.append(db.insertar_gasto(con, foto_id, empleado_id, ticket, avisos, estado, datos))
    return {"archivo": nombre, "foto_id": foto_id, "gastos": gastos}


# ------------------------------------------------------------------- gastos
@app.get("/api/gastos")
def listar_gastos(
    estado: Estado | None = None,
    empleado_id: int | None = None,
    categoria: str | None = None,
    desde: date | None = None,
    hasta: date | None = None,
):
    with db.conexion() as con:
        return db.listar_gastos(con, estado, empleado_id, categoria, desde, hasta)


@app.get("/api/gastos/{gasto_id}")
def ver_gasto(gasto_id: int):
    with db.conexion() as con:
        gasto = db.obtener_gasto(con, gasto_id)
    if not gasto:
        raise HTTPException(404, "Gasto no encontrado.")
    return gasto


@app.patch("/api/gastos/{gasto_id}")
def editar_gasto(gasto_id: int, cambios: GastoEditado):
    """Corrección manual: se vuelven a pasar todas las validaciones."""
    with db.conexion() as con:
        actual = db.obtener_gasto(con, gasto_id)
        if not actual:
            raise HTTPException(404, "Gasto no encontrado.")
        datos = {campo: actual[campo] for campo in db.CAMPOS_GASTO}
        datos |= cambios.model_dump(exclude_unset=True)
        datos["confianza"] = Decimal("1.00")  # revisado por una persona
        ticket, avisos, estado = validar_ticket(datos, db.limites_categoria(con))
        duplicado = db.buscar_duplicado(con, ticket, excluir_id=gasto_id)
        if duplicado:
            avisos.append(f"Posible duplicado del gasto #{duplicado}.")
            estado = "revisar"
        return db.actualizar_gasto(con, gasto_id, ticket, avisos, estado)


@app.post("/api/gastos/{gasto_id}/aprobar")
def aprobar(gasto_id: int):
    with db.conexion() as con:
        gasto = db.obtener_gasto(con, gasto_id)
        if not gasto:
            raise HTTPException(404, "Gasto no encontrado.")
        if gasto["total"] is None or gasto["fecha"] is None:
            raise HTTPException(422, "No se puede aprobar un gasto sin fecha o sin total.")
        return db.cambiar_estado(con, gasto_id, "aprobado")


@app.post("/api/gastos/{gasto_id}/rechazar")
def rechazar(gasto_id: int, datos: Rechazo):
    with db.conexion() as con:
        gasto = db.cambiar_estado(con, gasto_id, "rechazado", datos.motivo)
    if not gasto:
        raise HTTPException(404, "Gasto no encontrado.")
    return gasto


@app.delete("/api/gastos/{gasto_id}", status_code=204)
def borrar(gasto_id: int):
    with db.conexion() as con:
        if not db.borrar_gasto(con, gasto_id):
            raise HTTPException(404, "Gasto no encontrado.")
    return Response(status_code=204)


@app.get("/api/resumen")
def resumen():
    with db.conexion() as con:
        return db.resumen(con)


@app.get("/api/exportar.csv")
def exportar_csv(estado: Estado | None = Query(default="aprobado")):
    """CSV listo para abrir en Excel (separador ';' y coma decimal)."""
    with db.conexion() as con:
        gastos = db.listar_gastos(con, estado=estado)

    columnas = ["id", "fecha", "empleado", "comercio", "cif", "numero_ticket", "categoria_nombre",
                "base_imponible", "tipo_iva", "cuota_iva", "total", "moneda", "es_factura_completa", "estado"]
    salida = io.StringIO()
    salida.write("﻿")  # BOM: Excel detecta UTF-8 y muestra bien las tildes
    escritor = csv.writer(salida, delimiter=";")
    escritor.writerow(columnas)
    for g in gastos:
        fila = []
        for c in columnas:
            v = g.get(c)
            if isinstance(v, Decimal):
                v = f"{v:.2f}".replace(".", ",")
            elif isinstance(v, bool):
                v = "sí" if v else "no"
            fila.append("" if v is None else v)
        escritor.writerow(fila)

    nombre = f"gastos_{estado or 'todos'}_{date.today():%Y%m%d}.csv"
    return Response(
        salida.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


@app.get("/api/fotos/{foto_id}")
def ver_foto(foto_id: int):
    with db.conexion() as con:
        foto = db.obtener_foto(con, foto_id)
    if not foto or not foto["ruta_almacen"]:
        raise HTTPException(404, "Foto no disponible.")
    if almacen.modo() == "s3":
        return RedirectResponse(almacen.url_firmada(foto["ruta_almacen"]))
    ruta = almacen.ruta_local(foto["ruta_almacen"])
    if not ruta:
        raise HTTPException(404, "Foto no disponible.")
    return FileResponse(ruta, media_type=foto["tipo_mime"])


# ------------------------------------------------- interfaz web (al final)
# Se monta lo último para que las rutas /api/* tengan prioridad.
app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "static", html=True), name="web")
