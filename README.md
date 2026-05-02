# music-agent-win

Windows-native background music agent for CLI. Play music from YouTube, Bilibili, SoundCloud via keyword search or KKBOX hot charts.

## Install

```bash
cd Desktop\music-agent-win
pip install -e .
```

## Requirements

- Python 3.9+
- [mpv](https://mpv.io/) (download and add to PATH)
- yt-dlp (auto-installed or `pip install yt-dlp`)

## Commands

```bash
musicctl --text play "周杰伦 稻香"
musicctl --text hot english
musicctl --text pause
musicctl --text resume
musicctl --text stop
musicctl --text status
musicctl --text volume up
musicctl --text volume 60
musicctl --text mute
musicctl --text doctor
musicctl --text doctor --fix
musicctl --text source youtube
musicctl --text lang 粤语
```

## Architecture

```
musicctl (CLI)
  -> musicd.daemon (Windows named pipe server)
    -> player_mpv (mpv IPC)
    -> resolver (yt-dlp + search adapters)
      -> YouTubeAdapter / BilibiliAdapter / SoundCloudAdapter
    -> hotlist_kkbox (KKBOX hot chart)
```

## License

MIT