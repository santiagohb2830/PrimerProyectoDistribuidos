# Sistema Distribuido de Préstamo de Libros

## Descripción general

Este proyecto implementa un **sistema distribuido** para gestionar **devoluciones** y **renovaciones** de préstamos de libros. El sistema separa la **ingestión**, el **procesamiento** y la **persistencia** mediante **ZeroMQ** y una base de datos **SQLite**, priorizando la escalabilidad, el desacoplamiento y la idempotencia.

---

## Arquitectura general

* **PS (Procesos Solicitantes)**: leen archivos JSONL con solicitudes y las envían al **Gestor de Carga (GC)**.
* **GC (Gestor de Carga)**: responde un *ack* inmediato a los PS y publica las solicitudes según su tipo (`DEVOLUCION`, `RENOVACION`).
* **Actores**: dos procesos independientes suscritos a los tópicos publicados por el GC.
  * `actor_devol` para devoluciones.
  * `actor_renov` para renovaciones.
* **GA (Gestor de Almacenamiento)**: recibe las operaciones desde los actores y las aplica en la base de datos SQLite usando transacciones ACID.

**Patrones ZeroMQ empleados:**
* PS→GC: REQ/REP
* GC→Actores: PUB/SUB
* Actores→GA: REQ/REP

**Puertos por defecto:**
* GC REP: 5555
* GC PUB: 5560
* GA REP: 5570

---

## Operaciones soportadas

### DEVOLUCIÓN
* Valida el préstamo activo.
* Marca el libro como DEVUELTO.
* Libera el ejemplar.

### RENOVACIÓN
* Verifica el préstamo activo.
* Actualiza la fecha_entrega (+7 días por defecto).

### Idempotencia
Todas las operaciones incluyen idempotencyKey. El GA registra cada clave aplicada para evitar duplicados en reintentos.

---

## Contrato de mensaje

Cada línea del archivo JSONL representa una solicitud:

{
  "op": "DEVOLUCION" | "RENOVACION",
  "idSolicitud": 1001,
  "idUsuario": 501,
  "idLibro": 200,
  "sede": "SEDE1",
  "timestamp": "2025-08-20T12:00:00Z",
  "idempotencyKey": "DEVOLUCION:1001:200"
}

---

## Ejecución del sistema

El sistema requiere **6 terminales activas**:

1. Gestor de almacenamiento (GA)
   python -m ga.ga --rep tcp://*:5570 --db ga/biblioteca.db

2. Actor de devoluciones
   python -m actores.actor_devol --sub tcp://127.0.0.1:5560 --ga tcp://127.0.0.1:5570

3. Actor de renovaciones
   python -m actores.actor_renov --sub tcp://127.0.0.1:5560 --ga tcp://127.0.0.1:5570

4. Gestor de carga (GC)
   python -m gestor_carga.gc --rep tcp://*:5555 --pub tcp://*:5560

5. PS sede 1
   python -m ps.ps --file ps/data/sol_sede1.txt --endpoint tcp://127.0.0.1:5555

6. PS sede 2
   python -m ps.ps --file ps/data/sol_sede2.txt --endpoint tcp://127.0.0.1:5555

---

## Guía rápida de comandos y casos de prueba

### Requisitos
- Python 3.8+
- `pip install pyzmq`
- En shells como zsh pon las direcciones con `*` entre comillas: `--rep 'tcp://*:5570'`.

### Preparación de BD (primera vez)
```bash
cd ga
python3 init_db.py                    # crea ga/biblioteca.db
# o bien inicializa prim/sec iguales:
python3 seed_replicas.py --primary ga/biblioteca_prim.db --secondary ga/biblioteca_sec.db
cd ..
```

