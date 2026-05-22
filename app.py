# -*- coding: utf-8 -*-
from __future__ import annotations

import ipaddress
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import config
import network_utils as net


class NetworkSwitcherApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("内外网切换工具")
        self.geometry("920x680")
        self.minsize(860, 600)

        self.log_queue: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.scan_stop = threading.Event()
        self.available_ips: list[str] = []

        self.adapter_var = tk.StringVar()
        self.mode_var = tk.StringVar(value="未知")
        self.temp_ip_var = tk.StringVar(value=config.TEMP_IP)
        self.mask_var = tk.StringVar(value=config.DEFAULT_MASK)
        self.gateway_var = tk.StringVar(value=config.DEFAULT_GATEWAY)
        self.dns_var = tk.StringVar(value=config.DEFAULT_DNS)
        self.available_ip_var = tk.StringVar()
        self.auto_select_var = tk.BooleanVar(value=False)

        self._build_ui()
        self._load_adapters()
        self._check_admin()
        self.after(100, self._drain_log_queue)

    def _build_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(4, weight=1)

        top = ttk.Frame(self, padding=12)
        top.grid(row=0, column=0, sticky="ew")
        top.columnconfigure(1, weight=1)

        ttk.Label(top, text="网卡").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.adapter_combo = ttk.Combobox(top, textvariable=self.adapter_var, state="readonly")
        self.adapter_combo.grid(row=0, column=1, sticky="ew")
        self.refresh_button = ttk.Button(top, text="刷新网卡", command=self._load_adapters)
        self.refresh_button.grid(row=0, column=2, padx=(8, 0))

        ttk.Label(top, text="当前模式").grid(row=1, column=0, sticky="w", pady=(10, 0), padx=(0, 8))
        ttk.Label(top, textvariable=self.mode_var, font=("", 11, "bold")).grid(row=1, column=1, sticky="w", pady=(10, 0))

        self.admin_frame = ttk.Frame(self, padding=(12, 0, 12, 8))
        self.admin_frame.grid(row=1, column=0, sticky="ew")
        self.admin_label = ttk.Label(self.admin_frame, foreground="#b00020")
        self.admin_label.pack(side="left")
        self.admin_button = ttk.Button(self.admin_frame, text="以管理员权限重启", command=self._restart_as_admin)
        self.admin_button.pack(side="left", padx=(12, 0))

        actions = ttk.Frame(self, padding=(12, 0, 12, 12))
        actions.grid(row=2, column=0, sticky="ew")
        self.dhcp_button = ttk.Button(actions, text="切换到内网 DHCP", command=self._switch_to_dhcp)
        self.dhcp_button.pack(side="left")
        self.ping_button = ttk.Button(actions, text="测试网关", command=self._ping_gateway)
        self.ping_button.pack(side="left", padx=(8, 0))

        config_frame = ttk.LabelFrame(self, text="外网配置", padding=12)
        config_frame.grid(row=3, column=0, sticky="ew", padx=12, pady=(0, 12))
        for col in range(4):
            config_frame.columnconfigure(col, weight=1)

        self._add_labeled_entry(config_frame, "临时扫描 IP", self.temp_ip_var, 0, 0)
        self._add_labeled_entry(config_frame, "子网掩码", self.mask_var, 0, 2)
        self._add_labeled_entry(config_frame, "网关", self.gateway_var, 1, 0)
        self._add_labeled_entry(config_frame, "DNS", self.dns_var, 1, 2)

        self.auto_select_check = ttk.Checkbutton(
            config_frame,
            text="扫描后自动选择第一个可用 IP",
            variable=self.auto_select_var,
        )
        self.auto_select_check.grid(row=2, column=0, columnspan=2, sticky="w", pady=(10, 0))

        self.alternate_button = ttk.Button(config_frame, text="使用备用临时 IP", command=self._use_alternate_ip)
        self.alternate_button.grid(row=2, column=2, sticky="w", pady=(10, 0))

        self.scan_button = ttk.Button(config_frame, text="配置临时 IP 并扫描", command=self._prepare_and_scan)
        self.scan_button.grid(row=3, column=0, sticky="w", pady=(10, 0))
        self.apply_button = ttk.Button(config_frame, text="应用选中 IP", command=self._apply_selected_ip)
        self.apply_button.grid(row=3, column=1, sticky="w", pady=(10, 0))
        self.stop_scan_button = ttk.Button(config_frame, text="停止扫描", command=self._stop_scan, state="disabled")
        self.stop_scan_button.grid(row=3, column=2, sticky="w", pady=(10, 0))

        ttk.Label(config_frame, text="扫描结果").grid(row=4, column=0, sticky="nw", pady=(10, 0))
        self.available_list = tk.Listbox(config_frame, height=5, exportselection=False)
        self.available_list.grid(row=4, column=1, columnspan=3, sticky="ew", pady=(10, 0))
        self.available_list.bind("<<ListboxSelect>>", self._select_available_ip)

        log_frame = ttk.LabelFrame(self, text="日志", padding=8)
        log_frame.grid(row=4, column=0, sticky="nsew", padx=12, pady=(0, 12))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, height=16, wrap="word", state="disabled")
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

    def _add_labeled_entry(self, parent: ttk.Frame, label: str, var: tk.StringVar, row: int, col: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(parent, textvariable=var).grid(row=row, column=col + 1, sticky="ew", padx=(0, 16), pady=4)

    def _check_admin(self) -> None:
        if net.is_admin():
            self.admin_label.configure(text="已以管理员权限运行")
            self.admin_button.configure(state="disabled")
        else:
            self.admin_label.configure(text="需要管理员权限运行，才能修改 IP、DNS 和路由表。")

    def _require_admin_for_change(self) -> bool:
        if net.is_admin():
            return True
        messagebox.showwarning("需要管理员权限", "修改 IP、DNS 和路由表需要管理员权限，请先以管理员权限重启。")
        self.log("已阻止网络配置修改：当前不是管理员权限。")
        return False

    def _restart_as_admin(self) -> None:
        if net.relaunch_as_admin():
            self.log("已请求以管理员权限重启。")
            self.destroy()
        else:
            messagebox.showerror("重启失败", "无法发起管理员权限重启，请手动右键以管理员身份运行。")

    def _load_adapters(self) -> None:
        def task() -> None:
            self.log("正在读取启用的网卡列表...")
            adapters = net.get_enabled_adapters()
            self.after(0, lambda: self._set_adapters(adapters))

        self._run_worker(task)

    def _set_adapters(self, adapters: list[str]) -> None:
        self.adapter_combo.configure(values=adapters)
        if adapters:
            self.adapter_var.set(adapters[0])
            self.log(f"发现 {len(adapters)} 个启用网卡。")
        else:
            self.adapter_var.set("")
            self.log("未发现启用网卡。")

    def _use_alternate_ip(self) -> None:
        self.temp_ip_var.set(config.ALTERNATE_TEMP_IP)

    def _select_available_ip(self, _event: object = None) -> None:
        selected = self.available_list.curselection()
        if selected:
            self.available_ip_var.set(self.available_list.get(selected[0]))

    def _require_adapter(self) -> str | None:
        adapter = self.adapter_var.get().strip()
        if not adapter:
            messagebox.showwarning("请选择网卡", "请先选择一个启用的网卡。")
            return None
        return adapter

    def _validated_external_config(self) -> tuple[str, str, str, str] | None:
        try:
            temp_ip = net.validate_ip(self.temp_ip_var.get(), "临时扫描 IP")
            mask = net.validate_netmask(self.mask_var.get())
            gateway = net.validate_ip(self.gateway_var.get(), "网关")
            dns = net.validate_ip(self.dns_var.get(), "DNS")
            net.ensure_host_ip(temp_ip, mask, gateway, "临时扫描 IP")
            return temp_ip, mask, gateway, dns
        except ValueError as exc:
            messagebox.showerror("配置错误", str(exc))
            return None

    def _validate_selected_ip(self, selected_ip: str, mask: str, gateway: str) -> bool:
        try:
            selected_ip = net.validate_ip(selected_ip, "最终外网 IP")
            network = net.get_network_from_ip_mask(selected_ip, mask)
            if ipaddress.IPv4Address(selected_ip) not in network.hosts():
                raise ValueError(f"最终外网 IP {selected_ip} 不在网段 {network} 的可用主机范围内。")
            if selected_ip == gateway:
                raise ValueError("最终外网 IP 不能与网关相同。")
            return True
        except ValueError as exc:
            messagebox.showerror("IP 错误", str(exc))
            return False

    def _set_busy(self, busy: bool, scanning: bool = False) -> None:
        state = "disabled" if busy else "normal"
        readonly_state = "disabled" if busy else "readonly"
        self.refresh_button.configure(state=state)
        self.dhcp_button.configure(state=state)
        self.ping_button.configure(state=state)
        self.scan_button.configure(state=state)
        self.apply_button.configure(state=state)
        self.alternate_button.configure(state=state)
        self.auto_select_check.configure(state=state)
        self.adapter_combo.configure(state=readonly_state)
        self.stop_scan_button.configure(state="normal" if scanning else "disabled")

    def _switch_to_dhcp(self) -> None:
        if not self._require_admin_for_change():
            return
        adapter = self._require_adapter()
        if not adapter:
            return

        def task() -> None:
            ok = net.switch_to_dhcp(adapter, self.log)
            self.after(0, lambda: self.mode_var.set("内网" if ok else "未知"))

        self._run_worker(task)

    def _prepare_and_scan(self) -> None:
        if not self._require_admin_for_change():
            return
        adapter = self._require_adapter()
        values = self._validated_external_config()
        if not adapter or not values:
            return
        temp_ip, mask, gateway, dns = values
        auto_select = self.auto_select_var.get()

        self.scan_stop.clear()
        self._set_available_ips([])

        def task() -> None:
            prepared = net.prepare_external_scan(adapter, temp_ip, mask, gateway, dns, self.log)
            if not prepared:
                return

            ips = net.scan_available_ips(
                adapter,
                temp_ip,
                mask,
                gateway,
                dns,
                auto_select=auto_select,
                log=self.log,
                stop_check=self.scan_stop.is_set,
            )
            self.after(0, lambda: self._set_available_ips(ips))

            if not ips:
                self.log("没有扫描到可能可用 IP。可以手动输入其他临时 IP，或联系管理员确认可用地址。")
                return

            if auto_select and not self.scan_stop.is_set():
                selected_ip = ips[0]
                self.log(f"自动选择 IP: {selected_ip}")
                ok = net.apply_final_static_ip(adapter, selected_ip, mask, gateway, dns, self.log)
                self.after(0, lambda: self.mode_var.set("外网" if ok else "未知"))

        self._run_worker(task, scanning=True)

    def _apply_selected_ip(self) -> None:
        if not self._require_admin_for_change():
            return
        adapter = self._require_adapter()
        values = self._validated_external_config()
        if not adapter or not values:
            return
        _temp_ip, mask, gateway, dns = values

        selected_ip = self.available_ip_var.get().strip()
        if not selected_ip:
            messagebox.showwarning("请选择 IP", "请先从扫描结果中选择一个可能可用 IP。")
            return
        if not self._validate_selected_ip(selected_ip, mask, gateway):
            return

        def task() -> None:
            ok = net.apply_final_static_ip(adapter, selected_ip, mask, gateway, dns, self.log)
            self.after(0, lambda: self.mode_var.set("外网" if ok else "未知"))

        self._run_worker(task)

    def _stop_scan(self) -> None:
        self.scan_stop.set()
        self.log("正在请求停止扫描...")

    def _set_available_ips(self, ips: list[str]) -> None:
        self.available_ips = ips
        self.available_ip_var.set("")
        self.available_list.delete(0, "end")
        for ip in ips:
            self.available_list.insert("end", ip)
        if ips:
            self.available_list.selection_set(0)
            self.available_ip_var.set(ips[0])

    def _ping_gateway(self) -> None:
        try:
            gateway = net.validate_ip(self.gateway_var.get(), "网关")
        except ValueError as exc:
            messagebox.showerror("网关错误", str(exc))
            return

        def task() -> None:
            self.log("正在测试网关连通性...")
            ok, _results = net.ping_with_retry(gateway, log=self.log)
            if ok:
                self.log("网关 ping 成功。")
            else:
                self.log("网关 ping 失败。")

        self._run_worker(task)

    def _run_worker(self, target, scanning: bool = False) -> None:
        if self.worker and self.worker.is_alive():
            messagebox.showinfo("任务执行中", "已有任务正在执行，请等待完成。")
            return

        self._set_busy(True, scanning=scanning)

        def wrapped() -> None:
            try:
                target()
            except Exception as exc:
                self.log(f"任务失败：{exc}")
            finally:
                self.after(0, lambda: self._set_busy(False))

        self.worker = threading.Thread(target=wrapped, daemon=True)
        self.worker.start()

    def log(self, message: str) -> None:
        self.log_queue.put(str(message))

    def _drain_log_queue(self) -> None:
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log_text.configure(state="normal")
            self.log_text.insert("end", f"{message}\n")
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(100, self._drain_log_queue)


if __name__ == "__main__":
    app = NetworkSwitcherApp()
    app.mainloop()
