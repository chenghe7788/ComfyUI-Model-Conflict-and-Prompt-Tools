# ComfyUI-SmartCLIP

> 会认底模架构的 `CLIPTextEncode`，外加一整套提示词 / 词嵌入弹窗。
> *A drop-in `CLIPTextEncode` that detects the checkpoint family and pops the matching prompt library.*

```
CheckpointLoader ──CLIP──▶ SmartCLIPTextEncode ──CONDITIONING──▶ KSampler
                                     │
                                     └─（按钮）📝 选择提示词（SDXL · 正向）
```

| | |
|---|---|
| 节点名 | `SmartCLIPTextEncode` |
| 显示名 | `CLIP Text Encode (Smart) / 智能提示词` |
| 分类 | `conditioning/smart` |
| 输入 | `clip` / `text`（多行、支持动态提示词）/ `prompt_role`(auto/positive/negative) / `prompt_category`(仅标注) |
| 输出 | `CONDITIONING`（可直接替换原生节点）、`STRING`（识别到的架构） |
| 依赖 | **无第三方 Python 包**（只用 ComfyUI 自带的 aiohttp / safetensors） |
| 安装目录名 | `custom_nodes\ComfyUI_SmartCLIP` |

接口与原生 `CLIPTextEncode` 一致 —— 把工作流里的原生节点换成它，别的什么都不用改。

---

## 它解决什么问题

1. **底模换了，提示词还在用错的套路。** Pony 要 `score_9, score_8_up…`，Illustrious 要 `masterpiece, best quality`，
   SD1.5 和 SDXL 的质量词也不一样。这个节点会认出当前接的是哪一族底模，
   弹窗自动切到对应词库 —— 不用记、不用手改。

2. **词库散落在各种 txt 里，用的时候靠复制粘贴。** 内置可编辑的 `prompt_presets/presets.json`：
   按模型族 → 正/负面 → 分类（人物 / 发型 / 衣服 / 配饰 / 表情 / 动作姿势 / 环境 / 光照 / 镜头 / 质量词…）组织，
   弹窗左边分类、右边词条，点一下追加进提示词框。

3. **词嵌入（embedding）装了但不知道能不能用。** SDXL 底模上挂 SD1.5 的 `.pt` 词嵌入只会静默失效，
   甚至报 `shape mismatch`。插件给每个词嵌入打**兼容徽标**；选择器里用红/蓝/绿卡片区分
   **不兼容 / 兼容 / 当前使用**，认不出来就不上色。

## 功能一览

### 1. 架构识别 → 自动切词库

识别结果来自两条通路合并：

* **连线预判**（执行前就有）：前端沿 `clip` 输入往上找到加载器 → 读模型文件名 → 后端**只读 safetensors 头**判架构；
  文件名里的口味（Pony / Illustrious / NoobAI / Krea 2）也一并识别 —— 这是 CLIP 对象本身看不到的信息。
* **运行时真相**（执行后覆盖）：节点通过 `ui` 载荷上报权威的基础架构族。

运行时族优先，口味可以把预设集升级（Pony/Illustrious 结构上是 SDXL，但词库必须用它们自己的）。
结果写进 `node.properties.smart_clip` 随工作流保存，刷新页面不丢。

支持的族：`sd15 / sdxl / pony / illustrious / sd3 / flux`（+ `generic` 兜底）。

### 2. 提示词弹窗

```
┌─ 选择提示词 ─ 识别架构: SDXL · 尚未执行过节点 ─ [正向][负面] [追加] [搜索…] [重新加载] [✕] [权重] ─┐
├──────────────┬──────────────────────────────────────────────────────────────────────────────┤
│ 分类          │  score_9                                                                     │
│ 质量词        │  score_8_up                                                                  │
│ 光照          │  score_7_up                                                                  │
│ …            │  …                                                                           │
└──────────────┴──────────────────────────────────────────────────────────────────────────────┘
```

