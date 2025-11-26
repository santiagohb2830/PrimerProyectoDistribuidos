import sqlite3, os, random, argparse
from datetime import datetime, timedelta, timezone

DB_NAME = os.path.join(os.path.dirname(__file__), "biblioteca.db")
SCHEMA = os.path.join(os.path.dirname(__file__), "schema.sql")

def iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def iso_days_from_now(days: int):
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

def seed_db(db_path: str, n_libros: int = 1000, prest_s1: int = 50, prest_s2: int = 150):
    if os.path.exists(db_path):
        os.remove(db_path)

    with sqlite3.connect(db_path) as con, open(SCHEMA, "r", encoding="utf-8") as f:
        con.executescript(f.read())

        libros = []
        mitad = n_libros // 2
        for i in range(1, n_libros + 1):
            idLibro = f"L{i:04d}"
            sede = "SEDE1" if i <= mitad else "SEDE2"
            tot = 1
            disp = 1
            titulo = f"Libro {i:04d}"
            libros.append((idLibro, titulo, sede, tot, disp))

        con.executemany(
            "INSERT INTO libros(idLibro, titulo, sede, ejemplares_totales, ejemplares_disponibles) VALUES (?,?,?,?,?)",
            libros
        )

        prestados_s1 = list(range(1, mitad + 1))
        prestados_s2 = list(range(mitad + 1, n_libros + 1))
        random.seed(42)
        sample_s1 = random.sample(prestados_s1, prest_s1)
        sample_s2 = random.sample(prestados_s2, prest_s2)
        activos = []
        now = iso_now()
        plus14 = iso_days_from_now(14)

        for i in sample_s1:
            idLibro = f"L{i:04d}"
            con.execute("UPDATE libros SET ejemplares_disponibles = 0 WHERE idLibro = ?", (idLibro,))
            activos.append((
                f"S-INIT-S1-{i:04d}", f"U{i:04d}", idLibro, "SEDE1", now, plus14, "ACTIVO"
            ))
        for i in sample_s2:
            idLibro = f"L{i:04d}"
            con.execute("UPDATE libros SET ejemplares_disponibles = 0 WHERE idLibro = ?", (idLibro,))
            activos.append((
                f"S-INIT-S2-{i:04d}", f"U{i:04d}", idLibro, "SEDE2", now, plus14, "ACTIVO"
            ))

        con.executemany("""
            INSERT INTO prestamos(idSolicitud, idUsuario, idLibro, sede, fecha_prestamo, fecha_entrega, estado)
            VALUES (?,?,?,?,?,?,?)
        """, activos)

        con.commit()
        print(f"[INIT-DB] BD creada en {db_path} con {n_libros} libros y {prest_s1 + prest_s2} préstamos ACTIVO.")

def main():
    ap = argparse.ArgumentParser(description="Inicializa la BD con datos base.")
    ap.add_argument("--db", default=DB_NAME, help="Ruta destino de la BD SQLite")
    ap.add_argument("--libros", type=int, default=1000, help="Cantidad de libros a generar")
    ap.add_argument("--prest_s1", type=int, default=50, help="Préstamos activos iniciales en SEDE1")
    ap.add_argument("--prest_s2", type=int, default=150, help="Préstamos activos iniciales en SEDE2")
    args = ap.parse_args()
    seed_db(args.db, args.libros, args.prest_s1, args.prest_s2)

if __name__ == "__main__":
    main()
