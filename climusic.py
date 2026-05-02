#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

IS_WINDOWS = os.name == "nt"

# Direct synchronous player - no daemon needed
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

    ytdlp = shutil.which("yt-dlp")
    if ytdlp:
        YT_DLP_CMD = [ytdlp]
    else:
        scripts = Path(sys.executable).parent / "Scripts" / "yt-dlp.exe"
        if scripts.exists():
            YT_DLP_CMD = [str(scripts)]
        else:
            result = subprocess.run(
                [sys.executable, "-m", "yt_dlp", "--version"],
                capture_output=True, timeout=10, check=False
            )
            if result.returncode == 0:
                YT_DLP_CMD = [sys.executable, "-m", "yt_dlp"]

    if not MPV_PATH:
        print("ERROR: mpv not found. Install mpv from https://mpv.io/installation/", file=sys.stderr)
    if not YT_DLP_CMD:
        print("ERROR: yt-dlp not found. Run: pip install yt-dlp", file=sys.stderr)


def _run(cmd, timeout=45):
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    return result


def search_youtube(query, limit=5):
    if not YT_DLP_CMD:
        return []
    cmd = YT_DLP_CMD + ["--flat-playlist", "--dump-single-json", f"ytsearch{limit}:{query}"]
    result = _run(cmd, timeout=40)
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        import json
        payload = json.loads(result.stdout)
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
    cmd = YT_DLP_CMD + ["-f", "bestaudio/best", "--no-playlist", "-J", url]
    result = _run(cmd, timeout=45)
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError(f"resolve failed: {result.stderr}")
    try:
        import json
        payload = json.loads(result.stdout)
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

    print("搜索中...") if text_mode else None

    tracks = search_youtube(query, limit=5)
    if not tracks:
        msg = f"未找到与「{query}」相关的歌曲"
        print(msg) if text_mode else print(json.dumps({"ok": False, "message": msg}))
        return 1

    track = tracks[0]
    title = track["title"]
    artist = track["artist"]

    print(f"正在解析：{artist} - {title}") if text_mode else None

    try:
        stream_url, yt_title, duration = resolve_url(track["page_url"])
    except Exception as e:
        msg = f"解析失败：{e}"
        print(msg) if text_mode else print(json.dumps({"ok": False, "message": msg}))
        return 1

    full_title = f"{artist} - {title}" if artist else title

    # Start mpv with no window, streaming audio
    startupinfo = None
    if IS_WINDOWS:
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE

    pipe_path = r"\\.\pipe\climusic-mpv" if IS_WINDOWS else f"/tmp/climusic-mpv-{os.getpid()}.sock"
    try:
        Path(pipe_path).unlink(missing_ok=True)
    except Exception:
        pass

    proc = subprocess.Popen(
        [MPV_PATH, "--no-video", "--force-window=no", "--keep-open=no",
         f"--input-ipc-server={pipe_path}", "--really-quiet",
         stream_url],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        startupinfo=startupinfo,
        creationflags=0x08000000 if IS_WINDOWS else 0,
    )

    time.sleep(1)

    if text_mode:
        print(f"正在播放：{full_title}")
        print("---")
        print(f"  来源：YouTube")
        print(f"  时长：{_format_time(duration)}" if duration else "")
        print(f"  链接：{track['page_url']}")
        print("---")
        print("按 Ctrl+C 停止播放")

    try:
        while True:
            time.sleep(2)
            if proc.poll() is not None:
                break
    except KeyboardInterrupt:
        proc.terminate()
        print("\n已停止播放")
        return 0

    return 0


def _format_time(seconds):
    if not seconds:
        return "--:--"
    s = max(0, int(seconds))
    return f"{s // 60:02d}:{s % 60:02d}"


import re, json


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
        q = " ".join(args.query)
        return play(q, text_mode=args.text)

    if args.command == "search":
        if not args.query:
            print("用法: climusic search <关键词>")
            return 1
        q = " ".join(args.query)
        tracks = search_youtube(q, limit=10)
        if not tracks:
            print("未找到结果")
            return 1
        for i, t in enumerate(tracks, 1):
            print(f"{i}. {t['artist']} - {t['title']}")
        return 0

    if args.command == "stop":
        # Kill all mpv processes
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/F", "/IM", "mpv.exe"], check=False)
        else:
            subprocess.run(["pkill", "-f", "mpv"], check=False)
        print("已停止所有播放")
        return 0

    if args.command == "status":
        if IS_WINDOWS:
            result = subprocess.run(["tasklist", "/FI", "IMAGENAME eq mpv.exe", "/NH"], capture_output=True, text=True)
            if "mpv.exe" in result.stdout:
                print("状态：播放中")
            else:
                print("状态：空闲")
        else:
            result = subprocess.run(["pgrep", "-f", "mpv"], capture_output=True)
            print("状态：播放中" if result.returncode == 0 else "状态：空闲")
        return 0

    if args.command == "hot":
        print("热门歌曲（华语）")
        tracks = search_youtube("热门华语歌曲 2024", limit=10)
        for i, t in enumerate(tracks, 1):
            print(f"{i}. {t['artist']} - {t['title']}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())