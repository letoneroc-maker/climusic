#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json as _json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

IS_WINDOWS = os.name == "nt"
if IS_WINDOWS:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
MPV_PATH = None
YT_DLP_CMD = None


def init():
    global MPV_PATH, YT_DLP_CMD
    if IS_WINDOWS:
        for p in [r"C:\Program Files\mpv\mpv.exe", shutil.which("mpv")]:
            if p and Path(p).exists():
                MPV_PATH = p
                break
    else:
        for p in [shutil.which("mpv"), "/usr/local/bin/mpv"]:
            if p and Path(p).exists():
                MPV_PATH = p
                break

    # yt-dlp: prefer Python module (supports --js-runtimes), then .exe, then fallback
    ytdlp = shutil.which("yt-dlp")
    if ytdlp:
        YT_DLP_CMD = [ytdlp]
    else:
        r = subprocess.run([sys.executable, "-m", "yt_dlp", "--version"], capture_output=True, timeout=10, check=False)
        if r.returncode == 0:
            YT_DLP_CMD = [sys.executable, "-m", "yt_dlp"]
        else:
            scripts = Path(sys.executable).parent / "Scripts" / "yt-dlp.exe"
            if scripts.exists():
                YT_DLP_CMD = [str(scripts)]

    if not MPV_PATH:
        print("ERROR: mpv not found. Install mpv from https://mpv.io/installation/", file=sys.stderr)
    if not YT_DLP_CMD:
        print("ERROR: yt-dlp not found. Run: pip install yt-dlp", file=sys.stderr)


def _run(cmd, timeout=45):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)


def _clear_line():
    sys.stdout.write("\r" + " " * 100 + "\r")
    sys.stdout.flush()


def _progress_bar(elapsed: float, total: float, width: int = 30) -> str:
    if total <= 0:
        return "[" + "=" * width + "]"
    ratio = min(elapsed / total, 1.0)
    filled = int(width * ratio)
    bar = "#" * filled + "-" * (width - filled)
    return f"[{bar}]"


def _format_time(seconds):
    if not seconds:
        return "00:00"
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


def _get_mpv_time_pos(pipe_path: str) -> tuple:
    """Query mpv for current time position. Returns (elapsed, duration)."""
    if not MPV_PATH:
        return 0, 0

    if IS_WINDOWS:
        return _get_mpv_time_windows(pipe_path)
    return _get_mpv_time_unix(pipe_path)


def _get_mpv_time_unix(pipe_path: str) -> tuple:
    try:
        import socket
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(pipe_path)
        cmd = _json.dumps({"command": ["get_property", "time-pos"], "request_id": 1}) + "\n"
        s.sendall(cmd.encode())
        data = b""
        while b"\n" not in data:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        s.close()
        raw = data.decode("utf-8", errors="ignore").split("\n", 1)[0]
        result = _json.loads(raw)
        elapsed = result.get("data") or 0

        s2 = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s2.settimeout(2)
        s2.connect(pipe_path)
        cmd2 = _json.dumps({"command": ["get_property", "duration"], "request_id": 2}) + "\n"
        s2.sendall(cmd2.encode())
        data2 = b""
        while b"\n" not in data2:
            chunk = s2.recv(4096)
            if not chunk:
                break
            data2 += chunk
        s2.close()
        raw2 = data2.decode("utf-8", errors="ignore").split("\n", 1)[0]
        result2 = _json.loads(raw2)
        duration = result2.get("data") or 0
        return float(elapsed), float(duration)
    except Exception:
        return 0, 0


def _get_mpv_time_windows(pipe_path: str) -> tuple:
    """Query mpv for current time via TCP localhost:18743."""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect(("127.0.0.1", 18743))
        cmd = _json.dumps({"command": ["get_property", "time-pos"], "request_id": 1}) + "\n"
        s.sendall(cmd.encode())
        data = b""
        while b"\n" not in data:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
        s.close()
        raw = data.decode("utf-8", errors="ignore").split("\n", 1)[0]
        result = _json.loads(raw)
        elapsed = float(result.get("data") or 0)

        s2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s2.settimeout(1)
        s2.connect(("127.0.0.1", 18743))
        cmd2 = _json.dumps({"command": ["get_property", "duration"], "request_id": 2}) + "\n"
        s2.sendall(cmd2.encode())
        data2 = b""
        while b"\n" not in data2:
            chunk = s2.recv(4096)
            if not chunk:
                break
            data2 += chunk
        s2.close()
        raw2 = data2.decode("utf-8", errors="ignore").split("\n", 1)[0]
        result2 = _json.loads(raw2)
        duration = float(result2.get("data") or 0)
        return elapsed, duration
    except Exception:
        return 0, 0


