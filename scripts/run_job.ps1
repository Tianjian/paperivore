# run_job.ps1 - end-to-end job: model -> mesh -> deck -> solve -> render
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\run_job.ps1 -Job C:\cae\jobs\job-0001
#   powershell -NoProfile -ExecutionPolicy Bypass -File .\run_job.ps1 -Job <dir> -SkipSolve
#
# Why the explicit ExecutionPolicy bypass: unsigned .ps1 is blocked by the default
# Restricted policy on Windows. Agents must not change machine-wide policy; pass it per call.
param(
    [Parameter(Mandatory = $true)][string]$Job,
    [string]$Python = "",
    [string]$MsysBin = "",
    [string]$FreeCAD = "C:\FreeCAD\1.1.4",
    [switch]$SkipSolve = $false,
    [switch]$WithFreeCAD = $false
)

$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'

$repo = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).Path
if (-not $Python) {
    $candidate = Join-Path $repo '_venv_cad\Scripts\python.exe'
    if (Test-Path $candidate) { $Python = $candidate } else { $Python = 'python' }
}
if (-not $MsysBin) {
    $candidate2 = Join-Path $repo 'msys\msys64\ucrt64\bin'
    if (Test-Path $candidate2) { $MsysBin = $candidate2 } else { $MsysBin = 'C:\msys64\ucrt64\bin' }
}
if (Test-Path $MsysBin) { $env:PATH = "$MsysBin;" + $env:PATH }

$Job = (Resolve-Path -LiteralPath $Job).Path
$scripts = $PSScriptRoot

function Invoke-Step([string]$name, [scriptblock]$sb) {
    Write-Host "`n=== $name ===" -ForegroundColor Cyan
    & $sb
    if ($LASTEXITCODE -ne 0) { throw "$name failed (exit $LASTEXITCODE)" }
}

Invoke-Step 'model' { & $Python (Join-Path $scripts 'model.py') --job $Job }
Invoke-Step 'mesh'  { & $Python (Join-Path $scripts 'mesh.py')  --job $Job }
Invoke-Step 'deck'  { & $Python (Join-Path $scripts 'deck.py')  --job $Job }

if (-not $SkipSolve) {
    Write-Host "`n=== solve (calculix) ===" -ForegroundColor Cyan
    Push-Location $Job
    try {
        $env:OMP_NUM_THREADS = '8'
        $env:CCX_NPROC_STIFFNESS = '8'
        # Prefer the 64-bit integer build: MSYS2 ccx.exe 2.23 crashes in PaStiX
        # factorization with 0xC0000005 on Windows; ccx_i8.exe works.
        $solver = Join-Path $MsysBin 'ccx_i8.exe'
        if (-not (Test-Path $solver)) { $solver = Join-Path $MsysBin 'ccx.exe' }
        & $solver -i job
        $solveExit = $LASTEXITCODE
    } finally { Pop-Location }

    if ($solveExit -ne 0) { throw "solver exit code $solveExit" }

    $dat = Join-Path $Job 'job.dat'
    if (Test-Path $dat) {
        $errors = Select-String -Path $dat -Pattern '\*ERROR' -SimpleMatch
        if ($errors) {
            $errors | ForEach-Object { Write-Host $_.Line -ForegroundColor Red }
            throw 'CalculiX reported *ERROR, see job.dat'
        }
    }
    if (-not (Test-Path (Join-Path $Job 'job.frd'))) { throw 'job.frd not produced' }

    Invoke-Step 'render' { & $Python (Join-Path $scripts 'render.py') --job $Job }
}

# Optional: FreeCAD 2D drawing (geometry DXF via TechDraw, then annotate + PDF)
if ($WithFreeCAD) {
    $fcx = Join-Path $FreeCAD 'FreeCADCmd.exe'
    if (-not (Test-Path $fcx)) { throw "FreeCADCmd not found at $fcx (pass -FreeCAD <dir>)" }

    Write-Host "`n=== freecad (TechDraw DXF) ===" -ForegroundColor Cyan
    $env:CAE_JOB = $Job
    $exportScript = Join-Path $scripts 'fc_drawing_export.py'
    # FreeCADCmd parses its own argv, so drive it with -c exec(...) and CAE_JOB.
    & $fcx -c "exec(open(r'$exportScript', encoding='utf-8').read())"
    if ($LASTEXITCODE -ne 0) { throw "FreeCAD export failed (exit $LASTEXITCODE)" }
    $dxf = Join-Path $Job 'freecad\drawing.dxf'
    if (-not (Test-Path $dxf)) { throw 'TechDraw did not produce drawing.dxf' }

    Invoke-Step 'annotate' { & $Python (Join-Path $scripts 'annotate_dxf.py') --job $Job }
}

$result = Join-Path $Job 'result.json'
if (Test-Path $result) {
    Write-Host "`n=== result.json ===" -ForegroundColor Green
    Get-Content $result -Raw
} else {
    Write-Host "`nDONE (solve skipped, no result.json)" -ForegroundColor Yellow
}
