"""Métricas de prueba de regresión (M08): R², RMSE y MAE en las unidades del objetivo."""

from types import SimpleNamespace

import numpy as np
import pytest
from sklearn.metrics import r2_score

from workers.training.jobs.runner import _evaluate
from workers.training.pipelines.model_builder import build_model


def test_regression_evaluation_reports_r2_rmse_and_mae():
    rng = np.random.default_rng(7)
    x = rng.normal(size=(40, 3)).astype("float32")
    y = (x @ np.array([2.0, -1.0, 0.5]) * 1000 + 5000).astype("float32")
    model = build_model({"layers": [{"type": "Dense", "units": 1, "activation": "linear"}]},
                        (3,), "regression", "adam", 0.01)
    data = SimpleNamespace(x_test=x, y_test=y)

    result = _evaluate(model, data, "regression")
    test = result["test"]
    predicted = model.predict(x, verbose=0).reshape(-1)

    assert result["task"] == "regression" and "confusionMatrix" not in result
    assert test["mae"] == pytest.approx(np.mean(np.abs(y - predicted)), rel=1e-4)
    assert test["rmse"] == pytest.approx(np.sqrt(np.mean((y - predicted) ** 2)), rel=1e-4)
    assert test["rmse"] == pytest.approx(np.sqrt(test["loss"]), rel=1e-4)  # la pérdida es MSE
    assert test["r2"] == pytest.approx(r2_score(y, predicted), rel=1e-4)
