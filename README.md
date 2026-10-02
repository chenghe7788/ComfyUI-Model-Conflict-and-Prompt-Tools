# ComfyUI-Model-Conflict-and-Prompt-Tools

**看清你的模型，配对你的提示词** —— 模型缩略图选择 · 架构冲突红蓝标记 · 按底模架构自动切提示词词库 · 词嵌入兼容标记 · 预览图自动落盘

> 由 **DeepSeek Harness** 与使用者协作开发、在真实出图环境里跑过的一批 **ComfyUI 自定义插件**。
> 三个插件 + 两个环境工具，全部零第三方 Python 依赖，装完即用、可一键回滚。

*A small collection of ComfyUI custom nodes / frontend extensions developed with DeepSeek Harness:
an architecture-aware prompt & embedding picker, a thumbnail model picker with conflict colouring,
and a preview-saver. No third-party Python dependencies.*

---

## 里面有什么

| 目录 | 类型 | 一句话 |
|---|---|---|
| [`plugins/ComfyUI-SmartCLIP`](plugins/ComfyUI-SmartCLIP) | 节点插件 | 认出底模架构，自动切换对应的提示词词库；顺带管词嵌入（兼容徽标 + 图片选择器 + 打字补全） |
| [`plugins/ComfyUI-ModelImagePicker`](plugins/ComfyUI-ModelImagePicker) | 前端扩展 | 把模型下拉菜单换成**缩略图弹窗**，并按架构给每个模型**标红/标蓝**（冲突 / 兼容） |
| [`plugins/ComfyUI-AutoSavePreview`](plugins/ComfyUI-AutoSavePreview) | 节点插件 | 「预览图像」在写 temp 预览的同时，把整张图**另存一份到 output** |
| [`tools/ComfyUI-NetFast`](tools/ComfyUI-NetFast) | 工具（非插件） | 让 ComfyUI 的 pip / git / Manager 下载走镜像与代理的启动器改造 |
| [`tools/ComfyUI-InstallMissing`](tools/ComfyUI-InstallMissing) | 工具（非插件） | 扫描工作流，列出缺失插件与缺失 Python 依赖，并批量补装 |

三个插件的共同点：

* **不加载模型权重**。架构判定只读文件头 / `state_dict` 键指纹——不解包、不执行、不进显存，全量几十个模型也是零点几秒。
* **判不出来就不猜**。认不出架构的模型一律不着色、不标红，避免误报。
* **零第三方依赖**。只用 ComfyUI 自带的 `aiohttp` / `safetensors` / `PIL`。
* **改动可回滚**。安装脚本先快照再覆盖，卸载 = 删目录。

---

## 快速开始

```powershell
git clone https://github.com/YOUR_GITHUB_USER/ComfyUI-Model-Conflict-and-Prompt-Tools.git
cd ComfyUI-Model-Conflict-and-Prompt-Tools

# 自动探测 ComfyUI 便携版目录；探不到就手动指定
powershell -ExecutionPolicy Bypass -File install.ps1

# 手动指定 ComfyUI 根目录（便携版里 ComfyUI 那个文件夹）
powershell -ExecutionPolicy Bypass -File install.ps1 -ComfyUI "D:\ComfyUI_windows_portable\ComfyUI"

# 只看会做什么、不真写盘
powershell -ExecutionPolicy Bypass -File install.ps1 -DryRun
```

装完 **重启 ComfyUI**（Python 端新增了路由）。之后只改前端 JS 的话，浏览器 `Ctrl+Shift+R` 即可。

### 手动安装（不想跑脚本）

把插件目录复制进 `custom_nodes`，注意目录名用**下划线**：

```
plugins\ComfyUI-SmartCLIP        ->  <ComfyUI>\custom_nodes\ComfyUI_SmartCLIP
plugins\ComfyUI-ModelImagePicker ->  <ComfyUI>\custom_nodes\ComfyUI_ModelImagePicker
plugins\ComfyUI-AutoSavePreview  ->  <ComfyUI>\custom_nodes\ComfyUI_AutoSavePreview
```

