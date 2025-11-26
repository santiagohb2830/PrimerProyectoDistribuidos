import json, argparse, time, csv, os
from datetime import datetime, timezone
import zmq
from common.config import (
    GC_REP_ADDR,
    GC_PUB_ADDR,
    TOPIC_DEVOL,
    TOPIC_RENOV,
    TOPIC_PRESTAMO,
    ACTOR_PRESTAMO_REP_CONNECT,
    GA_PRIMARY_REP_CONNECT,
    GA_SECONDARY_REP_CONNECT,
)
from common.ga_client import send_with_failover


def iso_now_ms():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

def append_metric(path: str, row: dict):
    if not path:
        return
    try:
        first = not os.path.exists(path)
    except Exception:
        first = False
    try:
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["op","status","latency_ms","id","ts","extra"])
            if first:
                writer.writeheader()
            writer.writerow(row)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser(description="Gestor de Carga (GC)")
    ap.add_argument("--rep", default=GC_REP_ADDR, help="Endpoint REP bind (p.e., tcp://*:5555)")
    ap.add_argument("--pub", default=GC_PUB_ADDR, help="Endpoint PUB bind (p.e., tcp://*:5560)")
    ap.add_argument("--actor_prestamo", default=ACTOR_PRESTAMO_REP_CONNECT, help="Endpoint REQ al actor de PRESTAMO")
    ap.add_argument("--timeout_actor_ms", type=int, default=4000, help="Timeout esperando respuesta de actor")
    ap.add_argument("--sync_devren", action="store_true", help="Modo B: procesar DEVOL/RENOV de forma síncrona (sin publicar)")
    ap.add_argument("--ga_primary", default=GA_PRIMARY_REP_CONNECT, help="(Modo B) GA primario")
    ap.add_argument("--ga_secondary", default=GA_SECONDARY_REP_CONNECT, help="(Modo B) GA secundario")
    ap.add_argument("--metrics_csv", default=None, help="Ruta opcional para métricas del GC")
    args = ap.parse_args()

    ctx = zmq.Context.instance()
    rep = ctx.socket(zmq.REP); rep.bind(args.rep)
    pub = ctx.socket(zmq.PUB); pub.bind(args.pub)
    actor_req = ctx.socket(zmq.REQ); actor_req.connect(args.actor_prestamo)
    actor_req.setsockopt(zmq.RCVTIMEO, args.timeout_actor_ms)

    print(f"[GC] REP en {args.rep}")
    print(f"[GC] PUB en {args.pub}")
    print(f"[GC] REQ a actor PRESTAMO {args.actor_prestamo}")
    print("[GC] Esperando mensajes... (Ctrl+C para salir)")

    try:
        while True:
            raw = rep.recv()                       # bytes
            msg = json.loads(raw.decode("utf-8"))  # dict
            op  = (msg.get("op") or msg.get("tipo") or "").upper()

            if op == TOPIC_PRESTAMO:
                t0 = time.perf_counter()
                msg["tsGC"] = iso_now_ms()
                print(f"[GC] Recibió PRESTAMO: {msg}")

                actor_req.send_json(msg)
                try:
                    resp_actor = actor_req.recv_json()
                except zmq.Again:
                    rep.send_string(json.dumps({"idOperacion": msg.get("idOperacion"), "ok": False, "msg": "TIMEOUT_ACTOR"}))
                    print("[GC] Timeout actor PRESTAMO")
                    continue
                except Exception as e:
                    rep.send_string(json.dumps({"idOperacion": msg.get("idOperacion"), "ok": False, "msg": f"ERROR_ACTOR:{e}"}))
                    print(f"[GC] Error recibiendo actor PRESTAMO: {e}")
                    continue

                lat_ms = int((time.perf_counter() - t0) * 1000)
                final_resp = dict(resp_actor)
                final_resp["latenciaTotalMs"] = lat_ms
                rep.send_string(json.dumps(final_resp))
                print(f"[GC] Respuesta a PS: {final_resp}")
                append_metric(args.metrics_csv, {"op": op, "status": final_resp.get("ok"), "latency_ms": lat_ms, "id": msg.get("idOperacion"), "ts": iso_now_ms(), "extra": final_resp.get("msg")})
                continue

            if op not in (TOPIC_DEVOL, TOPIC_RENOV):
                rep.send_string(json.dumps({"ok": False, "msg": "op no soportada (Ent1)"}))
                print(f"[GC] op desconocida: {op} payload={msg}")
                continue

            if args.sync_devren:
                # Modo síncrono para DEVOL/RENOV (opción B)
                t0 = time.perf_counter()
                msg["tsGC"] = iso_now_ms()
                resp_ga, ep_used, lat_ms, err = send_with_failover(ctx, msg, args.ga_primary, args.ga_secondary, timeout_ms=args.timeout_actor_ms)
                total_ms = int((time.perf_counter() - t0) * 1000)
                resp_ga["latenciaTotalMs"] = total_ms
                rep.send_string(json.dumps(resp_ga))
                print(f"[GC] Sync {op} via GA({ep_used}) {total_ms}ms -> {resp_ga}")
                append_metric(args.metrics_csv, {"op": op, "status": resp_ga.get("ok"), "latency_ms": total_ms, "id": msg.get("idSolicitud"), "ts": iso_now_ms(), "extra": resp_ga.get("msg") or err})
                continue

            print(f"[GC] Recibí {op}: {msg}")

            # Respuesta inmediata a PS
            rep.send_string(json.dumps({"ok": True, "msg": "Recibido y publicado"}))

            # Publicación al tópico
            pub.send_multipart([op.encode("utf-8"), json.dumps(msg).encode("utf-8")])
            print(f"[GC] Publicado tópico {op}")
            append_metric(args.metrics_csv, {"op": op, "status": True, "latency_ms": 0, "id": msg.get("idSolicitud"), "ts": iso_now_ms(), "extra": "PUB"})

    except KeyboardInterrupt:
        print("\n[GC] Saliendo...")
    finally:
        rep.close(0); pub.close(0); actor_req.close(0); ctx.term()

if __name__ == "__main__":
    main()
