using System.Windows;

namespace CollisionTool
{
    public partial class App : Application
    {
        protected override void OnStartup(StartupEventArgs e)
        {
            base.OnStartup(e);

            // Clear the cache before MainWindow exists, so WebView2 has not opened any of the files yet.
            // (App.xaml has no StartupUri for this reason.)
            AppCache.ClearStaleCache();

            var window = new MainWindow();
            MainWindow = window;
            window.Show();
        }

        protected override void OnExit(ExitEventArgs e)
        {
            Engine.Cleanup();
            base.OnExit(e);
        }
    }
}
