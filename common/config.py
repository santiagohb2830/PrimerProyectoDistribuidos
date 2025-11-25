import os

# ======================
# GC Binds (para PS)
# ======================
GC_REP_ADDR = os.getenv("GC_REP_ADDR", "tcp://*:5555")   # GC escucha solicitudes de PS
GC_PUB_ADDR = os.getenv("GC_PUB_ADDR", "tcp://*:5560")   # Para DEVOL/RENOV (asíncrono)

# ======================
# GA Bind
# ======================
GA_REP_ADDR = os.getenv("GA_REP_ADDR", "tcp://*:5570")   # GA escucha a actores

# ======================
# ACTOR PRESTAMO (síncrono)
# ======================
ACTOR_PRESTAMO_REP_ADDR = os.getenv("ACTOR_PRESTAMO_REP_ADDR", "tcp://*:5558")   # Actor escucha GC
ACTOR_PRESTAMO_REP_CONNECT = os.getenv("ACTOR_PRESTAMO_REP_CONNECT", "tcp://127.0.0.1:5558")  # GC se conecta al actor

# ======================
# Connects (para procesos que se conectan)
# ======================
GC_REP_CONNECT = os.getenv("GC_REP_CONNECT", "tcp://127.0.0.1:5555")
GC_PUB_CONNECT = os.getenv("GC_PUB_CONNECT", "tcp://127.0.0.1:5560")
GA_REP_CONNECT = os.getenv("GA_REP_CONNECT", "tcp://127.0.0.1:5570")

# ======================
# Topics para DEVOL/RENOV/PRESTAMO
# ======================
TOPIC_DEVOL = "DEVOLUCION"
TOPIC_RENOV = "RENOVACION"
TOPIC_PRESTAMO = "PRESTAMO"

# ======================
# Base de datos
# ======================
DB_PATH = os.getenv("DB_PATH", os.path.join(os.path.dirname(__file__), "..", "ga", "biblioteca.db"))
