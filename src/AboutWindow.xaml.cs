using System.Reflection;
using System.Runtime.InteropServices;
using System.Windows;
using System.Windows.Interop;

namespace CollisionTool
{
    public partial class AboutWindow : Window
    {
        private const int DWMWA_USE_IMMERSIVE_DARK_MODE = 20;

        [DllImport("dwmapi.dll")]
        private static extern int DwmSetWindowAttribute(IntPtr hwnd, int attr, ref int attrValue, int attrSize);

        private void EnableDarkTitleBar()
        {
            try
            {
                var hwnd = new WindowInteropHelper(this).Handle;
                if (hwnd == IntPtr.Zero) return;

                int useDark = 1;
                DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ref useDark, sizeof(int));
            }
            catch
            {
                // Attribute not supported on this Windows version.
            }
        }

        public AboutWindow()
        {
            InitializeComponent();

            Height = Math.Min(Height, SystemParameters.WorkArea.Height * 0.9);
            Width = Math.Min(Width, SystemParameters.WorkArea.Width * 0.9);

            string version = Assembly.GetExecutingAssembly().GetName().Version?.ToString(3) ?? "Unknown";
            TxtVersion.Text = $"Version {version}";

            // Dark title bar before the first paint (see MainWindow).
            SourceInitialized += (s, e) => EnableDarkTitleBar();
        }

        private void Hyperlink_RequestNavigate(object sender, System.Windows.Navigation.RequestNavigateEventArgs e)
        {
            try
            {
                System.Diagnostics.Process.Start(
                    new System.Diagnostics.ProcessStartInfo(e.Uri.AbsoluteUri) { UseShellExecute = true });
            }
            catch
            {
                // No default browser.
            }
            e.Handled = true;
        }
    }
}
