# ComfyUI-ModelConflict

在**现有的模型弹窗**（`ComfyUI_ModelImagePicker` 的图片选择框）里按架构判断模型会不会冲突，
不只是 LoRA —— 大模型、LoRA、VAE、词嵌入、ControlNet、UNET、文本编码器全都管。

| 颜色 | 含义 | 实现 |
|---|---|---|
| 🟩 绿 | **当前使用**的那个模型 | 原有逻辑（绿框 + "当前使用"角标），未改动 |
| 🟥 红 | 与工作流其它模型**架构冲突** | 新增：红框 + 红底 + 右上角架构角标 |
| 🟦 蓝 | **兼容** | 新增：蓝框 + 蓝底 + 右上角架构角标 |
| ⬜ 无色 | 架构没认出来，**不做任何判断**（不误报） | 新增：保持原样 |

弹窗顶部会多一行基准信息，例如：

```
当前: majicmixRealistic_v7.safetensors     ● 基准: SD 1.5（大模型 majicmix…）  [46 冲突] [2 兼容]  图内: Krea2×5 · SDXL×2
```

## 为什么需要它

本机上的 `workflow.json / workflow_b.json / 经典2 (1).json` 正是典型案例：底模是
`majicmixRealistic_v7`（**SD 1.5**），但 LoRA 堆栈里塞的是 **Krea 2**
（`写实\snofs_krea_v1_4…`、`写实\ass_v2_krea2_loraholic…`）和 **SDXL**
（`add-detail-xl`、`privet-part`、`Kittew-4RCH0N`），提示词里还引用了 SDXL 专属词嵌入
`embedding:deep_negative_pony`。这些在弹窗里现在会直接标红。

## 判定依据（按本机上的真实文件校准）

| 类型 | 判据 |
|---|---|
| 大模型 | `conditioner.embedders.1` / `label_emb` → SDXL；`cond_stage_model` → SD1.5；`double_blocks`→FLUX；`joint_blocks`→SD3；TE 维度 768/1024 |
| LoRA | 元数据 → 键结构：`lora_te2`、`transformer_blocks_≥2` → SDXL；`lora_te_text_model`、`input/output_blocks_10/11`、`down_blocks_3` → SD1.5；`txtfusion`/`attn.gate` → Krea 2；`double_blocks` → FLUX |
| VAE | `quant_conv`（4 通道潜空间）→ SD 系；diffusers 命名 `encoder.down_blocks`（16 通道）→ FLUX VAE |
| 词嵌入 | `clip_g`+`clip_l` → SDXL 专用；单个 `emb_params` 768 → SD1.5；1024 → SD2.x |
| 放大/分割/检测模型 | 判为"通用"，永不冲突（蓝色） |

`.pt / .ckpt` 走**字节级标记扫描**（torch.save 把键名元数据写在文件头部，读头部即可，不解包、不执行），
所以 `anythingModelVAEV40_v10.pt`、`badhandv4.pt`、`ng_deepnegative_v1_75t.pt` 也能识别。

## 参考系怎么取（"和谁比"）

* **打开依赖类弹窗（LoRA / VAE / 词嵌入…）**：基准 = 工作流里的大模型架构，严格比对。
* **打开大模型弹窗**：反过来比 —— 看你已接入的模型需要什么。为避免"全部标红"，
  只由**强约束**模型（LoRA / ControlNet / 文本编码器）决定基准；它们都没有时，
  才退回 VAE / 词嵌入这类通用模型。
* 工作流里没有任何可参照模型 → 全部不着色（宁可不标，也不乱标）。

## 覆盖的节点

大模型（CheckpointLoader/CheckpointLoaderSimple）、LoRA、VAE、ControlNet、UNET、
文本编码器（CLIPLoader/DualCLIPLoader）、放大模型、SAM、检测模型；
另外**任意自定义节点**只要控件值是真模型名（例如 `JosiaLoraStack` 的 10 个 LoRA 槽位）
都会被读进参考系；提示词里的 `embedding:xxx` 也会被识别。

## 安装 / 回滚

```powershell
# 部署（自动把原文件备份到插件目录下的 _backup_<时间戳>）
powershell -ExecutionPolicy Bypass -File C:\ComfyUI-ModelConflict\install.ps1

# 回滚：还原成未打补丁的原版，并删除本功能新增的文件
powershell -ExecutionPolicy Bypass -File C:\ComfyUI-ModelConflict\install.ps1 -Restore
```

装完**重启 ComfyUI**（Python 端新增了路由）；以后只改前端时刷新页面即可。

## 验证

