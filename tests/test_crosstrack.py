"""Do the three tracks agree? Run before the 2pm merge:  pytest -m crosstrack

These read the other tracks' files, so they catch drift the per-track tests can't.
"""
import importlib.util
import json
import re
import sys

import pytest

from conftest import ROOT

pytestmark = pytest.mark.crosstrack


def load(path, name):
    if str(ROOT / "data") not in sys.path:
        sys.path.append(str(ROOT / "data"))  # appended so backend modules with the same names win
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def frontend_options(select_id):
    html = (ROOT / "frontend/index.html").read_text()
    block = re.search(rf'<select id="{select_id}".*?</select>', html, re.S).group(0)
    return set(re.findall(r'<option value="([^"]+)"', block))


@pytest.fixture(scope="module")
def seed_docs():
    return json.loads((ROOT / "data/sample_memories.json").read_text())


def test_frontend_plants_exist_in_seed_data(seed_docs):
    seeded = {d["plant_id"] for d in seed_docs}
    picker = frontend_options("plant")
    assert picker <= seeded, f"frontend picker plants {sorted(picker - seeded)} have no seed data (seeded: {sorted(seeded)})"


def test_backend_default_plant_is_seeded(seed_docs):
    import main
    default = main.PlanRequest.model_fields["plant_id"].default
    assert default in {d["plant_id"] for d in seed_docs}, f"backend defaults to '{default}', not in seed data"


def test_vector_index_name_matches():
    import config
    data_db = load(ROOT / "data/db.py", "data_db")
    assert config.VECTOR_INDEX == data_db.VECTOR_INDEX, (
        f"backend queries '{config.VECTOR_INDEX}', data creates '{data_db.VECTOR_INDEX}' (set VECTOR_INDEX env or rename)")


def test_db_and_collection_names_match():
    import config
    data_db = load(ROOT / "data/db.py", "data_db")
    assert (config.DB_NAME, config.COLLECTION) == (data_db.DB_NAME, data_db.MEMORIES)


def test_vector_index_declares_backend_filters():
    import inspect
    import memory_store
    src = inspect.getsource(memory_store.MongoStore.search)
    used = set(re.findall(r'"((?:plant_id|metadata\.[a-z_]+))":', src))
    declared = {f["path"] for f in load(ROOT / "data/create_indexes.py", "data_ix").VECTOR_INDEX_DEFINITION["fields"]
                if f["type"] == "filter"}
    assert used <= declared, f"backend filters on {sorted(used - declared)} but the index doesn't declare them"


def test_roles_match(seed_docs):
    roles = {r for d in seed_docs for r in d["metadata"]["access_level"]}
    assert roles <= frontend_options("role"), f"seed roles {sorted(roles)} vs frontend {sorted(frontend_options('role'))}"


def test_seed_docs_match_memory_contract(seed_docs):
    for d in seed_docs:
        assert d["location"]["type"] == "Point"
        lng, lat = d["location"]["coordinates"]
        assert -180 <= lng <= 180 and -90 <= lat <= 90
        assert d["metadata"]["status"] == "active"
        assert isinstance(d["metadata"]["access_level"], list)
