using System.Text.Json;
using ImageToPDF.WinUI.Services;

var root = Path.Combine(Path.GetTempPath(), "preset-tests-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(root);
try
{
    MissingFileKeepsBuiltIns();
    RoundTripAllConversionOptions();
    PresetsDoNotCopyJobOrWindowState();
    NamesAndBuiltInsAreProtected();
    OverwriteRequiresExplicitChoice();
    DeletePersistsWithoutApplyingSettings();
    InvalidStoredOptionsAreNormalized();
    BrokenEntriesDoNotDiscardGoodEntries();
    CorruptFileStillOffersBuiltIns();
    FailedWriteDoesNotChangeCatalog();
    LegacySettingsStillDeserialize();
    Console.WriteLine("Conversion preset regression tests: 11 passed.");
}
finally
{
    Directory.Delete(root, recursive: true);
}

ConversionPresetStore Store(string name) => new(Path.Combine(root, name + ".json"));

void MissingFileKeepsBuiltIns()
{
    var store = Store("missing");
    store.Load();
    Check(store.All.Count == 3 && store.All.All(item => item.IsBuiltIn), "Built-ins should work without a file.");
    Check(store.All.Single(item => item.Name == "提出書類用").Options.PageSize == "A4", "Document preset uses A4.");
    Check(store.All.Single(item => item.Name == "メール添付用").Options.Quality == "compact", "Email preset reduces image size.");
}

void RoundTripAllConversionOptions()
{
    var store = Store("roundtrip");
    var options = new ConversionPresetOptions
    {
        Quality = "compact", PageSize = "Custom", CustomPageWidthMm = 123.5, CustomPageHeightMm = 234.5,
        MarginMm = 12.5, DefaultDpi = 300, Background = "gray", AutoRotate = false, FitToPage = true,
        Alignment = "top-left", OpenAfter = true, Outline = true, CompactDpi = 240, JpegQuality = 92,
    };
    store.Save("  自分の書類  ", options);
    var loaded = Store("roundtrip");
    loaded.Load();
    var preset = loaded.All.Single(item => !item.IsBuiltIn);
    Check(preset.Name == "自分の書類" && preset.Options == options, "All conversion fields must survive restart.");
    var settings = new AppSettings();
    preset.Options.ApplyTo(settings);
    Check(ConversionPresetOptions.FromSettings(settings) == options, "Applying a preset must restore every conversion field.");
}

void PresetsDoNotCopyJobOrWindowState()
{
    var settings = new AppSettings
    {
        MetadataAuthor = "Private author", LastOutputDirectory = "private-output", GridView = true,
        FolderSortIndex = 2, WindowWidth = 1777, WindowHeight = 999,
    };
    var options = new ConversionPresetOptions { PageSize = "B5", Outline = true };
    options.ApplyTo(settings);
    Check(settings.MetadataAuthor == "Private author" && settings.LastOutputDirectory == "private-output"
        && settings.GridView && settings.FolderSortIndex == 2 && settings.WindowWidth == 1777
        && settings.WindowHeight == 999, "Presets must not overwrite document, output or display state.");
    var json = JsonSerializer.Serialize(ConversionPresetOptions.FromSettings(settings));
    Check(!json.Contains("Private author") && !json.Contains("private-output"), "Private job data must never enter preset JSON.");
}

void NamesAndBuiltInsAreProtected()
{
    var store = Store("names");
    foreach (var name in new[] { "", "  ", "line\nbreak", new string('a', 61), "提出書類用" })
        Expect<ArgumentException>(() => store.Save(name, new()));
    Expect<ArgumentException>(() => store.Save("写真用", new(), overwrite: true));
    Expect<ArgumentException>(() => store.Delete("写真用"));
    Check(store.All.Count == 3, "Rejected operations must preserve built-ins.");
}

void OverwriteRequiresExplicitChoice()
{
    var store = Store("overwrite");
    store.Save("Work", new() { PageSize = "A4" });
    Expect<ArgumentException>(() => store.Save(" work ", new() { PageSize = "A5" }));
    store.Save("WORK", new() { PageSize = "A5" }, overwrite: true);
    var loaded = Store("overwrite");
    loaded.Load();
    Check(loaded.All.Count == 4 && loaded.All.Last().Options.PageSize == "A5", "Overwrite should update, not duplicate, the preset.");
}

void DeletePersistsWithoutApplyingSettings()
{
    var store = Store("delete");
    var saved = store.Save("Temporary", new() { PageSize = "Legal" });
    var current = new AppSettings();
    saved.Options.ApplyTo(current);
    store.Delete("temporary");
    var loaded = Store("delete");
    loaded.Load();
    Check(loaded.All.Count == 3 && current.PageSize == "Legal", "Delete must persist while leaving applied settings alone.");
}

void InvalidStoredOptionsAreNormalized()
{
    var normalized = new ConversionPresetOptions
    {
        Quality = "bad", PageSize = "unknown", Background = "bad", Alignment = "bad",
        CustomPageWidthMm = double.NaN, CustomPageHeightMm = 9999, DefaultDpi = double.PositiveInfinity,
        MarginMm = -1, CompactDpi = 0, JpegQuality = 101,
    }.Normalize();
    Check(normalized == new ConversionPresetOptions(), "Invalid values should fall back to safe defaults.");
    Check((new ConversionPresetOptions { PageSize = "L", MarginMm = 50 }).Normalize().MarginMm == 0,
        "A margin larger than the paper must be repaired.");
    Check((new ConversionPresetOptions { PageSize = "Custom", CustomPageWidthMm = 10, MarginMm = 5 }).Normalize().MarginMm == 0,
        "Custom paper margins must leave a printable area.");
}

void BrokenEntriesDoNotDiscardGoodEntries()
{
    File.WriteAllText(Path.Combine(root, "entries.json"), """
        [null, {"Name":"Missing options"}, {"Name":"Wrong type","Options":{"CompactDpi":"bad"}},
         {"Name":"Useful","Options":{"PageSize":"B5"}}, {"Name":"Useful","Options":{}},
         {"Name":"写真用","Options":{}}, {"Name":"  ","Options":{}}]
        """);
    var store = Store("entries");
    store.Load();
    Check(store.All.Count == 4 && store.All.Last().Name == "Useful"
        && store.All.Last().Options.PageSize == "B5", "Skip malformed, duplicate and reserved entries independently.");
}

void CorruptFileStillOffersBuiltIns()
{
    File.WriteAllText(Path.Combine(root, "corrupt.json"), "{broken");
    var store = Store("corrupt");
    Expect<JsonException>(store.Load);
    Check(store.All.Count == 3, "Built-ins must remain usable after a load error.");
}

void FailedWriteDoesNotChangeCatalog()
{
    var blocked = Path.Combine(root, "blocked.json");
    Directory.CreateDirectory(blocked);
    var store = new ConversionPresetStore(blocked);
    try
    {
        store.Save("Cannot save", new());
        throw new Exception("Expected write failure.");
    }
    catch (Exception error) when (error is IOException or UnauthorizedAccessException)
    {
        Check(store.All.Count == 3, "Do not claim a preset was saved when publication failed.");
        Check(Directory.GetFiles(root, "blocked.json.*.tmp").Length == 0, "Failed writes must clean up staging files.");
    }
}

void LegacySettingsStillDeserialize()
{
    var settings = JsonSerializer.Deserialize<AppSettings>("""{"Quality":"compact","PageSize":"A4","MetadataAuthor":"Previous author"}""")!;
    Check(settings.Quality == "compact" && settings.MetadataAuthor == "Previous author", "Existing settings remain compatible.");
}

static void Check(bool condition, string message)
{
    if (!condition) throw new InvalidOperationException(message);
}

static void Expect<T>(Action action) where T : Exception
{
    try { action(); }
    catch (T) { return; }
    throw new InvalidOperationException($"Expected {typeof(T).Name}.");
}
