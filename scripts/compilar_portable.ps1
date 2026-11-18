<#
Compilacion local del portable Personalizado. Iniciar desde CompilarPortable.bat.
Origen: GitHub vfunes26/Personalizado, rama main, commit concreto.
NO instala dependencias, NO descarga Camoufox y NO modifica el portable del Escritorio.
#>
param([switch]$Recompilar)
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

    $python = LocalizarPython $root
    Avisar ('Python local: ' + $python)
    $env:UV_OFFLINE = '1'
    $env:PIP_NO_INDEX = '1'
    $env:PYTHONNOUSERSITE = '1'
    $env:PYTHONUTF8 = '1'
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

    # Obtener el identificador del ultimo commit antes de descargar el ZIP.
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $api = 'https://api.github.com/repos/vfunes26/Personalizado/commits/main'
    Avisar 'Consultando el ultimo commit de GitHub...'
    $commit = Invoke-RestMethod -Uri $api -Headers @{
        'User-Agent' = 'Cita-Extranjeria-Helper-Personalizado-Local'
        'Accept' = 'application/vnd.github+json'
    } -TimeoutSec 45
    $sha = [string]$commit.sha
    if ($sha -cnotmatch '^[a-f0-9]{40}$') {
        throw 'GitHub no devolvio un identificador de commit valido.'
    }
    Avisar ('Version del codigo: ' + $sha.Substring(0, 12))

    $builds = Join-Path $root 'Compilaciones'
    $ready = Join-Path $builds 'Cita Extranjeria Helper - Personalizado'
    # Never follow a junction or symlink into the original portable.
    foreach ($folder in @($root, $builds, $ready)) {
        if (Test-Path -LiteralPath $folder) {
            $item = Get-Item -LiteralPath $folder -Force
            if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw ('La ruta es un enlace, no una carpeta local segura: ' + $folder)
            }
        }
    }
    $marker = Join-Path $ready 'codigo-commit.txt'
    if (-not $Recompilar -and (Test-Path -LiteralPath $marker -PathType Leaf) -and
            (Test-Path -LiteralPath (Join-Path $ready 'Cita Extranjeria Helper.exe') -PathType Leaf)) {
        if ((Get-Content -LiteralPath $marker -Raw).Trim() -eq $sha) {
            Avisar 'La compilacion de este commit ya existe. No se descargara otra vez.'
            Avisar ('Portable: ' + $ready)
            exit 0
        }
    }

    $sourceCache = Join-Path $root 'CacheCompilacion\FuentesGitHub'
    $sourceZip = Join-Path $sourceCache ('Personalizado-' + $sha + '.zip')
    $expanded = Join-Path $sourceCache ('Personalizado-' + $sha)
    New-Item -ItemType Directory -Force -Path $sourceCache, $builds | Out-Null
    if (-not (Test-Path -LiteralPath $sourceZip -PathType Leaf)) {
        Avisar 'Descargando solo el codigo fuente (sin navegador ni modelos)...'
        $url = 'https://github.com/vfunes26/Personalizado/archive/' + $sha + '.zip'
        $download = $sourceZip + '.download'
        try {
            Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 180 -OutFile $download
            ConfirmarZip $download
            Move-Item -LiteralPath $download -Destination $sourceZip -ErrorAction Stop
        } finally {
            if (Test-Path -LiteralPath $download) {
                Remove-Item -LiteralPath $download -Force
            }
        }
    }
    ConfirmarZip $sourceZip

    if (-not (Test-Path -LiteralPath $expanded -PathType Container)) {
        New-Item -ItemType Directory -Path $expanded | Out-Null
        try {
            Expand-Archive -LiteralPath $sourceZip -DestinationPath $expanded -ErrorAction Stop
        } catch {
            throw 'No se pudo extraer el codigo de GitHub. La compilacion anterior sigue intacta.'
        }
    }
    $sources = @(Get-ChildItem -LiteralPath $expanded -Directory | Where-Object {
        (Test-Path -LiteralPath (Join-Path $_.FullName 'app\version.py')) -and
        (Test-Path -LiteralPath (Join-Path $_.FullName 'scripts\build_desktop_app.py')) -and
        (Test-Path -LiteralPath (Join-Path $_.FullName 'pyproject.toml'))
    })
    if ($sources.Count -ne 1) {
        throw 'El ZIP no contiene una unica estructura de proyecto valida.'
    }
    $source = $sources[0].FullName
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
    [IO.File]::WriteAllText((Join-Path $candidate 'codigo-commit.txt'), $digestLine)

    # La compilacion previa de CitaHelper (NO el original del Escritorio)
    # conserva datos de usuario en la carpeta data y se mueve al respaldo.
    if (Test-Path -LiteralPath $ready) {
        if (-not (Test-Path -LiteralPath $ready -PathType Container)) {
            throw 'La ruta de salida no es una carpeta. No se modifico nada.'
        }
        $oldData = Join-Path $ready 'data'
        if (Test-Path -LiteralPath $oldData -PathType Container) {
            Avisar 'Conservando perfiles y configuracion de la compilacion anterior...'
            & robocopy.exe $oldData (Join-Path $candidate 'data') /E /XJ /R:1 /W:1 /NFL /NDL /NP
            if ($LASTEXITCODE -ge 8) {
                throw 'No fue posible copiar los datos privados. La version anterior sigue intacta.'
            }
        }
    }

    # Guardar el ZIP verificado antes de cambiar la version anterior.
    $packages = Join-Path $builds ('Paquetes\' + $sha.Substring(0, 12))
    New-Item -ItemType Directory -Force -Path $packages | Out-Null
    Copy-Item -LiteralPath $zip -Destination (Join-Path $packages $name) -ErrorAction Stop
    Copy-Item -LiteralPath $hashfile -Destination (Join-Path $packages ($name + '.sha256')) -ErrorAction Stop

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

    Avisar 'COMPILACION FINALIZADA.'
    Avisar ('Portable nuevo: ' + $ready)
    Avisar ('ZIP: ' + (Join-Path $packages $name))
    if ($respaldo) { Avisar ('Respaldo anterior: ' + $respaldo) }
    Avisar 'El portable original del Escritorio NO se ha modificado.'
    exit 0
} catch {
    Write-Host ('[CitaHelper] ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    Write-Host '[CitaHelper] No abras ni reemplaces el portable original por ahora.' -ForegroundColor Yellow
    exit 1
}
