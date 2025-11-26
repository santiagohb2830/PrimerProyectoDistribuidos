import json
import time
import zmq


def send_with_failover(ctx: zmq.Context, payload: dict, primary: str, secondary: str | None = None, timeout_ms: int = 4000):
    """
    Envía payload a GA intentando primero el primario y luego el secundario (si se suministra).
    Devuelve (resp_dict, endpoint_usado, lat_ms, error_str).
    """
    endpoints = [primary]
    if secondary:
        endpoints.append(secondary)

    last_error = None
    for ep in endpoints:
        sock = ctx.socket(zmq.REQ)
        sock.connect(ep)
        sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
        sock.setsockopt(zmq.LINGER, 0)

        t0 = time.perf_counter()
        try:
            sock.send_string(json.dumps(payload))
            raw = sock.recv_string()
            lat_ms = int((time.perf_counter() - t0) * 1000)
            return json.loads(raw), ep, lat_ms, None
        except zmq.Again:
            last_error = f"TIMEOUT({ep})"
        except Exception as e:
            last_error = f"ERROR({ep}):{e}"
        finally:
            sock.close(0)

    return {"ok": False, "msg": last_error or "SIN_ENDPOINTS"}, None, None, last_error or "FALLO_DESCONOCIDO"
