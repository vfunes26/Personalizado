<# 
Limpieza opcional DESPUES de abrir y probar el portable Windows.
Uso: CompilarPortable.bat /limpiar
Solo elimina duplicados y fuentes descargadas sin .venv ni datos de usuario.
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Avisar([string]$mensaje) { Write-Host ('[CitaHelper] ' + $mensaje) }

function EliminarSeguro([string]$ruta, [string]$root) {
    if (-not (Test-Path -LiteralPath $ruta)) { return }
    $real = [IO.Path]::GetFullPath($ruta).TrimEnd('\')
    $base = [IO.Path]::GetFullPath($root).TrimEnd('\')
    if (-not $real.StartsWith($base + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw ('Fuera del directorio permitido: ' + $ruta)
    }
    $cursor = $real
    while ($cursor.Length -ge $base.Length) {
        if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw ('No se borran enlaces ni junctions: ' + $cursor)
        }
        if ($cursor -eq $base) { break }
        $cursor = [IO.Path]::GetDirectoryName($cursor)
    }
    if (Test-Path -LiteralPath $real -PathType Container) {
        $links = @(Get-ChildItem -LiteralPath $real -Recurse -Force |
            Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint })
        if ($links.Count -gt 0) {
            throw ('Hay enlaces en el interior. No se borra: ' + $real)
        }
    }
    Remove-Item -LiteralPath $real -Recurse -Force -ErrorAction Stop
    Avisar ('Eliminado: ' + $real)
}

try {
    if (-not $env:SystemDrive) { throw 'No se puede localizar el disco del sistema.' }
    $root = Join-Path $env:SystemDrive 'CitaHelper'
    $portable = Join-Path $root 'Compilaciones\Cita Extranjeria Helper - Personalizado'
    foreach ($required in @('Cita Extranjeria Helper.exe','portable.flag',
        '_internal\bundled-browser\camoufox.exe',
        '_internal\fpgen\data\fingerprint-network.json.zst')) {
        if (-not (Test-Path -LiteralPath (Join-Path $portable $required) -PathType Leaf)) {
            throw ('No se limpia: portable incompleto o ausente. Falta: ' + $required)
        }
    }
    if ((Get-Item -LiteralPath $portable -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
        throw 'La carpeta del portable no puede ser un enlace.'
    }
    Write-Host ''
    Avisar 'Esta limpieza SOLO es adecuada despues de probar que la nueva app abre bien.'
    Avisar 'Conserva: portable, datos privados, .venv, caches UV/Camoufox/FPGen y respaldos.'
    Avisar 'Elimina: ZIP duplicados, temporales y fuentes manuales SIN dependencias.'
    $answer = Read-Host 'Escribe LIMPIAR para ejecutar (otra respuesta cancela)'
    if ($answer -cne 'LIMPIAR') {
        Avisar 'Cancelado: nada eliminado.'
        exit 0
    }
    $compilaciones = Join-Path $root 'Compilaciones'
    $packages = Join-Path $compilaciones 'Paquetes'
    if (Test-Path -LiteralPath $packages -PathType Container) {
        $other = @(Get-ChildItem -LiteralPath $packages -File -Recurse |
            Where-Object { $_.Extension -notin @('.zip','.sha256') })
        if ($other.Count -eq 0) { EliminarSeguro $packages $root }
        else { Avisar 'Paquetes contiene archivos ajenos: se conserva.' }
    }
    foreach ($folder in @(Get-ChildItem -LiteralPath $compilaciones -Directory |
                           Where-Object { $_.Name -like '.preparando-*' })) {
        $private = Join-Path $folder.FullName 'Cita Extranjeria Helper\data'
        if ((Test-Path -LiteralPath $private -PathType Container) -and
            @(Get-ChildItem -LiteralPath $private -Recurse -Force).Count -gt 0) {
            Avisar ('Temporal con datos privados: se conserva ' + $folder.Name)
        } else { EliminarSeguro $folder.FullName $root }
    }
    $stages = Join-Path $root 's'
    if (Test-Path -LiteralPath $stages -PathType Container) {
        foreach ($folder in @(Get-ChildItem -LiteralPath $stages -Directory)) {
            if ($folder.Name -match '^(?:[a-f0-9]{12}|b[a-f0-9]{8})$') {
                $private = Join-Path $folder.FullName 'src\tasks.yml'
                if (Test-Path -LiteralPath $private) {
                    Avisar ('Temporal con perfiles privados: se conserva ' + $folder.Name)
                } else { EliminarSeguro $folder.FullName $root }
            }
        }
    }
    $cache = Join-Path $root 'CacheCompilacion'
    foreach ($name in @('FuentesGitHub','ExtraerFinal16')) {
        $item = Join-Path $cache $name
        if (Test-Path -LiteralPath $item -PathType Container) {
            EliminarSeguro $item $root
        }
    }
    $zip = Join-Path $cache 'Personalizado-final16.zip'
    if (Test-Path -LiteralPath $zip -PathType Leaf) { EliminarSeguro $zip $root }

    $proyecto = Join-Path $root 'Proyecto'
    if (Test-Path -LiteralPath $proyecto -PathType Container) {
        foreach ($folder in @(Get-ChildItem -LiteralPath $proyecto -Directory)) {
            if ($folder.Name -notlike 'Personalizado-*') { continue }
            $venv = Test-Path -LiteralPath (Join-Path $folder.FullName '.venv')
            $private = Test-Path -LiteralPath (Join-Path $folder.FullName 'tasks.yml')
            $data = Test-Path -LiteralPath (Join-Path $folder.FullName 'data')
            $git = Test-Path -LiteralPath (Join-Path $folder.FullName '.git')
            $source = Test-Path -LiteralPath (Join-Path $folder.FullName 'scripts\build_desktop_app.py')
            if ($source -and -not ($venv -or $private -or $data -or $git)) {
                EliminarSeguro $folder.FullName $root
            } else {
                Avisar ('Protegido: ' + $folder.Name + ' (dependencias, datos o carpeta no identificada).')
            }
        }
    }
    Avisar 'Limpieza de duplicados terminada.'
    Avisar ('Para respaldar SOLO el portable, copia: ' + $portable)
    Avisar 'No se elimino .venv, los caches, RespaldosPrivados ni el portable original.'
    exit 0
} catch {
    Write-Host ('[CitaHelper] Limpieza detenida: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
