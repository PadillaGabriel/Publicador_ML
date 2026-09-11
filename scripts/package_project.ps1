[CmdletBinding()]
param(
    [string]$OutputPath = "artifacts/ml_enterprise_source.zip"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Status {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("OK", "WARNING", "ERROR")]
        [string]$Level,
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    Write-Host ("[{0}] {1}" -f $Level, $Message)
}

function Invoke-CheckedCommand {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Description,
        [Parameter(Mandatory = $true)]
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host ("> {0}" -f $Description)
    & $Command
    if ($LASTEXITCODE -ne 0) {
        throw ("{0} falló con código {1}." -f $Description, $LASTEXITCODE)
    }
    Write-Status "OK" $Description
}


function Get-RelativePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BasePath,
        [Parameter(Mandatory = $true)]
        [string]$TargetPath
    )

    $baseFull = [System.IO.Path]::GetFullPath($BasePath).TrimEnd("\\", "/") + [System.IO.Path]::DirectorySeparatorChar
    $targetFull = [System.IO.Path]::GetFullPath($TargetPath)
    $baseUri = New-Object System.Uri($baseFull)
    $targetUri = New-Object System.Uri($targetFull)
    $relativeUri = $baseUri.MakeRelativeUri($targetUri)
    return [System.Uri]::UnescapeDataString($relativeUri.ToString()).Replace("/", [System.IO.Path]::DirectorySeparatorChar)
}

function Test-ProhibitedRelativePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$RelativePath
    )

    $normalized = $RelativePath.Replace("\", "/").TrimStart("./")
    $segments = $normalized.Split("/", [System.StringSplitOptions]::RemoveEmptyEntries)

    $blockedDirectories = @(
        ".git",
        ".venv",
        "node_modules",
        "dist",
        ".worktrees",
        ".superpowers",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        "tmp",
        "temp",
        "artifacts"
    )

    foreach ($segment in $segments) {
        if ($blockedDirectories -contains $segment) {
            return $true
        }
    }

    $name = if ($segments.Count -gt 0) { $segments[-1] } else { $normalized }

    if ($name -eq ".env" -or $name -like ".env.*") {
        return $true
    }

    if (
        $name -like "*.pyc" -or
        $name -like "*.pyo" -or
        $name -like "*.log" -or
        $name -like "*.tsbuildinfo"
    ) {
        return $true
    }

    return $false
}

function Assert-SingleAlembicHead {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$HeadOutput
    )

    $heads = @($HeadOutput | Where-Object { $_ -match "\(head\)" })
    if ($heads.Count -ne 1) {
        throw ("Se esperaba un único head de Alembic y se detectaron {0}." -f $heads.Count)
    }

    Write-Status "OK" ("Alembic tiene un único head: {0}" -f $heads[0].Trim())
}

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = (Resolve-Path (Join-Path $scriptDirectory "..")).Path
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

if (-not (Test-Path (Join-Path $root ".git") -PathType Container)) {
    Write-Status "ERROR" "No se encontró .git en la raíz esperada."
    exit 1
}
if (-not (Test-Path (Join-Path $backend "app") -PathType Container)) {
    Write-Status "ERROR" "No se encontró backend/app."
    exit 1
}
if (-not (Test-Path (Join-Path $frontend "package.json") -PathType Leaf)) {
    Write-Status "ERROR" "No se encontró frontend/package.json."
    exit 1
}

