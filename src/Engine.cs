using System.IO;
using System.Text;

namespace CollisionTool
{
    /// <summary>
    /// Locates the Python engine (Engine\core.py plus Engine\Dependencies\*.js)
    /// shipped next to the executable and prepares it to run.
    ///
    /// core.py is read into memory as ScriptSource. Everything else in the
    /// Engine folder (the three.js files) is copied once per app run into a
    /// randomly named folder under the OS temp directory, which becomes the
    /// interpreter's working directory. That keeps the app working when it is
    /// installed somewhere read-only (e.g. Program Files). Cleanup() deletes
    /// the temp folder on exit.
    /// </summary>
    public static class Engine
    {
        private const string ScriptEntryName = "core.py";
        private const string SurfaceNamesFileName = "SurfaceNames.txt";

        private static (string Source, string WorkingDir)? _resolved;
        private static string? _cacheDirToClean;

        private static (string Source, string WorkingDir) Resolved => _resolved ??= Resolve();

        /// <summary>The engine's Python source (core.py).</summary>
        public static string ScriptSource => Resolved.Source;

        /// <summary>Writable folder to run the interpreter from; contains Dependencies\ so core.py's lookups resolve.</summary>
        public static string WorkingDirectory => Resolved.WorkingDir;

        public static bool IsAvailable => !string.IsNullOrEmpty(ScriptSource);

        /// <summary>Engine\SurfaceNames.txt next to the executable; null when absent. Re-checked per run so edits apply on the next load.</summary>
        public static string? SurfaceNamesPath
        {
            get
            {
                string path = Path.Combine(AppContext.BaseDirectory, "Engine", SurfaceNamesFileName);
                return File.Exists(path) ? path : null;
            }
        }

        private static (string, string) Resolve()
        {
            string baseDir = AppContext.BaseDirectory;
            string engineDir = Path.Combine(baseDir, "Engine");
            string scriptPath = Path.Combine(engineDir, ScriptEntryName);

            if (!File.Exists(scriptPath))
                return ("", baseDir); // IsAvailable stays false

            string cacheDir = Path.Combine(Path.GetTempPath(), Guid.NewGuid().ToString("N"));

            try
            {
                string source = File.ReadAllText(scriptPath, Encoding.UTF8);
                CopyEngineFiles(engineDir, cacheDir);
                _cacheDirToClean = cacheDir;
                return (source, cacheDir);
            }
            catch
            {
                // Same "engine not available" path as a missing engine, instead of throwing from a property getter.
                try { if (Directory.Exists(cacheDir)) Directory.Delete(cacheDir, recursive: true); }
                catch { /* best-effort */ }
                return ("", baseDir);
            }
        }

        // Copies the Engine folder into cacheDir, except core.py (kept in memory) and SurfaceNames.txt (read in place).
        private static void CopyEngineFiles(string engineDir, string cacheDir)
        {
            Directory.CreateDirectory(cacheDir);

            foreach (string file in Directory.EnumerateFiles(engineDir, "*", SearchOption.AllDirectories))
            {
                string relative = Path.GetRelativePath(engineDir, file);
                if (string.Equals(relative, ScriptEntryName, StringComparison.OrdinalIgnoreCase) ||
                    string.Equals(relative, SurfaceNamesFileName, StringComparison.OrdinalIgnoreCase))
                    continue;

                string dest = Path.Combine(cacheDir, relative);
                Directory.CreateDirectory(Path.GetDirectoryName(dest)!);
                File.Copy(file, dest, overwrite: true);
            }
        }

        /// <summary>Deletes the temp folder created by Resolve(), if any. Call once on app exit.</summary>
        public static void Cleanup()
        {
            if (_cacheDirToClean == null)
                return;
            try { Directory.Delete(_cacheDirToClean, recursive: true); }
            catch { /* best-effort */ }
        }
    }
}
