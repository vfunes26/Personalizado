"""Offline, read-only check of the Windows build environment against uv.lock."""
from importlib import metadata
from pathlib import Path
import re
import sys
import tomllib

REQUIRED_PACKAGES = (
    "camoufox", "fpgen", "playwright", "maxminddb", "numpy", "orjson",
    "requests", "pysocks", "platformdirs", "ua-parser", "pyside6-essentials",
    "shiboken6", "pyinstaller", "pyinstaller-hooks-contrib", "pillow",
    "fonttools", "cryptography", "keyring", "sigstore", "pyyaml",
    "certifi", "tzdata",
)


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def locked_versions(lock_path: Path) -> dict[str, set[str]]:
    with lock_path.open("rb") as stream:
        document = tomllib.load(stream)
    versions: dict[str, set[str]] = {}
    for item in document.get("package", ()):
        if item.get("name") and item.get("version"):
            versions.setdefault(normalize(item["name"]), set()).add(str(item["version"]))
    return versions


def verify_environment(lock_path: Path, get_version=metadata.version) -> list[str]:
    versions = locked_versions(lock_path)
    problems: list[str] = []
    for name in REQUIRED_PACKAGES:
        expected = versions.get(normalize(name))
        if not expected:
            problems.append(f"{name}: no aparece fijado en uv.lock")
            continue
        try:
            installed = get_version(name)
        except metadata.PackageNotFoundError:
            problems.append(f"{name}: no esta instalado en la .venv")
            continue
        if installed not in expected:
            problems.append(f"{name}: instalado {installed}; uv.lock: {', '.join(sorted(expected))}")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("Uso: check_local_dependencies.py <uv.lock>", file=sys.stderr)
        return 2
    try:
        problems = verify_environment(Path(argv[1]))
    except (OSError, ValueError, tomllib.TOMLDecodeError) as error:
        print(f"[CitaHelper] No se pudo comprobar uv.lock: {error}", file=sys.stderr)
        return 2
    if problems:
        print("[CitaHelper] ERROR: la .venv no coincide con las dependencias esenciales de uv.lock:")
        for problem in problems:
            print("[CitaHelper] - " + problem)
        print("[CitaHelper] No se instalo ni descargo ningun paquete.")
        return 1
    print(f"[CitaHelper] Dependencias offline: {len(REQUIRED_PACKAGES)} versiones coinciden con uv.lock.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
