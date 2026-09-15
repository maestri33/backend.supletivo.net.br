<#
.SYNOPSIS
    Injects standard RFC 2822 Git Trailers for Agent Session and Rationale.
.DESCRIPTION
    Called by prepare-commit-msg or commit-msg hook.
    Appends Agent-Session, Agent-Harness, Agent-Model, and Hindsight-Bank to the commit message footer.
#>
param(
    [Parameter(Mandatory=$true)]
    [string]$CommitMsgPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path -LiteralPath $CommitMsgPath -PathType Leaf)) {
    exit 0
}

# 1. Detectar se há sessão de agente ativa
$SessionId = $env:ANTIGRAVITY_CONVERSATION_ID
if (-not $SessionId) { $SessionId = $env:AGENT_SESSION_ID }
if (-not $SessionId) { $SessionId = $env:CLAUDE_SESSION_ID }

# Se não estiver definido explicitamente, verificar se estamos em sessão interativa de agente
$Harness = $env:AGENT_HARNESS
if (-not $Harness) {
    if ($env:ANTIGRAVITY_CONVERSATION_ID) { $Harness = "antigravity" }
    elseif ($env:CLAUDE_SESSION_ID) { $Harness = "claude-code" }
    elseif ($env:CURSOR_SESSION_ID) { $Harness = "cursor" }
    else { $Harness = "developer" }
}

$Model = $env:AGENT_MODEL
if (-not $Model) { $Model = "gemini-3.8-flash" }

$BankId = $env:HINDSIGHT_BANK_ID
if (-not $BankId) {
    $repoName = (& git rev-parse --show-toplevel 2>$null | Split-Path -Leaf)
    $BankId = if ($repoName) { "coding-agent::$repoName" } else { "v7m" }
}

# Se não for sessão de agente e nenhuma variável estiver setada, não injeta trailers redundantes
if ($Harness -eq "developer" -and (-not $env:AGENT_SESSION_ID)) {
    exit 0
}

# 2. Montar trailers usando 'git interpret-trailers' nativo
$trailers = @(
    "--trailer", "Agent-Harness: $Harness",
    "--trailer", "Agent-Model: $Model",
    "--trailer", "Hindsight-Bank: $BankId"
)

if ($SessionId) {
    $trailers += @("--trailer", "Agent-Session: $SessionId")
}

if ($env:AGENT_RATIONALE) {
    $trailers += @("--trailer", "Agent-Rationale: $env:AGENT_RATIONALE")
}

& git interpret-trailers --in-place @trailers "$CommitMsgPath"
exit 0
