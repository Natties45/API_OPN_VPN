from __future__ import annotations

import json
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

BASE_DIR = Path(__file__).resolve().parent

# Primary config file for the GUI.
CONFIG_DATA_PATH = BASE_DIR / "config.gui.json"

# Legacy files that the PowerShell scripts expect.
LEGACY_PROFILE_PATH = BASE_DIR / "config.profiles.json"
LEGACY_SETTINGS_PATH = BASE_DIR / "config.settings.json"
LEGACY_USERS_PATH = BASE_DIR / "config.users.json"

DEFAULT_PROFILE_NAME = "Default"

# Connection (API/SSH) defaults for a new profile.
DEFAULT_CONNECTION = {
    "ApiBaseUrl": "https://firewall.example.com:4443",
    "ApiKey": "",
    "ApiSecret": "",
    "SshHost": "firewall.example.com",
    "SshUser": "root",
    "SshPass": "",
}

# Automation settings that were previously global.
DEFAULT_AUTOMATION = {
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

# Template for a brand-new user.
DEFAULT_USER_TEMPLATE = {
    "username": "user1",
    "password": "changeme",
    "full_name": "New VPN User",
    "email": "user@example.com",
}


def _new_connection_defaults() -> Dict[str, str]:
    return deepcopy(DEFAULT_CONNECTION)


def _new_automation_defaults() -> Dict[str, object]:
    return deepcopy(DEFAULT_AUTOMATION)


def _ensure_directory(path: Path) -> None:
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class User:
    username: str
    password: str
    full_name: str
    email: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "username": self.username,
            "password": self.password,
            "full_name": self.full_name,
            "email": self.email,
        }

    def to_legacy_dict(self) -> Dict[str, str]:
        return {
            "Name": self.username,
            "Password": self.password,
            "Full": self.full_name,
            "Email": self.email,
        }

    @staticmethod
    def from_dict(payload: Dict[str, str]) -> "User":
        if not payload:
            payload = {}
        return User(
            username=str(payload.get("username", payload.get("Name", ""))),
            password=str(payload.get("password", payload.get("Password", ""))),
            full_name=str(payload.get("full_name", payload.get("Full", ""))),
            email=str(payload.get("email", payload.get("Email", ""))),
        )


@dataclass
class Profile:
    id: str
    name: str
    settings: Dict[str, object]
    users: List[User] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "settings": deepcopy(self.settings),
            "users": [user.to_dict() for user in self.users],
        }

    @staticmethod
    def from_dict(payload: Dict[str, object]) -> "Profile":
        profile_id = str(payload.get("id") or uuid.uuid4().hex)
        name = payload.get("name") or DEFAULT_PROFILE_NAME
        settings = deepcopy(payload.get("settings") or {})

        if "connection" not in settings:
            settings["connection"] = _new_connection_defaults()
        else:
            # Ensure every key is present even when loading older configs.
            conn = settings["connection"]
            for key, value in DEFAULT_CONNECTION.items():
                conn.setdefault(key, value)

        if "automation" not in settings:
            settings["automation"] = _new_automation_defaults()
        else:
            automation = settings["automation"]
            # Fill any missing nested dictionaries with defaults.
            def _fill(target: Dict[str, object], defaults: Dict[str, object]) -> None:
                for key, value in defaults.items():
                    if key not in target:
                        target[key] = deepcopy(value)
                    elif isinstance(value, dict) and isinstance(target[key], dict):
                        _fill(target[key], value)

            if isinstance(automation, dict):
                _fill(automation, DEFAULT_AUTOMATION)
            else:
                settings["automation"] = _new_automation_defaults()

        users_payload = payload.get("users") or []
        users = [User.from_dict(item) for item in users_payload]

        return Profile(id=profile_id, name=str(name), settings=settings, users=users)


