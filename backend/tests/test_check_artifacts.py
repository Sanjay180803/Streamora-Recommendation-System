import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("check_artifacts", REPO_ROOT / "scripts" / "check_artifacts.py")
check_artifacts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(check_artifacts)


@pytest.fixture
def manifest(tmp_path):
    path = tmp_path / "artifacts.json"
    path.write_text(json.dumps({"files": [
        {"path": "model.onnx", "required": True, "purpose": "", "sha256": None},
        {"path": "optional.onnx", "required": False, "purpose": "", "sha256": None},
    ]}))
    return path


def run(manifest, root, *extra):
    return check_artifacts.main(["--manifest", str(manifest), "--root", str(root), *extra])


def test_repository_manifest_lists_the_files_the_backend_loads():
    entries = json.loads((REPO_ROOT / "configs" / "artifacts.json").read_text())["files"]
    required = {Path(e["path"]).name for e in entries if e["required"]}

    import recommender
    assert set(recommender.REQUIRED_DATA_FILES) <= required
    assert "bert4rec_v3.onnx" in required


def test_missing_required_file_fails(manifest, tmp_path):
    assert run(manifest, tmp_path) == 1


def test_missing_optional_file_is_allowed(manifest, tmp_path):
    (tmp_path / "model.onnx").write_bytes(b"weights")
    assert run(manifest, tmp_path) == 0


def test_record_then_verify_checksums(manifest, tmp_path):
    model = tmp_path / "model.onnx"
    model.write_bytes(b"weights")

    assert run(manifest, tmp_path, "--record") == 0
    assert json.loads(manifest.read_text())["files"][0]["sha256"] is not None
    assert run(manifest, tmp_path) == 0

    model.write_bytes(b"tampered")
    assert run(manifest, tmp_path) == 1
