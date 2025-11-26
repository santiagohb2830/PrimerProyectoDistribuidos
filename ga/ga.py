import argparse, json, sqlite3, os, uuid, threading
from typing import Tuple
from datetime import datetime, timedelta, timezone
import zmq
from common.config import (
    GA_REP_ADDR,
    GA_REPLICA_PULL_BIND,
    GA_REPLICA_PUSH_CONNECT,
    DB_PATH,
)


def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(db_path: str):
    con = sqlite3.connect(db_path, timeout=10, isolation_level=None)  # autocommit OFF -> usaremos BEGIN
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    return con


def apply_idempotency(con: sqlite3.Connection, key: str, op: str, idSolicitud: str, ts: str) -> bool:
    cur = con.execute("SELECT 1 FROM applied_ops WHERE idempotencyKey = ?", (key,))
    if cur.fetchone():
        return True
    con.execute(
        "INSERT INTO applied_ops(idempotencyKey, op, idSolicitud, timestamp) VALUES (?,?,?,?)",
        (key, op, idSolicitud, ts)
    )
    return False


def op_devolucion(con: sqlite3.Connection, data: dict) -> dict:
    idLibro = data["idLibro"]; idUsuario = data["idUsuario"]; sede = data["sede"]
    ahora = data.get("timestamp") or iso_now()

    cur = con.execute("""
        SELECT idPrestamo FROM prestamos
         WHERE idLibro=? AND idUsuario=? AND sede=? AND estado='ACTIVO'
         ORDER BY idPrestamo DESC LIMIT 1
    """, (idLibro, idUsuario, sede))
    row = cur.fetchone()
    if not row:
        return {"ok": True, "msg": "No habia prestamo activo (idempotente)."}

    idp = row[0]

    con.execute("UPDATE prestamos SET estado='DEVUELTO', fecha_entrega=? WHERE idPrestamo=?",
                (ahora, idp))
    con.execute("""
        UPDATE libros
           SET ejemplares_disponibles = MIN(ejemplares_totales, ejemplares_disponibles + 1)
         WHERE idLibro=?
    """, (idLibro,))
    return {"ok": True, "msg": f"Devolucion aplicada sobre prestamo {idp}"}


