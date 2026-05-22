# 内外网切换工具

这是一个面向 Windows 10/11 的 Python tkinter GUI 工具，用于一键切换公司内网 DHCP 和外网静态网络配置。

## 功能

- 列出当前启用的 Windows 网卡
- 切换到内网 DHCP：IP 自动获取、DNS 自动获取，并删除本工具管理的外网静态路由
- 切换到外网静态配置：设置 IP、子网掩码、网关、DNS
- 根据 IP 和掩码计算网段，并扫描可能可用的 IP
- 测试网关连通性并在 GUI 日志中显示命令结果
- GitHub Actions 自动打包为单个 `NetworkSwitcher.exe`

## 权限要求

修改网卡 IP、DNS 和路由表必须使用管理员权限。请右键以管理员身份运行程序或 exe。程序启动后也会提示是否需要管理员权限，并提供“以管理员权限重启”按钮。

## Windows 中文兼容

程序执行 `netsh`、`route`、`ping` 等命令时使用 bytes 捕获输出，再按 `utf-8`、`gbk`、`cp936`、`mbcs` 顺序兼容解码，无法识别的字符会替换显示，不会因为命令输出编码导致 GUI 崩溃。命令成功与否以 `returncode` 为准，stdout/stderr 只用于日志和排错。

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

把项目推送到 GitHub 后，进入仓库的 Actions 页面，选择 `Build Windows EXE` 工作流，点击 `Run workflow` 手动触发。执行完成后，在 workflow run 的 Artifacts 中下载 `NetworkSwitcher.exe`。

## 默认外网配置

- IP：`112.13.121.254`
- 备用默认 IP：`112.13.121.253`
- 子网掩码：`255.255.255.128`
- 网关：`112.13.121.129`
- DNS：`223.5.5.5`

根据默认配置计算出的网段为 `112.13.121.128/25`，可用主机范围为 `112.13.121.129 - 112.13.121.254`，其中网关 `112.13.121.129` 不能作为客户端 IP。

## IP 扫描提醒

扫描使用 `ping -n 1 -w 300 IP`。ping 不通只表示该 IP “可能可用”，不代表一定没人使用。某些设备可能禁 ping、防火墙拦截，或暂时离线。应用静态 IP 前，请确认不会与别人冲突。

## 修改外网路由

编辑 `config.py` 里的 `ROUTES`：

```python
ROUTES = [
    {"dest": "目标网段", "mask": "掩码", "gateway": "112.13.121.129"},
]
```

外网模式会执行：

```text
route add 目标网段 mask 掩码 网关 -p
```

切回内网时只会删除 `ROUTES` 中配置的目标网段：

```text
route delete 目标网段
```

请只在 `ROUTES` 中维护本工具负责管理的路由，避免误删系统或其他软件创建的路由。
