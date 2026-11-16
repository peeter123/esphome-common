#!/usr/bin/env pwsh
# Runs esphome-preview.py (the Docker-based display preview) with the caller's
# arguments and returns its exit code unchanged. Run from a project root; see
# esphome-preview.py --help.

$script = Join-Path (Split-Path $PSCommandPath) 'esphome-preview.py'
$python = $null
foreach ($candidate in @(@('python3'), @('python'), @('py', '-3'))) {
    $command = Get-Command $candidate[0] -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $command) { continue }
    $prefix = @($candidate | Select-Object -Skip 1)
    & $command.Source @prefix -c 'import sys; sys.exit(sys.version_info < (3, 8))' *> $null
    if ($LASTEXITCODE -eq 0) { $python = @($command.Source) + $prefix; break }
}
if (-not $python) {
    [Console]::Error.WriteLine('esphome-preview: Python 3.8 or later not found on PATH; install Python 3 (https://www.python.org/).')
    exit 127
}
$prefix = @($python | Select-Object -Skip 1)
& $python[0] @prefix $script @args
exit $LASTEXITCODE