`tests\` 和 `docs\` 不用复制（脚本会自动跳过）。

### 卸载

删掉 `custom_nodes` 里对应目录即可，没有任何注册表 / 系统级改动。
装了 SmartCLIP 又想退回官方 CLIPTextEncode：把工作流里的 `SmartCLIPTextEncode` 换回 `CLIPTextEncode`，它俩接口一致。

---

## 环境要求

| | |
|---|---|
| ComfyUI | 便携版（Windows），0.18.x 上实测；理论上任何带新版前端的版本都能跑 |
| Python | 用 ComfyUI 自带的 `python_embeded` 即可 |
| 第三方包 | **无** |
| 平台 | Windows 优先（安装脚本是 PowerShell）；插件代码本身跨平台 |

---

## 目录结构

```
ComfyUI-Model-Conflict-and-Prompt-Tools/
├── install.ps1                 一键安装（-ComfyUI / -DryRun / -Only / -ForcePresets）
├── publish.ps1                 把这个目录变成 git 仓库并推送（可选）
├── plugins/
│   ├── ComfyUI-SmartCLIP/      节点 + 前端 + 词库 + tests/ + docs/DESIGN.md
│   ├── ComfyUI-ModelImagePicker/
│   └── ComfyUI-AutoSavePreview/
├── tools/
│   ├── ComfyUI-NetFast/
│   └── ComfyUI-InstallMissing/
└── .github/workflows/syntax.yml   CI：Python 语法编译 + 前端 JS 语法检查
```

---

## 开发与测试

```powershell
# Python 语法（全部插件）
Get-ChildItem plugins -Recurse -Filter *.py | ForEach-Object { & <python_embeded>\python.exe -m py_compile $_.FullName }

# SmartCLIP 离线单测（不需要 ComfyUI 在跑）
& <python_embeded>\python.exe plugins\ComfyUI-SmartCLIP\tests\test_smartclip.py
node plugins\ComfyUI-SmartCLIP\tests\jscheck\run.mjs

# ModelImagePicker 引擎自测（对着 models\ 下真实的模型文件跑）
& <python_embeded>\python.exe plugins\ComfyUI-ModelImagePicker\tests\_test_conflict.py
```

`tests/` 里的脚本都认环境变量，换机器时按需覆盖：

| 变量 | 作用 | 默认 |
|---|---|---|
| `MCM_PYTHON` | 用哪个 python 跑 | 探测 `python_embeded` |
| `MCM_PLUGIN` | 已安装插件目录 | 源码目录 / 常见安装路径 |
| `MCM_BASE` | 实时验证打哪个实例 | `http://127.0.0.1:8189` |
| `COMFYUI_ROOT` | ComfyUI 根目录 | 常见安装路径 |

> 这些测试是在开发机上对着真实模型文件写的，换机器可能要按上面的变量指一下路径。

---

## 许可

MIT，见 [LICENSE](LICENSE)。

插件由 **DeepSeek Harness + 使用者** 协作完成；代码可以自由使用、修改、再分发，保留版权声明即可。

---

## At a glance (EN)

* **ComfyUI-SmartCLIP** — a drop-in replacement for `CLIPTextEncode` that detects the checkpoint
  family (SD1.5 / SDXL / Pony / Illustrious / SD3 / FLUX) and opens the matching prompt library,
  with embedding-compatibility badges, a visual embedding picker and type-ahead completion.
* **ComfyUI-ModelImagePicker** — turns the model dropdowns into a thumbnail-modal picker and
  colours every entry by architecture compatibility (green = in use, red = conflict, blue = ok,
  no colour = unknown, never guessed). Reads model headers only, never loads weights.
* **ComfyUI-AutoSavePreview** — keeps the standard preview node, but also writes the full image
  into `output/` (so a preview run leaves a real file behind). Toggle with
  `COMFYUI_AUTO_SAVE_PREVIEW=0`.
* **tools/** — two one-off helpers: network/mirror tuning for the portable launcher, and a
  "which workflow nodes are missing + which deps to install" scanner.

Install: copy the folder into `custom_nodes/` (use the underscore name) and restart ComfyUI.
