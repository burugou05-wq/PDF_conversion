$ErrorActionPreference = "Stop"
$RepoRoot = $PSScriptRoot
$Project = Join-Path $RepoRoot "winui\ImageToPDF.WinUI\ImageToPDF.WinUI.csproj"
$PublishDirectory = Join-Path $RepoRoot "dist\ImageToPDF-WinUI"
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

function Assert-PortableArchive {
    param(
        [Parameter(Mandatory)][string]$ArchivePath,
        [Parameter(Mandatory)][string]$PublishPath
    )

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $Zip = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
    try {
        $Entries = @{}
        foreach ($Entry in $Zip.Entries) {
            $EntryName = $Entry.FullName.Replace("\", "/")
            if ($EntryName.StartsWith("/") -or $EntryName -match '(^|/)\.\.(/|$)') {
                throw "Unsafe path in portable archive: $EntryName"
            }
            if ($Entries.ContainsKey($EntryName)) {
                throw "Duplicate path in portable archive: $EntryName"
            }
            $Entries[$EntryName] = $Entry

            if (-not $EntryName.EndsWith("/")) {
                $EntryStream = $Entry.Open()
                try {
                    $EntryStream.CopyTo([System.IO.Stream]::Null)
                }
                finally {
                    $EntryStream.Dispose()
                }
            }
        }

        $RequiredArchiveFiles = @(
            "ImageToPDF.WinUI.exe",
            "ImageToPDFWorker.exe",
            "ImageToPDF.WinUI.dll",
            "ImageToPDF.WinUI.deps.json",
            "ImageToPDF.WinUI.runtimeconfig.json",
            "ImageToPDF.WinUI.pri",
            "coreclr.dll",
            "hostfxr.dll",
            "hostpolicy.dll",
            "PORTABLE.txt"
        )
        foreach ($RequiredFile in $RequiredArchiveFiles) {
            if (-not $Entries.ContainsKey($RequiredFile)) {
                throw "Required file is missing from portable archive: $RequiredFile"
            }
        }
        if (@($Entries.Keys | Where-Object { $_ -match '\.xbf$' }).Count -eq 0) {
            throw "Portable archive is missing compiled WinUI XAML resources (.xbf files)."
        }

        foreach ($ExecutableName in @("ImageToPDF.WinUI.exe", "ImageToPDFWorker.exe")) {
            $PublishedLength = (Get-Item -LiteralPath (Join-Path $PublishPath $ExecutableName)).Length
            if ($Entries[$ExecutableName].Length -ne $PublishedLength) {
                throw "Portable archive entry size does not match the published file: $ExecutableName"
            }
        }

        Write-Host "Verified portable ZIP structure and read $($Zip.Entries.Count) entries: $ArchivePath"
    }
    finally {
        $Zip.Dispose()
    }
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

    & python -m PyInstaller --noconfirm --clean `
        --distpath $DistDirectory `
        --workpath (Join-Path $RepoRoot "build_tmp\worker") `
        (Join-Path $RepoRoot "ConversionWorker.spec")
    if ($LASTEXITCODE -ne 0) { throw "Python worker build failed (exit code $LASTEXITCODE)." }

    $WorkerExecutable = Join-Path $DistDirectory "ImageToPDFWorker.exe"
    Assert-X64PeExecutable -ExecutablePath $WorkerExecutable
    Test-WorkerConversion -WorkerExecutable $WorkerExecutable -Label "PyInstaller-output"

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

    $RequiredPublishedFiles = @(
        "ImageToPDF.WinUI.exe",
        "ImageToPDFWorker.exe",
        "ImageToPDF.WinUI.dll",
        "ImageToPDF.WinUI.deps.json",
        "ImageToPDF.WinUI.runtimeconfig.json",
        "ImageToPDF.WinUI.pri",
        "coreclr.dll",
        "hostfxr.dll",
        "hostpolicy.dll"
    )
    foreach ($RequiredFile in $RequiredPublishedFiles) {
        if (-not (Test-Path -LiteralPath (Join-Path $PublishDirectory $RequiredFile) -PathType Leaf)) {
            throw "Required self-contained publish file is missing: $RequiredFile"
        }
    }
    $PublishedXamlBinaries = @(Get-ChildItem -LiteralPath $PublishDirectory -Filter "*.xbf" -File -Recurse)
    if ($PublishedXamlBinaries.Count -eq 0) {
        throw "Self-contained publish is missing compiled WinUI XAML resources (.xbf files)."
    }

    foreach ($ExecutableName in @("ImageToPDF.WinUI.exe", "ImageToPDFWorker.exe")) {
        Assert-X64PeExecutable -ExecutablePath (Join-Path $PublishDirectory $ExecutableName)
    }
    Test-WorkerConversion `
        -WorkerExecutable (Join-Path $PublishDirectory "ImageToPDFWorker.exe") `
        -Label "published-folder"

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
    $Hash = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
    $ChecksumPath = Join-Path $DistDirectory "SHA256SUMS-WinUI.txt"
    $ChecksumLine = "$Hash  $(Split-Path -Leaf $Archive)"
    Set-Content -Path $ChecksumPath -Value $ChecksumLine -Encoding ASCII
    if (([System.IO.File]::ReadAllText($ChecksumPath)).Trim() -ne $ChecksumLine) {
        throw "WinUI artifact checksum file does not match the ZIP."
    }

    Assert-PortableArchive -ArchivePath $Archive -PublishPath $PublishDirectory

    $ExtractionDirectory = Join-Path $env:TEMP ("ImageToPDF-WinUI-ZipTest-" + [Guid]::NewGuid().ToString("N"))
    New-Item -ItemType Directory -Path $ExtractionDirectory | Out-Null
    try {
        Expand-Archive -LiteralPath $Archive -DestinationPath $ExtractionDirectory
        foreach ($ExecutableName in @("ImageToPDF.WinUI.exe", "ImageToPDFWorker.exe")) {
            Assert-X64PeExecutable -ExecutablePath (Join-Path $ExtractionDirectory $ExecutableName)
        }
        Test-WorkerConversion `
            -WorkerExecutable (Join-Path $ExtractionDirectory "ImageToPDFWorker.exe") `
            -Label "extracted-ZIP"
        Test-WinUiStartup `
            -ExecutablePath (Join-Path $ExtractionDirectory "ImageToPDF.WinUI.exe") `
            -WorkingDirectory $ExtractionDirectory
    }
    finally {
        Remove-Item $ExtractionDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }

    Write-Host "WinUI portable package fully validated: $Archive"
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