### Modo básico (sin réplica/failover)
Usa 6 terminales en la raíz del repo:
```bash
# 1) GA
python3 -m ga.ga --rep 'tcp://*:5570' --db ga/biblioteca.db

# 2) Actor DEVOL
python3 -m actores.actor_devol --sub tcp://127.0.0.1:5560 --ga_primary tcp://127.0.0.1:5570

# 3) Actor RENOV
python3 -m actores.actor_renov --sub tcp://127.0.0.1:5560 --ga_primary tcp://127.0.0.1:5570

# 4) Actor PRESTAMO (síncrono)
python3 -m actores.actor_prestamo --rep 'tcp://*:5558' --ga_primary tcp://127.0.0.1:5570

# 5) Gestor de Carga (GC)
python3 -m gestor_carga.gc --rep 'tcp://*:5555' --pub 'tcp://*:5560' --actor_prestamo tcp://127.0.0.1:5558

# 6) PS (ejemplo sede1)
python3 -m ps.ps --file ps/data/sol_sede1.txt --endpoint tcp://127.0.0.1:5555
# Otro PS opcional:
python3 -m ps.ps --file ps/data/sol_sede2.txt --endpoint tcp://127.0.0.1:5555
```

### Modo con réplica y failover
```bash
# GA primario
python3 -m ga.ga --role primary --rep 'tcp://*:5570' --db ga/biblioteca_prim.db --replica_push tcp://127.0.0.1:5580

# GA secundario (escucha peticiones y replicación)
python3 -m ga.ga --role secondary --rep 'tcp://*:5571' --db ga/biblioteca_sec.db --replica_pull 'tcp://*:5580'

# Actores (failover incluido)
python3 -m actores.actor_devol --sub tcp://127.0.0.1:5560 --ga_primary tcp://127.0.0.1:5570 --ga_secondary tcp://127.0.0.1:5571
python3 -m actores.actor_renov --sub tcp://127.0.0.1:5560 --ga_primary tcp://127.0.0.1:5570 --ga_secondary tcp://127.0.0.1:5571
python3 -m actores.actor_prestamo --rep 'tcp://*:5558' --ga_primary tcp://127.0.0.1:5570 --ga_secondary tcp://127.0.0.1:5571

# GC
python3 -m gestor_carga.gc --rep 'tcp://*:5555' --pub 'tcp://*:5560' --actor_prestamo tcp://127.0.0.1:5558
# Para modo B (DEV/REN síncronos, pruebas de desempeño):
# python3 -m gestor_carga.gc --rep 'tcp://*:5555' --pub 'tcp://*:5560' --actor_prestamo tcp://127.0.0.1:5558 --sync_devren --ga_primary tcp://127.0.0.1:5570 --ga_secondary tcp://127.0.0.1:5571

# PS
python3 -m ps.ps --file ps/data/sol_sede1.txt --endpoint tcp://127.0.0.1:5555 --mode B --metrics_csv ps_metrics.csv
```

### Comandos para la sustentación (demo completa)
1) Sembrar BDs idénticas:
```bash
python3 ga/seed_replicas.py --primary ga/biblioteca_prim.db --secondary ga/biblioteca_sec.db
```
2) Levantar GA primario/secundario (dos terminales):
```bash
python3 -m ga.ga --role primary --rep 'tcp://*:5570' --db ga/biblioteca_prim.db --replica_push tcp://127.0.0.1:5580 --metrics_csv ga_metrics_prim.csv
python3 -m ga.ga --role secondary --rep 'tcp://*:5571' --db ga/biblioteca_sec.db --replica_pull 'tcp://*:5580' --metrics_csv ga_metrics_sec.csv
```
3) Actores (tres terminales):
```bash
python3 -m actores.actor_devol --sub tcp://127.0.0.1:5560 --ga_primary tcp://127.0.0.1:5570 --ga_secondary tcp://127.0.0.1:5571
python3 -m actores.actor_renov --sub tcp://127.0.0.1:5560 --ga_primary tcp://127.0.0.1:5570 --ga_secondary tcp://127.0.0.1:5571
python3 -m actores.actor_prestamo --rep 'tcp://*:5558' --ga_primary tcp://127.0.0.1:5570 --ga_secondary tcp://127.0.0.1:5571
```
4) GC (elige modo A básico o modo B con DEV/REN síncronos):
```bash
# Modo A (baseline)
python3 -m gestor_carga.gc --rep 'tcp://*:5555' --pub 'tcp://*:5560' --actor_prestamo tcp://127.0.0.1:5558 --metrics_csv gc_metrics.csv
# Modo B (DEV/REN síncronos, usado en pruebas de desempeño)
python3 -m gestor_carga.gc --rep 'tcp://*:5555' --pub 'tcp://*:5560' --actor_prestamo tcp://127.0.0.1:5558 --sync_devren --ga_primary tcp://127.0.0.1:5570 --ga_secondary tcp://127.0.0.1:5571 --metrics_csv gc_metrics.csv
```
5) PS/carga (dos o más terminales):
```bash
python3 -m ps.ps --file ps/data/sol_sede1.txt --endpoint tcp://127.0.0.1:5555 --mode A --metrics_csv ps_metrics.csv
python3 -m ps.ps --file ps/data/sol_sede2.txt --endpoint tcp://127.0.0.1:5555 --mode A --metrics_csv ps_metrics.csv
# Para experimentos 2 min / 4-6-10 PS:
python3 -m ps.run_load --files ps/data/sol_sede1.txt ps/data/sol_sede2.txt --endpoint tcp://127.0.0.1:5555 --mode A --duration_s 120 --metrics_csv ps_metrics.csv --summary_dir metrics_summaries
```
6) Failover en vivo: detén el GA primario y envía más solicitudes; los actores seguirán usando el secundario sin reiniciar GC/PS.

