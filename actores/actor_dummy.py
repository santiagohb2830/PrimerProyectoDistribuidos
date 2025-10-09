import zmq, json, time
from common.config import GC_PUB_CONNECT

def main():
    ctx = zmq.Context.instance()
    sub = ctx.socket(zmq.SUB); sub.connect(GC_PUB_CONNECT)
    sub.setsockopt_string(zmq.SUBSCRIBE, "DEVOLUCION")
    sub.setsockopt_string(zmq.SUBSCRIBE, "RENOVACION")
    print(f"[ACTOR] SUB a {GC_PUB_CONNECT} (DEVOLUCION/RENOVACION)")
    try:
        while True:
            topic, payload = sub.recv_multipart()
            data = json.loads(payload.decode())
            print(f"[ACTOR] {topic.decode()}: {data}")
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\n[ACTOR] Saliendo...")
    finally:
        sub.close(0); ctx.term()

if __name__ == "__main__":
    main()
