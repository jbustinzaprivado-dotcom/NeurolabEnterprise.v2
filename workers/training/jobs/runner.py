"""Ejecución de un trabajo: PREPARING → RUNNING → evaluación → versión del modelo.

Cada paso deja estado persistido; si algo falla, el trabajo queda FAILED con
un mensaje controlado y la traza técnica en `error_detail` (solo admin).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
import traceback
from collections.abc import Callable
from pathlib import Path

import joblib
import keras
import numpy as np
from sklearn import metrics as skm
from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import SessionLocal, utcnow
from app.modules import state_machine as sm
from app.modules.datasets import read_csv_bytes
from app.repositories.models import ModelVersion, TrainingJob
from app.services import audit, job_events, platform_settings
from workers.training.callbacks.progress import ProgressCallback
from workers.training.pipelines.model_builder import build_model
from workers.training.pipelines.tabular import PreparedData, prepare

logger = logging.getLogger("neurolab.worker")


class ControlledError(Exception):
    """Error esperado cuyo mensaje se puede mostrar tal cual al usuario."""


def _finish(job_id: str, target: str, reason: str, detail: str | None = None) -> None:
    with SessionLocal() as db:
        job = db.get(TrainingJob, job_id)
        if job.status in sm.TERMINAL:
            return
        if detail:
            job.error_detail = detail
        job_events.transition(db, job, target, reason)
        if target == sm.FAILED:
            job_events.log(db, job_id, reason, "error")
        db.commit()


def _predict_labels(model: keras.Model, x: np.ndarray) -> np.ndarray:
    predictions = model.predict(x, verbose=0)
    if predictions.shape[1] == 1:
        return (predictions.reshape(-1) >= 0.5).astype(int)
    return predictions.argmax(axis=1)


def _f1_per_epoch(data: PreparedData) -> Callable[[keras.Model], dict[str, float]]:
    """F1 macro de entrenamiento y validación por época; muestrea hasta 2000 filas para no frenar."""
    rng = np.random.default_rng(0)
    sample = rng.choice(len(data.y_train), size=min(2000, len(data.y_train)), replace=False)

    def compute(model: keras.Model) -> dict[str, float]:
        return {
            "f1": float(skm.f1_score(data.y_train[sample], _predict_labels(model, data.x_train[sample]),
                                     average="macro", zero_division=0)),
            "val_f1": float(skm.f1_score(data.y_val, _predict_labels(model, data.x_val),
                                         average="macro", zero_division=0)),
        }

    return compute


def _latency_p95_ms(model: keras.Model, data: PreparedData, samples: int = 40) -> float:
    """Latencia de inferencia de una sola fila, como la vería un servicio en línea."""
    rows = data.x_test[: max(1, min(samples, len(data.x_test)))]
    timings = []
    for row in rows:
        start = time.perf_counter()
        model(row[np.newaxis, :], training=False)
        timings.append((time.perf_counter() - start) * 1000)
    return float(np.percentile(timings, 95))


def _evaluate(model: keras.Model, data: PreparedData, task: str) -> dict:
    scores = model.evaluate(data.x_test, data.y_test, verbose=0, return_dict=True)
    result: dict = {
        "task": task,
        "testRows": int(len(data.y_test)),
        "test": {k: float(v) for k, v in scores.items()},
        "latencyP95Ms": round(_latency_p95_ms(model, data), 2),
    }
    predictions = model.predict(data.x_test, verbose=0)
    if task == "regression":
        predicted = predictions.reshape(-1)
        result["test"].update({
            "r2": float(skm.r2_score(data.y_test, predicted)),
            "rmse": float(np.sqrt(skm.mean_squared_error(data.y_test, predicted))),
        })
        return result

    if predictions.shape[1] == 1:
        predicted = (predictions.reshape(-1) >= 0.5).astype(int)
    else:
        predicted = predictions.argmax(axis=1)
    labels = list(range(len(data.classes)))
    matrix = skm.confusion_matrix(data.y_test, predicted, labels=labels)
    precision, recall, f1, support = skm.precision_recall_fscore_support(
        data.y_test, predicted, labels=labels, zero_division=0
    )
    result["test"]["macroF1"] = float(np.mean(f1))
    result["confusionMatrix"] = {
        "classes": [
            {
                "index": i,
                "label": label,
                "counts": [int(c) for c in matrix[i]],
                "total": int(support[i]),
                "precision": float(precision[i]),
                "recall": float(recall[i]),
                "f1": float(f1[i]),
            }
            for i, label in enumerate(data.classes)
        ]
    }
    return result


def _checksum(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(folder.iterdir()):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _register(job_id: str, model: keras.Model, data: PreparedData, evaluation: dict, stop_note: str | None) -> None:
    """Guarda artefactos inmutables (RN-04) y cierra el trabajo como COMPLETED."""
    with SessionLocal() as db:
        job = db.get(TrainingJob, job_id)
        arch = job.architecture
        latest = db.scalar(
            select(func.max(ModelVersion.version)).where(
                ModelVersion.project_id == job.project_id, ModelVersion.name == arch.name
            )
        )
        version = (latest or 0) + 1
        # Una carpeta huérfana (registro interrumpido) nunca se sobrescribe: se salta ese número.
        while (settings.data_dir / f"models/{job.project_id}/{arch.name}/v{version}").exists():
            version += 1
        storage_key = f"models/{job.project_id}/{arch.name}/v{version}"
        folder = settings.data_dir / storage_key
        folder.mkdir(parents=True)

        model.save(folder / "model.keras")
        joblib.dump(
            {
                "preprocessor": data.preprocessor,
                "label_encoder": data.label_encoder,
                "input_columns": data.input_columns,
                "target": job.target_column,
            },
            folder / "preprocessor.pkl",
        )
        metadata = {
            "jobId": job.id,
            "projectId": job.project_id,
            "architecture": {"id": arch.id, "name": arch.name, "version": arch.version, "family": arch.family},
            "dataset": {"id": job.dataset.id, "name": job.dataset.name, "version": job.dataset.version,
                        "checksum": job.dataset.checksum},
            "target": job.target_column,
            "params": job.params_json,
            "codeVersion": job.code_version,
            "kerasVersion": keras.__version__,
            "inputColumns": data.input_columns,
            "features": data.feature_names,
            "droppedColumns": data.dropped,
            "classes": data.classes,
            "epochsRun": job.epoch,
            "trainedBy": job.created_by,
            "createdAt": utcnow().isoformat(),
        }
        (folder / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

        model_version = ModelVersion(
            project_id=job.project_id, job_id=job.id, architecture_id=arch.id, name=arch.name, version=version,
            storage_key=storage_key, checksum=_checksum(folder),
            metrics_json={**evaluation["test"], **{f"final_{k}": v for k, v in job.result_json.get("latest", {}).items()}},
            metadata_json=metadata,
        )
        db.add(model_version)
        db.flush()
        job.result_json = {**job.result_json, "evaluation": evaluation}
        reason = f"Modelo registrado como {arch.name} v{version}.0."
        if stop_note:
            reason = f"{stop_note} {reason}"
        job_events.log(db, job.id, reason, "success")
        job_events.transition(db, job, sm.COMPLETED, reason)
        audit.record(db, job.created_by, "model.register", "model_version", model_version.id, job.project_id,
                     jobId=job.id, version=version, checksum=model_version.checksum)
        db.commit()


def run_job(job_id: str, worker_id: str) -> str:
    """Ejecuta un trabajo ya reclamado (PREPARING) y devuelve su estado final."""
    try:
        with SessionLocal() as db:
            job = db.get(TrainingJob, job_id)
            if job.status != sm.PREPARING:
                return job.status
            if job.cancel_requested:
                job_events.transition(db, job, sm.CANCELLED, job.cancel_reason)
                db.commit()
                return sm.CANCELLED
            params = dict(job.params_json)
            config = dict(job.architecture.config_json)
            dataset_path = settings.data_dir / job.dataset.storage_key
            split = dict(job.dataset.split)
            target = job.target_column
            job_events.log(db, job_id, f"Preparando {job.dataset.name} v{job.dataset.version} (objetivo «{target}»).")
            db.commit()

        if not dataset_path.is_file():
            raise ControlledError("El archivo del dataset no está en el almacenamiento.")
        try:
            data = prepare(read_csv_bytes(dataset_path.read_bytes()), target, params["task"], split, params["seed"])
        except ValueError as exc:
            raise ControlledError(f"Preprocesamiento: {exc}") from exc
        if params["task"] == "classification" and len(data.classes) != params["classes"]:
            raise ControlledError(
                f"El objetivo tiene {len(data.classes)} clases tras limpiar nulos; la arquitectura espera {params['classes']}."
            )

        keras.utils.set_random_seed(params["seed"])
        model = build_model(config, (data.input_dim,), params["task"], params["optimizer"], params["learningRate"])

        with SessionLocal() as db:
            job = db.get(TrainingJob, job_id)
            notes = [
                f"Particiones: {len(data.y_train)} entrenamiento · {len(data.y_val)} validación · {len(data.y_test)} prueba.",
                f"{data.input_dim} características de entrada; {model.count_params():,} parámetros.",
            ]
            declared = config.get("input", {}).get("features")
            if declared and declared != data.input_dim:
                notes.append(f"Entrada ajustada de {declared} a {data.input_dim} según las columnas del dataset.")
            if data.dropped:
                notes.append(f"Columnas descartadas: {', '.join(data.dropped)}.")
            for note in notes:
                job_events.log(db, job_id, note)
            if job.cancel_requested:
                job_events.transition(db, job, sm.CANCELLED, job.cancel_reason)
                db.commit()
                return sm.CANCELLED
            job_events.transition(db, job, sm.RUNNING)
            db.commit()

        with SessionLocal() as db:
            max_seconds = int(platform_settings.limit(db, "duration") * 60)
        extra = _f1_per_epoch(data) if params["task"] == "classification" else None
        progress = ProgressCallback(job_id, worker_id, params["epochs"], max_seconds, extra)
        callbacks: list[keras.callbacks.Callback] = [progress]
        early = None
        if params.get("earlyStoppingPatience"):
            early = keras.callbacks.EarlyStopping(
                monitor="val_loss", patience=params["earlyStoppingPatience"], restore_best_weights=True
            )
            callbacks.insert(0, early)

        model.fit(
            data.x_train, data.y_train,
            validation_data=(data.x_val, data.y_val),
            epochs=params["epochs"], batch_size=params["batchSize"],
            callbacks=callbacks, verbose=0,
        )

        if progress.stop_reason == "cancelled":
            with SessionLocal() as db:
                reason = db.get(TrainingJob, job_id).cancel_reason or "Cancelado por el usuario."
            _finish(job_id, sm.CANCELLED, reason)
            return sm.CANCELLED
        if progress.stop_reason == "shutdown":
            _finish(job_id, sm.FAILED, "El worker se detuvo durante la ejecución; reintenta el trabajo.")
            return sm.FAILED
        if progress.stop_reason == "timeout":
            _finish(job_id, sm.FAILED, f"Superó el límite de duración de {max_seconds // 60} min.")
            return sm.FAILED

        stop_note = None
        if early is not None and early.stopped_epoch:
            stop_note = f"Parada temprana en la época {early.stopped_epoch + 1}."
        _register(job_id, model, data, _evaluate(model, data, params["task"]), stop_note)
        return sm.COMPLETED

    except ControlledError as exc:
        _finish(job_id, sm.FAILED, str(exc))
        return sm.FAILED
    except Exception as exc:  # noqa: BLE001 — cualquier fallo debe cerrar el trabajo
        logger.exception("Fallo en %s", job_id)
        _finish(
            job_id, sm.FAILED,
            "Error interno del motor de entrenamiento. La traza quedó registrada para administración.",
            detail="".join(traceback.format_exception(exc))[-8000:],
        )
        return sm.FAILED
