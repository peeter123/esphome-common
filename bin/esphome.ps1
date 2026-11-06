#!/usr/bin/env pwsh
# Runs ESPHome through uvx, pinned by requirements.txt in the current directory.
# Run from a project root; arguments are forwarded to ESPHome unchanged, and
# ESPHome's exit code is returned.

#region Environment

function Set-CcacheDir {
    # Returns where CCACHE_DIR came from: the caller's environment or the wrapper.
    if ($env:CCACHE_DIR) { return 'env' }
    $env:CCACHE_DIR = Join-Path $HOME '.ccache'
    'wrapper'
}

function Set-TempDir {
    # Native Windows GCC takes its temp dir from TMP/TEMP (GetTempPath), not TMPDIR.
    # Always override: Cygwin login shells already point these at their own temp dirs.
    $tmpDir = Join-Path (Get-Location).Path '.esphome\tmp'
    New-Item -ItemType Directory -Force $tmpDir | Out-Null
    $env:TMPDIR = $env:TMP = $env:TEMP = $tmpDir
}

function Get-ProjectVersion {
    (Get-Date).ToString('yyyy.MM.dd', [System.Globalization.CultureInfo]::InvariantCulture)
}

#endregion

#region Tool cache locations

function Get-EsphomeCacheRoot {
    # ESPHome's default tools cache: platformdirs.user_cache_dir("esphome", appauthor=False).
    if ($env:OS -eq 'Windows_NT') { return Join-Path $env:LOCALAPPDATA 'esphome\Cache' }
    if ($IsMacOS) { return Join-Path $HOME 'Library/Caches/esphome' }
    Join-Path (Get-XdgCacheHome) 'esphome'
}

function Get-UvDefaultCache {
    if ($env:OS -eq 'Windows_NT') { return Join-Path $env:LOCALAPPDATA 'uv\cache' }
    Join-Path (Get-XdgCacheHome) 'uv'
}

function Get-XdgCacheHome {
    if ($env:XDG_CACHE_HOME) { $env:XDG_CACHE_HOME } else { Join-Path $HOME '.cache' }
}

function Get-UvCache {
    # Ask uv which cache uvx will use: UV_CACHE_DIR, then cache-dir from uv.toml or
    # pyproject.toml (discovered from this directory), then the platform default.
    $default = Get-UvDefaultCache
    $path = $null
    if (Get-Command uv -ErrorAction SilentlyContinue) {
        $path = uv --color never cache dir 2>$null
        if ($LASTEXITCODE) { $path = $null }
    }
    $source = if ($env:UV_CACHE_DIR) { 'env' } elseif ($path -and $path -ne $default) { 'config' } else { 'default' }
    if (-not $path) { $path = if ($env:UV_CACHE_DIR) { $env:UV_CACHE_DIR } else { $default } }
    [pscustomobject]@{ Path = $path; Source = $source }
}

#endregion

#region Report
# Written to stderr so stdout (e.g. 'config' output) stays clean. Colour marks
# the source of each value: environment, wrapper, uv config, or default.

$script:UseColor = -not $env:NO_COLOR -and ($env:FORCE_COLOR -or -not [Console]::IsErrorRedirected)
$script:Colors = @{
    env = "$([char]27)[32m"; wrapper = "$([char]27)[36m"; config = "$([char]27)[33m"
    default = "$([char]27)[2m"; rule = "$([char]27)[1m"; off = "$([char]27)[0m"
}

function Write-WrapperLine([string]$Text, [string]$Color) {
    if ($script:UseColor) { $Text = $script:Colors[$Color] + $Text + $script:Colors.off }
    [Console]::Error.WriteLine($Text)
}

function Write-WrapperRule([string]$Title) {
    $line = "---- $Title ".PadRight(80, '-')
    Write-WrapperLine $line 'rule'
}

function Write-WrapperValue([string]$Name, [string]$Value, [string]$Source) {
    Write-WrapperLine ('  {0,-27} {1,-8} {2}' -f $Name, $Source, $Value) $Source
}

function Write-EnvOrDefault([string]$Name, [string]$Default) {
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ($value) { Write-WrapperValue $Name $value 'env' } else { Write-WrapperValue $Name $Default 'default' }
}

function Write-Environment([string]$ProjectVersion, [string]$CcacheSource) {
    $esphomeCache = Get-EsphomeCacheRoot
    $uvCache = Get-UvCache
    Write-WrapperRule 'esphome wrapper'
    Write-WrapperValue 'project_version' $ProjectVersion 'wrapper'
    Write-WrapperValue 'CCACHE_DIR' $env:CCACHE_DIR $CcacheSource
    foreach ($name in 'TMPDIR', 'TMP', 'TEMP') {
        Write-WrapperValue $name ([Environment]::GetEnvironmentVariable($name)) 'wrapper'
    }
    Write-WrapperValue 'UV_CACHE_DIR' $uvCache.Path $uvCache.Source
    Write-EnvOrDefault 'ESPHOME_ESP_IDF_PREFIX' (Join-Path $esphomeCache 'idf')
    Write-EnvOrDefault 'ESPHOME_SDK_NRF_PREFIX' (Join-Path $esphomeCache 'sdk-nrf')
    Write-EnvOrDefault 'ESPHOME_ARDUINO8266_PREFIX' (Join-Path $esphomeCache 'arduino8266')
    Write-WrapperRule 'esphome'
}

#endregion

#region ESPHome

function Invoke-Esphome([string]$ProjectVersion, [object[]]$Arguments) {
    # Leaves ESPHome's exit code in $LASTEXITCODE; returning it would mix it into
    # ESPHome's stdout, which a function passes through as its output.
    # Builds saturate every core; run below normal so the desktop stays responsive.
    # Windows children inherit BelowNormal and Idle, so uv, Python, and the compilers
    # all get it. Restore afterwards: '& esphome.ps1' runs in the caller's process.
    $process = Get-Process -Id $PID
    $originalPriority = $process.PriorityClass
    if ($originalPriority -notin 'Idle', 'BelowNormal') {
        $process.PriorityClass = 'BelowNormal'
    }
    try {
        uvx --with-requirements requirements.txt esphome -s project_version $ProjectVersion @Arguments
    } finally {
        $process.PriorityClass = $originalPriority
    }
}

#endregion

#region Main

$ccacheSource = Set-CcacheDir
Set-TempDir
$projectVersion = Get-ProjectVersion
Write-Environment $projectVersion $ccacheSource
Invoke-Esphome $projectVersion $args
exit $LASTEXITCODE

#endregion
