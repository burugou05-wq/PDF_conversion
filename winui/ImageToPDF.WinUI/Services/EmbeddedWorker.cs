using System.Reflection;

namespace ImageToPDF.WinUI.Services;

/// <summary>
/// Extracts the PyInstaller conversion worker that is embedded in the single-file EXE.
/// Each build has its own module version id, so an updated EXE never reuses an old worker.
/// </summary>
internal static class EmbeddedWorker
{
    internal const string ResourceName = "ImageToPDFWorker.exe";

    public static string? TryGetWorkerPath()
    {
        var assembly = typeof(EmbeddedWorker).Assembly;
        using var resource = assembly.GetManifestResourceStream(ResourceName);
        if (resource is null)
        {
            return null;
        }

        var directory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "ImageToPDF",
            "worker",
            assembly.ManifestModule.ModuleVersionId.ToString("N"));
        var target = Path.Combine(directory, ResourceName);
        if (File.Exists(target) && new FileInfo(target).Length == resource.Length)
        {
            return target;
        }

        Directory.CreateDirectory(directory);
        var temporary = Path.Combine(directory, $"{ResourceName}.{Guid.NewGuid():N}.tmp");
        try
        {
            using (var output = File.Create(temporary))
            {
                resource.CopyTo(output);
            }

            File.Move(temporary, target, overwrite: true);
        }
        catch (IOException) when (File.Exists(target) && new FileInfo(target).Length == resource.Length)
        {
            // Another instance finished extracting the same worker first.
        }
        finally
        {
            try
            {
                File.Delete(temporary);
            }
            catch (IOException)
            {
                // The temporary file was already moved or is still in use by another instance.
            }
            catch (UnauthorizedAccessException)
            {
                // Cleanup is best-effort; the worker itself is already in place.
            }
        }

        return target;
    }
}
