$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot
$Project = Join-Path $RepoRoot "winui\ImageToPDF.WinUI\ImageToPDF.WinUI.csproj"
$PublishDirectory = Join-Path $RepoRoot "dist\ImageToPDF-WinUI"
$DistDirectory = Join-Path $RepoRoot "dist"

if ($env:OS -ne "Windows_NT") {
    throw "WinUI 3 builds require Windows."
}

Push-Location $RepoRoot
try {
    & python -m pip install -r (Join-Path $RepoRoot "requirements-dev.txt") -r (Join-Path $RepoRoot "requirements-optional.txt")
    if ($LASTEXITCODE -ne 0) { throw "Python dependency setup failed (exit code $LASTEXITCODE)." }
    & python -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw "Python tests failed (exit code $LASTEXITCODE)." }
    & python -m ruff check .
    if ($LASTEXITCODE -ne 0) { throw "Ruff checks failed (exit code $LASTEXITCODE)." }

    & python -m PyInstaller --noconfirm --clean `
        --distpath $DistDirectory `
        --workpath (Join-Path $RepoRoot "build_tmp\worker") `
        (Join-Path $RepoRoot "ConversionWorker.spec")
    if ($LASTEXITCODE -ne 0) { throw "Python worker build failed (exit code $LASTEXITCODE)." }

    # Exercise the frozen worker before it is bundled with the WinUI frontend.
    $SmokeDirectory = Join-Path $env:TEMP ("ImageToPDF-Worker-Smoke-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $SmokeDirectory | Out-Null
    try {
        $SmokeSource = Join-Path $SmokeDirectory "smoke.png"
        $SmokeRequestPath = Join-Path $SmokeDirectory "request.json"
        $SmokeOutput = Join-Path $SmokeDirectory "smoke.pdf"
        & python -c "from PIL import Image; import sys; Image.new('RGB', (16, 16), 'navy').save(sys.argv[1])" $SmokeSource
        if ($LASTEXITCODE -ne 0) { throw "Could not create the worker smoke-test image." }
        $SmokeRequest = @{
            imagePaths = @($SmokeSource)
            outputPath = $SmokeOutput
            options = @{ quality = "original" }
        } | ConvertTo-Json -Compress
        [System.IO.File]::WriteAllText(
            $SmokeRequestPath,
            $SmokeRequest,
            [System.Text.UTF8Encoding]::new($false)
        )
        $WorkerOutput = & (Join-Path $DistDirectory "ImageToPDFWorker.exe") --request $SmokeRequestPath
        $WorkerExitCode = $LASTEXITCODE
        if ($WorkerExitCode -ne 0) {
            throw "Frozen worker smoke test failed (exit code $WorkerExitCode): $($WorkerOutput -join [Environment]::NewLine)"
        }
        $TerminalEvent = $WorkerOutput |
            ForEach-Object { $_ | ConvertFrom-Json } |
            Where-Object { $_.type -eq "completed" } |
            Select-Object -Last 1
        if ($null -eq $TerminalEvent -or -not (Test-Path $SmokeOutput)) {
            throw "Frozen worker smoke test did not produce a completed PDF."
        }
        $PdfBytes = [System.IO.File]::ReadAllBytes($SmokeOutput)
        $PdfHeader = [System.Text.Encoding]::ASCII.GetString($PdfBytes[0..4])
        if ($PdfHeader -ne "%PDF-") { throw "Frozen worker output is not a PDF." }
    }
    finally {
        Remove-Item $SmokeDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }

    if (Test-Path $PublishDirectory) {
        Remove-Item $PublishDirectory -Recurse -Force
    }
    $MSBuildPath = (Get-Command MSBuild.exe -ErrorAction Stop).Source
    $PublishOutput = @(& $MSBuildPath $Project /restore /target:Publish `
        /property:Configuration=Release `
        /property:Platform=x64 `
        /property:RuntimeIdentifier=win-x64 `
        /property:SelfContained=true `
        /property:WindowsAppSDKSelfContained=true `
        "/property:PublishDir=$PublishDirectory\" 2>&1)
    $PublishExitCode = $LASTEXITCODE
    $PublishOutput | ForEach-Object { Write-Host $_ }
    if ($PublishExitCode -ne 0) {
        $PublishDetails = ($PublishOutput | Out-String -Width 3000).Trim()
        if ($PublishDetails.Length -gt 3000) {
            $PublishDetails = $PublishDetails.Substring($PublishDetails.Length - 3000)
        }
        $EncodedPublishDetails = $PublishDetails.Replace("%", "%25") -replace "[\r\n]+", " | "
        Write-Host "::error title=MSBuild publish output::$EncodedPublishDetails"
        if ($env:GITHUB_STEP_SUMMARY) {
            "### MSBuild publish output`n`n````text`n$PublishDetails`n````" |
                Out-File -FilePath $env:GITHUB_STEP_SUMMARY -Append -Encoding utf8
        }
        throw "WinUI publish failed (exit code $PublishExitCode)."
    }

    foreach ($RequiredFile in @("ImageToPDF.WinUI.exe", "ImageToPDFWorker.exe")) {
        if (-not (Test-Path (Join-Path $PublishDirectory $RequiredFile))) {
            throw "Required WinUI package file is missing: $RequiredFile"
        }
    }

    $Version = & python -c "from app_config import VERSION; print(VERSION)"
    if ($LASTEXITCODE -ne 0) { throw "Could not read the application version." }
    $PortableNote = @"
ImageToPDF WinUI portable build v$Version

Extract the complete folder and run ImageToPDF.WinUI.exe.
Keep ImageToPDFWorker.exe and the other files beside the application.
"@
    Set-Content -Path (Join-Path $PublishDirectory "PORTABLE.txt") -Value $PortableNote -Encoding UTF8

    $Archive = Join-Path $DistDirectory "ImageToPDF-v$Version-Windows-x64-WinUI-Portable.zip"
    if (Test-Path $Archive) { Remove-Item $Archive -Force }
    Compress-Archive -Path (Join-Path $PublishDirectory "*") -DestinationPath $Archive -CompressionLevel Optimal
    $Hash = (Get-FileHash -Path $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
    Set-Content -Path (Join-Path $DistDirectory "SHA256SUMS-WinUI.txt") `
        -Value "$Hash  $(Split-Path -Leaf $Archive)" -Encoding ASCII

    Write-Host "WinUI portable package created: $Archive"
}
catch {
    $Details = ($_ | Out-String -Width 3000).Trim() -replace "[\r\n]+", " | "
    if ($Details.Length -gt 3000) { $Details = $Details.Substring(0, 3000) }
    $EncodedDetails = $Details.Replace("%", "%25")
    Write-Host "::error title=WinUI package build failed::$EncodedDetails"
    if ($env:GITHUB_STEP_SUMMARY) {
        "### WinUI package build failed`n`n````text`n$Details`n````" |
            Out-File -FilePath $env:GITHUB_STEP_SUMMARY -Append -Encoding utf8
    }
    throw
}
finally {
    Pop-Location
}
