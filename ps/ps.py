import argparse, json, sys, time, uuid, hashlib
from datetime import datetime, timezone
import zmq

ALLOWED_OPS = {"DEVOLUCION", "RENOVACION", "PRESTAMO"}


def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def iso_now_ms():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def ensure_message_contract(msg: dict):
    op = (msg.get("op") or msg.get("tipo") or "").upper()
    if op not in ALLOWED_OPS:
        raise ValueError(f"op/tipo inválida: {msg.get('op') or msg.get('tipo')}. Debe ser una de {ALLOWED_OPS}")
    msg["tipo"] = op

    if op == "PRESTAMO":
        if "idOperacion" not in msg:
            msg["idOperacion"] = f"OP-{uuid.uuid4()}"
        for k in ("idUsuario", "idLibro"):
            if k not in msg:
                raise ValueError(f"falta campo obligatorio: {k}")
        if "ts" not in msg:
            msg["ts"] = iso_now_ms()
        if "idempotencyKey" not in msg:
            base = f"{op}:{msg['idOperacion']}:{msg['idLibro']}"
            msg["idempotencyKey"] = hashlib.sha256(base.encode()).hexdigest()[:16]
        return msg, op

    # Devoluciones / Renovaciones
    msg["op"] = op
    if "idSolicitud" not in msg:
        msg["idSolicitud"] = f"S-{uuid.uuid4()}"
    for k in ("idUsuario", "idLibro", "sede"):
        if k not in msg:
            raise ValueError(f"falta campo obligatorio: {k}")
    if "timestamp" not in msg and "ts" not in msg:
        msg["timestamp"] = iso_now()
    if "timestamp" not in msg and "ts" in msg:
        msg["timestamp"] = msg["ts"]
    if "idempotencyKey" not in msg:
        base = f"{msg['op']}:{msg['idSolicitud']}:{msg['idLibro']}"
        msg["idempotencyKey"] = hashlib.sha256(base.encode()).hexdigest()[:16]
    return msg, op


def main():
    parser = argparse.ArgumentParser(description="Procesos Solicitantes (PS) - ZeroMQ REQ")
    parser.add_argument("--file", required=True, help="Ruta al archivo (JSON por línea)")
    parser.add_argument("--endpoint", default="tcp://127.0.0.1:5555", help="Endpoint del GC REP (p.e., tcp://gc:5555)")
    parser.add_argument("--interval", type=float, default=0.2, help="Intervalo entre envíos (s)")
    parser.add_argument("--timeout_ms", type=int, default=5000, help="Timeout de respuesta (ms)")
    args = parser.parse_args()

    print(f"[PS] Enviando solicitudes a {args.endpoint}")

    ctx = zmq.Context.instance()

    total, ok, fail = 0, 0, 0
    with open(args.file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                raw = json.loads(line)
                msg, op = ensure_message_contract(raw)
            except Exception as e:
                fail += 1
                print(f"[PS][ERROR] Línea {total} inválida: {e}")
                continue

            sock = ctx.socket(zmq.REQ)
            sock.connect(args.endpoint)
            sock.setsockopt(zmq.RCVTIMEO, args.timeout_ms)
            sock.setsockopt(zmq.LINGER, 0)

            try:
                sock.send_json(msg)
                reply = sock.recv_json()
                ok += 1
                id_log = msg.get("idSolicitud") or msg.get("idOperacion") or "?"
                print(f"[PS][OK] {op} id={id_log} ↦ {reply}")
            except zmq.Again:
                fail += 1
                id_log = msg.get("idSolicitud") or msg.get("idOperacion") or "?"
                print(f"[PS][WARN] Timeout para id={id_log}")
            except Exception as e:
                fail += 1
                id_log = msg.get("idSolicitud") or msg.get("idOperacion") or "?"
                print(f"[PS][ERROR] id={id_log} fallo: {e}")
            finally:
                sock.close(0)

            time.sleep(max(0.0, args.interval))

    print(f"[PS] Terminado. total={total} ok={ok} fail={fail}")
    ctx.term()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[PS] Interrumpido")
        sys.exit(130)
