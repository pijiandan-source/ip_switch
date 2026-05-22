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
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Callable

from config import (
    CLEAR_ARP_CACHE_BEFORE_SCAN,
    NETWORK_APPLY_DELAY_SECONDS,
    PING_RETRY_COUNT,
    PING_RETRY_INTERVAL_SECONDS,
    ROUTES,
    SCAN_PING_COUNT,
    SCAN_PING_TIMEOUT_MS,
)


LogCallback = Callable[[str], None]
StopCallback = Callable[[], bool]


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


def get_subprocess_kwargs() -> dict[str, object]:
    """Return subprocess options that capture output and hide console windows."""
    kwargs: dict[str, object] = {
        "capture_output": True,
        "text": False,
        "stdin": subprocess.DEVNULL,
        "shell": False,
    }
    if is_windows():
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return kwargs


def run_command(command: list[str], timeout: int = 30) -> CommandResult:
    """Run a Windows command and capture stdout, stderr, and return code."""
    try:
        completed = subprocess.run(command, timeout=timeout, **get_subprocess_kwargs())
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
    log(f"returncode: {result.returncode}")
    if result.stdout:
        log(f"stdout:\n{result.stdout}")
    if result.stderr:
        log(f"stderr:\n{result.stderr}")


def wait_for_network_apply(seconds: float = NETWORK_APPLY_DELAY_SECONDS, log: LogCallback | None = None) -> None:
    if seconds <= 0:
        return
    if log:
        log(f"网络配置命令已执行，等待 {seconds:.1f} 秒让配置生效...")
    time.sleep(seconds)


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


def ensure_host_ip(ip: str, mask: str, gateway: str, label: str = "IP 地址") -> None:
    network = get_network_from_ip_mask(ip, mask)
    ip_obj = ipaddress.IPv4Address(ip)
    if ip_obj not in network.hosts():
        raise ValueError(f"{label} {ip} 不在网段 {network} 的可用主机范围内。")
    if ip == gateway:
        raise ValueError(f"{label} 不能与网关地址相同。")


def get_enabled_adapters() -> list[str]:
    """Return enabled Windows network adapter names."""
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
    if not ROUTES and log:
        log("ROUTES 为空，未添加外网静态路由。")
    return results


def delete_managed_routes(log: LogCallback | None = None) -> list[CommandResult]:
    results = []
    for route in ROUTES:
        command = ["route", "delete", route["dest"]]
        result = run_command(command)
        log_command_result(result, log)
        results.append(result)
    if not ROUTES and log:
        log("ROUTES 为空，未删除外网静态路由。")
    return results


