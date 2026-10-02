# ComfyUI-NetFast —— 管理器/依赖下载加速（按本机的实测结论）

这份东西不是通用教程，是针对 **本机**的诊断 + 修复。所有结论都来自你的日志、
ComfyUI-Manager 源码、以及现场实测。

---

## 一、先说结论：你慢的**真实原因**和那份方案集说的不完全一样

### 证据 1：DB 拉取**时好时坏**，不是"机制落后"

| 时间 | 日志文件 | 结果 |
|---|---|---|
| 今天 11:07（那次启动） | `ComfyUI\user\comfyui.prev2.log` | `Failed to perform initial fetching 'model-list.json': Cannot connect to host raw.githubusercontent.com:443 ssl:default [信号灯超时时间已到]`，4 个 json 全失败 → 退回本地缓存 |
| 今天 11:55（当前这次） | `ComfyUI\user\comfyui.log` | 全部 `default cache updated: https://raw.githubusercontent.com/...` + `FETCH DATA ... [DONE]`，包括 `https://api.comfy.org/nodes` → **成功** |

同一台机器、同一个 Manager 版本，一次失败一次成功 ⇒ **链路波动**（含代理开关/节点切换），
不是管理器本身"单线程、无断点续传"造成的。

### 证据 2：本机上真正的缺口 —— **ComfyUI 根本没走你的代理**

* FlClash 正在跑，混合端口 = **127.0.0.1:7890**（实测：`FlClashCore` pid 11436 监听该端口）。
* 但**用户级/系统级**的 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY` **全是空的**。
* `run_nvidia_gpu.bat` 是原版，没有设置任何代理或镜像：

  ```bat
  .\python_embeded\python.exe -s ComfyUI\main.py --windows-standalone-build
  ```

**关键机制**：Python（requests / aiohttp / pip / git）只认 `HTTP_PROXY` 这类**环境变量**，
**不认 Windows 系统代理**（系统代理是 WinINET 的事，只对浏览器一类程序有效）。
所以你在 FlClash 里开"系统代理"，ComfyUI 依然直连 GitHub/HF → 就是 11:07 那次超时。

> 想让所有程序都走 FlClash，要么让它开 **TUN/虚拟网卡模式**，要么给 ComfyUI 设环境变量
> —— 本包用的是后者（更可控、随时可退出）。

### 证据 3：真正看得见的慢路径 + 两个没被利用的提速点

* 你日志里的实际命令：`python.exe -m pip install git+https://github.com/facebookresearch/sam2`
  —— 依赖安装同时踩 **GitHub + PyPI 官方源**两个慢点。
* **`uv` 已经装在这套 ComfyUI 里了**（实测 `uv 0.12.13`，`python -m uv` 可用），
  但你的 `config.ini` 里 `use_uv = False` —— 这是"装依赖慢"最直接的提速点，方案集完全没提。
* 默认下载器确实弱（读源码确认）：`glob/manager_downloader.py:57` 调
  `torchvision.datasets.utils.download_url`，单连接、**无断点续传**（`download_url_to_file` 直接 `"wb"` 覆盖写）。

---

## 二、那份方案集：逐条核对（✅成立 / ❌错误 / ⚠️有条件）

