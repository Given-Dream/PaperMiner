using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;
using System.Threading;
using System.Web.Script.Serialization;

[assembly: AssemblyTitle("PaperMiner")]
[assembly: AssemblyDescription("PaperMiner direct GUI launcher without PowerShell")]
[assembly: AssemblyCompany("PaperMiner Recovery")]
[assembly: AssemblyProduct("PaperMiner")]
[assembly: AssemblyVersion("1.4.19.0")]
[assembly: AssemblyFileVersion("1.4.19.0")]

internal static class PaperMinerLauncher
{
    private const uint MbIconError = 0x00000010;
    private const uint JobObjectLimitKillOnJobClose = 0x00002000;
    private const int JobObjectExtendedLimitInformation = 9;
    private const string InstanceMutexName = @"Local\PaperMiner_SingleInstance";
    private const int MaxCrashesInWindow = 3;
    private const int RestartDelayMilliseconds = 2000;
    private static readonly TimeSpan CrashWindow = TimeSpan.FromMinutes(10);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int MessageBoxW(IntPtr hWnd, string text, string caption, uint type);

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern IntPtr CreateJobObject(IntPtr securityAttributes, string name);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(
        IntPtr job,
        int informationClass,
        ref JobObjectExtendedLimitInformationData information,
        uint informationLength);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool CloseHandle(IntPtr handle);

    [STAThread]
    private static int Main(string[] args)
    {
        string baseDirectory = AppDomain.CurrentDomain.BaseDirectory;
        string guiScript = Path.Combine(baseDirectory, "scripts", "batch_pdf_processor_gui.py");

        if (args.Length > 0 &&
            string.Equals(args[0], "--check", StringComparison.OrdinalIgnoreCase))
        {
            return File.Exists(guiScript) ? 0 : 2;
        }

        if (args.Length > 0 &&
            string.Equals(args[0], "--check-restart-policy", StringComparison.OrdinalIgnoreCase))
        {
            List<DateTime> testCrashes = new List<DateTime>();
            DateTime testNow = DateTime.UtcNow;
            bool first = RegisterCrashAndShouldRestart(testCrashes, testNow);
            bool second = RegisterCrashAndShouldRestart(testCrashes, testNow.AddSeconds(1));
            bool third = RegisterCrashAndShouldRestart(testCrashes, testNow.AddSeconds(2));
            return first && second && !third ? 0 : 2;
        }

        if (!File.Exists(guiScript))
        {
            ShowError("The PaperMiner GUI payload is incomplete. Re-run Setup.exe.");
            return 2;
        }

        bool createdNew;
        using (Mutex instanceMutex = new Mutex(
            true,
            InstanceMutexName,
            out createdNew))
        {
            if (!createdNew)
            {
                // 鼠标双击或连续点击只保留第一个启动请求。
                return 0;
            }

            try
            {
                RuntimeInfo runtime = FindRuntime(baseDirectory);
                if (runtime == null)
                {
                    ShowError("The MinerU runtime was not found. Run Setup.exe to install or repair PaperMiner.");
                    return 2;
                }

                string python = Path.Combine(runtime.EnvironmentPath, "pythonw.exe");
                if (!File.Exists(python))
                {
                    python = runtime.PythonExe;
                }

                List<DateTime> crashTimes = new List<DateTime>();
                bool recoverAfterCrash = false;
                while (true)
                {
                    GuiRunResult result = RunGuiOnce(
                        python,
                        guiScript,
                        baseDirectory,
                        recoverAfterCrash);
                    if (result.ExitCode == 0)
                    {
                        return 0;
                    }

                    DateTime crashTime = DateTime.UtcNow;
                    LogLauncher(
                        "PaperMiner GUI exited unexpectedly. ExitCode=" +
                        result.ExitCode.ToString() + ", RuntimeSeconds=" +
                        result.Runtime.TotalSeconds.ToString("F1") + ".");
                    if (!RegisterCrashAndShouldRestart(crashTimes, crashTime))
                    {
                        ShowError(
                            "PaperMiner stopped after three unexpected exits within ten minutes.\n\n" +
                            "The unfinished batch remains saved and will be offered again on the next launch. " +
                            "Review PaperMiner-launcher-error.log and the latest PaperMiner log before retrying.");
                        return result.ExitCode;
                    }

                    // Closing this run's job has already removed every orphaned
                    // MinerU child.  The restarted GUI reconnects to the durable
                    // SQLite queue and re-runs only the interrupted PDF boundary.
                    Thread.Sleep(RestartDelayMilliseconds);
                    recoverAfterCrash = true;
                }
            }
            catch (Exception exception)
            {
                ShowError("PaperMiner could not start.\n\n" + exception.ToString());
                return 1;
            }
            finally
            {
                try
                {
                    instanceMutex.ReleaseMutex();
                }
                catch (ApplicationException)
                {
                }
            }
        }
    }

