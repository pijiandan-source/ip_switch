# -*- coding: utf-8 -*-
"""Windows network helpers used by the GUI.

All commands avoid shell=True and return structured command results so callers
can show stdout, stderr, and return codes in the GUI log.
"""

from __future__ import annotations

import ctypes
import ipaddress
import os
from pathlib import Path
import subprocess
import sys
from dataclasses import dataclass
from typing import Callable

from config import ROUTES


LogCallback = Callable[[str], None]


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.returncode == 0

    @property
    def command_text(self) -> str:
        return " ".join(f'"{part}"' if " " in part else part for part in self.command)

    def as_dict(self) -> dict[str, object]:
        return {
            "cmd": self.command,
            "returncode": self.returncode,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


def is_windows() -> bool:
    return os.name == "nt"


def is_admin() -> bool:
    if not is_windows():
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    """Relaunch the current Python program as administrator."""
    if not is_windows():
        return False

    executable = str(Path(sys.executable))
    if getattr(sys, "frozen", False):
        params = subprocess.list2cmdline(sys.argv[1:])
    else:
        params = subprocess.list2cmdline([str(Path(sys.argv[0])), *sys.argv[1:]])
    try:
        result = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            executable,
            params,
            None,
            1,
        )
        return result > 32
    except Exception:
        return False


def safe_decode(data: bytes | str | None) -> str:
    """Decode Windows command output without crashing on mixed encodings."""
    if not data:
        return ""
    if isinstance(data, str):
        return data
    for encoding in ("utf-8", "gbk", "cp936", "mbcs"):
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            pass
    return data.decode("utf-8", errors="replace")


def run_command(command: list[str], timeout: int = 30) -> CommandResult:
    """Run a Windows command and capture stdout, stderr, and return code."""
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout,
            shell=False,
        )
        return CommandResult(
            command=command,
            returncode=completed.returncode,
            stdout=safe_decode(completed.stdout).strip(),
            stderr=safe_decode(completed.stderr).strip(),
        )
    except subprocess.TimeoutExpired as exc:
        stdout = safe_decode(exc.stdout).strip()
        stderr = safe_decode(exc.stderr).strip()
        return CommandResult(
            command=command,
            returncode=124,
            stdout=stdout,
            stderr=stderr or f"命令超时：{timeout} 秒",
        )
    except FileNotFoundError as exc:
        return CommandResult(
            command=command,
            returncode=127,
            stdout="",
            stderr=f"命令不存在：{exc}",
        )
    except Exception as exc:
        return CommandResult(
            command=command,
            returncode=1,
            stdout="",
            stderr=f"执行命令失败：{exc}",
        )


def log_command_result(result: CommandResult, log: LogCallback | None = None) -> None:
    if log is None:
        return
    log(f"> {result.command_text}")
    log(f"返回码：{result.returncode}")
    if result.stdout:
        log(f"stdout:\n{result.stdout}")
    if result.stderr:
        log(f"stderr:\n{result.stderr}")


def validate_ip(value: str, field_name: str = "IP 地址") -> str:
    value = value.strip()
    try:
        return str(ipaddress.IPv4Address(value))
    except ipaddress.AddressValueError as exc:
        raise ValueError(f"{field_name} 格式不正确：{value}") from exc


def validate_netmask(value: str) -> str:
    value = value.strip()
    try:
        ipaddress.IPv4Network(f"0.0.0.0/{value}")
        return value
    except Exception as exc:
        raise ValueError(f"子网掩码格式不正确：{value}") from exc


def get_network_from_ip_mask(ip: str, mask: str) -> ipaddress.IPv4Network:
    ip = validate_ip(ip, "IP 地址")
    mask = validate_netmask(mask)
    return ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)


def get_enabled_adapters() -> list[str]:
    """Return enabled Windows network adapter names.

    Uses PowerShell when available because it exposes the user-facing adapter
    name used by netsh. Falls back to parsing netsh output.
    """
    if not is_windows():
        return []

    ps_command = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        "Get-NetAdapter | Where-Object {$_.Status -eq 'Up'} | Select-Object -ExpandProperty Name",
    ]
    result = run_command(ps_command, timeout=15)
    adapters = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if result.ok and adapters:
        return adapters

    result = run_command(["netsh", "interface", "show", "interface"], timeout=15)
    adapters = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].lower() in {"enabled", "已启用"} and parts[1].lower() in {"connected", "已连接"}:
            adapters.append(" ".join(parts[3:]))
    return adapters


def set_dhcp(adapter_name: str, log: LogCallback | None = None) -> list[CommandResult]:
    commands = [
        ["netsh", "interface", "ip", "set", "address", f"name={adapter_name}", "source=dhcp"],
        ["netsh", "interface", "ip", "set", "dns", f"name={adapter_name}", "source=dhcp"],
    ]
    results = []
    for command in commands:
        result = run_command(command)
        log_command_result(result, log)
        results.append(result)
    return results


def set_static_ip(adapter_name: str, ip: str, mask: str, gateway: str, log: LogCallback | None = None) -> CommandResult:
    command = [
        "netsh",
        "interface",
        "ip",
        "set",
        "address",
        f"name={adapter_name}",
        "static",
        ip,
        mask,
        gateway,
    ]
    result = run_command(command)
    log_command_result(result, log)
    return result


