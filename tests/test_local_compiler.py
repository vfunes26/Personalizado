"""Structural regressions for the opt-in Windows portable build helper.

These tests do NOT execute the BAT, download anything or build Windows packages.
Native packaging and smoke checks are performed by the user after adjustment 16.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_launcher_can_run_from_any_directory_and_finds_citahelper_root():
    launcher = (ROOT / 'CompilarPortable.bat').read_text(encoding='utf-8')
    assert '%SystemDrive%\\CitaHelper' in launcher
    assert '%~dp0scripts\\compilar_portable.ps1' in launcher
    assert '%RAIZ%\\compilar_portable.ps1' in launcher
    assert 'limpiar_portable.ps1' in launcher
    assert '"/limpiar"' in launcher
    assert 'Compilando codigo descomprimido manualmente' in launcher
    assert 'copy /Y "%~f0" "%RAIZ%\\CompilarPortable.bat"' in launcher
    assert 'copy /Y "%~dp0LimpiarPortable.bat" "%RAIZ%\\LimpiarPortable.bat"' in launcher
    assert 'powershell.exe -NoLogo -NoProfile' in launcher
    assert 'if not exist "%CONTROL%"' in launcher
    assert 'rmdir /s' not in launcher.lower()
    assert 'del /f' not in launcher.lower()


def test_native_windows_compiler_refuses_browser_and_model_downloads():
    native = (ROOT / 'scripts/build_native.py').read_text(encoding='utf-8')
    assert 'camoufox_path(download_if_missing=False)' in native
    assert 'hashlib.file_digest' in native
    assert "PIN['file_sha256']" in native
    assert 'ensure_fpgen_model(' not in native
    assert 'python -m camoufox fetch' not in native


def test_compilation_helper_checks_actual_pinned_source_and_dependencies():
    control = (ROOT / 'scripts/compilar_portable.ps1').read_text(encoding='utf-8')
    assert 'https://api.github.com/repos/vfunes26/Personalizado/commits/main' not in control
    assert 'Invoke-WebRequest' not in control
    assert 'Invoke-RestMethod' not in control
    assert 'ElegirFuente $root $Proyecto' in control
    assert 'CopiarFuentes $manualSource $source' in control
    assert 'codigo-fuente-local.sha256' in control
    assert "camoufox_path(download_if_missing=False)" in control
    assert "PIN['file_sha256'].items()" in control
    assert "scripts/verify_bundle.py" in control
    assert "scripts/package_release.py" in control
    assert "Get-FileHash -Algorithm SHA256" in control
    assert "CodigoFuente" not in control  # No blindly trusted stale archive.
    # Avoid MAX_PATH: stage only public code under a short temporary directory.
    assert "$shortSourceRoot = Join-Path $root 's'" in control
    assert "('b' + [Guid]::NewGuid().ToString('N').Substring(0,8))" in control
    assert '$source.Length -gt 120' in control
    assert "'tests','.github'" in control
    assert "Remove-Item -LiteralPath $buildRoot -Recurse -Force" in control
    assert "Copy-Item -LiteralPath $zip -Destination" not in control


def test_helper_verifies_new_build_before_safely_replacing_old_one():
    control = (ROOT / 'scripts/compilar_portable.ps1').read_text(encoding='utf-8')
    assert "ComprobarPortable $candidate" in control
    assert "Join-Path $builds 'Respaldos'" in control
    assert "Move-Item -LiteralPath $ready -Destination $respaldo" in control
    assert "Move-Item -LiteralPath $respaldo -Destination $ready" in control
    assert control.index("ComprobarPortable $candidate") < control.index(
        "Move-Item -LiteralPath $ready -Destination $respaldo")
    assert control.index('Get-FileHash -Algorithm SHA256') < control.index(
        "Move-Item -LiteralPath $ready -Destination $respaldo")
    assert "robocopy.exe $oldData" in control
    assert "/XJ" in control
    assert "[IO.FileAttributes]::ReparsePoint" in control
    assert "Get-ChildItem -LiteralPath $data -Force" in control
    assert "Cita Extranjeria Helper - Personalizado" in control
    assert "Desktop\\16-11-26" not in control
    assert "Remove-Item -LiteralPath $ready" not in control


def test_no_automatic_windows_build_was_enabled():
    actions = (ROOT / '.github/workflows/build-windows-portable.yml').read_text(
        encoding='utf-8')
    assert 'workflow_dispatch:' in actions
    assert 'push:' not in actions


def test_cleanup_runs_separately_after_manual_test_and_preserves_dependencies():
    cleanup = (ROOT / 'scripts/limpiar_portable.ps1').read_text(encoding='utf-8')
    launcher = (ROOT / 'CompilarPortable.bat').read_text(encoding='utf-8')
    assert 'Read-Host' in cleanup
    assert "-cne 'LIMPIAR'" in cleanup
    assert 'Cita Extranjeria Helper.exe' in cleanup
    assert 'portable.flag' in cleanup
    assert 'compilar_portable.ps1' in launcher
    assert 'limpiar_portable.ps1' in launcher
    assert "Join-Path $compilaciones 'Paquetes'" in cleanup
    assert "'FuentesGitHub','ExtraerFinal16'" in cleanup
    assert "'.venv'" in cleanup
    assert "'.git'" in cleanup
    assert "'tasks.yml'" in cleanup
    assert "'.preparando-*'" in cleanup
    assert "Remove-Item -LiteralPath $real" in cleanup
    assert "Remove-Item -LiteralPath $root" not in cleanup
    assert "Remove-Item -LiteralPath $portable" not in cleanup
    assert "RespaldoPrivados" not in cleanup or 'No se elimino .venv' in cleanup


def test_compiler_from_manual_source_is_immune_to_unwanted_private_files():
    control = (ROOT / 'scripts/compilar_portable.ps1').read_text(encoding='utf-8')
    for part in ("'app','scripts','catalogs','tests','.github'",
                 "'pyproject.toml','uv.lock','README.md'"):
        assert part in control
    assert 'CopiarFuentes' in control
    assert "Join-Path $toRoot 'data'" in control
    assert "Join-Path $toRoot 'tasks.yml'" in control
    assert 'No se permite empaquetar perfiles o datos privados.' in control
