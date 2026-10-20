param(
  [ValidateSet('verify', 'smoke', 'analyze', 'reproduce')]
  [string]$Mode = 'verify',
  [string]$PythonPath,
  [string]$OutputRoot,
  [string]$RawRoot,
  [string]$NetLogo,
  [string]$Rscript,
  [string]$JavaPath,
  [int]$Threads = 2
)

$taskCandidates = @()
if ($PythonPath) { $taskCandidates += $PythonPath }
$taskBundledPython = Join-Path $env:USERPROFILE '.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$taskCandidates += $taskBundledPython
$taskPythonCommand = Get-Command python -ErrorAction SilentlyContinue
if ($taskPythonCommand -and $taskPythonCommand.Source -notlike '*WindowsApps*') {
  $taskCandidates += $taskPythonCommand.Source
}
$taskSelectedPython = $null
foreach ($taskCandidate in $taskCandidates) {
  if (Test-Path -LiteralPath $taskCandidate -PathType Leaf) {
    & $taskCandidate -c 'import sys; assert sys.version_info >= (3,10)' 2>$null
    if ($LASTEXITCODE -eq 0) { $taskSelectedPython = $taskCandidate; break }
  }
}
if (-not $taskSelectedPython) {
  throw 'Python 3.10+ was not found. Supply -PythonPath with a working Python executable.'
}
$taskPythonArgs = @('-X', 'utf8', (Join-Path $PSScriptRoot 'run_all.py'), $Mode, '--threads', [string]$Threads)
foreach ($taskOption in @(
  @('--output-root', $OutputRoot), @('--raw-root', $RawRoot),
  @('--netlogo', $NetLogo), @('--rscript', $Rscript), @('--java', $JavaPath)
)) {
  if ($taskOption[1]) { $taskPythonArgs += $taskOption }
}
& $taskSelectedPython @taskPythonArgs
exit $LASTEXITCODE
