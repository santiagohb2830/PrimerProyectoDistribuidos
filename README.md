# PS — Procesos Solicitantes

Genera solicitudes hacia el Gestor de Carga (GC) por ZeroMQ (REQ → REP).

## Contrato JSON

Cada línea del archivo de entrada es un objeto JSON con:
{
  "op": "DEVOLUCION" | "RENOVACION",
  "idSolicitud": "S-001",
  "idUsuario": "U001",
  "idLibro": "L100",
  "sede": "SEDE1" | "SEDE2",
  "timestamp": "2025-10-07T21:00:00Z",
  "idempotencyKey": "op-idSolicitud-idLibro (opcional, PS lo genera si falta)"
}

## Requisitos

- Python 3.9+
- pyzmq: `pip install pyzmq`

## Ejecución

- Asegúrate de que el GC esté escuchando en `tcp://gc:5555`
  (puede usar IP o nombre `gc` vía /etc/hosts o docker network).

- Enviar solicitudes de SEDE1:
python ps.py –file data/sol_sede1.txt –host gc –port 5555 –interval 0.2 –retries 1 –timeout_ms 2000
- Enviar solicitudes de SEDE2:
python ps.py –file data/sol_sede2.txt –host gc –port 5555 –interval 0.2 –retries 1 –timeout_ms 2000


En consola se deberia ver respuestas del GC con `{ "ok": true, "msg": "Recibido" }`.

## Notas

- Si el GC no responde a tiempo, el PS reintentar (reconecta el socket).
- `timestamp` se completa si falta (UTC).
- `idempotencyKey` se genera si no se suministra.