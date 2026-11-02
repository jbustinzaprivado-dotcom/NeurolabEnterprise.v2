"""Regresión de punta a punta: la tarea se publica en el trabajo y M07 la evalúa con R², RMSE y MAE."""

from tests.conftest import ANA
from workers.training.main import process_next_job

API = "/api/v1"


def test_regression_job_is_evaluated_with_regression_metrics(client):
    if client.get(f"{API}/projects/PRJ-031", headers=ANA).json()["status"] == "ARCHIVED":
        assert client.patch(f"{API}/projects/PRJ-031", json={"status": "ACTIVE"}, headers=ANA).status_code == 200
    archs = client.get(f"{API}/projects/PRJ-031/architectures", headers=ANA).json()
    datasets = client.get(f"{API}/projects/PRJ-031/datasets", headers=ANA).json()
    payload = {
        "architectureId": next(a["id"] for a in archs if a["name"] == "ff-precios"),
        "datasetId": next(d["id"] for d in datasets if d["name"] == "viviendas-lima"),
        "targetColumn": "precio_soles", "epochs": 5, "batchSize": 32, "learningRate": 0.01,
    }
    launched = client.post(f"{API}/projects/PRJ-031/training-jobs", json=payload, headers=ANA)
    assert launched.status_code == 202 and launched.json()["task"] == "regression"
    job_id = launched.json()["id"]
    assert process_next_job("worker-regresion") == (job_id, "COMPLETED")

    job = client.get(f"{API}/training-jobs/{job_id}", headers=ANA).json()
    assert job["task"] == "regression" and job["mae"] > 0 and job["valMae"] > 0

    run = next(item for item in client.get(f"{API}/evaluations", headers=ANA).json() if item["jobId"] == job_id)
    assert run["task"] == "regression" and run["target"] == "precio_soles"
    assert run["confusion"] == [] and run["classes"] == []
    assert set(run["testMetrics"]) == {"r2", "rmse", "mae"}
    assert all(point["mae"] is not None and point["valMae"] is not None for point in run["history"])
    assert len(run["history"]) == 5

    # El KPI de accuracy del panel no cuenta trabajos de regresión.
    kpi = next(item for item in client.get(f"{API}/dashboard", headers=ANA).json()["kpis"] if item["id"] == "accuracy")
    assert job_id not in kpi["footnote"]
