from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import atexit
import signal
from pathlib import Path
from typing import Optional

IS_WINDOWS = os.name == "nt"

from musicd.daemon import daemonize
from shared.ipc import send_request
from musicctl.formatter import format_response
from shared.environment import (
    EnvironmentIssue,
    attempt_environment_fix,
    cleanup_all_runtime_processes,
    collect_environment_report,
    ensure_playback_environment,
)
from shared.runtime import SOCKET_PATH


def ensure_daemon() -> None:
    try:
        send_request({"action": "status"}, timeout=3)
        return
    except Exception:
        pass
    daemonize()


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="musicctl")
    parser.add_argument("--text", action="store_true", help="输出中文文本而不是 JSON")
    parser.add_argument("--follow", action="store_true", help="持续显示播放状态，退出时停止音乐服务")
    parser.add_argument("--detach", action="store_true", help="启动播放后立即返回，不跟随播放状态")
    subparsers = parser.add_subparsers(dest="command", required=True)

    play_parser = subparsers.add_parser("play")
    play_parser.add_argument("query")

    hot_parser = subparsers.add_parser("hot")
    hot_parser.add_argument("lang", nargs="?")

    subparsers.add_parser("pause")
    subparsers.add_parser("resume")
    subparsers.add_parser("next")
    subparsers.add_parser("prev")
    subparsers.add_parser("stop")
    subparsers.add_parser("status")
    subparsers.add_parser("mute")
    subparsers.add_parser("unmute")
    subparsers.add_parser("cleanup")

    volume_parser = subparsers.add_parser("volume")
    volume_parser.add_argument("value")

    lang_parser = subparsers.add_parser("lang")
    lang_parser.add_argument("value", nargs="?")

    source_parser = subparsers.add_parser("source")
    source_parser.add_argument("value", nargs="?")

    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.add_argument("--fix", action="store_true")

    return parser.parse_args(argv)


def build_payload(args: argparse.Namespace) -> dict:
    command = args.command
    if command == "play":
        return {"action": "play", "query": args.query}
    if command == "hot":
        return {"action": "hot", "lang": args.lang}
    if command == "pause":
        return {"action": "pause"}
    if command == "resume":
        return {"action": "resume"}
    if command == "next":
        return {"action": "next"}
    if command == "prev":
        return {"action": "prev"}
    if command == "stop":
        return {"action": "stop"}
    if command == "status":
        return {"action": "status"}
    if command == "mute":
        return {"action": "mute"}
    if command == "unmute":
        return {"action": "unmute"}
    if command == "cleanup":
        return {"action": "cleanup"}
    if command == "lang":
        return {"action": "lang", "value": args.value}
    if command == "source":
        return {"action": "source", "value": args.value}
    if command == "volume":
        if args.value == "up":
            return {"action": "volume_up"}
        if args.value == "down":
            return {"action": "volume_down"}
        return {"action": "volume", "value": int(args.value)}
    raise ValueError(f"Unsupported command: {command}")


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    if args.command == "doctor":
        report = collect_environment_report()
        fix_notes = attempt_environment_fix() if args.fix else []
        if args.fix:
            report = collect_environment_report()
        response = {"ok": report["ok"], "action": "doctor", "checks": report["checks"], "fix_notes": fix_notes}
        if args.text:
            print(format_response(response))
        else:
            print(json.dumps(response, ensure_ascii=False))
        return 0 if report["ok"] else 1
    if args.command == "cleanup":
        notes = cleanup_all_runtime_processes()
        response = {"ok": True, "action": "cleanup", "fix_notes": notes or ["当前没有可清理的 musicd/mpv 进程"]}
        if args.text:
            print(format_response(response))
        else:
            print(json.dumps(response, ensure_ascii=False))
        return 0
    if args.command in {"play", "hot"}:
        try:
            ensure_playback_environment()
        except EnvironmentIssue as exc:
            response = {"ok": False, "error_code": "DEPENDENCY_MISSING", "message": exc.message}
            if args.text:
                print(format_response(response))
            else:
                print(json.dumps(response, ensure_ascii=False))
            return 1
    ensure_daemon()
    timeout = 300 if args.command in {"play", "hot"} else 20
    follow_mode = _should_follow_playback(args)
    if args.text and follow_mode and args.command in {"play", "hot"}:
        print("正在准备播放队列，请稍候...")
    try:
        response = send_request(build_payload(args), timeout=timeout)
    except KeyboardInterrupt:
        return _handle_interrupted_startup(args)
    except TimeoutError:
        return _handle_startup_timeout(args)
    if args.text:
        print(format_response(response))
    else:
        print(json.dumps(response, ensure_ascii=False))
    if response.get("ok") and follow_mode and args.command in {"play", "hot"}:
        return follow_playback(text_mode=args.text)
    return 0 if response.get("ok") else 1


