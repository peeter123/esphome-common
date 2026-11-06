#!/usr/bin/env pwsh
if (-not $env:CCACHE_DIR) {
    $env:CCACHE_DIR = Join-Path $HOME '.ccache'
}
# Native Windows GCC takes its temp dir from TMP/TEMP (GetTempPath), not TMPDIR.
# Always override: Cygwin login shells already point these at their own temp dirs.
$tmpDir = Join-Path (Get-Location).Path '.esphome\tmp'
New-Item -ItemType Directory -Force $tmpDir | Out-Null
$env:TMPDIR = $env:TMP = $env:TEMP = $tmpDir
$projectVersion = (Get-Date).ToString('yyyy.MM.dd', [System.Globalization.CultureInfo]::InvariantCulture)
# Builds saturate every core; run below normal so the desktop stays responsive.
# Windows children inherit BelowNormal and Idle, so uv, Python, and the compilers
# all get it. Restore afterwards: '& esphome.ps1' runs in the caller's process.
$process = Get-Process -Id $PID
$originalPriority = $process.PriorityClass
if ($originalPriority -notin 'Idle', 'BelowNormal') {
    $process.PriorityClass = 'BelowNormal'
}
try {
    uvx --with-requirements requirements.txt esphome -s project_version $projectVersion @Args
} finally {
    $process.PriorityClass = $originalPriority
}
exit $LASTEXITCODE
