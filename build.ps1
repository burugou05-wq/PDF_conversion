$ErrorActionPreference = "Stop"
& python "$PSScriptRoot\build.py" @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
