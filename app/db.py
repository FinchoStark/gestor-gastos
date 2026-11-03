"""
Acceso a PostgreSQL con psycopg 3 y SQL escrito a mano.

Sin ORM a propósito: así se ve exactamente qué consultas se lanzan.
Todas las consultas usan parámetros (%s / %(nombre)s), nunca se concatena
texto del usuario dentro del SQL -> protección contra inyección SQL.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from . import config

ESQUEMA = Path(__file__).with_name("schema.sql")

CAMPOS_GASTO = [
    "fecha", "comercio", "cif", "numero_ticket", "base_imponible", "tipo_iva",
    "cuota_iva", "total", "moneda", "categoria", "metodo_pago",
    "es_factura_completa", "confianza",
]


@contextmanager
def conexion():
    """Abre una conexión, hace COMMIT si todo va bien y ROLLBACK si hay error."""
    # prepare_threshold=None: compatible con poolers tipo PgBouncer (Neon, Supabase)
    with psycopg.connect(config.DATABASE_URL, row_factory=dict_row, prepare_threshold=None) as con:
        yield con


def inicializar() -> None:
    with conexion() as con:
        con.execute(ESQUEMA.read_text(encoding="utf-8"))


def comprobar() -> bool:
    with conexion() as con:
        return con.execute("SELECT 1 AS ok").fetchone()["ok"] == 1


# ---------------------------------------------------------------- empleados
def listar_empleados(con) -> list[dict]:
    return con.execute("SELECT id, nombre, email, departamento FROM empleados ORDER BY nombre").fetchall()


def crear_empleado(con, nombre: str, email: str | None, departamento: str | None) -> dict:
    return con.execute(
        """INSERT INTO empleados (nombre, email, departamento)
           VALUES (%s, %s, %s)
           RETURNING id, nombre, email, departamento""",
        (nombre, email, departamento),
    ).fetchone()


def existe_empleado(con, empleado_id: int) -> bool:
    return con.execute("SELECT 1 FROM empleados WHERE id = %s", (empleado_id,)).fetchone() is not None


# --------------------------------------------------------------- categorías
def listar_categorias(con) -> list[dict]:
    return con.execute("SELECT codigo, nombre, limite_por_ticket FROM categorias ORDER BY nombre").fetchall()


def limites_categoria(con) -> dict:
    return {c["codigo"]: c["limite_por_ticket"] for c in listar_categorias(con)}


# -------------------------------------------------------------------- fotos
def foto_por_hash(con, hash_sha256: str) -> dict | None:
    return con.execute("SELECT * FROM fotos WHERE hash_sha256 = %s", (hash_sha256,)).fetchone()


def insertar_foto(con, empleado_id, hash_sha256, nombre_archivo, tipo_mime, ruta_almacen) -> int:
    return con.execute(
        """INSERT INTO fotos (empleado_id, hash_sha256, nombre_archivo, tipo_mime, ruta_almacen)
           VALUES (%s, %s, %s, %s, %s)
           RETURNING id""",
        (empleado_id, hash_sha256, nombre_archivo, tipo_mime, ruta_almacen),
    ).fetchone()["id"]


def obtener_foto(con, foto_id: int) -> dict | None:
    return con.execute("SELECT * FROM fotos WHERE id = %s", (foto_id,)).fetchone()


# ------------------------------------------------------------------- gastos
SELECT_GASTOS = """
    SELECT g.*, e.nombre AS empleado, c.nombre AS categoria_nombre
    FROM gastos g
    JOIN empleados e ON e.id = g.empleado_id
    JOIN categorias c ON c.codigo = g.categoria
