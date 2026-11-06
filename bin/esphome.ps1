#!/usr/bin/env pwsh
# Runs ESPHome through uvx, pinned by requirements.txt in the current directory.
# Run from a project root; arguments are forwarded to ESPHome unchanged, and
# ESPHome's exit code is returned. See Write-Help, or run with --help.

#region Help

function Write-Help {
    $name = Split-Path $PSCommandPath -Leaf
    @"
Usage: $name [ESPHOME ARGUMENTS...]

Runs ESPHome through uvx, at the version pinned in requirements.txt in the
current directory. Run it from a firmware project root. All arguments are
passed to ESPHome unchanged, and ESPHome's exit code is returned. Without
arguments, or with -h or --help first, this help is followed by ESPHome's.

Before starting ESPHome, the wrapper:
  - checks that requirements.txt exists and that uvx is on PATH
  - passes -s project_version YYYY.MM.DD with today's date; add your own
    -s project_version <version> to override it
  - sets CCACHE_DIR to ~/.ccache when it is unset
  - runs ESPHome on a Python within the pinned release's requires-python
    (read from PyPI once per pin), or on `$env:UV_PYTHON when it is set
  - points TMPDIR, TMP and TEMP at .esphome/tmp in the project
  - lowers its priority to below normal for the duration of the build
  - prints a report to stderr: the ESPHome pin, the common revision, ccache,
    and each cache location, tagged with where its value came from
After ESPHome exits, it prints the exit code and the elapsed time.

Report tags:
  env       set in the caller's environment
  wrapper   set by this wrapper
  config    cache-dir from a uv configuration file (uv.toml, pyproject.toml)
  default   unset; ESPHome or uv uses the location shown
  project   read from the project or the common checkout
  found, missing, system
            tool and system checks; a warning follows a problem

Environment:
  CCACHE_DIR                  compiler cache (default: ~/.ccache)
  UV_PYTHON                   Python for ESPHome and ESP-IDF (default: the
                              pinned release's requires-python)
  UV_CACHE_DIR                uv cache holding the ESPHome installation
  ESPHOME_ESP_IDF_PREFIX      ESP-IDF frameworks and toolchains
  ESPHOME_SDK_NRF_PREFIX      nRF52 SDK
  ESPHOME_ARDUINO8266_PREFIX  ESP8266 Arduino core
  FORCE_COLOR                 colour the report even when stderr is redirected
  NO_COLOR                    never colour the report

Examples:
  $name config device.yml
  $name compile device.yml
  $name -s project_version 2026.10.06.1 compile device.yml

See common/README.md for details.

"@
}

#endregion

#region Environment

# uvx runs ESPHome on the newest Python uv finds: uv ignores the upper bound of
# a package's requires-python, and tool runs ignore .python-version files.
# ESPHome creates the ESP-IDF Python environment from its own interpreter, so a
# Python newer than the release supports can fail the first build. The wrapper
# passes the pinned release's requires-python as the --python request instead;
# uv then picks the newest matching interpreter, downloading one if needed.
# The value is cached per pin, so PyPI is asked only when the pin changes.
$script:RequiresPythonCache = '.esphome\requires-python'

function Get-RequiresPython([string]$Version) {
    # requires-python for an ESPHome version from PyPI, or $null.
    try {
        $info = Invoke-RestMethod -TimeoutSec 10 -Uri "https://pypi.org/pypi/esphome/$Version/json"
        if ($info.info.requires_python) { return [string]$info.info.requires_python }
    } catch { }
    $null
}

function Get-Python {
    # The --python request and its source: UV_PYTHON from the caller, else the
    # pin's requires-python. Passed to uvx rather than set in the environment,
    # because '& esphome.ps1' runs in the caller's process.
    if ($env:UV_PYTHON) { return [pscustomobject]@{ Version = $env:UV_PYTHON; Source = 'env' } }
    $pin = Get-EsphomePin
    if (-not $pin) { return [pscustomobject]@{ Version = $null; Source = 'default' } }
    $spec = $null
    if (Test-Path $script:RequiresPythonCache) {
        foreach ($line in Get-Content $script:RequiresPythonCache) {
            $fields = $line -split "`t", 2
            if ($fields.Count -eq 2 -and $fields[0] -eq $pin) { $spec = $fields[1]; break }
        }
    }
    if (-not $spec) {
        $spec = Get-RequiresPython $pin
        if ($spec) {
            New-Item -ItemType Directory -Force (Split-Path $script:RequiresPythonCache) | Out-Null
            Set-Content -Path $script:RequiresPythonCache -Value "$pin`t$spec"
        }
    }
    if ($spec) { return [pscustomobject]@{ Version = $spec; Source = 'project' } }
    [pscustomobject]@{ Version = $null; Source = 'missing' }
}

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