def set_static_dns(adapter_name: str, dns: str, log: LogCallback | None = None) -> CommandResult:
    command = [
        "netsh",
        "interface",
        "ip",
        "set",
        "dns",
        f"name={adapter_name}",
        "static",
        dns,
        "primary",
    ]
    result = run_command(command)
    log_command_result(result, log)
    return result


def route_gateway(route: dict[str, str], default_gateway: str) -> str:
    return route.get("gateway") or default_gateway


def add_managed_routes(gateway: str, log: LogCallback | None = None) -> list[CommandResult]:
    results = []
    for route in ROUTES:
        command = [
            "route",
            "add",
            route["dest"],
            "mask",
            route["mask"],
            route_gateway(route, gateway),
            "-p",
        ]
        result = run_command(command)
        log_command_result(result, log)
        results.append(result)
    return results


def delete_managed_routes(log: LogCallback | None = None) -> list[CommandResult]:
    results = []
    for route in ROUTES:
        command = ["route", "delete", route["dest"]]
        result = run_command(command)
        log_command_result(result, log)
        results.append(result)
    return results


def ping_host(host: str, count: int = 1, timeout_ms: int = 300) -> CommandResult:
    validate_ip(host, "Ping 目标")
    command = ["ping", "-n", str(count), "-w", str(timeout_ms), host]
    return run_command(command, timeout=max(5, count * (timeout_ms // 1000 + 2)))


def ping_gateway(gateway: str, log: LogCallback | None = None) -> CommandResult:
    result = ping_host(gateway, count=4, timeout_ms=1000)
    log_command_result(result, log)
    return result


def is_ping_success(result: CommandResult) -> bool:
    return result.ok


def scan_available_ips(
    base_ip: str,
    mask: str,
    gateway: str,
    log: LogCallback | None = None,
    stop_check: Callable[[], bool] | None = None,
) -> list[str]:
    """Return IPs that did not respond to ping and are therefore possibly free."""
    network = get_network_from_ip_mask(base_ip, mask)
    gateway = validate_ip(gateway, "网关")
    available = []

    if log:
        log(f"开始扫描网段：{network}")
        log("提醒：ping 不通只表示可能可用，不保证该 IP 一定无人使用。")

    for ip_obj in network.hosts():
        ip = str(ip_obj)
        if stop_check and stop_check():
            if log:
                log("扫描已停止。")
            break
        if ip == gateway:
            if log:
                log(f"跳过网关地址：{ip}")
            continue

        result = ping_host(ip, count=1, timeout_ms=300)
        if is_ping_success(result):
            if log:
                log(f"{ip} 已响应 ping，跳过。")
        else:
            available.append(ip)
            if log:
                log(f"{ip} 可能可用。")

    if log:
        log(f"扫描完成，发现 {len(available)} 个可能可用 IP。")
    return available


def switch_to_dhcp(adapter_name: str, log: LogCallback | None = None) -> bool:
    if log:
        log("正在切换到内网 DHCP 模式...")
    results = set_dhcp(adapter_name, log)
    if log:
        log("正在删除本工具管理的外网静态路由...")
    delete_managed_routes(log)
    ok = all(result.ok for result in results)
    if log:
        log("内网 DHCP 配置完成。" if ok else "内网 DHCP 配置有错误，请查看上方日志。")
    return ok


def switch_to_static(
    adapter_name: str,
    ip: str,
    mask: str,
    gateway: str,
    dns: str,
    log: LogCallback | None = None,
) -> bool:
    ip = validate_ip(ip, "IP 地址")
    mask = validate_netmask(mask)
    gateway = validate_ip(gateway, "网关")
    dns = validate_ip(dns, "DNS")

    network = get_network_from_ip_mask(ip, mask)
    if ipaddress.IPv4Address(ip) not in network.hosts():
        raise ValueError(f"IP 地址 {ip} 不在可用主机范围内：{network}")
    if ip == gateway:
        raise ValueError("客户端 IP 不能与网关地址相同。")

    if log:
        log("正在切换到外网静态配置...")
        log(f"目标配置：IP={ip}, MASK={mask}, GATEWAY={gateway}, DNS={dns}")

    ip_result = set_static_ip(adapter_name, ip, mask, gateway, log)
    dns_result = set_static_dns(adapter_name, dns, log)

    if log:
        log("正在清理旧的本工具管理路由，避免重复添加。")
    delete_managed_routes(log)

    if log:
        log("正在添加本工具管理的外网静态路由...")
    route_results = add_managed_routes(gateway, log)

    if log:
        log("正在测试网关连通性...")
    ping_result = ping_gateway(gateway, log)
    ping_ok = is_ping_success(ping_result)

    command_ok = ip_result.ok and dns_result.ok and all(result.ok for result in route_results)
    if log:
        if command_ok and ping_ok:
            log("外网配置成功，网关可连通。")
        elif command_ok:
            log("静态配置命令已执行，但 ping 网关失败，请检查线路、网关或 IP 是否冲突。")
        else:
            log("外网配置失败，请查看上方命令错误。")
    return command_ok and ping_ok
