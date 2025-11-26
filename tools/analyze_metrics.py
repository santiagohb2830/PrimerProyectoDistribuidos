import argparse, csv, statistics
from datetime import datetime
from pathlib import Path


def parse_iso(ts: str):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description="Analiza métricas CSV generadas por ps.ps")
    ap.add_argument("--file", default="ps_metrics.csv", help="Ruta al CSV de métricas")
    ap.add_argument("--mode", default=None, help="Filtrar por modo (columna mode)")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        print(f"No existe {path}")
        return

    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if args.mode and r.get("mode") != args.mode:
                continue
            try:
                lat = float(r["latency_ms"]) if r.get("latency_ms") not in (None, "", "None") else None
            except Exception:
                lat = None
            r["latency_ms"] = lat
            rows.append(r)

    if not rows:
        print("Sin filas para analizar.")
        return

    # Throughput estimado por timestamps
    ts_min, ts_max = None, None
    for r in rows:
        t0 = parse_iso(r.get("t_send", ""))
        t1 = parse_iso(r.get("t_recv", ""))
        if t0:
            ts_min = t0 if not ts_min else min(ts_min, t0)
        if t1:
            ts_max = t1 if not ts_max else max(ts_max, t1)
    duration = (ts_max - ts_min).total_seconds() if ts_min and ts_max else None

    total = len(rows)
    ok_rows = [r for r in rows if r.get("status") == "OK"]
    lat_ok = [r["latency_ms"] for r in ok_rows if r["latency_ms"] is not None]

    print(f"Archivo: {path}")
    if args.mode:
        print(f"Modo filtrado: {args.mode}")
    print(f"Total filas: {total}, OK: {len(ok_rows)}, Fail/Timeout: {total - len(ok_rows)}")
    if lat_ok:
        avg = statistics.mean(lat_ok)
        stdev = statistics.pstdev(lat_ok) if len(lat_ok) > 1 else 0.0
        print(f"Latencia OK avg={avg:.2f} ms, stdev={stdev:.2f} ms, min={min(lat_ok):.2f}, max={max(lat_ok):.2f}")
    else:
        print("Sin latencias OK.")
    if duration and duration > 0:
        thr = total / duration
        print(f"Ventana temporal ~{duration:.2f}s, throughput ~{thr:.2f} ops/s")

    # Por operación
    by_op = {}
    for r in rows:
        op = r.get("op", "UNK")
        by_op.setdefault(op, []).append(r)
    for op, ops_rows in by_op.items():
        ok_op = [r for r in ops_rows if r.get("status") == "OK"]
        lat_op = [r["latency_ms"] for r in ok_op if r["latency_ms"] is not None]
        print(f"\nOp {op}: total={len(ops_rows)} ok={len(ok_op)} fail={len(ops_rows)-len(ok_op)}")
        if lat_op:
            avg = statistics.mean(lat_op)
            stdev = statistics.pstdev(lat_op) if len(lat_op) > 1 else 0.0
            print(f"  Latencia avg={avg:.2f} ms stdev={stdev:.2f} ms min={min(lat_op):.2f} max={max(lat_op):.2f}")


if __name__ == "__main__":
    main()
