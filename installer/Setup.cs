using System;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

class LuminaCoderSetup
{
    [STAThread]
    static void Main()
    {
        string dest = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "Programs", "LuminaCoder");
        try
        {
            Directory.CreateDirectory(dest);
            string exe = Path.Combine(dest, "LuminaCoder.exe");

            using (Stream res = Assembly.GetExecutingAssembly().GetManifestResourceStream("LuminaCoder.exe"))
            {
                if (res == null) throw new InvalidOperationException("未找到内嵌程序资源。");
                using (FileStream fs = new FileStream(exe, FileMode.Create, FileAccess.Write, FileShare.None))
                {
                    res.CopyTo(fs);
                }
            }

            dynamic shell = Activator.CreateInstance(Type.GetTypeFromProgID("WScript.Shell"));
            string sm = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.Programs), "LuminaCoder.lnk");
            dynamic sc = shell.CreateShortcut(sm);
            sc.TargetPath = exe;
            sc.WorkingDirectory = dest;
            sc.Save();

            string desk = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), "LuminaCoder.lnk");
            dynamic dc = shell.CreateShortcut(desk);
            dc.TargetPath = exe;
            dc.WorkingDirectory = dest;
            dc.Save();

            MessageBox.Show("LuminaCoder 1.0.0 已安装到：\n" + dest +
                "\n\n已在开始菜单和桌面创建快捷方式。",
                "安装完成", MessageBoxButtons.OK, MessageBoxIcon.Information);
        }
        catch (Exception ex)
        {
            MessageBox.Show("安装失败：" + ex.Message, "错误",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
