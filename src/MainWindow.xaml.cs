using Microsoft.Web.WebView2.Core;
using Microsoft.Win32;
using System.ComponentModel;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows;
using System.Windows.Interop;

namespace CollisionTool
{
    public partial class MainWindow : Window
    {
        private static readonly string[] PythonCandidates = { "pythonw.exe", "pythonw", "python.exe", "python" };

        private readonly AppSettings _settings;
        private string? _currentBinPath;
        private string? _currentModelPath;

        private static readonly string HtmlOutputPath = Path.Combine(
            AppCache.TempDir, "collision_bounds_3d.html");

        public MainWindow()
        {
            InitializeComponent();
            ApplyScreenBasedSize();
            _settings = AppSettings.Load();

            // Runs before the first paint.
            SourceInitialized += (s, e) => EnableDarkTitleBar();

            Loaded += MainWindow_Loaded;
        }

        // Sizes the window relative to the screen work area.
        private void ApplyScreenBasedSize()
        {
            const double RefWorkW = 2560.0, RefWorkH = 1400.0;
            const double RefWinW = 1300.0, RefWinH = 850.0;
            const double MinWinW = 1000.0;
            const double MaxFill = 0.95;

            var wa = SystemParameters.WorkArea;
            double scale = Math.Min(wa.Width / RefWorkW, wa.Height / RefWorkH);

            double w = RefWinW * scale;
            double h = RefWinH * scale;

            if (w < MinWinW)
            {
                w = MinWinW;
                h = MinWinW * RefWinH / RefWinW;
            }

            double maxW = wa.Width * MaxFill;
            double maxH = wa.Height * MaxFill;
            if (w > maxW || h > maxH)
            {
                double f = Math.Min(maxW / w, maxH / h);
                w *= f;
                h *= f;
            }

            Width = w;
            Height = h;
        }

        private async void MainWindow_Loaded(object sender, RoutedEventArgs e)
        {
            if (!await InitWebViewAsync())
                return;

            if (!Engine.IsAvailable)
            {
                StatusText.Text = "Engine files not found next to the application. Reinstall the application.";
                OpenButton.IsEnabled = false;
            }
            else if (!string.IsNullOrWhiteSpace(_settings.LastBinPath) && File.Exists(_settings.LastBinPath))
            {
                if (!string.IsNullOrWhiteSpace(_settings.LastModelPath) && File.Exists(_settings.LastModelPath))
                    _currentModelPath = _settings.LastModelPath;
                await ProcessBinFileAsync(_settings.LastBinPath);
            }
        }

        private async Task<bool> InitWebViewAsync()
        {
            try
            {
                // Dark background until WebView2 navigates to the generated page.
                webView.DefaultBackgroundColor = System.Drawing.Color.FromArgb(255, 0x12, 0x12, 0x12);

                var userDataFolder = AppCache.WebView2Dir;
                Directory.CreateDirectory(userDataFolder);

                var env = await CoreWebView2Environment.CreateAsync(null, userDataFolder);
                await webView.EnsureCoreWebView2Async(env);

                webView.CoreWebView2.Settings.AreDevToolsEnabled = true;
                webView.CoreWebView2.Settings.IsStatusBarEnabled = false;
                return true;
            }
            catch (WebView2RuntimeNotFoundException)
            {
                ShowWebViewUnavailable("The WebView2 Runtime is not installed.");
                return false;
            }
            catch (Exception ex)
            {
                ShowWebViewUnavailable("WebView2 failed to start:\n" + ex.Message);
                return false;
            }
        }

        private void ShowWebViewUnavailable(string reason)
        {
            const string downloadUrl = "https://developer.microsoft.com/microsoft-edge/webview2/";

            StatusText.Text = "WebView2 Runtime is not available.";
            OpenButton.IsEnabled = false;
            ReloadButton.IsEnabled = false;
            ImportModelButton.IsEnabled = false;

            var result = MessageBox.Show(this,
                reason + "\n\nInstall the WebView2 Runtime, then restart the app.\n\nOpen the download page now?",
                "WebView2 Runtime", MessageBoxButton.YesNo, MessageBoxImage.Error);

            if (result == MessageBoxResult.Yes)
            {
                try { Process.Start(new ProcessStartInfo(downloadUrl) { UseShellExecute = true }); }
                catch { }
            }
        }