    private static GuiRunResult RunGuiOnce(
        string python,
        string guiScript,
        string baseDirectory,
        bool recoverAfterCrash)
    {
        ProcessStartInfo startInfo = new ProcessStartInfo();
        startInfo.FileName = python;
        startInfo.Arguments =
            "-s -X utf8 " + QuoteArgument(guiScript) + " --paperminer-launcher" +
            (recoverAfterCrash ? " --recover-after-crash" : "");
        startInfo.WorkingDirectory = baseDirectory;
        startInfo.UseShellExecute = false;
        startInfo.CreateNoWindow = true;
        startInfo.WindowStyle = ProcessWindowStyle.Hidden;

        Stopwatch stopwatch = Stopwatch.StartNew();
        int exitCode;
        using (KillOnCloseJob job = new KillOnCloseJob())
        {
            Process process = Process.Start(startInfo);
            if (process == null)
            {
                throw new InvalidOperationException("The Python GUI process did not start.");
            }
            using (process)
            {
                job.TryAssign(process);
                process.WaitForExit();
                exitCode = process.ExitCode;
            }
        }
        stopwatch.Stop();
        GuiRunResult result = new GuiRunResult();
        result.ExitCode = exitCode;
        result.Runtime = stopwatch.Elapsed;
        return result;
    }

    private static bool RegisterCrashAndShouldRestart(
        List<DateTime> crashTimes,
        DateTime crashTime)
    {
        crashTimes.RemoveAll(delegate(DateTime value)
        {
            return crashTime - value > CrashWindow;
        });
        crashTimes.Add(crashTime);
        return crashTimes.Count < MaxCrashesInWindow;
    }

