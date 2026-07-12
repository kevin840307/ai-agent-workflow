param(
  [switch]$Parallel,
  [string[]]$Case,
  [int]$TimeoutSec = 1200
)
$ErrorActionPreference = "Stop"
$env:QWEN_MOCK = "0"
$argsList = @("scripts/run_real_qwen_unattended_e2e.py", "--timeout", "$TimeoutSec")
if ($Parallel) { $argsList += "--parallel" }
foreach ($item in $Case) { $argsList += @("--case", $item) }
python @argsList