* 左右两栏，词条一行一条；**追加 / 覆盖**两种插入方式，权重 ≠ 1 时自动写成 `(词:权重)`。
* 搜索跨分类；右键分类可改名 / 删除。
* **直接在弹窗里入库**：把一段提示词粘进输入框，服务端按分类规则自动拆到 人物 / 环境 / 光照 / 镜头 …
  等分类里，拆不出来的落「其它」，超长段落会如实提示"已跳过 N 段"而不是假装成功。
* **`_shared` 全局分类**：自己新建的分类不属于任何模型族，所有工作流的弹窗都能看到
  （正向只进正向弹窗、负面只进负面弹窗）。

### 3. 词嵌入（embedding）

两个入口，一份判定：

* **提示词弹窗头部的「词嵌入」按钮** → 图片选择器：一张卡一个词嵌入，带侧车预览图、兼容徽标、架构短标签。
  单击插入（延后 240 ms 等双击判定），双击插入并关窗，底部有「撤销插入」。
* **打字补全**：在提示词框敲 `embedding:` 或名字前几个字母 → 光标下方弹候选，`↑↓` 选择、`Enter`/`Tab` 插入。
  只敲裸名字（例如 `ea`）会自动补上 `embedding:` 前缀。

兼容判定规则（状态：`ok` / `partial` 半兼容 / `incompatible` / `missing` / `unknown`）：

| 底模 | 词嵌入 | 结果 |
|---|---|---|
| SDXL / Pony / Illustrious | 768 维 SD1.5 TI | partial —— CLIP-L 吃、CLIP-G(1280) 忽略并打 `shape mismatch` |
| SD3 / FLUX | SD1.5 TI | partial（两者也有 768 的 CLIP-L） |
| FLUX | SDXL TI | incompatible（没有 1280 那一路） |
| SD3 | SDXL TI | ok |
| SD1.5 | SDXL TI | incompatible |
| 族未识别 / generic | 任意 | unknown —— **不假报兼容** |

颜色语义与模型弹窗一致：**红 = 不兼容、蓝 = 兼容、黄 = 半兼容、绿 = 当前使用**，判不出来不着色。

> 提示词语法（实测）：`embedding:EasyNegative` 生效；裸名 `easynegative` 只是普通文字 token，静默无效；
> `(embedding:EasyNegative:0.8)` 权重 0.8 合法；`<lora:名字:0.8>` **不是**本版 ComfyUI 的语法，整段会被当文字。
> 所以选择器里不放 LoRA。

### 4. 词库导入

三种方式，任选：

1. 直接编辑 `<ComfyUI>\custom_nodes\ComfyUI_SmartCLIP\prompt_presets\presets.json`（不用重启，按文件修改时间生效）。
2. 用导入脚本（有备份、可预演、能直接吃已导出的工作流 JSON）：

   ```powershell
   <python_embeded>\python.exe import_presets.py --file workflow.json --family sd15 --role negative --category 我的负面词 --dry-run
   ```
   去掉 `--dry-run` 才真写；写入前自动备份成 `presets.json.bak-<时间戳>`。
3. 在弹窗里粘贴提示词入库（见上）。

`presets.json` 格式：`{ "模型族": { "positive": { "分类": ["词", …] }, "negative": {…} } }`，
顶层 `_` 开头的 key 被忽略（可写注释）。某个族/方向没写就回落到代码内置的最小词库。

---

## 安装

把本目录（**注意目录名用下划线**）复制到 `custom_nodes`：

```
<ComfyUI>\custom_nodes\ComfyUI_SmartCLIP\
```

然后重启 ComfyUI。之后：

* 改 `web/js/*.js` → 浏览器 `Ctrl+Shift+R` 就够（ComfyUI 每次请求实时读盘）。
* 改 `prompt_presets/*.json` → 不用重启也不用刷新，弹窗里点「重新加载」。
* 改 Python（`nodes.py` / `*_api.py` / `model_detector.py` …）→ 必须重启。

## 卸载

