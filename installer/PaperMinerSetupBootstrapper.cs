using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: AssemblyTitle("PaperMiner Setup")]
[assembly: AssemblyDescription("Single-file PaperMiner installer")]
[assembly: AssemblyCompany("PaperMiner Recovery")]
[assembly: AssemblyProduct("PaperMiner")]
[assembly: AssemblyVersion("1.4.24.0")]
[assembly: AssemblyFileVersion("1.4.24.0")]

internal static class PaperMinerSetupBootstrapper
{
    internal const string ResourceSuffix = "PaperMiner.Payload.zip";

    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length > 0 &&
            string.Equals(args[0], "--check", StringComparison.OrdinalIgnoreCase))
        {
            try
            {
                InstallerEngine.VerifyEmbeddedPayload();
                return 0;
            }
            catch
            {
                return 2;
            }
        }

        if (args.Length == 2 &&
            string.Equals(args[0], "--check-install-path", StringComparison.OrdinalIgnoreCase))
        {
            try
            {
                InstallerEngine.NormalizeInstallDirectory(args[1]);
                return 0;
            }
            catch
            {
                return 2;
            }
        }

        if (args.Length == 3 &&
            string.Equals(args[0], "--check-anaconda-path", StringComparison.OrdinalIgnoreCase))
        {
            try
            {
                InstallerEngine.NormalizeAnacondaDirectory(args[2], args[1]);
                return 0;
            }
            catch
            {
                return 2;
            }
        }

        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new SetupForm());
        return 0;
    }

    internal static Stream OpenPayload()
    {
        Assembly assembly = Assembly.GetExecutingAssembly();
        foreach (string name in assembly.GetManifestResourceNames())
        {
            if (name.EndsWith(ResourceSuffix, StringComparison.OrdinalIgnoreCase))
            {
                Stream stream = assembly.GetManifestResourceStream(name);
                if (stream != null)
                {
                    return stream;
                }
            }
        }

        throw new InvalidDataException("The embedded PaperMiner payload is missing.");
    }
}

internal sealed class SetupForm : Form
{
    private readonly TextBox installPathBox;
    private readonly Button browseButton;
    private readonly Label condaStatusLabel;
    private readonly Button condaDetectButton;
    private readonly Label anacondaPathLabel;
    private readonly TextBox anacondaPathBox;
    private readonly Button anacondaBrowseButton;
    private readonly Button condaPathDetectButton;
    private readonly Button fullDiskSearchButton;
    private readonly Label anacondaNote;
    private readonly CheckBox noCondaCheckBox;
    private readonly Button installButton;
    private readonly Button cancelButton;
    private readonly Label statusLabel;
    private readonly ProgressBar progressBar;
    private string detectedCondaRoot;
    private bool condaDetectionCompleted;
    private bool condaDetectionInProgress;
    private bool manualCondaDetectionInProgress;
    private bool fullDiskSearchInProgress;
    private bool anacondaLocationShown;
    private string manualCondaRoot;

