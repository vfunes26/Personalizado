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
    # Avoid passing a path ending in a backslash immediately before a quote.
    assert '-Proyecto "%~dp0."' in launcher
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
    cleaner_bat = (ROOT / 'LimpiarPortable.bat').read_text(encoding='utf-8')
    assert 'copy /Y "%~dp0scripts\\limpiar_portable.ps1"' in cleaner_bat
    assert 'copy /Y "%~dp0CompilarPortable.bat"' in cleaner_bat
    assert 'call "%RAIZ%\\CompilarPortable.bat" /limpiar' in cleaner_bat
    assert 'start "" /D "%RAIZ%" "%RAIZ%\\CompilarPortable.bat" /limpiar' in cleaner_bat
    assert cleaner_bat.index('start ""') < cleaner_bat.index('call "%RAIZ%')
    assert 'python -m' not in cleaner_bat.lower()
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
    # PowerShell 5.1 does not interpret backslashes as string escapes.
    # Avoid doubled separators in StartsWith/TrimEnd comparisons.
    assert "\\\\" not in cleanup
    assert "\\\\" not in (ROOT / 'scripts/compilar_portable.ps1').read_text(encoding='utf-8')


def test_compiler_from_manual_source_is_immune_to_unwanted_private_files():
    control = (ROOT / 'scripts/compilar_portable.ps1').read_text(encoding='utf-8')
    for part in ("'app','scripts','catalogs','tests','.github'",
                 "'pyproject.toml','uv.lock','README.md'"):
        assert part in control
    assert 'CopiarFuentes' in control
    assert "Join-Path $toRoot 'data'" in control
    assert "Join-Path $toRoot 'tasks.yml'" in control
    assert 'No se permite empaquetar perfiles o datos privados.' in control


def test_cleanup_releases_extracted_source_directory_before_removal():
    """Both entry points detach CMD and its PowerShell child from the source dir."""
    cleaner = (ROOT / 'LimpiarPortable.bat').read_text(encoding='utf-8')
    launcher = (ROOT / 'CompilarPortable.bat').read_text(encoding='utf-8')
    assert 'cd /d "%RAIZ%"' in cleaner
    assert 'start "" /D "%RAIZ%" "%RAIZ%\\CompilarPortable.bat" /limpiar' in cleaner
    assert cleaner.index('cd /d "%RAIZ%"') < cleaner.index('start "" /D')
    cleanup_branch = launcher.split('\n:limpiar\n', 1)[1].split('\n:resultado\n', 1)[0]
    assert 'cd /d "%RAIZ%"' in cleanup_branch
    assert cleanup_branch.index('cd /d "%RAIZ%"') < cleanup_branch.index('powershell.exe')


def test_manual_cleanup_preserves_empty_source_container_and_checks_backups():
    cleanup = (ROOT / 'scripts/limpiar_portable.ps1').read_text(encoding='utf-8')
    assert 'function VaciarFuenteManual' in cleanup
    assert "Join-Path $proyecto 'Personalizado-final'" in cleanup
    assert 'VaciarFuenteManual $root' in cleanup
    assert 'foreach ($item in $contenido) { EliminarSeguro $item.FullName $root }' in cleanup
    assert 'function RespaldoDuplicado' in cleanup
    assert 'Get-FileHash -LiteralPath $archivo.FullName -Algorithm SHA256' in cleanup
    assert 'Respaldo PROTEGIDO por datos no verificados' in cleanup
    assert "'Personalizado-final') { continue }" in cleanup


def test_compiler_checks_offline_lock_before_staging_new_build():
    control = (ROOT / 'scripts/compilar_portable.ps1').read_text(encoding='utf-8')
    assert 'check_local_dependencies.py' in control
    assert 'EjecutarPython $python @($guard' in control
    assert control.index('EjecutarPython $python @($guard') < control.index(
        'CopiarFuentes $manualSource $source')
    guard = (ROOT / 'scripts/check_local_dependencies.py').read_text(encoding='utf-8')
    assert 'tomllib.load(stream)' in guard
    assert 'metadata.version' in guard
    assert 'urlopen' not in guard


def test_installed_bundle_integrity_is_checked_before_source_hash_shortcut():
    ps = (ROOT / 'scripts/compilar_portable.ps1').read_text(encoding='utf-8')
    assert "function CrearHuellaPortable" in ps
    assert "function VerificarHuellaPortable" in ps
    assert "CrearHuellaPortable $candidate" in ps
    assert "VerificarHuellaPortable $ready" in ps
    assert "'bundle-esencial.sha256'" in ps
    assert "scripts\\verify_bundle.py'), $ready" in ps
    assert ps.index("VerificarHuellaPortable $ready") < ps.index(
        "Esta fuente ya esta compilada. No se repite el trabajo.")


def test_powershell_parser_in_ci_and_cleanup_regex_not_truncated():
    cleanup = (ROOT / 'scripts/limpiar_portable.ps1').read_text(encoding='utf-8')
    assert "Where-Object { $_.Name -match '^Personalizado-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}$' })) {" in cleanup
    assert cleanup.count("} catch {") == 1
    assert cleanup.rstrip().endswith("    exit 1\\n}".replace("\\n", "\n"))
    action = (ROOT / '.github/workflows/tests.yml').read_text(encoding='utf-8')
    assert 'pwsh -NoProfile -NonInteractive -File scripts/check_powershell_syntax.ps1' in action
    parser = (ROOT / 'scripts/check_powershell_syntax.ps1').read_text(encoding='utf-8')
    assert '[System.Management.Automation.Language.Parser]::ParseFile' in parser


def test_protected_cleanup_previews_before_password_and_only_deletes_approved_paths():
    cleanup = (ROOT / 'scripts/limpiar_portable.ps1').read_text(encoding='utf-8')
    assert 'param([switch]$SoloVistaPrevia)' in cleanup
    assert '$script:VistaPrevia = $true' in cleanup
    assert "Avisar ('[VISTA PREVIA] Se eliminaria: ' + $real)" in cleanup
    assert 'if (-not $script:RutasPrevistas.ContainsKey($real))' in cleanup
    assert 'PROTEGIDO: ruta no incluida en la vista previa' in cleanup
    assert cleanup.count('EjecutarLimpieza $root $portable') == 2
    first = cleanup.index('EjecutarLimpieza $root $portable')
    confirmation = cleanup.index("Read-Host 'Escribe LIMPIAR")
    second = cleanup.rindex('EjecutarLimpieza $root $portable')
    assert first < confirmation < second
    assert cleanup.index('$script:VistaPrevia = $false') > confirmation
    assert 'if ($SoloVistaPrevia)' in cleanup
    assert 'function FuenteManualReconocida' in cleanup
    assert 'bundle-esencial.sha256' in cleanup
    assert "'Personalizado-final') { continue }" in cleanup
    assert 'VaciarFuenteManual $root' in cleanup

def test_cleanup_preview_does_not_claim_to_have_emptied_the_source():
    ps = (ROOT / 'scripts/limpiar_portable.ps1').read_text(encoding='utf-8')
    assert "if ($script:VistaPrevia) {\n        Avisar ('[VISTA PREVIA] Personalizado-final quedaria VACIA" in ps
    assert "Avisar ('Personalizado-final VACIA y conservada: ' + $folder)" in ps
    assert ps.index("if ($script:VistaPrevia) {\n        Avisar ('[VISTA PREVIA] Personalizado-final") < ps.index("function EjecutarLimpieza")
