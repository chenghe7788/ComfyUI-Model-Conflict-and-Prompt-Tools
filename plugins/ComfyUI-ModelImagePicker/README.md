# ComfyUI-ModelImagePicker

> 把模型下拉菜单换成**缩略图弹窗**，并按架构给每个模型**标红 / 标蓝**。
> *Thumbnail model picker with architecture-conflict colouring. No nodes, no weights loaded.*

| 颜色 | 含义 |
|---|---|
| 🟩 绿框 + 「当前使用」 | 工作流里正在用的那个模型（原有逻辑，未改动） |
| 🟥 红框 + 红底 | 与工作流里**其它模型架构冲突** |
| 🟦 蓝框 + 蓝底 | **兼容** |
| ⬜ 无色 | 架构没认出来 —— **不做任何判断，绝不误报** |

顶部会多一行基准信息：

```
当前: majicmixRealistic_v7.safetensors   ● 基准: SD 1.5（大模型 majicmix…）  [46 冲突] [2 兼容]  图内: Krea2×5 · SDXL×2
```

| | |
|---|---|
| 提供节点 | **无**（纯前端扩展 + 后端路由） |
| 依赖 | **无第三方 Python 包** |
| 安装目录名 | `custom_nodes\ComfyUI_ModelImagePicker` |
| 路由 | `/modelpreview/list`、`/modelpreview/img`、`/modelpreview/debug`、`/modelconflict/index`、`/modelconflict/check`、`/modelconflict/model`、`/modelconflict/refresh` |

---

## 它解决什么问题

**认模型靠文件名太痛苦，而认出来了也不代表能混用。**

* 缩略图来自模型同名侧车图（`majicmixRealistic_v7.safetensors` 旁边的 `majicmixRealistic_v7.png`），
  和 SD WebUI 用的是同一套。有图就显示图，没图显示占位。
* 弹窗**接管了所有会弹出模型列表的地方**：大模型、LoRA、VAE、ControlNet、UNET、文本编码器、
  词嵌入、放大模型、SAM、检测模型 —— 全局包装 `LiteGraph.ContextMenu`，
  任何自定义节点只要控件值是真实模型名（例如 LoRA 堆叠的 10 个槽位）也会被读进参考系。
* 常见翻车现场：底模是 **SD1.5**，LoRA 堆栈里却塞了 **Krea2** 和 **SDXL** 的 LoRA，
  提示词里还引用了 SDXL 专属词嵌入 —— 出图要么糊要么直接报 `shape mismatch`。
  现在打开弹窗就一眼看到谁红谁蓝。

## 判定依据（判据全部来自真实文件校准）

| 类型 | 判据（**只读文件头 / state_dict 键指纹**） |
|---|---|
| 大模型 | `conditioner.embedders.1` / `label_emb` → SDXL；`cond_stage_model` → SD1.5；`double_blocks` → FLUX；`joint_blocks` → SD3；TE 维度 768/1024 |
| LoRA | 元数据 → 键结构：`lora_te2`、`transformer_blocks_≥2` → SDXL；`lora_te_text_model`、`input/output_blocks_10/11`、`down_blocks_3` → SD1.5；`txtfusion` / `attn.gate` → Krea2；`double_blocks` → FLUX；`adaln_modulation` → Anima；`qkv_proj` / `mlp_fc1` → MiniMax H3 |
| VAE | `quant_conv`（4 通道潜空间）→ SD 系；diffusers 命名 `encoder.down_blocks`（16 通道）→ FLUX VAE |
| 词嵌入 | `clip_g` + `clip_l` → SDXL 专用；单个 `emb_params` 768 → SD1.5；1024 → SD2.x |
| 放大 / 分割 / 检测模型 | 判为「通用」，永不冲突（蓝色） |

`.pt / .ckpt` 走**字节级标记扫描** —— `torch.save` 把键名元数据写在文件头部，读头部即可，
**不解包、不 `torch.load`、不执行模型内容**，所以也能识别那些手动装的 `.pt` 词嵌入和 VAE。

## 参考系怎么取（"和谁比"）

* **打开依赖类弹窗（LoRA / VAE / 词嵌入…）**：基准 = 工作流里的大模型架构，严格比对。
* **打开大模型弹窗**：反过来比 —— 看你已接入的模型需要什么。为避免"全部标红"，
  只由**强约束**模型（LoRA / ControlNet / 文本编码器）决定基准；都没有时才退回 VAE / 词嵌入这类。
* 工作流里没有任何可参照的模型 → 全部不着色。

## 其它被一起修掉的小毛病

* **"选大模型时要关两次弹窗"**：一是单击卡片只写入不关闭（现在单击 = 选中并关闭，
  与原生菜单项行为一致）；二是原生菜单是同步构造、缩略图弹窗要等索引加载完才创建，
  这段空窗期里连点会叠两层（现在用 `takeoverPending` 堵住）。
* 打开弹窗前主动清掉残留的原生菜单（`app.canvas.closeContextMenu()` / `.litecontextmenu`），
  避免"弹窗关了、底下的原生菜单还在"。
* 中文目录名、反斜杠、U+2011 智能连字符、不带扩展名的词嵌入引用 —— 都做了容错。

## 安装

把本目录复制到 `custom_nodes`（**目录名用下划线**），重启 ComfyUI：

```
<ComfyUI>\custom_nodes\ComfyUI_ModelImagePicker\
```

之后改 `web\js\*.js` 只需浏览器 `Ctrl+Shift+R`；改 Python 要重启。

## 卸载

删掉目录即可。它没有自己的节点，也没有配置文件 —— 删掉就完全回到原样。

## 测试

```powershell
# 引擎自测：对着 models\ 下真实模型文件跑（可用 MCM_PLUGIN 指定已安装目录）
<python_embeded>\python.exe tests\_test_conflict.py

# 实时接口 / 前端 / 编码 门禁（需要 ComfyUI 在跑）
<python_embeded>\python.exe tests\_final_gate.py
node tests\_jscheck\run.mjs
```

| 变量 | 作用 | 默认 |
|---|---|---|
| `MCM_PLUGIN` | 已安装插件目录 | `C:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_ModelImagePicker` |
| `MCM_PYTHON` | 用哪个 python | 探测 |
| `MCM_BASE` | 实时验证的实例地址 | `http://127.0.0.1:8189` |

`tests\_start_8189.ps1` / `_stop_8189.ps1` 是给开发时自起一个独立实例用的
（**不要**在用户正在出图的实例上跑验证）。

## 已知边界

* 认不出来的架构一律**不着色**，不猜测、不误报。
* SD1.5 / SD2 / SDXL 的 VAE 结构相同（都是 4 通道潜空间），归为一族「SD VAE」，互相不算冲突；
  真正的硬冲突是 FLUX 的 16 通道 VAE 对上 SD 系底模。
* Pony / Illustrious / NoobAI 归为 SDXL 一族（实际用法互通）。
* 只读文件头，从不把权重加载进显存。
* 首次全量扫描有几百毫秒开销（实测 16 个大模型 0.18 s、60 个文件 0.45 s），之后走缓存（四种类型合计 0.05 s）。
