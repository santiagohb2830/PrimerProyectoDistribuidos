import argparse, json
from datetime import datetime, timezone
import zmq
from common.config import (
    ACTOR_PRESTAMO_REP_ADDR,
    GA_PRIMARY_REP_CONNECT,
    GA_SECONDARY_REP_CONNECT,
)
from common.ga_client import send_with_failover


def iso_now_ms():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def main():
    ap = argparse.ArgumentParser(description="Actor PRESTAMO (sincrono REP<->REQ)")
    ap.add_argument("--rep", default=ACTOR_PRESTAMO_REP_ADDR, help="Endpoint REP bind (GC se conecta)")
    ap.add_argument("--ga_primary", default=GA_PRIMARY_REP_CONNECT, help="Endpoint REQ al GA primario")
    ap.add_argument("--ga_secondary", default=GA_SECONDARY_REP_CONNECT, help="Endpoint REQ al GA secundario (failover)")
    ap.add_argument("--timeout_ms", type=int, default=4000, help="Timeout esperando GA")
    args = ap.parse_args()

    ctx = zmq.Context.instance()
    rep = ctx.socket(zmq.REP)
    rep.bind(args.rep)

    print(f"[ACTOR-PRESTAMO] REP escuchando en {args.rep}")
    print(f"[ACTOR-PRESTAMO] REQ GA primario {args.ga_primary} / secundario {args.ga_secondary}")

    try:
        while True:
            raw = rep.recv()
            ts_in = iso_now_ms()
            try:
                data = json.loads(raw.decode("utf-8"))
            except Exception as e:
                rep.send_string(json.dumps({"ok": False, "msg": f"JSON invalido actor: {e}"}))
                print(f"[ACTOR-PRESTAMO] JSON invalido desde GC: {e}")
                continue

            print(f"[ACTOR-PRESTAMO] Solicitud: {data}")

            ga_msg = dict(data)
            ga_msg.setdefault("tipo", data.get("tipo") or data.get("op"))
            ga_msg["tsActorIn"] = ts_in

            ga_resp, ep_used, lat_ms, err = send_with_failover(ctx, ga_msg, args.ga_primary, args.ga_secondary, timeout_ms=args.timeout_ms)
            if ga_resp.get("ok"):
                print(f"[ACTOR-PRESTAMO] GA({ep_used}) {lat_ms}ms -> {ga_resp}")
            else:
                if not ga_resp.get("idOperacion"):
                    ga_resp["idOperacion"] = data.get("idOperacion")
                if not ga_resp.get("msg"):
                    ga_resp["msg"] = err or "ERROR_GA"
                print(f"[ACTOR-PRESTAMO] Error GA {err} resp={ga_resp}")

            ts_out = iso_now_ms()
            resp_gc = dict(ga_resp)
            resp_gc.setdefault("idOperacion", data.get("idOperacion"))
            resp_gc["tsActorOut"] = ts_out

            rep.send_string(json.dumps(resp_gc))
    except KeyboardInterrupt:
        print("\n[ACTOR-PRESTAMO] Saliendo...")
    finally:
        rep.close(0)
        ctx.term()


if __name__ == "__main__":
    main()