        [DllImport("dwmapi.dll")]
        private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int attrValue, int attrSize);

        private const int DWMWA_USE_IMMERSIVE_DARK_MODE = 20;

        private void EnableDarkTitleBar()
        {
            try
            {
                var hwnd = new WindowInteropHelper(this).Handle;
                int useDark = 1;
                DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ref useDark, sizeof(int));
            }
            catch
            {
                // Attribute not supported on this Windows version.
            }
        }

        private async void OpenButton_Click(object sender, RoutedEventArgs e)
        {
            var dlg = new OpenFileDialog { Filter = "Collision file (*.bin)|*.bin|All files (*.*)|*.*" };
            if (dlg.ShowDialog() == true)
            {
                // The reference model belongs to the loaded collision: eject it when a different .bin
                // is opened. Reload and ImportModel keep it.
                _currentModelPath = null;
                _settings.LastModelPath = "";
                _settings.Save();

                await ProcessBinFileAsync(dlg.FileName);
            }
        }

        private async void ReloadButton_Click(object sender, RoutedEventArgs e)
        {
            if (_currentBinPath != null)
                await ProcessBinFileAsync(_currentBinPath);
        }

        // Posts the model to the open page ("setCarModel" listener in core.py).
        private async void ImportModelButton_Click(object sender, RoutedEventArgs e)
        {
            var dlg = new OpenFileDialog { Filter = "3D car model (*.obj)|*.obj|All files (*.*)|*.*" };
            if (dlg.ShowDialog() != true) return;

            _currentModelPath = dlg.FileName;
            _settings.LastModelPath = dlg.FileName;
            _settings.Save();

            if (_currentBinPath == null) return;

            try
            {
                byte[] bytes = await File.ReadAllBytesAsync(dlg.FileName);
                string base64 = Convert.ToBase64String(bytes);
                string ext = Path.GetExtension(dlg.FileName).TrimStart('.').ToLowerInvariant();
                string filename = Path.GetFileName(dlg.FileName);

                string json = "{\"type\":\"setCarModel\",\"filename\":" + JsonEscape(filename) +
                              ",\"ext\":" + JsonEscape(ext) + ",\"base64\":" + JsonEscape(base64) + "}";
                webView.CoreWebView2.PostWebMessageAsJson(json);
                StatusText.Text = $"Model imported: {dlg.FileName}";
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, "Couldn't load the model file:\n" + ex.Message,
                    "Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
        }

        // Minimal JSON string escaper for the PostWebMessageAsJson payload (avoids System.Text.Json).
        private static string JsonEscape(string s)
        {
            var sb = new StringBuilder(s.Length + 2);
            sb.Append('"');
            foreach (char c in s)
            {
                switch (c)
                {
                    case '"': sb.Append("\\\""); break;
                    case '\\': sb.Append("\\\\"); break;
                    case '\n': sb.Append("\\n"); break;
                    case '\r': sb.Append("\\r"); break;
                    case '\t': sb.Append("\\t"); break;
                    default:
                        if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                        else sb.Append(c);
                        break;
                }
            }
            sb.Append('"');
            return sb.ToString();
        }

        private void AboutButton_Click(object sender, RoutedEventArgs e)
        {
            var about = new AboutWindow { Owner = this };
            about.ShowDialog();
        }

        private async Task ProcessBinFileAsync(string binPath)
        {
            if (!Engine.IsAvailable)
            {
                MessageBox.Show(this, "Engine files not found next to the application. Reinstall the application.",
                    "Missing engine", MessageBoxButton.OK, MessageBoxImage.Error);
                return;
            }
            if (!File.Exists(binPath))
            {
                MessageBox.Show(this, $"File not found:\n{binPath}", "Error", MessageBoxButton.OK, MessageBoxImage.Error);
                return;
            }

            SetBusy(true, "Processing file...");
            try
            {
                var (success, output, htmlPath) = await RunPythonScriptAsync(binPath, _currentModelPath);

                if (!success)
                {
                    MessageBox.Show(this,
                        string.IsNullOrWhiteSpace(output) ? "The Python engine failed to run." : output,
                        "Processing failed", MessageBoxButton.OK, MessageBoxImage.Error);
                    return;
                }
                if (!File.Exists(htmlPath))
                {
                    MessageBox.Show(this, "The engine ran but no output file was found:\n" + htmlPath,
                        "Error", MessageBoxButton.OK, MessageBoxImage.Error);
                    return;
                }

                // Cache-bust query so Reload loads the new file.
                string url = new Uri(htmlPath).AbsoluteUri + "?t=" + DateTime.UtcNow.Ticks;
                webView.CoreWebView2.Navigate(url);

                _currentBinPath = binPath;
                ReloadButton.IsEnabled = true;
                ImportModelButton.IsEnabled = true;
                _settings.LastBinPath = binPath;
                _settings.Save();
                StatusText.Text = $"Loaded: {binPath}";
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, "Unexpected error:\n" + ex.Message, "Error", MessageBoxButton.OK, MessageBoxImage.Error);
            }
            finally
            {
                SetBusy(false, null);
            }
        }

        private void SetBusy(bool busy, string? message)
        {
            LoadingOverlay.Visibility = busy ? Visibility.Visible : Visibility.Collapsed;
            if (message != null) StatusText.Text = message;
            OpenButton.IsEnabled = !busy;
            ReloadButton.IsEnabled = !busy && _currentBinPath != null;
            ImportModelButton.IsEnabled = !busy && _currentBinPath != null;
            AboutButton.IsEnabled = !busy;

        }

        // Writes Engine.ScriptSource to a temp file in Engine.WorkingDirectory, runs it and deletes it
        // afterwards. The engine always writes its HTML to HtmlOutputPath.
        private async Task<(bool success, string output, string htmlPath)> RunPythonScriptAsync(string binPath, string? modelPath)
        {
            string workingDir = Engine.WorkingDirectory;
            string htmlPath = HtmlOutputPath;
            Directory.CreateDirectory(Path.GetDirectoryName(htmlPath) ?? "");

            string tempScriptPath = Path.Combine(workingDir, Guid.NewGuid().ToString("N"));
            await File.WriteAllTextAsync(tempScriptPath, Engine.ScriptSource, new UTF8Encoding(false));

            try
            {
                Exception? lastError = null;

                var candidates = new List<string>();
                string bundledPy = Path.Combine(AppContext.BaseDirectory, "Python", "pythonw.exe");
                if (File.Exists(bundledPy))
                    candidates.Add(bundledPy);
                candidates.AddRange(PythonCandidates);

                foreach (var exe in candidates)
                {
                    var psi = new ProcessStartInfo
                    {
                        FileName = exe,
                        WorkingDirectory = workingDir,
                        UseShellExecute = false,
                        CreateNoWindow = true,
                        RedirectStandardOutput = true,
                        RedirectStandardError = true,
                        StandardOutputEncoding = Encoding.UTF8,
                        StandardErrorEncoding = Encoding.UTF8,
                    };
                    psi.ArgumentList.Add(tempScriptPath);
                    psi.ArgumentList.Add(binPath);
                    psi.ArgumentList.Add(htmlPath);
                    if (!string.IsNullOrWhiteSpace(modelPath))
                        psi.ArgumentList.Add(modelPath);
                    if (Engine.SurfaceNamesPath is string surfaceNamesPath)
                        psi.Environment["COLLISIONTOOL_SURFACE_NAMES"] = surfaceNamesPath;

                    try
                    {
                        using var process = new Process { StartInfo = psi };
                        var stdOut = new StringBuilder();
                        var stdErr = new StringBuilder();
                        process.OutputDataReceived += (s, e) => { if (e.Data != null) stdOut.AppendLine(e.Data); };
                        process.ErrorDataReceived += (s, e) => { if (e.Data != null) stdErr.AppendLine(e.Data); };

                        process.Start();
                        process.BeginOutputReadLine();
                        process.BeginErrorReadLine();
                        await process.WaitForExitAsync();

                        string combined = (stdOut + stdErr.ToString()).Trim();
                        bool hasError = process.ExitCode != 0 || combined.Contains("ERROR:") || combined.Contains("Traceback");
                        return (!hasError, combined, htmlPath);
                    }
                    catch (Win32Exception ex)
                    {
                        lastError = ex; // Interpreter not found, try the next candidate.
                    }
                }

                return (false, "Python was not found on PATH (tried pythonw/python). Install Python or add it to PATH.\n" + lastError?.Message, htmlPath);
            }
            finally
            {
                try { File.Delete(tempScriptPath); }
                catch { /* may still be locked (e.g. AV scan) */ }
            }
        }
    }
}
