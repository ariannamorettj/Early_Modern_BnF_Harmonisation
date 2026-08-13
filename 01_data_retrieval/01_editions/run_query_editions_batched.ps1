<#
.SYNOPSIS
  Runs query_editions.R in bounded-year blocks, restarting the Rscript
  process between blocks.

.DESCRIPTION
  query_editions.R leaks native (non-R-heap) memory across a long-running
  session (observed via the Windows Resource-Exhaustion-Detector: Rscript.exe
  reached ~115 GB of virtual memory after ~250 yearly SPARQL queries, always
  crashing the run around the same point). Restarting the R process every
  $BlockSize years resets its virtual memory and avoids the crash, while
  get_start_year() inside query_editions.R makes each restart resume exactly
  where the previous block left off.

.PARAMETER FirstYear
  First year of the overall acquisition range.

.PARAMETER LastYear
  Last year of the overall acquisition range.

.PARAMETER BlockSize
  Number of years processed per Rscript invocation.

.PARAMETER MaxRetries
  How many times to retry a block if Rscript exits with a non-zero code.

.PARAMETER RetryDelaySeconds
  Pause before retrying a failed block, to let system memory recover.

.EXAMPLE
  powershell -File 01_data_retrieval\01_editions\run_query_editions_batched.ps1
#>

param(
  [int]$FirstYear = 1454,
  [int]$LastYear = 1799,
  [int]$BlockSize = 50,
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

$ScriptRelPath = "01_data_retrieval/01_editions/query_editions.R"

# Shared across every batch so all of them append to the same sessionInfo file
# instead of each restart creating its own.
$SessionTimestamp = Get-Date -Format "yyyyMMdd_HHmmss"

$blockStart = $FirstYear

while ($blockStart -le $LastYear) {
  $blockEnd = [Math]::Min($blockStart + $BlockSize - 1, $LastYear)
  $isFinalBlock = $blockEnd -ge $LastYear
  $compileOutput = if ($isFinalBlock) { "TRUE" } else { "FALSE" }

  Write-Host ""
  Write-Host "==================================================================="
  Write-Host "Block $blockStart-$blockEnd (compile_output=$compileOutput)"
  Write-Host "==================================================================="

  $attempt = 0
  $success = $false

  while (-not $success -and $attempt -lt $MaxRetries) {
    $attempt++

    if ($attempt -gt 1) {
      Write-Host "Retry $attempt/$MaxRetries for block $blockStart-$blockEnd after $RetryDelaySeconds s..."
      Start-Sleep -Seconds $RetryDelaySeconds
    }

    & $RscriptPath $ScriptRelPath $FirstYear $blockEnd $compileOutput $SessionTimestamp $LastYear
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
Write-Host "All blocks completed successfully ($FirstYear-$LastYear)."
