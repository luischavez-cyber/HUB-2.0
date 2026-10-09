import pytest


@pytest.fixture(autouse=True)
def espacio_temporal(tmp_path, monkeypatch):
    monkeypatch.setenv("CAEPSA_WORKSPACE", str(tmp_path / "workspace"))
    return tmp_path
