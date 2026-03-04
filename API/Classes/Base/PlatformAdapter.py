from __future__ import annotations

import os
import platform
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path


class PlatformAdapter:
    """Centralized OS detection utilities."""

    @staticmethod
    def system() -> str:
        """
        Return a standardized platform string.

        Values are aligned with Python's platform.system():
        - 'Windows'
        - 'Darwin' (macOS)
        - 'Linux'
        """
        return platform.system()

    @staticmethod
    def is_windows() -> bool:
        return PlatformAdapter.system() == "Windows"

    @staticmethod
    def is_macos() -> bool:
        return PlatformAdapter.system() == "Darwin"

    @staticmethod
    def is_linux() -> bool:
        return PlatformAdapter.system() == "Linux"


@dataclass(frozen=True)
class SolverResolution:
    binary_path: Path
    source: str  # 'env', 'path', 'bundled'


class DependencyManager:
    """
    Centralized dependency/binary resolution layer.

    - Uses shutil.which for PATH lookups
    - Applies Windows .exe suffix for lookups where needed
    - Can ensure bundled binaries are executable on Unix/macOS
    """

    def __init__(self, solvers_folder: Path | None = None):
        if solvers_folder is None:
            # Avoid importing Config here to keep this module low-side-effect
            # (e.g., scripts/setup_dev.py imports this module early).
            # Repo root is 3 levels above API/Classes/Base.
            repo_root = Path(__file__).resolve().parents[3]
            solvers_folder = repo_root / "WebAPP" / "SOLVERs"
        self.solvers_folder = Path(solvers_folder).resolve()

    def _binary_name_candidates(self, base_name: str) -> list[str]:
        base = base_name.strip()
        if not base:
            return []
        if PlatformAdapter.is_windows() and not base.lower().endswith(".exe"):
            return [f"{base}.exe", base]
        return [base]

    def which(self, base_name: str) -> Path | None:
        """
        Resolve a binary on PATH.
        Returns a Path to the resolved executable, or None.
        """
        for name in self._binary_name_candidates(base_name):
            found = shutil.which(name)
            if found:
                return Path(found).resolve()
        return None

    def get_status_report(self) -> dict:
        """
        Return a lightweight status snapshot for diagnostics.

        Includes:
          - current OS
          - resolved solver paths (glpsol, cbc) or 'Not Found'
          - whether the bundled solvers folder is writable
        """
        glpsol = self.which("glpsol")
        cbc = self.which("cbc")

        return {
            "os": PlatformAdapter.system(),
            "solvers": {
                "glpsol": str(glpsol) if glpsol else "Not Found",
                "cbc": str(cbc) if cbc else "Not Found",
            },
            "solvers_folder": str(self.solvers_folder),
            "solvers_folder_writable": os.access(self.solvers_folder, os.W_OK),
        }

    def ensure_executable(self, path: Path) -> None:
        """
        Ensure a binary is executable on macOS/Linux when it lives under our
        bundled solver directory (WebAPP/SOLVERs).

        On Windows this is a no-op.
        """
        p = Path(path)
        if PlatformAdapter.is_windows():
            return

        try:
            resolved = p.resolve()
        except FileNotFoundError:
            raise RuntimeError(f"Binary not found: {p}")

        try:
            if not resolved.is_relative_to(self.solvers_folder):
                return
        except AttributeError:
            # Python <3.9 fallback; project targets >=3.10 but keep this safe.
            if not str(resolved).startswith(str(self.solvers_folder) + os.sep):
                return

        try:
            mode = resolved.stat().st_mode
            if mode & stat.S_IXUSR:
                return
            os.chmod(resolved, mode | stat.S_IEXEC)
        except OSError as exc:
            raise RuntimeError(
                f"Failed to mark bundled solver binary as executable: {resolved}\n"
                f"Try running: chmod +x '{resolved}'\n"
                f"Underlying error: {exc}"
            )

    def _find_binary_in_dir(self, root: Path, base_name: str, *, recursive: bool) -> Path | None:
        names = self._binary_name_candidates(base_name)
        if not names:
            return None

        if root.is_file():
            lowered = {n.lower() for n in names}
            return root if root.name.lower() in lowered else None

        if not root.is_dir():
            return None

        for n in names:
            candidate = root / n
            if candidate.is_file():
                return candidate

        if recursive:
            for n in names:
                for candidate in root.rglob(n):
                    if candidate.is_file():
                        return candidate

        return None

    def resolve_solver(
        self,
        *,
        env_var: str,
        binary_name: str,
        bundled_dir: Path,
    ) -> SolverResolution:
        """
        Resolve a solver binary using a 3-tier priority chain:
          1) Environment variable (env_var): path to executable OR directory containing it
          2) System PATH
          3) Bundled directory (bundled_dir) inside SOLVERs_FOLDER

        Returns a SolverResolution with the final binary path.
        """
        env_val = os.environ.get(env_var, "").strip().strip("\"'")
        if env_val:
            env_path = Path(env_val).expanduser()
            env_bin = self._find_binary_in_dir(env_path, binary_name, recursive=False)
            if env_bin is not None:
                self.ensure_executable(env_bin)
                return SolverResolution(binary_path=env_bin.resolve(), source="env")
            raise RuntimeError(
                f"{env_var} is set to '{env_val}', but no '{binary_name}' binary was found there.\n"
                f"Set {env_var} to the solver executable or to the directory containing it."
            )

        path_bin = self.which(binary_name)
        if path_bin is not None:
            return SolverResolution(binary_path=path_bin, source="path")

        bundled_bin = self._find_binary_in_dir(Path(bundled_dir), binary_name, recursive=True)
        if bundled_bin is not None:
            self.ensure_executable(bundled_bin)
            return SolverResolution(binary_path=bundled_bin.resolve(), source="bundled")

        raise RuntimeError(
            f"Solver binary '{binary_name}' could not be found.\n"
            f"Set {env_var}, install '{binary_name}' on PATH, or provide bundled binaries under '{bundled_dir}'."
        )


# Singleton used across the codebase.
dependency_manager = DependencyManager()