#region Preflight and project

function Test-Preflight {
    # Returns 0 when ESPHome can start, otherwise the exit code to stop with.
    if (-not (Test-Path -PathType Leaf 'requirements.txt')) {
        Write-WrapperError "requirements.txt not found in $((Get-Location).Path); run the wrapper from a project root."
        return 2
    }
    if (-not (Get-Command uvx -ErrorAction SilentlyContinue)) {
        Write-WrapperError 'uvx not found on PATH; install uv (https://docs.astral.sh/uv/).'
        return 127
    }
    0
}

function Get-EsphomePin {
    $match = Select-String -Path 'requirements.txt' -Pattern '^\s*esphome\s*==\s*([^\s;#]+)' |
        Select-Object -First 1
    if ($match) { $match.Matches[0].Groups[1].Value }
}

function Get-CommonRevision {
    # The common checkout this wrapper belongs to: the project's pinned submodule
    # or the canonical sibling clone.
    $commonDir = Split-Path (Split-Path $PSCommandPath)
    $revision = $null
    if (Get-Command git -ErrorAction SilentlyContinue) {
        $revision = git -C $commonDir describe --always --dirty --abbrev=7 2>$null
        if ($LASTEXITCODE) { $revision = $null }
    }
    if (-not $revision) { $revision = 'unknown' }
    "$revision  $commonDir"
}

#endregion

#region Tool cache locations

function Get-XdgCacheHome {
    if ($env:XDG_CACHE_HOME) { $env:XDG_CACHE_HOME } else { Join-Path $HOME '.cache' }
}

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

#region Tool and system checks

function Get-Ccache {
    # ESPHome uses ccache only when a working ccache is on PATH; CCACHE_DIR alone
    # does not enable it.
    $command = Get-Command ccache -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $command) { return $null }
    $version = & $command.Source --version 2>$null | Select-Object -First 1
    "$($version -replace '^ccache version ', '')  $($command.Source)"
}

function Get-PythonInfo([string]$Request) {
    # Version and path of the installed Python that uv selects for the request
    # ($null: no request), or $null when none matches and uvx would download one.
    # Tool runs ignore projects, so this does too.
    if (-not (Get-Command uv -CommandType Application -ErrorAction SilentlyContinue)) { return $null }
    $find = @('python', 'find', '--no-project', '--no-python-downloads')
    if ($Request) { $find += $Request }
    $path = & uv @find 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $path) { return $null }
    $version = & uv @find --show-version 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $version) { $version = 'unknown' }
    "$version  $path"
}

function Get-LongPathsEnabled {
    $key = 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem'
    (Get-ItemProperty $key -Name LongPathsEnabled -ErrorAction SilentlyContinue).LongPathsEnabled -eq 1
}

# ESP-IDF toolchain paths nest about this many characters below the IDF prefix
# (see README), against Windows' 260-character MAX_PATH without long paths.
$script:IdfPathDepth = 245
$script:MaxPath = 260

#endregion

