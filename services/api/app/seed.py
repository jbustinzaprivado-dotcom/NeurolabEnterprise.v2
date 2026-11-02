"""Datos demo no sensibles (§17): usuarios del directorio del frontend y un proyecto Iris.

Se ejecuta al arrancar si la base está vacía, o manualmente:
    venv\\Scripts\\python.exe services\\api\\app\\seed.py
"""

from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, migrate
from app.core.security import hash_password
from app.modules.architecture import validate_architecture
from app.modules.datasets import inspect_csv
from app.repositories.models import Architecture, Dataset, Project, ProjectMember, User
from app.schemas.architecture import ArchitectureIn
from app.services import audit

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


def _initials(name: str) -> str:
    parts = name.split()
    return (parts[0][0] + parts[1][0]).upper()


def iris_csv() -> bytes:
    from sklearn.datasets import load_iris

    frame = load_iris(as_frame=True).frame
    frame.columns = ["largo_sepalo", "ancho_sepalo", "largo_petalo", "ancho_petalo", "especie"]
    frame["especie"] = frame["especie"].map({0: "setosa", 1: "versicolor", 2: "virginica"})
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    return buffer.getvalue().encode()


def _add_dataset(db: Session, project: Project, name: str, description: str, content: bytes, user_id: str) -> Dataset:
    report = inspect_csv(content)
    dataset = Dataset(
        project_id=project.id, name=name, version=1, description=description,
        original_filename=f"{name}.csv", storage_key="", size_bytes=len(content), rows=report.rows,
        columns=report.columns, checksum=hashlib.sha256(content).hexdigest(), privacy="PUBLIC",
        tags=["tabular", "demo", "clasificación"],
        license="BSD-3-Clause (scikit-learn)", split={"train": 0.7, "validation": 0.15, "test": 0.15},
        metadata_json={"schema": report.schema, "warnings": report.warnings}, created_by=user_id,
    )
    db.add(dataset)
    db.flush()
    dataset.storage_key = f"uploads/{project.id}/{dataset.id}.csv"
    path = settings.data_dir / dataset.storage_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return dataset


def _add_architecture(db: Session, project: Project, payload: dict, user_id: str) -> Architecture:
    arch_in = ArchitectureIn.model_validate(payload)
    summary = validate_architecture(arch_in)
    arch = Architecture(
        project_id=project.id, name=arch_in.name, family=arch_in.family, version=1,
        justification=arch_in.justification,
        config_json=arch_in.model_dump(mode="json", by_alias=True, exclude={"name", "justification"}),
        summary_json=summary.model_dump(mode="json", by_alias=True), created_by=user_id,
    )
    db.add(arch)
    return arch


def seed(db: Session) -> bool:
    if db.scalar(select(User.id).limit(1)):
        return False

    password = hash_password(settings.demo_password)
    for user_id, name, handle, title, role in USERS:
        db.add(User(
            id=user_id, email=f"{handle}@neurolab.enterprise", display_name=name,
            initials=_initials(name), title=title, role=role, password_hash=password,
            mfa_enabled=role in {"admin", "owner", "reviewer"},
        ))
    db.flush()

    iris = Project(
        id="PRJ-101", name="Clasificación de especies Iris", family="FEEDFORWARD", status="ACTIVE",
        owner_id="USR-207", tags=["demo", "tabular", "clasificación"],
        description="Clasificar flores Iris en tres especies a partir de cuatro medidas del sépalo y el pétalo. "
                    "Proyecto de demostración del flujo completo del MVP (§18).",
    )
    for user_id, role in [("USR-207", "owner"), ("USR-212", "engineer"), ("USR-218", "reviewer"), ("USR-231", "reader")]:
        iris.members.append(ProjectMember(user_id=user_id, role=role))
    db.add(iris)

    # Proyecto ajeno a la usuaria demo: comprueba el aislamiento entre proyectos.
    faults = Project(
        id="PRJ-102", name="Predicción de fallas en compresores", family="RNN", status="DRAFT",
        owner_id="USR-223", tags=["series", "mantenimiento"],
        description="Anticipar fallas de compresores industriales a partir de series de vibración.",
    )
    for user_id, role in [("USR-223", "owner"), ("USR-236", "engineer"), ("USR-244", "reviewer")]:
        faults.members.append(ProjectMember(user_id=user_id, role=role))
    db.add(faults)
    db.flush()

    _add_dataset(db, iris, "iris", "150 flores, 4 medidas en cm y la especie.", iris_csv(), "USR-207")
    _add_architecture(db, iris, {
        "name": "ff-iris", "family": "FEEDFORWARD",
        "justification": "Datos tabulares con pocas características: una red densa pequeña basta.",
        "input": {"features": 4},
        "layers": [
            {"type": "Dense", "units": 16, "activation": "relu"},
            {"type": "Dropout", "dropout": 0.1},
            {"type": "Dense", "units": 8, "activation": "relu"},
            {"type": "Dense", "units": 3, "activation": "softmax"},
        ],
    }, "USR-207")
    _add_architecture(db, faults, {
        "name": "lstm-vibracion", "family": "RNN",
        "justification": "Las fallas dependen de la evolución temporal de la vibración.",
        "input": {"timesteps": 50, "seqFeatures": 6},
        "layers": [
            {"type": "LSTM", "units": 32, "activation": "tanh"},
            {"type": "Dense", "units": 1, "activation": "sigmoid"},
        ],
    }, "USR-223")
    audit.record(db, "system", "seed.demo", "project", iris.id, iris.id)
    db.commit()
    return True


if __name__ == "__main__":
    migrate()
    with SessionLocal() as session:
        print("Datos demo creados." if seed(session) else "La base ya tenía datos; no se modificó.")
