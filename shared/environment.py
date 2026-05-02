from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

IS_WINDOWS = os.name == "nt"


class EnvironmentIssue(RuntimeError):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _python_candidates() -> List[str]:
    candidates: List[str] = []
    for candidate in [
        os.sys.executable,
        shutil.which("python3"),
        shutil.which("python"),
        r"C:\Users\Administrator\AppData\Local\Programs\Python\Python313\python.exe",
    ]:
        if candidate and candidate not in candidates and Path(candidate).exists():
            candidates.append(candidate)
    return candidates


def _yt_dlp_bin_candidates() -> List[str]:
    candidates: List[str] = []
    for candidate in [
        shutil.which("yt-dlp"),
        str(Path.home() / ".local" / "bin" / "yt-dlp"),
        r"C:\Users\Administrator\AppData\Local\Programs\Python\Python313\Scripts\yt-dlp.exe",
    ]:
        if candidate and candidate not in candidates and Path(candidate).exists():
            candidates.append(candidate)
    return candidates


def get_mpv_path() -> Optional[str]:
    if IS_WINDOWS:
        for candidate in [
            shutil.which("mpv"),
            r"C:\Program Files\mpv\mpv.exe",
            r"C:\Users\Administrator\AppData\Local\Programs\mpv\mpv.exe",
        ]:
            if candidate and Path(candidate).exists():
                return candidate
        return None
    for candidate in [
        shutil.which("mpv"),
        "/opt/homebrew/bin/mpv",
        "/usr/local/bin/mpv",
    ]:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def get_yt_dlp_command() -> Optional[List[str]]:
    for candidate in _yt_dlp_bin_candidates():
        result = subprocess.run([candidate, "--version"], capture_output=True, timeout=20, check=False)
        if result.returncode == 0:
            return [candidate]
    for python_bin in _python_candidates():
        result = subprocess.run(
            [python_bin, "-m", "yt_dlp", "--version"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if result.returncode == 0:
            return [python_bin, "-m", "yt_dlp"]
    return None


def _path_has_local_bin() -> bool:
    path_entries = os.environ.get("PATH", os.pathsep).split(os.pathsep)
    if IS_WINDOWS:
        local_bin = str(Path.home() / "AppData" / "Local" / "Programs" / "Python" / "Python313" / "Scripts")
        return local_bin in path_entries
    return str(Path.home() / ".local" / "bin") in path_entries


def _is_pid_alive(pid: int) -> bool:
    if IS_WINDOWS:
        result = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
        )
        return str(pid) in result.stdout
    else:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _read_pid(path: Path) -> Optional[int]:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def _pgrep(pattern: str) -> List[int]:
    if IS_WINDOWS:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq python.exe", "/NH", "/FO", "CSV"],
            capture_output=True,
            text=True,
        )
        values: List[int] = []
        for line in result.stdout.splitlines():
            try:
                parts = line.strip().split('","')
                if len(parts) >= 2:
                    pid = int(parts[1].strip('"'))
                    values.append(pid)
            except (ValueError, IndexError):
                continue
        return values
    else:
        result = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        return [int(line.strip()) for line in result.stdout.splitlines() if line.strip().isdigit()]


def _kill_pids(pids: List[int]) -> None:
    if not pids:
        return
    if IS_WINDOWS:
        for pid in pids:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], check=False)
    else:
        subprocess.run(["kill", "-TERM"] + [str(pid) for pid in pids], check=False)
        import time
        time.sleep(0.4)
        survivors = [pid for pid in pids if _is_pid_alive(pid)]
        if survivors:
            subprocess.run(["kill", "-KILL"] + [str(pid) for pid in survivors], check=False)


def get_musicd_pids() -> List[int]:
    return _pgrep(r"musicd\.daemon --serve")


def get_musicd_mpv_pids() -> List[int]:
    if IS_WINDOWS:
        return _pgrep(r"mpv")
    return _pgrep(rf"mpv .*--input-ipc-server=")


