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

function Get-InnoSetupCompiler {
    $Command = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($null -ne $Command) { return $Command.Source }

    foreach ($Candidate in @(
        (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
    )) {
        if ($Candidate -and (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
            return $Candidate
        }
    }

    if ($env:GITHUB_ACTIONS -eq "true") {
        & choco install innosetup --no-progress -y
        foreach ($Candidate in @(
            (Join-Path ${env:ProgramFiles(x86)} "Inno Setup 6\ISCC.exe"),
            (Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe")
        )) {
            if ($Candidate -and (Test-Path -LiteralPath $Candidate -PathType Leaf)) {
                return $Candidate
            }
        }
    }

    throw "Inno Setup 6 (ISCC.exe) was not found. Install Inno Setup 6 to build the installer."
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

    # The resident worker logs its startup/protocol steps when this variable
    # is set; the log localizes EXE-only hangs that stderr cannot show.
    $WorkerLog = "$OutputPdf.worker-log.txt"
    # The application log is redirected the same way: the packaged EXE then
    # writes its records to a temp file, so the runner's own %LOCALAPPDATA%
    # stays clean and the self-test can assert that logging and its 1MB
    # rotation work outside the development tree.
    $AppLog = "$OutputPdf.app-log.txt"
    if (Test-Path -LiteralPath $WorkerLog) { Remove-Item -LiteralPath $WorkerLog -Force }
    if (Test-Path -LiteralPath $AppLog) { Remove-Item -LiteralPath $AppLog -Force }
    $env:IMAGETOPDF_WORKER_LOG = $WorkerLog
    $env:IMAGETOPDF_APP_LOG = $AppLog
    try {
        $Process = Start-Process -FilePath $ExecutablePath `
            -ArgumentList @("--selftest-convert", "`"$ImagePath`"", "`"$OutputPdf`"") `
            -WorkingDirectory $WorkingDirectory -PassThru -WindowStyle Hidden
    }
    finally {
        Remove-Item Env:\IMAGETOPDF_WORKER_LOG -ErrorAction SilentlyContinue
        Remove-Item Env:\IMAGETOPDF_APP_LOG -ErrorAction SilentlyContinue
    }

    function Get-SelftestDiagnostics {
        $Parts = @()
        foreach ($Log in @($WorkerLog, "$OutputPdf.selftest-log.txt", "$OutputPdf.selftest-error.txt")) {
            if (Test-Path -LiteralPath $Log) {
                $Parts += "[$([System.IO.Path]::GetFileName($Log))]`n$([System.IO.File]::ReadAllText($Log))"
            }
        }
        if (Test-Path -LiteralPath $AppLog) {
            # The rotation check pads the log with 400KB lines; keep only the
            # human-readable records in the failure message.
            $AppLogRecords = @(Get-Content -LiteralPath $AppLog -Encoding utf8 |
                Where-Object { $_.Length -lt 400 } |
                Select-Object -Last 30)
            $Parts += "[app-log.txt]`n$($AppLogRecords -join "`n")"
        }
        if ($Parts.Count -eq 0) { return "no diagnostics were written" }
        return $Parts -join "`n"
    }

    try {
        if (-not $Process.WaitForExit(120000)) {
            $Process.Kill($true)
            throw "Single-file conversion self-test timed out. Diagnostics: $(Get-SelftestDiagnostics)"
        }
        if ($Process.ExitCode -ne 0) {
            throw "Single-file conversion self-test failed (exit code $($Process.ExitCode)). Diagnostics: $(Get-SelftestDiagnostics)"
        }
    }
    finally {
        $Process.Dispose()
    }

    $PdfBytes = [System.IO.File]::ReadAllBytes($OutputPdf)
    if ([System.Text.Encoding]::ASCII.GetString($PdfBytes[0..4]) -ne "%PDF-") {
        throw "Single-file conversion did not write a PDF header."
    }

    if (-not (Test-Path -LiteralPath $AppLog)) {
        throw "Single-file conversion did not write the application log: $AppLog"
    }
    $AppLogLength = (Get-Item -LiteralPath $AppLog).Length
    if ($AppLogLength -lt 1) {
        throw "Application log is empty after the single-file conversion: $AppLog"
    }
    if (-not (Test-Path -LiteralPath "$AppLog.1")) {
        throw "Application log did not rotate past 1MB: $AppLog.1"
    }

    Write-Host "Single-file embedded-worker conversion passed: $ExecutablePath"
    Write-Host "Application log verified: $AppLog ($AppLogLength bytes, rotated to $AppLog.1)"
}

function Test-UpdateSelfCheck {
    param(
        [Parameter(Mandatory)][string]$ExecutablePath,
        [Parameter(Mandatory)][string]$WorkingDirectory
    )

    # リリース応答の解析・バージョン比較・SHA-256照合・更新ダイアログの生成を
    # ネットワークなしで確認します（GitHub APIの応答を模した固定のJSONを使用）。
    $LogPath = Join-Path $WorkingDirectory "アップデート自己診断.txt"
    if (Test-Path -LiteralPath $LogPath) { Remove-Item -LiteralPath $LogPath -Force }
    $Process = $null
    $env:IMAGETOPDF_DISABLE_UPDATE_CHECK = "1"
    try {
        $Process = Start-Process -FilePath $ExecutablePath `
            -ArgumentList @("--selftest-update", "`"$LogPath`"") `
            -WorkingDirectory $WorkingDirectory -PassThru -WindowStyle Hidden
        if (-not $Process.WaitForExit(90000)) {
            $Process.Kill($true)
            throw "Update self-check timed out."
        }
        if ($Process.ExitCode -ne 0) {
            $Details = if (Test-Path -LiteralPath $LogPath) {
                [System.IO.File]::ReadAllText($LogPath)
            } else {
                "no diagnostics were written"
            }
            throw "Update self-check failed (exit code $($Process.ExitCode)).`n$Details"
        }
    }
    finally {
        Remove-Item Env:\IMAGETOPDF_DISABLE_UPDATE_CHECK -ErrorAction SilentlyContinue
        if ($null -ne $Process) { $Process.Dispose() }
    }

    if (-not (Test-Path -LiteralPath $LogPath)) {
        throw "Update self-check did not write its log: $LogPath"
    }
    $Log = [System.IO.File]::ReadAllText($LogPath)
    if ($Log -notlike "*update selftest ok*") {
        throw "Update self-check reported a failure: $Log"
    }

    Write-Host "Update self-check passed: $LogPath"
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

    # The GUI writes its startup record to app.log; redirect it into the temp
    # verification folder so the check below can read what the window logged.
    $AppLog = Join-Path $WorkingDirectory "起動ログ.txt"
    if (Test-Path -LiteralPath $AppLog) { Remove-Item -LiteralPath $AppLog -Force }
    $env:IMAGETOPDF_APP_LOG = $AppLog
    # 起動確認では外部通信（更新確認）を行いません。
    $env:IMAGETOPDF_DISABLE_UPDATE_CHECK = "1"
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

        if (-not (Test-Path -LiteralPath $AppLog)) {
            throw "WinUI startup did not create the application log: $AppLog"
        }
        $StartupLog = [System.IO.File]::ReadAllText($AppLog, [System.Text.Encoding]::UTF8)
        if ($StartupLog -notlike "*アプリを開始しました*") {
            throw "WinUI startup log has no startup record: $StartupLog"
        }

        Write-Host "WinUI executable startup smoke test passed: $ExecutablePath"
        Write-Host "WinUI startup log verified: $AppLog"
    }
    finally {
        Remove-Item Env:\IMAGETOPDF_APP_LOG -ErrorAction SilentlyContinue
        Remove-Item Env:\IMAGETOPDF_DISABLE_UPDATE_CHECK -ErrorAction SilentlyContinue
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

    $ReleaseName = "ImageToPDF-Setup-v$Version-Windows-x64.exe"
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

    # Inno Setup requires UTF-8 with BOM when the .iss file contains Japanese text.
    $InstallerScript = Join-Path $RepoRoot "installer\ImageToPDF.iss"
    $IssContent = [System.IO.File]::ReadAllText($InstallerScript, [System.Text.Encoding]::UTF8)
    [System.IO.File]::WriteAllText($InstallerScript, $IssContent, [System.Text.UTF8Encoding]::new($true))

    $IsccPath = Get-InnoSetupCompiler
    & $IsccPath `
        "/DAppVersion=$Version" `
        "/DSourceExe=$PublishedExecutable" `
        "/DOutputDir=$DistDirectory" `
        $InstallerScript
    if ($LASTEXITCODE -ne 0) {
        throw "Inno Setup installer build failed (exit code $LASTEXITCODE)."
    }
    if (-not (Test-Path -LiteralPath $ReleaseExecutable -PathType Leaf)) {
        throw "Inno Setup did not produce the expected installer: $ReleaseExecutable"
    }
    $InstallerSize = (Get-Item -LiteralPath $ReleaseExecutable).Length
    if ($InstallerSize -lt 20MB) {
        throw "Installer executable is unexpectedly small ($InstallerSize bytes); the runtime or worker may be missing."
    }

    # Redistribution notices ship both inside the installer and next to it in Release assets.
    Copy-Item -LiteralPath (Join-Path $RepoRoot "LICENSE") -Destination $DistDirectory -Force
    Copy-Item -LiteralPath (Join-Path $RepoRoot "THIRD_PARTY_NOTICES.md") -Destination $DistDirectory -Force
    $Hash = (Get-FileHash -LiteralPath $ReleaseExecutable -Algorithm SHA256).Hash.ToLowerInvariant()
    # The tag header is covered by the detached ECDSA signature, so a signed
    # checksum file cannot be replayed for a different release tag.
    $ChecksumHeader = "# tag: v$Version"
    $ChecksumLine = "$Hash  $ReleaseName"
    Set-Content -Path $ChecksumPath -Value @($ChecksumHeader, $ChecksumLine) -Encoding ASCII
    $ExpectedChecksumContent = "$ChecksumHeader`n$ChecksumLine"
    $ActualChecksumContent = ([System.IO.File]::ReadAllText($ChecksumPath)).Replace("`r`n", "`n").Trim()
    if ($ActualChecksumContent -ne $ExpectedChecksumContent) {
        throw "Checksum file does not match the release installer."
    }

    # Run the installer into a Unicode folder and validate the installed ImageToPDF.exe.
    $VerificationDirectory = Join-Path $env:TEMP ("画像PDF確認-" + [Guid]::NewGuid().ToString("N"))
    $InstalledDirectory = Join-Path $VerificationDirectory "インストール先"
    New-Item -ItemType Directory -Path $VerificationDirectory | Out-Null
    $UninstallerExecutable = Join-Path $InstalledDirectory "unins000.exe"
    try {
        $VerificationInstaller = Join-Path $VerificationDirectory $ReleaseName
        Copy-Item -LiteralPath $ReleaseExecutable -Destination $VerificationInstaller
        $InstallProcess = Start-Process -FilePath $VerificationInstaller `
            -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-", "/TASKS=`"`"", "/DIR=`"$InstalledDirectory`"") `
            -WorkingDirectory $VerificationDirectory -PassThru -WindowStyle Hidden
        try {
            if (-not $InstallProcess.WaitForExit(120000)) {
                $InstallProcess.Kill($true)
                throw "Installer smoke test timed out."
            }
            if ($InstallProcess.ExitCode -ne 0) {
                throw "Installer smoke test failed (exit code $($InstallProcess.ExitCode))."
            }
        }
        finally {
            $InstallProcess.Dispose()
        }

        $InstalledExecutable = Join-Path $InstalledDirectory "ImageToPDF.exe"
        Assert-X64PeExecutable -ExecutablePath $InstalledExecutable
        if (-not (Test-Path -LiteralPath $UninstallerExecutable -PathType Leaf)) {
            throw "Installer did not create the uninstaller: $UninstallerExecutable"
        }
        if (-not (Test-Path -LiteralPath (Join-Path $InstalledDirectory "LICENSE") -PathType Leaf)) {
            throw "Installer did not copy LICENSE to the installation folder."
        }
        if (-not (Test-Path -LiteralPath (Join-Path $InstalledDirectory "THIRD_PARTY_NOTICES.md") -PathType Leaf)) {
            throw "Installer did not copy THIRD_PARTY_NOTICES.md to the installation folder."
        }

        Test-SingleExeConversion -ExecutablePath $InstalledExecutable -WorkingDirectory $VerificationDirectory
        Test-UpdateSelfCheck -ExecutablePath $InstalledExecutable -WorkingDirectory $VerificationDirectory
        Test-WinUiStartup -ExecutablePath $InstalledExecutable -WorkingDirectory $VerificationDirectory
    }
    finally {
        if (Test-Path -LiteralPath $UninstallerExecutable -PathType Leaf) {
            $UninstallProcess = Start-Process -FilePath $UninstallerExecutable `
                -ArgumentList @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART") `
                -WorkingDirectory $VerificationDirectory -PassThru -WindowStyle Hidden
            try {
                [void]$UninstallProcess.WaitForExit(30000)
            }
            finally {
                $UninstallProcess.Dispose()
            }
            Start-Sleep -Seconds 1
        }
        Remove-Item $VerificationDirectory -Recurse -Force -ErrorAction SilentlyContinue
    }

    Write-Host "WinUI installer release fully validated: $ReleaseExecutable"
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