| 说法 | 判定 | 依据（都在本机核实过） |
|---|---|---|
| 国内访问 GitHub/HF 慢是主因 | ✅ | 你 11:07 的日志 |
| 默认单线程、无断点续传 | ✅ | `manager_downloader.py:57` + torchvision 源码 |
| `GITHUB_ENDPOINT` | ✅ 存在，但**只作用于 git clone/pull** | `glob/git_utils.py:5,83-84`；**不影响** json 数据库拉取（那是 `channel_url`），**也不影响 `pip install git+...`**（pip 自己调 git） |
| `HF_ENDPOINT` | ✅ 存在，且**同时**作用于 `huggingface_hub`（实测 `constants.ENDPOINT` 变成 `hf-mirror.com`） | `manager_downloader.py:12,51-53` |
| ↳ 但它不是万能的 | ⚠️ `download_repo_in_bytes()` 里有一处**硬编码** `https://huggingface.co/{repo}/resolve/main/...`（`:152`）不会被替换 → 整个仓库下载仍走原站。这是上游疏漏 | 源码 |
| `network_mode = public/private/offline` | ✅ | `manager_core.py:1875`、README:277 |
| 换 pip 源 | ✅ 有效（但见下） | 实测 |
| **aria2 在 `config.ini` 里配** | ❌ **错**。本版用环境变量 `COMFYUI_MANAGER_ARIA2_SERVER` + `COMFYUI_MANAGER_ARIA2_SECRET`，另需 `pip install aria2p`；`config.ini` 里**没有** aria2 项 | `manager_downloader.py:11-22`、`docs/en/use_aria2.md` |
| "检测到 aria2 就自动切换" | ❌ 与源码不符：**只有设了那个环境变量才会启用** | `manager_downloader.py:15,54` |
| `mirror.ghproxy.com`（Manager README 的示例） | ⚠️ 从本机测：HEAD 直接连接失败；`ghfast.top` / `gh-proxy.com` 返回 200。**但 git clone 要走 CONNECT 隧道，被我这边的沙箱策略拒了，所以我无法替你验证 clone** —— 我的网络受策略代理限制，不代表你的网络 | 实测 |
| `git config --global url."https://kkgithub.com/".insteadOf ...` | ❌ **不要做**。这会把**本机上所有程序**对 `github.com` 的请求都改写（含私有库鉴权、其它软件更新），而 kkgithub 不是官方镜像，随时可能失效。用 `GITHUB_ENDPOINT` 即可，作用范围只限 Manager | 机制分析 |
| 没提到：`uv` | ⚠️ 已装好却没用，是本次收益最大的一项 | 实测 |

---

## 三、我实际改了什么（3 处，全部限定在**这套 ComfyUI 内**，且可一键回滚）

| # | 位置 | 改动 | 作用范围 |
|---|---|---|---|
| 1 | `python_embeded\pip.ini` | 清华 PyPI 镜像 + `timeout = 30` | **只影响这套 ComfyUI 的 Python**（pip 的"site"级配置；`pip config debug` 已确认被加载）。没有动你的用户级/全局 pip 配置 |
| 2 | `run_nvidia_gpu_fast.bat`（**新文件**） | 启动前按情况设环境变量；**原版启动器一字未动** | 只有用这个 .bat 启动才生效 |
| 3 | `ComfyUI\user\__manager\config.ini` | `use_uv = False` → `True` | 备份在同目录 `config.ini.bak-20260915-121010` |

### 新启动器的逻辑（已实测两个分支）

```bat
有 127.0.0.1:7890 在监听  ->  设 HTTP_PROXY/HTTPS_PROXY/ALL_PROXY(含小写)
                              Python / git / pip 全部走 FlClash，不用镜像
没有监听                  ->  设 GITHUB_ENDPOINT=https://ghfast.top/https://github.com
                              只对 git clone 走镜像
两种情况都设:
  HF_ENDPOINT    = https://hf-mirror.com          (HF 模型下载)
  PIP_INDEX_URL / UV_INDEX_URL = 清华 PyPI 镜像    (依赖安装)
  NO_PROXY       = 127.0.0.1,localhost,::1        (localhost 永不走代理)
```

实测输出：

```
[netfast] proxy ON  -> 127.0.0.1:7890 (python/git/pip all use it)
[netfast] proxy OFF -> git clone via https://ghfast.top/https://github.com
```

> 端口不是 7890 时不用改文件，启动前 `set PROXY_PORT=你的端口` 即可；
> 镜像也可用 `set GH_MIRROR=...` 覆盖。

### 已做的确定性验证（不依赖我的网络）

用启动器同样的环境变量，直接加载 Manager 的模块看它读到什么：

