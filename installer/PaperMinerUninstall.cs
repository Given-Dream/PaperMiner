using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("PaperMiner Maintenance")]
[assembly: AssemblyDescription("PaperMiner reinstall and safe uninstall")]
[assembly: AssemblyCompany("PaperMiner Recovery")]
[assembly: AssemblyProduct("PaperMiner")]
[assembly: AssemblyVersion("1.4.13.0")]
[assembly: AssemblyFileVersion("1.4.13.0")]

internal static class PaperMinerUninstall
{
    [STAThread]
    private static int Main(string[] args)
    {
        string baseDirectory = AppDomain.CurrentDomain.BaseDirectory;
        string script = Path.Combine(baseDirectory, "Maintenance-PaperMiner.ps1");

        if (args.Length > 0 &&
            string.Equals(args[0], "--check", StringComparison.OrdinalIgnoreCase))
        {
            return File.Exists(script) ? 0 : 2;
        }

        if (!File.Exists(script))
        {
            MessageBox.Show(
                "Maintenance-PaperMiner.ps1 was not found.",
                "PaperMiner",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
            return 2;
        }

        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new MaintenanceForm(baseDirectory, script));
        return 0;
    }
}

internal sealed class MaintenanceForm : Form
{
    private readonly string baseDirectory;
    private readonly string script;

    public MaintenanceForm(string baseDirectory, string script)
    {
        this.baseDirectory = baseDirectory;
        this.script = script;

        Text = "PaperMiner \u7ef4\u62a4";
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        ClientSize = new Size(650, 280);
        Font = new Font("Microsoft YaHei UI", 9F, FontStyle.Regular, GraphicsUnit.Point);

        Label title = new Label();
        title.Text = "PaperMiner \u91cd\u88c5\u4e0e\u5378\u8f7d";
        title.Font = new Font(Font.FontFamily, 16F, FontStyle.Bold);
        title.Location = new Point(28, 24);
        title.AutoSize = true;
        Controls.Add(title);

        Label explanation = new Label();
        explanation.Text =
            "\u91cd\u88c5\uff1a\u4ec5\u79fb\u9664 MinerU Conda \u73af\u5883\uff0c\u7136\u540e\u542f\u52a8 Setup.exe\u3002\r\n" +
            "\u5378\u8f7d\uff1a\u79fb\u9664 MinerU \u73af\u5883\u3001\u8fd0\u884c\u8bb0\u5f55\u548c\u672c\u7a0b\u5e8f\u5feb\u6377\u65b9\u5f0f\u3002\r\n\r\n" +
            "\u4e24\u79cd\u64cd\u4f5c\u90fd\u4fdd\u7559\u6a21\u578b\u3001input/output \u4ee5\u53ca\u9879\u76ee\u6587\u4ef6\uff0c\u5e76\u663e\u793a PowerShell \u65e5\u5fd7\u3002";
        explanation.Location = new Point(31, 72);
        explanation.Size = new Size(585, 105);
        Controls.Add(explanation);

        Button cancelButton = new Button();
        cancelButton.Text = "\u53d6\u6d88";
        cancelButton.Location = new Point(277, 215);
        cancelButton.Size = new Size(105, 38);
        cancelButton.Click += delegate { Close(); };
        Controls.Add(cancelButton);

        Button reinstallButton = new Button();
        reinstallButton.Text = "\u91cd\u88c5";
        reinstallButton.Location = new Point(394, 215);
        reinstallButton.Size = new Size(105, 38);
        reinstallButton.Click += delegate { ConfirmAndStart("Reinstall"); };
        Controls.Add(reinstallButton);

        Button uninstallButton = new Button();
        uninstallButton.Text = "\u5378\u8f7d";
        uninstallButton.Location = new Point(511, 215);
        uninstallButton.Size = new Size(105, 38);
        uninstallButton.Click += delegate { ConfirmAndStart("Uninstall"); };
        Controls.Add(uninstallButton);

        CancelButton = cancelButton;
    }

    private void ConfirmAndStart(string mode)
    {
        bool reinstall = string.Equals(mode, "Reinstall", StringComparison.Ordinal);
        string title = reinstall ? "\u786e\u8ba4\u91cd\u88c5" : "\u786e\u8ba4\u5378\u8f7d";
        string message = reinstall
            ? "\u5c06\u79fb\u9664 MinerU Conda \u73af\u5883\u5e76\u542f\u52a8 Setup.exe\u3002\r\n\u9879\u76ee\u6570\u636e\u548c\u6a21\u578b\u4f1a\u4fdd\u7559\u3002\u7ee7\u7eed\uff1f"
            : "\u5c06\u79fb\u9664 MinerU Conda \u73af\u5883\u548c PaperMiner \u5feb\u6377\u65b9\u5f0f\u3002\r\n\u9879\u76ee\u76ee\u5f55\u3001input/output \u548c\u6a21\u578b\u4f1a\u4fdd\u7559\u3002\u7ee7\u7eed\uff1f";

        if (MessageBox.Show(message, title, MessageBoxButtons.YesNo, MessageBoxIcon.Warning) !=
            DialogResult.Yes)
        {
            return;
        }

        try
        {
            string systemDirectory = Environment.GetFolderPath(Environment.SpecialFolder.System);
            string powershell = Path.Combine(systemDirectory, @"WindowsPowerShell\v1.0\powershell.exe");
            if (!File.Exists(powershell))
            {
                powershell = "powershell.exe";
            }

            ProcessStartInfo startInfo = new ProcessStartInfo();
            startInfo.FileName = powershell;
            startInfo.Arguments =
                "-NoLogo -NoProfile -ExecutionPolicy Bypass -File " +
                QuoteArgument(script) + " -Mode " + mode;
            startInfo.WorkingDirectory = baseDirectory;
            startInfo.UseShellExecute = true;
            startInfo.WindowStyle = ProcessWindowStyle.Normal;
            Process.Start(startInfo);
            Close();
        }
        catch (Exception exception)
        {
            MessageBox.Show(
                exception.Message,
                "PaperMiner",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
        }
    }

    private static string QuoteArgument(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }
}
