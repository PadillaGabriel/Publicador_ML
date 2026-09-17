$ErrorActionPreference = "Stop"

$obsolete = Join-Path $PSScriptRoot "backend\migrations\versions\0009_product_technical_attributes.py"

if (Test-Path $obsolete) {
    Remove-Item -LiteralPath $obsolete -Force
    Write-Host "Eliminado: $obsolete"
}
else {
    Write-Host "No existe (sin cambios): $obsolete"
}