    public SetupForm()
    {
        Text = "PaperMiner Setup";
        StartPosition = FormStartPosition.CenterScreen;
        FormBorderStyle = FormBorderStyle.FixedDialog;
        MaximizeBox = false;
        MinimizeBox = false;
        ClientSize = new Size(690, 580);
        Font = new Font("Microsoft YaHei UI", 9F, FontStyle.Regular, GraphicsUnit.Point);

        Label title = new Label();
        title.Text = "PaperMiner 1.4.24";
        title.Font = new Font(Font.FontFamily, 18F, FontStyle.Bold);
        title.Location = new Point(30, 25);
        title.AutoSize = true;
        Controls.Add(title);

        Label description = new Label();
        description.Text =
            "\u6b64 Setup.exe \u662f\u5b8c\u6574\u5b89\u88c5\u5305\u3002\u5b89\u88c5\u540e\u624d\u4f1a\u751f\u6210 PaperMiner.exe \u548c Uninstall.exe\u3002\r\n" +
            "\u53ef\u5b89\u88c5\u5230 C/D/E/F \u7b49\u4efb\u610f\u53ef\u5199\u76ee\u5f55\uff08\u4e0d\u80fd\u76f4\u63a5\u9009\u62e9\u78c1\u76d8\u6839\u76ee\u5f55\uff09\u3002\r\n" +
            "Setup \u5148\u68c0\u67e5\u660e\u786e\u8def\u5f84\u548c PaperMiner \u5df2\u4fdd\u5b58\u914d\u7f6e\uff1b\u627e\u4e0d\u5230\u65f6\u53ef\u76f4\u63a5\u786e\u8ba4\u672a\u5b89\u88c5\uff0c\u6216\u9009\u62e9\u989d\u5916\u68c0\u7d22\u3002\r\n" +
            "\u5b89\u88c5\u9636\u6bb5\u4f1a\u53e6\u884c\u663e\u793a PowerShell \u65e5\u5fd7\uff0c\u4e0d\u4f1a\u81ea\u52a8\u542f\u52a8\u4e3b\u7a0b\u5e8f\u3002";
        description.Location = new Point(33, 73);
        description.Size = new Size(625, 88);
        Controls.Add(description);

        Label pathLabel = new Label();
        pathLabel.Text = "\u5b89\u88c5\u4f4d\u7f6e";
        pathLabel.Location = new Point(33, 166);
        pathLabel.AutoSize = true;
        Controls.Add(pathLabel);

        installPathBox = new TextBox();
        installPathBox.Location = new Point(35, 190);
        installPathBox.Size = new Size(530, 27);
        installPathBox.Text = InstallerEngine.GetDefaultInstallDirectory();
        Controls.Add(installPathBox);

        browseButton = new Button();
        browseButton.Text = "\u6d4f\u89c8...";
        browseButton.Location = new Point(577, 188);
        browseButton.Size = new Size(80, 31);
        browseButton.Click += BrowseButtonClick;
        Controls.Add(browseButton);

        Label condaSectionLabel = new Label();
        condaSectionLabel.Text = "Conda \u73af\u5883\u68c0\u6d4b";
        condaSectionLabel.Location = new Point(33, 232);
        condaSectionLabel.AutoSize = true;
        Controls.Add(condaSectionLabel);

        condaStatusLabel = new Label();
        condaStatusLabel.Text = "\u7b49\u5f85\u68c0\u6d4b...";
        condaStatusLabel.Location = new Point(35, 256);
        condaStatusLabel.Size = new Size(530, 38);
        Controls.Add(condaStatusLabel);

        condaDetectButton = new Button();
        condaDetectButton.Text = "\u91cd\u65b0\u68c0\u6d4b";
        condaDetectButton.Location = new Point(577, 252);
        condaDetectButton.Size = new Size(80, 31);
        condaDetectButton.Enabled = false;
        condaDetectButton.Click += delegate { StartCondaDetection(); };
        Controls.Add(condaDetectButton);

        anacondaPathLabel = new Label();
        anacondaPathLabel.Text = "Conda \u6839\u76ee\u5f55\uff08\u81ea\u52a8\u68c0\u6d4b\u4e0d\u5230\u65f6\u6307\u5b9a\uff09";
        anacondaPathLabel.Location = new Point(33, 303);
        anacondaPathLabel.AutoSize = true;
        Controls.Add(anacondaPathLabel);

        anacondaPathBox = new TextBox();
        anacondaPathBox.Location = new Point(35, 327);
        anacondaPathBox.Size = new Size(410, 27);
        anacondaPathBox.Text = InstallerEngine.GetDefaultAnacondaDirectory(installPathBox.Text);
        Controls.Add(anacondaPathBox);

        condaPathDetectButton = new Button();
        condaPathDetectButton.Text = "\u68c0\u6d4b\u6b64\u76ee\u5f55";
        condaPathDetectButton.Location = new Point(455, 325);
        condaPathDetectButton.Size = new Size(100, 31);
        condaPathDetectButton.Click += delegate { StartManualCondaDetection(); };
        Controls.Add(condaPathDetectButton);

        anacondaBrowseButton = new Button();
        anacondaBrowseButton.Text = "\u6d4f\u89c8...";
        anacondaBrowseButton.Location = new Point(565, 325);
        anacondaBrowseButton.Size = new Size(92, 31);
        anacondaBrowseButton.Click += AnacondaBrowseButtonClick;
        Controls.Add(anacondaBrowseButton);

        fullDiskSearchButton = new Button();
        fullDiskSearchButton.Text = "\u5168\u76d8\u68c0\u7d22 Conda";
        fullDiskSearchButton.Location = new Point(455, 361);
        fullDiskSearchButton.Size = new Size(202, 31);
        fullDiskSearchButton.Click += delegate { StartFullDiskCondaSearch(); };
        Controls.Add(fullDiskSearchButton);

        anacondaNote = new Label();
        anacondaNote.Text = "\u6307\u5b9a\u76ee\u5f55\u68c0\u6d4b\u548c\u5168\u76d8\u68c0\u7d22\u5747\u4e3a\u53ef\u9009\u6838\u67e5\u3002\r\n\u786e\u8ba4\u65e0 Conda \u540e\uff0c\u4e0a\u65b9\u8def\u5f84\u5c06\u4f5c\u4e3a Anaconda \u4e0b\u8f7d\u5b89\u88c5\u76ee\u6807\u3002";
        anacondaNote.ForeColor = Color.DimGray;
        anacondaNote.Location = new Point(35, 360);
        anacondaNote.Size = new Size(410, 50);
        Controls.Add(anacondaNote);

        noCondaCheckBox = new CheckBox();
        noCondaCheckBox.Text = "\u6211\u786e\u8ba4\u672c\u673a\u6ca1\u6709 Conda\uff0c\u5141\u8bb8\u4ece\u6d4b\u901f\u540e\u9009\u5b9a\u7684\u955c\u50cf/\u5b98\u65b9\u6e90\u4e0b\u8f7d\u5e76\u5b89\u88c5 Anaconda";
        noCondaCheckBox.Location = new Point(35, 414);
        noCondaCheckBox.Size = new Size(622, 29);
        noCondaCheckBox.CheckedChanged += delegate { NoCondaCheckBoxChanged(); };
        Controls.Add(noCondaCheckBox);

        anacondaPathBox.TextChanged += delegate
        {
            if (!manualCondaDetectionInProgress)
            {
                manualCondaRoot = null;
                noCondaCheckBox.Enabled = anacondaLocationShown &&
                    detectedCondaRoot == null && manualCondaRoot == null;
                if (anacondaLocationShown && !noCondaCheckBox.Checked)
                {
                    condaStatusLabel.ForeColor = Color.DarkOrange;
                    condaStatusLabel.Text = "\u8def\u5f84\u5df2\u4fee\u6539\u3002\u53ef\u9009\u68c0\u6d4b\u73b0\u6709 Conda\uff0c\u6216\u76f4\u63a5\u786e\u8ba4\u672c\u673a\u6ca1\u6709 Conda\u3002";
                }
                UpdateInstallReadiness();
            }
        };

        progressBar = new ProgressBar();
        progressBar.Location = new Point(35, 451);
        progressBar.Size = new Size(622, 18);
        progressBar.Style = ProgressBarStyle.Marquee;
        progressBar.MarqueeAnimationSpeed = 25;
        progressBar.Visible = false;
        Controls.Add(progressBar);

        statusLabel = new Label();
        statusLabel.Text = "\u6b63\u5728\u51c6\u5907 Conda \u68c0\u6d4b...";
        statusLabel.Location = new Point(35, 475);
        statusLabel.Size = new Size(622, 35);
        Controls.Add(statusLabel);

        cancelButton = new Button();
        cancelButton.Text = "\u53d6\u6d88";
        cancelButton.Location = new Point(557, 525);
        cancelButton.Size = new Size(100, 36);
        cancelButton.Click += delegate { Close(); };
        Controls.Add(cancelButton);

        installButton = new Button();
        installButton.Text = "\u5b89\u88c5";
        installButton.Location = new Point(445, 525);
        installButton.Size = new Size(100, 36);
        installButton.Enabled = false;
        installButton.Click += InstallButtonClick;
        Controls.Add(installButton);

        AcceptButton = installButton;
        CancelButton = cancelButton;
        SetAnacondaLocationVisible(false);
        Shown += delegate { StartCondaDetection(); };
    }

    private void SetAnacondaLocationVisible(bool visible)
    {
        anacondaPathLabel.Visible = visible;
        anacondaPathBox.Visible = visible;
        condaPathDetectButton.Visible = visible;
        anacondaBrowseButton.Visible = visible;
        fullDiskSearchButton.Visible = visible;
        anacondaNote.Visible = visible;
        noCondaCheckBox.Visible = visible;
    }

    private void UpdateInstallReadiness()
    {
        bool ready = condaDetectionCompleted && !condaDetectionInProgress &&
            !manualCondaDetectionInProgress && !fullDiskSearchInProgress &&
            (detectedCondaRoot != null || manualCondaRoot != null ||
             noCondaCheckBox.Checked);
        installButton.Enabled = ready;
    }

