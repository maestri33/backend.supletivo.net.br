<#
.SYNOPSIS
    Ultralight Agent Checkpoint Runner for Windows (PowerShell / pwsh).
.DESCRIPTION
    Zero-bloat verification of AGENTS.md rules with sub-200ms staged execution.
    Checks:
    1. Legacy brand prevention (v7m, maestri.group)
    2. Cloudflare-First dependency enforcement
    3. Secret leakage detection (Redaction Engine)
    4. PT-BR frontend route convention
#>
[CmdletBinding()]
param (
    [ValidateSet('fast', 'agent', 'ci')]
    [string]$Tier = 'fast',
    [switch]$AllFiles
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$Stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
$RepoRoot = (& git rev-parse --show-toplevel 2>$null)
if (-not $RepoRoot) {
    Write-Error "Not a git repository."
    exit 1
}

# 1. Carregar regras
$RulesDir = Join-Path $PSScriptRoot "rules"
$BrandRulesFile = Join-Path $RulesDir "brand-blacklist.json"
$CloudflareRulesFile = Join-Path $RulesDir "cloudflare-enforcement.json"

$ForbiddenBrands = @('v7m', 'maestri.group')
$IgnoredExtensions = @('.lock', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.ico', '.woff', '.woff2', '.ttf', '.db', '.sqlite3')

if (Test-Path $BrandRulesFile) {
    $BrandConfig = Get-Content -Raw $BrandRulesFile | ConvertFrom-Json
    $ForbiddenBrands = $BrandConfig.forbiddenTerms
    $IgnoredExtensions = $BrandConfig.ignoredFileExtensions
}

$DisallowedPackages = @('@aws-sdk', 'boto3', 'botocore', 'google-cloud-storage', 'firebase-admin')
if (Test-Path $CloudflareRulesFile) {
    $CfConfig = Get-Content -Raw $CloudflareRulesFile | ConvertFrom-Json
    $DisallowedPackages = $CfConfig.disallowedPackages
}

# 2. Obter arquivos a inspecionar
if ($AllFiles -or $Tier -eq 'ci') {
    $Files = & git ls-files
} else {
    $Files = & git diff --cached --name-only --diff-filter=ACM
}

if (-not $Files) {
    $Stopwatch.Stop()
    Write-Host "[Checkpoint] No staged files to inspect. Passed ($($Stopwatch.ElapsedMilliseconds)ms)." -ForegroundColor Green
    exit 0
}

$Violations = [System.Collections.Generic.List[string]]::new()

# 3. Padrões de detecção de segredos (Redaction Guard)
$SecretPatterns = @(
    '(?i)(bearer\s+)[a-zA-Z0-9_\-\.]{25,}',
    'ghp_[a-zA-Z0-9]{36}',
    'ey[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}',
    '-----BEGIN [A-Z ]+ PRIVATE KEY-----'
)

# 4. Executar inspeção por arquivo
foreach ($relPath in $Files) {
    if (-not $relPath) { continue }
    $fullPath = Join-Path $RepoRoot $relPath
    if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) { continue }

    $ext = [System.IO.Path]::GetExtension($relPath).ToLowerInvariant()
    if ($IgnoredExtensions -contains $ext) { continue }

    # Leitura do conteúdo
    try {
        $lines = [System.IO.File]::ReadAllLines($fullPath, [System.Text.Encoding]::UTF8)
    } catch {
        continue
    }

    # A. Checagem de Marcas Proibidas (Regra AGENTS.md)
    # Permite exceção apenas em arquivos de regras do checkpoint
    if ($relPath -notmatch 'tools/checkpoint' -and $relPath -notmatch '\.agent-checkpoint\.json') {
        for ($i = 0; $i -lt $lines.Length; $i++) {
            $line = $lines[$i]
            foreach ($brand in $ForbiddenBrands) {
                if ($line -match "(?i)\b$([regex]::Escape($brand))\b") {
                    $Violations.Add("[${relPath}:$($i + 1)] Prohibited legacy brand detected ('$brand'): $($line.Trim())")
                }
            }
        }
    }

    # B. Checagem de Segredos em Texto Puro (Redaction Gate)
    for ($i = 0; $i -lt $lines.Length; $i++) {
        $line = $lines[$i]
        foreach ($secPat in $SecretPatterns) {
            if ($line -match $secPat) {
                $Violations.Add("[${relPath}:$($i + 1)] Secret or credential exposure pattern detected: [REDACTED]")
            }
        }
    }

    # C. Checagem Cloudflare-First (em package.json / pyproject.toml / requirements)
    $fileName = [System.IO.Path]::GetFileName($relPath)
    if ($fileName -in @('package.json', 'pyproject.toml', 'requirements.txt', 'requirements-dev.txt')) {
        for ($i = 0; $i -lt $lines.Length; $i++) {
            $line = $lines[$i]
            foreach ($pkg in $DisallowedPackages) {
                if ($line -match "(?i)\b$([regex]::Escape($pkg))\b") {
                    $Violations.Add("[${relPath}:$($i + 1)] Cloudflare-First policy violation: '$pkg' detected. Use Cloudflare R2/D1/KV/Workers.")
                }
            }
        }
    }

    # D. Checagem de Rotas PT-BR em Páginas Frontend (Astro/Svelte)
    if ($relPath -match 'src/pages/(?<pageName>[a-zA-Z0-9_-]+)\.(astro|svelte)$') {
        $pageName = $Matches['pageName'].ToLowerInvariant()
        $invalidEnglishRoutes = @('login', 'signup', 'dashboard', 'settings', 'documents', 'exams')
        if ($pageName -in $invalidEnglishRoutes) {
            $Violations.Add("[$relPath] Frontend route must be in PT-BR (e.g., '/autenticacao/login', '/painel'). Found: '/$pageName'")
        }
    }
}

# 5. Se Tier 'agent' ou 'ci': Executar checagens adicionais se disponíveis
if ($Tier -in @('agent', 'ci')) {
    $PkgJson = Join-Path $RepoRoot "package.json"
    if (Test-Path $PkgJson) {
        $PkgContent = Get-Content -Raw $PkgJson | ConvertFrom-Json
        if ($PkgContent.scripts.PSObject.Properties['check-types']) {
            Write-Host "[Checkpoint:Agent] Running check-types..." -ForegroundColor Cyan
            & npm run check-types 2>&1 | Out-Null
            if ($LASTEXITCODE -ne 0) {
                $Violations.Add("[Types] 'npm run check-types' failed.")
            }
        }
    }
}

$Stopwatch.Stop()

# 6. Avaliação final
if ($Violations.Count -gt 0) {
    Write-Host "`n[CHECKPOINT FAILED] $($Violations.Count) violation(s) found in $($Stopwatch.ElapsedMilliseconds)ms:" -ForegroundColor Red
    foreach ($v in $Violations) {
        Write-Host " - $v" -ForegroundColor Yellow
    }
    Write-Host "`nConsulte c:\rep\AGENTS.md para diretrizes de conformidade.`n" -ForegroundColor Red
    exit 1
}

Write-Host "[CHECKPOINT PASSED] Tier '$Tier' passed in $($Stopwatch.ElapsedMilliseconds)ms." -ForegroundColor Green
exit 0
