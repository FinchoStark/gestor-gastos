"""
Prueba rápida de la IA sin levantar la web ni la base de datos.

Uso:
    python -m scripts.leer_ticket ruta/a/foto.jpg
"""
import json
import mimetypes
import sys
from pathlib import Path

from app.extractor import extraer_tickets, modo
from app.validacion import validar_ticket

if len(sys.argv) != 2:
    sys.exit("Uso: python -m scripts.leer_ticket foto.jpg")

ruta = Path(sys.argv[1])
tipo = mimetypes.guess_type(ruta.name)[0] or "image/jpeg"
print(f"Modo IA: {modo()} · leyendo {ruta.name} ({tipo})\n")

for i, datos in enumerate(extraer_tickets(ruta.read_bytes(), tipo), start=1):
    ticket, avisos, estado = validar_ticket(datos)
    print(f"--- Ticket {i} · estado inicial: {estado}")
    print(json.dumps(ticket, indent=2, ensure_ascii=False, default=str))
    for aviso in avisos:
        print("  ⚠", aviso)
    print()