"""


def buscar_duplicado(con, ticket: dict, excluir_id: int | None = None) -> int | None:
    """Mismo emisor, misma fecha y mismo total => probablemente el mismo ticket."""
    if not (ticket.get("cif") and ticket.get("fecha") and ticket.get("total") is not None):
        return None
    fila = con.execute(
        """SELECT id FROM gastos
           WHERE cif = %s AND fecha = %s AND total = %s
             AND id <> COALESCE(%s, -1)
             AND estado <> 'rechazado'
           LIMIT 1""",
        (ticket["cif"], ticket["fecha"], ticket["total"], excluir_id),
    ).fetchone()
    return fila["id"] if fila else None


def insertar_gasto(con, foto_id, empleado_id, ticket: dict, avisos, estado, datos_ia) -> dict:
    valores = {campo: ticket.get(campo) for campo in CAMPOS_GASTO}
    valores |= {
        "foto_id": foto_id, "empleado_id": empleado_id, "estado": estado,
        "avisos": Jsonb(avisos), "datos_ia": Jsonb(datos_ia),
    }
    columnas = list(valores)
    consulta = sql.SQL("INSERT INTO gastos ({}) VALUES ({}) RETURNING id").format(
        sql.SQL(", ").join(map(sql.Identifier, columnas)),
        sql.SQL(", ").join(sql.Placeholder(c) for c in columnas),
    )
    nuevo_id = con.execute(consulta, valores).fetchone()["id"]
    return obtener_gasto(con, nuevo_id)


def obtener_gasto(con, gasto_id: int) -> dict | None:
    return con.execute(SELECT_GASTOS + " WHERE g.id = %s", (gasto_id,)).fetchone()


def gastos_de_foto(con, foto_id: int) -> list[dict]:
    return con.execute(SELECT_GASTOS + " WHERE g.foto_id = %s ORDER BY g.id", (foto_id,)).fetchall()


def listar_gastos(con, estado=None, empleado_id=None, categoria=None, desde=None, hasta=None) -> list[dict]:
    condiciones, params = [], {}
    if estado:
        condiciones.append("g.estado = %(estado)s"); params["estado"] = estado
    if empleado_id:
        condiciones.append("g.empleado_id = %(empleado_id)s"); params["empleado_id"] = empleado_id
    if categoria:
        condiciones.append("g.categoria = %(categoria)s"); params["categoria"] = categoria
    if desde:
        condiciones.append("g.fecha >= %(desde)s"); params["desde"] = desde
    if hasta:
        condiciones.append("g.fecha <= %(hasta)s"); params["hasta"] = hasta
    where = (" WHERE " + " AND ".join(condiciones)) if condiciones else ""
    return con.execute(
        SELECT_GASTOS + where + " ORDER BY g.fecha DESC NULLS LAST, g.id DESC", params
    ).fetchall()


def actualizar_gasto(con, gasto_id: int, ticket: dict, avisos, estado) -> dict | None:
    valores = {campo: ticket.get(campo) for campo in CAMPOS_GASTO}
    valores |= {"avisos": Jsonb(avisos), "estado": estado, "id": gasto_id}
    asignaciones = sql.SQL(", ").join(
        sql.SQL("{} = {}").format(sql.Identifier(c), sql.Placeholder(c)) for c in valores if c != "id"
    )
    consulta = sql.SQL("UPDATE gastos SET {}, revisado_en = now() WHERE id = %(id)s RETURNING id").format(asignaciones)
    if con.execute(consulta, valores).fetchone() is None:
        return None
    return obtener_gasto(con, gasto_id)


def cambiar_estado(con, gasto_id: int, estado: str, motivo: str | None = None) -> dict | None:
    fila = con.execute(
        """UPDATE gastos SET estado = %s, motivo_rechazo = %s, revisado_en = now()
           WHERE id = %s RETURNING id""",
        (estado, motivo, gasto_id),
    ).fetchone()
    return obtener_gasto(con, gasto_id) if fila else None


def borrar_gasto(con, gasto_id: int) -> bool:
    fila = con.execute("DELETE FROM gastos WHERE id = %s RETURNING foto_id", (gasto_id,)).fetchone()
    if fila is None:
        return False
    # Si la foto se queda sin gastos se olvida su registro, para poder volver a subirla
    con.execute(
        """DELETE FROM fotos f
           WHERE f.id = %s
             AND NOT EXISTS (SELECT 1 FROM gastos g WHERE g.foto_id = f.id)""",
        (fila["foto_id"],),
    )
    return True


def resumen(con) -> dict:
    por_estado = con.execute(
        """SELECT estado, count(*) AS num, COALESCE(sum(total), 0) AS total
           FROM gastos GROUP BY estado"""
    ).fetchall()
    por_categoria = con.execute(
        """SELECT c.codigo, c.nombre, count(g.id) AS num,
                  COALESCE(sum(g.total), 0) AS total,
                  COALESCE(sum(g.cuota_iva), 0) AS iva
           FROM categorias c
           LEFT JOIN gastos g ON g.categoria = c.codigo AND g.estado <> 'rechazado'
           GROUP BY c.codigo, c.nombre
           HAVING count(g.id) > 0
           ORDER BY total DESC"""
    ).fetchall()
    return {"por_estado": por_estado, "por_categoria": por_categoria}