class ConfigManager:
    def __init__(self, path: Path = CONFIG_DATA_PATH) -> None:
        self.path = path
        self.active_profile_id: Optional[str] = None
        self._profiles: List[Profile] = []

    # ------------------------------------------------------------------
    # Loading / saving
    # ------------------------------------------------------------------
    @classmethod
    def load(cls, path: Path = CONFIG_DATA_PATH) -> "ConfigManager":
        manager = cls(path)
        manager._load()
        return manager

    def save(self) -> None:
        data = {
            "active_profile_id": self.active_profile_id,
            "profiles": [profile.to_dict() for profile in self._profiles],
        }
        _ensure_directory(self.path)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")

    # ------------------------------------------------------------------
    # Public getters
    # ------------------------------------------------------------------
    def list_profiles(self) -> List[Profile]:
        return list(self._profiles)

    def get_profile(self, profile_id: str) -> Profile:
        for profile in self._profiles:
            if profile.id == profile_id:
                return profile
        raise ValueError(f"Profile '{profile_id}' was not found.")

    def get_active_profile(self) -> Profile:
        if not self._profiles:
            raise ValueError("No profiles are available.")
        if self.active_profile_id:
            try:
                return self.get_profile(self.active_profile_id)
            except ValueError:
                pass
        return self._profiles[0]

    # ------------------------------------------------------------------
    # Profile CRUD
    # ------------------------------------------------------------------
    def create_profile(self, name: str) -> Profile:
        clean_name = name.strip() or DEFAULT_PROFILE_NAME
        self._ensure_unique_profile_name(clean_name)
        profile_id = uuid.uuid4().hex
        profile = Profile(
            id=profile_id,
            name=clean_name,
            settings={
                "connection": _new_connection_defaults(),
                "automation": _new_automation_defaults(),
            },
            users=[],
        )
        self._profiles.append(profile)
        if not self.active_profile_id:
            self.active_profile_id = profile_id
        return profile

    def rename_profile(self, profile_id: str, new_name: str) -> None:
        profile = self.get_profile(profile_id)
        clean_name = new_name.strip()
        if not clean_name:
            raise ValueError("Profile name cannot be empty.")
        self._ensure_unique_profile_name(clean_name, exclude_id=profile_id)
        profile.name = clean_name

    def delete_profile(self, profile_id: str) -> None:
        if len(self._profiles) <= 1:
            raise ValueError("Cannot delete the last profile.")
        profile = self.get_profile(profile_id)
        self._profiles.remove(profile)
        if self.active_profile_id == profile_id:
            self.active_profile_id = self._profiles[0].id

    def set_active_profile(self, profile_id: str) -> None:
        self.get_profile(profile_id)  # Ensure it exists.
        self.active_profile_id = profile_id

    def update_profile_connection(self, profile_id: str, connection: Dict[str, str]) -> None:
        profile = self.get_profile(profile_id)
        conn = profile.settings.setdefault("connection", {})
        for key, default_value in DEFAULT_CONNECTION.items():
            conn[key] = connection.get(key, default_value).strip()

    def update_profile_settings(self, profile_id: str, automation: Dict[str, object]) -> None:
        profile = self.get_profile(profile_id)
        profile.settings["automation"] = deepcopy(automation)

    # ------------------------------------------------------------------
    # User management
    # ------------------------------------------------------------------
    def add_user(self, profile_id: str, user: User) -> None:
        profile = self.get_profile(profile_id)
        self._ensure_unique_username(profile, user.username)
        profile.users.append(user)

    def update_user(self, profile_id: str, user: User) -> None:
        profile = self.get_profile(profile_id)
        for idx, existing in enumerate(profile.users):
            if existing.username.lower() == user.username.lower():
                profile.users[idx] = user
                return
        raise ValueError(f"User '{user.username}' was not found in profile '{profile.name}'.")

    def delete_user(self, profile_id: str, username: str) -> None:
        profile = self.get_profile(profile_id)
        for idx, existing in enumerate(profile.users):
            if existing.username.lower() == username.lower():
                del profile.users[idx]
                return
        raise ValueError(f"User '{username}' was not found in profile '{profile.name}'.")

    # ------------------------------------------------------------------
    # Legacy export helpers
    # ------------------------------------------------------------------
    def export_legacy_files(self, profile_id: Optional[str] = None) -> None:
        if not self._profiles:
            raise ValueError("No profiles are available to export.")
        target_profile = self.get_profile(profile_id) if profile_id else self.get_active_profile()

        # config.profiles.json
        legacy_profiles = []
        for profile in self._profiles:
            conn = deepcopy(profile.settings.get("connection", {}))
            legacy_profile = {
                "ProfileName": profile.name,
            }
            legacy_profile.update(conn)
            legacy_profiles.append(legacy_profile)

        _ensure_directory(LEGACY_PROFILE_PATH)
        with LEGACY_PROFILE_PATH.open("w", encoding="utf-8") as handle:
            json.dump({"profiles": legacy_profiles}, handle, indent=2, ensure_ascii=False)
            handle.write("\n")

        # config.settings.json
        automation = deepcopy(target_profile.settings.get("automation", {}))
        _ensure_directory(LEGACY_SETTINGS_PATH)
        with LEGACY_SETTINGS_PATH.open("w", encoding="utf-8") as handle:
            json.dump(automation, handle, indent=2, ensure_ascii=False)
            handle.write("\n")

        # config.users.json
        legacy_users = [user.to_legacy_dict() for user in target_profile.users]
        _ensure_directory(LEGACY_USERS_PATH)
        with LEGACY_USERS_PATH.open("w", encoding="utf-8") as handle:
            json.dump({"users": legacy_users}, handle, indent=2, ensure_ascii=False)
            handle.write("\n")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _load(self) -> None:
        if self.path.exists():
            data = self._read_json(self.path)
            if "profiles" not in data and "settings" in data and "users" in data:
                data = self._migrate_single_profile_payload(data)
                self._write_migrated(data)
            self._load_from_payload(data)
            return

        # Attempt to migrate from the legacy split files.
        legacy_payload = self._load_from_split_files()
        self._load_from_payload(legacy_payload)
        self._write_migrated(legacy_payload)

    def _load_from_payload(self, payload: Dict[str, object]) -> None:
        profiles_payload = payload.get("profiles") or []
        self._profiles = [Profile.from_dict(item) for item in profiles_payload]

        if not self._profiles:
            default_profile = Profile(
                id=uuid.uuid4().hex,
                name=DEFAULT_PROFILE_NAME,
                settings={
                    "connection": _new_connection_defaults(),
                    "automation": _new_automation_defaults(),
                },
                users=[],
            )
            self._profiles = [default_profile]

        active_id = payload.get("active_profile_id")
        if not active_id or active_id not in {p.id for p in self._profiles}:
            active_id = self._profiles[0].id
        self.active_profile_id = active_id

    def _load_from_split_files(self) -> Dict[str, object]:
        profiles_payload = []
        if LEGACY_PROFILE_PATH.exists():
            data = self._read_json(LEGACY_PROFILE_PATH)
            profiles_payload = data.get("profiles") or []

        settings_payload = _new_automation_defaults()
        if LEGACY_SETTINGS_PATH.exists():
            try:
                data = self._read_json(LEGACY_SETTINGS_PATH)
                if isinstance(data, dict):
                    settings_payload = deepcopy(data)
            except json.JSONDecodeError:
                pass

        users_payload: Iterable[Dict[str, str]] = []
        if LEGACY_USERS_PATH.exists():
            data = self._read_json(LEGACY_USERS_PATH)
            users_payload = data.get("users") or []

        if not profiles_payload:
            profiles_payload = [
                {
                    "ProfileName": DEFAULT_PROFILE_NAME,
                    **_new_connection_defaults(),
                }
            ]

        migrated_profiles = []
        for item in profiles_payload:
            connection = {key: item.get(key, DEFAULT_CONNECTION[key]) for key in DEFAULT_CONNECTION}
            profile_name = item.get("ProfileName") or DEFAULT_PROFILE_NAME
            migrated_profiles.append(
                {
                    "id": uuid.uuid4().hex,
                    "name": profile_name,
                    "settings": {
                        "connection": connection,
                        "automation": deepcopy(settings_payload),
                    },
                    "users": list(users_payload),
                }
            )

        return {
            "active_profile_id": migrated_profiles[0]["id"],
            "profiles": migrated_profiles,
        }

    def _migrate_single_profile_payload(self, payload: Dict[str, object]) -> Dict[str, object]:
        automation = deepcopy(payload.get("settings") or {})
        users = payload.get("users") or []
        profile_id = payload.get("id") or uuid.uuid4().hex
        name = payload.get("name") or DEFAULT_PROFILE_NAME
        return {
            "active_profile_id": profile_id,
            "profiles": [
                {
                    "id": profile_id,
                    "name": name,
                    "settings": {
                        "connection": _new_connection_defaults(),
                        "automation": automation or _new_automation_defaults(),
                    },
                    "users": users,
                }
            ],
        }

    def _write_migrated(self, payload: Dict[str, object]) -> None:
        _ensure_directory(self.path)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
            handle.write("\n")

    @staticmethod
    def _read_json(path: Path) -> Dict[str, object]:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _ensure_unique_profile_name(self, name: str, exclude_id: Optional[str] = None) -> None:
        for profile in self._profiles:
            if exclude_id and profile.id == exclude_id:
                continue
            if profile.name.lower() == name.lower():
                raise ValueError(f"A profile named '{name}' already exists.")

    @staticmethod
    def _ensure_unique_username(profile: Profile, username: str) -> None:
        for user in profile.users:
            if user.username.lower() == username.lower():
                raise ValueError(f"User '{username}' already exists in profile '{profile.name}'.")