```
GITHUB_ENDPOINT as the Manager reads it : https://ghfast.top/https://github.com
HF_ENDPOINT as the Manager reads it     : https://hf-mirror.com
git clone url:  https://github.com/...  ->  https://ghfast.top/https://github.com/...
（且镜像前缀的 URL 仍被正确识别为 github 仓库: ltdrdata/ComfyUI-Manager）
HF model url :  https://huggingface.co/... -> https://hf-mirror.com/...
pip 站点配置 :  python_embeded\pip.ini 已被 pip 加载（pip config debug 确认）
```

---

## 四、怎么用

1. **以后用 `run_nvidia_gpu_fast.bat` 启动**（可以把快捷方式指向它）。
   用原版启动器也能享受 pip.ini + `use_uv`，但拿不到代理/镜像环境变量。
2. 想确认它到底设了什么（不会真的启动 ComfyUI）：

   ```bat
   set COMFY_NETFAST_DRYRUN=1
   run_nvidia_gpu_fast.bat
   ```
3. 回滚：

   ```powershell
   powershell -ExecutionPolicy Bypass -File C:\ComfyUI-NetFast\install.ps1 -Restore
   ```
   （删除新 .bat 和 pip.ini，并从备份恢复 config.ini）

---

## 五、留给你的可选增强（我没擅自做）

### A. aria2 多线程 + 断点续传（只加速**模型下载**）

```bat
winget install aria2.aria2            :: 或 choco install aria2 / 手工解压加 PATH
python_embeded\python.exe -m pip install aria2p
aria2c --enable-rpc --rpc-listen-all --rpc-secret=改成你的密码 --dir=ComfyUI\models
:: 然后在这两个环境变量存在的情况下启动 ComfyUI（可加进 run_nvidia_gpu_fast.bat）
set COMFYUI_MANAGER_ARIA2_SERVER=http://127.0.0.1:6800
set COMFYUI_MANAGER_ARIA2_SECRET=改成你的密码
```

注意：aria2 需要**常驻一个进程**，且只管 Manager 的模型下载（`download_url`），
插件安装（git/pip）不受益。你要是更想要"少一个常驻服务"，可以不做。

### B. 让 uv 也走镜像（不限于用我的启动器时）

`uv` **不读** `pip.ini`。若有需要，可写用户级 uv 配置（影响本机上所有 uv 调用）：

```toml
# %APPDATA%\uv\uv.toml
[[index]]
url = "https://pypi.tuna.tsinghua.edu.cn/simple"
default = true
```

或者只依赖启动器里的 `UV_INDEX_URL`（我已加上）。

### C. 数据库拉取超时时换 `channel_url`

管理器内置的 channel 列表里**没有国内镜像**（`channels.list.template` 六个全是
`raw.githubusercontent.com`），所以只能手工填一个能提供同结构 json 的地址
（管理器界面 → Channel 下拉可改）。当前 `db_mode = cache` 已经能在拉取失败时用本地缓存，
所以**我没有动它** —— 填一个来路不明的地址风险更大。

---

## 六、想自己复核的话

```powershell
# 1) GitHub 镜像能不能真的 clone（这是唯一我无法替你验证的一条）
git ls-remote https://ghfast.top/https://github.com/ltdrdata/ComfyUI-Manager
git ls-remote https://gh-proxy.com/https://github.com/ltdrdata/ComfyUI-Manager

# 2) pip 走的是哪个源
C:\ComfyUI_windows_portable\python_embeded\python.exe -m pip config list

# 3) FlClash 的端口
Get-NetTCPConnection -State Listen | Where-Object OwningProcess -in (Get-Process FlClashCore).Id

# 4) 启动后确认 uv 生效（装依赖时才会打印）
#    日志里出现：[ComfyUI-Manager] Using `uv` as Python module for pip operations.
```

## 七、一句提醒

我这边所有 shell 命令都走 DSH 的策略代理（`127.0.0.1` 的另一个端口），
所以"哪个镜像更快""clone 能不能成功"这类**真实网络速度问题，只能以本机上的实测为准**；
本包做的是把**配置层面的坑**全部补上（代理没生效、uv 没用上、pip 源是官方的、
启动器没带镜像），并给出可回滚的改动。
