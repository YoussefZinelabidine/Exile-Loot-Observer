import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.common import gen_models
from backend.common.config import Settings
from backend.common.snapshot_models import Daily, Manifest, Patch

SNAPSHOT = Path(__file__).resolve().parents[2] / "shared" / "fixtures" / "snapshot"


def load(name: str) -> dict:
    return json.loads((SNAPSHOT / name).read_text(encoding="utf-8"))


def test_generated_models_are_up_to_date():
    current = gen_models.OUTPUT.read_text(encoding="utf-8")
    assert current == gen_models.generate_source(), (
        "snapshot_models.py is out of date; run python -m backend.common.gen_models"
    )


@pytest.mark.parametrize(
    ("model", "name"), [(Manifest, "manifest.json"), (Patch, "patch.json"), (Daily, "daily.json")]
)
def test_fixture_snapshot_validates(model, name):
    parsed = model.model_validate(load(name))
    dumped = parsed.model_dump(by_alias=True, exclude_none=True, mode="json")
    assert dumped["schema"] == load(name)["schema"]


def test_schema_field_uses_alias():
    assert Patch.model_fields["schema_"].alias == "schema"
    data = load("patch.json")
    data["unknown_field"] = 1
    with pytest.raises(ValidationError):
        Patch.model_validate(data)  # strict, like the schema


def test_settings_reads_data_dir():
    s = Settings(
        _env_file=None, db_host="h", db_name="n", db_user="u", db_pass="p", data_dir="/tmp/elo-data"
    )
    assert s.data_dir == Path("/tmp/elo-data")
    s2 = Settings(_env_file=None, db_host="h", db_name="n", db_user="u", db_pass="p")
    assert s2.data_dir is None
