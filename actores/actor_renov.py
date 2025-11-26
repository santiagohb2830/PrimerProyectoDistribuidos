import zmq, json, argparse, time
from datetime import datetime, timedelta, timezone
from common.config import GC_PUB_CONNECT, GA_PRIMARY_REP_CONNECT, GA_SECONDARY_REP_CONNECT, TOPIC_RENOV
from common.ga_client import send_with_failover

def iso_plus_7days(base_iso: str | None) -> str:
    try:
        if base_iso:
            # "2025-10-07T21:00:00Z"
            dt = datetime.strptime(base_iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        else:
            dt = datetime.now(timezone.utc)
    except Exception:
        dt = datetime.now(timezone.utc)
    return (dt + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

def main():
    ap = argparse.ArgumentParser(description="Actor RENOVACION")
    ap.add_argument("--sub", default=GC_PUB_CONNECT, help="Endpoint SUB (GC PUB connect)")
    ap.add_argument("--ga_primary",  default=GA_PRIMARY_REP_CONNECT,  help="Endpoint REQ al GA primario")
    ap.add_argument("--ga_secondary",  default=GA_SECONDARY_REP_CONNECT,  help="Endpoint REQ al GA secundario (failover)")
    ap.add_argument("--timeout_ms", type=int, default=4000, help="Timeout por GA (ms)")
    args = ap.parse_args()

    ctx = zmq.Context.instance()
    sub = ctx.socket(zmq.SUB); sub.connect(args.sub)
    sub.setsockopt_string(zmq.SUBSCRIBE, TOPIC_RENOV)

    print(f"[ACTOR-REN] SUB a {args.sub} (tópico {TOPIC_RENOV})")
    print(f"[ACTOR-REN] REQ GA primario {args.ga_primary} / secundario {args.ga_secondary}")

    try:
        while True:
            topic, payload = sub.recv_multipart()
            data = json.loads(payload.decode("utf-8"))
            print(f"[ACTOR-REN] {topic.decode()}: {data}")

            nueva_entrega = iso_plus_7days(data.get("timestamp"))

            ga_msg = {
                "op": "RENOVACION",
                "idempotencyKey": data.get("idempotencyKey"),
                "idSolicitud":    data.get("idSolicitud"),
                "idUsuario":      data.get("idUsuario"),
                "idLibro":        data.get("idLibro"),
                "sede":           data.get("sede"),
                "timestamp":      data.get("timestamp"),
                "nuevaFechaEntrega": nueva_entrega
            }

            resp, ep, lat_ms, err = send_with_failover(ctx, ga_msg, args.ga_primary, args.ga_secondary, timeout_ms=args.timeout_ms)
            if resp.get("ok"):
                print(f"[ACTOR-REN] GA({ep}) {lat_ms}ms → {resp}")
            else:
                print(f"[ACTOR-REN] ⚠ Error GA {err} resp={resp}")
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("\n[ACTOR-REN] Saliendo...")
    finally:
        sub.close(0); ctx.term()

if __name__ == "__main__":
    main()
