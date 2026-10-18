$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot
$Project = Join-Path $RepoRoot "winui\ImageToPDF.WinUI\ImageToPDF.WinUI.csproj"
$PublishDirectory = Join-Path $RepoRoot "build_tmp\winui-publish"
$DistDirectory = Join-Path $RepoRoot "dist"

function Assert-X64PeExecutable {
    param([Parameter(Mandatory)][string]$ExecutablePath)

    if (-not (Test-Path -LiteralPath $ExecutablePath -PathType Leaf)) {
        throw "Required executable is missing: $ExecutablePath"
    }

    $Stream = [System.IO.File]::OpenRead($ExecutablePath)
    try {
        $Reader = [System.IO.BinaryReader]::new($Stream, [System.Text.Encoding]::ASCII, $true)
        try {
            if ($Reader.ReadUInt16() -ne 0x5A4D) {
                throw "Invalid DOS/PE signature: $ExecutablePath"
            }

            $Stream.Position = 0x3C
            $PeOffset = $Reader.ReadInt32()
            if ($PeOffset -lt 0 -or $PeOffset -gt ($Stream.Length - 6)) {
                throw "Invalid PE header offset: $ExecutablePath"
            }

            $Stream.Position = $PeOffset
            if ($Reader.ReadUInt32() -ne 0x00004550) {
                throw "Invalid PE signature: $ExecutablePath"
            }

            $Machine = $Reader.ReadUInt16()
            if ($Machine -ne 0x8664) {
                throw ("Expected AMD64 PE machine 0x8664, found 0x{0:X4}: {1}" -f $Machine, $ExecutablePath)
            }
        }
        finally {
            $Reader.Dispose()
        }
    }
    finally {
        $Stream.Dispose()
    }

    Write-Host "Verified x64 PE executable: $ExecutablePath"
}

function Test-WorkerConversion {
    param(
        [Parameter(Mandatory)][string]$WorkerExecutable,
        [Parameter(Mandatory)][string]$Label
    )

    if (-not (Test-Path -LiteralPath $WorkerExecutable -PathType Leaf)) {
        throw "Packaged conversion worker is missing: $WorkerExecutable"
    }

    $SmokeDirectory = Join-Path $env:TEMP ("画像PDF-Worker-" + $Label + "-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $SmokeDirectory -Force | Out-Null
    try {
        $SourceImage = Join-Path $SmokeDirectory "画像 001.png"
        $RequestPath = Join-Path $SmokeDirectory "変換リクエスト.json"
        $OutputPdf = Join-Path $SmokeDirectory "変換結果.pdf"

        & python -c "from PIL import Image; import sys; Image.new('RGB', (37, 53), 'navy').save(sys.argv[1])" $SourceImage
        if ($LASTEXITCODE -ne 0) { throw "Could not create the worker smoke-test image." }

        $Request = @{
            imagePaths = @($SourceImage)
            outputPath = $OutputPdf
            overwrite = $false
            options = @{
                quality = "original"
                pageSize = "A4"
                marginMm = 2
                background = @(255, 255, 255)
                autoRotate = $true
            }
        } | ConvertTo-Json -Compress -Depth 5
        [System.IO.File]::WriteAllText(
            $RequestPath,
            $Request,
            [System.Text.UTF8Encoding]::new($false)
        )

        $WorkerOutput = @(& $WorkerExecutable --request $RequestPath)
        $WorkerExitCode = $LASTEXITCODE
        if ($WorkerExitCode -ne 0) {
            throw "Worker smoke test failed (exit code $WorkerExitCode): $($WorkerOutput -join [Environment]::NewLine)"
        }

        $Events = @($WorkerOutput | ForEach-Object { ConvertFrom-Json -InputObject $_ })
        $CompletedEvent = $Events |
            Where-Object { $_.type -eq "completed" } |
            Select-Object -Last 1
        if ($null -eq $CompletedEvent) {
            throw "Worker did not emit a completed event: $WorkerExecutable"
        }
        if ($CompletedEvent.pageCount -ne 1 -or -not (Test-Path -LiteralPath $OutputPdf -PathType Leaf)) {
            throw "Worker did not create the expected one-page PDF: $WorkerExecutable"
        }

        $PdfBytes = [System.IO.File]::ReadAllBytes($OutputPdf)
        if ($PdfBytes.Length -lt 5) { throw "Worker output PDF is unexpectedly short." }
        $PdfHeader = [System.Text.Encoding]::ASCII.GetString($PdfBytes[0..4])
        if ($PdfHeader -ne "%PDF-") { throw "Worker output does not have a PDF header." }
        if (-not [string]::Equals(
            $CompletedEvent.outputPath,
            [System.IO.Path]::GetFullPath($OutputPdf),
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Worker completion event returned an unexpected output path."
        }
    }
    finally {
        Remove-Item $SmokeDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }

    Write-Host "Unicode-path PDF conversion smoke test passed: $Label"
}

function Test-SingleExeConversion {
    param(
        [Parameter(Mandatory)][string]$ExecutablePath,
        [Parameter(Mandatory)][string]$WorkingDirectory
    )

    $ImagePath = Join-Path $WorkingDirectory "入力画像.png"
    $OutputPdf = Join-Path $WorkingDirectory "変換結果.pdf"
    & python -c "from PIL import Image; import sys; Image.new('RGB', (37, 53), 'navy').save(sys.argv[1])" $ImagePath
    if ($LASTEXITCODE -ne 0) { throw "Could not create the single-file smoke-test image." }

    $Process = Start-Process -FilePath $ExecutablePath `
        -ArgumentList @("--selftest-convert", "`"$ImagePath`"", "`"$OutputPdf`"") `
        -WorkingDirectory $WorkingDirectory -PassThru -WindowStyle Hidden
    try {
        if (-not $Process.WaitForExit(120000)) {
            $Process.Kill($true)
            throw "Single-file conversion self-test timed out."
        }
        if ($Process.ExitCode -ne 0) {
            $ErrorFile = "$OutputPdf.selftest-error.txt"
            $Details = if (Test-Path -LiteralPath $ErrorFile) { [System.IO.File]::ReadAllText($ErrorFile) } else { "no details" }
            throw "Single-file conversion self-test failed (exit code $($Process.ExitCode)): $Details"
        }
    }
    finally {
        $Process.Dispose()
    }

    $PdfBytes = [System.IO.File]::ReadAllBytes($OutputPdf)
    if ([System.Text.Encoding]::ASCII.GetString($PdfBytes[0..4]) -ne "%PDF-") {
        throw "Single-file conversion did not write a PDF header."
    }

    Write-Host "Single-file embedded-worker conversion passed: $ExecutablePath"
}

function Get-WinUiCrashContext {
    param(
        [Parameter(Mandatory)][string]$ExecutablePath,
        [Parameter(Mandatory)][datetime]$StartedAt
    )

    try {
        $ExecutableName = [System.IO.Path]::GetFileName($ExecutablePath)
        $CrashEvents = @(Get-WinEvent `
            -FilterHashtable @{ LogName = "Application"; StartTime = $StartedAt } `
            -MaxEvents 40 `
            -ErrorAction SilentlyContinue |
            Where-Object {
                $_.ProviderName -in @("Application Error", ".NET Runtime", "Windows Error Reporting") -and
                $_.Message -like "*$ExecutableName*"
            } |
            Select-Object -First 4)
        if ($CrashEvents.Count -eq 0) {
            return "No matching Application/.NET crash event was recorded."
        }

        return (($CrashEvents | ForEach-Object {
            $Message = ($_.Message -replace "[\r\n]+", " ").Trim()
            if ($Message.Length -gt 1200) { $Message = $Message.Substring(0, 1200) }
            "{0} event {1}: {2}" -f $_.ProviderName, $_.Id, $Message
        }) -join " || ")
    }
    catch {
        return "Could not read Windows Application crash events: $($_.Exception.Message)"
    }
}

