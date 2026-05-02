from __future__ import annotations

from shared.lang import display_lang as _display_lang
from shared.source import display_source as _display_source


def _format_status_snapshot(response: dict) -> str:
    if response.get("state") == "idle":
        return (
            f"当前没有正在播放的音乐"
            f"｜语种偏好：{display_lang(response.get('lang', 'mandarin'))}"
            f"｜音源偏好：{display_source(response.get('source_preference', 'youtube'))}"
        )
    if response.get("state") == "error":
        return response.get("message") or "音乐服务异常"
    track = response.get("track") or {}
    next_track = response.get("next_track") or {}
    state_map = {"playing": "播放中", "paused": "已暂停"}
    queue_index = response.get("queue_index") or "-"
    queue_total = response.get("queue_total") or "-"
    muted = "是" if response.get("muted") else "否"
    return (
        f"当前播放：{track.get('artist', '未知歌手')} - {track.get('title', '未知歌曲')}"
        f"｜下一首：{next_track.get('artist', '未知歌手')} - {next_track.get('title', '未知歌曲')}"
        f"｜状态：{state_map.get(response.get('state'), response.get('state'))}"
        f"｜音量：{response.get('volume', 0)}"
        f"｜静音：{muted}"
        f"｜队列：{queue_index}/{queue_total}"
        f"｜模式：循环"
        f"｜来源：{track.get('source', 'unknown')}"
        f"｜热榜语种：{display_lang(response.get('lang', 'mandarin'))}"
        f"｜音源偏好：{display_source(response.get('source_preference', 'youtube'))}"
    )


def _append_status(message: str, response: dict) -> str:
    snapshot = response.get("status_snapshot")
    if not snapshot:
        return message
    return f"{message}\n{_format_status_snapshot(snapshot)}"


def format_response(response: dict) -> str:
    action = response.get("action")
    if action == "doctor":
        lines = ["环境检查结果："]
        for item in response.get("checks", []):
            prefix = "OK" if item.get("ok") else "FAIL"
            lines.append(f"{prefix} {item.get('message')}")
        for note in response.get("fix_notes", []):
            lines.append(f"INFO {note}")
        return "\n".join(lines)
    if not response.get("ok"):
        return response.get("message") or "请求失败"
    if action == "play":
        track = response.get("track") or {}
        next_track = response.get("next_track") or {}
        return _append_status(
            (
            f"已开始播放\"{response.get('query', '')}\"相关队列，共 {response.get('queue_total', 0)} 首"
            f"，当前：{track.get('artist', '未知歌手')} - {track.get('title', '未知歌曲')}"
            f"，下一首：{next_track.get('artist', '未知歌手')} - {next_track.get('title', '未知歌曲')}"
            ),
            response,
        )
    if action == "hot":
        track = response.get("track") or {}
        next_track = response.get("next_track") or {}
        lang = response.get("lang")
        return _append_status(
            (
            f"已开始播放{_display_lang(lang)}热门歌曲队列，共 {response.get('queue_total', 0)} 首"
            f"，当前：{track.get('artist', '未知歌手')} - {track.get('title', '未知歌曲')}"
            f"，下一首：{next_track.get('artist', '未知歌手')} - {next_track.get('title', '未知歌曲')}"
            ),
            response,
        )
    if action == "pause":
        return _append_status("已暂停播放", response)
    if action == "resume":
        track = response.get("track") or {}
        return _append_status(f"已继续播放：{track.get('artist', '未知歌手')} - {track.get('title', '未知歌曲')}", response)
    if action == "next":
        track = response.get("track") or {}
        return _append_status(f"已切换到下一首：{track.get('artist', '未知歌手')} - {track.get('title', '未知歌曲')}", response)
    if action == "prev":
        track = response.get("track") or {}
        return _append_status(f"已切换到上一首：{track.get('artist', '未知歌手')} - {track.get('title', '未知歌曲')}", response)
    if action == "stop":
        return _append_status("已停止播放", response)
    if action == "status":
        return _format_status_snapshot(response)
    if action == "volume":
        return _append_status(f"音量已设置为 {response.get('volume', 0)}", response)
    if action == "mute":
        return _append_status("已静音", response)
    if action == "unmute":
        return _append_status(f"已取消静音，当前音量：{response.get('volume', 0)}", response)
    if action == "lang":
        return _append_status(f"当前热榜语种：{response.get('display')}", response)
    if action == "source":
        return _append_status(f"当前默认音源：{response.get('display')}", response)
    return "操作成功"