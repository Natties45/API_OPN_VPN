#!/usr/bin/env python3
"""Tkinter GUI wrapper for the OPNsense OpenVPN automation scripts.

This version provides multi-profile management where each profile owns its
settings and users.  The GUI keeps the PowerShell automation compatible by
exporting legacy JSON files whenever actions run.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import threading
from copy import deepcopy
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import messagebox, scrolledtext, simpledialog, ttk

from models import (
    CONFIG_DATA_PATH,
    ConfigManager,
    DEFAULT_AUTOMATION,
    DEFAULT_CONNECTION,
    DEFAULT_USER_TEMPLATE,
    Profile,
    User,
)

BASE_DIR = Path(__file__).resolve().parent


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("OPNsense OpenVPN Setup GUI")
        self.geometry("1000x720")

        self.manager = ConfigManager.load()
        profiles = self.manager.list_profiles()
        self.selected_profile_id: Optional[str] = (
            self.manager.active_profile_id if profiles else None
        )
        if not self.selected_profile_id and profiles:
            self.selected_profile_id = profiles[0].id

        self.current_user_username: Optional[str] = None
        self._last_loaded_user: Optional[User] = None

        self.connection_vars: Dict[str, tk.StringVar] = {
            key: tk.StringVar() for key in DEFAULT_CONNECTION
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
            "username": tk.StringVar(),
            "password": tk.StringVar(),
            "full_name": tk.StringVar(),
            "email": tk.StringVar(),
        }
        self.profile_name_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Ready")

        self.profile_listbox: Optional[tk.Listbox] = None
        self.user_listbox: Optional[tk.Listbox] = None
        self.action_profile_combo: Optional[ttk.Combobox] = None
        self.full_setup_button: Optional[ttk.Button] = None
        self.build_button: Optional[ttk.Button] = None
        self.log_text: Optional[scrolledtext.ScrolledText] = None

        self._in_profile_refresh = False
        self._in_action_refresh = False

        self._build_layout()
        self._refresh_profile_listbox()
        self._refresh_action_profile_selector()
        self._load_selected_profile()

    # ------------------------------------------------------------------
    # Layout helpers
    # ------------------------------------------------------------------
    def _build_layout(self) -> None:
        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

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

        status_frame = ttk.Frame(self)
        status_frame.pack(fill=tk.X, padx=10, pady=(0, 10))
        ttk.Label(status_frame, textvariable=self.status_var).pack(anchor=tk.W)

    def _build_profile_tab(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(1, weight=1)

        list_frame = ttk.Frame(frame)
        list_frame.grid(row=0, column=0, sticky="ns")
        ttk.Label(list_frame, text="Profiles").pack(anchor=tk.W)

        self.profile_listbox = tk.Listbox(list_frame, height=14)
        self.profile_listbox.pack(fill=tk.Y, expand=True)
        self.profile_listbox.bind("<<ListboxSelect>>", self._on_profile_selected)

        btn_frame = ttk.Frame(list_frame)
        btn_frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btn_frame, text="New Profile", command=self._create_profile).pack(
            side=tk.TOP, fill=tk.X, pady=2
        )
        ttk.Button(btn_frame, text="Rename", command=self._rename_profile).pack(
            side=tk.TOP, fill=tk.X, pady=2
        )
        ttk.Button(btn_frame, text="Delete", command=self._delete_profile).pack(
            side=tk.TOP, fill=tk.X, pady=2
        )

        field_frame = ttk.Frame(frame)
        field_frame.grid(row=0, column=1, sticky="nsew", padx=(15, 0))
        field_frame.columnconfigure(1, weight=1)

        ttk.Label(field_frame, textvariable=self.profile_name_var, font=("Segoe UI", 11, "bold")).grid(
            row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 8)
        )

        connection_fields = (
            ("API Base URL", "ApiBaseUrl"),
            ("API Key", "ApiKey"),
            ("API Secret", "ApiSecret"),
            ("SSH Host", "SshHost"),
            ("SSH User", "SshUser"),
            ("SSH Password", "SshPass"),
        )

        for idx, (label, key) in enumerate(connection_fields, start=1):
            ttk.Label(field_frame, text=label).grid(row=idx, column=0, sticky=tk.W, pady=2)
            entry = ttk.Entry(field_frame, textvariable=self.connection_vars[key])
            entry.grid(row=idx, column=1, sticky="ew", pady=2)
            if key in {"ApiSecret", "SshPass"}:
                entry.configure(show="*")

        ttk.Button(field_frame, text="Save Connection", command=self._save_connection).grid(
            row=len(connection_fields) + 1, column=1, sticky=tk.E, pady=(12, 0)
        )

    def _build_settings_tab(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(1, weight=1)

        sections = [
            (
                "General",
                [
                    ("Group Name", ("GroupName",)),
                    ("Group Description", ("GroupDesc",)),
                    ("VPN Tunnel Network", ("VpnTunnelNetwork",)),
                    ("VPN Local Network", ("VpnLocalNetwork",)),
                    ("Static Key Mode", ("StaticKeyMode",)),
                    ("Device Type", ("VpnDevType",)),
                    ("Topology", ("VpnTopology",)),
                    ("Interface Description", ("InterfaceDesc",)),
                ],
            ),
            (
                "Name Patterns",
                [
                    ("CA Prefix", ("NamePatterns", "CaPrefix")),
                    ("Server CN", ("NamePatterns", "ServerCn")),
                    ("Static Key Prefix", ("NamePatterns", "StaticKeyPrefix")),
                    ("Instance Prefix", ("NamePatterns", "InstancePrefix")),
                ],
            ),
            (
                "Lifetimes",
                [
                    ("CA Lifetime (days)", ("Lifetimes", "CALifetimeDays")),
                    ("Server Cert Lifetime (days)", ("Lifetimes", "ServerCertLifetimeDays")),
                    ("Client Cert Lifetime (days)", ("Lifetimes", "ClientCertLifetimeDays")),
                ],
            ),
            (
                "Firewall",
                [
                    ("Listen Port", ("Firewall", "VpnListenPort")),
                    ("Protocol", ("Firewall", "VpnProto")),
                ],
            ),
        ]

        current_row = 0
        for title, items in sections:
            ttk.Label(frame, text=title, font=("Segoe UI", 10, "bold")).grid(
                row=current_row, column=0, columnspan=2, sticky=tk.W, pady=(10 if current_row else 0, 0)
            )
            current_row += 1
            for label, key in items:
                ttk.Label(frame, text=label).grid(row=current_row, column=0, sticky=tk.W, pady=2)
                ttk.Entry(frame, textvariable=self.settings_vars[key]).grid(
                    row=current_row, column=1, sticky="ew", pady=2
                )
                current_row += 1

        ttk.Button(frame, text="Save Settings", command=self._save_settings).grid(
            row=current_row, column=1, sticky=tk.E, pady=(12, 0)
        )

    def _build_users_tab(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(1, weight=1)

        list_frame = ttk.Frame(frame)
        list_frame.grid(row=0, column=0, sticky="ns")
        ttk.Label(list_frame, text="Users").pack(anchor=tk.W)

        self.user_listbox = tk.Listbox(list_frame, height=16)
        self.user_listbox.pack(fill=tk.Y, expand=True)
        self.user_listbox.bind("<<ListboxSelect>>", self._on_user_selected)

        btn_frame = ttk.Frame(list_frame)
        btn_frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btn_frame, text="New", command=self._new_user).pack(side=tk.LEFT, padx=2)
        ttk.Button(btn_frame, text="Delete", command=self._delete_user).pack(side=tk.LEFT, padx=2)

        field_frame = ttk.Frame(frame)
        field_frame.grid(row=0, column=1, sticky="nsew", padx=(15, 0))
        field_frame.columnconfigure(1, weight=1)

        user_fields = (
            ("Username", "username"),
            ("Password", "password"),
            ("Full Name", "full_name"),
            ("Email", "email"),
        )

        for idx, (label, key) in enumerate(user_fields):
            ttk.Label(field_frame, text=label).grid(row=idx, column=0, sticky=tk.W, pady=2)
            entry = ttk.Entry(field_frame, textvariable=self.user_vars[key])
            entry.grid(row=idx, column=1, sticky="ew", pady=2)
            if key == "password":
                entry.configure(show="*")

        ttk.Button(field_frame, text="Save User", command=self._save_user).grid(
            row=len(user_fields), column=1, sticky=tk.E, pady=(12, 0)
        )

    def _build_actions_tab(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(0, weight=1)

        action_frame = ttk.Frame(frame)
        action_frame.grid(row=0, column=0, sticky=tk.E)

        self.full_setup_button = ttk.Button(
            action_frame, text="Run Full Setup", command=self._run_full_setup
        )
        self.full_setup_button.grid(row=0, column=0, padx=5, pady=5)

        self.build_button = ttk.Button(
            action_frame, text="Build OVPN Files", command=self._run_build_ovpn
        )
        self.build_button.grid(row=0, column=1, padx=5, pady=5)

        select_frame = ttk.Frame(frame)
        select_frame.grid(row=1, column=0, sticky="ew", padx=5)
        select_frame.columnconfigure(1, weight=1)

        ttk.Label(select_frame, text="Profile for scripts:").grid(row=0, column=0, sticky=tk.W)
        self.action_profile_var = tk.StringVar()
        self.action_profile_combo = ttk.Combobox(
            select_frame, textvariable=self.action_profile_var, state="readonly"
        )
        self.action_profile_combo.grid(row=0, column=1, sticky="ew")
        self.action_profile_combo.bind("<<ComboboxSelected>>", self._on_action_profile_selected)

        self.log_text = scrolledtext.ScrolledText(frame, height=24, state=tk.DISABLED)
        self.log_text.grid(row=2, column=0, sticky="nsew", padx=5, pady=(10, 0))
        frame.rowconfigure(2, weight=1)

    # ------------------------------------------------------------------
    # Profile helpers
    # ------------------------------------------------------------------
    def _refresh_profile_listbox(self) -> None:
        if not self.profile_listbox:
            return
        profiles = self.manager.list_profiles()
        active_id = self.manager.active_profile_id
        if not self.selected_profile_id and active_id:
            self.selected_profile_id = active_id

        self._in_profile_refresh = True
        try:
            self.profile_listbox.delete(0, tk.END)
            for profile in profiles:
                label = profile.name
                if profile.id == active_id:
                    label = f"{label} (active)"
                self.profile_listbox.insert(tk.END, label)

            if not profiles:
                self.profile_listbox.selection_clear(0, tk.END)
                self.selected_profile_id = None
            else:
                if not self.selected_profile_id or not any(
                    profile.id == self.selected_profile_id for profile in profiles
                ):
                    self.selected_profile_id = profiles[0].id

                index = next(
                    (idx for idx, profile in enumerate(profiles) if profile.id == self.selected_profile_id),
                    0,
                )
                self.profile_listbox.selection_clear(0, tk.END)
                self.profile_listbox.selection_set(index)
                self.profile_listbox.activate(index)
        finally:
            self._in_profile_refresh = False

        self._refresh_action_profile_selector()

    def _activate_profile(self, profile_id: str, persist: bool = True) -> None:
        if not profile_id:
            return
        self.selected_profile_id = profile_id
        try:
            self.manager.set_active_profile(profile_id)
        except ValueError:
            return
        if persist:
            self._persist_and_export(profile_id)
        if not self._in_profile_refresh:
            self._refresh_profile_listbox()


    def _create_profile(self) -> None:
        name = simpledialog.askstring("New Profile", "Profile name:", parent=self)
        if name is None:
            return
        try:
            profile = self.manager.create_profile(name)
        except ValueError as exc:
            messagebox.showerror("Cannot create profile", str(exc))
            return
        self._activate_profile(profile.id)
        self._load_selected_profile()
        self._set_status(f"Profile '{profile.name}' created.")

    def _rename_profile(self) -> None:
        profile = self._get_selected_profile()
        if not profile:
            return
        new_name = simpledialog.askstring(
            "Rename Profile", "New profile name:", initialvalue=profile.name, parent=self
        )
        if new_name is None:
            return
        try:
            self.manager.rename_profile(profile.id, new_name)
        except ValueError as exc:
            messagebox.showerror("Cannot rename profile", str(exc))
            return
        self._persist_and_export(profile.id)
        self._refresh_profile_listbox()
        self._load_selected_profile()
        self._set_status(f"Profile renamed to '{new_name.strip()}'.")

    def _delete_profile(self) -> None:
        profile = self._get_selected_profile()
        if not profile:
            return
        if not messagebox.askyesno(
            "Delete Profile",
            f"Delete profile '{profile.name}'? This cannot be undone.",
            parent=self,
        ):
            return
        try:
            self.manager.delete_profile(profile.id)
        except ValueError as exc:
            messagebox.showerror("Cannot delete profile", str(exc))
            return
        remaining = self.manager.list_profiles()
        self.selected_profile_id = remaining[0].id if remaining else None
        if self.selected_profile_id:
            self._activate_profile(self.selected_profile_id)
        else:
            self._persist_and_export()
            self._refresh_profile_listbox()
        self._load_selected_profile()
        self._set_status("Profile deleted.")

    def _on_profile_selected(self, event) -> None:
        if not self.profile_listbox or self._in_profile_refresh:
            return
        selection = self.profile_listbox.curselection()
        if not selection:
            return
        profiles = self.manager.list_profiles()
        index = selection[0]
        if index >= len(profiles):
            return
        self.selected_profile_id = profiles[index].id
        self._load_selected_profile()
        if self.selected_profile_id:
            self._activate_profile(self.selected_profile_id)

    def _get_selected_profile(self) -> Optional[Profile]:
        if not self.selected_profile_id:
            return None
        try:
            return self.manager.get_profile(self.selected_profile_id)
        except ValueError:
            return None

    def _load_selected_profile(self) -> None:
        profile = self._get_selected_profile()
        if not profile:
            self.profile_name_var.set("No profile selected")
            for var in self.connection_vars.values():
                var.set("")
            self._clear_settings_form()
            self._refresh_user_listbox([])
            return

        self.profile_name_var.set(profile.name)
        connection = profile.settings.get("connection", {})
        for key, var in self.connection_vars.items():
            var.set(connection.get(key, DEFAULT_CONNECTION.get(key, "")))
        self._load_settings_into_vars(profile.settings.get("automation", {}))
        self._refresh_user_listbox(profile.users)
        if profile.users:
            self._select_user_in_list(profile.users[0].username)
        else:
            self._new_user()

    def _save_connection(self) -> None:
        profile = self._get_selected_profile()
        if not profile:
            messagebox.showerror("No profile", "Select a profile first.")
            return
        payload = {key: var.get().strip() for key, var in self.connection_vars.items()}
        self.manager.update_profile_connection(profile.id, payload)
        self._persist_and_export(profile.id)
        self._set_status("Connection details saved.")

    # ------------------------------------------------------------------
    # Settings helpers
    # ------------------------------------------------------------------
    def _clear_settings_form(self) -> None:
        for var in self.settings_vars.values():
            var.set("")

    def _load_settings_into_vars(self, settings: Dict[str, object]) -> None:
        def get_value(path: Tuple[str, ...]):
            current = settings
            for part in path:
                if not isinstance(current, dict):
                    return ""
                current = current.get(part)
            return "" if current is None else str(current)

        for path, var in self.settings_vars.items():
            var.set(get_value(path))

    def _collect_settings_from_vars(self) -> Dict[str, object]:
        automation = deepcopy(DEFAULT_AUTOMATION)

        def set_value(path: Tuple[str, ...], value: str) -> None:
            current = automation
            for part in path[:-1]:
                current = current.setdefault(part, {})
            current[path[-1]] = value

        for path, var in self.settings_vars.items():
            value = var.get().strip()
            if path[0] == "Lifetimes" and value:
                try:
                    value_int = int(value)
                except ValueError:
                    raise ValueError(f"Field '{path[-1]}' must be an integer.")
                set_value(path, value_int)
            else:
                set_value(path, value)
        return automation

    def _save_settings(self) -> None:
        profile = self._get_selected_profile()
        if not profile:
            messagebox.showerror("No profile", "Select a profile first.")
            return
        try:
            automation = self._collect_settings_from_vars()
        except ValueError as exc:
            messagebox.showerror("Invalid data", str(exc))
            return
        self.manager.update_profile_settings(profile.id, automation)
        self._persist_and_export(profile.id)
        self._set_status("Settings saved.")

    # ------------------------------------------------------------------
    # User helpers
    # ------------------------------------------------------------------
    def _refresh_user_listbox(self, users: List[User]) -> None:
        if not self.user_listbox:
            return
        self.user_listbox.delete(0, tk.END)
        for user in users:
            self.user_listbox.insert(tk.END, user.username)
        # leave selection handling to caller

    def _select_user_in_list(self, username: str) -> None:
        profile = self._get_selected_profile()
        if not profile or not self.user_listbox:
            return
        self.user_listbox.selection_clear(0, tk.END)
        for idx, user in enumerate(profile.users):
            if user.username.lower() == username.lower():
                self.user_listbox.selection_set(idx)
                self.user_listbox.activate(idx)
                self.current_user_username = user.username
                self._last_loaded_user = deepcopy(user)
                self.user_vars["username"].set(user.username)
                self.user_vars["password"].set(user.password)
                self.user_vars["full_name"].set(user.full_name)
                self.user_vars["email"].set(user.email)
                return
        self._new_user()



    def _new_user(self) -> None:
        profile = self._get_selected_profile()
        if not profile:
            return
        template = deepcopy(DEFAULT_USER_TEMPLATE)
        existing = {user.username.lower() for user in profile.users}
        base = template["username"].rstrip("0123456789") or "user"
        counter = 1
        candidate = template["username"]
        while candidate.lower() in existing:
            candidate = f"{base}{counter}"
            counter += 1
        template["username"] = candidate
        if self.user_listbox:
            self.user_listbox.selection_clear(0, tk.END)
        for key, var in self.user_vars.items():
            var.set(template.get(key, ""))
        self.current_user_username = None
        self._last_loaded_user = None

    def _on_user_selected(self, event) -> None:
        profile = self._get_selected_profile()
        if not profile or not self.user_listbox:
            return
        selection = self.user_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        if index >= len(profile.users):
            return
        user = profile.users[index]
        self._select_user_in_list(user.username)

    def _save_user(self) -> None:
        profile = self._get_selected_profile()
        if not profile:
            messagebox.showerror("No profile", "Select a profile first.")
            return
        username = self.user_vars["username"].get().strip()
        password = self.user_vars["password"].get().strip()
        full_name = self.user_vars["full_name"].get().strip()
        email = self.user_vars["email"].get().strip()
        if not username:
            messagebox.showerror("Invalid user", "Username cannot be empty.")
            return
        new_user = User(username=username, password=password, full_name=full_name, email=email)
        if self.current_user_username is None:
            try:
                self.manager.add_user(profile.id, new_user)
            except ValueError as exc:
                messagebox.showerror("Cannot add user", str(exc))
                return
        else:
            if username.lower() == self.current_user_username.lower():
                try:
                    self.manager.update_user(profile.id, new_user)
                except ValueError as exc:
                    messagebox.showerror("Cannot update user", str(exc))
                    return
            else:
                # Rename scenario: remove old, then add new. Restore on failure.
                original = deepcopy(self._last_loaded_user) if self._last_loaded_user else None
                try:
                    self.manager.delete_user(profile.id, self.current_user_username)
                    self.manager.add_user(profile.id, new_user)
                except ValueError as exc:
                    if original:
                        self.manager.add_user(profile.id, original)
                    messagebox.showerror("Cannot rename user", str(exc))
                    return
        self._persist_and_export(profile.id)
        self._set_status(f"User '{username}' saved.")
        self._refresh_user_listbox(profile.users)
        self._select_user_in_list(username)

    def _delete_user(self) -> None:
        profile = self._get_selected_profile()
        if not profile or not self.user_listbox:
            return
        selection = self.user_listbox.curselection()
        if not selection:
            messagebox.showinfo("Delete User", "Select a user first.")
            return
        index = selection[0]
        if index >= len(profile.users):
            return
        user = profile.users[index]
        if not messagebox.askyesno("Delete User", f"Delete user '{user.username}'?", parent=self):
            return
        try:
            self.manager.delete_user(profile.id, user.username)
        except ValueError as exc:
            messagebox.showerror("Cannot delete user", str(exc))
            return
        self._persist_and_export(profile.id)
        self._set_status(f"User '{user.username}' deleted.")
        self._load_selected_profile()

    # ------------------------------------------------------------------
    # Actions tab helpers
    # ------------------------------------------------------------------
    def _refresh_action_profile_selector(self) -> None:
        if not self.action_profile_combo:
            return
        profiles = self.manager.list_profiles()
        labels = [profile.name for profile in profiles]

        self._in_action_refresh = True
        try:
            self.action_profile_combo["values"] = labels
            if not profiles:
                self.action_profile_var.set("")
                self.action_profile_combo.set("")
                for button in (self.full_setup_button, self.build_button):
                    if button:
                        button.configure(state=tk.DISABLED)
                return

            for button in (self.full_setup_button, self.build_button):
                if button:
                    button.configure(state=tk.NORMAL)

            active_id = self.manager.active_profile_id or profiles[0].id
            active_index = next(
                (idx for idx, profile in enumerate(profiles) if profile.id == active_id), 0
            )
            self.action_profile_combo.current(active_index)
            self.action_profile_var.set(labels[active_index])
        finally:
            self._in_action_refresh = False

    def _on_action_profile_selected(self, event) -> None:
        if not self.action_profile_combo or self._in_action_refresh:
            return
        profiles = self.manager.list_profiles()
        selection = self.action_profile_combo.current()
        if selection < 0 or selection >= len(profiles):
            return
        self.selected_profile_id = profiles[selection].id
        self._load_selected_profile()
        if self.selected_profile_id:
            self._activate_profile(self.selected_profile_id)

    def _commit_profile_changes(self) -> bool:
        profile = self._get_selected_profile()
        if not profile:
            messagebox.showerror("No profile", "Select a profile first.")
            return False
        # Connection
        payload = {key: var.get().strip() for key, var in self.connection_vars.items()}
        self.manager.update_profile_connection(profile.id, payload)
        # Settings
        try:
            automation = self._collect_settings_from_vars()
        except ValueError as exc:
            messagebox.showerror("Invalid data", str(exc))
            return False
        self.manager.update_profile_settings(profile.id, automation)
        # Users (if editing unsaved new user, keep as-is)
        if self.current_user_username is None:
            # Nothing to commit; user must press Save User for new entries.
            pass
        return True

    def _run_full_setup(self) -> None:
        self._run_script("Run-Full-Setup.ps1", "Full Setup")

    def _run_build_ovpn(self) -> None:
        self._run_script("Build-Ovpn-Files.ps1", "Build OVPN")

    def _run_script(self, script_name: str, friendly_name: str) -> None:
        if not self._commit_profile_changes():
            return

        profile = self._get_selected_profile()
        if not profile:
            return
        try:
            self._persist_and_export(profile.id, suppress_errors=False)
        except ValueError as exc:
            messagebox.showerror("Export failed", str(exc))
            return

        powershell = self._get_powershell_executable()
        if not powershell:
            messagebox.showerror(
                "PowerShell not found",
                "Could not locate 'pwsh' or 'powershell'. Please install PowerShell.",
            )
            return

        script_path = BASE_DIR / script_name
        if not script_path.exists():
            messagebox.showerror("Missing script", f"Could not find {script_name}.")
            return

        profiles = self.manager.list_profiles()
        try:
            profile_index = next(idx for idx, item in enumerate(profiles) if item.id == profile.id)
        except StopIteration:
            messagebox.showerror("Profile error", "Selected profile not found.")
            return

        display_name = profile.name or f"Profile {profile_index + 1}"
        self._append_log(f"\n>>> Starting {friendly_name} for {display_name}\n")
        self._set_button_state(tk.DISABLED)

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
                "-ProfileName",
                display_name,
            ]
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
                self._append_log(f">>> {friendly_name} completed successfully.\n")
            else:
                self._append_log(f">>> {friendly_name} failed (exit code {retcode}).\n")
            self._set_button_state(tk.NORMAL)

        threading.Thread(target=worker, daemon=True).start()

    def _set_button_state(self, state: str) -> None:
        for button in (self.full_setup_button, self.build_button):
            if button:
                button.configure(state=state)

    def _append_log(self, text: str) -> None:
        if not self.log_text:
            return

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
    def _persist_and_export(self, profile_id: Optional[str] = None, suppress_errors: bool = True) -> None:
        self.manager.save()
        try:
            self.manager.export_legacy_files(profile_id)
        except ValueError:
            if not suppress_errors:
                raise


    def _set_status(self, message: str) -> None:
        self.status_var.set(message)


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)







