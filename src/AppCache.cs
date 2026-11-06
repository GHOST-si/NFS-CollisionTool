using System.IO;

namespace CollisionTool
{
    /// <summary>
    /// Per-run cache and scratch data, stored under %LocalAppData%\CollisionTool.
    /// The install folder can be read-only (e.g. Program Files), so nothing is written there.
    ///
    ///   WebView2\  WebView2 profile/cache for the generated page.
    ///   Temp\      generated HTML for the last opened .bin.
    ///
    /// Both folders are cleared at startup (ClearStaleCache).
    /// The engine's Dependencies copy is created in the OS temp directory (see Engine.cs).
    /// </summary>
    internal static class AppCache
    {
        internal static string Root => Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "CollisionTool");

        internal static string WebView2Dir => Path.Combine(Root, "WebView2");
        internal static string TempDir => Path.Combine(Root, "Temp");

        /// <summary>
        /// Deletes and recreates the WebView2 and Temp folders. Call once at startup,
        /// before WebView2 or the engine use either path (see App.OnStartup).
        /// A folder that is still locked is left as is.
        /// </summary>
        internal static void ClearStaleCache()
        {
            TryResetDirectory(WebView2Dir);
            TryResetDirectory(TempDir);
        }

        private static void TryResetDirectory(string dir)
        {
            try
            {
                if (Directory.Exists(dir))
                    Directory.Delete(dir, recursive: true);
            }
            catch
            {
                // Locked (previous instance or AV scan): reuse the existing folder.
            }

            try
            {
                Directory.CreateDirectory(dir);
            }
            catch
            {
                // A failure here surfaces later in InitWebViewAsync/RunPythonScriptAsync.
            }
        }
    }
}
