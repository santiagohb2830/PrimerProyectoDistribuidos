import argparse
from pathlib import Path
from init_db import seed_db


def main():
    ap = argparse.ArgumentParser(description="Inicializa dos BDs (primaria/secundaria) idénticas.")
    ap.add_argument("--primary", default=str(Path(__file__).with_name("biblioteca_prim.db")), help="Ruta BD primaria")
    ap.add_argument("--secondary", default=str(Path(__file__).with_name("biblioteca_sec.db")), help="Ruta BD secundaria")
    ap.add_argument("--libros", type=int, default=1000)
    ap.add_argument("--prest_s1", type=int, default=50)
    ap.add_argument("--prest_s2", type=int, default=150)
    args = ap.parse_args()

    seed_db(args.primary, args.libros, args.prest_s1, args.prest_s2)
    seed_db(args.secondary, args.libros, args.prest_s1, args.prest_s2)
    print(f"[SEED-REPLICAS] Listo: {args.primary} y {args.secondary}")


if __name__ == "__main__":
    main()