#region Report
# Written to stderr so stdout (e.g. 'config' output) stays clean. Colour marks
# the source of each value: environment, wrapper, uv config, or default.

$script:UseColor = -not $env:NO_COLOR -and ($env:FORCE_COLOR -or -not [Console]::IsErrorRedirected)
$script:Colors = @{
    env = "$([char]27)[32m"; wrapper = "$([char]27)[36m"; config = "$([char]27)[33m"
    default = "$([char]27)[2m"; project = ''; system = ''
    found = "$([char]27)[32m"; missing = "$([char]27)[31m"; warning = "$([char]27)[31m"
    rule = "$([char]27)[1m"; failed = "$([char]27)[1;31m"; off = "$([char]27)[0m"
}

function Write-WrapperLine([string]$Text, [string]$Color) {
    if ($script:UseColor -and $script:Colors[$Color]) {
        $Text = $script:Colors[$Color] + $Text + $script:Colors.off
    }
    [Console]::Error.WriteLine($Text)
}

function Write-WrapperRule([string]$Title, [string]$Color = 'rule') {
    $line = "---- $Title ".PadRight(80, '-')
    Write-WrapperLine $line $Color
}

function Write-WrapperValue([string]$Name, [string]$Value, [string]$Source) {
    Write-WrapperLine ('  {0,-27} {1,-8} {2}' -f $Name, $Source, $Value) $Source
}

function Write-WrapperWarning([string]$Message) {
    Write-WrapperLine "  ! $Message" 'warning'
}

function Write-WrapperError([string]$Message) {
    Write-WrapperLine "esphome wrapper: $Message" 'failed'
}

function Write-EnvOrDefault([string]$Name, [string]$Default) {
    # Returns the effective value.
    $value = [Environment]::GetEnvironmentVariable($Name)
    if ($value) { Write-WrapperValue $Name $value 'env' } else { Write-WrapperValue $Name $Default 'default' }
    if ($value) { $value } else { $Default }
}

function Write-LongPathCheck([string]$IdfPrefix) {
    if ($env:OS -ne 'Windows_NT') { return }
    $enabled = Get-LongPathsEnabled
    Write-WrapperValue 'LongPathsEnabled' $(if ($enabled) { '1' } else { '0' }) 'system'
    $deepest = $IdfPrefix.Length + $script:IdfPathDepth
    if (-not $enabled -and $deepest -gt $script:MaxPath) {
        $maxPrefix = $script:MaxPath - $script:IdfPathDepth
        Write-WrapperWarning ("ESP-IDF paths reach about $deepest characters below this IDF prefix, past " +
            "the $($script:MaxPath)-character limit. Enable LongPathsEnabled or use a prefix of at " +
            "most $maxPrefix characters.")
    }
}

