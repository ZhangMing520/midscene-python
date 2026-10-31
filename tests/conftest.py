import pytest

from midscene.core.ai_model.env_config import MIDSCENE_RUN_DIR


@pytest.fixture(autouse=True)
def _isolated_run_dir(tmp_path, monkeypatch):
    """Keep dumps/reports/cache out of the repository working tree."""
    monkeypatch.setenv(MIDSCENE_RUN_DIR, str(tmp_path / "midscene_run"))
    yield