`tests\` 里是全部验证脚本，用 ComfyUI 自带的 Python 跑：

```powershell
$py = 'C:\ComfyUI_windows_portable\python_embeded\python.exe'
& $py C:\ComfyUI-ModelConflict\tests\_test_conflict.py        # 引擎自测：36 个真实文件 + 工作流级红蓝期望
& $py C:\ComfyUI-ModelConflict\tests\_final_gate.py          # 需要 ComfyUI 跑在 8189：接口 + 前端 + 编码 全量门禁
node C:\ComfyUI-ModelConflict\tests\_jscheck\run.mjs         # 前端模块无头测试（48 项；需有实例在跑）
```

`run.mjs` 也认 `MCM_BASE` 了，可以直接打你正在用的实例，不用另开 8189：

```powershell
$env:MCM_BASE = 'http://127.0.0.1:8188'
node C:\ComfyUI-ModelConflict\tests\_jscheck\run.mjs
```

脚本里的路径都可以用环境变量覆盖：`MCM_PYTHON`（ComfyUI 的 python）、`MCM_PLUGIN`（插件目录）、
`MCM_BASE`（实时验证打哪个地址，默认 `http://127.0.0.1:8189`；你自己开着的实例是 **8188**）。

已实测结果（2026-09-14 ~ 09-15，本机）：

* 引擎自测 **36/36 通过**，工作流级红/蓝期望 **0 失败**
* 实时接口：LoRA 46 红 / 2 蓝、FLUX VAE 红、SD VAE 蓝、SDXL 词嵌入红、SD1.5 词嵌入蓝、
  底模弹窗里 `majicmix`（SD1.5）红 / Illustrious 蓝 —— 全部符合预期
* 前端无头测试 **48 项断言通过**（含中文目录名、反斜杠、U+2011 智能连字符、不带扩展名的词嵌入引用，
  以及本次修复的"单击即关 / 防叠层 / 清原生菜单"回归）
* 性能：首次全量扫描 16 个大模型 0.18s、60 个文件 0.45s；命中缓存后四种类型合计 **0.05s**
* 另在**你正在运行的实例**（`127.0.0.1:8188`）上只读复验过：接口判定与前端资源（UTF-8）全部通过

## 顺带发现：你的工作流 JSON 里有"智能连字符"

`workflow.json` 等文件里 `vae‑ft‑mse‑840000‑ema‑pruned.safetensors` 用的是 **U+2011 非断连字符**
（不是 ASCII `-`），`LatentUpscaleBy` 的 `nearest‑exact` 也一样 —— 这种名字 ComfyUI 本身是匹配不到的。
本插件对这类字符做了容错（能正确识别成 SD VAE），但**建议你自己把工作流里的字符改回 ASCII `-`**，
否则 ComfyUI 校验那一项仍会失败。

## 弹窗只要关一次（本次修复）

"选大模型的时候要关两次弹窗"是两个原因叠加，两个都修了：

1. **选完不自动关**：从 `▣ 大模型` 按钮打开的弹窗，单击卡片只写入、不关闭，还得再点一次 ✕。
   现在单击 = **选中并关闭**（与原生菜单项、以及"拦截菜单自动打开"那条路径行为完全一致）。
2. **可能叠两个弹窗**：原生菜单是同步构造的，我们的弹窗要等模型索引加载完才创建；这段空窗期里
   `openModals` 还是空的，于是双击（或索引加载期间的第二次点击）会再开一个 —— 关掉上面那个，
   底下还有一个。现在用 `takeoverPending` 把这段窗口堵住，重复菜单直接关闭，不再叠层。

另外，打开弹窗前会主动清掉残留的原生菜单（`app.canvas.closeContextMenu()` 与 `.litecontextmenu`），
避免"弹窗关了、底下的原生菜单还在"。

## 已知边界

* 认不出来的架构一律**不着色**，不猜测、不误报；
* SD1.5 / SD2 / SDXL 的 VAE 结构相同（都是 4 通道潜空间），归为一族"SD VAE"，互相之间不算冲突
  ——真正的硬冲突是 FLUX 的 16 通道 VAE 对上 SD 系底模；
* Pony / Illustrious / NoobAI 归为 SDXL 一族（互相通用的实际用法）；
* 只读文件头，从不加载权重到显存，不执行模型内容。

## 文件清单

```
install.ps1                           一键部署 / -Restore 回滚（往返已实测）
src\model_conflict.py                 引擎：架构判定 + 兼容矩阵 + 参考系 + 缓存（901 行）
src\model_conflict_api.py             4 个 HTTP 路由（index / check / model / refresh）
src\__init__.py                       在原插件里注册冲突路由（已合并原内容）
src\web\js\model_conflict.js          前端：读工作流模型、请求判定、上色、图例
src\web\js\model_image_picker.js      原弹窗（已打 8 处补丁：导入、新类型、CSS、着色、图例；
                                       另有本次修复：单击即关、防叠层、清原生菜单）
original\__init__.py                  未打补丁的原版（-Restore 用）
original\model_image_picker.js        未打补丁的原版（-Restore 用）
tests\_test_conflict.py               引擎自测（36 个真实文件 + 工作流级期望）
tests\_final_gate.py                  总门禁：实时接口 + 前端 + 编码 + 计时
tests\_verify_api.py                  实时接口验证
tests\_verify_js_encoding.py          服务端 JS 的 UTF-8 / 中文字面量校验
tests\_jscheck\run.mjs                前端无头测试（含 scripts\app.js 桩）
```

部署位置：`C:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_ModelImagePicker\`
（未打补丁的原文件另存于同目录 `_backup_20260914_modelconflict\`）