function Write-Environment([string]$ProjectVersion, [string]$CcacheSource, [object]$Python) {
    $esphomeCache = Get-EsphomeCacheRoot
    $uvCache = Get-UvCache
    $pin = Get-EsphomePin
    $ccache = Get-Ccache
    Write-WrapperRule 'esphome wrapper'
    Write-WrapperValue 'project_version' $ProjectVersion 'wrapper'
    if ($pin) {
        Write-WrapperValue 'esphome' $pin 'project'
    } else {
        Write-WrapperValue 'esphome' 'not pinned' 'missing'
        Write-WrapperWarning 'requirements.txt has no esphome==X.Y.Z line; uvx will use the latest release.'
    }
    Write-WrapperValue 'common' (Get-CommonRevision) 'project'
    switch ($Python.Source) {
        'missing' {
            Write-WrapperValue 'UV_PYTHON' 'unknown' 'missing'
            Write-WrapperWarning "Could not read ESPHome $pin's requires-python from PyPI; uvx will pick the newest Python. Set UV_PYTHON to choose one."
        }
        'default' { Write-WrapperValue 'UV_PYTHON' 'uv default' 'default' }
        default { Write-WrapperValue 'UV_PYTHON' $Python.Version $Python.Source }
    }
    $pythonInfo = Get-PythonInfo $Python.Version
    if ($pythonInfo) {
        Write-WrapperValue 'python' $pythonInfo 'found'
    } else {
        Write-WrapperValue 'python' 'no match installed; uv will download one' 'missing'
    }
    if ($ccache) {
        Write-WrapperValue 'ccache' $ccache 'found'
    } else {
        Write-WrapperValue 'ccache' 'not on PATH' 'missing'
        Write-WrapperWarning 'ESPHome builds without a compiler cache; CCACHE_DIR has no effect.'
    }
    Write-WrapperValue 'CCACHE_DIR' $env:CCACHE_DIR $CcacheSource
    foreach ($name in 'TMPDIR', 'TMP', 'TEMP') {
        Write-WrapperValue $name ([Environment]::GetEnvironmentVariable($name)) 'wrapper'
    }
    Write-WrapperValue 'UV_CACHE_DIR' $uvCache.Path $uvCache.Source
    $idfPrefix = Write-EnvOrDefault 'ESPHOME_ESP_IDF_PREFIX' (Join-Path $esphomeCache 'idf')
    Write-LongPathCheck $idfPrefix
    Write-EnvOrDefault 'ESPHOME_SDK_NRF_PREFIX' (Join-Path $esphomeCache 'sdk-nrf') | Out-Null
    Write-EnvOrDefault 'ESPHOME_ARDUINO8266_PREFIX' (Join-Path $esphomeCache 'arduino8266') | Out-Null
    Write-WrapperRule 'esphome'
}

function Format-Duration([TimeSpan]$Duration) {
    $culture = [System.Globalization.CultureInfo]::InvariantCulture
    if ($Duration.TotalSeconds -lt 60) {
        return [string]::Format($culture, '{0:0.0}s', $Duration.TotalSeconds)
    }
    [string]::Format($culture, '{0}m {1:00}s', [int][Math]::Floor($Duration.TotalMinutes), $Duration.Seconds)
}

function Write-Footer([object]$ExitCode, [TimeSpan]$Duration) {
    # $ExitCode is $null when ESPHome was interrupted (Ctrl+C).
    $elapsed = Format-Duration $Duration
    if ($null -eq $ExitCode) {
        Write-WrapperRule "esphome interrupted after $elapsed" 'failed'
    } elseif ($ExitCode -eq 0) {
        Write-WrapperRule "esphome exited 0 after $elapsed"
    } else {
        Write-WrapperRule "esphome exited $ExitCode after $elapsed" 'failed'
    }
}

#endregion

#region ESPHome

function Invoke-Esphome([string]$ProjectVersion, [string]$Python, [object[]]$Arguments) {
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
        $pythonArgs = if ($Python) { @('--python', $Python) } else { @() }
        uvx @pythonArgs --with-requirements requirements.txt esphome -s project_version $ProjectVersion @Arguments
    } finally {
        $process.PriorityClass = $originalPriority
    }
}

#endregion

#region Main

$esphomeArgs = @($args)
if (-not $esphomeArgs.Count) { $esphomeArgs = @('--help') }
if ($esphomeArgs[0] -in '-h', '--help') { Write-Help }
$preflight = Test-Preflight
if ($preflight) { exit $preflight }
$ccacheSource = Set-CcacheDir
Set-TempDir
$python = Get-Python
$projectVersion = Get-ProjectVersion
Write-Environment $projectVersion $ccacheSource $python
$stopwatch = [Diagnostics.Stopwatch]::StartNew()
$exitCode = $null
try {
    Invoke-Esphome $projectVersion $python.Version $esphomeArgs
    $exitCode = $LASTEXITCODE
} finally {
    Write-Footer $exitCode $stopwatch.Elapsed
}
exit $exitCode

#endregion
