using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;

[assembly: AssemblyTitle("PaperMiner Setup")]
[assembly: AssemblyDescription("PaperMiner dependency setup and repair")]
[assembly: AssemblyCompany("PaperMiner Recovery")]
[assembly: AssemblyProduct("PaperMiner")]
[assembly: AssemblyVersion("1.4.24.0")]
[assembly: AssemblyFileVersion("1.4.24.0")]

internal static class PaperMinerSetupLauncher
{
    private const uint MbIconError = 0x00000010;

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int MessageBoxW(IntPtr hWnd, string text, string caption, uint type);

    [STAThread]
    private static int Main(string[] args)
    {
        string baseDirectory = AppDomain.CurrentDomain.BaseDirectory;
        string setupScript = Path.Combine(baseDirectory, "Setup-PaperMiner.ps1");
        string runtimeScript = Path.Combine(baseDirectory, "PaperMiner.Runtime.ps1");

        if (args.Length > 0 &&
            string.Equals(args[0], "--check", StringComparison.OrdinalIgnoreCase))
        {
            return File.Exists(setupScript) && File.Exists(runtimeScript) ? 0 : 2;
        }

        if (!File.Exists(setupScript) || !File.Exists(runtimeScript))
        {
            ShowError("Setup payload is incomplete. Extract the full release package first.");
            return 2;
        }

        try
        {
            string powershell = GetPowerShellPath();
            ProcessStartInfo startInfo = new ProcessStartInfo();
            startInfo.FileName = powershell;
            startInfo.Arguments =
                "-NoLogo -NoProfile -ExecutionPolicy Bypass -File " + QuoteArgument(setupScript);
            startInfo.WorkingDirectory = baseDirectory;
            startInfo.UseShellExecute = true;
            startInfo.WindowStyle = ProcessWindowStyle.Normal;
            Process.Start(startInfo);
            return 0;
        }
        catch (Exception exception)
        {
            ShowError("PaperMiner Setup could not start.\n\n" + exception.Message);
            return 1;
        }
    }

    private static string GetPowerShellPath()
    {
        string systemDirectory = Environment.GetFolderPath(Environment.SpecialFolder.System);
        string powershell = Path.Combine(systemDirectory, @"WindowsPowerShell\v1.0\powershell.exe");
        return File.Exists(powershell) ? powershell : "powershell.exe";
    }

    private static string QuoteArgument(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }

    private static void ShowError(string message)
    {
        MessageBoxW(IntPtr.Zero, message, "PaperMiner Setup", MbIconError);
    }
}
