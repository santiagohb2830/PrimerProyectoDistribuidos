import json
import zmq
from common.config import GC_REP_ADDR, GC_PUB_ADDR

def main():
    ctx = zmq.Context.instance()
    rep = ctx.socket(zmq.REP); rep.bind(GC_REP_ADDR)
    pub = ctx.socket(zmq.PUB); pub.bind(GC_PUB_ADDR)

    print(f"[GC] REP en {GC_REP_ADDR}")
    print(f"[GC] PUB en {GC_PUB_ADDR}")
    print("[GC] Esperando mensajes... (Ctrl+C para salir)")

    try:
        while True:
            raw = rep.recv()                       # bytes
            msg = json.loads(raw.decode("utf-8"))  # dict
            op  = (msg.get("op") or "").upper()

            if op not in ("DEVOLUCION","RENOVACION"):
                rep.send_string(json.dumps({"ok": False, "msg": "op no soportada (Ent1)"}))
                print(f"[GC] ⚠ op desconocida: {op} payload={msg}")
                continue

            print(f"[GC] Recibí {op}: {msg}")

            # Responde inmediato al PS
            rep.send_string(json.dumps({"ok": True, "msg": "Recibido y publicado"}))

            # Publica al tópico (frame1=tópico, frame2=payload)
            pub.send_multipart([op.encode("utf-8"), json.dumps(msg).encode("utf-8")])
            print(f"[GC] Publicado tópico {op}")

    except KeyboardInterrupt:
        print("\n[GC] Saliendo...")
    finally:
        rep.close(0); pub.close(0); ctx.term()

if __name__ == "__main__":
    main()
