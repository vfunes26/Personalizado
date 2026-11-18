<# 
Limpieza opcional DESPUES de abrir y probar el portable Windows.
Uso: CompilarPortable.bat /limpiar
Solo elimina duplicados y fuentes descargadas sin .venv ni datos de usuario.
#>
param([switch]$SoloVistaPrevia)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Avisar([string]$mensaje) { Write-Host ('[CitaHelper] ' + $mensaje) }

# Dos pases: primero solo lectura, despues exclusivamente rutas aprobadas.
$script:VistaPrevia = $true
$script:RutasPrevistas = @{}
$script:ContadorPrevistos = 0

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
    if ($script:VistaPrevia) {
        $script:RutasPrevistas[$real] = $true
        $script:ContadorPrevistos++
        Avisar ('[VISTA PREVIA] Se eliminaria: ' + $real)
        return
    }
    if (-not $script:RutasPrevistas.ContainsKey($real)) {
        Avisar ('PROTEGIDO: ruta no incluida en la vista previa: ' + $real)
        return
    }
    Remove-Item -LiteralPath $real -Recurse -Force -ErrorAction Stop
    Avisar ('Eliminado: ' + $real)
}


# Se puede retirar un respaldo solo cuando no contiene datos exclusivos.
function RespaldoDuplicado([string]$anterior, [string]$actual) {
    if ((Get-Item -LiteralPath $anterior -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { return $false }
    $esperados = @('Cita Extranjeria Helper.exe','LICENSE.txt','portable.flag',
                   'codigo-commit.txt','codigo-fuente-local.sha256','_internal','data')
    if (@(Get-ChildItem -LiteralPath $anterior -Force |
          Where-Object { $_.Name -notin $esperados }).Count -gt 0) { return $false }
    if (@(Get-ChildItem -LiteralPath $anterior -Recurse -Force |
          Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count -gt 0) { return $false }
    $oldData = Join-Path $anterior 'data'
    $newData = Join-Path $actual 'data'
    if (-not (Test-Path -LiteralPath $oldData)) { return $true }
    if (-not (Test-Path -LiteralPath $oldData -PathType Container) -or
        -not (Test-Path -LiteralPath $newData -PathType Container)) { return $false }
    if ((Get-Item -LiteralPath $newData -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { return $false }
    foreach ($archivo in @(Get-ChildItem -LiteralPath $oldData -File -Recurse -Force)) {
        $copia = Join-Path $newData $archivo.FullName.Substring($oldData.Length + 1)
        if (-not (Test-Path -LiteralPath $copia -PathType Leaf)) { return $false }
        if ((Get-Item -LiteralPath $copia -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { return $false }
        if ((Get-FileHash -LiteralPath $archivo.FullName -Algorithm SHA256).Hash -cne
            (Get-FileHash -LiteralPath $copia -Algorithm SHA256).Hash) { return $false }
    }
    return $true
}

# El ZIP descargado de GitHub tiene un conjunto de elementos raiz conocido.
# Si aparecen archivos privados, extraños o enlaces, conservar la carpeta.
function FuenteManualReconocida([string]$folder) {
    if (-not (Test-Path -LiteralPath (Join-Path $folder 'scripts\build_desktop_app.py') -PathType Leaf) -or
        -not (Test-Path -LiteralPath (Join-Path $folder 'uv.lock') -PathType Leaf)) {
        return $false
    }
    foreach ($name in @('.venv','tasks.yml','data','.git','.env')) {
        if (Test-Path -LiteralPath (Join-Path $folder $name)) { return $false }
    }
    $allowed = @(
        '.coderabbit.yaml','.github','.gitignore','AGENTS.md','CHANGELOG.md',
        'CODE_OF_CONDUCT.md','CONTRIBUTING.md','CompilarPortable.bat','LICENSE',
        'LimpiarPortable.bat','README.es.md','README.md','README.ru.md',
        'SECURITY.md','app','catalogs','docs','greptile.json',
        'pyproject.toml','scripts','tests','uv.lock'
    )
    if (@(Get-ChildItem -LiteralPath $folder -Force |
          Where-Object { $_.Name -notin $allowed }).Count -gt 0) { return $false }
    if (@(Get-ChildItem -LiteralPath $folder -Recurse -Force |
          Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count -gt 0) {
        return $false
    }
    return $true
}

# Borrar solo el contenido de Personalizado-final; mantener la carpeta.
function VaciarFuenteManual([string]$root) {
    $proyecto = Join-Path $root 'Proyecto'
    if (-not (Test-Path -LiteralPath $proyecto -PathType Container)) {
        throw 'No existe Proyecto. No se puede preparar Personalizado-final.'
    }
    $folder = Join-Path $proyecto 'Personalizado-final'
    if (-not (Test-Path -LiteralPath $folder)) {
        if ($script:VistaPrevia) {
            Avisar ('[VISTA PREVIA] Se prepararia carpeta vacia: ' + $folder)
        } else {
            New-Item -ItemType Directory -Path $folder -ErrorAction Stop | Out-Null
            Avisar ('Carpeta vacia preparada: ' + $folder)
        }
        return
    }
    if (-not (Test-Path -LiteralPath $folder -PathType Container) -or
        ((Get-Item -LiteralPath $folder -Force).Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        throw 'Personalizado-final no es una carpeta normal.'
    }
    foreach ($nombre in @('.venv','tasks.yml','data','.git','.env')) {
        if (Test-Path -LiteralPath (Join-Path $folder $nombre)) {
            Avisar ('PROTEGIDO Personalizado-final: contiene ' + $nombre)
            return
        }
    }
    $contenido = @(Get-ChildItem -LiteralPath $folder -Force)
    if ($contenido.Count -eq 0) {
        Avisar ('Personalizado-final ya esta vacia: ' + $folder)
        return
    }
    if (-not (FuenteManualReconocida $folder)) {
        Avisar 'PROTEGIDO Personalizado-final: hay archivos ajenos al ZIP o datos privados.'
        return
    }
    foreach ($item in $contenido) { EliminarSeguro $item.FullName $root }
    Avisar ('Personalizado-final VACIA y conservada: ' + $folder)
}

function EjecutarLimpieza([string]$root, [string]$portable) {
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
            if ($folder.Name -notlike 'Personalizado-*' -or $folder.Name -eq 'Personalizado-final') { continue }
            if (FuenteManualReconocida $folder.FullName) {
                EliminarSeguro $folder.FullName $root
            } else {
                Avisar ('PROTEGIDO: ' + $folder.Name + ' (datos, dependencias o archivos ajenos al ZIP).')
            }
        }
    }
    VaciarFuenteManual $root

    $respaldos = Join-Path $compilaciones 'Respaldos'
    if (Test-Path -LiteralPath $respaldos -PathType Container) {
        foreach ($anterior in @(Get-ChildItem -LiteralPath $respaldos -Directory -Force |
                                Where-Object { $_.Name -match '^Personalizado-[0-9]{8}-[0-9]{6}-[a-f0-9]{8}$' })) {
            $duplicado = $false
            try { $duplicado = RespaldoDuplicado $anterior.FullName $portable }
            catch { Avisar ('Respaldo sin verificar: ' + $anterior.Name + ': ' + $_.Exception.Message) }
            if ($duplicado) {
                EliminarSeguro $anterior.FullName $root
            } else {
                Avisar ('Respaldo PROTEGIDO por datos no verificados: ' + $anterior.Name)
            }
        }
        if (@(Get-ChildItem -LiteralPath $respaldos -Force).Count -eq 0) {
            EliminarSeguro $respaldos $root
        }
    }
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
    Avisar 'Conserva: portable actual, datos privados, .venv y caches UV/Camoufox/FPGen.'
    Avisar 'Elimina: temporales, fuentes descargadas y respaldos con datos duplicados.'
    Avisar ''
    Avisar 'VISTA PREVIA: estas son las rutas que se eliminarian.'
    Avisar ('PROTEGIDO portable actual: ' + $portable)
    Avisar ('PROTEGIDO datos privados: ' + (Join-Path $portable 'data'))
    Avisar ('PROTEGIDO .venv: ' + (Join-Path $root 'Proyecto\Personalizado-main\.venv'))
    Avisar ('PROTEGIDO caches UV/Camoufox/FPGen: ' + (Join-Path $root 'CacheCompilacion'))
    Avisar ('PROTEGIDO respaldo privado: ' + (Join-Path $root 'RespaldosPrivados'))
    Avisar 'PROTEGIDO portable original del Escritorio.'
    EjecutarLimpieza $root $portable
    Avisar ('[VISTA PREVIA] Total de rutas que se eliminarian: ' + $script:ContadorPrevistos)
    Avisar 'Los respaldos con datos privados no verificados se conservan.'
    if ($SoloVistaPrevia) {
        Avisar 'Modo SOLO VISTA PREVIA: NO se elimino ningun archivo.'
        exit 0
    }
    $answer = Read-Host 'Escribe LIMPIAR para ejecutar las rutas mostradas (otra respuesta cancela)'
    if ($answer -cne 'LIMPIAR') {
        Avisar 'Cancelado: nada eliminado.'
        exit 0
    }
    $script:VistaPrevia = $false
    EjecutarLimpieza $root $portable
    Avisar 'Limpieza de duplicados terminada.'
    Avisar ('Portable actual: ' + $portable)
    Avisar 'Personalizado-final se conserva vacia cuando solo tenia fuentes reconocidas.'
    Avisar 'No se elimino .venv, caches, RespaldosPrivados ni el portable original.'
    exit 0
} catch {
    Write-Host ('[CitaHelper] Limpieza detenida: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