    private void ApplyCondaDetectionResult(string condaRoot, string errorMessage)
    {
        detectedCondaRoot = string.IsNullOrWhiteSpace(condaRoot) ? null : condaRoot;
        if (detectedCondaRoot != null)
        {
            manualCondaRoot = null;
            noCondaCheckBox.Checked = false;
            noCondaCheckBox.Enabled = false;
            condaStatusLabel.ForeColor = Color.DarkGreen;
            condaStatusLabel.Text = "\u5df2\u68c0\u6d4b\u5230 Conda\uff0c\u5c06\u76f4\u63a5\u590d\u7528\uff1a" + detectedCondaRoot;
            SetAnacondaLocationVisible(false);
            UpdateInstallReadiness();
            return;
        }

        if (!anacondaLocationShown)
        {
            try
            {
                anacondaPathBox.Text = InstallerEngine.GetDefaultAnacondaDirectory(
                    installPathBox.Text);
            }
            catch
            {
                anacondaPathBox.Text = InstallerEngine.GetDefaultAnacondaDirectory(
                    InstallerEngine.GetDefaultInstallDirectory());
            }
            anacondaLocationShown = true;
        }
        condaStatusLabel.ForeColor = string.IsNullOrWhiteSpace(errorMessage)
            ? Color.DarkOrange
            : Color.Firebrick;
        condaStatusLabel.Text = string.IsNullOrWhiteSpace(errorMessage)
            ? "\u660e\u786e\u8def\u5f84\u548c\u5df2\u4fdd\u5b58\u914d\u7f6e\u4e2d\u672a\u627e\u5230 Conda\u3002\u53ef\u76f4\u63a5\u786e\u8ba4\u672a\u5b89\u88c5\uff0c\u6216\u9009\u62e9\u989d\u5916\u68c0\u7d22\u3002"
            : "Conda \u81ea\u52a8\u68c0\u6d4b\u5931\u8d25\u3002\u53ef\u76f4\u63a5\u786e\u8ba4\u672a\u5b89\u88c5\uff0c\u6216\u9009\u62e9\u989d\u5916\u68c0\u7d22\u3002";
        manualCondaRoot = null;
        noCondaCheckBox.Checked = false;
        SetAnacondaLocationVisible(true);
        condaPathDetectButton.Enabled = true;
        fullDiskSearchButton.Enabled = true;
        noCondaCheckBox.Enabled = true;
        UpdateInstallReadiness();
    }

    private void StartCondaDetection()
    {
        if (condaDetectionInProgress || manualCondaDetectionInProgress ||
            fullDiskSearchInProgress)
        {
            return;
        }

        condaDetectionInProgress = true;
        condaDetectionCompleted = false;
        detectedCondaRoot = null;
        manualCondaRoot = null;
        noCondaCheckBox.Checked = false;
        condaDetectButton.Enabled = false;
        condaPathDetectButton.Enabled = false;
        fullDiskSearchButton.Enabled = false;
        installButton.Enabled = false;
        SetAnacondaLocationVisible(false);
        condaStatusLabel.ForeColor = Color.DimGray;
        condaStatusLabel.Text = "\u6b63\u5728\u68c0\u67e5\u660e\u786e\u8def\u5f84\u548c PaperMiner \u5df2\u4fdd\u5b58\u914d\u7f6e...";
        statusLabel.Text = "\u8bf7\u7a0d\u5019\uff0c\u68c0\u6d4b\u5b8c\u6210\u540e\u624d\u80fd\u5f00\u59cb\u5b89\u88c5\u3002";
        progressBar.Visible = true;

        BackgroundWorker detector = new BackgroundWorker();
        detector.DoWork += delegate(object sender, DoWorkEventArgs arguments)
        {
            arguments.Result = InstallerEngine.ProbeExistingConda();
        };
        detector.RunWorkerCompleted += delegate(object sender, RunWorkerCompletedEventArgs arguments)
        {
            if (IsDisposed)
            {
                return;
            }

            condaDetectionInProgress = false;
            condaDetectionCompleted = true;
            progressBar.Visible = false;
            condaDetectButton.Enabled = true;
            if (arguments.Error == null)
            {
                ApplyCondaDetectionResult(arguments.Result as string, null);
            }
            else
            {
                ApplyCondaDetectionResult(null, arguments.Error.Message);
            }
            statusLabel.Text = "\u68c0\u6d4b\u5b8c\u6210\uff0c\u8bf7\u786e\u8ba4\u8def\u5f84\u540e\u5b89\u88c5\u3002";
            UpdateInstallReadiness();
        };
        detector.RunWorkerAsync();
    }

    private void StartManualCondaDetection()
    {
        if (!condaDetectionCompleted || condaDetectionInProgress ||
            manualCondaDetectionInProgress || fullDiskSearchInProgress)
        {
            return;
        }

        string path = anacondaPathBox.Text;
        if (string.IsNullOrWhiteSpace(path))
        {
            condaStatusLabel.ForeColor = Color.Firebrick;
            condaStatusLabel.Text = "\u8bf7\u5148\u8f93\u5165\u6216\u6d4f\u89c8 Conda \u6839\u76ee\u5f55\u3002";
            return;
        }

        manualCondaDetectionInProgress = true;
        manualCondaRoot = null;
        noCondaCheckBox.Checked = false;
        condaPathDetectButton.Enabled = false;
        anacondaBrowseButton.Enabled = false;
        fullDiskSearchButton.Enabled = false;
        noCondaCheckBox.Enabled = false;
        installButton.Enabled = false;
        progressBar.Visible = true;
        statusLabel.Text = "\u6b63\u5728\u9a8c\u8bc1\u7528\u6237\u6307\u5b9a\u7684 Conda \u76ee\u5f55...";

        BackgroundWorker detector = new BackgroundWorker();
        detector.DoWork += delegate(object sender, DoWorkEventArgs arguments)
        {
            arguments.Result = InstallerEngine.ProbeCondaDirectory(path);
        };
        detector.RunWorkerCompleted += delegate(object sender, RunWorkerCompletedEventArgs arguments)
        {
            if (IsDisposed)
            {
                return;
            }

            manualCondaDetectionInProgress = false;
            progressBar.Visible = false;
            condaPathDetectButton.Enabled = true;
            anacondaBrowseButton.Enabled = true;
            fullDiskSearchButton.Enabled = true;
            if (arguments.Error != null)
            {
                condaStatusLabel.ForeColor = Color.Firebrick;
                condaStatusLabel.Text = "\u6307\u5b9a\u76ee\u5f55\u68c0\u6d4b\u5931\u8d25\uff1a" + arguments.Error.Message;
                manualCondaRoot = null;
            }
            else if (arguments.Result is string &&
                !string.IsNullOrWhiteSpace((string)arguments.Result))
            {
                manualCondaRoot = ((string)arguments.Result).Trim();
                condaStatusLabel.ForeColor = Color.DarkGreen;
                condaStatusLabel.Text = "\u5df2\u627e\u5230\u6307\u5b9a\u7684 Conda\uff0c\u5c06\u590d\u7528\uff1a" + manualCondaRoot;
            }
            else
            {
                condaStatusLabel.ForeColor = Color.Firebrick;
                condaStatusLabel.Text = "\u8be5\u76ee\u5f55\u4e2d\u6ca1\u6709\u53ef\u7528 Conda\u3002\u5982\u679c\u786e\u5b9e\u672a\u5b89\u88c5\uff0c\u52fe\u9009\u4e0b\u65b9\u786e\u8ba4\u540e\u624d\u4f1a\u4e0b\u8f7d\u3002";
                manualCondaRoot = null;
            }
            noCondaCheckBox.Enabled = manualCondaRoot == null;
            statusLabel.Text = "\u6307\u5b9a\u76ee\u5f55\u68c0\u6d4b\u5b8c\u6210\u3002";
            UpdateInstallReadiness();
        };
        detector.RunWorkerAsync();
    }

