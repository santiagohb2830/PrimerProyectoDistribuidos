import argparse, subprocess, sys, time
from pathlib import Path


def main():
    ap = argparse.ArgumentParser(description="Lanzador de carga: múltiples PS en paralelo")
    ap.add_argument("--files", nargs="+", required=True, help="Archivos JSONL para cada PS")
    ap.add_argument("--endpoint", default="tcp://127.0.0.1:5555", help="Endpoint GC REP")
    ap.add_argument("--interval", type=float, default=0.1, help="Intervalo entre envíos de cada PS")
    ap.add_argument("--mode", default="A", help="Etiqueta modo/experimento (A/B)")
    ap.add_argument("--metrics_csv", default="ps_metrics.csv", help="CSV global donde todos los PS escriben métricas")
    ap.add_argument("--summary_dir", default=None, help="Directorio opcional para almacenar resúmenes JSON individuales")
    args = ap.parse_args()

    procs = []
    summary_dir = Path(args.summary_dir) if args.summary_dir else None
    if summary_dir:
        summary_dir.mkdir(parents=True, exist_ok=True)

    for idx, file_path in enumerate(args.files, start=1):
        tag = f"ps{idx}"
        summary_path = None
        if summary_dir:
            summary_path = summary_dir / f"summary_{tag}.json"
        cmd = [
            sys.executable, "-m", "ps.ps",
            "--file", file_path,
            "--endpoint", args.endpoint,
            "--interval", str(args.interval),
            "--mode", args.mode,
            "--tag", tag,
            "--metrics_csv", args.metrics_csv,
        ]
        if summary_path:
            cmd.extend(["--summary_json", str(summary_path)])
        print(f"[RUN-LOAD] Lanzando {cmd}")
        procs.append(subprocess.Popen(cmd))

    try:
        for p in procs:
            p.wait()
    except KeyboardInterrupt:
        print("\n[RUN-LOAD] Interrumpido, terminando procesos...")
        for p in procs:
            p.terminate()
    finally:
        for p in procs:
            if p.poll() is None:
                p.wait(timeout=2)


if __name__ == "__main__":
    main()
