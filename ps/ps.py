import argparse, json, sys, time, uuid, hashlib, csv, statistics
from pathlib import Path
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
    parser.add_argument("--metrics_csv", default="ps_metrics.csv", help="Ruta CSV para almacenar métricas de latencia")
    parser.add_argument("--summary_json", default=None, help="Ruta opcional para guardar resumen JSON (promedios)")
    parser.add_argument("--mode", default="A", help="Etiqueta de modo/experimento (A/B)")
    parser.add_argument("--tag", default=None, help="Etiqueta adicional para identificar la corrida")
    parser.add_argument("--duration_s", type=float, default=None, help="Si se indica, repite el archivo hasta cumplir esta duración (segundos)")
    args = parser.parse_args()

    print(f"[PS] Enviando solicitudes a {args.endpoint}")

    ctx = zmq.Context.instance()

    total, ok, fail = 0, 0, 0
    records = []
    run_start = time.perf_counter()
    def send_all_lines():
        nonlocal total, ok, fail
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

                t0 = time.perf_counter()
                send_ts = iso_now_ms()
                id_log = msg.get("idSolicitud") or msg.get("idOperacion") or "?"
                try:
                    sock.send_json(msg)
                    reply = sock.recv_json()
                    ok += 1
                    recv_ts = iso_now_ms()
                    lat_ms = int((time.perf_counter() - t0) * 1000)
                    print(f"[PS][OK] {op} id={id_log} {lat_ms}ms ↦ {reply}")
                    records.append({
                        "mode": args.mode,
                        "tag": args.tag or "",
                        "op": op,
                        "id": id_log,
                        "status": "OK",
                        "latency_ms": lat_ms,
                        "msg": reply.get("msg") if isinstance(reply, dict) else "",
                        "t_send": send_ts,
                        "t_recv": recv_ts,
                        "endpoint": args.endpoint,
                    })
                except zmq.Again:
                    fail += 1
                    print(f"[PS][WARN] Timeout para id={id_log}")
                    records.append({
                        "mode": args.mode,
                        "tag": args.tag or "",
                        "op": op,
                        "id": id_log,
                        "status": "TIMEOUT",
                        "latency_ms": None,
                        "msg": "TIMEOUT",
                        "t_send": send_ts,
                        "t_recv": iso_now_ms(),
                        "endpoint": args.endpoint,
                    })
                except Exception as e:
                    fail += 1
                    print(f"[PS][ERROR] id={id_log} fallo: {e}")
                    records.append({
                        "mode": args.mode,
                        "tag": args.tag or "",
                        "op": op,
                        "id": id_log,
                        "status": "ERROR",
                        "latency_ms": None,
                        "msg": str(e),
                        "t_send": send_ts,
                        "t_recv": iso_now_ms(),
                        "endpoint": args.endpoint,
                    })
                finally:
                    sock.close(0)

                time.sleep(max(0.0, args.interval))

    if args.duration_s:
        end_time = time.perf_counter() + args.duration_s
        while time.perf_counter() < end_time:
            send_all_lines()
    else:
        send_all_lines()

    run_end = time.perf_counter()
    duration = max(run_end - run_start, 0.0001)
    throughput = ok / duration

    if args.metrics_csv:
        path = Path(args.metrics_csv)
        first = not path.exists()
        with path.open("a", newline="", encoding="utf-8") as csvfile:
            fieldnames = ["mode", "tag", "op", "id", "status", "latency_ms", "msg", "t_send", "t_recv", "endpoint"]
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            if first:
                writer.writeheader()
            for r in records:
                writer.writerow(r)

    latencies_ok = [r["latency_ms"] for r in records if r["latency_ms"] is not None and r["status"] == "OK"]
    summary = {
        "mode": args.mode,
        "tag": args.tag,
        "file": args.file,
        "endpoint": args.endpoint,
        "total": total,
        "ok": ok,
        "fail": fail,
        "duration_s": round(duration, 3),
        "throughput_ops_s": round(throughput, 3),
        "avg_latency_ms": round(statistics.mean(latencies_ok), 2) if latencies_ok else None,
        "stdev_latency_ms": round(statistics.pstdev(latencies_ok), 2) if len(latencies_ok) > 1 else None,
    }
    print(f"[PS] Terminado. total={total} ok={ok} fail={fail} thr={summary['throughput_ops_s']} op/s avg_lat={summary['avg_latency_ms']}")

    if args.summary_json:
        Path(args.summary_json).write_text(json.dumps(summary, indent=2), encoding="utf-8")

    ctx.term()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n[PS] Interrumpido")
        sys.exit(130)
