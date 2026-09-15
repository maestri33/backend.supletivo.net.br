<#
.SYNOPSIS
    Asynchronous Post-Commit Sync to Hindsight Memory Server.
.DESCRIPTION
    Runs detached in background (fire-and-forget).
    Reads the last commit's hash and Agent-Session trailer, sending a lightweight checkpoint to Hindsight.
#>
param(
    [string]$HindsightUrl = "http://10.0.1.99:8888"
)

$ErrorActionPreference = 'SilentlyContinue'

try {
    $commitHash = (& git rev-parse HEAD 2>$null).Trim()
    if (-not $commitHash) { exit 0 }

    $commitSubject = (& git log -1 --pretty=%s 2>$null).Trim()
    $agentSession = (& git log -1 --format="%(trailers:key=Agent-Session,valueonly)" 2>$null).Trim()
    $agentModel = (& git log -1 --format="%(trailers:key=Agent-Model,valueonly)" 2>$null).Trim()
    $bankId = (& git log -1 --format="%(trailers:key=Hindsight-Bank,valueonly)" 2>$null).Trim()

    if (-not $bankId) {
        $repoName = (& git rev-parse --show-toplevel 2>$null | Split-Path -Leaf)
        $bankId = if ($repoName) { "coding-agent::$repoName" } else { "v7m" }
    }

    # Se não houver Agent-Session, sincroniza apenas commits que contenham prefixo de agente ou devagent
    if (-not $agentSession -and $commitSubject -notmatch '^(\[agent\]|agent:|fix\(agent\))') {
        exit 0
    }

    $payloadObj = @{
        items = @(
            @{
                content = "Commit Git [$commitHash]: $commitSubject. (Agente: $agentSession, Modelo: $agentModel)"
                context = "git-checkpoint"
                tags = @(
                    "source:git-commit",
                    "commit:$commitHash",
                    "session:$agentSession"
                )
            }
        )
        async = $true
    }

    $jsonBody = $payloadObj | ConvertTo-Json -Depth 5

    # Envio com timeout estrito de 3 segundos
    $requestUri = "$HindsightUrl/v1/default/banks/$bankId/memories"
    $response = Invoke-RestMethod -Uri $requestUri -Method Post -Body $jsonBody -ContentType "application/json" -TimeoutSec 3
} catch {
    # Falha aberta: erro silencioso para nunca travar o desenvolvedor ou o Git
}

exit 0
