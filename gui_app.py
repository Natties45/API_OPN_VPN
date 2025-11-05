#!/usr/bin/env python3
"""Tkinter GUI wrapper for the OPNsense OpenVPN automation scripts.

This lightweight desktop application lets administrators edit the
configuration JSON files and execute the existing PowerShell automation
without having to touch the command line.  The intent is to keep the
configuration model identical to the PowerShell workflow, so the GUI only
provides convenience around those JSON files.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

BASE_DIR = Path(__file__).resolve().parent

CONFIG_PROFILE_PATH = BASE_DIR / "config.profiles.json"
CONFIG_SETTINGS_PATH = BASE_DIR / "config.settings.json"
CONFIG_USERS_PATH = BASE_DIR / "config.users.json"

DEFAULT_PROFILE = {
    "ProfileName": "New Profile",
    "ApiBaseUrl": "https://firewall.example.com:4443",
    "ApiKey": "",
    "ApiSecret": "",
    "SshHost": "firewall.example.com",
    "SshUser": "root",
    "SshPass": "",
}

DEFAULT_SETTINGS = {
    "GroupName": "vpn-users",
    "GroupDesc": "VPN users (auto-generated)",
    "VpnTunnelNetwork": "10.99.0.0/24",
    "VpnLocalNetwork": "192.168.1.0/24",
    "StaticKeyMode": "tls-crypt",
    "VpnDevType": "tun",
    "VpnTopology": "subnet",
    "InterfaceDesc": "VPN_TUNNEL_AUTO",
    "NamePatterns": {
        "CaPrefix": "AutoCA_VPN",
        "ServerCn": "AutoVPN_Gateway",
        "StaticKeyPrefix": "AutoTLSKey",
        "InstancePrefix": "AutoVPN_Server",
    },
    "Lifetimes": {
        "CALifetimeDays": 3650,
        "ServerCertLifetimeDays": 3650,
        "ClientCertLifetimeDays": 3650,
    },
    "Firewall": {
        "VpnListenPort": "1194",
        "VpnProto": "udp4",
    },
}

DEFAULT_USER = {
    "Name": "newuser",
    "Password": "changeme",
    "Full": "New VPN User",
    "Email": "user@example.com",
}


class ConfigStore:
    """Helper that loads and saves JSON config files."""

    def __init__(self) -> None:
        self.profile_path = CONFIG_PROFILE_PATH
        self.settings_path = CONFIG_SETTINGS_PATH
        self.users_path = CONFIG_USERS_PATH

    def load_profiles(self) -> List[Dict[str, str]]:
        return self._load_json(self.profile_path, "profiles", default=[DEFAULT_PROFILE.copy()])

    def save_profiles(self, profiles: List[Dict[str, str]]) -> None:
        self._save_json(self.profile_path, {"profiles": profiles})

    def load_settings(self) -> Dict[str, object]:
        return self._load_json(self.settings_path, default=DEFAULT_SETTINGS.copy())

    def save_settings(self, settings: Dict[str, object]) -> None:
        self._save_json(self.settings_path, settings)

    def load_users(self) -> List[Dict[str, str]]:
        return self._load_json(self.users_path, "users", default=[])

    def save_users(self, users: List[Dict[str, str]]) -> None:
        self._save_json(self.users_path, {"users": users})

    def _load_json(
        self,
        path: Path,
        key: Optional[str] = None,
        default=None,
    ):
        if not path.exists():
            return default if default is not None else {}
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except json.JSONDecodeError as exc:
            messagebox.showerror(
                "Invalid JSON",
                f"ไม่สามารถอ่านไฟล์ {path.name} ได้\nรายละเอียด: {exc}",
            )
            return default if default is not None else {}
        if key is None:
            return data
        return data.get(key, default if default is not None else [])

    def _save_json(self, path: Path, data) -> None:
        with path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("OPNsense OpenVPN Setup GUI")
        self.geometry("950x700")

        self.store = ConfigStore()

        self.profiles: List[Dict[str, str]] = self.store.load_profiles()
        self.settings: Dict[str, object] = self.store.load_settings()
        self.users: List[Dict[str, str]] = self.store.load_users()

        if not self.profiles:
            self.profiles = [DEFAULT_PROFILE.copy()]
        if not self.users:
            self.users = []

        self.current_profile_index: int = 0
        self.current_user_index: Optional[int] = 0 if self.users else None

        self.profile_vars: Dict[str, tk.StringVar] = {
            "ProfileName": tk.StringVar(),
            "ApiBaseUrl": tk.StringVar(),
            "ApiKey": tk.StringVar(),
            "ApiSecret": tk.StringVar(),
            "SshHost": tk.StringVar(),
            "SshUser": tk.StringVar(),
            "SshPass": tk.StringVar(),
        }

        self.settings_vars: Dict[Tuple[str, ...], tk.StringVar] = {
            ("GroupName",): tk.StringVar(),
            ("GroupDesc",): tk.StringVar(),
            ("VpnTunnelNetwork",): tk.StringVar(),
            ("VpnLocalNetwork",): tk.StringVar(),
            ("StaticKeyMode",): tk.StringVar(),
            ("VpnDevType",): tk.StringVar(),
            ("VpnTopology",): tk.StringVar(),
            ("InterfaceDesc",): tk.StringVar(),
            ("NamePatterns", "CaPrefix"): tk.StringVar(),
            ("NamePatterns", "ServerCn"): tk.StringVar(),
            ("NamePatterns", "StaticKeyPrefix"): tk.StringVar(),
            ("NamePatterns", "InstancePrefix"): tk.StringVar(),
            ("Lifetimes", "CALifetimeDays"): tk.StringVar(),
            ("Lifetimes", "ServerCertLifetimeDays"): tk.StringVar(),
            ("Lifetimes", "ClientCertLifetimeDays"): tk.StringVar(),
            ("Firewall", "VpnListenPort"): tk.StringVar(),
            ("Firewall", "VpnProto"): tk.StringVar(),
        }

        self.user_vars: Dict[str, tk.StringVar] = {
            "Name": tk.StringVar(),
            "Password": tk.StringVar(),
            "Full": tk.StringVar(),
            "Email": tk.StringVar(),
        }

        self.action_profile_var = tk.StringVar()
        self.action_profile_combo: Optional[ttk.Combobox] = None

        self._build_layout()
        self._load_profile_into_vars()
        self._load_settings_into_vars()
        self._load_current_user_into_vars()

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.notebook = notebook

        profile_frame = ttk.Frame(notebook)
        settings_frame = ttk.Frame(notebook)
        users_frame = ttk.Frame(notebook)
        actions_frame = ttk.Frame(notebook)

        notebook.add(profile_frame, text="Profiles")
        notebook.add(settings_frame, text="Settings")
        notebook.add(users_frame, text="Users")
        notebook.add(actions_frame, text="Actions & Logs")

        self._build_profile_tab(profile_frame)
        self._build_settings_tab(settings_frame)
        self._build_users_tab(users_frame)
        self._build_actions_tab(actions_frame)

    def _build_profile_tab(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(1, weight=1)

        list_frame = ttk.Frame(frame)
        list_frame.grid(row=0, column=0, sticky="ns")

        ttk.Label(list_frame, text="Profiles").pack(anchor=tk.W)
        self.profile_listbox = tk.Listbox(list_frame, height=12)
        self.profile_listbox.pack(fill=tk.Y, expand=True)
        self.profile_listbox.bind("<<ListboxSelect>>", self._on_profile_selected)
        self._refresh_profile_listbox()

        btn_frame = ttk.Frame(list_frame)
        btn_frame.pack(fill=tk.X, pady=(5, 0))
        ttk.Button(btn_frame, text="New", command=self._create_profile).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Delete", command=self._delete_profile).pack(side=tk.LEFT, padx=2)

        fields = (
            ("Profile Name", "ProfileName"),
            ("API Base URL", "ApiBaseUrl"),
            ("API Key", "ApiKey"),
            ("API Secret", "ApiSecret"),
            ("SSH Host", "SshHost"),
            ("SSH User", "SshUser"),
            ("SSH Password", "SshPass"),
        )

        field_frame = ttk.Frame(frame)
        field_frame.grid(row=0, column=1, sticky="nsew", padx=(15, 0))
        field_frame.columnconfigure(1, weight=1)

        for idx, (label, key) in enumerate(fields):
            ttk.Label(field_frame, text=label).grid(row=idx, column=0, sticky=tk.W, pady=2)
            entry = ttk.Entry(field_frame, textvariable=self.profile_vars[key])
            entry.grid(row=idx, column=1, sticky="ew", pady=2)
            if key in {"ApiSecret", "SshPass"}:
                entry.configure(show="*")

        ttk.Button(field_frame, text="Save Profile", command=self._save_current_profile).grid(
            row=len(fields), column=1, sticky=tk.E, pady=(10, 0)
        )

    def _build_settings_tab(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(1, weight=1)

        general_fields = [
            ("Group Name", ("GroupName",)),
            ("Group Description", ("GroupDesc",)),
            ("VPN Tunnel Network", ("VpnTunnelNetwork",)),
            ("VPN Local Network", ("VpnLocalNetwork",)),
            ("Static Key Mode", ("StaticKeyMode",)),
            ("Device Type", ("VpnDevType",)),
            ("Topology", ("VpnTopology",)),
            ("Interface Description", ("InterfaceDesc",)),
        ]

        patterns_fields = [
            ("CA Prefix", ("NamePatterns", "CaPrefix")),
            ("Server CN", ("NamePatterns", "ServerCn")),
            ("Static Key Prefix", ("NamePatterns", "StaticKeyPrefix")),
            ("Instance Prefix", ("NamePatterns", "InstancePrefix")),
        ]

        lifetime_fields = [
            ("CA Lifetime (days)", ("Lifetimes", "CALifetimeDays")),
            ("Server Cert Lifetime (days)", ("Lifetimes", "ServerCertLifetimeDays")),
            ("Client Cert Lifetime (days)", ("Lifetimes", "ClientCertLifetimeDays")),
        ]

        firewall_fields = [
            ("Listen Port", ("Firewall", "VpnListenPort")),
            ("Protocol", ("Firewall", "VpnProto")),
        ]

        def build_section(start_row: int, title: str, fields_data) -> int:
            ttk.Label(frame, text=title, font=("Segoe UI", 10, "bold")).grid(
                row=start_row, column=0, columnspan=2, sticky=tk.W, pady=(10, 0)
            )
            row = start_row + 1
            for label, key in fields_data:
                ttk.Label(frame, text=label).grid(row=row, column=0, sticky=tk.W, pady=2)
                ttk.Entry(frame, textvariable=self.settings_vars[key]).grid(
                    row=row, column=1, sticky="ew", pady=2
                )
                row += 1
            return row

        next_row = build_section(0, "General", general_fields)
        next_row = build_section(next_row, "Name Patterns", patterns_fields)
        next_row = build_section(next_row, "Lifetimes", lifetime_fields)
        next_row = build_section(next_row, "Firewall", firewall_fields)

        ttk.Button(frame, text="Save Settings", command=self._save_settings).grid(
            row=next_row, column=1, sticky=tk.E, pady=(10, 0)
        )

    def _build_users_tab(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(1, weight=1)

        list_frame = ttk.Frame(frame)
        list_frame.grid(row=0, column=0, sticky="ns")

        ttk.Label(list_frame, text="Users").pack(anchor=tk.W)
        self.user_listbox = tk.Listbox(list_frame, height=14)
        self.user_listbox.pack(fill=tk.Y, expand=True)
        self.user_listbox.bind("<<ListboxSelect>>", self._on_user_selected)
        self._refresh_user_listbox()

        btn_frame = ttk.Frame(list_frame)
        btn_frame.pack(fill=tk.X, pady=(5, 0))
        ttk.Button(btn_frame, text="New", command=self._create_user).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Delete", command=self._delete_user).pack(side=tk.LEFT, padx=2)

        fields = (
            ("Username", "Name"),
            ("Password", "Password"),
            ("Full Name", "Full"),
            ("Email", "Email"),
        )

        field_frame = ttk.Frame(frame)
        field_frame.grid(row=0, column=1, sticky="nsew", padx=(15, 0))
        field_frame.columnconfigure(1, weight=1)

        for idx, (label, key) in enumerate(fields):
            ttk.Label(field_frame, text=label).grid(row=idx, column=0, sticky=tk.W, pady=2)
            entry = ttk.Entry(field_frame, textvariable=self.user_vars[key])
            entry.grid(row=idx, column=1, sticky="ew", pady=2)
            if key == "Password":
                entry.configure(show="*")

        ttk.Button(field_frame, text="Save User", command=self._save_current_user).grid(
            row=len(fields), column=1, sticky=tk.E, pady=(10, 0)
        )

    def _build_actions_tab(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(0, weight=1)
        action_frame = ttk.Frame(frame)
        action_frame.grid(row=0, column=0, sticky="ew")

        self.save_button = ttk.Button(action_frame, text="Save Config Files", command=self._save_all)
        self.save_button.grid(row=0, column=0, padx=5, pady=5)

        self.full_setup_button = ttk.Button(
            action_frame, text="Run Full Setup", command=self._run_full_setup
        )
        self.full_setup_button.grid(row=0, column=1, padx=5, pady=5)

        self.build_button = ttk.Button(
            action_frame, text="Build OVPN Files", command=self._run_build_ovpn
        )
        self.build_button.grid(row=0, column=2, padx=5, pady=5)

        profile_select_frame = ttk.Frame(frame)
        profile_select_frame.grid(row=1, column=0, sticky="ew", padx=(0, 5))
        profile_select_frame.columnconfigure(1, weight=1)

        ttk.Label(profile_select_frame, text="Profile for scripts:").grid(
            row=0, column=0, sticky=tk.W, padx=5, pady=(0, 5)
        )
        self.action_profile_combo = ttk.Combobox(
            profile_select_frame,
            textvariable=self.action_profile_var,
            state="readonly",
        )
        self.action_profile_combo.grid(row=0, column=1, sticky="ew", pady=(0, 5))
        self.action_profile_combo.bind("<<ComboboxSelected>>", self._on_action_profile_selected)

        self.log_text = scrolledtext.ScrolledText(frame, height=25, state=tk.DISABLED)
        self.log_text.grid(row=2, column=0, sticky="nsew", padx=(0, 5), pady=(10, 0))
        frame.rowconfigure(2, weight=1)

        self._refresh_action_profile_selector()

    def _refresh_action_profile_selector(self) -> None:
        """Update the combobox that picks a profile for script execution."""

        if not self.action_profile_combo:
            return

        profile_names: List[str] = []
        for index, profile in enumerate(self.profiles, start=1):
            name = profile.get("ProfileName", "").strip()
            profile_names.append(name or f"Profile {index}")

        self.action_profile_combo["values"] = profile_names

        if not profile_names:
            self.action_profile_var.set("")
            self.action_profile_combo.set("")
            self.full_setup_button.configure(state=tk.DISABLED)
            self.build_button.configure(state=tk.DISABLED)
            return

        current_index = min(self.current_profile_index, len(profile_names) - 1)
        self.action_profile_combo.current(current_index)
        self.action_profile_var.set(profile_names[current_index])
        self.full_setup_button.configure(state=tk.NORMAL)
        self.build_button.configure(state=tk.NORMAL)

    def _on_action_profile_selected(self, event) -> None:
        if not self.action_profile_combo:
            return

        selection = self.action_profile_var.get()
        profile_names = list(self.action_profile_combo["values"])
        if selection not in profile_names:
            return

        new_index = profile_names.index(selection)
        if new_index == self.current_profile_index:
            return

        self._update_profile_from_vars()
        self.current_profile_index = new_index
        self._load_profile_into_vars()
        self.profile_listbox.selection_clear(0, tk.END)
        self.profile_listbox.selection_set(new_index)
        self.profile_listbox.activate(new_index)

    def _get_selected_action_profile_index(self) -> Optional[int]:
        if not self.profiles:
            return None

        if self.action_profile_combo is not None:
            combo_index = self.action_profile_combo.current()
            if combo_index is not None and combo_index >= 0:
                return combo_index

        if 0 <= self.current_profile_index < len(self.profiles):
            return self.current_profile_index

        return 0

    # ------------------------------------------------------------------
    # Profile handling
    # ------------------------------------------------------------------
    def _refresh_profile_listbox(self) -> None:
        self.profile_listbox.delete(0, tk.END)
        for profile in self.profiles:
            self.profile_listbox.insert(tk.END, profile.get("ProfileName", "(unnamed)"))
        if self.profiles:
            index = min(self.current_profile_index, len(self.profiles) - 1)
            self.profile_listbox.selection_clear(0, tk.END)
            self.profile_listbox.selection_set(index)
            self.profile_listbox.activate(index)
        self._refresh_action_profile_selector()

    def _on_profile_selected(self, event) -> None:
        if not self.profile_listbox.curselection():
            return
        new_index = self.profile_listbox.curselection()[0]
        if new_index == self.current_profile_index:
            return
        self._update_profile_from_vars()
        self.current_profile_index = new_index
        self._load_profile_into_vars()

    def _create_profile(self) -> None:
        self._update_profile_from_vars()
        new_profile = DEFAULT_PROFILE.copy()
        suffix = len(self.profiles) + 1
        new_profile["ProfileName"] = f"New Profile {suffix}"
        self.profiles.append(new_profile)
        self.current_profile_index = len(self.profiles) - 1
        self._refresh_profile_listbox()
        self._load_profile_into_vars()

    def _delete_profile(self) -> None:
        if not self.profiles:
            return
        if not messagebox.askyesno("Confirm", "ต้องการลบโปรไฟล์นี้หรือไม่?"):
            return
        del self.profiles[self.current_profile_index]
        if not self.profiles:
            self.profiles = [DEFAULT_PROFILE.copy()]
        self.current_profile_index = min(self.current_profile_index, len(self.profiles) - 1)
        self._refresh_profile_listbox()
        self._load_profile_into_vars()

    def _save_current_profile(self) -> None:
        self._update_profile_from_vars()
        self._refresh_profile_listbox()
        messagebox.showinfo("Saved", "บันทึกโปรไฟล์เรียบร้อยแล้ว")

    def _update_profile_from_vars(self) -> None:
        if not self.profiles:
            return
        profile = self.profiles[self.current_profile_index]
        for key, var in self.profile_vars.items():
            profile[key] = var.get().strip()

    def _load_profile_into_vars(self) -> None:
        profile = self.profiles[self.current_profile_index]
        for key, var in self.profile_vars.items():
            var.set(profile.get(key, ""))

    # ------------------------------------------------------------------
    # Settings handling
    # ------------------------------------------------------------------
    def _load_settings_into_vars(self) -> None:
        def get_value(settings_dict, path: Tuple[str, ...]):
            current = settings_dict
            for part in path:
                if not isinstance(current, dict):
                    return ""
                current = current.get(part, "")
            return "" if current is None else str(current)

        for path, var in self.settings_vars.items():
            var.set(get_value(self.settings, path))

    def _collect_settings_from_vars(self) -> Dict[str, object]:
        settings = {
            "GroupName": self.settings_vars[("GroupName",)].get().strip(),
            "GroupDesc": self.settings_vars[("GroupDesc",)].get().strip(),
            "VpnTunnelNetwork": self.settings_vars[("VpnTunnelNetwork",)].get().strip(),
            "VpnLocalNetwork": self.settings_vars[("VpnLocalNetwork",)].get().strip(),
            "StaticKeyMode": self.settings_vars[("StaticKeyMode",)].get().strip(),
            "VpnDevType": self.settings_vars[("VpnDevType",)].get().strip(),
            "VpnTopology": self.settings_vars[("VpnTopology",)].get().strip(),
            "InterfaceDesc": self.settings_vars[("InterfaceDesc",)].get().strip(),
            "NamePatterns": {
                "CaPrefix": self.settings_vars[("NamePatterns", "CaPrefix")].get().strip(),
                "ServerCn": self.settings_vars[("NamePatterns", "ServerCn")].get().strip(),
                "StaticKeyPrefix": self.settings_vars[("NamePatterns", "StaticKeyPrefix")].get().strip(),
                "InstancePrefix": self.settings_vars[("NamePatterns", "InstancePrefix")].get().strip(),
            },
            "Lifetimes": {},
            "Firewall": {
                "VpnListenPort": self.settings_vars[("Firewall", "VpnListenPort")].get().strip(),
                "VpnProto": self.settings_vars[("Firewall", "VpnProto")].get().strip(),
            },
        }

        lifetime_fields = {
            "CALifetimeDays": ("Lifetimes", "CALifetimeDays"),
            "ServerCertLifetimeDays": ("Lifetimes", "ServerCertLifetimeDays"),
            "ClientCertLifetimeDays": ("Lifetimes", "ClientCertLifetimeDays"),
        }

        for key, path in lifetime_fields.items():
            value = self.settings_vars[path].get().strip()
            if value:
                try:
                    settings["Lifetimes"][key] = int(value)
                except ValueError:
                    raise ValueError(f"ค่าของ {key} ต้องเป็นตัวเลขจำนวนเต็ม")
            else:
                settings["Lifetimes"][key] = 0

        return settings

    def _save_settings(self) -> None:
        try:
            self.settings = self._collect_settings_from_vars()
        except ValueError as exc:
            messagebox.showerror("Invalid data", str(exc))
            return
        self.store.save_settings(self.settings)
        messagebox.showinfo("Saved", "บันทึกการตั้งค่าเรียบร้อยแล้ว")

    # ------------------------------------------------------------------
    # User handling
    # ------------------------------------------------------------------
    def _refresh_user_listbox(self) -> None:
        self.user_listbox.delete(0, tk.END)
        for user in self.users:
            self.user_listbox.insert(tk.END, user.get("Name", "(unnamed)"))
        if self.users and self.current_user_index is not None:
            index = min(self.current_user_index, len(self.users) - 1)
            self.user_listbox.selection_clear(0, tk.END)
            self.user_listbox.selection_set(index)
            self.user_listbox.activate(index)
        elif not self.users:
            self.current_user_index = None

    def _on_user_selected(self, event) -> None:
        if not self.user_listbox.curselection():
            return
        new_index = self.user_listbox.curselection()[0]
        if self.current_user_index == new_index:
            return
        self._update_user_from_vars()
        self.current_user_index = new_index
        self._load_current_user_into_vars()

    def _create_user(self) -> None:
        self._update_user_from_vars()
        new_user = DEFAULT_USER.copy()
        suffix = len(self.users) + 1
        new_user["Name"] = f"user{suffix}"
        self.users.append(new_user)
        self.current_user_index = len(self.users) - 1
        self._refresh_user_listbox()
        self._load_current_user_into_vars()

    def _delete_user(self) -> None:
        if self.current_user_index is None:
            return
        if not messagebox.askyesno("Confirm", "ต้องการลบผู้ใช้นี้หรือไม่?"):
            return
        del self.users[self.current_user_index]
        if not self.users:
            self.current_user_index = None
            for var in self.user_vars.values():
                var.set("")
        else:
            self.current_user_index = min(self.current_user_index, len(self.users) - 1)
            self._load_current_user_into_vars()
        self._refresh_user_listbox()

    def _save_current_user(self) -> None:
        self._update_user_from_vars()
        self._refresh_user_listbox()
        messagebox.showinfo("Saved", "บันทึกข้อมูลผู้ใช้เรียบร้อยแล้ว")

    def _update_user_from_vars(self) -> None:
        if self.current_user_index is None:
            return
        user = self.users[self.current_user_index]
        for key, var in self.user_vars.items():
            user[key] = var.get().strip()

    def _load_current_user_into_vars(self) -> None:
        if self.current_user_index is None:
            for var in self.user_vars.values():
                var.set("")
            return
        user = self.users[self.current_user_index]
        for key, var in self.user_vars.items():
            var.set(user.get(key, ""))

    # ------------------------------------------------------------------
    # Saving helpers
    # ------------------------------------------------------------------
    def _save_all(self, show_message: bool = True) -> None:
        self._update_profile_from_vars()
        try:
            self.settings = self._collect_settings_from_vars()
        except ValueError as exc:
            messagebox.showerror("Invalid data", str(exc))
            return
        self._update_user_from_vars()

        self.store.save_profiles(self.profiles)
        self.store.save_settings(self.settings)
        self.store.save_users(self.users)

        if show_message:
            messagebox.showinfo("Saved", "บันทึกไฟล์คอนฟิกทั้งหมดเรียบร้อยแล้ว")

    # ------------------------------------------------------------------
    # Script execution
    # ------------------------------------------------------------------
    def _run_full_setup(self) -> None:
        self._run_script("Run-Full-Setup.ps1", "Full Setup")

    def _run_build_ovpn(self) -> None:
        self._run_script("Build-Ovpn-Files.ps1", "Build OVPN")

    def _run_script(self, script_name: str, friendly_name: str) -> None:
        try:
            self._save_all(show_message=False)
        except ValueError:
            # Error already shown to the user.
            return

        powershell = self._get_powershell_executable()
        if not powershell:
            messagebox.showerror(
                "PowerShell not found",
                "ไม่พบคำสั่ง PowerShell หรือ pwsh ในระบบ\nกรุณาติดตั้งก่อนใช้งาน",
            )
            return

        script_path = BASE_DIR / script_name
        if not script_path.exists():
            messagebox.showerror("Missing script", f"ไม่พบไฟล์ {script_name}")
            return

        profile_index = self._get_selected_action_profile_index()
        if profile_index is None:
            messagebox.showerror("No profile", "กรุณาเลือกโปรไฟล์ก่อนรันสคริปต์")
            return

        selected_profile = self.profiles[profile_index]
        profile_name = selected_profile.get("ProfileName", "").strip()
        display_name = profile_name or f"Profile {profile_index + 1}"

        self._append_log(f"\n>>> เริ่มรัน {friendly_name} สำหรับโปรไฟล์ {display_name}\n")
        self._set_action_buttons_state(tk.DISABLED)

        def worker() -> None:
            cmd = [
                powershell,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script_path),
                "-ProfileIndex",
                str(profile_index + 1),
            ]
            if profile_name:
                cmd.extend(["-ProfileName", profile_name])
            process = subprocess.Popen(
                cmd,
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
            )
            assert process.stdout is not None
            for line in process.stdout:
                self._append_log(line)
            retcode = process.wait()
            if retcode == 0:
                self._append_log(f">>> {friendly_name} เสร็จสมบูรณ์\n")
            else:
                self._append_log(f">>> {friendly_name} ล้มเหลว (exit code {retcode})\n")
            self._set_action_buttons_state(tk.NORMAL)

        threading.Thread(target=worker, daemon=True).start()

    def _set_action_buttons_state(self, state: str) -> None:
        for button in (self.save_button, self.full_setup_button, self.build_button):
            button.configure(state=state)

    def _append_log(self, text: str) -> None:
        def append() -> None:
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, text)
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)

        self.log_text.after(0, append)

    @staticmethod
    def _get_powershell_executable() -> Optional[str]:
        for candidate in ("pwsh", "powershell", "powershell.exe"):
            if shutil.which(candidate):
                return candidate
        return None


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
