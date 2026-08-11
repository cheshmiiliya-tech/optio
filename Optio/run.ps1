<#
    Optio — start the site.

        .\run.ps1              start with the best interpreter available
        .\run.ps1 -Setup       install the requirements first, then start
        .\run.ps1 -Check       report what is installed and stop

    Why this exists: running app.py against an interpreter with no packages
    dies on the first import, nothing binds to port 8000, and the browser
    only says ERR_CONNECTION_REFUSED - which tells you nothing about the
    actual cause. This checks first and says what is wrong in words.
#>

param(
    [switch]$Setup,
    [switch]$Check,
    [int]$Port = 8000
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Required = @("fastapi", "uvicorn", "pandas", "numpy", "scipy", "sklearn", "joblib")
$Optional = @("lightgbm", "matplotlib", "ollama")

function Get-Interpreters {
    $found = @()
    foreach ($tag in @("3.12", "3.11", "3.10")) {
        try {
            $exe = (py -$tag -c "import sys; print(sys.executable)" 2>$null)
            if ($exe) { $found += [pscustomobject]@{ Label = "py -$tag"; Exe = $exe.Trim() } }
        } catch {}
    }
    $c = Get-Command python -ErrorAction SilentlyContinue
    if ($c) { $found += [pscustomobject]@{ Label = "python"; Exe = $c.Source } }
    return $found
}

function Test-Interpreter($exe) {
    $script = "import importlib.util as u,sys;" +
              "req=['fastapi','uvicorn','pandas','numpy','scipy','sklearn','joblib'];" +
              "opt=['lightgbm','matplotlib','ollama'];" +
              "print(sys.version.split()[0]);" +
              "print(','.join(m for m in req if not u.find_spec(m)));" +
              "print(','.join(m for m in opt if u.find_spec(m)))"
    try { $out = & $exe -c $script 2>$null } catch { return $null }
    if (-not $out -or $out.Count -lt 3) { return $null }
    return [pscustomobject]@{
        Version = $out[0]
        Missing = @($out[1] -split ',' | Where-Object { $_ })
        Extras  = @($out[2] -split ',' | Where-Object { $_ })
    }
}

Write-Host ""
Write-Host "  Optio - AI Entertainment Decision System" -ForegroundColor Cyan
Write-Host ""

$candidates = Get-Interpreters
if (-not $candidates) {
    Write-Host "  No Python found. Install Python 3.12 from python.org and try again." -ForegroundColor Red
    exit 1
}

$report = @()
foreach ($c in $candidates) {
    $info = Test-Interpreter $c.Exe
    if ($info) { $report += [pscustomobject]@{ Label = $c.Label; Exe = $c.Exe; Info = $info } }
}

foreach ($r in $report) {
    $state = if ($r.Info.Missing.Count -eq 0) { "ready" } else { "missing: " + ($r.Info.Missing -join ", ") }
    $colour = if ($r.Info.Missing.Count -eq 0) { "Green" } else { "Yellow" }
    Write-Host ("  {0,-10} {1,-8} {2}" -f $r.Label, $r.Info.Version, $state) -ForegroundColor $colour
    if ($r.Info.Extras) { Write-Host ("  {0,-10} {1,-8} also has: {2}" -f "", "", ($r.Info.Extras -join ", ")) -ForegroundColor DarkGray }
}
Write-Host ""

# Prefer a 3.12 that is ready; the saved models were pickled under 3.12 and
# NumPy 2.x, and older NumPy refuses to unpickle them.
$ready = $report | Where-Object { $_.Info.Missing.Count -eq 0 }
$best  = $ready | Where-Object { $_.Info.Version -like "3.12*" } | Select-Object -First 1
if (-not $best) { $best = $ready | Select-Object -First 1 }

if ($Setup -or (-not $best)) {
    $target = $report | Where-Object { $_.Info.Version -like "3.12*" } | Select-Object -First 1
    if (-not $target) { $target = $report | Select-Object -First 1 }

    if (-not $Setup) {
        Write-Host "  Nothing has the packages it needs yet." -ForegroundColor Yellow
        Write-Host "  Installing them into $($target.Label) ($($target.Info.Version))..." -ForegroundColor Yellow
        Write-Host ""
    }
    & $target.Exe -m pip install --upgrade pip
    & $target.Exe -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) {
        Write-Host ""
        Write-Host "  pip failed. Check the internet connection, then run:  .\run.ps1 -Setup" -ForegroundColor Red
        exit 1
    }
    $best = [pscustomobject]@{ Label = $target.Label; Exe = $target.Exe; Info = (Test-Interpreter $target.Exe) }
    Write-Host ""
}

if ($Check) {
    Write-Host "  Would start with: $($best.Label)  ($($best.Info.Version))" -ForegroundColor Cyan
    Write-Host ""
    exit 0
}

if ($best.Info.Version -notlike "3.12*") {
    Write-Host "  Note: starting on $($best.Info.Version). The saved models were built with" -ForegroundColor DarkYellow
    Write-Host "  Python 3.12 and NumPy 2.x, so the classifiers may not load. Everything" -ForegroundColor DarkYellow
    Write-Host "  else works. For the full system:  .\run.ps1 -Setup" -ForegroundColor DarkYellow
    Write-Host ""
}

$busy = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($busy) {
    Write-Host "  Port $Port is already in use by PID $($busy.OwningProcess)." -ForegroundColor Yellow
    Write-Host "  Optio may already be running - try http://127.0.0.1:$Port first." -ForegroundColor Yellow
    Write-Host "  To take the port back:  Stop-Process -Id $($busy.OwningProcess) -Force" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

Write-Host "  Starting with $($best.Label) ($($best.Info.Version))" -ForegroundColor Green
Write-Host "  First run builds a search index over 36,016 items - give it a minute." -ForegroundColor DarkGray
Write-Host ""
Write-Host "  ->  http://127.0.0.1:$Port" -ForegroundColor Cyan
Write-Host "      Ctrl+C here stops it." -ForegroundColor DarkGray
Write-Host ""

& $best.Exe app.py
