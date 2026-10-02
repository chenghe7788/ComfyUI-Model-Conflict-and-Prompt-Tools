# ComfyUI-NetFast

> 让 ComfyUI 便携版的 pip / git / HuggingFace / Manager 下载走镜像与代理。
> *Mirror + proxy environment for the ComfyUI portable launcher. Not a custom node.*

| | |
|---|---|
| 类型 | 启动器 / 环境改造（**不是** custom_nodes 插件） |
| 影响范围 | 只在这套 ComfyUI 里，不动系统环境变量、不动系统代理 |
| 一键回滚 | `install.ps1 -Restore` |

---

## 它改哪三处

| 位置 | 改动 |
|---|---|
| `python_embeded\pip.ini` | 给这个内嵌 Python 单独指定 PyPI 镜像（pip 的 `site` 级配置，只影响这份 python.exe） |
| `run_nvidia_gpu_fast.bat` | **新增**一个启动器，先设好环境变量再 `call` 原本的 `run_nvidia_gpu.bat` —— 原文件一个字不改 |
| `ComfyUI\user\__manager\config.ini` | `use_uv = True`（改前先备份成 `config.ini.bak-<时间戳>`） |

## 为什么是"环境变量"而不是"系统代理"

Python 侧的 `requests` / `aiohttp` / `pip` / `git` **只认 `HTTP_PROXY` 这类环境变量**，
**不认 Windows 系统代理** —— 系统代理是 WinINET 的事，只对浏览器一类程序有效。
所以在代理软件里勾了"系统代理"，ComfyUI 依然直连 GitHub / HuggingFace，然后超时。
这个启动器干的就是把环境变量补上。

新启动器的逻辑：

```
1. 设镜像：HF_ENDPOINT / PIP_INDEX_URL / UV_INDEX_URL
2. 设 NO_PROXY（别让 127.0.0.1 的调用绕进代理）
3. 探测本机 127.0.0.1:7890 有没有在监听：
     有  -> 打开 HTTP_PROXY / HTTPS_PROXY / ALL_PROXY，走代理
     没有 -> 不设代理，改用 GITHUB_ENDPOINT=ghfast.top 前缀（只作用于 Manager 的 git clone）
4. 打印一行当前选择，然后 call run_nvidia_gpu.bat
```

端口和镜像都可以不改文件、用环境变量覆盖：

```bat
set PROXY_PORT=7897
set GH_MIRROR=https://ghproxy.net/https://github.com
run_nvidia_gpu_fast.bat
```

## 安装 / 回滚

```powershell
# 先看现在是什么状态、会改什么（不写盘）
powershell -ExecutionPolicy Bypass -File install.ps1 -DryRun

powershell -ExecutionPolicy Bypass -File install.ps1
powershell -ExecutionPolicy Bypass -File install.ps1 -ComfyRoot "D:\ComfyUI_windows_portable"

# 回滚：删掉新增的 pip.ini / 启动器，并用最近的备份还原 config.ini
powershell -ExecutionPolicy Bypass -File install.ps1 -Restore
```

**什么都不启动就能验证启动器逻辑**：

```bat
set COMFY_NETFAST_DRYRUN=1
run_nvidia_gpu_fast.bat
```

它只会把环境变量和选择结果打印出来，然后退出。

## 注意

* `uv` **不读** `pip.ini`，它认 `UV_INDEX_URL`（启动器里已经设了）。
* 不要用 `git config --global url."https://某镜像/".insteadOf` 这类全局改写 —— 那会把机器上
  **所有**程序对 github.com 的请求都改掉（含私有库鉴权、其它软件更新），而镜像不是官方源，随时可能失效。
  用 `GITHUB_ENDPOINT`，作用范围只限 ComfyUI-Manager。
* 镜像可用性随时会变，**速度类问题只能以本机实测为准**；
  [`docs/REPORT.md`](docs/REPORT.md) 里是当初的实测过程与逐条核对结论（针对某一台机器、某一个时间点）。
* ComfyUI-Manager 默认下载器是单连接、无断点续传（`manager_downloader.py` 里调
  `torchvision.datasets.utils.download_url`），大文件慢是它本身的问题，启动器只能改善"连不上"。