def op_renovacion(con: sqlite3.Connection, data: dict) -> dict:
    idLibro = data["idLibro"]; idUsuario = data["idUsuario"]; sede = data["sede"]
    nueva = data.get("nuevaFechaEntrega")
    if not nueva:
        try:
            base_ts = data.get("timestamp")
            dt = datetime.strptime(base_ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) if base_ts else datetime.now(timezone.utc)
        except Exception:
            dt = datetime.now(timezone.utc)
        nueva = (dt + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")

    cur = con.execute("""
        SELECT idPrestamo FROM prestamos
         WHERE idLibro=? AND idUsuario=? AND sede=? AND estado='ACTIVO'
         ORDER BY idPrestamo DESC LIMIT 1
    """, (idLibro, idUsuario, sede))
    row = cur.fetchone()
    if not row:
        return {"ok": False, "msg": "No hay prestamo activo para renovar."}

    idp = row[0]
    con.execute("UPDATE prestamos SET fecha_entrega=? WHERE idPrestamo=?", (nueva, idp))
    return {"ok": True, "msg": f"Renovacion aplicada sobre prestamo {idp} nueva_entrega={nueva}"}


def op_prestamo(con: sqlite3.Connection, data: dict) -> dict:
    idLibro = data["idLibro"]; idUsuario = data["idUsuario"]
    ts = data.get("tsActorOut") or data.get("tsGC") or data.get("ts") or iso_now()

    cur = con.execute(
        "SELECT sede, ejemplares_disponibles FROM libros WHERE idLibro = ?",
        (idLibro,),
    )
    row = cur.fetchone()
    if not row:
        return {"ok": False, "msg": "LIBRO_NO_EXISTE"}

    sede_db, disponibles = row
    if disponibles <= 0:
        return {"ok": False, "msg": "NO_HAY_EJEMPLARES"}

    fecha_prestamo = ts
    fecha_entrega_dt = datetime.now(timezone.utc) + timedelta(days=14)
    fecha_entrega_iso = fecha_entrega_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    fecha_entrega_resp = fecha_entrega_dt.strftime("%Y-%m-%d")

    cur_upd = con.execute(
        "UPDATE libros SET ejemplares_disponibles = ejemplares_disponibles - 1 WHERE idLibro=? AND ejemplares_disponibles > 0",
        (idLibro,),
    )
    if cur_upd.rowcount == 0:
        return {"ok": False, "msg": "NO_HAY_EJEMPLARES"}

    cur_ins = con.execute(
        """
        INSERT INTO prestamos(idSolicitud, idUsuario, idLibro, sede, fecha_prestamo, fecha_entrega, estado)
        VALUES (?,?,?,?,?,?,?)
        """,
        (
            data.get("idOperacion") or data.get("idSolicitud") or f"S-{uuid.uuid4()}",
            idUsuario,
            idLibro,
            sede_db,
            fecha_prestamo,
            fecha_entrega_iso,
            "ACTIVO",
        ),
    )
    return {"ok": True, "msg": "PRESTAMO_REALIZADO", "fechaEntrega": fecha_entrega_resp, "ejemplarId": cur_ins.lastrowid}


def apply_operation(con: sqlite3.Connection, data: dict) -> Tuple[dict, str, str, str]:
    """
    Ejecuta la operación dentro de una transacción y retorna (resultado, op, idsol, idem_key).
    Lanza ValueError si la operación no es soportada.
    """
    op = (data.get("op") or data.get("tipo") or "").upper()
    idem = data.get("idempotencyKey")
    idsol = data.get("idSolicitud") or data.get("idOperacion") or "?"
    ts = data.get("timestamp") or data.get("ts") or iso_now()

    con.execute("BEGIN")
    if not idem:
        idem = f"NOIDEMP-{op}-{idsol}"

    if op == "PRESTAMO":
        cur_idem = con.execute("SELECT 1 FROM applied_ops WHERE idempotencyKey = ?", (idem,))
        if cur_idem.fetchone():
            con.execute("COMMIT")
            return {"ok": False, "msg": "YA_APLICADA"}, op, idsol, idem
        res = op_prestamo(con, data)
        if res.get("ok"):
            apply_idempotency(con, idem, op, idsol, ts)
    elif op == "DEVOLUCION":
        ya = apply_idempotency(con, idem, op, idsol, ts)
        if ya:
            con.execute("COMMIT")
            return {"ok": True, "msg": "Ya aplicado (idempotente)."}, op, idsol, idem
        res = op_devolucion(con, data)
    elif op == "RENOVACION":
        ya = apply_idempotency(con, idem, op, idsol, ts)
        if ya:
            con.execute("COMMIT")
            return {"ok": True, "msg": "Ya aplicado (idempotente)."}, op, idsol, idem
        res = op_renovacion(con, data)
    else:
        con.execute("ROLLBACK")
        raise ValueError(f"op no soportada: {op}")

    con.execute("COMMIT")
    return res, op, idsol, idem


def start_replica_listener(bind_addr: str, db_path: str):
    def _loop():
        ctx = zmq.Context.instance()
        pull = ctx.socket(zmq.PULL)
        pull.bind(bind_addr)
        con_replica = connect(db_path)
        print(f"[GA-SEC] Replicación escuchando en {bind_addr}")
        try:
            while True:
                raw = pull.recv()
                try:
                    data = json.loads(raw.decode("utf-8"))
                except Exception as e:
                    print(f"[GA-SEC] Replicación descartada por JSON inválido: {e}")
                    continue
                try:
                    res, op, idsol, idem = apply_operation(con_replica, data)
                    print(f"[GA-SEC] Replica {op} id={idsol} -> {res}")
                except Exception as e:
                    try:
                        con_replica.execute("ROLLBACK")
                    except Exception:
                        pass
                    print(f"[GA-SEC] Error aplicando replica: {e}")
        except KeyboardInterrupt:
            print("\n[GA-SEC] Replicación detenida")
        finally:
            pull.close(0)
            con_replica.close()

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    return t


def main():
    ap = argparse.ArgumentParser(description="Gestor de Almacenamiento (GA)")
    ap.add_argument("--rep", default=GA_REP_ADDR, help="Endpoint REP bind (p.e., tcp://*:5570)")
    ap.add_argument("--role", choices=["primary", "secondary"], default="primary", help="Rol del GA para replicación/failover")
    ap.add_argument("--replica_push", default=GA_REPLICA_PUSH_CONNECT, help="(Primario) endpoint PUSH hacia el secundario")
    ap.add_argument("--replica_pull", default=GA_REPLICA_PULL_BIND, help="(Secundario) endpoint PULL para recibir del primario")
    ap.add_argument("--db", default=DB_PATH, help="Ruta a la BD SQLite (biblioteca.db)")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.db), exist_ok=True)
    con = connect(args.db)

    ctx = zmq.Context.instance()
    rep = ctx.socket(zmq.REP); rep.bind(args.rep)
    replica_push = None
    if args.role == "primary" and args.replica_push:
        replica_push = ctx.socket(zmq.PUSH)
        replica_push.connect(args.replica_push)
        replica_push.setsockopt(zmq.LINGER, 0)
        print(f"[GA] Replicando (PUSH) a {args.replica_push}")
    if args.role == "secondary":
        start_replica_listener(args.replica_pull, args.db)
        print(f"[GA] Modo secundario escuchando replicación en {args.replica_pull}")

    print(f"[GA] REP en {args.rep}")
    print(f"[GA] Usando BD: {args.db}")
    print("[GA] Esperando operaciones... (Ctrl+C para salir)")

    try:
        while True:
            raw = rep.recv()
            try:
                data = json.loads(raw.decode("utf-8"))
            except Exception as e:
                rep.send_string(json.dumps({"ok": False, "msg": f"JSON invalido: {e}"}))
                continue

            op = (data.get("op") or data.get("tipo") or "?").upper()
            idsol = data.get("idSolicitud") or data.get("idOperacion") or "?"
            try:
                res, op, idsol, idem = apply_operation(con, data)
                if args.role == "primary" and replica_push and res.get("ok"):
                    try:
                        replica_push.send_string(json.dumps(data), flags=zmq.NOBLOCK)
                    except Exception as e:
                        print(f"[GA] No se pudo replicar {op} id={idsol}: {e}")
                rep.send_string(json.dumps(res))
                print(f"[GA] {op} id={idsol} -> {res}")
            except ValueError as e:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                rep.send_string(json.dumps({"ok": False, "msg": str(e)}))
                print(f"[GA] op desconocida: {e} data={data}")
            except Exception as e:
                try:
                    con.execute("ROLLBACK")
                except Exception:
                    pass
                rep.send_string(json.dumps({"ok": False, "msg": f"Error aplicando op: {e}"}))
                print(f"[GA] Error aplicando {op} id={idsol}: {e}")

    except KeyboardInterrupt:
        print("\n[GA] Saliendo...")
    finally:
        rep.close(0);
        if replica_push:
            replica_push.close(0)
        ctx.term(); con.close()


if __name__ == "__main__":
    main()
