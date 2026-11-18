<#
Compilacion local del portable Personalizado. Iniciar desde CompilarPortable.bat.
Origen: ZIP de GitHub descomprimido manualmente en CitaHelper\Proyecto.
Compila sin conexion a GitHub y sin descargar Camoufox ni FPGen.
#>
param([switch]$Recompilar, [string]$Proyecto)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

function Avisar([string]$mensaje) {
    Write-Host ('[CitaHelper] ' + $mensaje)
}

function EjecutarPython([string]$python, [string[]]$argumentos) {
    & $python @argumentos
    if ($LASTEXITCODE -ne 0) {
        throw ('Python termino con error ' + $LASTEXITCODE + ': ' + $argumentos[0])
    }
}

function LocalizarPython([string]$root) {
    $proyecto = Join-Path $root 'Proyecto'
    if (-not (Test-Path -LiteralPath $proyecto -PathType Container)) {
        throw 'No existe la carpeta CitaHelper\Proyecto.'
    }
    $principal = Join-Path $proyecto 'Personalizado-main\.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $principal -PathType Leaf) { return $principal }
    foreach ($dir in @(Get-ChildItem -LiteralPath $proyecto -Directory | Sort-Object Name)) {
        $candidate = Join-Path $dir.FullName '.venv\Scripts\python.exe'
        if (Test-Path -LiteralPath $candidate -PathType Leaf) { return $candidate }
    }
    throw 'No se encontro Python en un entorno .venv dentro de CitaHelper\Proyecto.'
}