### Carga y métricas
- Disparar carga paralela con varios PS:
```bash
python3 -m ps.run_load --files ps/data/sol_sede1.txt ps/data/sol_sede2.txt --endpoint tcp://127.0.0.1:5555 --mode A --metrics_csv ps_metrics.csv --summary_dir metrics_summaries
```
- Analizar métricas PS:
```bash
python3 -m tools.analyze_metrics --file ps_metrics.csv --mode A
```

### Casos de prueba rápidos
- **Préstamo exitoso**: agrega en un archivo de PS una línea `{"op":"PRESTAMO","idUsuario":"U001","idLibro":"L100"}` y verifica que GC responde `ok=True` y GA descuenta ejemplar.
- **Préstamo sin stock**: usa un `idLibro` inexistente o sin ejemplares; espera `ok=False` con mensaje `NO_HAY_EJEMPLARES` o `LIBRO_NO_EXISTE`.
- **Devolución idempotente**: repite dos veces la misma solicitud `DEVOLUCION` (misma `idempotencyKey`) y observa que la segunda responde como aplicada previamente.
- **Failover**: en modo con réplica, mata el GA primario y envía más solicitudes; los actores deben responder usando el secundario sin reiniciar GC/PS.

---

## Dependencias

* Python 3.8+
* PyZMQ
* SQLite

Instalación:
pip install pyzmq

---

## Métricas registradas

* Latencias (t_ack, t_ga)
* Throughput
* Consumo de recursos (CPU, RAM, I/O)

Archivos de salida:
* ps_metrics.csv
* actor_metrics.csv
* ga_metrics.csv

---

## Pruebas realizadas

* Funcionales
* Robustez
* Desempeño

Resultados esperados:
* Ack GC < 50 ms
* Respuesta GA < 150 ms

---

## Seguridad

* Validación JSON
* Consultas parametrizadas
* IdempotencyKey
* (Planeado) TLS/CurveZMQ

---

## Roadmap

* Persistencia GC
* Health-check GA
* Backoff exponencial

---

## Autores

Daniel Avila Medina · Amelie Guerrero Jaramillo · Santiago Hernández Barbosa · Andrés Ortiz Forero  
Curso Sistemas Distribuidos – Pontificia Universidad Javeriana

---

# Documentación del Proyecto

## Entrega 1

La documentación formal de la Entrega 1 está en:

docs/entrega1/DOC-Proyecto-1-SisDistri.pdf

Incluye:
* Modelos del sistema
* Diseño (componentes, clases, despliegue, secuencia)
* Protocolo de pruebas
* Método de métricas
* Implementación inicial (PS → GC → Actores → GA)

---

## Entrega 2

La estructura de la Entrega 2 está organizada así:

docs/entrega2/
    Entrega2-Informe.pdf      ← Informe final (cuando esté terminado)
    resultados/               ← CSV y logs de pruebas de rendimiento

Incluye:
* Pruebas de rendimiento
* Métricas reales
* Análisis del sistema
* Documento final de entrega

---

## Estado del repositorio

* Entrega 1 completa y verificada
* Entrega 2 lista para comenzar