    private void StartFullDiskCondaSearch()
    {
        if (!condaDetectionCompleted || condaDetectionInProgress ||
            manualCondaDetectionInProgress || fullDiskSearchInProgress)
        {
            return;
        }

        fullDiskSearchInProgress = true;
        manualCondaRoot = null;
        noCondaCheckBox.Checked = false;
        condaPathDetectButton.Enabled = false;
        anacondaBrowseButton.Enabled = false;
        anacondaPathBox.Enabled = false;
        fullDiskSearchButton.Enabled = false;
        noCondaCheckBox.Enabled = false;
        installButton.Enabled = false;
        progressBar.Visible = true;
        condaStatusLabel.ForeColor = Color.DarkOrange;
        condaStatusLabel.Text = "\u6b63\u5728\u53ea\u8bfb\u68c0\u7d22\u672c\u5730\u78c1\u76d8\uff0c\u8fd9\u53ef\u80fd\u9700\u8981\u8f83\u957f\u65f6\u95f4...";
        statusLabel.Text = "\u6b63\u5728\u51c6\u5907\u5168\u76d8\u68c0\u7d22...";

        BackgroundWorker detector = new BackgroundWorker();
        detector.WorkerReportsProgress = true;
        detector.DoWork += delegate(object sender, DoWorkEventArgs arguments)
        {
            BackgroundWorker activeDetector = (BackgroundWorker)sender;
            arguments.Result = InstallerEngine.ProbeAllLocalDrives(
                delegate(string currentPath)
                {
                    activeDetector.ReportProgress(0, currentPath);
                });
        };
        detector.ProgressChanged += delegate(object sender, ProgressChangedEventArgs arguments)
        {
            string currentPath = arguments.UserState as string;
            if (!string.IsNullOrWhiteSpace(currentPath))
            {
                statusLabel.Text = "\u6b63\u5728\u68c0\u7d22\uff1a" + currentPath;
            }
        };
        detector.RunWorkerCompleted += delegate(object sender, RunWorkerCompletedEventArgs arguments)
        {
            if (IsDisposed)
            {
                return;
            }

            fullDiskSearchInProgress = false;
            progressBar.Visible = false;
            condaPathDetectButton.Enabled = true;
            anacondaBrowseButton.Enabled = true;
            anacondaPathBox.Enabled = true;
            fullDiskSearchButton.Enabled = true;
            if (arguments.Error != null)
            {
                manualCondaRoot = null;
                condaStatusLabel.ForeColor = Color.Firebrick;
                condaStatusLabel.Text = "\u5168\u76d8\u68c0\u7d22\u5931\u8d25\uff1a" + arguments.Error.Message;
                statusLabel.Text = "\u5168\u76d8\u68c0\u7d22\u672a\u5b8c\u6210\uff0c\u8bf7\u6539\u7528\u6307\u5b9a\u76ee\u5f55\u68c0\u6d4b\u3002";
            }
            else if (arguments.Result is string &&
                !string.IsNullOrWhiteSpace((string)arguments.Result))
            {
                manualCondaRoot = ((string)arguments.Result).Trim();
                manualCondaDetectionInProgress = true;
                anacondaPathBox.Text = manualCondaRoot;
                manualCondaDetectionInProgress = false;
                condaStatusLabel.ForeColor = Color.DarkGreen;
                condaStatusLabel.Text = "\u5168\u76d8\u68c0\u7d22\u5df2\u627e\u5230 Conda\uff0c\u5c06\u590d\u7528\uff1a" + manualCondaRoot;
                statusLabel.Text = "\u5168\u76d8\u68c0\u7d22\u5b8c\u6210\uff0c\u53ef\u76f4\u63a5\u5b89\u88c5\u3002";
            }
            else
            {
                manualCondaRoot = null;
                condaStatusLabel.ForeColor = Color.DarkOrange;
                condaStatusLabel.Text = "\u5168\u76d8\u68c0\u7d22\u672a\u627e\u5230\u53ef\u7528 Conda\u3002\u786e\u8ba4\u672a\u5b89\u88c5\u540e\uff0c\u624d\u53ef\u52fe\u9009\u4e0b\u65b9\u786e\u8ba4\u6846\u3002";
                statusLabel.Text = "\u5168\u76d8\u68c0\u7d22\u5b8c\u6210\uff0c\u672a\u627e\u5230 Conda\u3002";
            }
            noCondaCheckBox.Enabled = manualCondaRoot == null;
            UpdateInstallReadiness();
        };
        detector.RunWorkerAsync();
    }

    private void NoCondaCheckBoxChanged()
    {
        if (noCondaCheckBox.Checked &&
            (detectedCondaRoot != null || manualCondaRoot != null))
        {
            noCondaCheckBox.Checked = false;
            return;
        }

        if (noCondaCheckBox.Checked)
        {
            manualCondaRoot = null;
            condaStatusLabel.ForeColor = Color.DarkOrange;
            condaStatusLabel.Text = "\u5df2\u786e\u8ba4\u672a\u5b89\u88c5 Conda\uff0c\u5b89\u88c5\u6309\u94ae\u5c06\u4ece\u591a\u4e2a\u4e2d\u56fd\u955c\u50cf\u4e0b\u8f7d Anaconda\u3002";
        }
        else if (manualCondaRoot == null && anacondaLocationShown)
        {
            condaStatusLabel.ForeColor = Color.DarkOrange;
            condaStatusLabel.Text = "\u53ef\u9009\u68c0\u6d4b\u6307\u5b9a\u76ee\u5f55\u6216\u5168\u76d8\u68c0\u7d22\uff0c\u4e5f\u53ef\u76f4\u63a5\u52fe\u9009\u201c\u6211\u786e\u8ba4\u672c\u673a\u6ca1\u6709 Conda\u201d\u3002";
        }
        UpdateInstallReadiness();
    }

