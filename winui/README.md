# WinUI 3 frontend (preview)

This folder contains the first native Windows UI implementation. It is intentionally separate from the current Tkinter release until Windows builds and feature-parity checks pass.

## Design direction

- Use the standard WinUI 3 controls, Windows system typography, and theme-aware colors.
- Keep the surface quiet and task-focused: clear headings, thin separators, one restrained accent action, and no gradients, glass effects, decorative badges, or stacked cards.
- Keep the image queue and conversion controls visible together. Use native file/folder pickers and accept image drops from Explorer.

## Architecture

- `MainWindow.xaml` / `.xaml.cs`: WinUI presentation and Windows pickers.
- `ViewModels/MainViewModel.cs`: file queue, filtering, folder sorting, and order changes.
- `Services/ConversionWorkerService.cs`: starts the Python worker without showing a console, streams progress, and sends cooperative cancellation.
- `../../conversion_worker.py`: JSON request + JSON Lines response adapter over the existing `image_processor.py` conversion engine. Thumbnail requests use Pillow too, including formats Windows may not preview natively.

The existing Tkinter application and CLI are left intact while this frontend is being validated.

## Development

Build and run on Windows 10/11 x64 with the .NET 8 SDK, Visual Studio 2022 MSBuild and Windows SDK tooling, Windows App SDK restore access, Python 3.10–3.12, and the repository's Python dependencies installed:

```powershell
python -m pip install -r requirements-dev.txt -r requirements-optional.txt
dotnet run --project .\winui\ImageToPDF.WinUI\ImageToPDF.WinUI.csproj -p:Platform=x64
```

When `ImageToPDFWorker.exe` is not beside the app, the frontend looks up the repository's `conversion_worker.py` and runs it with `python` (or the executable named by `PYTHON`). This is intended for development only.

To create a self-contained WinUI folder and portable ZIP, run from PowerShell on Windows:

```powershell
.\build_winui.ps1
```

The script builds a console-capable worker executable for redirected JSONL communication, publishes the WinUI app with the Windows App SDK self-contained, and packages the folder. The project explicitly includes its generated app `.pri` and compiled `.xbf` resources in the unpackaged publish output; a missing app PRI caused the first CI launch smoke test to exit with `0xC000027B`. The worker's console window is suppressed by the WinUI process launcher.

## Validation status

The repository sandbox has no .NET SDK and is not Windows, so it cannot validate the WinUI executable locally. Windows CI run [38526128543](https://github.com/burugou05-wq/PDF_conversion/actions/runs/38526128543) passed on the final packaging changes and uploaded `ImageToPDF-WinUI-Preview` (not an official release asset). It verifies x64 PE headers, self-contained .NET runtime files, the app PRI and XBF resources, ZIP entries and checksums, worker conversions with Japanese filenames from the build/published/extracted folders, and startup of the WinUI EXE from the extracted ZIP with the expected window title.

The CI launch smoke is a basic startup check, not a substitute for manual testing on a real Windows 11 machine. Keep Tkinter as the official Release until the WinUI runtime, Explorer drag-and-drop, AVIF/HEIF thumbnail fallback, cancellation, Unicode paths, and portable placement have been verified interactively on Windows 11.
