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

* GC REP: `5555`
* GC PUB: `5560`
* GA REP: `5570`

---

## Operaciones soportadas

### DEVOLUCIÓN

* Valida el préstamo activo.
* Marca el libro como `DEVUELTO`.
* Libera el ejemplar.

### RENOVACIÓN

* Verifica el préstamo activo.
* Actualiza la `fecha_entrega` (+7 días por defecto).

### Idempotencia

Todas las operaciones incluyen `idempotencyKey`. El **GA** registra cada clave aplicada para evitar duplicados en reintentos.

---

## Contrato de mensaje

Cada línea del archivo JSONL representa una solicitud:

```json
{
  "op": "DEVOLUCION" | "RENOVACION",
  "idSolicitud": 1001,
  "idUsuario": 501,
  "idLibro": 200,
  "sede": "SEDE1",
  "timestamp": "2025-08-20T12:00:00Z",
  "idempotencyKey": "DEVOLUCION:1001:200"
}
```

---

## Ejecución del sistema

El sistema requiere **6 terminales activas**:

1. **Gestor de almacenamiento (GA)**

   ```bash
   python -m ga.ga --rep tcp://*:5570 --db ga/biblioteca.db
   ```

2. **Actor de devoluciones**

   ```bash
   python -m actores.actor_devol --sub tcp://127.0.0.1:5560 --ga tcp://127.0.0.1:5570
   ```

3. **Actor de renovaciones**

   ```bash
   python -m actores.actor_renov --sub tcp://127.0.0.1:5560 --ga tcp://127.0.0.1:5570
   ```

4. **Gestor de carga (GC)**

   ```bash
   python -m gestor_carga.gc --rep tcp://*:5555 --pub tcp://*:5560
   ```

5. **PS sede 1**

   ```bash
   python -m ps.ps --file ps/data/sol_sede1.txt --endpoint tcp://127.0.0.1:5555
   ```

6. **PS sede 2**

   ```bash
   python -m ps.ps --file ps/data/sol_sede2.txt --endpoint tcp://127.0.0.1:5555
   ```

---

## Dependencias

* Python 3.8+
* Librería **PyZMQ**
* **SQLite** 

Instalación:

```bash
pip install pyzmq
```

---

## Métricas registradas

El sistema recopila métricas de rendimiento y trazabilidad:

* **Latencias**

  * `t_ack`: tiempo entre solicitud PS → ack GC.
  * `t_ga`: tiempo entre recepción de actor → respuesta GA.
* **Throughput**: operaciones por segundo.
* **Consumo de recursos**: CPU, RAM, I/O, tráfico.

Los resultados se guardan en:

* `ps_metrics.csv`
* `actor_metrics.csv`
* `ga_metrics.csv`

---

## Pruebas realizadas

* **Funcionales:** ejecución de devoluciones y renovaciones, validación de contratos y casos de error.
* **Robustez:** manejo de caídas de GC/GA, reintentos y pérdidas de publicaciones.
* **Desempeño:** escalabilidad con múltiples PS en paralelo.

**Resultados esperados:**

* Ack GC < 50 ms.
* Respuesta GA < 150 ms en localhost.

---

## Seguridad

* Validación de mensajes JSON.
* Consultas parametrizadas para evitar inyección SQL.
* Seguimiento por `idSolicitud` e `idempotencyKey`.
* Planeado: uso de TLS/CurveZMQ y autenticación por token.

---

## Roadmap (entrega final)

* Persistencia de publicaciones en GC.
* Health-check de GA con failover.
* Reintentos con backoff exponencial.

---

## Autores

Daniel Avila Medina · Amelie Guerrero Jaramillo · Santiago Hernández Barbosa · Andrés Ortiz Forero
Curso **Sistemas Distribuidos** – Pontificia Universidad Javeriana
