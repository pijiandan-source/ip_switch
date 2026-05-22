# 内外网切换工具

这是一个面向 Windows 10/11 的 Python tkinter GUI 工具，用于切换公司内网 DHCP 和外网静态网络配置。程序最终可通过 GitHub Actions 打包为单文件 `NetworkSwitcher.exe`。

## 功能

- 列出当前启用的 Windows 网卡
- 切换到内网 DHCP：IP 自动获取、DNS 自动获取，并删除本工具管理的外网静态路由
- 外网模式先配置临时扫描 IP，再扫描同网段可能可用 IP，最后应用用户选择或自动选择的最终 IP
- 配置静态 IP、DNS、路由后等待一小段时间，让 Windows 网卡、ARP 和路由表刷新
- ping 网关失败时会按配置重试，不会只 ping 一次就判定失败
- 使用 `ping -n 1 -w 800` 做扫描检测，并用 `arp -a` 作为辅助判断
- 测试网关连通性，并在 GUI 日志中显示命令、returncode、stdout、stderr
- GitHub Actions 自动打包并发布 `NetworkSwitcher.exe`

## 权限要求

修改网卡 IP、DNS 和路由表必须使用管理员权限。请右键以管理员身份运行程序或 exe。程序启动后也会提示是否需要管理员权限，并提供“以管理员权限重启”按钮。

## 外网配置流程

1. 选择网卡。
2. 输入临时扫描 IP、子网掩码、网关、DNS。
3. 点击“配置临时 IP 并扫描”。
4. 程序先把网卡配置为临时 IP，让网卡进入目标外网网段。
5. 程序等待 `NETWORK_APPLY_DELAY_SECONDS`，默认 2.0 秒。
6. 程序 ping 网关；失败后按 `PING_RETRY_COUNT` 和 `PING_RETRY_INTERVAL_SECONDS` 重试。
7. 程序开始扫描同网段候选 IP。
8. 从“扫描结果”中手动选择一个可能可用 IP，点击“应用选中 IP”；也可以勾选“扫描后自动选择第一个可用 IP”。
9. 程序把网卡改成最终 IP，配置 DNS，添加 `ROUTES` 中的路由。
10. 程序再次等待 2.0 秒，然后 ping 网关并重试验证。

临时 IP 不是最终 IP。它的作用只是让网卡先进入目标外网网段，从而更可靠地扫描同网段地址。最终 IP 是扫描后手动选择或自动选择出来的 IP。

## 默认外网配置

- 临时扫描 IP：`112.13.121.254`
- 备用临时扫描 IP：`112.13.121.253`
- 子网掩码：`255.255.255.128`
- 网关：`112.13.121.129`
- DNS：`223.5.5.5`

根据默认配置计算出的网段为 `112.13.121.128/25`。扫描会跳过网络地址、广播地址、网关地址和当前临时扫描 IP。

## 可调整配置

在 `config.py` 中可以调整：

```python
NETWORK_APPLY_DELAY_SECONDS = 2.0
PING_RETRY_COUNT = 2
PING_RETRY_INTERVAL_SECONDS = 1.0
SCAN_PING_COUNT = 1
SCAN_PING_TIMEOUT_MS = 800
CLEAR_ARP_CACHE_BEFORE_SCAN = False
```

`CLEAR_ARP_CACHE_BEFORE_SCAN` 默认关闭。开启后会在临时 IP 配置生效等待后执行 `arp -d *`，失败不会中断流程，但会写入日志。这个操作可能影响当前机器 ARP 缓存，所以默认不启用。

## 扫描可用 IP 的局限性

扫描结果只是“可能可用”。部分设备禁 ping 或 ARP 缓存不完整，不能 100% 保证无冲突。应用最终 IP 前，请确认不会与其他设备冲突；如没有扫描到可用 IP，可以尝试更换临时扫描 IP 或联系管理员确认可用地址。

## Windows 中文和黑框兼容

程序执行 `netsh`、`route`、`ping`、`arp` 等命令时使用 bytes 捕获输出，再按 `utf-8`、`gbk`、`cp936`、`mbcs` 顺序兼容解码，无法识别的字符会替换显示，不会因为命令输出编码导致 GUI 崩溃。

命令执行使用 `subprocess.run([...])`，不使用 `shell=True`。Windows 下通过标准库 `subprocess.CREATE_NO_WINDOW` 和 `STARTUPINFO` 尽量隐藏 ping/netsh/route 的黑色命令行窗口，不使用 VBS、计划任务、WMI 远程进程、代码注入或隐藏 PowerShell 下载执行等方式。即使隐藏窗口，stdout、stderr 和 returncode 仍会完整写入 GUI 日志。

所有等待和 ping 重试都在后台 worker 线程中执行，不会阻塞 tkinter 主线程。等待期间日志会显示类似“网络配置命令已执行，等待 2.0 秒让配置生效...”。

## 本地运行

需要 Python 3.11+。

```powershell
pip install -r requirements.txt
python app.py
```

## 本地打包

```powershell
pyinstaller --onefile --noconsole --uac-admin --name NetworkSwitcher app.py
```

生成的 exe 位于：

```text
dist/NetworkSwitcher.exe
```

## GitHub Actions 打包

推送到 GitHub 后，进入仓库的 Actions 页面，选择 `Build Windows EXE` 工作流，点击 `Run workflow` 手动触发；推送到 `main` 或 `master` 也会触发构建。workflow 会先执行：

```powershell
python -m py_compile app.py network_utils.py config.py
```

然后使用 PyInstaller 打包单文件 exe。CI 中不会执行真实 `netsh`、`route`、`ping` 网络修改。

构建完成后，可以在 Actions artifact 或 Release 页面下载 `NetworkSwitcher.exe`。

## 修改外网路由

编辑 `config.py` 里的 `ROUTES`：

```python
ROUTES = [
    {"dest": "目标网段", "mask": "掩码", "gateway": "112.13.121.129"},
]
```

外网最终配置时会执行：

```text
route add 目标网段 mask 掩码 网关 -p
```

切回内网时只会删除 `ROUTES` 中配置的目标网段：

```text
route delete 目标网段
```

请只在 `ROUTES` 中维护本工具负责管理的路由，避免误删系统或其他软件创建的路由。