def _render_simple_message(args: argparse.Namespace, message: str) -> int:
    if args.text:
        print(message)
    else:
        print(json.dumps({"ok": False, "message": message}, ensure_ascii=False))
    return 1


def _handle_interrupted_startup(args: argparse.Namespace) -> int:
    if args.command in {"play", "hot"}:
        cleanup_all_runtime_processes()
        return _render_simple_message(args, "已取消本次播放，并清理后台音乐进程。")
    return _render_simple_message(args, "操作已取消")


def _handle_startup_timeout(args: argparse.Namespace) -> int:
    if args.command in {"play", "hot"}:
        cleanup_all_runtime_processes()
        return _render_simple_message(args, "准备播放队列超时，已自动清理后台音乐进程，请重试。")
    return _render_simple_message(args, "请求超时，请重试。")


def _format_seconds(value: Optional[float]) -> str:
    if value is None:
        return "--:--"
    total = max(0, int(value))
    return f"{total // 60:02d}:{total % 60:02d}"


def _should_follow_playback(args: argparse.Namespace) -> bool:
    if args.command not in {"play", "hot"}:
        return False
    if args.detach:
        return False
    if args.follow:
        return True
    return bool(sys.stdin.isatty() and sys.stdout.isatty())


def _print_follow_status(response: dict, previous_signature: Optional[str]) -> str:
    track = response.get("track") or {}
    next_track = response.get("next_track") or {}
    signature = "|".join([
        response.get("state", ""),
        track.get("title", ""),
        track.get("artist", ""),
        next_track.get("title", ""),
        str(response.get("queue_index")),
        str(int(response.get("elapsed_sec") or 0)),
    ])
    if signature == previous_signature:
        return previous_signature or ""
    if response.get("state") == "idle":
        print("播放已结束，当前没有活动队列。")
        return signature
    current = f"{track.get('artist', '未知歌手')} - {track.get('title', '未知歌曲')}"
    upcoming = f"{next_track.get('artist', '未知歌手')} - {next_track.get('title', '未知歌曲')}" if next_track else "无"
    progress = f"{_format_seconds(response.get('elapsed_sec'))}/{_format_seconds(response.get('duration_sec'))}"
    print(f"当前播放：{current}｜下一首：{upcoming}｜进度：{progress}｜队列：{response.get('queue_index')}/{response.get('queue_total')}")
    return signature


def follow_playback(text_mode: bool) -> int:
    stopped = {"done": False}

    def cleanup() -> None:
        if stopped["done"]:
            return
        stopped["done"] = True
        try:
            send_request({"action": "stop"}, timeout=5)
        except Exception:
            pass
        try:
            send_request({"action": "shutdown"}, timeout=5)
        except Exception:
            pass

    atexit.register(cleanup)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_args: (_ for _ in ()).throw(KeyboardInterrupt()))
    previous_signature: Optional[str] = None
    try:
        while True:
            status = send_request({"action": "status"}, timeout=5)
            previous_signature = _print_follow_status(status, previous_signature)
            time.sleep(2)
    except KeyboardInterrupt:
        print("已退出播放会话，正在关闭音乐服务。")
        cleanup()
        return 0


if __name__ == "__main__":
    raise SystemExit(main())