"""Catálogo demo (§17): proyectos, documentos, datasets, arquitecturas e historial.

Los proyectos y su documentación son la cartera de ejemplo del frontend original.
PRJ-101 y PRJ-102 se conservan tal cual porque las pruebas automáticas dependen de
ellos (aislamiento entre proyectos, flujo E2E sobre Iris).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.demo import datasets as data

USERS = [
    ("USR-201", "Sofía Ramírez Castro", "sofia.ramirez", "Administradora de plataforma", "admin"),
    ("USR-207", "Ana Quispe Ramos", "ana.quispe", "Ingeniera de IA", "engineer"),
    ("USR-212", "Luis Paredes Soto", "luis.paredes", "Ingeniero de IA", "engineer"),
    ("USR-218", "Rosa Medina Vega", "rosa.medina", "Revisora de modelos", "reviewer"),
    ("USR-223", "Diego Salas Rojas", "diego.salas", "Responsable de proyecto", "owner"),
    ("USR-231", "Carla Núñez Prado", "carla.nunez", "Analista de datos", "reader"),
    ("USR-236", "Marco Herrera León", "marco.herrera", "Ingeniero de ML", "engineer"),
    ("USR-244", "Elena Torres Gil", "elena.torres", "Revisora de modelos", "reviewer"),
    ("USR-251", "Jorge Campos Ríos", "jorge.campos", "Auditor de datos", "reader"),
]


@dataclass
class DemoDataset:
    name: str
    description: str
    generator: Callable[[], bytes]
    license: str
    tags: list[str]
    privacy: str = "INTERNAL"


@dataclass
class DemoArchitecture:
    name: str
    family: str
    justification: str
    input: dict[str, int]
    layers: list[dict[str, Any]]


@dataclass
class DemoJob:
    """Entrenamiento que la semilla deja en cola y el worker ejecuta al arrancar."""

    architecture: str
    dataset: str
    target: str
    owner: str
    epochs: int
    batch_size: int = 32
    optimizer: str = "adam"
    learning_rate: float = 0.005
    priority: str = "NORMAL"
    early_stopping_patience: int | None = None
    cancel_reason: str | None = None
    observations: list[tuple[str, str, str, str]] = field(default_factory=list)


@dataclass
class DemoProject:
    id: str
    name: str
    family: str
    status: str
    owner: str
    created: str
    updated: str
    description: str
    tags: list[str]
    members: list[tuple[str, str, str]]
    documents: list[tuple[str, str, str, str]] = field(default_factory=list)
    datasets: list[DemoDataset] = field(default_factory=list)
    architectures: list[DemoArchitecture] = field(default_factory=list)
    jobs: list[DemoJob] = field(default_factory=list)


def dense(units: int, activation: str = "relu") -> dict[str, Any]:
    return {"type": "Dense", "units": units, "activation": activation}


def dropout(rate: float) -> dict[str, Any]:
    return {"type": "Dropout", "dropout": rate}


SKLEARN = "BSD-3-Clause (scikit-learn)"
SYNTHETIC = "Uso interno · datos sintéticos"

PROJECTS: list[DemoProject] = [
    DemoProject(
        id="PRJ-101", name="Clasificación de especies Iris", family="FEEDFORWARD", status="ACTIVE",
        owner="USR-207", created="2026-07-01T09:00:00Z", updated="2026-10-30T10:00:00Z",
        description="Clasificar flores Iris en tres especies a partir de cuatro medidas del sépalo y el pétalo. "
                    "Proyecto de demostración del flujo completo del MVP (§18).",
        tags=["demo", "tabular", "clasificación"],
        members=[("USR-207", "owner", "2026-07-01T09:00:00Z"), ("USR-212", "engineer", "2026-07-03T10:00:00Z"),
                 ("USR-218", "reviewer", "2026-07-05T11:00:00Z"), ("USR-231", "reader", "2026-07-08T12:00:00Z")],
        documents=[("Objetivo del MVP", "Demostrar de extremo a extremo que una red Feedforward se configura, entrena con "
                    "TensorFlow/Keras, se sigue en tiempo real y queda versionada con trazabilidad (§18).\n\n"
                    "La exactitud de prueba esperada es superior al 90 %.", "USR-207", "2026-07-02T09:30:00Z")],
        datasets=[DemoDataset("iris", "150 flores, 4 medidas en cm y la especie.", data.iris, SKLEARN,
                              ["tabular", "demo", "clasificación"], "PUBLIC")],
        architectures=[DemoArchitecture(
            "ff-iris", "FEEDFORWARD", "Datos tabulares con pocas características: una red densa pequeña basta.",
            {"features": 4}, [dense(16), dropout(0.1), dense(8), dense(3, "softmax")])],
        jobs=[
            DemoJob("ff-iris", "iris", "especie", "USR-207", epochs=40, batch_size=16, learning_rate=0.01,
                    observations=[("LIMITATION", "Partición de prueba pequeña",
                                   "Solo 23 flores en prueba: un error mueve la exactitud más de 4 puntos.", "USR-218")]),
            DemoJob("ff-iris", "iris", "especie", "USR-212", epochs=25, batch_size=16, optimizer="adamw",
                    learning_rate=0.005),
        ],
    ),
    DemoProject(
        id="PRJ-102", name="Predicción de fallas en compresores", family="RNN", status="DRAFT",
        owner="USR-223", created="2026-08-10T08:00:00Z", updated="2026-10-29T16:00:00Z",
        description="Anticipar fallas de compresores industriales a partir de series de vibración.",
        tags=["series", "mantenimiento"],
        members=[("USR-223", "owner", "2026-08-10T08:00:00Z"), ("USR-236", "engineer", "2026-08-12T09:00:00Z"),
                 ("USR-244", "reviewer", "2026-08-15T10:00:00Z")],
        datasets=[DemoDataset("vibracion-compresores", "Lecturas resumidas por compresor y falla en las 48 h siguientes.",
                              data.vibracion_compresores, SYNTHETIC, ["sensores", "mantenimiento"])],
        architectures=[
            DemoArchitecture("lstm-vibracion", "RNN", "Las fallas dependen de la evolución temporal de la vibración.",
                             {"timesteps": 50, "seqFeatures": 6},
                             [{"type": "LSTM", "units": 32, "activation": "tanh"}, dense(1, "sigmoid")]),
            DemoArchitecture("ff-vibracion-base", "FEEDFORWARD",
                             "Línea base densa sobre lecturas resumidas mientras se habilita la familia RNN (§18).",
                             {"features": 5}, [dense(24), dense(12), dense(1, "sigmoid")]),
        ],
        jobs=[DemoJob("ff-vibracion-base", "vibracion-compresores", "falla_48h", "USR-236", epochs=30)],
    ),
    DemoProject(
        id="PRJ-118", name="Scoring de riesgo de fuga", family="FEEDFORWARD", status="ACTIVE",
        owner="USR-207", created="2026-07-14T09:00:00Z", updated="2026-10-28T16:20:00Z",
        description="Predecir la probabilidad de que un cliente empresarial cancele su contrato en los próximos 90 días, "
                    "priorizando las cuentas que requieren intervención del equipo de éxito del cliente.",
        tags=["riesgo", "binario", "customer-success"],
        members=[("USR-207", "owner", "2026-07-14T09:00:00Z"), ("USR-212", "engineer", "2026-07-18T14:30:00Z"),
                 ("USR-218", "reviewer", "2026-08-02T10:15:00Z"), ("USR-231", "reader", "2026-09-10T16:40:00Z")],
        documents=[
            ("Contexto del problema", "El equipo comercial detecta la intención de cancelación demasiado tarde: las señales de "
             "uso se revisan de forma manual y solo cuando el cliente ya abrió un ticket de salida.\n\nEste proyecto busca "
             "anticipar esa decisión con un modelo binario que combine actividad del producto, tickets de soporte y "
             "facturación de los últimos seis meses. El resultado se usará como insumo para priorizar llamadas de "
             "retención, nunca para decisiones automáticas.", "USR-207", "2026-10-27T15:10:00Z"),
            ("Criterios de éxito", "La versión candidata debe alcanzar un AUC-ROC igual o superior a 0,86 en la partición de "
             "prueba y mantener una tasa de falsos positivos por debajo del 18 %.\n\nLa revisión de sesgo se hará por "
             "segmento de antigüedad y tamaño de cuenta. Un modelo que incumpla cualquiera de los dos criterios se devuelve "
             "a diseño antes de publicarse.", "USR-218", "2026-10-22T11:35:00Z"),
        ],
        datasets=[DemoDataset("clientes-fuga", "Cuentas empresariales con uso, soporte, facturación y fuga a 90 días.",
                              data.clientes_fuga, SYNTHETIC, ["clientes", "binario"])],
        architectures=[DemoArchitecture(
            "ff-fuga", "FEEDFORWARD", "Variables tabulares mixtas: densa con dropout para no memorizar cuentas.",
            {"features": 10}, [dense(32), dropout(0.2), dense(16), dense(1, "sigmoid")])],
        jobs=[
            DemoJob("ff-fuga", "clientes-fuga", "fuga", "USR-207", epochs=30, priority="ALTA",
                    observations=[("RISK", "Clase minoritaria", "Solo ~25 % de fugas: revisar recall antes de aprobar.",
                                   "USR-218")]),
            DemoJob("ff-fuga", "clientes-fuga", "fuga", "USR-212", epochs=40, optimizer="sgd", learning_rate=0.05,
                    early_stopping_patience=5),
            DemoJob("ff-fuga", "clientes-fuga", "fuga", "USR-212", epochs=30, batch_size=64,
                    cancel_reason="Duplicado del trabajo anterior con otro lote; se cancela antes de ocupar el worker."),
        ],
    ),
    DemoProject(
        id="PRJ-121", name="Detección de fraude transaccional", family="RNN", status="ACTIVE",
        owner="USR-223", created="2026-06-02T08:20:00Z", updated="2026-10-29T08:10:00Z",
        description="Identificar cargos fraudulentos en secuencias cortas de transacciones con ventana deslizante, "
                    "reduciendo falsos positivos frente al motor de reglas actual.",
        tags=["fraude", "series-temporales", "tiempo-real"],
        members=[("USR-223", "owner", "2026-06-02T08:20:00Z"), ("USR-207", "engineer", "2026-06-08T13:00:00Z"),
                 ("USR-212", "engineer", "2026-06-15T09:45:00Z"), ("USR-244", "reviewer", "2026-07-01T17:10:00Z"),
                 ("USR-231", "reader", "2026-08-19T10:05:00Z")],
        documents=[("Arquitectura objetivo", "Se evaluará una red recurrente con unidades GRU sobre ventanas de 20 "
                    "transacciones. La entrada combina monto normalizado, canal, comercio y hora; la salida es una "
                    "probabilidad calibrada de fraude.\n\nEl modelo no reemplaza al motor de reglas: se ejecuta como segunda "
                    "capa de scoring y solo recibe los eventos que superan el umbral inicial.", "USR-223",
                    "2026-10-26T18:00:00Z")],
        datasets=[DemoDataset("transacciones", "Transacciones con tarjeta y etiqueta de fraude (≈9 %).",
                              data.transacciones, SYNTHETIC, ["fraude", "desbalanceado"], "SENSITIVE")],
        architectures=[
            DemoArchitecture("gru-fraude", "RNN", "Secuencias de 20 transacciones con memoria compacta.",
                             {"timesteps": 20, "seqFeatures": 8},
                             [{"type": "GRU", "units": 32, "activation": "tanh"}, dense(1, "sigmoid")]),
            DemoArchitecture("ff-fraude-base", "FEEDFORWARD", "Línea base por transacción individual.",
                             {"features": 14}, [dense(32), dropout(0.2), dense(1, "sigmoid")]),
        ],
        jobs=[DemoJob("ff-fraude-base", "transacciones", "fraude", "USR-207", epochs=20, batch_size=64)],
    ),
    DemoProject(
        id="PRJ-126", name="Visión industrial de juntas", family="CNN", status="ACTIVE",
        owner="USR-207", created="2026-08-05T07:30:00Z", updated="2026-10-27T11:45:00Z",
        description="Detectar defectos superficiales en juntas metálicas durante la línea de ensamblaje y clasificar su "
                    "severidad para activar el rechazo automático.",
        tags=["visión", "manufactura", "calidad"],
        members=[("USR-207", "owner", "2026-08-05T07:30:00Z"), ("USR-212", "engineer", "2026-08-05T07:30:00Z"),
                 ("USR-218", "reviewer", "2026-08-21T12:00:00Z"), ("USR-231", "reader", "2026-09-02T15:25:00Z")],
        documents=[
            ("Plan de etiquetado", "Cada imagen se etiqueta con una de cuatro clases: junta conforme, porosidad leve, fisura "
             "y deformación. Dos especialistas revisan las muestras dudosas y un tercero resuelve los desacuerdos.",
             "USR-207", "2026-10-24T09:20:00Z"),
            ("Restricciones de la línea", "La inferencia debe completarse en menos de 120 ms por pieza para no detener la "
             "línea. El modelo corre en el servidor de planta y no puede enviar imágenes fuera de la red industrial.",
             "USR-212", "2026-10-27T11:45:00Z"),
        ],
        architectures=[DemoArchitecture(
            "cnn-juntas", "CNN", "Filtros convolucionales para defectos locales en imágenes de 64×64.",
            {"height": 64, "width": 64, "channels": 1},
            [{"type": "Conv2D", "filters": 16, "kernelSize": 3, "activation": "relu"}, {"type": "MaxPooling2D", "poolSize": 2},
             {"type": "Conv2D", "filters": 32, "kernelSize": 3, "activation": "relu"}, {"type": "MaxPooling2D", "poolSize": 2},
             {"type": "Flatten"}, dense(64), dense(4, "softmax")])],
    ),
    DemoProject(
        id="PRJ-131", name="Síntesis de datos tabulares", family="GAN", status="DRAFT",
        owner="USR-212", created="2026-09-18T10:00:00Z", updated="2026-10-25T09:30:00Z",
        description="Generar muestras sintéticas que equilibren las clases minoritarias de los sensores de turbina sin "
                    "exponer datos operativos confidenciales.",
        tags=["generativo", "datos-sinteticos", "tabular"],
        members=[("USR-212", "owner", "2026-09-18T10:00:00Z"), ("USR-207", "reviewer", "2026-09-22T11:30:00Z"),
                 ("USR-223", "engineer", "2026-09-29T09:15:00Z")],
        documents=[("Alcance del piloto", "El piloto se limita a las lecturas de vibración de dos turbinas y a tres clases "
                    "de fallo poco frecuentes. La meta es duplicar la representación de esas clases sin alterar la "
                    "distribución de las variables de operación.", "USR-212", "2026-10-25T09:30:00Z")],
        architectures=[DemoArchitecture(
            "gan-turbinas", "GAN", "Generador denso desde un espacio latente de 32 dimensiones.",
            {"latent": 32}, [dense(64), dense(128), dense(12, "sigmoid")])],
    ),
    DemoProject(
        id="PRJ-018", name="Clasificación de dígitos", family="FEEDFORWARD", status="ACTIVE",
        owner="USR-207", created="2026-03-11T08:40:00Z", updated="2026-10-28T10:05:00Z",
        description="Reconocer dígitos manuscritos en formularios escaneados para automatizar la captura de códigos de "
                    "cliente y reducir la digitación manual.",
        tags=["visión", "digitos", "benchmark"],
        members=[("USR-207", "owner", "2026-03-11T08:40:00Z"), ("USR-212", "engineer", "2026-03-19T10:10:00Z"),
                 ("USR-218", "reviewer", "2026-04-04T14:50:00Z")],
        documents=[
            ("Problema y alcance", "Los formularios de afiliación llegan escaneados y el código de cliente se transcribe a "
             "mano. El error de digitación genera duplicados y retrasa la activación del servicio.", "USR-207",
             "2026-09-30T11:05:00Z"),
            ("Línea base del modelo", "La red Feedforward de referencia usa una capa oculta de 128 unidades con activación "
             "ReLU y salida softmax de 10 clases sobre imágenes de 8×8 normalizadas.", "USR-212", "2026-10-28T10:05:00Z"),
        ],
        datasets=[DemoDataset("digitos-8x8", "1797 dígitos manuscritos de 8×8 píxeles (64 características).",
                              data.digitos, SKLEARN, ["visión", "benchmark"], "PUBLIC")],
        architectures=[DemoArchitecture(
            "ff-digitos", "FEEDFORWARD", "64 píxeles aplanados: una capa oculta ancha basta como línea base.",
            {"features": 64}, [dense(128), dropout(0.2), dense(10, "softmax")])],
        jobs=[DemoJob("ff-digitos", "digitos-8x8", "digito", "USR-207", epochs=20, batch_size=64, learning_rate=0.002)],
    ),
    DemoProject(
        id="PRJ-021", name="Visión para objetos", family="CNN", status="ACTIVE",
        owner="USR-212", created="2026-05-06T09:00:00Z", updated="2026-10-26T17:40:00Z",
        description="Clasificar objetos y prendas en imágenes de inventario para mejorar la búsqueda visual del catálogo "
                    "y detectar publicaciones incompletas.",
        tags=["visión", "objetos", "cnn"],
        members=[("USR-212", "owner", "2026-05-06T09:00:00Z"), ("USR-207", "engineer", "2026-05-13T15:20:00Z"),
                 ("USR-223", "engineer", "2026-06-01T11:00:00Z"), ("USR-231", "reader", "2026-07-22T10:35:00Z")],
        documents=[("Fuentes de imágenes", "El corpus combina fotos de estudio del catálogo con imágenes de usuarios "
                    "aprobadas para uso interno. Cada lote conserva un manifiesto con origen, licencia y fecha de ingesta.",
                    "USR-212", "2026-10-26T17:40:00Z")],
        architectures=[DemoArchitecture(
            "cnn-objetos", "CNN", "Convolución simple sobre miniaturas de 32×32 en color.",
            {"height": 32, "width": 32, "channels": 3},
            [{"type": "Conv2D", "filters": 32, "kernelSize": 3, "activation": "relu"}, {"type": "MaxPooling2D", "poolSize": 2},
             {"type": "Flatten"}, dense(10, "softmax")])],
    ),
    DemoProject(
        id="PRJ-024", name="Análisis de sentimiento", family="RNN", status="ACTIVE",
        owner="USR-207", created="2026-04-09T10:00:00Z", updated="2026-10-24T14:15:00Z",
        description="Clasificar la polaridad de reseñas de productos en español para priorizar reclamos y detectar caídas "
                    "de satisfacción por categoría.",
        tags=["nlp", "sentimiento", "español"],
        members=[("USR-207", "owner", "2026-04-09T10:00:00Z"), ("USR-218", "reviewer", "2026-04-16T09:40:00Z"),
                 ("USR-231", "reader", "2026-05-03T16:15:00Z")],
        documents=[
            ("Diccionario de etiquetas", "La polaridad se anota en tres clases: negativa, neutra y positiva. Una reseña con "
             "elogios y quejas se marca según la intención dominante.", "USR-207", "2026-09-28T12:30:00Z"),
            ("Protocolo de anonimización", "Antes de cargar una reseña se eliminan correos, teléfonos, nombres propios y "
             "números de pedido. Ningún modelo se entrena con textos crudos.", "USR-218", "2026-10-24T14:15:00Z"),
        ],
        architectures=[DemoArchitecture(
            "lstm-sentimiento", "RNN", "Secuencias de 100 tokens con embeddings de 50 dimensiones.",
            {"timesteps": 100, "seqFeatures": 50},
            [{"type": "LSTM", "units": 64, "activation": "tanh"}, dropout(0.2), dense(3, "softmax")])],
    ),
    DemoProject(
        id="PRJ-027", name="Detección de anomalías sísmicas", family="RNN", status="ACTIVE",
        owner="USR-223", created="2026-02-17T08:00:00Z", updated="2026-10-29T07:20:00Z",
        description="Detectar patrones anómalos en ventanas de sensores sísmicos del norte del país para emitir alertas "
                    "tempranas con revisión humana.",
        tags=["series-temporales", "sensores", "anomalias"],
        members=[("USR-223", "owner", "2026-02-17T08:00:00Z"), ("USR-212", "engineer", "2026-02-25T10:20:00Z"),
                 ("USR-207", "reader", "2026-08-14T09:10:00Z"), ("USR-218", "reviewer", "2026-09-01T13:45:00Z")],
        documents=[("Contexto operativo", "Las estaciones del norte envían ventanas de 10 segundos con tres componentes de "
                    "movimiento. La salida del modelo es una alerta priorizada para el turno de monitoreo. Ninguna alerta "
                    "activa protocolos automáticos: la decisión final siempre es humana.", "USR-223",
                    "2026-10-29T07:20:00Z")],
        datasets=[DemoDataset("ventanas-sismicas", "Características de ventanas de 10 s por estación (anómala/normal).",
                              data.ventanas_sismicas, SYNTHETIC, ["sensores", "series"])],
        architectures=[
            DemoArchitecture("lstm-sismos", "RNN", "Ventanas crudas de 1000 muestras en tres componentes.",
                             {"timesteps": 1000, "seqFeatures": 3},
                             [{"type": "LSTM", "units": 32, "activation": "tanh"}, dense(1, "sigmoid")]),
            DemoArchitecture("ff-sismos-base", "FEEDFORWARD", "Línea base sobre características resumidas de cada ventana.",
                             {"features": 11}, [dense(32), dense(16), dense(1, "sigmoid")]),
        ],
        jobs=[DemoJob("ff-sismos-base", "ventanas-sismicas", "estado", "USR-212", epochs=25, priority="ALTA")],
    ),
    DemoProject(
        id="PRJ-029", name="Generación de retratos", family="GAN", status="DRAFT",
        owner="USR-223", created="2026-09-22T12:00:00Z", updated="2026-10-20T12:00:00Z",
        description="Entrenar un generador de retratos sintéticos para aumentar la diversidad de un dataset de referencia "
                    "sin recurrir a imágenes de personas reales.",
        tags=["generativo", "imagenes"],
        members=[("USR-223", "owner", "2026-09-22T12:00:00Z"), ("USR-212", "engineer", "2026-09-27T09:30:00Z"),
                 ("USR-207", "reviewer", "2026-10-01T15:00:00Z")],
        architectures=[DemoArchitecture(
            "gan-retratos", "GAN", "Generador denso que produce retratos de 32×32 en escala de grises.",
            {"latent": 100}, [dense(256), dense(512), dense(1024, "sigmoid")])],
    ),
    DemoProject(
        id="PRJ-031", name="Regresión de precios", family="FEEDFORWARD", status="ARCHIVED",
        owner="USR-207", created="2026-01-20T09:30:00Z", updated="2026-09-30T15:00:00Z",
        description="Estimar el precio de vivienda a partir de distrito, área y características estructurales para apoyar "
                    "la tasación inicial de créditos hipotecarios.",
        tags=["tabular", "regresion"],
        members=[("USR-207", "owner", "2026-01-20T09:30:00Z"), ("USR-231", "reader", "2026-02-11T11:45:00Z")],
        documents=[("Cierre del piloto", "El piloto se archivó porque la variable de distrito no estaba actualizada en el "
                    "sistema de origen. Se conservan las versiones del dataset y del modelo para trazabilidad.",
                    "USR-207", "2026-09-30T15:00:00Z")],
        datasets=[DemoDataset("viviendas-lima", "Viviendas simuladas por distrito con precio en soles.",
                              data.viviendas, SYNTHETIC, ["tabular", "regresión"])],
        architectures=[DemoArchitecture(
            "ff-precios", "FEEDFORWARD", "Regresión densa con salida lineal.",
            {"features": 14}, [dense(64), dense(32), dense(1, "linear")])],
        jobs=[DemoJob("ff-precios", "viviendas-lima", "precio_soles", "USR-207", epochs=60, learning_rate=0.01)],
    ),
]