    private void BrowseButtonClick(object sender, EventArgs eventArgs)
    {
        using (FolderBrowserDialog dialog = new FolderBrowserDialog())
        {
            dialog.Description = "\u9009\u62e9 PaperMiner \u5b89\u88c5\u76ee\u5f55";
            dialog.SelectedPath = installPathBox.Text;
            dialog.ShowNewFolderButton = true;
            if (dialog.ShowDialog(this) == DialogResult.OK)
            {
                installPathBox.Text = dialog.SelectedPath;
            }
        }
    }

    private void AnacondaBrowseButtonClick(object sender, EventArgs eventArgs)
    {
        using (FolderBrowserDialog dialog = new FolderBrowserDialog())
        {
            dialog.Description = "\u9009\u62e9 Anaconda \u5b89\u88c5\u76ee\u5f55";
            dialog.SelectedPath = anacondaPathBox.Text;
            dialog.ShowNewFolderButton = true;
            if (dialog.ShowDialog(this) == DialogResult.OK)
            {
                anacondaPathBox.Text = dialog.SelectedPath;
            }
        }
    }

    private void InstallButtonClick(object sender, EventArgs eventArgs)
    {
        if (!condaDetectionCompleted || condaDetectionInProgress ||
            manualCondaDetectionInProgress || fullDiskSearchInProgress)
        {
            MessageBox.Show(
                "\u8bf7\u7b49\u5f85 Conda \u68c0\u6d4b\u5b8c\u6210\u3002",
                "PaperMiner Setup",
                MessageBoxButtons.OK,
                MessageBoxIcon.Information);
            return;
        }

        string installDirectory;
        string condaDirectory;
        string anacondaDirectory;
        bool allowAnacondaBootstrap;
        try
        {
            installDirectory = InstallerEngine.NormalizeInstallDirectory(installPathBox.Text);
            condaDirectory = detectedCondaRoot ?? manualCondaRoot;
            allowAnacondaBootstrap = false;
            if (string.IsNullOrWhiteSpace(condaDirectory))
            {
                if (!noCondaCheckBox.Checked)
                {
                    throw new ArgumentException(
                        "\u8bf7\u5148\u6307\u5b9a Conda \u6839\u76ee\u5f55\u5e76\u70b9\u51fb\u68c0\u6d4b\u6b64\u76ee\u5f55\uff1b\u5982\u679c\u786e\u8ba4\u6ca1\u6709 Conda\uff0c\u8bf7\u5148\u52fe\u9009\u786e\u8ba4\u6846\u3002");
                }
                anacondaDirectory = InstallerEngine.NormalizeAnacondaDirectory(
                    anacondaPathBox.Text,
                    installDirectory);
                allowAnacondaBootstrap = true;
            }
            else
            {
                condaDirectory = InstallerEngine.NormalizeAnacondaDirectory(
                    condaDirectory,
                    installDirectory);
                anacondaDirectory = condaDirectory;
            }
            InstallerEngine.VerifyEmbeddedPayload();
        }
        catch (Exception exception)
        {
            MessageBox.Show(exception.Message, "PaperMiner Setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        installButton.Enabled = false;
        browseButton.Enabled = false;
        installPathBox.Enabled = false;
        condaDetectButton.Enabled = false;
        condaPathDetectButton.Enabled = false;
        anacondaBrowseButton.Enabled = false;
        anacondaPathBox.Enabled = false;
        fullDiskSearchButton.Enabled = false;
        noCondaCheckBox.Enabled = false;
        cancelButton.Enabled = false;
        progressBar.Visible = true;
        statusLabel.Text = "\u6b63\u5728\u89e3\u5305\u7a0b\u5e8f\u6587\u4ef6...";
        BackgroundWorker worker = new BackgroundWorker();
        worker.WorkerReportsProgress = true;
        worker.DoWork += delegate(object workerSender, DoWorkEventArgs workerArguments)
        {
            BackgroundWorker activeWorker = (BackgroundWorker)workerSender;
            string[] targets = (string[])workerArguments.Argument;
            string target = targets[0];
            string condaTarget = targets[1];
            string anacondaTarget = targets[2];
            bool allowBootstrap = string.Equals(targets[3], "1", StringComparison.Ordinal);
            InstallerEngine.InstallPayload(target);
            activeWorker.ReportProgress(0,
                allowBootstrap
                    ? "\u5df2\u786e\u8ba4\u65e0 Conda\uff0c\u6b63\u5728\u4ece\u591a\u4e2a\u4e2d\u56fd\u955c\u50cf\u4e0b\u8f7d Anaconda..."
                    : "\u6b63\u5728\u590d\u7528\u5df2\u627e\u5230\u7684 Conda\uff0c\u8bf7\u67e5\u770b PowerShell \u65e5\u5fd7\u7a97\u53e3...");

            int exitCode = InstallerEngine.RunDependencySetup(
                target,
                condaTarget,
                anacondaTarget,
                allowBootstrap);
            if (exitCode != 0)
            {
                throw new InvalidOperationException(
                    "Dependency setup failed with exit code " + exitCode +
                    ". Review the Setup log in the installed logs folder.");
            }

            InstallerEngine.RegisterUninstall(target);
            workerArguments.Result = target;
        };
        worker.ProgressChanged += delegate(object workerSender, ProgressChangedEventArgs progressArguments)
        {
            statusLabel.Text = progressArguments.UserState as string;
        };
        worker.RunWorkerCompleted += delegate(object workerSender, RunWorkerCompletedEventArgs completedArguments)
        {
            progressBar.Visible = false;
            if (completedArguments.Error == null)
            {
                statusLabel.Text = "\u5b89\u88c5\u5b8c\u6210";
                MessageBox.Show(
                    "PaperMiner \u5df2\u5b89\u88c5\u3002\r\n\r\n\u73b0\u5728\u53ef\u4ee5\u901a\u8fc7\u684c\u9762\u5feb\u6377\u65b9\u5f0f\u6216\u5b89\u88c5\u76ee\u5f55\u4e2d\u7684 PaperMiner.exe \u542f\u52a8\u3002",
                    "PaperMiner Setup",
                    MessageBoxButtons.OK,
                    MessageBoxIcon.Information);
                Close();
                return;
            }

            statusLabel.Text = "\u5b89\u88c5\u672a\u5b8c\u6210";
            browseButton.Enabled = true;
            installPathBox.Enabled = true;
            condaDetectButton.Enabled = true;
            condaPathDetectButton.Enabled = detectedCondaRoot == null;
            anacondaBrowseButton.Enabled = detectedCondaRoot == null;
            anacondaPathBox.Enabled = detectedCondaRoot == null;
            fullDiskSearchButton.Enabled = detectedCondaRoot == null;
            noCondaCheckBox.Enabled = detectedCondaRoot == null &&
                manualCondaRoot == null;
            cancelButton.Enabled = true;
            UpdateInstallReadiness();
            MessageBox.Show(
                completedArguments.Error.Message +
                "\r\n\r\nExtracted program files and setup backups were preserved for inspection.",
                "PaperMiner Setup",
                MessageBoxButtons.OK,
                MessageBoxIcon.Error);
        };
        worker.RunWorkerAsync(new string[]
        {
            installDirectory,
            condaDirectory ?? string.Empty,
            anacondaDirectory,
            allowAnacondaBootstrap ? "1" : "0"
        });
    }
}

internal static class InstallerEngine
{
    private const string UninstallRegistryPath =
        @"Software\Microsoft\Windows\CurrentVersion\Uninstall\PaperMiner";

    private static readonly string[] RequiredEntries =
    {
        "PaperMiner.exe",
        "Uninstall.exe",
        "Setup-PaperMiner.ps1",
        "Maintenance-PaperMiner.ps1",
        "PaperMiner.Runtime.ps1",
        "PaperMiner.AnacondaBootstrap.ps1",
        "scripts/batch_pdf_processor_gui.py",
        "scripts/mineru_path_policy.py",
        "scripts/torch_runtime_policy.py",
        "scripts/run_recovery.py",
        "scripts/title_extractor.py",
        "scripts/raw_output_policy.py"
    };

    public static string GetDefaultInstallDirectory()
    {
        try
        {
            using (RegistryKey key = Registry.CurrentUser.OpenSubKey(UninstallRegistryPath))
            {
                if (key != null)
                {
                    string existing = key.GetValue("InstallLocation") as string;
                    if (!string.IsNullOrWhiteSpace(existing))
                    {
                        return existing;
                    }
                }
            }
        }
        catch
        {
        }

        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Programs",
            "PaperMiner");
    }

    public static string NormalizeInstallDirectory(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new ArgumentException("Select an installation directory.");
        }

        string fullPath = Path.GetFullPath(Environment.ExpandEnvironmentVariables(path.Trim()));
        ValidateBatchSafePath(fullPath);
        string root = Path.GetPathRoot(fullPath);
        if (string.Equals(fullPath.TrimEnd(Path.DirectorySeparatorChar),
                root.TrimEnd(Path.DirectorySeparatorChar),
                StringComparison.OrdinalIgnoreCase))
        {
            throw new ArgumentException("A drive root cannot be used as the installation directory.");
        }

        return fullPath.TrimEnd(Path.DirectorySeparatorChar);
    }