def collect_environment_report() -> dict:
    mpv_path = get_mpv_path()
    yt_dlp_command = get_yt_dlp_command()
    musicd_pids = get_musicd_pids()
    mpv_pids = get_musicd_mpv_pids()
    checks = [
        {
            "key": "mpv",
            "ok": bool(mpv_path),
            "message": f"已检测到 mpv：{mpv_path}" if mpv_path else "未检测到 mpv",
        },
        {
            "key": "yt_dlp",
            "ok": bool(yt_dlp_command),
            "message": (
                f"已检测到 yt-dlp：{' '.join(yt_dlp_command)}"
                if yt_dlp_command
                else "未检测到可用的 yt-dlp"
            ),
        },
        {
            "key": "local_bin",
            "ok": _path_has_local_bin(),
            "message": (
                "PATH 已包含 Scripts 目录"
                if _path_has_local_bin()
                else "PATH 未包含 Scripts 目录，终端里可能找不到 musicctl"
            ),
        },
        {
            "key": "musicd_processes",
            "ok": len(musicd_pids) <= 1,
            "message": f"musicd 进程数：{len(musicd_pids)}",
        },
        {
            "key": "mpv_processes",
            "ok": len(mpv_pids) <= 1,
            "message": f"music-agent 管理的 mpv 进程数：{len(mpv_pids)}",
        },
    ]
    blocking_issues = [
        check["message"]
        for check in checks
        if check["key"] in {"mpv", "yt_dlp"} and not check["ok"]
    ]
    warnings = [
        check["message"]
        for check in checks
        if check["key"] not in {"mpv", "yt_dlp"} and not check["ok"]
    ]
    return {
        "ok": not blocking_issues,
        "checks": checks,
        "blocking_issues": blocking_issues,
        "warnings": warnings,
        "mpv_path": mpv_path,
        "yt_dlp_command": yt_dlp_command,
        "musicd_pids": musicd_pids,
        "mpv_pids": mpv_pids,
    }


def format_blocking_message(report: dict) -> str:
    parts = []
    if report["blocking_issues"]:
        parts.append("环境检查未通过：")
        parts.extend(report["blocking_issues"])
    if report["warnings"]:
        parts.append("附加提醒：")
        parts.extend(report["warnings"])
    parts.append("请先运行：musicctl --text doctor")
    return "；".join(parts)


def ensure_playback_environment() -> None:
    report = collect_environment_report()
    if not report["ok"]:
        raise EnvironmentIssue(format_blocking_message(report))


def _try_install_yt_dlp() -> str:
    for python_bin in _python_candidates():
        result = subprocess.run(
            [python_bin, "-m", "pip", "--version"],
            capture_output=True,
            timeout=20,
            check=False,
        )
        if result.returncode != 0:
            continue
        install = subprocess.run(
            [python_bin, "-m", "pip", "install", "--user", "yt-dlp"],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if install.returncode == 0 and get_yt_dlp_command():
            return f"已尝试通过 {python_bin} 安装 yt-dlp"
    return "无法自动安装 yt-dlp，请手动执行：python -m pip install --user yt-dlp"


def _try_install_mpv() -> str:
    if IS_WINDOWS:
        return "请手动下载安装 mpv：https://mpv.io/installation/（或搜索 mpv windows 下载）"
    brew = shutil.which("brew")
    if not brew:
        return "未检测到 Homebrew，无法自动安装 mpv，请手动安装 mpv"
    install = subprocess.run([brew, "install", "mpv"], capture_output=True, text=True, timeout=1800, check=False)
    if install.returncode == 0 and get_mpv_path():
        return "已尝试通过 Homebrew 安装 mpv"
    stderr = (install.stderr or "").strip()
    if stderr:
        return f"自动安装 mpv 失败：{stderr.splitlines()[-1]}"
    return "自动安装 mpv 失败，请检查 Homebrew 权限后重试"


def attempt_environment_fix() -> list[str]:
    notes: list[str] = []
    if not get_yt_dlp_command():
        notes.append(_try_install_yt_dlp())
    if not get_mpv_path():
        notes.append(_try_install_mpv())
    duplicate_notes = cleanup_duplicate_runtime_processes()
    notes.extend(duplicate_notes)
    return notes


def cleanup_duplicate_runtime_processes() -> List[str]:
    notes: List[str] = []
    app_dir = Path.home() / "AppData" / "Local" / "music-agent-win"
    current_musicd = _read_pid(app_dir / "musicd.pid")
    current_mpv = _read_pid(app_dir / "mpv.pid")
    extra_musicd = [pid for pid in get_musicd_pids() if pid != current_musicd]
    extra_mpv = [pid for pid in get_musicd_mpv_pids() if pid != current_mpv]
    if extra_musicd:
        _kill_pids(extra_musicd)
        notes.append(f"已清理多余 musicd 进程：{', '.join(str(pid) for pid in extra_musicd)}")
    if extra_mpv:
        _kill_pids(extra_mpv)
        notes.append(f"已清理多余 mpv 进程：{', '.join(str(pid) for pid in extra_mpv)}")
    return notes


def cleanup_all_runtime_processes() -> list[str]:
    notes: List[str] = []
    musicd = get_musicd_pids()
    mpv = get_musicd_mpv_pids()
    if musicd:
        _kill_pids(musicd)
        notes.append(f"已停止 musicd：{', '.join(str(pid) for pid in musicd)}")
    if mpv:
        _kill_pids(mpv)
        notes.append(f"已停止 mpv：{', '.join(str(pid) for pid in mpv)}")
    app_dir = Path.home() / "AppData" / "Local" / "music-agent-win"
    for path in [
        app_dir / "musicd",
        app_dir / "musicd.pid",
        app_dir / "mpv",
        app_dir / "mpv.pid",
        app_dir / "musicd.lock",
    ]:
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass
    return notes