# Static syntax check only: never execute the Windows compiler or cleaner.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
foreach ($name in @('scripts/compilar_portable.ps1', 'scripts/limpiar_portable.ps1')) {
    $tokens = $null
    $errors = $null
    $full = Join-Path $root $name
    [System.Management.Automation.Language.Parser]::ParseFile(
        $full, [ref]$tokens, [ref]$errors) | Out-Null
    if ($errors.Count -gt 0) {
        foreach ($problem in $errors) {
            Write-Host ($name + ': ' + $problem.Message) -ForegroundColor Red
        }
        throw ('PowerShell syntax error: ' + $name)
    }
    Write-Host ('PowerShell syntax OK: ' + $name)
}
