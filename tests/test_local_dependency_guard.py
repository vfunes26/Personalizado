"""Unit tests for the offline Windows .venv and uv.lock version gate."""
import importlib.util
from pathlib import Path

GUARD = Path(__file__).resolve().parents[1] / "scripts" / "check_local_dependencies.py"
SPEC = importlib.util.spec_from_file_location("offline_guard", GUARD)
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


def create_lock(tmp_path, without=None):
    document = "version = 1\n"
    for package in guard.REQUIRED_PACKAGES:
        if package != without:
            document += f'\n[[package]]\nname = "{package}"\nversion = "1.0"\n'
    target = tmp_path / "uv.lock"
    target.write_text(document, encoding="utf-8")
    return target


def test_exact_versions_pass(tmp_path):
    assert guard.verify_environment(create_lock(tmp_path), lambda name: "1.0") == []


def test_changed_version_blocks_build(tmp_path):
    errors = guard.verify_environment(
        create_lock(tmp_path), lambda name: "0.9" if name == "camoufox" else "1.0")
    assert len(errors) == 1 and "camoufox" in errors[0] and "0.9" in errors[0]


def test_missing_lock_entry_blocks_build(tmp_path):
    errors = guard.verify_environment(create_lock(tmp_path, without="fpgen"), lambda name: "1.0")
    assert len(errors) == 1 and "fpgen" in errors[0]


def test_missing_installed_package_blocks_build(tmp_path):
    def lookup(name):
        if name == "fpgen":
            raise guard.metadata.PackageNotFoundError(name)
        return "1.0"

    errors = guard.verify_environment(create_lock(tmp_path), lookup)
    assert len(errors) == 1 and "fpgen" in errors[0]


def test_normalized_distribution_names():
    assert guard.normalize("PyInstaller_Hooks.Contrib") == "pyinstaller-hooks-contrib"