def search_youtube(query, limit=5):
    if not YT_DLP_CMD:
        return []
    for attempt in range(2):
        cmd = YT_DLP_CMD + ["--flat-playlist", "--dump-single-json", f"ytsearch{limit}:{query}"]
        result = _run(cmd, timeout=40)
        if result.returncode == 0 and result.stdout.strip():
            break
        if "429" in result.stdout or "Too Many Requests" in result.stderr:
            time.sleep(2 ** attempt)
            continue
        break

    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        payload = _json.loads(result.stdout)
    except Exception:
        return []

    tracks = []
    for entry in payload.get("entries", []) or []:
        if entry.get("ie_key") != "Youtube":
            continue
        video_id = entry.get("id")
        if not video_id:
            continue
        title = entry.get("title") or ""
        if not title.strip():
            continue
        url = entry.get("url")
        if not url:
            url = f"https://www.youtube.com/watch?v={video_id}"
        tracks.append({
            "id": video_id,
            "title": title,
            "artist": re.sub(r'\s*\([^)]*\)', '', entry.get("channel") or entry.get("uploader") or "").strip(),
            "source": "youtube",
            "page_url": url,
            "thumbnail": (entry.get("thumbnails") or [{}])[-1].get("url"),
        })
    return tracks[:limit]


def resolve_url(url):
    if not YT_DLP_CMD:
        raise RuntimeError("yt-dlp not available")
    for attempt in range(3):
        cmd = YT_DLP_CMD + ["--js-runtimes", "node", "-f", "bestaudio/best", "--no-playlist", "-J", url]
        result = _run(cmd, timeout=45)
        if result.returncode == 0 and result.stdout.strip():
            break
        if "429" in result.stderr or "Too Many Requests" in result.stderr:
            time.sleep(2 ** attempt)
            continue
        break

    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"resolve failed: {result.stderr}")
    try:
        payload = _json.loads(result.stdout)
    except Exception:
        raise RuntimeError("invalid JSON")
    formats = payload.get("formats") or []
    audio = [f for f in formats if f.get("url") and f.get("vcodec") == "none"]
    stream_url = (audio[-1] if audio else {}).get("url") or payload.get("url")
    if not stream_url:
        raise RuntimeError("no playable stream")
    return stream_url, payload.get("title"), payload.get("duration")


