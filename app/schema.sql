-- =====================================================================
--  Gestor de gastos de empleados - esquema PostgreSQL
--  Idempotente: se puede ejecutar varias veces sin romper nada.
-- =====================================================================

CREATE TABLE IF NOT EXISTS empleados (
    id            INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    nombre        TEXT NOT NULL,
    email         TEXT UNIQUE,
    departamento  TEXT,
    creado_en     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Catálogo de categorías con un límite orientativo por ticket (política de gastos)
CREATE TABLE IF NOT EXISTS categorias (
    codigo             TEXT PRIMARY KEY,
    nombre             TEXT NOT NULL,
    limite_por_ticket  NUMERIC(10,2)          -- NULL = sin límite
);

-- Cada foto subida. Una foto puede contener uno o VARIOS tickets.
CREATE TABLE IF NOT EXISTS fotos (
    id              INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    empleado_id     INT NOT NULL REFERENCES empleados(id),
    hash_sha256     TEXT NOT NULL UNIQUE,     -- evita subir la misma foto dos veces
    nombre_archivo  TEXT,
    tipo_mime       TEXT,
    ruta_almacen    TEXT,                     -- clave en S3 o ruta local
    subida_en       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Cada ticket detectado = una línea de gasto
CREATE TABLE IF NOT EXISTS gastos (
    id                   INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    foto_id              INT REFERENCES fotos(id) ON DELETE CASCADE,
    empleado_id          INT NOT NULL REFERENCES empleados(id),
    fecha                DATE,
    comercio             TEXT,
    cif                  TEXT,
    numero_ticket        TEXT,
    base_imponible       NUMERIC(10,2),
    tipo_iva             NUMERIC(5,2),
    cuota_iva            NUMERIC(10,2),
    total                NUMERIC(10,2) CHECK (total IS NULL OR total >= 0),
    moneda               CHAR(3) NOT NULL DEFAULT 'EUR',
    categoria            TEXT NOT NULL DEFAULT 'otros' REFERENCES categorias(codigo),
    metodo_pago          TEXT,
    es_factura_completa  BOOLEAN NOT NULL DEFAULT false,
    confianza            NUMERIC(3,2),
    estado               TEXT NOT NULL DEFAULT 'pendiente'
                         CHECK (estado IN ('revisar', 'pendiente', 'aprobado', 'rechazado')),
    avisos               JSONB NOT NULL DEFAULT '[]',   -- avisos de las validaciones
    datos_ia             JSONB,                         -- respuesta original de la IA (auditoría)
    motivo_rechazo       TEXT,
    creado_en            TIMESTAMPTZ NOT NULL DEFAULT now(),
    revisado_en          TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_gastos_empleado_fecha ON gastos (empleado_id, fecha);
CREATE INDEX IF NOT EXISTS idx_gastos_estado ON gastos (estado);
CREATE INDEX IF NOT EXISTS idx_gastos_duplicados ON gastos (cif, fecha, total);

-- Resumen mensual para contabilidad: gasto total e IVA soportado por categoría
CREATE OR REPLACE VIEW v_resumen_mensual AS
SELECT
    date_trunc('month', g.fecha)::date AS mes,
    g.categoria,
    c.nombre                           AS categoria_nombre,
    count(*)                           AS num_tickets,
    sum(g.total)                       AS total,
    sum(g.cuota_iva)                   AS iva_soportado,
    sum(g.cuota_iva) FILTER (WHERE g.es_factura_completa) AS iva_deducible
FROM gastos g
JOIN categorias c ON c.codigo = g.categoria
WHERE g.estado = 'aprobado'
GROUP BY 1, 2, 3;

-- ---------------------------------------------------------------------
-- Datos iniciales
-- ---------------------------------------------------------------------
INSERT INTO categorias (codigo, nombre, limite_por_ticket) VALUES
    ('comida',           'Comidas y dietas',        60.00),
    ('alojamiento',      'Alojamiento',            150.00),
    ('transporte',       'Transporte (taxi, tren, avión)', NULL),
    ('combustible',      'Combustible',            120.00),
    ('parking_peajes',   'Parking y peajes',        50.00),
    ('material_oficina', 'Material de oficina',    100.00),
    ('formacion',        'Formación',              NULL),
    ('otros',            'Otros',                  NULL)
ON CONFLICT (codigo) DO NOTHING;

INSERT INTO empleados (nombre, email, departamento)
SELECT * FROM (VALUES
    ('Empleado Demo', 'demo@empresa.local', 'Ventas'),
    ('Responsable Demo', 'responsable@empresa.local', 'Administración')
) AS v(nombre, email, departamento)
WHERE NOT EXISTS (SELECT 1 FROM empleados);
