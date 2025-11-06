from __future__ import annotations

import json
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Set

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


def _format_copy_name(base: str, fmt: str, suffix_index: int) -> str:
    if suffix_index <= 1:
        if "{}" in fmt:
            return f"{base}{fmt.format('')}"
        return f"{base}{fmt}"
    if "{}" in fmt:
        return f"{base}{fmt.format(suffix_index)}"
    if fmt.endswith(")"):
        return f"{base}{fmt[:-1]} {suffix_index})"
    return f"{base}{fmt} {suffix_index}"


def make_unique_name(base: str, taken: Set[str], fmt: str = " (copy)") -> str:
    """Return a unique profile name, appending copy suffixes when needed."""

    candidate_base = (base or "").strip() or DEFAULT_PROFILE_NAME
    taken_lower = {item.lower() for item in taken}
    if candidate_base.lower() not in taken_lower:
        return candidate_base

    suffix_index = 1
    while True:
        candidate = _format_copy_name(candidate_base, fmt, suffix_index)
        if candidate.lower() not in taken_lower:
            return candidate
        suffix_index += 1


def make_unique_username(base: str, taken: Set[str]) -> str:
    """Return a unique username, appending -copy suffixes when needed."""

    candidate_base = (base or "").strip() or DEFAULT_USER_TEMPLATE["username"]
    taken_lower = {item.lower() for item in taken}
    if candidate_base.lower() not in taken_lower:
        return candidate_base

    candidate = f"{candidate_base}-copy"
    if candidate.lower() not in taken_lower:
        return candidate

    counter = 2
    while True:
        candidate = f"{candidate_base}-copy-{counter}"
        if candidate.lower() not in taken_lower:
            return candidate
        counter += 1


@dataclass
class User:
    username: str
    password: str
    full_name: str
    email: str
    original_username: Optional[str] = field(default=None, repr=False, compare=False)

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

    def clone(self) -> "User":
        return User(
            username=self.username,
            password=self.password,
            full_name=self.full_name,
            email=self.email,
        )

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
class OPNsenseProfile:
    id: str
    name: str
    settings: Dict[str, object]

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "settings": deepcopy(self.settings),
        }

    def clone(self, *, new_id: Optional[str] = None, name: Optional[str] = None) -> "OPNsenseProfile":
        return OPNsenseProfile(
            id=new_id or self.id,
            name=name or self.name,
            settings=deepcopy(self.settings),
        )

    @staticmethod
    def from_dict(payload: Dict[str, object]) -> "OPNsenseProfile":
        profile_id = str(payload.get("id") or uuid.uuid4().hex)
        name = payload.get("name") or DEFAULT_PROFILE_NAME
        settings = deepcopy(payload.get("settings") or {})

        if "connection" not in settings or not isinstance(settings["connection"], dict):
            settings["connection"] = _new_connection_defaults()
        else:
            conn = settings["connection"]
            for key, value in DEFAULT_CONNECTION.items():
                conn.setdefault(key, value)

        if "automation" not in settings or not isinstance(settings["automation"], dict):
            settings["automation"] = _new_automation_defaults()
        else:
            automation = settings["automation"]

            def _merge_defaults(target: Dict[str, object], defaults: Dict[str, object]) -> None:
                for default_key, default_value in defaults.items():
                    if default_key not in target:
                        target[default_key] = deepcopy(default_value)
                    elif isinstance(default_value, dict) and isinstance(target[default_key], dict):
                        _merge_defaults(target[default_key], default_value)

            _merge_defaults(automation, DEFAULT_AUTOMATION)

        return OPNsenseProfile(id=profile_id, name=str(name), settings=settings)