def play(query, text_mode=True):
    if not MPV_PATH or not YT_DLP_CMD:
        print("ERROR: missing dependencies (mpv/yt-dlp)")
        return 1

    print("搜索中...")
    tracks = search_youtube(query, limit=5)
    if not tracks:
        print(f"未找到与「{query}」相关的歌曲")
        return 1

    track = tracks[0]
    title = track["title"]
    artist = track["artist"]

    print(f"正在解析：{artist} - {title}")

    try:
        stream_url, yt_title, duration = resolve_url(track["page_url"])
    except Exception as e:
        print(f"解析失败：{e}")
        return 1

    full_title = f"{artist} - {title}" if artist else title

    startupinfo = None
    if IS_WINDOWS:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
        subprocess.run(["taskkill", "/F", "/IM", "mpv.exe"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        subprocess.run(["pkill", "-f", "mpv"], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    pipe_path = "127.0.0.1:18743" if IS_WINDOWS else f"/tmp/climusic-mpv-{os.getpid()}.sock"

    proc = subprocess.Popen(
        [MPV_PATH, "--no-video", "--force-window=no", "--keep-open=no",
         f"--input-ipc-server={pipe_path}", "--really-quiet", stream_url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        startupinfo=startupinfo,
        creationflags=0x08000000 if IS_WINDOWS else 0,
    )

    # Wait for mpv IPC server to be ready
    time.sleep(0.8)

    # Box-style UI
    current_elapsed = 0.0
    current_duration = float(duration) if duration else 0.0
    print()
    print("+" + "-" * 54 + "+")
    print(f"|  [>] 正在播放: {full_title[:46]}")
    print("+" + "-" * 54 + "+")
    print(f"|  时长: {_format_time(current_duration)}")
    print(f"|  进度: ")
    print(f"|  来源: {track['page_url']}")
    print("+" + "-" * 54 + "+")

    last_update = 0
    box_line_count = 7  # number of lines in the box above

    def _redraw_box(elapsed, dur, url):
        pct = f"{int(elapsed / dur * 100)}%" if dur > 0 else "0%"
        bar = _progress_bar(elapsed, dur, 48)
        elapsed_str = _format_time(elapsed)
        dur_str = _format_time(dur)
        sys.stdout.write(f"\x1b[{box_line_count}A")
        sys.stdout.write("\x1b[2K")
        print("+" + "-" * 54 + "+")
        print(f"|  [>] 正在播放: {full_title[:46]}")
        print("+" + "-" * 54 + "+")
        print(f"|  时长: {dur_str}")
        print(f"|  进度: {bar}  {elapsed_str}/{dur_str}  {pct}")
        print(f"|  来源: {url[:48]}")
        print("+" + "-" * 54 + "+")
        sys.stdout.flush()

    try:
        while True:
            time.sleep(1)
            if proc.poll() is not None:
                break

            now = time.time()
            if now - last_update >= 0.5:
                last_update = now
                elapsed, dur = _get_mpv_time_pos(pipe_path)
                if dur > 0:
                    current_duration = dur
                if elapsed > 0:
                    current_elapsed = elapsed

                _redraw_box(current_elapsed, current_duration, track['page_url'])

    except KeyboardInterrupt:
        proc.terminate()
        print("\n\n已停止播放")
        return 0

    print(f"  播放结束")
    return 0


def main():
    init()

    parser = argparse.ArgumentParser(prog="climusic", description="在线音乐播放器")
    parser.add_argument("command", choices=["play", "search", "stop", "status", "hot"])
    parser.add_argument("query", nargs="*", help="搜索关键词或歌曲名")
    parser.add_argument("--text", action="store_true", help="文本输出模式")

    args = parser.parse_args()

    if args.command == "play":
        if not args.query:
            print("用法: climusic play <歌曲名>")
            return 1
        return play(" ".join(args.query), text_mode=args.text)

    if args.command == "search":
        if not args.query:
            print("用法: climusic search <关键词>")
            return 1
        tracks = search_youtube(" ".join(args.query), limit=10)
        if not tracks:
            print("未找到结果")
            return 1
        print()
        print("━" * 50)
        for i, t in enumerate(tracks, 1):
            print(f"  {i:2d}. {t['artist']} - {t['title']}")
        print("━" * 50)
        print(f"  共 {len(tracks)} 首")
        print()
        print(f"  播放示例: climusic play \"{tracks[0]['artist']} {tracks[0]['title']}\"")
        return 0

    if args.command == "stop":
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/F", "/IM", "mpv.exe"], check=False)
        else:
            subprocess.run(["pkill", "-f", "mpv"], check=False)
        print("已停止所有播放")
        return 0

    if args.command == "status":
        if IS_WINDOWS:
            result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq mpv.exe", "/NH"], capture_output=True, text=True)
            print("状态：播放中" if "mpv.exe" in result.stdout else "状态：空闲")
        else:
            result = subprocess.run(["pgrep", "-f", "mpv"], capture_output=True)
            print("状态：播放中" if result.returncode == 0 else "状态：空闲")
        return 0

    if args.command == "hot":
        print()
        print("🔥 热门华语歌曲")
        print()
        tracks = search_youtube("热门华语歌曲 2024", limit=10)
        print("━" * 50)
        for i, t in enumerate(tracks, 1):
            print(f"  {i:2d}. {t['artist']} - {t['title']}")
        print("━" * 50)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())