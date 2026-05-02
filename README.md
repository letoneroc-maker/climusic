# climusic

Windows 原生 CLI 音乐播放器 —— 通过关键词搜索在线播放 YouTube 音乐。

## 功能特性

- 🔍 **在线搜索** - 通过关键词从 YouTube 搜索歌曲
- ▶️ **在线播放** - 直接解析并播放，无下载等待
- 📊 **动态进度条** - 实时显示播放进度、时长、百分比
- 🎨 **方框 UI** - ASCII 方框布局，显示歌曲名、歌手、进度、来源链接
- 🔇 **自动切歌** - 播放新歌曲时自动停止旧歌曲，不重不漏
- 🛑 **停止命令** - 一键终止所有 mpv 进程

## 安装

### 前置要求

1. **Python 3.9+**
   ```bash
   python --version
   ```

2. **mpv**（必须）
   - 下载地址：https://mpv.io/installation/
   - 安装后将 `mpv.exe` 所在目录加入系统 PATH
   - 或将 mpv 安装到默认路径 `C:\Program Files\mpv\mpv.exe`

3. **yt-dlp**（自动安装或手动）
   ```bash
   pip install yt-dlp
   ```

### 安装 climusic

```bash
cd Desktop\music-agent-win
pip install -e .
```

## 命令用法

```bash
# 播放歌曲（直接搜索 + 在线播放）
climusic play 周杰伦 晴天

# 搜索歌曲（查看搜索结果）
climusic search 周杰伦

# 播放热门华语歌曲
climusic hot

# 停止播放
climusic stop

# 查看播放状态
climusic status
```

## UI 界面

播放时显示方框布局：

```
+------------------------------------------------------+
|  [>] 正在播放: 周杰伦 Jay Chou - 晴天 Sunny Day...
+------------------------------------------------------+
|  时长: 05:18
|  进度: [################--------]  02:30/05:18  48%
|  来源: https://www.youtube.com/watch?v=DYptgVkVLQ
+------------------------------------------------------+
```

- 进度条每 0.5 秒动态更新
- 显示已播放时间 / 总时长 / 百分比
- 显示歌曲来源链接

## 工作原理

```
用户输入 "climusic play 晴天"
    │
    ▼
// 搜索阶段
yt-dlp --flat-playlist --dump-single-json "ytsearch5:晴天"
    │
    ▼
// 解析阶段
yt-dlp -f bestaudio --no-playlist -J <video_url>
    │
    ▼
// 播放阶段
mpv --no-video --input-ipc-server=127.0.0.1:18743 <stream_url>
    │
    ▼
// IPC 控制（每 0.5 秒）
TCP localhost:18743 → get_property time-pos / duration
    │
    ▼
// UI 重绘
ASCII 方框 + 动态进度条
```

## 依赖说明

| 组件 | 用途 | 安装方式 |
|------|------|----------|
| mpv | 媒体播放器 | 手动安装 https://mpv.io/ |
| yt-dlp | 视频解析 + 搜索 | `pip install yt-dlp` |
| pywin32 | Windows IPC | `pip install pywin32`（自动依赖）|

## 技术细节

- **IPC 通信**：Windows 使用 TCP `localhost:18743`，Unix 使用 Unix Domain Socket
- **播放控制**：通过 mpv IPC 的 `get_property time-pos` 和 `get_property duration` 获取播放时间
- **防重播**：每次播放新歌曲前，先 `taskkill /F /IM mpv.exe` 终止旧进程
- **编码处理**：Windows 端配置 `sys.stdout.reconfigure(encoding="utf-8")` 防止中文乱码

## 项目结构

```
music-agent-win/
├── climusic_pkg/
│   ├── __init__.py      # 主程序（搜索、解析、播放、UI）
│   └── __main__.py      # 入口点
├── pyproject.toml       # 包配置
└── README.md
```

## 常见问题

**Q: 提示 "mpv not found"**
A: 确保 mpv 已安装并可在 PATH 中找到，或安装在 `C:\Program Files\mpv\mpv.exe`

**Q: 提示 "yt-dlp not found"**
A: 运行 `pip install yt-dlp`

**Q: 进度条一直是 00:00**
A: 检查防火墙是否阻止了 `127.0.0.1:18743` 的 TCP 连接

**Q: 两首歌曲同时播放**
A: 当前版本已修复，每次播放会自动终止旧 mpv 进程

## 开源协议

MIT License
