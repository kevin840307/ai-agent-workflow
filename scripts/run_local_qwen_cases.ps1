param(
  [string[]]$Case = @("all"),
  [ValidateSet("general-auto-development", "adaptive-auto-workflow")]
  [string]$Workflow = "general-auto-development",
  [ValidateSet("qwen", "opencode")]
  [string]$Agent = "qwen",
  [int]$Repeat = 1,
  [int]$TimeoutSec = 900,
  [string]$Output = "reports/local-real-agent-cases",
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Python = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { throw "Python not found in PATH." }

$argsList = @(
  (Join-Path $Root "scripts/run_local_qwen_cases.py"),
  "--agent", $Agent,
  "--workflow", $Workflow,
  "--repeat", $Repeat,
  "--timeout-sec", $TimeoutSec,
  "--output", $Output
)
foreach ($caseId in $Case) { $argsList += @("--case", $caseId) }
if ($DryRun) { $argsList += "--dry-run" }

Push-Location $Root
try {
  & $Python @argsList
  exit $LASTEXITCODE
}
finally {
  Pop-Location
}
