"""Datasets demo no sensibles (§17), generados dentro del proyecto.

Cada generador es determinista (semilla fija) y produce un CSV con encabezados que
la API verifica igual que cualquier carga (RN-01). No se descarga nada: los datos
son sintéticos o vienen incluidos en scikit-learn. Ninguna fila corresponde a una
persona real.
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd


def _csv(frame: pd.DataFrame) -> bytes:
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    return buffer.getvalue().encode()


def _sigmoid(values: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-values))


def iris() -> bytes:
    from sklearn.datasets import load_iris

    frame = load_iris(as_frame=True).frame
    frame.columns = ["largo_sepalo", "ancho_sepalo", "largo_petalo", "ancho_petalo", "especie"]
    frame["especie"] = frame["especie"].map({0: "setosa", 1: "versicolor", 2: "virginica"})
    return _csv(frame)


def digitos() -> bytes:
    """Dígitos manuscritos 8×8 (1797 imágenes) incluidos en scikit-learn."""
    from sklearn.datasets import load_digits

    frame = load_digits(as_frame=True).frame
    frame.columns = [f"pixel_{i:02d}" for i in range(64)] + ["digito"]
    return _csv(frame)


def clientes_fuga(n: int = 1200) -> bytes:
    """Fuga de clientes empresariales a 90 días (binaria, ~25 % de fuga)."""
    rng = np.random.default_rng(118)
    plan = rng.choice(["basico", "pro", "enterprise"], size=n, p=[0.5, 0.35, 0.15])
    antiguedad = rng.integers(1, 73, size=n)
    usuarios = rng.poisson(np.select([plan == "basico", plan == "pro"], [4, 18], 60)) + 1
    uso = rng.gamma(2.0, 9.0, size=n)
    tickets = rng.poisson(1.6, size=n)
    facturacion = np.select([plan == "basico", plan == "pro"], [490, 1890], 6900) + rng.normal(0, 120, size=n)
    atrasado = rng.random(n) < 0.15
    logit = -0.9 - 0.035 * antiguedad + 0.5 * tickets - 0.045 * uso + 1.3 * atrasado - 0.7 * (plan == "enterprise")
    fuga = rng.random(n) < _sigmoid(logit)
    frame = pd.DataFrame({
        "antiguedad_meses": antiguedad,
        "plan": plan,
        "usuarios_activos": usuarios,
        "uso_30d_horas": uso.round(1),
        "tickets_soporte_90d": tickets,
        "facturacion_mensual": facturacion.round(2),
        "pago_atrasado": np.where(atrasado, "si", "no"),
        "fuga": np.where(fuga, "si", "no"),
    })
    # Huecos reales de registro: el preprocesamiento los imputa (mediana).
    frame.loc[rng.random(n) < 0.03, "uso_30d_horas"] = np.nan
    return _csv(frame)


def transacciones(n: int = 2000) -> bytes:
    """Transacciones con tarjeta y etiqueta de fraude (binaria y desbalanceada, ~9 %)."""
    rng = np.random.default_rng(121)
    monto = rng.lognormal(3.6, 0.9, size=n)
    hora = rng.integers(0, 24, size=n)
    canal = rng.choice(["web", "app", "pos", "atm"], size=n, p=[0.3, 0.3, 0.3, 0.1])
    comercio = rng.choice(["retail", "viajes", "digital", "servicios", "combustible"], size=n)
    distancia = rng.exponential(8.0, size=n)
    recientes = rng.poisson(0.8, size=n)
    presente = rng.random(n) < np.where(canal == "pos", 0.95, 0.05)
    nocturna = (hora <= 4) | (hora >= 23)
    logit = (
        -5.2 + 0.012 * monto + 1.1 * nocturna + 0.06 * distancia + 0.7 * recientes
        - 1.2 * presente + 0.8 * (comercio == "digital")
    )
    fraude = rng.random(n) < _sigmoid(logit)
    return _csv(pd.DataFrame({
        "monto": monto.round(2),
        "hora": hora,
        "canal": canal,
        "comercio": comercio,
        "distancia_km_habitual": distancia.round(1),
        "transacciones_ultima_hora": recientes,
        "tarjeta_presente": np.where(presente, "si", "no"),
        "fraude": np.where(fraude, "si", "no"),
    }))


def ventanas_sismicas(n: int = 1500) -> bytes:
    """Características de ventanas de 10 s de estaciones sísmicas (anómala/normal, ~15 %)."""
    rng = np.random.default_rng(27)
    anomala = rng.random(n) < 0.15
    # Distribuciones solapadas: un evento débil se parece al ruido de fondo.
    frame = pd.DataFrame({
        "estacion": rng.choice([f"N{i:02d}" for i in range(1, 6)], size=n),
        "amplitud_max": np.where(anomala, rng.lognormal(0.8, 0.55, n), rng.lognormal(0.4, 0.45, n)).round(3),
        "energia": np.where(anomala, rng.gamma(3, 1.6, n), rng.gamma(2, 1.2, n)).round(3),
        "frecuencia_dominante_hz": np.where(anomala, rng.normal(7.0, 2.4, n), rng.normal(9.0, 2.5, n)).round(2),
        "curtosis": np.where(anomala, rng.normal(4.6, 1.8, n), rng.normal(3.2, 1.0, n)).round(2),
        "relacion_sta_lta": np.where(anomala, rng.normal(1.8, 0.7, n), rng.normal(1.1, 0.35, n)).round(2),
        "duracion_s": rng.uniform(2, 10, n).round(1),
    })
    # Un 4 % de etiquetas dudosas, como las revisiones humanas en desacuerdo.
    dudosas = rng.random(n) < 0.04
    frame["estado"] = np.where(anomala ^ dudosas, "anomala", "normal")
    return _csv(frame)


def vibracion_compresores(n: int = 800) -> bytes:
    """Lecturas resumidas de compresores industriales con falla en las 48 h siguientes."""
    rng = np.random.default_rng(102)
    horas = rng.uniform(100, 20000, n)
    rms = rng.normal(2.0, 0.5, n) + horas / 12000
    temperatura = rng.normal(68, 6, n) + rms * 3
    presion = rng.normal(7.5, 0.8, n)
    pico = rms * rng.uniform(2.5, 4.0, n)
    falla = rng.random(n) < _sigmoid(-9 + 1.4 * rms + 0.06 * (temperatura - 60) + 0.0001 * horas)
    return _csv(pd.DataFrame({
        "rms_vibracion": rms.round(3),
        "pico_vibracion": pico.round(3),
        "temperatura_c": temperatura.round(1),
        "presion_bar": presion.round(2),
        "horas_operacion": horas.round(0).astype(int),
        "falla_48h": np.where(falla, "si", "no"),
    }))


def viviendas(n: int = 900) -> bytes:
    """Precios de vivienda simulados por distrito (regresión, en soles)."""
    rng = np.random.default_rng(31)
    precio_m2 = {
        "Miraflores": 8200, "San Isidro": 8900, "Barranco": 7600, "Surco": 6400,
        "Los Olivos": 3900, "San Juan de Lurigancho": 3300, "Callao": 3500,
    }
    distrito = rng.choice(list(precio_m2), size=n)
    area = rng.uniform(45, 220, n)
    antiguedad = rng.integers(0, 40, n)
    banos = rng.integers(1, 4, n)
    estacionamiento = rng.random(n) < 0.55
    base = np.array([precio_m2[d] for d in distrito])
    precio = area * base * (1 - 0.006 * antiguedad) + 15000 * banos + 22000 * estacionamiento
    precio *= rng.normal(1, 0.07, n)
    return _csv(pd.DataFrame({
        "distrito": distrito,
        "area_m2": area.round(1),
        "dormitorios": np.clip((area / 45).astype(int), 1, 5),
        "banos": banos,
        "antiguedad_anios": antiguedad,
        "piso": rng.integers(1, 21, n),
        "estacionamiento": np.where(estacionamiento, "si", "no"),
        "precio_soles": precio.round(-2),
    }))