删掉目录即可。工作流里已放入的 `SmartCLIPTextEncode` 换回原生 `CLIPTextEncode` 即可，
`text` 与 `prompt_role` 之外的引脚一一对应。

## HTTP 接口

想脚本化时可以直接调（都是本机 ComfyUI 端口，默认 8188）：

| 方法 | 路径 |
|---|---|
| GET | `/smart_clip/presets` · `/smart_clip/text` · `/smart_clip/detect` · `/smart_clip/info` · `/smart_clip/embeddings` · `/smart_clip/embeddings/img` |
| POST | `/smart_clip/classify` · `/smart_clip/reload` · `/smart_clip/presets/save` · `/smart_clip/presets/save_many` · `/smart_clip/presets/create_category` · `/smart_clip/presets/rename_category` · `/smart_clip/presets/delete_category` · `/smart_clip/presets/delete` |

注册是幂等的（先查 `routes._items` 再注册），重复导入不会出现重复路由。

## 实现上的几个坑（写插件的人可能用得上）

* **前端拿不到节点 Python 实例的任何状态**。没有 `getNodeInstance()` 这种通路；
  唯一机制是节点返回 `{"ui": {...}, "result": (...)}`，由 `execution.py` 经 `executed` websocket 事件下发。
* **`ui` 字典的每个值必须是列表**：`execution.py` 会把 `ui` 拍平成 `{k: [y for x in uis for y in x[k]]}`，
  写成 `{"smart_clip": "sdxl"}` 会被拆成 `['s','d','x','l']`。
* **`OUTPUT_NODE = True` 是让非产物节点的 ui 在缓存命中时被回放的关键**；
  光靠 `IS_CHANGED = NaN` 每次返回新对象会让采样器缓存失效 → 整张图重画，代价比"多编码一次"大得多。
* **只用 bilinear/bicubic 做潜变量放大**（这是另一个插件的事，但同样是踩过的坑）。

细节都写在 [`docs/DESIGN.md`](docs/DESIGN.md)（开发期记录，含逐条实测证据）。

## 已知边界

* 词库按**模型族**给，不按具体 checkpoint；文件名里没有 `pony/illustrious/krea/flux` 线索时，
  SDXL 微调会被当作普通 SDXL（架构相同，只有口味不同）。
* 未接线的 SmartCLIP 节点也会执行一次（`OUTPUT_NODE` 的代价），目的是缓存命中时 UI 不 stale。
* FLUX 一般不用负面提示词，词库里给的是说明文字而非硬凑的负面词。
* 只读模型文件头，不加载权重、不执行模型内容。
* `.pt` 词嵌入拿不到宽度时按 SD1.5 处理（与 ModelImagePicker 的引擎一致），真认不出写「未知」，不猜。

## 测试

```powershell
# 离线单测，不需要 ComfyUI 在跑
<python_embeded>\python.exe tests\test_smartclip.py
<python_embeded>\python.exe tests\merge_selftest.py
node tests\jscheck\run.mjs

# 需要 ComfyUI 在跑
<python_embeded>\python.exe tests\live_check.py
<python_embeded>\python.exe tests\live_ws_check.py
```

环境变量：`MCM_PLUGIN`（插件目录）、`MCM_BASE`（实例地址，默认 `http://127.0.0.1:8189`）、
`MCM_CKPT` / `MCM_FAMILY`（换底模）。

> 改完 `web/js/*.js` 记得同步一份给无头测试，否则 `jscheck` 跑的是旧副本：
> `Copy-Item src\web\js\*.js tests\jscheck\web\js\ -Force`
> （本仓库把源码直接放在插件根目录，对应命令是 `Copy-Item web\js\*.js tests\jscheck\web\js\ -Force`。）

已知红：`test_smartclip.py` 里有 2 项断言是模型族识别的**旧期望值**（检测器现在返回
`illustrious` / `pony`，与 `/smart_clip/info` 的 families 表自洽），非回归。