    public static string GetDefaultAnacondaDirectory(string paperMinerDirectory)
    {
        string fullPath = NormalizeInstallDirectory(paperMinerDirectory);
        string root = Path.GetPathRoot(fullPath);
        if (!string.IsNullOrWhiteSpace(root) &&
            !root.StartsWith("C:", StringComparison.OrdinalIgnoreCase))
        {
            return Path.Combine(root, "PaperMinerRuntime", "Anaconda3");
        }

        return Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "PaperMiner",
            "Anaconda3");
    }

    public static string NormalizeAnacondaDirectory(string path, string paperMinerDirectory)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            throw new ArgumentException("Select an Anaconda installation directory.");
        }

        string fullPath = Path.GetFullPath(
            Environment.ExpandEnvironmentVariables(path.Trim()))
            .TrimEnd(Path.DirectorySeparatorChar);
        ValidateBatchSafePath(fullPath);
        string root = Path.GetPathRoot(fullPath).TrimEnd(Path.DirectorySeparatorChar);
        if (string.Equals(fullPath, root, StringComparison.OrdinalIgnoreCase))
        {
            throw new ArgumentException(
                "A drive root cannot be used as the Anaconda installation directory.");
        }

        string paperMinerPath = NormalizeInstallDirectory(paperMinerDirectory);
        string paperMinerBoundary = paperMinerPath + Path.DirectorySeparatorChar;
        string anacondaBoundary = fullPath + Path.DirectorySeparatorChar;
        if (string.Equals(fullPath, paperMinerPath, StringComparison.OrdinalIgnoreCase) ||
            fullPath.StartsWith(paperMinerBoundary, StringComparison.OrdinalIgnoreCase) ||
            paperMinerPath.StartsWith(anacondaBoundary, StringComparison.OrdinalIgnoreCase))
        {
            throw new ArgumentException(
                "PaperMiner and Anaconda must use separate, non-overlapping directories.");
        }

        return fullPath;
    }

    private static void ValidateBatchSafePath(string path)
    {
        if (path.IndexOf('!') >= 0 || path.IndexOf('%') >= 0)
        {
            throw new ArgumentException(
                "Installation paths cannot contain ! or % characters.");
        }
    }

    public static void VerifyEmbeddedPayload()
    {
        HashSet<string> names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        using (Stream stream = PaperMinerSetupBootstrapper.OpenPayload())
        using (ZipArchive archive = new ZipArchive(stream, ZipArchiveMode.Read, false))
        {
            foreach (ZipArchiveEntry entry in archive.Entries)
            {
                string normalized = ValidateEntryName(entry.FullName);
                if (normalized.Length > 0)
                {
                    names.Add(normalized.Replace('\\', '/'));
                }
            }
        }

        foreach (string required in RequiredEntries)
        {
            if (!names.Contains(required))
            {
                throw new InvalidDataException("Installer payload is missing: " + required);
            }
        }

        foreach (string name in names)
        {
            string lower = name.ToLowerInvariant();
            if (lower == "setup.exe" || lower == ".env" ||
                lower == ".paperminer-runtime.json" ||
                lower.StartsWith("input/") || lower.StartsWith("output/") ||
                lower.StartsWith("logs/"))
            {
                throw new InvalidDataException("Installer payload contains mutable or recursive content: " + name);
            }
        }
    }

    public static void InstallPayload(string installDirectory)
    {
        string stagingDirectory = Path.Combine(
            Path.GetTempPath(),
            "PaperMinerSetup_" + Guid.NewGuid().ToString("N"));
        string backupDirectory = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "PaperMiner",
            "SetupBackups",
            DateTime.Now.ToString("yyyyMMdd_HHmmss"));

        Directory.CreateDirectory(stagingDirectory);
        try
        {
            ExtractPayloadTo(stagingDirectory);
            Directory.CreateDirectory(installDirectory);

            foreach (string sourceFile in Directory.GetFiles(stagingDirectory, "*", SearchOption.AllDirectories))
            {
                string relative = sourceFile.Substring(stagingDirectory.Length)
                    .TrimStart(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
                string destination = GetSafeDestination(installDirectory, relative);
                string destinationDirectory = Path.GetDirectoryName(destination);
                Directory.CreateDirectory(destinationDirectory);

                if (File.Exists(destination))
                {
                    string backup = GetSafeDestination(backupDirectory, relative);
                    Directory.CreateDirectory(Path.GetDirectoryName(backup));
                    File.Copy(destination, backup, false);
                }

                File.Copy(sourceFile, destination, true);
            }
        }
        finally
        {
            if (Directory.Exists(stagingDirectory))
            {
                Directory.Delete(stagingDirectory, true);
            }
        }
    }

    private static string GetCondaCommandAtRoot(string root)
    {
        string condaBat = Path.Combine(root, "condabin", "conda.bat");
        if (File.Exists(condaBat))
        {
            return condaBat;
        }

        string condaExe = Path.Combine(root, "Scripts", "conda.exe");
        return File.Exists(condaExe) ? condaExe : null;
    }

    public static string ProbeCondaDirectory(string path)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            return null;
        }

        string selected = Path.GetFullPath(
            Environment.ExpandEnvironmentVariables(path.Trim()))
            .TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar);
        List<string> candidates = new List<string>();
        candidates.Add(selected);
        // FolderBrowserDialog users sometimes select the parent (for example
        // D:\\Program Files). Check only the standard immediate child names;
        // do not recursively scan arbitrary user data.
        foreach (string name in new string[]
            { "Anaconda3", "anaconda3", "Anaconda", "anaconda", "Miniconda3", "miniconda3", "Miniconda", "miniconda" })
        {
            candidates.Add(Path.Combine(selected, name));
        }

        foreach (string root in candidates)
        {
            string command = GetCondaCommandAtRoot(root);
            if (command == null)
            {
                continue;
            }

            string systemDirectory = Environment.GetFolderPath(Environment.SpecialFolder.System);
            string cmd = Path.Combine(systemDirectory, "cmd.exe");
            if (!File.Exists(cmd))
            {
                cmd = "cmd.exe";
            }

            ProcessStartInfo startInfo = new ProcessStartInfo();
            if (command.EndsWith(".bat", StringComparison.OrdinalIgnoreCase))
            {
                startInfo.FileName = cmd;
                startInfo.Arguments = "/d /c call " + QuoteArgument(command) + " --version";
            }
            else
            {
                startInfo.FileName = command;
                startInfo.Arguments = "--version";
            }
            startInfo.WorkingDirectory = root;
            startInfo.UseShellExecute = false;
            startInfo.CreateNoWindow = true;
            startInfo.WindowStyle = ProcessWindowStyle.Hidden;
            try
            {
                using (Process process = Process.Start(startInfo))
                {
                    if (process == null)
                    {
                        continue;
                    }

                    if (!process.WaitForExit(15000))
                    {
                        try { process.Kill(); } catch { }
                        continue;
                    }
                    if (process.ExitCode == 0)
                    {
                        return Path.GetFullPath(root).TrimEnd(
                            Path.DirectorySeparatorChar,
                            Path.AltDirectorySeparatorChar);
                    }
                }
            }
            catch
            {
                // Continue to the next candidate so a stale child directory
                // cannot block the user from choosing a valid Conda root.
            }
        }

        return null;
    }

    private static bool ShouldSkipFullDiskDirectory(string path)
    {
        try
        {
            FileAttributes attributes = File.GetAttributes(path);
            if ((attributes & FileAttributes.ReparsePoint) != 0)
            {
                return true;
            }

            string name = new DirectoryInfo(path).Name;
            foreach (string skippedName in new string[]
                { "$Recycle.Bin", "System Volume Information", "Recovery", "Windows", "WinSxS", "node_modules", ".git" })
            {
                if (string.Equals(name, skippedName, StringComparison.OrdinalIgnoreCase))
                {
                    return true;
                }
            }
        }
        catch
        {
            return true;
        }

        return false;
    }

    private static string ProbeDirectoryTree(
        string root,
        HashSet<string> visited,
        ref int inspectedDirectories,
        Action<string> progress)
    {
        Stack<string> pending = new Stack<string>();
        pending.Push(root);
        if (progress != null)
        {
            progress(root);
        }

        while (pending.Count > 0)
        {
            string current = pending.Pop();
            string normalized;
            try
            {
                normalized = Path.GetFullPath(current).TrimEnd(
                    Path.DirectorySeparatorChar,
                    Path.AltDirectorySeparatorChar);
                if (normalized.Length == 2 && normalized[1] == ':')
                {
                    normalized += Path.DirectorySeparatorChar;
                }
            }
            catch
            {
                continue;
            }

            if (!visited.Add(normalized))
            {
                continue;
            }

            if (GetCondaCommandAtRoot(normalized) != null)
            {
                string detected = ProbeCondaDirectory(normalized);
                if (!string.IsNullOrWhiteSpace(detected))
                {
                    return detected;
                }
            }

            inspectedDirectories += 1;
            if (progress != null && inspectedDirectories % 250 == 0)
            {
                progress(normalized);
            }

            string[] children;
            try
            {
                children = Directory.GetDirectories(normalized);
            }
            catch
            {
                continue;
            }

            foreach (string child in children)
            {
                if (!ShouldSkipFullDiskDirectory(child))
                {
                    pending.Push(child);
                }
            }
        }

        return null;
    }

    public static string ProbeDirectoryTree(string root, Action<string> progress)
    {
        HashSet<string> visited = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        int inspectedDirectories = 0;
        return ProbeDirectoryTree(root, visited, ref inspectedDirectories, progress);
    }

    public static string ProbeAllLocalDrives(Action<string> progress)
    {
        HashSet<string> visited = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        int inspectedDirectories = 0;

        foreach (DriveInfo drive in DriveInfo.GetDrives())
        {
            try
            {
                if (!drive.IsReady ||
                    (drive.DriveType != DriveType.Fixed &&
                     drive.DriveType != DriveType.Removable))
                {
                    continue;
                }
            }
            catch
            {
                continue;
            }

            string detected = ProbeDirectoryTree(
                drive.RootDirectory.FullName,
                visited,
                ref inspectedDirectories,
                progress);
            if (!string.IsNullOrWhiteSpace(detected))
            {
                return detected;
            }
        }

        return null;
    }

    public static string ProbeExistingConda()
    {
        string stagingDirectory = Path.Combine(
            Path.GetTempPath(),
            "PaperMinerCondaProbe_" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(stagingDirectory);
        try
        {
            ExtractPayloadTo(stagingDirectory);
            string script = Path.Combine(stagingDirectory, "Setup-PaperMiner.ps1");
            string powershell = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.System),
                @"WindowsPowerShell\v1.0\powershell.exe");
            if (!File.Exists(powershell))
            {
                powershell = "powershell.exe";
            }

            ProcessStartInfo startInfo = new ProcessStartInfo();
            startInfo.FileName = powershell;
            startInfo.Arguments =
                "-NoLogo -NoProfile -ExecutionPolicy Bypass -File " +
                QuoteArgument(script) + " -DetectCondaOnly";
            startInfo.WorkingDirectory = stagingDirectory;
            startInfo.UseShellExecute = false;
            startInfo.CreateNoWindow = true;
            startInfo.WindowStyle = ProcessWindowStyle.Hidden;
            startInfo.RedirectStandardOutput = true;
            startInfo.RedirectStandardError = true;

            using (Process process = Process.Start(startInfo))
            {
                if (process == null)
                {
                    throw new InvalidOperationException(
                        "The Conda detection process did not start.");
                }

                string output = process.StandardOutput.ReadToEnd();
                string error = process.StandardError.ReadToEnd();
                process.WaitForExit();
                if (process.ExitCode == 3)
                {
                    return null;
                }
                if (process.ExitCode != 0)
                {
                    throw new InvalidOperationException(
                        "Conda detection failed with exit code " + process.ExitCode +
                        ". " + error.Trim());
                }

                const string prefix = "PAPERMINER_CONDA_ROOT_BASE64=";
                foreach (string line in output.Split(
                    new string[] { "\r\n", "\n" },
                    StringSplitOptions.RemoveEmptyEntries))
                {
                    string trimmed = line.Trim();
                    if (!trimmed.StartsWith(prefix, StringComparison.Ordinal))
                    {
                        continue;
                    }

                    string encoded = trimmed.Substring(prefix.Length);
                    string root = System.Text.Encoding.UTF8.GetString(
                        Convert.FromBase64String(encoded));
                    if (!string.IsNullOrWhiteSpace(root))
                    {
                        string verified = ProbeCondaDirectory(root.Trim());
                        if (!string.IsNullOrWhiteSpace(verified))
                        {
                            return verified;
                        }
                    }
                }

                throw new InvalidOperationException(
                    "Conda detection succeeded without returning a root directory.");
            }
        }
        finally
        {
            try
            {
                if (Directory.Exists(stagingDirectory))
                {
                    Directory.Delete(stagingDirectory, true);
                }
            }
            catch
            {
            }
        }
    }

    private static void ExtractPayloadTo(string destinationRoot)
    {
        using (Stream stream = PaperMinerSetupBootstrapper.OpenPayload())
        using (ZipArchive archive = new ZipArchive(stream, ZipArchiveMode.Read, false))
        {
            foreach (ZipArchiveEntry entry in archive.Entries)
            {
                string relative = ValidateEntryName(entry.FullName);
                if (relative.Length == 0)
                {
                    continue;
                }

                string destination = GetSafeDestination(destinationRoot, relative);
                if (entry.FullName.EndsWith("/", StringComparison.Ordinal) ||
                    entry.FullName.EndsWith("\\", StringComparison.Ordinal))
                {
                    Directory.CreateDirectory(destination);
                    continue;
                }

                Directory.CreateDirectory(Path.GetDirectoryName(destination));
                using (Stream input = entry.Open())
                using (FileStream output = new FileStream(destination, FileMode.CreateNew, FileAccess.Write))
                {
                    input.CopyTo(output);
                }
            }
        }
    }

    private static string ValidateEntryName(string entryName)
    {
        string normalized = entryName.Replace('/', '\\').TrimStart('\\');
        if (normalized.Length == 0)
        {
            return string.Empty;
        }
        if (Path.IsPathRooted(normalized) || normalized == ".." ||
            normalized.StartsWith("..\\", StringComparison.Ordinal) ||
            normalized.Contains("\\..\\"))
        {
            throw new InvalidDataException("Unsafe payload path: " + entryName);
        }
        return normalized;
    }

    private static string GetSafeDestination(string root, string relative)
    {
        string fullRoot = Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) +
            Path.DirectorySeparatorChar;
        string destination = Path.GetFullPath(Path.Combine(fullRoot, relative));
        if (!destination.StartsWith(fullRoot, StringComparison.OrdinalIgnoreCase))
        {
            throw new InvalidDataException("Path escaped the installation boundary: " + relative);
        }
        return destination;
    }

    public static int RunDependencySetup(
        string installDirectory,
        string condaDirectory,
        string anacondaDirectory,
        bool allowAnacondaBootstrap)
    {
        string script = Path.Combine(installDirectory, "Setup-PaperMiner.ps1");
        string powershell = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.System),
            @"WindowsPowerShell\v1.0\powershell.exe");
        if (!File.Exists(powershell))
        {
            powershell = "powershell.exe";
        }

        ProcessStartInfo startInfo = new ProcessStartInfo();
        startInfo.FileName = powershell;
        string condaPath = string.IsNullOrWhiteSpace(condaDirectory)
            ? anacondaDirectory
            : condaDirectory;
        startInfo.Arguments =
            "-NoLogo -NoProfile -ExecutionPolicy Bypass -File " + QuoteArgument(script) +
            " -Bootstrap -CondaInstallRoot " + QuoteArgument(condaPath) +
            (allowAnacondaBootstrap ? " -AllowAnacondaBootstrap" : string.Empty);
        startInfo.WorkingDirectory = installDirectory;
        startInfo.UseShellExecute = true;
        startInfo.WindowStyle = ProcessWindowStyle.Normal;

        using (Process process = Process.Start(startInfo))
        {
            process.WaitForExit();
            return process.ExitCode;
        }
    }

    public static void RegisterUninstall(string installDirectory)
    {
        using (RegistryKey key = Registry.CurrentUser.CreateSubKey(UninstallRegistryPath))
        {
            key.SetValue("DisplayName", "PaperMiner 1.4.24", RegistryValueKind.String);
            key.SetValue("DisplayVersion", "1.4.24", RegistryValueKind.String);
            key.SetValue("Publisher", "PaperMiner Recovery", RegistryValueKind.String);
            key.SetValue("InstallLocation", installDirectory, RegistryValueKind.String);
            key.SetValue("DisplayIcon", Path.Combine(installDirectory, "PaperMiner.exe"), RegistryValueKind.String);
            key.SetValue("UninstallString", QuoteArgument(Path.Combine(installDirectory, "Uninstall.exe")), RegistryValueKind.String);
            key.SetValue("NoModify", 1, RegistryValueKind.DWord);
            key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
        }
    }

    private static string QuoteArgument(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }
}