function ElegirFuente([string]$root, [string]$requested) {
    $base = Join-Path $root 'Proyecto'
    if (-not (Test-Path -LiteralPath $base -PathType Container)) {
        throw 'Descomprime primero el ZIP de Personalizado en CitaHelper\Proyecto.'
    }
    if ($requested) {
        $candidate = (Resolve-Path -LiteralPath $requested -ErrorAction Stop).ProviderPath
        if (-not $candidate.StartsWith($base + '\', [StringComparison]::OrdinalIgnoreCase)) {
            throw 'La fuente debe estar dentro de CitaHelper\Proyecto.'
        }
    } else {
        # Never use the stale source inside the permanent .venv holder.
        $sources = @(Get-ChildItem -LiteralPath $base -Directory | Where-Object {
            -not (Test-Path (Join-Path $_.FullName '.venv')) -and
            (Test-Path (Join-Path $_.FullName 'scripts\build_desktop_app.py')) -and
            (Test-Path (Join-Path $_.FullName 'uv.lock'))
        } | Sort-Object LastWriteTime -Descending)
        if ($sources.Count -eq 0) {
            throw 'No hay fuente nueva. Descomprime el ZIP main en una carpeta NUEVA dentro de CitaHelper\Proyecto.'
        }
        $candidate = $sources[0].FullName
    }
    if (-not (Test-Path (Join-Path $candidate 'app\version.py'))) {
        throw 'El ZIP extraido no tiene la estructura esperada.'
    }
    if ((Get-Item -LiteralPath $candidate -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'La carpeta fuente no puede ser un enlace.'
    }
    return $candidate
}

function CopiarFuentes([string]$fromRoot, [string]$toRoot) {
    New-Item -ItemType Directory -Path $toRoot -ErrorAction Stop | Out-Null
    foreach ($name in @('app','scripts','catalogs','tests','.github')) {
        $from = Join-Path $fromRoot $name
        if (-not (Test-Path -LiteralPath $from -PathType Container)) {
            throw ('Falta la carpeta fuente: ' + $name)
        }
        Copy-Item -LiteralPath $from -Destination (Join-Path $toRoot $name) -Recurse -ErrorAction Stop
    }
    foreach ($name in @('pyproject.toml','uv.lock','README.md','README.es.md','README.ru.md',
                         'CHANGELOG.md','LICENSE')) {
        $from = Join-Path $fromRoot $name
        if (-not (Test-Path -LiteralPath $from -PathType Leaf)) {
            throw ('Falta un archivo fuente: ' + $name)
        }
        Copy-Item -LiteralPath $from -Destination (Join-Path $toRoot $name) -ErrorAction Stop
    }
    if ((Test-Path (Join-Path $toRoot 'tasks.yml')) -or
        (Test-Path (Join-Path $toRoot 'data'))) {
        throw 'No se permite empaquetar perfiles o datos privados.'
    }
}

function ConfirmarZip([string]$path) {
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($path)
    try {
        if ($archive.Entries.Count -lt 20) {
            throw 'El ZIP de codigo esta incompleto.'
        }
        foreach ($entry in $archive.Entries) {
            $name = [string]$entry.FullName
            if ($name.Contains('..') -or $name.Contains('\') -or
                $name.StartsWith('/') -or $name.Contains(':')) {
                throw 'El archivo ZIP contiene rutas no permitidas.'
            }
        }
    } finally {
        $archive.Dispose()
    }
}

function ComprobarPortable([string]$bundle) {
    $exe = Join-Path $bundle 'Cita Extranjeria Helper.exe'
    $browser = Join-Path $bundle '_internal\bundled-browser\camoufox.exe'
    $fpgen = Join-Path $bundle '_internal\fpgen\data\fingerprint-network.json.zst'
    $portable = Join-Path $bundle 'portable.flag'
    foreach ($item in @($exe, $browser, $fpgen, $portable)) {
        if (-not (Test-Path -LiteralPath $item -PathType Leaf)) {
            throw ('El portable no supero la verificacion: ' + $item)
        }
    }
    $data = Join-Path $bundle 'data'
    if (-not (Test-Path -LiteralPath $data -PathType Container)) {
        New-Item -ItemType Directory -Path $data -Force | Out-Null
    }
    if (@(Get-ChildItem -LiteralPath $data -Force).Count -gt 0) {
        throw 'El paquete recien compilado no debe contener datos privados.'
    }
    if (Test-Path -LiteralPath (Join-Path $bundle 'tasks.yml')) {
        throw 'El paquete contiene un archivo de perfiles privado.'
    }
}

try {
    if (-not [Environment]::OSVersion.Platform.ToString().StartsWith('Win')) {
        throw 'El BAT solo puede compilar el portable en Windows.'
    }
    if (-not $env:SystemDrive) { throw 'No se pudo determinar el disco del sistema.' }
    $root = Join-Path $env:SystemDrive 'CitaHelper'
    if (-not (Test-Path -LiteralPath $root -PathType Container)) {
        throw ('No existe la carpeta raiz: ' + $root)
    }

    $manualSource = ElegirFuente $root $Proyecto
    Avisar ('Fuente manual: ' + $manualSource)
    $python = LocalizarPython $root
    Avisar ('Python local: ' + $python)
    $env:UV_OFFLINE = '1'
    $env:PIP_NO_INDEX = '1'
    $env:PYTHONNOUSERSITE = '1'
    $env:PYTHONUTF8 = '1'
    # Control de versiones offline antes de generar temporales o compilar.
    $guard = Join-Path $manualSource 'scripts\check_local_dependencies.py'
    if (-not (Test-Path -LiteralPath $guard -PathType Leaf)) {
        throw 'Falta scripts\check_local_dependencies.py en el ZIP.'
    }
    EjecutarPython $python @($guard, (Join-Path $manualSource 'uv.lock'))
    # Ninguna llamada a ensure_fpgen_model ni al downloader Camoufox.
    $offlineCheck = @'
from pathlib import Path
import hashlib
import PyInstaller, PySide6, playwright, camoufox
from camoufox.pkgman import camoufox_path
from camoufox.fpgen_model import fpgen_data_dir, PIN, STAMP
p = Path(camoufox_path(download_if_missing=False))
assert (p / 'camoufox.exe').is_file(), 'Falta Camoufox local'
assert (p / 'application.ini').is_file(), 'Falta application.ini'
m = fpgen_data_dir()
assert (m / STAMP).is_file(), 'Falta el marcador de FPGen'
for name, digest in PIN['file_sha256'].items():
    f = m / name
    assert f.is_file(), 'Falta FPGen: ' + name
    with f.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == digest, 'Hash FPGen incorrecto: ' + name
print('Camoufox, FPGen y dependencias: disponibles SIN descargar.')
'@
    EjecutarPython $python @('-c', $offlineCheck)

    $builds = Join-Path $root 'Compilaciones'
    $ready = Join-Path $builds 'Cita Extranjeria Helper - Personalizado'
    foreach ($folder in @($root,$builds,$ready)) {
        if (Test-Path -LiteralPath $folder) {
            if ((Get-Item -LiteralPath $folder -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw ('Ruta de compilacion enlazada: ' + $folder)
            }
        }
    }
    # From a manually extracted GitHub ZIP. No network request or ZIP download.
    # Copy only source allowlists to a SHORT path for Windows PyInstaller.
    $shortSourceRoot = Join-Path $root 's'
    New-Item -ItemType Directory -Force -Path $builds, $shortSourceRoot | Out-Null
    $buildRoot = Join-Path $shortSourceRoot ('b' + [Guid]::NewGuid().ToString('N').Substring(0,8))
    New-Item -ItemType Directory -Path $buildRoot -ErrorAction Stop | Out-Null
    $source = Join-Path $buildRoot 'src'
    CopiarFuentes $manualSource $source
    if ($source.Length -gt 120) {
        throw 'La ruta de compilacion es demasiado larga.'
    }
    $hashLines = foreach ($file in @(Get-ChildItem -LiteralPath $source -File -Recurse |
                                      Sort-Object FullName)) {
        $file.FullName.Substring($source.Length) + ':' +
        (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash
    }
    $digest = [Security.Cryptography.SHA256]::Create()
    try {
        $hashData = [Text.Encoding]::UTF8.GetBytes(($hashLines -join [char]10))
        $sha = ([BitConverter]::ToString($digest.ComputeHash($hashData))).Replace('-', '').ToLowerInvariant()
    } finally {
        $digest.Dispose()
    }
    Avisar ('Huella local de la fuente: ' + $sha.Substring(0,12))
    Avisar ('Ruta corta de compilacion: ' + $source)
    $marker = Join-Path $ready 'codigo-fuente-local.sha256'
    if (-not $Recompilar -and (Test-Path -LiteralPath $marker -PathType Leaf) -and
        (Test-Path -LiteralPath (Join-Path $ready 'Cita Extranjeria Helper.exe') -PathType Leaf) -and
        (Get-Content -LiteralPath $marker -Raw).Trim() -eq $sha) {
        Avisar 'Esta fuente ya esta compilada. No se repite el trabajo.'
        Remove-Item -LiteralPath $buildRoot -Recurse -Force
        exit 0
    }
    $versionLine = Select-String -LiteralPath (Join-Path $source 'app\version.py') -Pattern '^VERSION\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"' | Select-Object -First 1
    if ($null -eq $versionLine) { throw 'La version de codigo no es valida.' }
    $version = $versionLine.Matches[0].Groups[1].Value
    Avisar ('Compilando aplicacion version ' + $version + '...')

    # Asegura que los import del codigo procedan del commit descargado.
    $env:PYTHONPATH = $source
    Push-Location $source
    try {
        EjecutarPython $python @('scripts/preflight.py', '--metadata-only')
        EjecutarPython $python @('scripts/build_desktop_app.py')
        $bundle = Join-Path $source 'data\dist\Cita Extranjeria Helper'
        if (-not (Test-Path -LiteralPath $bundle -PathType Container)) {
            throw 'No se genero el directorio del portable.'
        }
        # Prueba no interactiva sin usuarios, ni conexion al portal de citas.
        Avisar 'Verificando navegador empaquetado, interfaz y trabajador IPC...'
        EjecutarPython $python @('scripts/verify_bundle.py', $bundle)
        EjecutarPython $python @('scripts/package_release.py', '--platform', 'windows', '--arch', 'x64', '--portable')
    } finally {
        Pop-Location
    }

    $name = 'extranjeria-cita-helper-' + $version + '-windows-x64-portable.zip'
    $zip = Join-Path $source ('data\releases\' + $name)
    $hashfile = $zip + '.sha256'
    if (-not (Test-Path -LiteralPath $zip -PathType Leaf) -or
            -not (Test-Path -LiteralPath $hashfile -PathType Leaf)) {
        throw 'Falta el ZIP final o su suma SHA-256.'
    }
    $digest = (Get-FileHash -Algorithm SHA256 -LiteralPath $zip).Hash.ToLowerInvariant()
    $expected = $digest + '  ' + $name
    if ((Get-Content -LiteralPath $hashfile -Raw).TrimEnd() -cne $expected) {
        throw 'La suma SHA-256 del portable no coincide.'
    }

    # Extraer ANTES de tocar la version anterior, sobre el mismo disco.
    $candidateParent = Join-Path $builds ('.preparando-' + $sha.Substring(0, 12) + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 8))
    if (Test-Path -LiteralPath $candidateParent) {
        throw 'Existe una preparacion previa. Revisala antes de volver a ejecutar el BAT.'
    }
    New-Item -ItemType Directory -Path $candidateParent | Out-Null
    Expand-Archive -LiteralPath $zip -DestinationPath $candidateParent -ErrorAction Stop
    $candidate = Join-Path $candidateParent 'Cita Extranjeria Helper'
    ComprobarPortable $candidate
    $digestLine = $sha + [Environment]::NewLine
    [IO.File]::WriteAllText((Join-Path $candidate 'codigo-fuente-local.sha256'), $digestLine)

    # La compilacion previa de CitaHelper (NO el original del Escritorio)
    # conserva datos de usuario en la carpeta data y se mueve al respaldo.
    if (Test-Path -LiteralPath $ready) {
        if (-not (Test-Path -LiteralPath $ready -PathType Container)) {
            throw 'La ruta de salida no es una carpeta. No se modifico nada.'
        }
        $oldData = Join-Path $ready 'data'
        if (Test-Path -LiteralPath $oldData -PathType Container) {
            Avisar 'Verificando que la compilacion anterior este cerrada...'
            $running = @(Get-CimInstance -ClassName Win32_Process -Filter "Name='Cita Extranjeria Helper.exe'" | Where-Object {
                $_.ExecutablePath -and $_.ExecutablePath.StartsWith(
                    $ready + '\', [StringComparison]::OrdinalIgnoreCase)
            })
            if ($running.Count -gt 0) {
                throw 'Cierra el portable compilado anterior antes de conservar sus datos.'
            }
            $migration = Join-Path $source 'scripts\verify_private_migration.py'
            # Verify there are no symlinks or active WAL files BEFORE robocopy.
            EjecutarPython $python @($migration, $oldData, $oldData)
            Avisar 'Conservando perfiles y configuracion de la compilacion anterior...'
            & robocopy.exe $oldData (Join-Path $candidate 'data') /E /XJ /R:1 /W:1 /NFL /NDL /NP
            if ($LASTEXITCODE -ge 8) {
                throw 'No fue posible copiar los datos privados. La version anterior sigue intacta.'
            }
            EjecutarPython $python @($migration, $oldData, (Join-Path $candidate 'data'))
        }
    }

    # El ZIP solo se usa durante el ensamblado y no se conserva duplicado.
    # Conservar un respaldo antes del reemplazo; restaurar si hay error.
    $respaldo = $null
    if (Test-Path -LiteralPath $ready -PathType Container) {
        $folder = Join-Path $builds 'Respaldos'
        New-Item -ItemType Directory -Path $folder -Force | Out-Null
        $respaldo = Join-Path $folder ('Personalizado-' + (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + $sha.Substring(0, 8))
        if (Test-Path -LiteralPath $respaldo) {
            throw 'El nombre de respaldo ya existe; no se sobrescribio nada.'
        }
        Move-Item -LiteralPath $ready -Destination $respaldo -ErrorAction Stop
    }
    try {
        Move-Item -LiteralPath $candidate -Destination $ready -ErrorAction Stop
    } catch {
        if ($respaldo -and (Test-Path -LiteralPath $respaldo) -and
                -not (Test-Path -LiteralPath $ready)) {
            Move-Item -LiteralPath $respaldo -Destination $ready -ErrorAction Stop
        }
        throw 'La instalacion local fallo; se intento restaurar el respaldo.'
    }

    # Borrar exclusivamente temporales del intento que acaba de superar
    # todas las comprobaciones. Nunca borrar fuentes manuales o .venv aqui.
    Remove-Item -LiteralPath $buildRoot -Recurse -Force -ErrorAction Stop
    if (Test-Path -LiteralPath $candidateParent) {
        Remove-Item -LiteralPath $candidateParent -Recurse -Force -ErrorAction Stop
    }
    Avisar 'COMPILACION FINALIZADA.'
    Avisar ('Portable nuevo: ' + $ready)
    if ($respaldo) { Avisar ('Respaldo anterior: ' + $respaldo) }
    Avisar 'ZIP temporal eliminado. El portable original NO se ha modificado.'
    Avisar 'Despues de probar el portable, ejecuta CompilarPortable.bat /limpiar.'
    exit 0
} catch {
    Write-Host ('[CitaHelper] ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host '[CitaHelper] No abras ni reemplaces el portable original por ahora.' -ForegroundColor Yellow
    exit 1
}