    private static void LogLauncher(string message)
    {
        try
        {
            string localData = Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData);
            string logDirectory = Path.Combine(localData, "PaperMiner", "logs");
            Directory.CreateDirectory(logDirectory);
            File.AppendAllText(
                Path.Combine(logDirectory, "PaperMiner-launcher-error.log"),
                DateTime.Now.ToString("o") + " " + message + Environment.NewLine,
                System.Text.Encoding.UTF8);
        }
        catch
        {
            try
            {
                string fallback = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "logs");
                Directory.CreateDirectory(fallback);
                File.AppendAllText(
                    Path.Combine(fallback, "PaperMiner-launcher-error.log"),
                    DateTime.Now.ToString("o") + " " + message + Environment.NewLine,
                    System.Text.Encoding.UTF8);
            }
            catch
            {
            }
        }
    }

    private sealed class GuiRunResult
    {
        public int ExitCode { get; set; }
        public TimeSpan Runtime { get; set; }
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IoCounters
    {
        public ulong ReadOperationCount;
        public ulong WriteOperationCount;
        public ulong OtherOperationCount;
        public ulong ReadTransferCount;
        public ulong WriteTransferCount;
        public ulong OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JobObjectBasicLimitInformation
    {
        public long PerProcessUserTimeLimit;
        public long PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize;
        public UIntPtr MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass;
        public uint SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JobObjectExtendedLimitInformationData
    {
        public JobObjectBasicLimitInformation BasicLimitInformation;
        public IoCounters IoInfo;
        public UIntPtr ProcessMemoryLimit;
        public UIntPtr JobMemoryLimit;
        public UIntPtr PeakProcessMemoryUsed;
        public UIntPtr PeakJobMemoryUsed;
    }

    private sealed class KillOnCloseJob : IDisposable
    {
        private IntPtr handle;

        public KillOnCloseJob()
        {
            handle = CreateJobObject(IntPtr.Zero, null);
            if (handle == IntPtr.Zero)
            {
                return;
            }

            JobObjectExtendedLimitInformationData information =
                new JobObjectExtendedLimitInformationData();
            information.BasicLimitInformation.LimitFlags = JobObjectLimitKillOnJobClose;
            uint size = (uint)Marshal.SizeOf(typeof(JobObjectExtendedLimitInformationData));
            if (!SetInformationJobObject(
                    handle,
                    JobObjectExtendedLimitInformation,
                    ref information,
                    size))
            {
                CloseHandle(handle);
                handle = IntPtr.Zero;
            }
        }

        public bool TryAssign(Process process)
        {
            return handle != IntPtr.Zero &&
                process != null &&
                AssignProcessToJobObject(handle, process.Handle);
        }

        public void Dispose()
        {
            if (handle != IntPtr.Zero)
            {
                CloseHandle(handle);
                handle = IntPtr.Zero;
            }
        }
    }

    private static RuntimeInfo FindRuntime(string baseDirectory)
    {
        string configPath = Path.Combine(baseDirectory, ".paperminer-runtime.json");
        if (File.Exists(configPath))
        {
            try
            {
                JavaScriptSerializer serializer = new JavaScriptSerializer();
                RuntimeConfig config = serializer.Deserialize<RuntimeConfig>(
                    File.ReadAllText(configPath));
                RuntimeInfo configured = CreateRuntime(config.PythonExe, config.EnvironmentPath);
                if (configured != null)
                {
                    return configured;
                }
            }
            catch
            {
            }
        }

        string condaPrefix = Environment.GetEnvironmentVariable("CONDA_PREFIX");
        RuntimeInfo active = CreateRuntime(
            string.IsNullOrWhiteSpace(condaPrefix) ? null : Path.Combine(condaPrefix, "python.exe"),
            condaPrefix);
        if (active != null &&
            string.Equals(new DirectoryInfo(active.EnvironmentPath).Name, "MinerU",
                StringComparison.OrdinalIgnoreCase))
        {
            return active;
        }

        foreach (string root in GetCondaRoots())
        {
            string environmentPath = Path.Combine(root, "envs", "MinerU");
            RuntimeInfo runtime = CreateRuntime(
                Path.Combine(environmentPath, "python.exe"), environmentPath);
            if (runtime != null)
            {
                return runtime;
            }
        }

        return null;
    }

    private static RuntimeInfo CreateRuntime(string pythonExe, string environmentPath)
    {
        if (string.IsNullOrWhiteSpace(environmentPath) && !string.IsNullOrWhiteSpace(pythonExe))
        {
            environmentPath = Path.GetDirectoryName(pythonExe);
        }
        if (string.IsNullOrWhiteSpace(pythonExe) && !string.IsNullOrWhiteSpace(environmentPath))
        {
            pythonExe = Path.Combine(environmentPath, "python.exe");
        }
        if (string.IsNullOrWhiteSpace(pythonExe) || string.IsNullOrWhiteSpace(environmentPath) ||
            !File.Exists(pythonExe))
        {
            return null;
        }

        RuntimeInfo runtime = new RuntimeInfo();
        runtime.PythonExe = Path.GetFullPath(pythonExe);
        runtime.EnvironmentPath = Path.GetFullPath(environmentPath);
        return runtime;
    }

    private static IEnumerable<string> GetCondaRoots()
    {
        List<string> roots = new List<string>();
        AddUnique(roots, Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "miniconda3"));
        AddUnique(roots, Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.UserProfile), "anaconda3"));
        AddUnique(roots, Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "miniconda3"));
        AddUnique(roots, Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "anaconda3"));
        AddUnique(roots, Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "miniconda3"));
        AddUnique(roots, Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "anaconda3"));

        string currentUser = Environment.UserName;
        foreach (DriveInfo drive in DriveInfo.GetDrives())
        {
            try
            {
                if (!drive.IsReady)
                {
                    continue;
                }
                foreach (string distribution in new string[] { "miniconda3", "anaconda3" })
                {
                    AddUnique(roots, Path.Combine(drive.RootDirectory.FullName, distribution));
                    AddUnique(roots, Path.Combine(
                        drive.RootDirectory.FullName, "soft", currentUser, distribution));
                    AddUnique(roots, Path.Combine(
                        drive.RootDirectory.FullName, "soft", "admin", distribution));
                }
            }
            catch
            {
            }
        }

        return roots;
    }

    private static void AddUnique(List<string> values, string value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return;
        }
        foreach (string existing in values)
        {
            if (string.Equals(existing, value, StringComparison.OrdinalIgnoreCase))
            {
                return;
            }
        }
        values.Add(value);
    }

    private static string QuoteArgument(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }

    private static void ShowError(string message)
    {
        LogLauncher(message);
        MessageBoxW(IntPtr.Zero, message, "PaperMiner", MbIconError);
    }

    private sealed class RuntimeConfig
    {
        public string PythonExe { get; set; }
        public string EnvironmentPath { get; set; }
    }

    private sealed class RuntimeInfo
    {
        public string PythonExe { get; set; }
        public string EnvironmentPath { get; set; }
    }
}
