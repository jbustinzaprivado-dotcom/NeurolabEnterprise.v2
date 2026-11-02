import keras
import pytest

from app.modules.architecture import validate_architecture
from app.schemas.architecture import ArchitectureIn
from workers.training.pipelines.model_builder import build_model


def arch(family, layers, **input_):
    return ArchitectureIn.model_validate({"name": "prueba", "family": family, "input": input_, "layers": layers})


CASES = [
    arch("FEEDFORWARD", [
        {"type": "Dense", "units": 16, "activation": "relu"},
        {"type": "BatchNormalization"},
        {"type": "Dropout", "dropout": 0.2},
        {"type": "Dense", "units": 3, "activation": "softmax"},
    ], features=7),
    arch("CNN", [
        {"type": "Conv2D", "filters": 8, "kernelSize": 3, "activation": "relu"},
        {"type": "MaxPooling2D", "poolSize": 2},
        {"type": "Flatten"},
        {"type": "Dense", "units": 10, "activation": "softmax"},
    ], height=28, width=28, channels=1),
    arch("RNN", [
        {"type": "LSTM", "units": 12, "activation": "tanh"},
        {"type": "GRU", "units": 6, "activation": "tanh"},
        {"type": "Dense", "units": 1, "activation": "sigmoid"},
    ], timesteps=20, seqFeatures=5),
]


@pytest.mark.parametrize("config", CASES, ids=lambda c: c.family)
def test_param_count_matches_keras(config):
    summary = validate_architecture(config)
    assert summary.valid, summary.issues
    payload = config.model_dump(mode="json", by_alias=True)
    model = build_model(payload, tuple(summary.input_shape), "classification", "adam", 0.001)
    assert summary.total_params == model.count_params()
    assert summary.output_shape == list(model.output_shape[1:])
    keras.backend.clear_session()


def test_rejects_layer_from_other_family():
    summary = validate_architecture(arch("FEEDFORWARD", [{"type": "LSTM", "units": 8}, {"type": "Dense", "units": 1}]))
    assert not summary.valid
    assert "no es válida para la familia" in summary.issues[0].message


def test_dense_after_conv_requires_flatten():
    summary = validate_architecture(arch("CNN", [
        {"type": "Conv2D", "filters": 4, "kernelSize": 3},
        {"type": "Dense", "units": 2, "activation": "softmax"},
    ], height=8, width=8, channels=1))
    assert not summary.valid
    assert any("Flatten" in issue.message for issue in summary.issues)


def test_kernel_larger_than_input():
    summary = validate_architecture(arch("CNN", [
        {"type": "Conv2D", "filters": 4, "kernelSize": 9},
        {"type": "Flatten"},
        {"type": "Dense", "units": 2, "activation": "softmax"},
    ], height=5, width=5, channels=1))
    assert not summary.valid


def test_out_of_range_units_and_dropout():
    summary = validate_architecture(arch("FEEDFORWARD", [
        {"type": "Dense", "units": 0},
        {"type": "Dropout", "dropout": 0.95},
        {"type": "Dense", "units": 1},
    ], features=3))
    messages = [issue.message for issue in summary.issues]
    assert any("units" in m for m in messages)
    assert any("dropout" in m for m in messages)


def test_output_must_be_dense():
    summary = validate_architecture(arch("FEEDFORWARD", [{"type": "Dense", "units": 4}, {"type": "Dropout", "dropout": 0.1}], features=3))
    assert not summary.valid
    assert "última capa" in summary.issues[-1].message


def test_softmax_single_unit_warns():
    summary = validate_architecture(arch("FEEDFORWARD", [{"type": "Dense", "units": 1, "activation": "softmax"}], features=3))
    assert summary.valid
    assert summary.issues[0].severity == "warning"