@dataclass
class UserProfile:
    id: str
    name: str
    users: List[User] = field(default_factory=list)

    def to_dict(self) -> Dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "users": [user.to_dict() for user in self.users],
        }

    def clone(self, *, new_id: Optional[str] = None, name: Optional[str] = None) -> "UserProfile":
        return UserProfile(
            id=new_id or self.id,
            name=name or self.name,
            users=[user.clone() for user in self.users],
        )

    @staticmethod
    def from_dict(payload: Dict[str, object]) -> "UserProfile":
        profile_id = str(payload.get("id") or uuid.uuid4().hex)
        name = payload.get("name") or DEFAULT_PROFILE_NAME
        users_payload = payload.get("users") or []
        users = [User.from_dict(item) for item in users_payload]
        return UserProfile(id=profile_id, name=str(name), users=users)


class ConfigManager:
    """Manage configuration persistence and in-memory state."""

    _EVENTS = (
        "opnsense_profiles_changed",
        "user_profiles_changed",
        "user_list_changed",
        "selection_changed",
    )

    def __init__(self, path: Path = CONFIG_DATA_PATH) -> None:
        self.path = path
        self._opnsense_profiles: List[OPNsenseProfile] = []
        self._user_profiles: List[UserProfile] = []
        self._selected_opnsense_profile_id: Optional[str] = None
        self._selected_user_profile_id: Optional[str] = None
        self._listeners: Dict[str, List[Callable[[], None]]] = {event: [] for event in self._EVENTS}

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
            "opnsense_profiles": [profile.to_dict() for profile in self._opnsense_profiles],
            "user_profiles": [profile.to_dict() for profile in self._user_profiles],
            "selected_opnsense_profile_id": self._selected_opnsense_profile_id,
            "selected_user_profile_id": self._selected_user_profile_id,
        }
        _ensure_directory(self.path)
        with self.path.open("w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")

    # ------------------------------------------------------------------
    # Event helpers
    # ------------------------------------------------------------------
    def register_listener(self, event: str, callback: Callable[[], None]) -> None:
        if event not in self._listeners:
            raise ValueError(f"Unsupported event '{event}'.")
        self._listeners[event].append(callback)

    def _notify(self, event: str) -> None:
        listeners = self._listeners.get(event, [])
        for callback in list(listeners):
            callback()

    # ------------------------------------------------------------------
    # Public getters / selection
    # ------------------------------------------------------------------
    def list_opnsense_profiles(self) -> List[OPNsenseProfile]:
        return list(self._opnsense_profiles)

    def list_user_profiles(self) -> List[UserProfile]:
        return list(self._user_profiles)

    def get_opnsense_profile(self, profile_id: str) -> OPNsenseProfile:
        for profile in self._opnsense_profiles:
            if profile.id == profile_id:
                return profile
        raise ValueError(f"OPNsense profile '{profile_id}' was not found.")

    def get_user_profile(self, profile_id: str) -> UserProfile:
        for profile in self._user_profiles:
            if profile.id == profile_id:
                return profile
        raise ValueError(f"User profile '{profile_id}' was not found.")

    def get_selected_opnsense_profile_id(self) -> Optional[str]:
        return self._selected_opnsense_profile_id

    def get_selected_user_profile_id(self) -> Optional[str]:
        return self._selected_user_profile_id

    def get_selected_opnsense_profile(self) -> Optional[OPNsenseProfile]:
        if not self._selected_opnsense_profile_id:
            return None
        try:
            return self.get_opnsense_profile(self._selected_opnsense_profile_id)
        except ValueError:
            return None

    def get_selected_user_profile(self) -> Optional[UserProfile]:
        if not self._selected_user_profile_id:
            return None
        try:
            return self.get_user_profile(self._selected_user_profile_id)
        except ValueError:
            return None

    def set_selected_opnsense_profile_id(self, profile_id: Optional[str]) -> None:
        if profile_id is None:
            if self._selected_opnsense_profile_id is not None:
                self._selected_opnsense_profile_id = None
                self._notify("selection_changed")
            return

        self.get_opnsense_profile(profile_id)
        if self._selected_opnsense_profile_id != profile_id:
            self._selected_opnsense_profile_id = profile_id
            self._notify("selection_changed")

    def set_selected_user_profile_id(self, profile_id: Optional[str]) -> None:
        if profile_id is None:
            if self._selected_user_profile_id is not None:
                self._selected_user_profile_id = None
                self._notify("selection_changed")
            return

        self.get_user_profile(profile_id)
        if self._selected_user_profile_id != profile_id:
            self._selected_user_profile_id = profile_id
            self._notify("selection_changed")

    # ------------------------------------------------------------------
    # OPNsense profile CRUD
    # ------------------------------------------------------------------
    def create_opnsense_profile(
        self, name: str, settings: Optional[Dict[str, object]] = None
    ) -> OPNsenseProfile:
        clean_name = (name or "").strip() or DEFAULT_PROFILE_NAME
        self._ensure_unique_opnsense_name(clean_name)
        payload = {
            "id": uuid.uuid4().hex,
            "name": clean_name,
            "settings": deepcopy(settings) if settings else {},
        }
        profile = OPNsenseProfile.from_dict(payload)
        self._opnsense_profiles.append(profile)
        if not self._selected_opnsense_profile_id:
            self._selected_opnsense_profile_id = profile.id
            self._notify("selection_changed")
        self._notify("opnsense_profiles_changed")
        return profile

    def rename_opnsense_profile(self, profile_id: str, new_name: str) -> None:
        profile = self.get_opnsense_profile(profile_id)
        clean_name = (new_name or "").strip()
        if not clean_name:
            raise ValueError("Profile name cannot be empty.")
        self._ensure_unique_opnsense_name(clean_name, exclude_id=profile_id)
        profile.name = clean_name
        self._notify("opnsense_profiles_changed")

    def delete_opnsense_profile(self, profile_id: str) -> None:
        if len(self._opnsense_profiles) <= 1:
            raise ValueError("Cannot delete the last OPNsense profile.")
        profile = self.get_opnsense_profile(profile_id)
        self._opnsense_profiles.remove(profile)
        was_selected = self._selected_opnsense_profile_id == profile_id
        if was_selected:
            replacement = self._opnsense_profiles[0] if self._opnsense_profiles else None
            self._selected_opnsense_profile_id = replacement.id if replacement else None
        self._notify("opnsense_profiles_changed")
        if was_selected:
            self._notify("selection_changed")

    def duplicate_opnsense_profile(
        self, source_profile_id: str, new_name: Optional[str] = None
    ) -> OPNsenseProfile:
        source = self.get_opnsense_profile(source_profile_id)
        taken = {profile.name for profile in self._opnsense_profiles}
        base_name = (new_name or source.name).strip() or DEFAULT_PROFILE_NAME
        duplicate_name = make_unique_name(base_name, taken)
        clone = source.clone(new_id=uuid.uuid4().hex, name=duplicate_name)
        self._opnsense_profiles.append(clone)
        self._selected_opnsense_profile_id = clone.id
        self._notify("opnsense_profiles_changed")
        self._notify("selection_changed")
        return clone

    def update_opnsense_connection(self, profile_id: str, connection: Dict[str, str]) -> None:
        profile = self.get_opnsense_profile(profile_id)
        conn = profile.settings.setdefault("connection", {})
        for key, default_value in DEFAULT_CONNECTION.items():
            value = connection.get(key, default_value)
            conn[key] = value.strip() if isinstance(value, str) else str(value)

    def update_opnsense_settings(self, profile_id: str, automation: Dict[str, object]) -> None:
        profile = self.get_opnsense_profile(profile_id)
        profile.settings["automation"] = deepcopy(automation)

    # ------------------------------------------------------------------
    # User profile CRUD
    # ------------------------------------------------------------------
    def create_user_profile(
        self, name: str, users: Optional[Iterable[Dict[str, str]]] = None
    ) -> UserProfile:
        clean_name = (name or "").strip() or DEFAULT_PROFILE_NAME
        self._ensure_unique_user_profile_name(clean_name)
        payload = {
            "id": uuid.uuid4().hex,
            "name": clean_name,
            "users": list(users or []),
        }
        profile = UserProfile.from_dict(payload)
        self._user_profiles.append(profile)
        if not self._selected_user_profile_id:
            self._selected_user_profile_id = profile.id
            self._notify("selection_changed")
        self._notify("user_profiles_changed")
        return profile

    def rename_user_profile(self, profile_id: str, new_name: str) -> None:
        profile = self.get_user_profile(profile_id)
        clean_name = (new_name or "").strip()
        if not clean_name:
            raise ValueError("Profile name cannot be empty.")
        self._ensure_unique_user_profile_name(clean_name, exclude_id=profile_id)
        profile.name = clean_name
        self._notify("user_profiles_changed")

    def delete_user_profile(self, profile_id: str) -> None:
        if len(self._user_profiles) <= 1:
            raise ValueError("Cannot delete the last user profile.")
        profile = self.get_user_profile(profile_id)
        self._user_profiles.remove(profile)
        was_selected = self._selected_user_profile_id == profile_id
        if was_selected:
            replacement = self._user_profiles[0] if self._user_profiles else None
            self._selected_user_profile_id = replacement.id if replacement else None
        self._notify("user_profiles_changed")
        if was_selected:
            self._notify("selection_changed")

    def duplicate_user_profile(
        self, source_profile_id: str, new_name: Optional[str] = None
    ) -> UserProfile:
        source = self.get_user_profile(source_profile_id)
        taken = {profile.name for profile in self._user_profiles}
        base_name = (new_name or source.name).strip() or DEFAULT_PROFILE_NAME
        duplicate_name = make_unique_name(base_name, taken)
        clone = source.clone(new_id=uuid.uuid4().hex, name=duplicate_name)
        self._user_profiles.append(clone)
        self._selected_user_profile_id = clone.id
        self._notify("user_profiles_changed")
        self._notify("selection_changed")
        self._notify("user_list_changed")
        return clone

    # ------------------------------------------------------------------
    # User management (scoped to user profiles)
    # ------------------------------------------------------------------
    def add_user(self, user_profile_id: str, user: User) -> None:
        profile = self.get_user_profile(user_profile_id)
        username = user.username.strip()
        if not username:
            raise ValueError("Username cannot be empty.")
        self._ensure_unique_username(profile, username)
        profile.users.append(User.from_dict(user.to_dict()))
        self._notify("user_list_changed")

    def update_user(self, user_profile_id: str, user: User) -> None:
        profile = self.get_user_profile(user_profile_id)
        original = (user.original_username or user.username).strip()
        if not original:
            raise ValueError("Original username is required.")
        new_username = user.username.strip()
        if not new_username:
            raise ValueError("Username cannot be empty.")
        match_index: Optional[int] = None
        for idx, existing in enumerate(profile.users):
            if existing.username.lower() == original.lower():
                match_index = idx
                break
        if match_index is None:
            raise ValueError(f"User '{original}' was not found in profile '{profile.name}'.")
        if new_username.lower() != original.lower():
            self._ensure_unique_username(profile, new_username, exclude=original)
        profile.users[match_index] = User.from_dict(user.to_dict())
        self._notify("user_list_changed")

    def delete_user(self, user_profile_id: str, username: str) -> None:
        profile = self.get_user_profile(user_profile_id)
        for idx, existing in enumerate(profile.users):
            if existing.username.lower() == username.lower():
                del profile.users[idx]
                self._notify("user_list_changed")
                return
        raise ValueError(f"User '{username}' was not found in profile '{profile.name}'.")

    def duplicate_user(
        self, user_profile_id: str, username: str, new_username: Optional[str] = None
    ) -> User:
        profile = self.get_user_profile(user_profile_id)
        for existing in profile.users:
            if existing.username.lower() == username.lower():
                taken = {user.username for user in profile.users}
                base = (new_username or existing.username).strip() or existing.username
                duplicate_username = make_unique_username(base, taken)
                clone = existing.clone()
                clone.username = duplicate_username
                profile.users.append(clone)
                self._notify("user_list_changed")
                return clone
        raise ValueError(f"User '{username}' was not found in profile '{profile.name}'.")

    # ------------------------------------------------------------------
    # Legacy export helpers
    # ------------------------------------------------------------------
    def export_legacy_files(
        self,
        opnsense_profile_id: Optional[str] = None,
        user_profile_id: Optional[str] = None,
        username: Optional[str] = None,
    ) -> None:
        if not self._opnsense_profiles:
            raise ValueError("No OPNsense profiles are available to export.")
        target_opnsense = self._resolve_opnsense_profile(opnsense_profile_id)
        target_user_profile: Optional[UserProfile] = None
        if self._user_profiles:
            target_user_profile = self._resolve_user_profile(user_profile_id)

        legacy_profiles = []
        for profile in self._opnsense_profiles:
            conn = deepcopy(profile.settings.get("connection", {}))
            legacy_profile = {"ProfileName": profile.name}
            legacy_profile.update(conn)
            legacy_profiles.append(legacy_profile)
        _ensure_directory(LEGACY_PROFILE_PATH)
        with LEGACY_PROFILE_PATH.open("w", encoding="utf-8") as handle:
            json.dump({"profiles": legacy_profiles}, handle, indent=2, ensure_ascii=False)
            handle.write("\n")

        automation = deepcopy(target_opnsense.settings.get("automation", {}))
        _ensure_directory(LEGACY_SETTINGS_PATH)
        with LEGACY_SETTINGS_PATH.open("w", encoding="utf-8") as handle:
            json.dump(automation, handle, indent=2, ensure_ascii=False)
            handle.write("\n")

        legacy_users_payload: List[Dict[str, str]] = []
        if target_user_profile:
            if username:
                matched_user = next(
                    (
                        user
                        for user in target_user_profile.users
                        if user.username.lower() == username.lower()
                    ),
                    None,
                )
                if not matched_user:
                    raise ValueError(
                        f"User '{username}' was not found in profile '{target_user_profile.name}'."
                    )
                legacy_users_payload = [matched_user.to_legacy_dict()]
            else:
                legacy_users_payload = [user.to_legacy_dict() for user in target_user_profile.users]
        _ensure_directory(LEGACY_USERS_PATH)
        with LEGACY_USERS_PATH.open("w", encoding="utf-8") as handle:
            json.dump({"users": legacy_users_payload}, handle, indent=2, ensure_ascii=False)
            handle.write("\n")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _resolve_opnsense_profile(self, profile_id: Optional[str]) -> OPNsenseProfile:
        if profile_id:
            return self.get_opnsense_profile(profile_id)
        selected = self.get_selected_opnsense_profile()
        if selected:
            return selected
        if not self._opnsense_profiles:
            raise ValueError("No OPNsense profiles are available.")
        return self._opnsense_profiles[0]

    def _resolve_user_profile(self, profile_id: Optional[str]) -> UserProfile:
        if profile_id:
            return self.get_user_profile(profile_id)
        selected = self.get_selected_user_profile()
        if selected:
            return selected
        if not self._user_profiles:
            raise ValueError("No user profiles are available.")
        return self._user_profiles[0]

    def _load(self) -> None:
        migrated = False
        data: Dict[str, object] = {}

        if self.path.exists():
            try:
                data = self._read_json(self.path)
            except json.JSONDecodeError:
                data = {}
            if "opnsense_profiles" in data and "user_profiles" in data:
                pass
            elif "profiles" in data:
                data = self._migrate_profiles_payload(data)
                migrated = True
            elif "settings" in data and "users" in data:
                data = self._migrate_single_profile_payload(data)
                migrated = True
            else:
                data = {"opnsense_profiles": [], "user_profiles": []}
        else:
            data = self._load_from_split_files()
            migrated = True

        self._load_from_payload(data)
        if migrated:
            self.save()

    def _load_from_payload(self, payload: Dict[str, object]) -> None:
        opnsense_payload = payload.get("opnsense_profiles") or []
        user_payload = payload.get("user_profiles") or []
        self._opnsense_profiles = [OPNsenseProfile.from_dict(item) for item in opnsense_payload]
        self._user_profiles = [UserProfile.from_dict(item) for item in user_payload]

        if not self._opnsense_profiles:
            default_profile = OPNsenseProfile.from_dict(
                {"id": uuid.uuid4().hex, "name": DEFAULT_PROFILE_NAME, "settings": {}}
            )
            self._opnsense_profiles = [default_profile]

        if not self._user_profiles:
            default_user_profile = UserProfile.from_dict(
                {"id": uuid.uuid4().hex, "name": DEFAULT_PROFILE_NAME, "users": []}
            )
            self._user_profiles = [default_user_profile]

        selected_opnsense_id = payload.get("selected_opnsense_profile_id")
        valid_opnsense_ids = {profile.id for profile in self._opnsense_profiles}
        if selected_opnsense_id and selected_opnsense_id in valid_opnsense_ids:
            self._selected_opnsense_profile_id = selected_opnsense_id
        else:
            self._selected_opnsense_profile_id = self._opnsense_profiles[0].id

        selected_user_id = payload.get("selected_user_profile_id")
        valid_user_ids = {profile.id for profile in self._user_profiles}
        if selected_user_id and selected_user_id in valid_user_ids:
            self._selected_user_profile_id = selected_user_id
        else:
            self._selected_user_profile_id = self._user_profiles[0].id

    def _load_from_split_files(self) -> Dict[str, object]:
        profiles_payload: List[Dict[str, object]] = []
        if LEGACY_PROFILE_PATH.exists():
            try:
                data = self._read_json(LEGACY_PROFILE_PATH)
                profiles_payload = data.get("profiles") or []
            except json.JSONDecodeError:
                profiles_payload = []

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
            try:
                data = self._read_json(LEGACY_USERS_PATH)
                users_payload = data.get("users") or []
            except json.JSONDecodeError:
                users_payload = []

        if not profiles_payload:
            profiles_payload = [
                {
                    "ProfileName": DEFAULT_PROFILE_NAME,
                    **_new_connection_defaults(),
                }
            ]

        opnsense_profiles = []
        user_profiles = []
        taken_opnsense: Set[str] = set()
        taken_user: Set[str] = set()
        for item in profiles_payload:
            connection = {key: item.get(key, DEFAULT_CONNECTION[key]) for key in DEFAULT_CONNECTION}
            raw_name = item.get("ProfileName") or DEFAULT_PROFILE_NAME
            opnsense_name = make_unique_name(raw_name, taken_opnsense)
            taken_opnsense.add(opnsense_name)
            user_profile_name = make_unique_name(raw_name, taken_user)
            taken_user.add(user_profile_name)
            opnsense_profiles.append(
                {
                    "id": uuid.uuid4().hex,
                    "name": opnsense_name,
                    "settings": {
                        "connection": connection,
                        "automation": deepcopy(settings_payload),
                    },
                }
            )
            user_profiles.append(
                {
                    "id": uuid.uuid4().hex,
                    "name": user_profile_name,
                    "users": [dict(user) for user in users_payload],
                }
            )

        return {
            "opnsense_profiles": opnsense_profiles,
            "user_profiles": user_profiles,
            "selected_opnsense_profile_id": opnsense_profiles[0]["id"],
            "selected_user_profile_id": user_profiles[0]["id"],
        }

    def _migrate_profiles_payload(self, payload: Dict[str, object]) -> Dict[str, object]:
        profiles_payload = payload.get("profiles") or []
        opnsense_profiles = []
        user_profiles = []
        taken_opnsense: Set[str] = set()
        taken_user: Set[str] = set()

        for item in profiles_payload:
            name = item.get("name") or DEFAULT_PROFILE_NAME
            settings = deepcopy(item.get("settings") or {})
            users = item.get("users") or []

            opnsense_name = make_unique_name(name, taken_opnsense)
            taken_opnsense.add(opnsense_name)
            user_profile_name = make_unique_name(name, taken_user)
            taken_user.add(user_profile_name)

            opnsense_profiles.append(
                {
                    "id": str(item.get("id") or uuid.uuid4().hex),
                    "name": opnsense_name,
                    "settings": {
                        "connection": deepcopy(settings.get("connection") or {}),
                        "automation": deepcopy(settings.get("automation") or {}),
                    },
                }
            )
            user_profiles.append(
                {
                    "id": uuid.uuid4().hex,
                    "name": user_profile_name,
                    "users": deepcopy(users),
                }
            )

        selected_id = payload.get("selected_profile_id") or payload.get("active_profile_id")
        selected_opnsense_id = None
        if selected_id and profiles_payload:
            for op_profile, legacy in zip(opnsense_profiles, profiles_payload):
                legacy_id = str(legacy.get("id") or "")
                if legacy_id and legacy_id == selected_id:
                    selected_opnsense_id = op_profile["id"]
                    break
        return {
            "opnsense_profiles": opnsense_profiles,
            "user_profiles": user_profiles,
            "selected_opnsense_profile_id": selected_opnsense_id or opnsense_profiles[0]["id"],
            "selected_user_profile_id": user_profiles[0]["id"],
        }

    def _migrate_single_profile_payload(self, payload: Dict[str, object]) -> Dict[str, object]:
        automation = deepcopy(payload.get("settings") or {})
        users = payload.get("users") or []
        profile_id = payload.get("id") or uuid.uuid4().hex
        name = payload.get("name") or DEFAULT_PROFILE_NAME
        opnsense_profile = {
            "id": str(profile_id),
            "name": name,
            "settings": {
                "connection": _new_connection_defaults(),
                "automation": automation or _new_automation_defaults(),
            },
        }
        user_profile = {
            "id": uuid.uuid4().hex,
            "name": name,
            "users": deepcopy(users),
        }
        return {
            "opnsense_profiles": [opnsense_profile],
            "user_profiles": [user_profile],
            "selected_opnsense_profile_id": opnsense_profile["id"],
            "selected_user_profile_id": user_profile["id"],
        }

    @staticmethod
    def _read_json(path: Path) -> Dict[str, object]:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _ensure_unique_opnsense_name(self, name: str, exclude_id: Optional[str] = None) -> None:
        for profile in self._opnsense_profiles:
            if exclude_id and profile.id == exclude_id:
                continue
            if profile.name.lower() == name.lower():
                raise ValueError(f"An OPNsense profile named '{name}' already exists.")

    def _ensure_unique_user_profile_name(self, name: str, exclude_id: Optional[str] = None) -> None:
        for profile in self._user_profiles:
            if exclude_id and profile.id == exclude_id:
                continue
            if profile.name.lower() == name.lower():
                raise ValueError(f"A user profile named '{name}' already exists.")

    @staticmethod
    def _ensure_unique_username(
        profile: UserProfile, username: str, exclude: Optional[str] = None
    ) -> None:
        for user in profile.users:
            if exclude and user.username.lower() == exclude.lower():
                continue
            if user.username.lower() == username.lower():
                raise ValueError(
                    f"User '{username}' already exists in profile '{profile.name}'."
                )