function Test-WinUiStartup {
    param(
        [Parameter(Mandatory)][string]$ExecutablePath,
        [Parameter(Mandatory)][string]$WorkingDirectory
    )

    $Process = $null
    $StartupStartedAt = Get-Date
    try {
        $Process = Start-Process -FilePath $ExecutablePath -WorkingDirectory $WorkingDirectory -PassThru
        if (-not $Process.WaitForInputIdle(20000)) {
            throw "WinUI process did not reach its message loop within 20 seconds."
        }

        $ExpectedTitle = "画像PDF変換ツール"
        $Deadline = [DateTime]::UtcNow.AddSeconds(10)
        do {
            $Process.Refresh()
            if ($Process.HasExited) {
                Start-Sleep -Milliseconds 500
                $CrashContext = Get-WinUiCrashContext -ExecutablePath $ExecutablePath -StartedAt $StartupStartedAt
                throw "WinUI process exited during startup (exit code $($Process.ExitCode)). $CrashContext"
            }
            if ($Process.MainWindowTitle -eq $ExpectedTitle) { break }
            Start-Sleep -Milliseconds 250
        } while ([DateTime]::UtcNow -lt $Deadline)

        $Process.Refresh()
        if ($Process.HasExited) {
            Start-Sleep -Milliseconds 500
            $CrashContext = Get-WinUiCrashContext -ExecutablePath $ExecutablePath -StartedAt $StartupStartedAt
            throw "WinUI process exited during startup (exit code $($Process.ExitCode)). $CrashContext"
        }
        if ($Process.MainWindowTitle -ne $ExpectedTitle) {
            throw "WinUI main window was not found. Actual title: '$($Process.MainWindowTitle)'"
        }

        Write-Host "WinUI executable startup smoke test passed: $ExecutablePath"
    }
    finally {
        if ($null -ne $Process) {
            try {
                $Process.Refresh()
                if (-not $Process.HasExited) {
                    [void]$Process.CloseMainWindow()
                    if (-not $Process.WaitForExit(5000)) {
                        $Process.Kill($true)
                        [void]$Process.WaitForExit(5000)
                    }
                }
            }
            finally {
                $Process.Dispose()
            }
        }
    }
}

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

    $Version = & python -c "from app_config import VERSION; print(VERSION)"
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($Version)) { throw "Could not read the application version." }
    $Version = $Version.Trim()

    $MainWindowXaml = [System.IO.File]::ReadAllText((Join-Path $RepoRoot "winui\ImageToPDF.WinUI\MainWindow.xaml"))
    if (-not $MainWindowXaml.Contains("Text=`"v$Version`"")) {
        throw "winui/ImageToPDF.WinUI/MainWindow.xaml does not show version v$Version."
    }

    & python -m PyInstaller --noconfirm --clean `
        --distpath $DistDirectory `
        --workpath (Join-Path $RepoRoot "build_tmp\worker") `
        (Join-Path $RepoRoot "ConversionWorker.spec")
    if ($LASTEXITCODE -ne 0) { throw "Python worker build failed (exit code $LASTEXITCODE)." }

    $WorkerExecutable = Join-Path $DistDirectory "ImageToPDFWorker.exe"
    Assert-X64PeExecutable -ExecutablePath $WorkerExecutable
    Test-WorkerConversion -WorkerExecutable $WorkerExecutable -Label "PyInstaller-output"

    $ReleaseName = "ImageToPDF-v$Version-Windows-x64.exe"
    $ReleaseExecutable = Join-Path $DistDirectory $ReleaseName
    $ChecksumPath = Join-Path $DistDirectory "SHA256SUMS.txt"
    foreach ($Stale in @($PublishDirectory, $ReleaseExecutable, $ChecksumPath)) {
        if (Test-Path -LiteralPath $Stale) {
            Remove-Item -LiteralPath $Stale -Recurse -Force
        }
    }

    $MSBuildPath = (Get-Command MSBuild.exe -ErrorAction Stop).Source
    $PublishOutput = @(& $MSBuildPath $Project /restore /target:Publish `
        /property:Configuration=Release `
        /property:Platform=x64 `
        /property:RuntimeIdentifier=win-x64 `
        /property:SelfContained=true `
        /property:PublishSingleFile=true `
        /property:IncludeNativeLibrariesForSelfExtract=true `
        /property:IncludeAllContentForSelfExtract=true `
        /property:EnableCompressionInSingleFile=true `
        /property:WindowsAppSDKSelfContained=true `
        /property:Version=$Version `
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

    $PublishedExecutable = Join-Path $PublishDirectory "ImageToPDF.WinUI.exe"
    Assert-X64PeExecutable -ExecutablePath $PublishedExecutable
    $StrayFiles = @(Get-ChildItem -LiteralPath $PublishDirectory -File |
        Where-Object { $_.Name -ne "ImageToPDF.WinUI.exe" -and $_.Extension -ne ".pdb" })
    if ($StrayFiles.Count -gt 0) {
        throw "Single-file publish left files beside the executable: $(($StrayFiles | ForEach-Object { $_.Name }) -join ', ')"
    }
    $ExecutableSize = (Get-Item -LiteralPath $PublishedExecutable).Length
    if ($ExecutableSize -lt 20MB) {
        throw "Single-file executable is unexpectedly small ($ExecutableSize bytes); the runtime or worker may be missing."
    }

    Copy-Item -LiteralPath $PublishedExecutable -Destination $ReleaseExecutable -Force
    # Redistribution notices ship next to the executable: the embedded Python
    # worker bundles LGPL/GPL components documented in THIRD_PARTY_NOTICES.md.
    Copy-Item -LiteralPath (Join-Path $RepoRoot "LICENSE") -Destination $DistDirectory -Force
    Copy-Item -LiteralPath (Join-Path $RepoRoot "THIRD_PARTY_NOTICES.md") -Destination $DistDirectory -Force
    $Hash = (Get-FileHash -LiteralPath $ReleaseExecutable -Algorithm SHA256).Hash.ToLowerInvariant()
    $ChecksumLine = "$Hash  $ReleaseName"
    Set-Content -Path $ChecksumPath -Value $ChecksumLine -Encoding ASCII
    if (([System.IO.File]::ReadAllText($ChecksumPath)).Trim() -ne $ChecksumLine) {
        throw "Checksum file does not match the release executable."
    }

    # Run the release file alone, from a Unicode folder with no build output beside it.
    $VerificationDirectory = Join-Path $env:TEMP ("画像PDF確認-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $VerificationDirectory | Out-Null
    try {
        $VerificationExecutable = Join-Path $VerificationDirectory $ReleaseName
        Copy-Item -LiteralPath $ReleaseExecutable -Destination $VerificationExecutable
        Test-SingleExeConversion -ExecutablePath $VerificationExecutable -WorkingDirectory $VerificationDirectory
        Test-WinUiStartup -ExecutablePath $VerificationExecutable -WorkingDirectory $VerificationDirectory
    }
    finally {
        Remove-Item $VerificationDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }

    Write-Host "WinUI single-file release fully validated: $ReleaseExecutable"
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
