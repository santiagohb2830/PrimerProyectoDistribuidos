import argparse, json
from datetime import datetime, timezone
import zmq
from common.config import (
    ACTOR_PRESTAMO_REP_ADDR,
    GA_REP_CONNECT,
)


def iso_now_ms():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def main():
    ap = argparse.ArgumentParser(description="Actor PRESTAMO (sincrono REP<->REQ)")
    ap.add_argument("--rep", default=ACTOR_PRESTAMO_REP_ADDR, help="Endpoint REP bind (GC se conecta)")
    ap.add_argument("--ga", default=GA_REP_CONNECT, help="Endpoint REQ a GA")
    ap.add_argument("--timeout_ms", type=int, default=4000, help="Timeout esperando GA")
    args = ap.parse_args()

    ctx = zmq.Context.instance()
    rep = ctx.socket(zmq.REP)
    rep.bind(args.rep)

    req_ga = ctx.socket(zmq.REQ)
    req_ga.connect(args.ga)
    req_ga.setsockopt(zmq.RCVTIMEO, args.timeout_ms)

    print(f"[ACTOR-PRESTAMO] REP escuchando en {args.rep}")
    print(f"[ACTOR-PRESTAMO] REQ a GA {args.ga}")

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

            try:
                req_ga.send_string(json.dumps(ga_msg))
                raw_resp = req_ga.recv_string()
                ga_resp = json.loads(raw_resp)
                print(f"[ACTOR-PRESTAMO] GA -> {ga_resp}")
            except zmq.Again:
                ga_resp = {"idOperacion": data.get("idOperacion"), "ok": False, "msg": "TIMEOUT_GA"}
                print("[ACTOR-PRESTAMO] Timeout esperando GA")
            except Exception as e:
                ga_resp = {"idOperacion": data.get("idOperacion"), "ok": False, "msg": f"ERROR_GA:{e}"}
                print(f"[ACTOR-PRESTAMO] Error hablando con GA: {e}")

            ts_out = iso_now_ms()
            resp_gc = dict(ga_resp)
            resp_gc.setdefault("idOperacion", data.get("idOperacion"))
            resp_gc["tsActorOut"] = ts_out

            rep.send_string(json.dumps(resp_gc))
    except KeyboardInterrupt:
        print("\n[ACTOR-PRESTAMO] Saliendo...")
    finally:
        rep.close(0)
        req_ga.close(0)
        ctx.term()


if __name__ == "__main__":
    main()