Push-Location $root
try {
    Write-Status "OK" ("Raíz del proyecto: {0}" -f $root)

    $branch = (& git branch --show-current).Trim()
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo determinar la rama Git actual."
    }
    if ($branch -ne "master") {
        throw ("La rama actual es '{0}'. El paquete definitivo sólo se genera desde master." -f $branch)
    }
    Write-Status "OK" "Rama actual: master"

    $worktreeLines = @(& git worktree list --porcelain)
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo consultar git worktree list."
    }
    $worktreeCount = @($worktreeLines | Where-Object { $_ -like "worktree *" }).Count
    if ($worktreeCount -ne 1) {
        throw ("Se detectaron {0} worktrees. Debe existir únicamente el repositorio principal." -f $worktreeCount)
    }
    Write-Status "OK" "Existe únicamente el worktree principal."

    $status = @(& git status --short)
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo consultar git status."
    }
    if ($status.Count -gt 0) {
        Write-Status "WARNING" ("El working tree contiene {0} cambio(s) local(es). Se empaquetará el estado actual sin descartarlos." -f $status.Count)
    }
    else {
        Write-Status "OK" "Working tree limpio."
    }

    $trackedEnv = @(& git ls-files ".env" "*.env" ".env.*")
    if ($LASTEXITCODE -ne 0) {
        throw "No se pudo revisar archivos .env versionados."
    }
    $unsafeTrackedEnv = @($trackedEnv | Where-Object { $_ -ne ".env.example" })
    if ($unsafeTrackedEnv.Count -gt 0) {
        throw ("Se detectaron archivos de entorno sensibles versionados: {0}" -f ($unsafeTrackedEnv -join ", "))
    }
    Write-Status "OK" "No hay archivos .env sensibles versionados."

    Push-Location $backend
    try {
        Invoke-CheckedCommand "Compilación Python" { python -m compileall app migrations }
        Invoke-CheckedCommand "Suite backend" { python -m pytest }

        Write-Host ""
        Write-Host "> Alembic heads"
        $headOutput = @(& python -m alembic heads)
        if ($LASTEXITCODE -ne 0) {
            throw "alembic heads falló."
        }
        $headOutput | ForEach-Object { Write-Host $_ }
        Assert-SingleAlembicHead -HeadOutput $headOutput
    }
    finally {
        Pop-Location
    }

    Push-Location $frontend
    try {
        $npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
        if ($null -eq $npmCommand) {
            $npmCommand = Get-Command npm -ErrorAction SilentlyContinue
        }
        if ($null -eq $npmCommand) {
            throw "No se encontró npm/npm.cmd."
        }
        if (-not (Test-Path (Join-Path $frontend "node_modules") -PathType Container)) {
            throw "frontend/node_modules no existe. El empaquetador no ejecuta npm install automáticamente."
        }

        Invoke-CheckedCommand "Build frontend" { & $npmCommand.Source run build }
    }
    finally {
        Pop-Location
    }

    $resolvedOutput = if ([System.IO.Path]::IsPathRooted($OutputPath)) {
        [System.IO.Path]::GetFullPath($OutputPath)
    }
    else {
        [System.IO.Path]::GetFullPath((Join-Path $root $OutputPath))
    }

    $outputDirectory = Split-Path -Parent $resolvedOutput
    New-Item -ItemType Directory -Force -Path $outputDirectory | Out-Null

    $staging = Join-Path ([System.IO.Path]::GetTempPath()) ("ml_enterprise_package_{0}" -f [Guid]::NewGuid().ToString("N"))
    $stagedRoot = Join-Path $staging "ml_enterprise_v1"
    New-Item -ItemType Directory -Force -Path $stagedRoot | Out-Null

    try {
        $sourceFiles = Get-ChildItem -LiteralPath $root -Recurse -Force -File
        $copied = 0

        foreach ($file in $sourceFiles) {
            $relative = Get-RelativePath -BasePath $root -TargetPath $file.FullName
            if (Test-ProhibitedRelativePath -RelativePath $relative) {
                continue
            }

            $destination = Join-Path $stagedRoot $relative
            $destinationDirectory = Split-Path -Parent $destination
            New-Item -ItemType Directory -Force -Path $destinationDirectory | Out-Null
            Copy-Item -LiteralPath $file.FullName -Destination $destination -Force
            $copied++
        }

        if ($copied -eq 0) {
            throw "El staging quedó vacío."
        }
        Write-Status "OK" ("Staging creado con {0} archivo(s)." -f $copied)

        if (Test-Path $resolvedOutput -PathType Leaf) {
            Remove-Item -LiteralPath $resolvedOutput -Force
        }
        Compress-Archive -LiteralPath $stagedRoot -DestinationPath $resolvedOutput -CompressionLevel Optimal
        Write-Status "OK" ("ZIP creado: {0}" -f $resolvedOutput)

        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $archive = [System.IO.Compression.ZipFile]::OpenRead($resolvedOutput)
        try {
            $violations = New-Object System.Collections.Generic.List[string]
            foreach ($entry in $archive.Entries) {
                if ([string]::IsNullOrWhiteSpace($entry.Name)) {
                    continue
                }

                $entryPath = $entry.FullName.Replace("\", "/")
                $relativeInPackage = $entryPath
                if ($relativeInPackage.StartsWith("ml_enterprise_v1/")) {
                    $relativeInPackage = $relativeInPackage.Substring("ml_enterprise_v1/".Length)
                }

                if (Test-ProhibitedRelativePath -RelativePath $relativeInPackage) {
                    $violations.Add($entryPath)
                }
            }

            if ($violations.Count -gt 0) {
                throw ("El ZIP contiene archivos prohibidos: {0}" -f (($violations | Select-Object -First 20) -join ", "))
            }
        }
        finally {
            $archive.Dispose()
        }

        Write-Status "OK" "ZIP validado: no contiene secretos, entornos, caches ni builds prohibidos."
    }
    finally {
        if (Test-Path $staging) {
            Remove-Item -LiteralPath $staging -Recurse -Force
        }
    }

    Write-Host ""
    Write-Status "OK" "Empaquetado enterprise finalizado correctamente."
}
catch {
    Write-Host ""
    Write-Status "ERROR" $_.Exception.Message
    exit 1
}
finally {
    Pop-Location
}
