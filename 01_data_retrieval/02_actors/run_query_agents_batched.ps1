<#
.SYNOPSIS
  Runs query_agents.R in bounded-index blocks, restarting the Rscript
  process between blocks.

.DESCRIPTION
  query_agents.R uses the same SPARQL/RCurl/XML client as query_editions.R,
  which leaks native (non-R-heap) memory across a long-running session (see
  run_query_editions_batched.ps1 for the diagnosis: Rscript.exe reached
  ~115 GB of virtual memory and crashed after ~250 network queries in a
  single process). The actors acquisition loops over ~125k distinct actors
  (one SPARQL query each) - far more than the editions run - so it is even
  more exposed to the same crash. Restarting the R process every
  $BlockSize actors resets its virtual memory, while get_start_index() inside
  query_agents.R makes each restart resume exactly where the previous block
  left off.

.PARAMETER FirstIndex
  First actor index of the overall acquisition range (normally 1).

.PARAMETER LastIndex
  Last actor index of the overall acquisition range. Defaults to the actor
  count observed from the current bnf_edition_data_raw.csv (124695 as of
  2026-07-14) - recompute via extract_distinct_actors() if the editions
  dataset changes, and pass a fresh value with -LastIndex.

.PARAMETER BlockSize
  Number of actors processed per Rscript invocation.

.PARAMETER MaxRetries
  How many times to retry a block if Rscript exits with a non-zero code.

.PARAMETER RetryDelaySeconds
  Pause before retrying a failed block, to let system memory recover.

.EXAMPLE
  powershell -File 01_data_retrieval\02_actors\run_query_agents_batched.ps1
#>

param(
  [int]$FirstIndex = 1,
  [int]$LastIndex = 124695,
  [int]$BlockSize = 2000,
  [int]$MaxRetries = 3,
  [int]$RetryDelaySeconds = 30
)

$ErrorActionPreference = "Stop"

$RscriptPath = "C:\Program Files\R\R-4.6.1\bin\Rscript.exe"

if (-not (Test-Path $RscriptPath)) {
  throw "Rscript.exe not found at '$RscriptPath'. Update `$RscriptPath in this script."
}

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $RepoRoot

$ScriptRelPath = "01_data_retrieval/02_actors/query_agents.R"

# Shared across every batch so all of them append to the same sessionInfo file
# instead of each restart creating its own.
$SessionTimestamp = Get-Date -Format "yyyyMMdd_HHmmss"

$blockStart = $FirstIndex

while ($blockStart -le $LastIndex) {
  $blockEnd = [Math]::Min($blockStart + $BlockSize - 1, $LastIndex)
  $isFinalBlock = $blockEnd -ge $LastIndex
  $mergeOutput = if ($isFinalBlock) { "TRUE" } else { "FALSE" }

  Write-Host ""
  Write-Host "==================================================================="
  Write-Host "Block $blockStart-$blockEnd (merge_output=$mergeOutput)"
  Write-Host "==================================================================="

  $attempt = 0
  $success = $false

  while (-not $success -and $attempt -lt $MaxRetries) {
    $attempt++

    if ($attempt -gt 1) {
      Write-Host "Retry $attempt/$MaxRetries for block $blockStart-$blockEnd after $RetryDelaySeconds s..."
      Start-Sleep -Seconds $RetryDelaySeconds
    }

    & $RscriptPath $ScriptRelPath $blockEnd $mergeOutput $SessionTimestamp $LastIndex
    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
      $success = $true
    } else {
      Write-Warning "Block $blockStart-$blockEnd failed (exit code $exitCode), attempt $attempt/$MaxRetries."
    }
  }

  if (-not $success) {
    throw "Block $blockStart-$blockEnd failed after $MaxRetries attempts. Stopping."
  }

  $blockStart = $blockEnd + 1
}

Write-Host ""
Write-Host "All blocks completed successfully (actor indices $FirstIndex-$LastIndex)."