def ping_host(host: str, count: int = 1, timeout_ms: int = 300, log: LogCallback | None = None) -> CommandResult:
    validate_ip(host, "Ping 目标")
    command = ["ping", "-n", str(count), "-w", str(timeout_ms), host]
    result = run_command(command, timeout=max(5, count * (timeout_ms // 1000 + 2)))
    log_command_result(result, log)
    return result


def ping_gateway(gateway: str, log: LogCallback | None = None) -> CommandResult:
    return ping_host(gateway, count=4, timeout_ms=1000, log=log)


def is_ping_success(result: CommandResult) -> bool:
    return result.returncode == 0


def ping_with_retry(
    host: str,
    count: int = 4,
    timeout_ms: int = 1000,
    retry_count: int = PING_RETRY_COUNT,
    retry_interval: float = PING_RETRY_INTERVAL_SECONDS,
    log: LogCallback | None = None,
) -> tuple[bool, list[CommandResult]]:
    host = validate_ip(host, "Ping 目标")
    results = []
    max_attempts = 1 + max(0, retry_count)

    for index in range(max_attempts):
        attempt = index + 1
        if log:
            log(f"第 {attempt} 次 ping 网关 {host} ...")
        result = ping_host(host, count=count, timeout_ms=timeout_ms, log=log)
        results.append(result)
        if result.ok:
            if log:
                log("网关连通性测试成功。")
            return True, results
        if index < max_attempts - 1:
            if log:
                log(f"ping 失败，等待 {retry_interval:.1f} 秒后重试...")
            time.sleep(retry_interval)

    if log:
        log("网关连通性测试失败。")
    return False, results


def get_arp_ips(log: LogCallback | None = None) -> set[str]:
    result = run_command(["arp", "-a"], timeout=15)
    log_command_result(result, log)
    if not result.stdout:
        return set()
    candidates = re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", result.stdout)
    valid_ips = set()
    for candidate in candidates:
        try:
            valid_ips.add(str(ipaddress.IPv4Address(candidate)))
        except ipaddress.AddressValueError:
            continue
    return valid_ips


def clear_arp_cache(log: LogCallback | None = None) -> CommandResult:
    if log:
        log("正在清理 ARP 缓存：arp -d *")
    result = run_command(["arp", "-d", "*"], timeout=15)
    log_command_result(result, log)
    if not result.ok and log:
        log("ARP 缓存清理失败，继续后续流程。")
    return result


def prepare_external_scan(
    adapter_name: str,
    temp_ip: str,
    mask: str,
    gateway: str,
    dns: str,
    log: LogCallback | None = None,
) -> bool:
    """Configure a temporary static IP and ping gateway before scanning."""
    temp_ip = validate_ip(temp_ip, "临时扫描 IP")
    mask = validate_netmask(mask)
    gateway = validate_ip(gateway, "网关")
    dns = validate_ip(dns, "DNS")
    ensure_host_ip(temp_ip, mask, gateway, "临时扫描 IP")

    if log:
        log("正在配置临时扫描 IP，让网卡进入外网目标网段。")
        log(f"临时配置：IP={temp_ip}, MASK={mask}, GATEWAY={gateway}, DNS={dns}")

    ip_result = set_static_ip(adapter_name, temp_ip, mask, gateway, log)
    dns_result = set_static_dns(adapter_name, dns, log)

    if not (ip_result.ok and dns_result.ok):
        if log:
            log("临时 IP 或 DNS 配置命令失败，已停止扫描。")
        return False

    wait_for_network_apply(NETWORK_APPLY_DELAY_SECONDS, log)

    if CLEAR_ARP_CACHE_BEFORE_SCAN:
        clear_arp_cache(log)

    if log:
        log("临时 IP 已配置，正在 ping 网关。")
    gateway_ok, _gateway_results = ping_with_retry(gateway, log=log)
    if gateway_ok:
        if log:
            log("临时 IP 配置后网关 ping 成功，可以开始扫描。")
        return True

    if log:
        log("临时 IP 已配置，但网关 ping 不通，可能是临时 IP 冲突、网线/VLAN 不对、网关不可达或防火墙限制。程序将继续扫描，但结果仅供参考。")
    return True


def scan_available_ips(
    adapter_name: str,
    temp_ip: str,
    mask: str,
    gateway: str,
    dns: str,
    auto_select: bool = False,
    log: LogCallback | None = None,
    stop_check: StopCallback | None = None,
) -> list[str]:
    """Scan the temp IP subnet and return IPs that are possibly available."""
    del adapter_name, dns, auto_select

    temp_ip = validate_ip(temp_ip, "临时扫描 IP")
    mask = validate_netmask(mask)
    gateway = validate_ip(gateway, "网关")
    ensure_host_ip(temp_ip, mask, gateway, "临时扫描 IP")

    network = get_network_from_ip_mask(temp_ip, mask)
    skip_ips = {temp_ip, gateway}
    available = []

    if log:
        log(f"开始扫描网段：{network}")
        log(f"跳过临时 IP：{temp_ip}")
        log(f"跳过网关 IP：{gateway}")
        log("扫描结果只是可能可用。部分设备禁 ping 或 ARP 缓存不完整，不能 100% 保证无冲突。")
        log("正在读取 ARP 缓存作为辅助判断。")

    arp_ips = get_arp_ips(log)

    for ip_obj in network.hosts():
        ip = str(ip_obj)
        if stop_check and stop_check():
            if log:
                log("扫描已停止。")
            break
        if ip in skip_ips:
            continue

        if log:
            log(f"正在检测 {ip} ...")

        result = ping_host(ip, count=SCAN_PING_COUNT, timeout_ms=SCAN_PING_TIMEOUT_MS, log=log)
        if result.ok:
            if log:
                log(f"{ip} 有响应，跳过。")
            continue

        if ip in arp_ips:
            if log:
                log(f"{ip} 无 ping 响应，但出现在 ARP 缓存中，标记为疑似占用并跳过。")
            continue

        available.append(ip)
        if log:
            log(f"{ip} 无响应，可能可用。")

    if log:
        log(f"扫描完成，发现 {len(available)} 个可能可用 IP。")
    return available


def switch_to_dhcp(adapter_name: str, log: LogCallback | None = None) -> bool:
    if log:
        log("正在切换到内网 DHCP 模式。")
    results = set_dhcp(adapter_name, log)
    if log:
        log("正在删除本工具管理的外网静态路由。")
    delete_managed_routes(log)
    ok = all(result.ok for result in results)
    if ok:
        wait_for_network_apply(NETWORK_APPLY_DELAY_SECONDS, log)
    if log:
        log("内网 DHCP 配置完成。" if ok else "内网 DHCP 配置有错误，请查看上方日志。")
    return ok


def apply_final_static_ip(
    adapter_name: str,
    selected_ip: str,
    mask: str,
    gateway: str,
    dns: str,
    log: LogCallback | None = None,
) -> bool:
    selected_ip = validate_ip(selected_ip, "最终外网 IP")
    mask = validate_netmask(mask)
    gateway = validate_ip(gateway, "网关")
    dns = validate_ip(dns, "DNS")
    ensure_host_ip(selected_ip, mask, gateway, "最终外网 IP")

    if log:
        log("正在应用最终外网静态 IP。")
        log(f"最终配置：IP={selected_ip}, MASK={mask}, GATEWAY={gateway}, DNS={dns}")

    ip_result = set_static_ip(adapter_name, selected_ip, mask, gateway, log)
    dns_result = set_static_dns(adapter_name, dns, log)

    if log:
        log("正在清理旧的本工具管理路由，避免重复添加。")
    delete_managed_routes(log)

    if log:
        log("正在添加本工具管理的外网静态路由。")
    route_results = add_managed_routes(gateway, log)

    command_ok = ip_result.ok and dns_result.ok and all(result.ok for result in route_results)
    if command_ok:
        wait_for_network_apply(NETWORK_APPLY_DELAY_SECONDS, log)

    if log:
        log("正在 ping 网关验证最终外网配置。")
    ping_ok, _ping_results = ping_with_retry(gateway, log=log)

    if log:
        if command_ok and ping_ok:
            log(f"外网配置成功，当前 IP: {selected_ip}")
        elif command_ok:
            log("最终外网配置命令已执行，但 ping 网关失败，请查看日志并检查网络环境。")
        else:
            log("最终外网配置失败，请查看上方命令错误。")
    return command_ok and ping_ok


def switch_to_static(
    adapter_name: str,
    ip: str,
    mask: str,
    gateway: str,
    dns: str,
    log: LogCallback | None = None,
) -> bool:
    """Backward-compatible alias for applying the final external IP."""
    return apply_final_static_ip(adapter_name, ip, mask, gateway, dns, log)
