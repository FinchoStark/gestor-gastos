# Contexto del proyecto para Claude Code

Gestor de gastos de empleados: fotos de tickets → Claude (visión) → validaciones → PostgreSQL.

## Comandos
- Arrancar: `uvicorn app.main:app --reload`
- Tests: `pytest`
- Probar solo la IA: `python -m scripts.leer_ticket foto.jpg`
- BD local: `docker compose up -d`

## Normas del proyecto
- Código, nombres y mensajes en español.
- Dinero siempre con `Decimal` en Python y `NUMERIC(10,2)` en PostgreSQL. Nunca `float`.
- SQL a mano con psycopg 3 y siempre con parámetros (`%s`, `%(nombre)s`). Sin ORM.
- Las reglas de negocio van en `app/validacion.py`, sin dependencias de web ni BD, y cada regla nueva lleva su test en `tests/`.
- `app/schema.sql` debe seguir siendo idempotente (`IF NOT EXISTS`, `ON CONFLICT DO NOTHING`).
- Ningún gasto se aprueba automáticamente: la IA propone y una persona decide.
- Variables de S3 con prefijo `S3_` (Vercel reserva `AWS_*`).
