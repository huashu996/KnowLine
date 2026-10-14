# GitHub ZIP 桌面启动修复 / Windows ZIP startup fix

修复版本：2026.10.14-blank-startup-fix。

## 原因与修复

Windows 会为浏览器下载并解压的文件保留 `Zone.Identifier`（Internet 来源标记）。原下载版的本地服务能启动，但 .NET 拒绝加载带标记的 `Python.Runtime.dll`，桌面窗口因此退出。实际复现错误为 `Failed to resolve Python.Runtime.Loader.Initialize`。同一 DLL 的 SHA-256 与 Git 检出版一致，Git 检出版桌面自检通过。

现在 `StartKnowline.cmd` 调用 `app/StartKnowline.ps1`，在打开桌面之前按发行清单验证主程序、页面入口与随包 DLL 的长度和 SHA-256。全部验证通过后，仅对清单内的运行库 DLL 使用 Windows `Unblock-File`。用户资料、导入文件、清单外文件以及系统安全设置不受影响。发行清单用于完整性检查，不是代码签名或独立的发布者认证。

Windows PowerShell 的执行策略参数只作用于这一次启动进程。程序仍未进行代码签名，首次双击 `.cmd` 时可能显示“未知发布者”；核对来自本仓库后点击“运行”。此修复解决的是之后的 DLL 加载失败，不会伪造发布者或关闭系统提示。

启动器等待真实桌面窗口出现；错误会显示在启动窗口并写入 `resource/.knowledge/startup.log`。缺失、损坏的程序文件会停止启动，提示重新完整解压。

## 自检

在解压后的根目录执行：

```bat
StartKnowline.cmd -SelfTest
```

自检使用实际打包 EXE、Edge WebView2 和前端页面，检查六个导航区域及本实例 API；结果保存在 `resource/.knowledge/desktop-startup-check.json`。自检窗口结束后自动关闭，正常使用仍双击 `StartKnowline.cmd`。

回归测试：`app/tests/test_windows_startup.py`，覆盖下载标记、重复准备、中文/空格/符号路径、文件损坏与缺失、清单越界，以及用户文件与清单外 DLL 保持原标记。

本次验证范围为 Windows 桌面启动和空白工作台加载，不代表重新测试所有研究、Office 或智能体功能。

## English

Downloaded ZIPs can retain Windows Internet-origin markers on DLLs. The original package started its local server but failed to load Python.Runtime.dll, preventing the desktop window from opening. The launcher now verifies packaged runtime files against the release manifest, unblocks only those verified DLLs, and reports startup failures visibly. It does not unblock imported documents, modify system security settings, or provide a code-signing identity.

See Microsoft's documentation for [Unblock-File](https://learn.microsoft.com/powershell/module/microsoft.powershell.utility/unblock-file) and [.NET remote assembly loading](https://learn.microsoft.com/dotnet/framework/configure-apps/file-schema/runtime/loadfromremotesources-element).
