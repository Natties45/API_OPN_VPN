
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
from typing import Callable, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import messagebox, scrolledtext, simpledialog, ttk

from models import (
    ConfigManager,
    DEFAULT_AUTOMATION,
    DEFAULT_CONNECTION,
    DEFAULT_USER_TEMPLATE,
    OPNsenseProfile,
    User,
    UserProfile,
    make_unique_username,
)

BASE_DIR = Path(__file__).resolve().parent


class AppState:
    """Holds current selections and notifies listeners when they change."""

    def __init__(
        self,
        current_opnsense_profile_id: Optional[str] = None,
        current_user_profile_id: Optional[str] = None,
    ) -> None:
        self.current_opnsense_profile_id = current_opnsense_profile_id
        self.current_user_profile_id = current_user_profile_id
        self.on_user_profile_changed: List[Callable[[Optional[str]], None]] = []

    def set_current_user_profile_id(self, profile_id: Optional[str]) -> bool:
        if self.current_user_profile_id == profile_id:
            return False
        self.current_user_profile_id = profile_id
        for callback in list(self.on_user_profile_changed):
            callback(profile_id)
        return True


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("OPNsense OpenVPN Setup GUI")
        self.geometry("1000x720")

        self.manager = ConfigManager.load()
        opnsense_profiles = self.manager.list_opnsense_profiles()
        user_profiles = self.manager.list_user_profiles()
        self.app_state = AppState(
            current_opnsense_profile_id=self.manager.get_selected_opnsense_profile_id()
            or (opnsense_profiles[0].id if opnsense_profiles else None),
            current_user_profile_id=self.manager.get_selected_user_profile_id()
            or (user_profiles[0].id if user_profiles else None),
        )

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
        self.connection_entries: List[tk.Entry] = []
        self.settings_entries: List[tk.Entry] = []
        self.status_var = tk.StringVar(value="Ready")
        self.user_profile_context_var = tk.StringVar(value="User Profile: (none)")

        self.profile_listbox: Optional[tk.Listbox] = None
        self.user_profile_listbox: Optional[tk.Listbox] = None
        self.user_listbox: Optional[tk.Listbox] = None
        self.action_opnsense_combo: Optional[ttk.Combobox] = None
        self.action_user_profile_combo: Optional[ttk.Combobox] = None
        self.full_setup_button: Optional[ttk.Button] = None
        self.build_button: Optional[ttk.Button] = None
        self.log_text: Optional[scrolledtext.ScrolledText] = None

        self.btn_profile_new: Optional[ttk.Button] = None
        self.btn_profile_rename: Optional[ttk.Button] = None
        self.btn_profile_duplicate: Optional[ttk.Button] = None
        self.btn_profile_delete: Optional[ttk.Button] = None

        self.btn_user_profile_new: Optional[ttk.Button] = None
        self.btn_user_profile_rename: Optional[ttk.Button] = None
        self.btn_user_profile_duplicate: Optional[ttk.Button] = None
        self.btn_user_profile_delete: Optional[ttk.Button] = None

        self.users_btn_new: Optional[ttk.Button] = None
        self.users_btn_duplicate: Optional[ttk.Button] = None
        self.users_btn_delete: Optional[ttk.Button] = None
        self.user_save_button: Optional[ttk.Button] = None
        self.user_entries: List[tk.Entry] = []

        self.actions_opnsense_var = tk.StringVar()
        self.actions_user_profile_var = tk.StringVar()
        self._action_opnsense_ids: List[str] = []
        self._action_user_profile_ids: List[str] = []
        self._actions_opnsense_profile_id: Optional[str] = self.app_state.current_opnsense_profile_id
        self._actions_user_profile_id: Optional[str] = self.app_state.current_user_profile_id

        self._in_opnsense_refresh = False
        self._in_user_profile_refresh = False
        self._in_user_refresh = False
        self._in_action_refresh = False

        self._build_layout()
        self.app_state.on_user_profile_changed.append(self._on_app_state_user_profile_changed)
        self._register_manager_callbacks()

        self._refresh_opnsense_profile_listbox()
        self._load_selected_opnsense_profile()
        self._refresh_action_opnsense_selector()
        self._update_profile_buttons_state()
        self._on_app_state_user_profile_changed(self.app_state.current_user_profile_id)

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

        notebook.add(profile_frame, text="OPNsense Profiles")
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
        ttk.Label(list_frame, text="OPNsense Profiles").pack(anchor=tk.W)

        self.profile_listbox = tk.Listbox(list_frame, height=14)
        self.profile_listbox.pack(fill=tk.Y, expand=True)
        self.profile_listbox.bind("<<ListboxSelect>>", self._on_opnsense_profile_selected)

        btn_frame = ttk.Frame(list_frame)
        btn_frame.pack(fill=tk.X, pady=(6, 0))
        self.btn_profile_new = ttk.Button(btn_frame, text="New Profile", command=self._create_profile)
        self.btn_profile_new.pack(side=tk.TOP, fill=tk.X, pady=2)
        self.btn_profile_rename = ttk.Button(btn_frame, text="Rename", command=self._rename_profile)
        self.btn_profile_rename.pack(side=tk.TOP, fill=tk.X, pady=2)
        self.btn_profile_duplicate = ttk.Button(
            btn_frame, text="Duplicate", command=self._duplicate_profile
        )
        self.btn_profile_duplicate.pack(side=tk.TOP, fill=tk.X, pady=2)
        self.btn_profile_delete = ttk.Button(btn_frame, text="Delete", command=self._delete_profile)
        self.btn_profile_delete.pack(side=tk.TOP, fill=tk.X, pady=2)

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
            self.connection_entries.append(entry)

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
                entry = ttk.Entry(frame, textvariable=self.settings_vars[key])
                entry.grid(row=current_row, column=1, sticky="ew", pady=2)
                self.settings_entries.append(entry)
                current_row += 1

        ttk.Button(frame, text="Save Settings", command=self._save_settings).grid(
            row=current_row, column=1, sticky=tk.E, pady=(12, 0)
        )

    def _build_users_tab(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(0, weight=1)

        left_container = ttk.Frame(frame)
        left_container.grid(row=0, column=0, sticky="ns")
        left_container.columnconfigure(0, weight=1)

        profile_frame = ttk.Frame(left_container)
        profile_frame.grid(row=0, column=0, sticky="nsew")
        ttk.Label(profile_frame, text="User Profiles").pack(anchor=tk.W)

        self.user_profile_listbox = tk.Listbox(profile_frame, height=8)
        self.user_profile_listbox.pack(fill=tk.BOTH, expand=True)
        self.user_profile_listbox.bind("<<ListboxSelect>>", self._on_user_profile_selected)

        profile_btn_frame = ttk.Frame(profile_frame)
        profile_btn_frame.pack(fill=tk.X, pady=(6, 12))
        self.btn_user_profile_new = ttk.Button(
            profile_btn_frame, text="New User Profile", command=self._create_user_profile
        )
        self.btn_user_profile_new.pack(fill=tk.X, pady=2)
        self.btn_user_profile_rename = ttk.Button(
            profile_btn_frame, text="Rename", command=self._rename_user_profile
        )
        self.btn_user_profile_rename.pack(fill=tk.X, pady=2)
        self.btn_user_profile_duplicate = ttk.Button(
            profile_btn_frame, text="Duplicate", command=self._duplicate_user_profile
        )
        self.btn_user_profile_duplicate.pack(fill=tk.X, pady=2)
        self.btn_user_profile_delete = ttk.Button(
            profile_btn_frame, text="Delete", command=self._delete_user_profile
        )
        self.btn_user_profile_delete.pack(fill=tk.X, pady=2)

        users_frame = ttk.Frame(left_container)
        users_frame.grid(row=1, column=0, sticky="nsew")
        ttk.Label(users_frame, text="Users").pack(anchor=tk.W)

        self.user_listbox = tk.Listbox(users_frame, height=10)
        self.user_listbox.pack(fill=tk.BOTH, expand=True)
        self.user_listbox.bind("<<ListboxSelect>>", self._on_user_selected)

        users_btn_frame = ttk.Frame(users_frame)
        users_btn_frame.pack(fill=tk.X, pady=(6, 0))
        self.users_btn_new = ttk.Button(users_btn_frame, text="New", command=self._new_user)
        self.users_btn_new.pack(side=tk.LEFT, padx=2)
        self.users_btn_duplicate = ttk.Button(
            users_btn_frame, text="Duplicate", command=self._duplicate_user
        )
        self.users_btn_duplicate.pack(side=tk.LEFT, padx=2)
        self.users_btn_delete = ttk.Button(
            users_btn_frame, text="Delete", command=self._delete_user
        )
        self.users_btn_delete.pack(side=tk.LEFT, padx=2)

        field_frame = ttk.Frame(frame)
        field_frame.grid(row=0, column=1, sticky="nsew", padx=(15, 0))
        field_frame.columnconfigure(1, weight=1)

        ttk.Label(
            field_frame,
            textvariable=self.user_profile_context_var,
            font=("Segoe UI", 11, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky=tk.W, pady=(0, 10))

        user_fields = (
            ("Username", "username"),
            ("Password", "password"),
            ("Full Name", "full_name"),
            ("Email", "email"),
        )

        self.user_entries = []
        for idx, (label, key) in enumerate(user_fields, start=1):
            ttk.Label(field_frame, text=label).grid(row=idx, column=0, sticky=tk.W, pady=2)
            entry = ttk.Entry(field_frame, textvariable=self.user_vars[key])
            entry.grid(row=idx, column=1, sticky="ew", pady=2)
            if key == "password":
                entry.configure(show="*")
            self.user_entries.append(entry)

        self.user_save_button = ttk.Button(field_frame, text="Save User", command=self._save_user)
        self.user_save_button.grid(row=len(user_fields) + 1, column=1, sticky=tk.E, pady=(12, 0))

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

        ttk.Label(select_frame, text="OPNsense Profile:").grid(row=0, column=0, sticky=tk.W)
        self.action_opnsense_combo = ttk.Combobox(
            select_frame, textvariable=self.actions_opnsense_var, state="readonly"
        )
        self.action_opnsense_combo.grid(row=0, column=1, sticky="ew")
        self.action_opnsense_combo.bind("<<ComboboxSelected>>", self._on_action_opnsense_selected)

        ttk.Label(select_frame, text="User Profile:").grid(row=1, column=0, sticky=tk.W, pady=(6, 0))
        self.action_user_profile_combo = ttk.Combobox(
            select_frame, textvariable=self.actions_user_profile_var, state="readonly"
        )
        self.action_user_profile_combo.grid(row=1, column=1, sticky="ew", pady=(6, 0))
        self.action_user_profile_combo.bind("<<ComboboxSelected>>", self._on_action_user_profile_selected)

        self.log_text = scrolledtext.ScrolledText(frame, height=24, state=tk.DISABLED)
        self.log_text.grid(row=2, column=0, sticky="nsew", padx=5, pady=(10, 0))
        frame.rowconfigure(2, weight=1)
    # ------------------------------------------------------------------
    # Manager event wiring
    # ------------------------------------------------------------------
    def _register_manager_callbacks(self) -> None:
        self.manager.register_listener("opnsense_profiles_changed", self._on_opnsense_profiles_changed)
        self.manager.register_listener("user_profiles_changed", self._on_user_profiles_changed)
        self.manager.register_listener("user_list_changed", self._on_user_list_changed)
        self.manager.register_listener("selection_changed", self._on_selection_changed)

    def _on_opnsense_profiles_changed(self) -> None:
        profiles = self.manager.list_opnsense_profiles()
        selected_id = self.manager.get_selected_opnsense_profile_id()
        if selected_id is None and profiles:
            selected_id = profiles[0].id
            self.manager.set_selected_opnsense_profile_id(selected_id)
        self.app_state.current_opnsense_profile_id = selected_id
        self._refresh_opnsense_profile_listbox()
        self._load_selected_opnsense_profile()
        self._refresh_action_opnsense_selector()
        self._update_profile_buttons_state()
        self._update_action_buttons_state()

    def _on_user_profiles_changed(self) -> None:
        profiles = self.manager.list_user_profiles()
        selected_id = self.manager.get_selected_user_profile_id()
        if selected_id is None and profiles:
            selected_id = profiles[0].id
            self.manager.set_selected_user_profile_id(selected_id)
        changed = self.app_state.set_current_user_profile_id(selected_id)
        if not changed:
            self._on_app_state_user_profile_changed(selected_id)

    def _on_user_list_changed(self) -> None:
        self._refresh_users_for_current_profile()
        self._update_user_controls_state()

    def _on_selection_changed(self) -> None:
        current_opnsense_id = self.manager.get_selected_opnsense_profile_id()
        if current_opnsense_id != self.app_state.current_opnsense_profile_id:
            self.app_state.current_opnsense_profile_id = current_opnsense_id
            self._refresh_opnsense_profile_listbox()
            self._load_selected_opnsense_profile()
            self._refresh_action_opnsense_selector()
            self._update_profile_buttons_state()

        current_user_profile_id = self.manager.get_selected_user_profile_id()
        if current_user_profile_id != self.app_state.current_user_profile_id:
            self.app_state.set_current_user_profile_id(current_user_profile_id)

        self._update_action_buttons_state()

    def _on_app_state_user_profile_changed(self, profile_id: Optional[str]) -> None:
        label = "User Profile: (none)"
        if profile_id:
            try:
                profile = self.manager.get_user_profile(profile_id)
            except ValueError:
                label = "User Profile: (missing)"
            else:
                label = f"User Profile: {profile.name}"
        self.user_profile_context_var.set(label)
        self._refresh_user_profile_listbox()
        self._refresh_users_for_current_profile()
        self._refresh_action_user_profile_selector()
        self._update_user_profile_buttons_state()
        self._update_user_controls_state()
        self._update_action_buttons_state()


    def _refresh_opnsense_profile_listbox(self) -> None:
        if not self.profile_listbox:
            return
        profiles = self.manager.list_opnsense_profiles()
        selected_id = self.app_state.current_opnsense_profile_id

        self._in_opnsense_refresh = True
        try:
            self.profile_listbox.delete(0, tk.END)
            selected_index: Optional[int] = None
            for idx, profile in enumerate(profiles):
                self.profile_listbox.insert(tk.END, profile.name)
                if profile.id == selected_id:
                    selected_index = idx
            if selected_index is not None:
                self.profile_listbox.selection_clear(0, tk.END)
                self.profile_listbox.selection_set(selected_index)
                self.profile_listbox.activate(selected_index)
                self.profile_listbox.see(selected_index)
            else:
                self.profile_listbox.selection_clear(0, tk.END)
        finally:
            self._in_opnsense_refresh = False
        self._update_profile_buttons_state()

    def _refresh_user_profile_listbox(self) -> None:
        if not self.user_profile_listbox:
            return
        profiles = self.manager.list_user_profiles()
        selected_id = self.app_state.current_user_profile_id

        self._in_user_profile_refresh = True
        try:
            self.user_profile_listbox.delete(0, tk.END)
            selected_index: Optional[int] = None
            for idx, profile in enumerate(profiles):
                self.user_profile_listbox.insert(tk.END, profile.name)
                if profile.id == selected_id:
                    selected_index = idx
            if selected_index is not None:
                self.user_profile_listbox.selection_clear(0, tk.END)
                self.user_profile_listbox.selection_set(selected_index)
                self.user_profile_listbox.activate(selected_index)
                self.user_profile_listbox.see(selected_index)
            else:
                self.user_profile_listbox.selection_clear(0, tk.END)
        finally:
            self._in_user_profile_refresh = False
        self._update_user_profile_buttons_state()

    # ------------------------------------------------------------------
    # Profile helpers
    # ------------------------------------------------------------------

    def _create_profile(self) -> None:
        name = simpledialog.askstring("New OPNsense Profile", "Profile name:", parent=self)
        if name is None:
            return
        try:
            profile = self.manager.create_opnsense_profile(name)
        except ValueError as exc:
            messagebox.showerror("Cannot create profile", str(exc))
            return
        self.manager.set_selected_opnsense_profile_id(profile.id)
        self.app_state.current_opnsense_profile_id = profile.id
        self._persist_and_export(profile_id=profile.id, user_profile_id=self.app_state.current_user_profile_id)
        self._set_status(f"OPNsense profile '{profile.name}' created.")

    def _rename_profile(self) -> None:
        profile = self._get_selected_opnsense_profile()
        if not profile:
            return
        new_name = simpledialog.askstring(
            "Rename OPNsense Profile",
            "New profile name:",
            initialvalue=profile.name,
            parent=self,
        )
        if new_name is None:
            return
        try:
            self.manager.rename_opnsense_profile(profile.id, new_name)
        except ValueError as exc:
            messagebox.showerror("Cannot rename profile", str(exc))
            return
        self._persist_and_export(profile_id=profile.id, user_profile_id=self.app_state.current_user_profile_id)
        self._set_status(f"OPNsense profile renamed to '{new_name}'.")

    def _duplicate_profile(self) -> None:
        profile = self._get_selected_opnsense_profile()
        if not profile:
            return
        try:
            clone = self.manager.duplicate_opnsense_profile(profile.id)
        except ValueError as exc:
            messagebox.showerror("Cannot duplicate profile", str(exc))
            return
        self.app_state.current_opnsense_profile_id = clone.id
        self._persist_and_export(profile_id=clone.id, user_profile_id=self.app_state.current_user_profile_id)
        self._set_status(f"OPNsense profile '{clone.name}' duplicated.")

    def _delete_profile(self) -> None:
        profile = self._get_selected_opnsense_profile()
        if not profile:
            return
        if not messagebox.askyesno(
            "Delete OPNsense Profile",
            f"Delete profile '{profile.name}'? This cannot be undone.",
            parent=self,
        ):
            return
        try:
            self.manager.delete_opnsense_profile(profile.id)
        except ValueError as exc:
            messagebox.showerror("Cannot delete profile", str(exc))
            return
        new_profile = self.manager.get_selected_opnsense_profile()
        self.app_state.current_opnsense_profile_id = new_profile.id if new_profile else None
        self._persist_and_export(
            profile_id=new_profile.id if new_profile else None,
            user_profile_id=self.app_state.current_user_profile_id,
        )
        self._set_status(f"OPNsense profile '{profile.name}' deleted.")

    def _on_opnsense_profile_selected(self, event) -> None:
        if self._in_opnsense_refresh or not self.profile_listbox:
            return
        selection = self.profile_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        profiles = self.manager.list_opnsense_profiles()
        if index >= len(profiles):
            return
        profile = profiles[index]
        self.app_state.current_opnsense_profile_id = profile.id
        self.manager.set_selected_opnsense_profile_id(profile.id)

    def _update_profile_buttons_state(self) -> None:
        profiles = self.manager.list_opnsense_profiles()
        selected_id = self.app_state.current_opnsense_profile_id
        selection_exists = selected_id is not None
        multiple_profiles = len(profiles) > 1

        if self.btn_profile_rename:
            self.btn_profile_rename.configure(state=tk.NORMAL if selection_exists else tk.DISABLED)
        if self.btn_profile_duplicate:
            self.btn_profile_duplicate.configure(state=tk.NORMAL if selection_exists else tk.DISABLED)
        if self.btn_profile_delete:
            state = tk.NORMAL if selection_exists and multiple_profiles else tk.DISABLED
            self.btn_profile_delete.configure(state=state)


    def _update_user_profile_buttons_state(self) -> None:
        profiles = self.manager.list_user_profiles()
        selected_id = self.app_state.current_user_profile_id
        selection_exists = selected_id is not None
        multiple_profiles = len(profiles) > 1

        if self.btn_user_profile_rename:
            self.btn_user_profile_rename.configure(state=tk.NORMAL if selection_exists else tk.DISABLED)
        if self.btn_user_profile_duplicate:
            self.btn_user_profile_duplicate.configure(state=tk.NORMAL if selection_exists else tk.DISABLED)
        if self.btn_user_profile_delete:
            state = tk.NORMAL if selection_exists and multiple_profiles else tk.DISABLED
            self.btn_user_profile_delete.configure(state=state)

    def _get_selected_user_profile(self) -> Optional[UserProfile]:
        selected_id = self.app_state.current_user_profile_id
        if not selected_id:
            return None
        try:
            return self.manager.get_user_profile(selected_id)
        except ValueError:
            return None

    def _create_user_profile(self) -> None:
        name = simpledialog.askstring("New User Profile", "User profile name:", parent=self)
        if name is None:
            return
        try:
            profile = self.manager.create_user_profile(name)
        except ValueError as exc:
            messagebox.showerror("Cannot create user profile", str(exc))
            return
        self.manager.set_selected_user_profile_id(profile.id)
        self.app_state.set_current_user_profile_id(profile.id)
        self._persist_and_export(
            profile_id=self.app_state.current_opnsense_profile_id, user_profile_id=profile.id
        )
        self._set_status(f"User profile '{profile.name}' created.")

    def _rename_user_profile(self) -> None:
        profile = self._get_selected_user_profile()
        if not profile:
            return
        new_name = simpledialog.askstring(
            "Rename User Profile",
            "New user profile name:",
            initialvalue=profile.name,
            parent=self,
        )
        if new_name is None:
            return
        try:
            self.manager.rename_user_profile(profile.id, new_name)
        except ValueError as exc:
            messagebox.showerror("Cannot rename user profile", str(exc))
            return
        self._persist_and_export(
            profile_id=self.app_state.current_opnsense_profile_id, user_profile_id=profile.id
        )
        self._set_status(f"User profile renamed to '{new_name}'.")

    def _duplicate_user_profile(self) -> None:
        profile = self._get_selected_user_profile()
        if not profile:
            return
        try:
            clone = self.manager.duplicate_user_profile(profile.id)
        except ValueError as exc:
            messagebox.showerror("Cannot duplicate user profile", str(exc))
            return
        self.app_state.set_current_user_profile_id(clone.id)
        self._persist_and_export(
            profile_id=self.app_state.current_opnsense_profile_id, user_profile_id=clone.id
        )
        self._set_status(f"User profile '{clone.name}' duplicated.")

    def _delete_user_profile(self) -> None:
        profile = self._get_selected_user_profile()
        if not profile:
            return
        if not messagebox.askyesno(
            "Delete User Profile",
            f"Delete user profile '{profile.name}'? This cannot be undone.",
            parent=self,
        ):
            return
        try:
            self.manager.delete_user_profile(profile.id)
        except ValueError as exc:
            messagebox.showerror("Cannot delete user profile", str(exc))
            return
        new_profile = self.manager.get_selected_user_profile()
        self.app_state.set_current_user_profile_id(new_profile.id if new_profile else None)
        self._persist_and_export(
            profile_id=self.app_state.current_opnsense_profile_id,
            user_profile_id=new_profile.id if new_profile else None,
        )
        self._set_status(f"User profile '{profile.name}' deleted.")

    def _on_user_profile_selected(self, event) -> None:
        if self._in_user_profile_refresh or not self.user_profile_listbox:
            return
        selection = self.user_profile_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        profiles = self.manager.list_user_profiles()
        if index >= len(profiles):
            return
        profile = profiles[index]
        self.app_state.set_current_user_profile_id(profile.id)
        self.manager.set_selected_user_profile_id(profile.id)

    def _get_selected_opnsense_profile(self) -> Optional[OPNsenseProfile]:
        selected_id = self.app_state.current_opnsense_profile_id
        if not selected_id:
            return None
        try:
            return self.manager.get_opnsense_profile(selected_id)
        except ValueError:
            return None

    def _load_selected_opnsense_profile(self) -> None:
        profile = self._get_selected_opnsense_profile()
        if not profile:
            self.profile_name_var.set("No OPNsense profile selected")
            for var in self.connection_vars.values():
                var.set("")
            self._clear_settings_form()
            self._set_profile_form_state(False)
            return

        self.profile_name_var.set(profile.name)
        connection = profile.settings.get("connection", {})
        for key, var in self.connection_vars.items():
            var.set(connection.get(key, DEFAULT_CONNECTION.get(key, "")))
        self._load_settings_into_vars(profile.settings.get("automation", {}))
        self._set_profile_form_state(True)

    def _set_profile_form_state(self, enabled: bool) -> None:
        state = tk.NORMAL if enabled else tk.DISABLED
        for entry in self.connection_entries + self.settings_entries:
            entry.configure(state=state)

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
        profile = self._get_selected_opnsense_profile()
        if not profile:
            messagebox.showerror("No profile", "Select a profile first.")
            return
        try:
            automation = self._collect_settings_from_vars()
        except ValueError as exc:
            messagebox.showerror("Invalid data", str(exc))
            return
        self.manager.update_opnsense_settings(profile.id, automation)
        self._persist_and_export(profile_id=profile.id, user_profile_id=self.app_state.current_user_profile_id)
        self._set_status("Settings saved.")

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------
    def _save_connection(self) -> None:
        profile = self._get_selected_opnsense_profile()
        if not profile:
            messagebox.showerror("No profile", "Select a profile first.")
            return
        payload = {key: var.get().strip() for key, var in self.connection_vars.items()}
        self.manager.update_opnsense_connection(profile.id, payload)
        self._persist_and_export(profile_id=profile.id, user_profile_id=self.app_state.current_user_profile_id)
        self._set_status("Connection details saved.")

    # ------------------------------------------------------------------
    # User helpers
    # ------------------------------------------------------------------
    def _refresh_users_for_current_profile(self) -> None:
        user_profile = self._get_selected_user_profile()
        if not user_profile:
            self._refresh_user_listbox([])
            self._clear_user_form()
            self.current_user_username = None
            self._last_loaded_user = None
            self._update_user_controls_state()
            return

        users = user_profile.users
        self._refresh_user_listbox(users)
        if self.current_user_username:
            for user in users:
                if user.username.lower() == self.current_user_username.lower():
                    self._select_user_in_list(user.username)
                    break
            else:
                self.current_user_username = None
        if self.current_user_username is None and users:
            self._select_user_in_list(users[0].username)
        elif not users:
            self._clear_user_form()
            self.current_user_username = None
            self._last_loaded_user = None
        self._update_user_controls_state()

    def _refresh_user_listbox(self, users: List[User]) -> None:
        if not self.user_listbox:
            return
        self._in_user_refresh = True
        try:
            self.user_listbox.delete(0, tk.END)
            for user in users:
                self.user_listbox.insert(tk.END, user.username)
            if users:
                self.user_listbox.configure(state=tk.NORMAL)
            else:
                self.user_listbox.configure(state=tk.DISABLED)
                self.user_listbox.selection_clear(0, tk.END)
        finally:
            self._in_user_refresh = False

    def _update_user_controls_state(self) -> None:
        user_profile = self._get_selected_user_profile()
        has_profile = user_profile is not None
        has_selection = has_profile and self.current_user_username is not None

        if self.users_btn_new:
            self.users_btn_new.configure(state=tk.NORMAL if has_profile else tk.DISABLED)
        if self.users_btn_duplicate:
            self.users_btn_duplicate.configure(state=tk.NORMAL if has_selection else tk.DISABLED)
        if self.users_btn_delete:
            self.users_btn_delete.configure(state=tk.NORMAL if has_selection else tk.DISABLED)
        for entry in self.user_entries:
            entry.configure(state=tk.NORMAL if has_profile else tk.DISABLED)
        if self.user_save_button:
            self.user_save_button.configure(state=tk.NORMAL if has_profile else tk.DISABLED)

    def _clear_user_form(self) -> None:
        for var in self.user_vars.values():
            var.set("")

    def _populate_user_form(self, user: User) -> None:
        self.user_vars["username"].set(user.username)
        self.user_vars["password"].set(user.password)
        self.user_vars["full_name"].set(user.full_name)
        self.user_vars["email"].set(user.email)

    def _new_user(self, focus_username: bool = True) -> None:
        user_profile = self._get_selected_user_profile()
        if not user_profile:
            return
        template = deepcopy(DEFAULT_USER_TEMPLATE)
        taken = {user.username for user in user_profile.users}
        candidate = make_unique_username(template["username"], {name.lower() for name in taken})
        self.user_vars["username"].set(candidate)
        self.user_vars["password"].set(template["password"])
        self.user_vars["full_name"].set(template["full_name"])
        self.user_vars["email"].set(template["email"])

        if self.user_listbox:
            self._in_user_refresh = True
            try:
                self.user_listbox.selection_clear(0, tk.END)
            finally:
                self._in_user_refresh = False
        if focus_username and self.user_entries:
            self.user_entries[0].focus_set()
        self.current_user_username = None
        self._last_loaded_user = None
        self._update_user_controls_state()

    def _duplicate_user(self) -> None:
        user_profile = self._get_selected_user_profile()
        if not user_profile or not self.current_user_username:
            return
        try:
            clone = self.manager.duplicate_user(user_profile.id, self.current_user_username)
        except ValueError as exc:
            messagebox.showerror("Cannot duplicate user", str(exc))
            return
        self.current_user_username = clone.username
        self._persist_and_export(
            profile_id=self.app_state.current_opnsense_profile_id,
            user_profile_id=user_profile.id,
            username=clone.username,
        )
        self._set_status(f"User '{clone.username}' duplicated.")
        self._refresh_users_for_current_profile()
        self._select_user_in_list(clone.username)

    def _on_user_selected(self, event) -> None:
        if self._in_user_refresh or not self.user_listbox:
            return
        user_profile = self._get_selected_user_profile()
        if not user_profile:
            return
        selection = self.user_listbox.curselection()
        if not selection:
            return
        index = selection[0]
        if index >= len(user_profile.users):
            return
        self._select_user_in_list(user_profile.users[index].username)

    def _select_user_in_list(self, username: str) -> None:
        user_profile = self._get_selected_user_profile()
        if not user_profile or not self.user_listbox:
            return
        for idx, user in enumerate(user_profile.users):
            if user.username.lower() == username.lower():
                self._in_user_refresh = True
                try:
                    self.user_listbox.selection_clear(0, tk.END)
                    self.user_listbox.selection_set(idx)
                    self.user_listbox.activate(idx)
                    self.user_listbox.see(idx)
                finally:
                    self._in_user_refresh = False
                self.current_user_username = user.username
                self._last_loaded_user = deepcopy(user)
                self._populate_user_form(user)
                self._update_user_controls_state()
                return
        self.current_user_username = None
        self._last_loaded_user = None
        self._update_user_controls_state()

    def _save_user(self) -> None:
        user_profile = self._get_selected_user_profile()
        if not user_profile:
            messagebox.showerror("No user profile", "Select a user profile first.")
            return
        username = self.user_vars["username"].get().strip()
        if not username:
            messagebox.showerror("Invalid user", "Username cannot be empty.")
            return
        user = User(
            username=username,
            password=self.user_vars["password"].get(),
            full_name=self.user_vars["full_name"].get(),
            email=self.user_vars["email"].get(),
        )
        try:
            if self.current_user_username is None:
                self.manager.add_user(user_profile.id, user)
            else:
                user.original_username = self.current_user_username
                self.manager.update_user(user_profile.id, user)
        except ValueError as exc:
            messagebox.showerror("Cannot save user", str(exc))
            return
        self.current_user_username = user.username
        self._last_loaded_user = deepcopy(user)
        self._persist_and_export(
            profile_id=self.app_state.current_opnsense_profile_id,
            user_profile_id=user_profile.id,
            username=user.username,
        )
        self._set_status(f"User '{user.username}' saved.")
        self._refresh_users_for_current_profile()
        self._select_user_in_list(user.username)

    def _delete_user(self) -> None:
        user_profile = self._get_selected_user_profile()
        if not user_profile or not self.current_user_username:
            messagebox.showinfo("Delete User", "Select a user first.")
            return
        username = self.current_user_username
        if not messagebox.askyesno("Delete User", f"Delete user '{username}'?", parent=self):
            return
        try:
            self.manager.delete_user(user_profile.id, username)
        except ValueError as exc:
            messagebox.showerror("Cannot delete user", str(exc))
            return
        self.current_user_username = None
        self._last_loaded_user = None
        self._persist_and_export(
            profile_id=self.app_state.current_opnsense_profile_id,
            user_profile_id=user_profile.id,
        )
        self._set_status(f"User '{username}' deleted.")
        self._refresh_users_for_current_profile()

    # ------------------------------------------------------------------
    # Actions tab helpers
    # ------------------------------------------------------------------
    def _refresh_action_opnsense_selector(self) -> None:
        if not self.action_opnsense_combo:
            return
        profiles = self.manager.list_opnsense_profiles()
        labels = [profile.name for profile in profiles]
        self._action_opnsense_ids = [profile.id for profile in profiles]

        selected_id = self._actions_opnsense_profile_id
        if selected_id not in self._action_opnsense_ids:
            selected_id = self.app_state.current_opnsense_profile_id or (
                self._action_opnsense_ids[0] if self._action_opnsense_ids else None
            )
            self._actions_opnsense_profile_id = selected_id

        self._in_action_refresh = True
        try:
            self.action_opnsense_combo["values"] = labels
            if not self._action_opnsense_ids:
                self.actions_opnsense_var.set("")
                self.action_opnsense_combo.set("")
                self.action_opnsense_combo.configure(state="disabled")
            else:
                index = (
                    self._action_opnsense_ids.index(selected_id)
                    if selected_id in self._action_opnsense_ids
                    else 0
                )
                self.action_opnsense_combo.configure(state="readonly")
                self.action_opnsense_combo.current(index)
                self.actions_opnsense_var.set(labels[index])
        finally:
            self._in_action_refresh = False
        self._update_action_buttons_state()

    def _refresh_action_user_profile_selector(self) -> None:
        if not self.action_user_profile_combo:
            return
        profiles = self.manager.list_user_profiles()
        labels = [profile.name for profile in profiles]
        self._action_user_profile_ids = [profile.id for profile in profiles]

        selected_id = self._actions_user_profile_id
        if selected_id not in self._action_user_profile_ids:
            selected_id = self.app_state.current_user_profile_id or (
                self._action_user_profile_ids[0] if self._action_user_profile_ids else None
            )
            self._actions_user_profile_id = selected_id

        self._in_action_refresh = True
        try:
            self.action_user_profile_combo["values"] = labels
            if not self._action_user_profile_ids:
                self.actions_user_profile_var.set("")
                self.action_user_profile_combo.set("")
                self.action_user_profile_combo.configure(state="disabled")
            else:
                index = (
                    self._action_user_profile_ids.index(selected_id)
                    if selected_id in self._action_user_profile_ids
                    else 0
                )
                self.action_user_profile_combo.configure(state="readonly")
                self.action_user_profile_combo.current(index)
                self.actions_user_profile_var.set(labels[index])
        finally:
            self._in_action_refresh = False
        self._update_action_buttons_state()

    def _on_action_opnsense_selected(self, event) -> None:
        if self._in_action_refresh or not self.action_opnsense_combo:
            return
        selection = self.action_opnsense_combo.current()
        if selection < 0 or selection >= len(self._action_opnsense_ids):
            return
        self._actions_opnsense_profile_id = self._action_opnsense_ids[selection]
        self._update_action_buttons_state()

    def _on_action_user_profile_selected(self, event) -> None:
        if self._in_action_refresh or not self.action_user_profile_combo:
            return
        selection = self.action_user_profile_combo.current()
        if selection < 0 or selection >= len(self._action_user_profile_ids):
            return
        self._actions_user_profile_id = self._action_user_profile_ids[selection]
        self._update_action_buttons_state()

    def _update_action_buttons_state(self) -> None:
        has_opnsense = self._actions_opnsense_profile_id is not None
        has_user_profile = self._actions_user_profile_id is not None

        if self.action_opnsense_combo:
            state = "readonly" if self._action_opnsense_ids else "disabled"
            self.action_opnsense_combo.configure(state=state)
        if self.action_user_profile_combo:
            state = "readonly" if self._action_user_profile_ids else "disabled"
            self.action_user_profile_combo.configure(state=state)
        if self.full_setup_button:
            self.full_setup_button.configure(
                state=tk.NORMAL if has_opnsense and has_user_profile else tk.DISABLED
            )
        if self.build_button:
            self.build_button.configure(
                state=tk.NORMAL if has_opnsense and has_user_profile else tk.DISABLED
            )

    def _run_full_setup(self) -> None:
        self._run_script("Run-Full-Setup.ps1", "Full Setup", require_users=False)

    def _run_build_ovpn(self) -> None:
        self._run_script("Build-Ovpn-Files.ps1", "Build OVPN", require_users=True)

    def _run_script(self, script_name: str, friendly_name: str, require_users: bool) -> None:
        if not self._commit_profile_changes():
            return

        opnsense_id = self._actions_opnsense_profile_id
        user_profile_id = self._actions_user_profile_id
        if not opnsense_id or not user_profile_id:
            messagebox.showerror("Missing selection", "Select both profiles first.")
            return
        try:
            opnsense_profile = self.manager.get_opnsense_profile(opnsense_id)
        except ValueError:
            messagebox.showerror("Profile error", "Selected OPNsense profile not found.")
            self._refresh_action_opnsense_selector()
            return
        try:
            user_profile = self.manager.get_user_profile(user_profile_id)
        except ValueError:
            messagebox.showerror("Profile error", "Selected user profile not found.")
            self._refresh_action_user_profile_selector()
            return

        if require_users and not user_profile.users:
            self._append_log("\n>>> No users in selected User Profile.\n")
            return

        try:
            self._persist_and_export(
                profile_id=opnsense_id,
                user_profile_id=user_profile_id,
                suppress_errors=False,
            )
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

        profiles = self.manager.list_opnsense_profiles()
        try:
            profile_index = next(idx for idx, item in enumerate(profiles) if item.id == opnsense_id)
        except StopIteration:
            messagebox.showerror("Profile error", "Selected OPNsense profile not found.")
            return

        display_name = opnsense_profile.name or f"Profile {profile_index + 1}"
        user_info = f" (user profile: {user_profile.name} / {len(user_profile.users)} users)"
        self._append_log(
            f"\n>>> Starting {friendly_name} for {display_name}{user_info}\n"
        )
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

    def _commit_profile_changes(self) -> bool:
        profile = self._get_selected_opnsense_profile()
        if not profile:
            messagebox.showerror("No profile", "Select a profile first.")
            return False
        payload = {key: var.get().strip() for key, var in self.connection_vars.items()}
        self.manager.update_opnsense_connection(profile.id, payload)
        try:
            automation = self._collect_settings_from_vars()
        except ValueError as exc:
            messagebox.showerror("Invalid data", str(exc))
            return False
        self.manager.update_opnsense_settings(profile.id, automation)
        return True
    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------
    def _persist_and_export(
        self,
        profile_id: Optional[str] = None,
        user_profile_id: Optional[str] = None,
        username: Optional[str] = None,
        suppress_errors: bool = True,
    ) -> None:
        self.manager.save()
        try:
            self.manager.export_legacy_files(
                opnsense_profile_id=profile_id,
                user_profile_id=user_profile_id,
                username=username,
            )
        except ValueError:
            if not suppress_errors:
                raise

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------
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




