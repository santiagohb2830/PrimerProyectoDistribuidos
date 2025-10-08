#!/usr/bin/env python3
import argparse, json, sys, time, uuid, hashlib
from datetime import datetime, timezone
import zmq

ALLOWED_OPS = {"DEVOLUCION", "RENOVACION"}

def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def ensure_message_contract(msg: dict) -> dict:
    # Validación mínima y autocompletado de campos
    if "op" not in msg or msg["op"] not in ALLOWED_OPS:
        raise ValueError(f'op inválida: {msg.get("op")}. Debe ser una de {ALLOWED_OPS}')
    if "idSolicitud" not in msg:
        msg["idSolicitud"] = f"S-{uuid.uuid4()}"
    for k in ("idUsuario", "idLibro", "sede"):
        if k not in msg:
            raise ValueError(f"falta campo obligatorio: {k}")
    if "timestamp" not in msg:
        msg["timestamp"] = iso_now()
    if "idempotencyKey" not in msg:
        base = f"{msg['op']}:{msg['idSolicitud']}:{msg['idLibro']}"
        msg["idempotencyKey"] = hashlib.sha256(base.encode()).hexdigest()[:16]
    return msg

def send_with_retry(sock, payload: dict, retries: int, timeout_ms: int):
    # Configura timeout de recv por intento
    poller = zmq.Poller()
    poller.register(sock, zmq.POLLIN)

    for attempt in range(1, retries + 1):
        sock.send_json(payload)
        socks = dict(poller.poll(timeout_ms))
        if socks.get(sock) == zmq.POLLIN:
            try:
                reply = sock.recv_json(flags=0)
            except Exception as e:
                return None, f"Respuesta no-JSON: {e}"
            return reply, None
        else:
            # Reintento: reconectar y re-enviar
            try:
                sock.setsockopt(zmq.LINGER, 0)
                sock.close()
            except Exception:
                pass
            # Reabrir socket para siguiente intento
            ctx = zmq.Context.instance()
            sock = ctx.socket(zmq.REQ)
            sock.setsockopt(zmq.RCVTIMEO, timeout_ms)  # seguridad extra
            yield f"timeout intento {attempt}, reintentando..."
            # Dirección se guarda en closure via outer args—no disponible aquí.
            # Esta función se usa con un socket ya conectado por cada envío para simplificar.
            return None, "Reintento requiere reconexión externa"
    return None, "Se agotaron los reintentos"

def main():
    parser = argparse.ArgumentParser(description="Procesos Solicitantes (PS) - Cliente ZeroMQ REQ")
    parser.add_argument("--file", required=True, help="Ruta al archivo de solicitudes (JSON por línea)")
    parser.add_argument("--host", default="gc", help="Host del Gestor de Carga (default: gc)")
    parser.add_argument("--port", type=int, default=5555, help="Puerto REP del GC (default: 5555)")
    parser.add_argument("--interval", type=float, default=0.2, help="Intervalo entre envíos (s)")
    parser.add_argument("--retries", type=int, default=1, help="Reintentos por solicitud (default: 1)")
    parser.add_argument("--timeout_ms", type=int, default=2000, help="Timeout por intento de respuesta (ms)")
    args = parser.parse_args()

    endpoint = f"tcp://{args.host}:{args.port}"
    print(f"[PS] Enviando solicitudes a {endpoint}")

    ctx = zmq.Context.instance()

    # Leemos el archivo línea a línea
    total, ok, fail = 0, 0, 0
    with open(args.file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                raw = json.loads(line)
                msg = ensure_message_contract(raw)
            except Exception as e:
                fail += 1
                print(f"[PS][ERROR] Línea {total} inválida: {e}")
                continue

            # Crear socket por envío para soportar reconexión limpia en reintentos
            sock = ctx.socket(zmq.REQ)
            sock.connect(endpoint)
            sock.setsockopt(zmq.RCVTIMEO, args.timeout_ms)
            sock.setsockopt(zmq.LINGER, 0)

            # Enviar y esperar respuesta con reintento simple (recrear socket si timeout)
            attempt = 1
            while attempt <= max(1, args.retries):
                try:
                    sock.send_json(msg)
                    reply = sock.recv_json()
                    ok += 1
                    print(f"[PS][OK] {msg['op']} id={msg['idSolicitud']} → respuesta: {reply}")
                    break
                except zmq.Again:
                    print(f"[PS][WARN] Timeout intento {attempt} para id={msg['idSolicitud']}")
                    attempt += 1
                    # Reconectar para siguiente intento
                    try:
                        sock.close()
                    except Exception:
                        pass
                    sock = ctx.socket(zmq.REQ)
                    sock.connect(endpoint)
                    sock.setsockopt(zmq.RCVTIMEO, args.timeout_ms)
                    sock.setsockopt(zmq.LINGER, 0)
                except Exception as e:
                    fail += 1
                    print(f"[PS][ERROR] id={msg['idSolicitud']} fallo: {e}")
                    break

            # Ritmo de envío
            time.sleep(max(0.0, args.interval))

    print(f"[PS] Envío terminado. total={total} ok={ok} fail={fail}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[PS] Interrumpido por el usuario")
        sys.exit(130)