import json, time, zmq
from common.config import GC_REP_CONNECT

def enviar(ctx, op, libro_id, usuario, extras=None):
    req = ctx.socket(zmq.REQ); req.connect(GC_REP_CONNECT)
    msg = {"op": op, "libro_id": libro_id, "usuario": usuario}
    if extras: msg.update(extras)
    req.send_string(json.dumps(msg))
    resp = req.recv_string()
    print(f"[PS] {op} {libro_id} -> {resp}")
    req.close(0)

def main():
    ctx = zmq.Context.instance()
    try:
        enviar(ctx, "DEVOLUCION", "A123", "u001")
        time.sleep(0.1)
        enviar(ctx, "RENOVACION", "B777", "u002", {"dias_extra": 7})
    except KeyboardInterrupt:
        pass
    finally:
        ctx.term()

if __name__ == "__main__":
    main()
