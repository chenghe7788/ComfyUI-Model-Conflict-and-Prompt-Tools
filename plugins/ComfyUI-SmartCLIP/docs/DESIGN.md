# ComfyUI SmartCLIP

**CLIP 文本编码（智能）** —— 接口与原生 `CLIPTextEncode` 一致，但会识别输入 CLIP 的架构，
并据此弹出对应的提示词词库（SD1.5 / SDXL / Pony 评分标签 / Illustrious / SD3 / FLUX）。

```
CheckpointLoader ──CLIP──▶ SmartCLIPTextEncode ──CONDITIONING──▶ KSampler
                                    │
                                    └─（按钮）📝 选择提示词（SDXL · 正面）
```

| | |
|---|---|
| 节点名 | `SmartCLIPTextEncode`（显示名 `CLIP Text Encode (Smart) / 智能提示词`） |
| 分类 | `conditioning/smart` |
| 输入 | `clip` / `text`（多行、支持动态提示词）/ `prompt_role`(auto/positive/negative) / `prompt_category`(标注) |
| 输出 | `CONDITIONING`（可直接替换原生节点）、`STRING`（识别到的架构） |
| 依赖 | **无第三方 Python 包**（只用 ComfyUI 自带的 aiohttp / safetensors） |

---

## 一、这份实现修正了初稿报告里的哪些问题

下面每一条都**在本机这份 ComfyUI 上实测/读源码确认过**，不是推断。

### 1. 模型类型"塞进 conditioning 传给前端"——机制根本不存在

初稿写 `return ([[cond, {"pooled_output": pooled}]],)` 并把 `smart_clip` 元数据塞进
conditioning，前端再用 `this.getNodeInstance()._cached_model_type` 读。

* ComfyUI 的前端 **拿不到节点 Python 实例的任何状态**，没有 `getNodeInstance()` 这种通路。
* 真正机制是节点返回 `{"ui": {...}, "result": (...)}`（`execution.py:341-364`），
  由 `execution.py:542-553` 经 `executed` websocket 事件下发；前端在
  `comfyui_frontend_package 1.41.21` 里就是一句
  `node.onExecuted(e.output)`（`dialogService-*.js`，监听 `executed` 事件）。
* **更隐蔽的坑**：`execution.py:403` 会把 ui 字典拍平——
  `ui = {k: [y for x in uis for y in x[k]] for k in uis[0].keys()}`
  **所以每个 ui 值必须是列表**。写成 `{"smart_clip": "sdxl"}` 会被拆成
  `['s','d','x','l']`（单测里有一行专门演示这个）。
* 本实现：`{"ui": {"smart_clip": [payload]}, "result": (conditioning, label)}`。

### 2. `IS_CHANGED = NaN`：方向对，但只做对了一半

`NaN` 确实会强制每次重跑；但初稿把它删掉后，**缓存命中时前端就收不到任何更新**（实测：
第二次完全命中缓存时，不带 `OUTPUT_NODE` 的节点 payload 不会下发）。

* 实测结论（`tests/live_ws_check.py`，websocket 走浏览器同样的通路）：
  **`OUTPUT_NODE = True` 才是让"非产物节点"的 ui 在缓存命中时被回放的关键**。
  加上它之后：第二次运行 `ran=[]`（**采样器没有重跑**），但两个节点的 payload 照常到达。
* 而 `IS_CHANGED = NaN` 的真正代价比"多编码一次"更大：每次返回新的 conditioning 对象会让
  **采样器的缓存键失效 → 整张图重画**。所以两者必须这样组合，本实现即如此。
* 副作用（有意为之）：未接线的 SmartCLIP 节点也会执行一次，于是还没连线就能看到架构标签；
  代价是一次文本编码（毫秒级），不是一次采样。

### 3. `/smart_clip/presets` 路由：404 的根因不止"没写"

初稿在 `nodes.py` 里直接 `@PromptServer.instance.routes.get(...)`：

* 模块被非服务端环境导入时 `PromptServer.instance` 可能是 `None` → 导入期 AttributeError；
* 函数内 `import aiohttp.web` 后再用 `aiohttp.web.json_response`，而 `aiohttp` 名字并未绑定；
* 同一模块被重复导入会向 RouteTableDef 追加重复路由；
* 两个分支返回的 JSON **结构不一致**（一个是 `{分类: [...]}`，一个是
  `{模型: {方向: {分类: [...]}}}`），前端无法用同一套代码渲染；
* `f"{model}_{role}.json"` 的文件名拼法在缺文件时落回的内置词库形状又和上面两者都不同。

本实现：独立 `smart_clip_api.py`，注册时先查 `routes._items` 做幂等；
**永远返回同一种结构** `{model, role, categories:{分类:[词]}, source, models, roles}`；
缺文件/坏 JSON 一律回落内置词库（单测里用损坏 JSON 验证过）。

> 另一个事实：本版 aiohttp 3.13 的 `RouteTableDef` **没有 `.router`**，
> 直接 `routes.router.add_route(...)` 会 AttributeError；而 ComfyUI 是
> `main.py`: 先 `nodes.init_extra_nodes()` 再 `prompt_server.add_routes()`，
> 所以**装饰器写法才是正确姿势**。

### 4. 连线遍历 `app.graph.links[linkId]` 在本版前端是 undefined

初稿的 `determinePromptRole` 用 `app.graph.links[linkId]`：

* 本版 LiteGraph（`api-*.js`）里 `LGraph` 的 `links` 只是**声明未赋值**，
  真正的存储是 `_links = new Map()`；`getOutputNodes()` 内部用的就是 `this.graph._links.get(id)`。
  所以 `graph.links[id]` 在浏览器里会 `TypeError`，**整个正负向自动判断从来没有生效过**。
* 单测里把这条写成了回归用例：先证明 `graph.links[id]` 抛 `TypeError`，
  再证明本实现照样能找到下游节点。
* 另外初稿的防环 `if (visited.has(node.id)) return "positive"` 会把**环**当成正向
  （语义错误），且 `visited` 在递归里被共享/污染。本实现改成 BFS +
  `visited` + 深度上限 + 步数上限，并对"环 / 自环"各写了用例（都是毫秒级返回）。

### 5. 用 `cond_stage_model.transformer.context_dim` 检测：属性不存在，且不该读权重

* 本版 SD1.5/SDXL 的 CLIP 是 `SD1ClipModel` / `SDXLClipModel` 这类**组合包装类**，
  并没有 `transformer.context_dim` 这个属性 → 初稿的分支基本走不到；
* 初稿第一句就是 `clip_obj.cond_stage_model.state_dict()`：对 dynamic/mmap 的
  patcher，这可能**把几个 GB 的文本编码器权重实体化**，只为回答一个字符串问题。

本实现的分层探测（全程不碰权重）：

| 顺序 | 依据 | 覆盖 |
|---|---|---|
| 1 | `clip.cond_stage_model.__class__.__name__` | SD1ClipModel / SD2ClipModel / SDXLClipModel / SD3ClipModel / FluxClipModel / StableCascadeClipModel |
| 2 | `clip.tokenizer` 类名 + `clip_g`/`t5xxl`/`clip_name` 属性 | 第三方包装类兜底 |
| 3 | `clip.patcher.model` 类名 | 再兜底 |
| 4 | 放弃 → `unknown`（**绝不当成冲突**） | 不猜测 |

单测覆盖 12 种情况，包括"属性访问直接抛异常"和"完全陌生的对象"。

### 6. `encode_from_tokens(return_pooled=True)` 不是"完全兼容原生"

本版原生 `CLIPTextEncode.encode` 是：

```python
tokens = clip.tokenize(text)
return (clip.encode_from_tokens_scheduled(tokens), )
```

`encode_from_tokens_scheduled` 负责应用 hooks、LoRA 对 CLIP 的补丁、以及不同模型的
token 处理，返回的是 conditioning **列表**。初稿的写法绕过这些，还会给 FLUX 这类
**没有 pooled 输出**的模型硬塞一个 `pooled_output`。本实现用原生调用。

### 7. 预设 JSON 读取：初稿缺失（已实现）

`prompt_presets/presets.json`，按文件修改时间缓存 → **改完存盘即生效，不用重启**。
形状容错：`["a"]` / `"a"` / `{"prompts": [...]}` / `{"words": "a, b"}` / 嵌套数组
全部归一化成字符串列表（单测 6 种形状）。

### 8. 弹窗 HTML 注入：不是"用 dataset 补一下"就够了

初稿 `overlay.innerHTML = _buildHTML(...)` 之后再回头补 `dataset.prompt`，
注入点在 `_buildHTML` 里已经发生了。本实现**全程不拼 HTML**：
元素用 `createElement` + `textContent`，词条文本原样进 DOM。
单测断言"整次渲染里 `innerHTML` 赋值次数 == 0"，并用
`he said "hi" & <b>bold</b> 'quote'` 这种词条验证 DOM 里没有多出子元素。

### 额外修正

* 初稿的 `IS_CHANGED` 写成 `return float("nan") if False else None`（等于定义了却永远返回 None）——已删除。
* `prompt_category` 明确为**标注**用途（记录上次取词的分类，写在节点的 `properties`/ui 里），不参与编码。

---

## 二、架构判定：运行时 vs 连线预判（解决"首次弹窗 unknown"）

初稿把"首次弹窗显示 unknown"列为已知限制。本实现用两条来源合并解决：

1. **连线预判（执行前就有）**：前端从 `clip` 输入往上走，
   找到 `CheckpointLoaderSimple` / `UNETLoader` / `CLIPLoader` 等加载器，
   读出模型文件名 → 调 `GET /smart_clip/detect`，后端**只读 safetensors 头**判断架构，
   并给出文件名里的"口味"（Pony / Illustrious / NoobAI / Krea 2）——这是 CLIP 对象本身看不到的信息。
2. **运行时真相（执行后覆盖）**：节点的 ui 载荷给出权威的基础架构族。

合并规则（`model_tracker.js`）：**运行时族优先**，但"口味"可以把预设集升级
（Pony/Illustrious 结构上是 SDXL，词库必须用它们自己的）。
结果写进 `node.properties.smart_clip` 随工作流保存，刷新页面不丢。

---

## 二之补、词嵌入已并入本插件（原 ComfyUI_EmbeddingHelper）

**一句话**：以前「提示词弹窗」和「词嵌入弹窗」是两个插件，各有一份嵌入列表；
现在只有 **ComfyUI_SmartCLIP** 一个插件，嵌入的选取有两个入口（提示词弹窗头部的
「词嵌入」按钮 + 打字补全；**没有**全局悬浮按钮、**没有**节点按钮），安装/架构判定
统一走 `embedding_compat.py` 的 `resolve()` / `annotate()`。

| 能力 | 合并前 | 现在 |
| --- | --- | --- |
| 提示词弹窗（分类词库、入库、权重） | SmartCLIP | SmartCLIP |
| 词嵌入**兼容标记**（已装/不兼容/未装） | SmartCLIP（仅提示词弹窗可见） | SmartCLIP（提示词弹窗词条徽标 + 选择器卡片颜色，都走 `annotate()`） |
| 词嵌入**打字补全** | EmbeddingHelper | SmartCLIP（`web/js/embedding_picker.js`） |
| 词嵌入**图片选择器**（预览图、搜索、复制、撤销插入） | EmbeddingHelper（独立弹窗 + 右下角悬浮按钮） | SmartCLIP：**「选择提示词」弹窗头部那个「词嵌入」按钮**打开（2026-09-15 二次改版） |
| 负面提示词节点上的「▣ Embedding」按钮 | EmbeddingHelper | **已删除**（2026-09-15） |
| Embedding 列表接口 | `/embeddinghelper/list`、`/img` | `/smart_clip/embeddings`（`?family=<预设>` 时逐条返回 `compat` 判定；`/img` 预览图路由给选择器用） |

两个入口：

* **「词嵌入」按钮**（提示词弹窗头部，`追加/覆盖` 右边）：打开选择器，一张卡一个词嵌入，
  带侧车预览图、兼容徽标和架构短标签。颜色语义直接抄 LoRA 模型弹窗
  （`model_conflict.js`）：**红 = 不兼容、蓝 = 兼容、绿 = 当前使用**（绿优先），
  判不出来就不上色。单击插入并留在弹窗里（负面提示词常常要连点好几个；单击会延后
  240 ms 等双击判定，双击只插一次并关窗），底部有「撤销插入」。插入规则和词条点击
  完全同一条路径：走弹窗自己的追加/覆盖 + 权重，权重 ≠ 1 时写成
  `(embedding:名字:权重)`（实测合法，见下）。
* **打字补全**：在提示词框里敲 `embedding:` 或名字的前几个字母 → 候选列表弹在光标下方，
  `↑↓` 选择、`Enter`/`Tab` 插入、`Esc` 关闭；只敲名字（例如 `ea`）会自动补上 `embedding:` 前缀。

> 为什么不是全局悬浮按钮 / 节点按钮：2026-09-15 用户原话「把负面提示词那里的嵌入弹窗
> 和负面提示词文本弹窗整合到一起」——入口只留一个，就在提示词弹窗里；插入目标由调用方
> 通过 `openEmbeddingPicker({ family, role, getText, setText, onPick })` 决定，弹窗自己不碰
> 任何节点控件。
>
> 改这块有一条铁律：`embedding_picker.js` 末尾那个 `app.registerExtension`
> **必须保留**，补全引擎（`injectCss` + `bindGlobalListeners` + `loadItems`）
> 就住在它的 `setup()` 里；`prompt_dialog.js` 还会显式 `import` 一次这个文件，
> 保证补全一定被装上。

### 提示词里到底能写什么（实测，`tests/probe_prompt_syntax.py`）

| 写法 | 结果 |
| --- | --- |
| `embedding:EasyNegative` | ✅ 变成 768 维词向量（真的生效） |
| `easynegative`（裸名） | ❌ 只是普通文字 token，静默无效 |
| `(embedding:EasyNegative:0.8)` | ✅ 词向量权重就是 0.8（`token_weights()` 用 `rfind(":")` 取权重） |
| `<lora:add_detail:0.8>` / `<lora:名字:1>` | ❌ 本机 ComfyUI **没有**这个语法：整段被切成普通文字 token（连 `<lora:` 都进提示词），LoRA 只能走 `LoraLoader` 节点 |

所以选择器里**不放 LoRA**（用户 2026-09-15 拍板「Lora 可以取消」）。


---

## 三、安装 / 卸载

```powershell
# 部署（旧版先快照，词库原样保留，旧的 EmbeddingHelper 改名为 .disabled）
powershell -ExecutionPolicy Bypass -File C:\ComfyUI-SmartCLIP\install.ps1

# 回滚（把 premerge 快照放回去，并把 .disabled 改回 EmbeddingHelper）
powershell -ExecutionPolicy Bypass -File C:\ComfyUI-SmartCLIP\install.ps1 -Restore

# 想用源码里的默认词库覆盖现有词库时才加这个（会覆盖你的词库！）
powershell -ExecutionPolicy Bypass -File C:\ComfyUI-SmartCLIP\install.ps1 -ForcePresets
```

装完**重启 ComfyUI**。之后只改 JS 的话刷新页面即可；改词库 JSON 不用重启。

> **词库不会被覆盖**：`prompt_presets\presets.json` 已存在时安装脚本原样保留
> （老版本的脚本会把它覆盖掉，这个是这次一起修掉的坑）。
>
> **旧插件处理**：`custom_nodes\ComfyUI_EmbeddingHelper` 会被改名为
> `ComfyUI_EmbeddingHelper.disabled`（文件一个不删，ComfyUI 不再加载它）。
> 不改名也能跑（两边路由不冲突），但嵌入扩展会注册两次：两个悬浮按钮、两个补全弹层。
>
> 备份位置：`<ComfyUI>\_plugin_backups\<时间戳>_SmartCLIP_premerge`，回滚记录写在
> `_plugin_backups\last-install.json`。
> **故意不放在 `custom_nodes` 里**——ComfyUI 会把 `custom_nodes` 下的每个顶层目录都当成一个插件包加载，
> 备份放那儿等于又装了一份（日志里会出现重复路由、JS 被服务两份）。

## 四、验证

```powershell
$py = 'C:\ComfyUI_windows_portable\python_embeded\python.exe'
$sc = 'C:\ComfyUI-SmartCLIP'          # 源码副本，测试随它走

& $py "$sc\tests\test_smartclip.py"     # 离线单测（68 项，不需要 ComfyUI）
& $py "$sc\tests\merge_selftest.py"     # 合并自测（嵌入列表/预览图/判定同源/路由，临时目录用完即删）
node "$sc\tests\jscheck\run.mjs"        # 前端无头测试（47 项，不需要 ComfyUI）
& $py "$sc\tests\live_check.py"         # 需 ComfyUI 在跑：接口 + 真跑工作流 + 从 /history 验载荷
& $py "$sc\tests\live_ws_check.py"      # 需 ComfyUI 在跑：websocket 通路 + 缓存回放 + 未接线节点
```

环境变量：`MCM_BASE`（实时脚本打哪个地址，默认 `http://127.0.0.1:8189`；你自己开着的实例是 **8188**）、
`MCM_CKPT` / `MCM_FAMILY`（换底模，例如 `hassakuXLIllustrious_v13StyleA.safetensors` + `sdxl`）、
`MCM_PLUGIN`（单测找不到已安装插件时手动指定）。
前端无头测试跑的是 `tests\jscheck\web\js\` 下的副本，改完 web/js 记得同步一次：

```powershell
Copy-Item "$sc\src\web\js\*.js" "$sc\tests\jscheck\web\js\" -Force
```

已实测结果（2026-09-15，本机，ComfyUI 独立实例 `127.0.0.1:8189`）：

| 套件 | 结果 |
|---|---|
| `test_smartclip.py` | **188 项（186 通过 + 2 项已知期望差异）**（CLIP 检测 12 / 节点契约 14 / 文件检测 18 / 词库 24 / 词嵌入兼容 41 / 入库写入 20 / 分类拆分 59）。2 项红的是模型族识别：检测器现在对 `hassakuXLIllustrious…` / `ponyDiffusionV6XL…` 返回 family=`illustrious`/`pony`（与 `/smart_clip/info` 的 families 表、词嵌入族表一致），测试里仍是旧的 `('sdxl','illustrious')` 断言，与拆分入库改动无关，待定。 |
| `merge_selftest.py` | **11 项通过**（嵌入索引 7 个 / 列表 6 项·3 张预览图 / 名字 6/6 可 `resolve` / 判定与 `annotate` 逐项同源 / 族切换 sd15=1 不兼容·flux=0 / 词库 3 条徽标 / 两个路由可注册 / 无旧路由残留） |
| `jscheck/run.mjs` | **199 项通过**（含 `graph.links[id]` 抛错回归、环/自环、注入安全、分类列表、词嵌入徽标、跨分类搜索、入库/拆分入库/错误路径/旧后端置灰；新增「拆不出词条时不再谎报空输入」「部分超长段落被跳过时如实提示」等） |
| `live_check.py`（SD1.5 `majicmix`） | **41 项通过**，`family=sd15`，证据 `cond_stage_model=SD1ClipModel` |
| `live_check.py`（SDXL `hassakuXLIllustrious`） | **通过**，`family=sdxl`，缓存回放载荷一致 |
| `live_ws_check.py` | **14 项通过**：首次下发 / 缓存命中仍下发 / 采样器未重跑 / 未接线节点也上报 |
| `probe_embeddings.py` | 对本机 `models/embeddings` 里 7 个词嵌入逐个判定（见第七节） |
| `probe_prompt_syntax.py` | 用本机 `SDTokenizer` 实测提示词语法：`embedding:X` 出词向量、裸名无效、带权重合法、`<lora:X:w>` **无效**（见第二之补） |

真实 ui 载荷示例（`/history` 里读出来的原文）：

```json
{"smart_clip": [{"family": "sd15", "label": "SD 1.5", "preset": "sd15",
  "evidence": "cond_stage_model=SD1ClipModel; tokenizer=SD1Tokenizer; clip_name=l",
  "source": "cond_stage_model", "role": "auto", "chars": 25,
  "text_preview": "masterpiece, best quality"}]}
```

## 五、已知边界

* 词库按"模型族"给，不按具体 checkpoint；`prompt_presets/presets.json` 可自由增删改。
* 文件名里没有 `pony/illustrious/krea/flux` 等线索时，SDXL 微调会被当作普通 SDXL
  （架构相同，只是词库口味不同）。
* 未接线的节点也会执行（`OUTPUT_NODE` 的代价，换来缓存命中时 UI 不 stale）。
* FLUX 一般不用负面提示词，词库里给的是说明文字而不是硬凑的负面词。
* 只读模型文件头，不加载权重、不执行模型内容。
* 词嵌入标签只读文件头：`.pt` 拿不到宽度时按 SD1.5 处理（与 ModelConflict 引擎一致），
  真的认不出来就写「未知」，不猜。

---

## 六、提示词弹窗：分类列表 + 词条列表

弹窗改成左右两栏，词条始终是一行一条的列表：

```
┌─ 选择提示词 ─ 识别架构: SDXL · 尚未执行过节点 ─ [正向][负面] [追加] [搜索…] [重新加载] [✕] [权重] ─┐
├──────────────┬──────────────────────────────────────────────────────────────────────────────┤
│ 分类          │  score_9                                                                     │
│ 评分标签   5  │  score_8_up                                                                  │
│ 来源标签   5  │  score_7_up                                                                  │
│ 质量词     6  │  …                                                                           │
│ 构图与镜头 6  │                                                                              │
├──────────────┴──────────────────────────────────────────────────────────────────────────────┤
│ 当前文本框内容预览…                                                                          │
├─────────────────────────────────────────────────────────────────────────────────────────────┤
│ 词库文件 · pony / positive · 5 个分类 · 词嵌入 2 可用 / 1 未安装                              │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

* 左栏每行是一个分类，右侧数字是词条数，当前分类高亮；点一行即切换。
  自建分类（全局）在名字后面带一个绿色「全局」小标，鼠标悬停会说明它处处可见（见第八节 `_shared`）。
* 右栏是该分类的词条列表；点击一条就按当前的「追加/覆盖 + 权重」写入节点文本框。
* 搜索框一旦有输入就**跨分类**搜索，命中项后面用灰色标出它来自哪个分类（清空搜索回到当前分类）。
* 仍然是「零 `innerHTML`」：词条、分类名都用 `textContent` 写入，`"`/`<`/`&` 不会破坏布局，
  也不会被当成标签解析。

## 七、词嵌入（embedding）兼容标记

词条里只要引用词嵌入，弹窗就会按**当前识别到的架构**给出徽标：

| 徽标 | 状态 | 含义 |
|---|---|---|
| `TI-SD1.5 · 兼容` | ok | 768 维词嵌入（或仅 `clip_l`），用在 SD1.5 底模上 |
| `TI-SDXL · 兼容` | ok | `clip_g` + `clip_l` 双编码器词嵌入 |
| `TI-SD1.5 · 半兼容` | partial | 768 维 SD1.5 词嵌入用在 SDXL 系底模上：CLIP-L 吃下它，CLIP-G(1280) 忽略它并打印 `shape mismatch ... 768 != 1280` —— 只有一半文本编码器生效（黄标，不置灰） |
| `TI-SDXL · 不兼容` | incompatible | 已安装，但训练用的文本编码器跟当前模型族不同 —— **整条置灰** |
| `未安装` | missing | `models/embeddings` 里没有这个文件（词条是"需自己下载"的） |
| `未知` | unknown | 已安装，但架构认不出来 —— 不做判断（宁可不标） |

* 两种写法都认：`embedding:EasyNegative`，以及**裸名** `EasyNegative`
  （裸名只有在"确实是已安装的某个文件"时才算，所以 `masterpiece` 这类普通词不会被误判；
  带括号的整句也不会被当成单个引用）。
* **整句里含 `embedding:` 的长负面提示词也会判定**（从工作流导入的提示词基本都是这种）：
  取其中**最严重**的那一个作为整条的判定，徽标写"3 个词嵌入 · 不兼容"，悬停能看到是哪个词条出的问题。
  只含普通词、或只有不带 `embedding:` 前缀的散词的句子，不给徽标（避免误判）。
* 兼容分组与 **ComfyUI-ModelConflict 引擎完全一致**，两个插件不会互相打架：
  `sd15 → {TI-SD1.5}`、`sdxl/pony/illustrious → {TI-SD1.5, TI-SDXL}`、`sd21 → {TI-SD2}`
  （SD1.5 的 768 维词嵌入放在 SDXL 上是**半兼容**：CLIP-L 吃下它，CLIP-G(1280) 忽略它，
  ComfyUI 控制台会打一行 `shape mismatch when trying to apply embedding ... 768 != 1280`，
  所以标黄「半兼容」而不是标蓝「兼容」；SDXL 词嵌入放到 SD1.5 上才是硬冲突）；
  `sd3/flux` 也有 768 维的 CLIP-L，所以 768 维词嵌入在它们上面同样是**半兼容**
  （FLUX 上 1280 维的才是硬冲突；SD3 两个编码器都有，SDXL 词嵌入反而全兼容）；
  `cascade/krea2` 这类本表说不清的架构只标「已安装」；
  **底模族还没识别出来时（`generic` / `unknown`）一律标「未知」**，不拿「兼容」糊弄——不骗人，也不冤枉模型。
* 一条词条里有多条引用时，**确定的半兼容优先于「未识别」**（会刷 shape mismatch 警告的那个更值得提醒）；
  引用里的子目录（`embedding:sub/name`）必须真的对上那个目录，不会退化成"同名文件在别处"而误报已安装。
* **底模族从哪来（2026-09-23 补）**：正常是前端沿 CLIP 连线回溯到加载器（`GET /smart_clip/detect`，读文件头）。
  这条线走不通时——CLIP 中间隔了一个 LoRA 堆叠节点、页面在 ComfyUI 还没启动完时加载、
  浏览器拿着旧缓存——前端只能说 `generic`，于是**整片徽标都变成「未知」**，弹窗等于没标注。
  现在前端说不出话时由**服务端兜底**：`workflow_model.py` 从 ComfyUI 自己的队列/历史里取
  **最近一张真正跑过的图**，找出它的 CheckpointLoaderSimple / UNETLoader / CLIPLoader，
  读文件头认出底模族再判定（正在跑的 > 排队中的 > 最近完成的）。
  判定用的族可以在弹窗副标题里看到：显示成 `模型族 illustrious（按工作流推断）` 就说明用的是兜底值；
  是前端自己认出来的（例如 `模型族 pony`）就不会带这个括注。前端给出的判定**永远优先**，兜底只在它说不出话时生效。
  想看服务端认为你在用哪个底模：`GET /smart_clip/info` 里的 `workflow` 字段。
  `presets.load(model, role, verdict_model=...)` 里 `verdict_model` 只改**徽标判定所用的族**，
  不改弹窗给你哪一份词库。
* 判定只读文件头：safetensors 读 JSON 头（`clip_g`/`emb_params` 维度），
  `.pt` 扫头部的字节标记；**从不加载权重**。
* 引用可以带权重、也可以套括号：`(embedding:EasyNegative:1.2)`、`embedding:badhandv4:0.8`
  都会先剥掉 `:权重` 再去找文件——不会把 `:1.2` 当成文件名而误报「未安装」。
* 置灰的条目**仍可点击加入**，只是提醒你别用错；悬停能看到原因。

本机 `models/embeddings`（8 个）实测（最后一列是**在 SDXL 系底模下**会亮什么徽标）：

```
deep_negative_pony.safetensors     TI-SDXL    clip_g + clip_l        -> 兼容
负面手脚negative_hands.safetensors TI-SDXL    clip_g + clip_l        -> 兼容
EasyNegative.safetensors           TI-SD1.5   emb_params 768 维      -> 半兼容（CLIP-G 会忽略）
EasyNegativeV2.safetensors         TI-SD1.5   emb_params 768 维      -> 半兼容（CLIP-G 会忽略）
ng_deepnegative_v1_75t.safetensors TI-SD1.5   emb_params 768 维      -> 半兼容（CLIP-G 会忽略）
ng_deepnegative_v1_75t.pt          TI-SD1.5   .pt 无 SDXL 标记        -> 半兼容（CLIP-G 会忽略）
badhandv4.pt                       TI-SD1.5   .pt 无 SDXL 标记        -> 半兼容（CLIP-G 会忽略）
NegfeetV2.pt                       TI-SD1.5   .pt 无 SDXL 标记        -> 半兼容（CLIP-G 会忽略）
```

要看自己机器上的实际情况：

```powershell
$env:SMARTCLIP_EMBEDDINGS_DIR = 'C:\ComfyUI_windows_portable\ComfyUI\models\embeddings'
& 'C:\ComfyUI_windows_portable\python_embeded\python.exe' `
  'C:\ComfyUI-SmartCLIP\tests\probe_embeddings.py'
```

## 八、提示词库怎么导入（重点）

**提示词文件就一个**——它同时是"目录"和"文件"：

```
<ComfyUI>\custom_nodes\ComfyUI_SmartCLIP\prompt_presets\presets.json
例如 C:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_SmartCLIP\prompt_presets\presets.json
源代码副本：C:\ComfyUI-SmartCLIP\src\prompt_presets\presets.json
```

结构是 **模型族 → 方向 → 分类 → 词条数组**：

```json
{
  "sd15": {
    "positive": { "质量词": ["masterpiece", "best quality"] },
    "negative": { "词嵌入（需已安装）": ["embedding:EasyNegative"] }
  }
}
```

* 模型族 key：`generic / sd15 / sdxl / pony / illustrious / sd3 / flux`（可自由增加）；
* 分类值必须是数组（`{"prompts": [...]}`、单个字符串也兼容）；以 `_` 开头的 key 当作注释忽略；
* **改完保存即生效**：文件按修改时间缓存，不用重启 ComfyUI；在弹窗里点「重新加载」或重开弹窗即可看到；
* 某个族/方向没写，会自动回落到代码内置的最小词库（不会报错、不会变空）。

### `_shared`：你自己新建的分类 = 全局分类（2026-09-19）

**在弹窗里新建的分类，一律写进 `_shared` 段**，它不属于任何模型族：

* 不管哪个工作流、哪个底模，打开提示词弹窗都能看到它——左侧带绿色「全局」小标；
* 方向仍然分开：正向分类只出现在正向弹窗，反向分类只出现在反向弹窗；
* 在任意一个族的弹窗里改名 / 删除，等于改全局（所有族一起跟着变，不会留下一份旧副本）；
* 模型族自带的预设（`评分标签`、`描述模板`、`通用负面`…）不受影响，仍然只出现在那个族的弹窗里；
* 重名不互相顶掉：`_shared` 里的 `光照` 会和 `generic` 自己的 `光照` 合并显示（去重后并集）。

> 为什么要有这一段：老版本把自建分类存在"当时识别到的模型族"下面（没连底模、节点没跑过时会落到
> `generic`），于是同一个分类在这个工作流里有、换个工作流就看不见——因为那个工作流识别成了
> `illustrious` / `pony`，弹窗去别的族里找词库了。
>
> 第一次读取词库时会把这类自建分类自动收拢进 `_shared`（**只搬自建分类，各族自带的预设原地不动**），
> 并先备份一份 `presets.json.bak-before-shared`。这个动作只在确有东西要搬时写一次盘，之后不再碰文件。

```json
{
  "_shared": {
    "positive": { "蝴蝶忍": ["score_9", "1girl"] },
    "negative": { "我的负面": ["worst quality"] }
  }
}
```

也可以自己手写这一段（`_` 开头的 key 本来就会被忽略成注释，所以你手写的 `_shared` 同样生效）。

### 方式一：手动改 presets.json

最简单。用 VS Code/记事本打开上面的文件，照抄一个分类块改词即可（记得 JSON 逗号）。
写坏了也不会崩：解析失败会回落到内置词库，弹窗照常能用。

### 方式二：用导入脚本（有备份、可预演、能直接吃工作流）

```powershell
$py  = 'C:\ComfyUI_windows_portable\python_embeded\python.exe'
$imp = 'C:\ComfyUI_windows_portable\ComfyUI\custom_nodes\ComfyUI_SmartCLIP\import_presets.py'

# 1) 先看现在有什么
& $py $imp --list

# 2) 预演：把你自己的工作流（workflow.json / workflow_b.json 都行）里的提示词抽成一个分类
& $py $imp --file "C:\workflow.json" --family sd15 --role negative --category 经典2 --dry-run

# 3) 真导入（自动备份成 presets.json.bak-<时间戳>）
& $py $imp --file "C:\workflow.json" --family sd15 --role negative --category 经典2

# 4) 导入一个纯词条文件（json 数组 / {"prompts":[...]} / {"分类":[...]} / txt 每行一条）
& $py $imp --file "D:\我的词库.txt" --family sdxl --role positive --category 我的词库
```

也可以直接双击插件目录里的 **`import-presets.bat`**（不带参数时等于 `--list`）。

支持的输入与合并规则：

| 输入 | 识别为 | 落到哪 |
|---|---|---|
| ComfyUI 工作流 JSON（含 `nodes`） | 自动抽取每个 CLIP 文本编码节点的提示词 | 你给的 `--family/--role/--category` |
| `{"sd15": {"negative": {"分类": [...]}}}` | presets 形状 | **按它自己的族/方向**（`--flatten` 可强制压平） |
| `{"分类": [...]}` | 分类映射 | 你给的族/方向 |
| `["a","b"]` / `{"prompts": [...]}` / `{"words": "a, b"}` | 一个分类 | 你给的族/方向 |
| `.txt` / `.md` | 每行、每个逗号切一条 | 你给的族/方向 |

* 同名分类是**去重合并**（旧词保留，新词追加），其它分类不动；
* 导入的分类如果**不是那个模型族自带的预设名**，会在下次读取词库时按上面的规则收进 `_shared`
  （全局可见，正向/反向照旧分开）；族自带预设名（`质量词`/`评分标签`/`通用负面`…）则留在该族里；
* 写之前自动备份 `presets.json.bak-<时间戳>`，写入是"临时文件 + 原子替换"，并且会先自校验 JSON；
* 想回滚：把 `.bak-*` 改名覆盖回 `presets.json` 即可。

### 方式三：把"我的词库"加到弹窗里当独立分类

只想要自己的词、不想要内置词？把 `prompt_presets/presets.json` 换成一个只含你自己分类的文件即可
（`--list` 会打印当前结构，方便对照）。留空某个方向是安全的——弹窗会回落到内置词库。

## 九、在弹窗里直接把提示词入库

弹窗右侧底部有一块「新增到词库」，两种入库方式：

```
┌ 新增到词库 ───────────────────────────────── 已分好 6 条，确认后写入词库 ─┐
│ [ masterpiece, 1girl, long hair, red dress, forest, night ]              │
│ ┌──────────────────────────────────────────────────────────────────────┐ │
│ │ 质量词   masterpiece                                                  │ │
│ │ 人物     1girl                                                        │ │
│ │ 发型     long hair                                                    │ │
│ │ 衣服     red dress                                                    │ │
│ │ 环境     forest、night                                                │ │
│ └──────────────────────────────────────────────────────────────────────┘ │
│ [ 分类（留空 = 当前分类） ] [取当前文本框] [整条入库] [确认入库（6 条）] [取消] │
└──────────────────────────────────────────────────────────────────────────┘
```

* **拆分入库（推荐）**：点一下 → 按逗号把提示词拆成词条，**自动分到 人物 / 发型 / 衣服 /
  配饰 / 表情 / 动作姿势 / 环境 / 光照 / 镜头 / 质量词**（谁都不匹配的进「其它」）→
  先在弹窗里**列出分类预览**，确认后一次性写完（或按 `Ctrl+Enter` 直接走完这两步）。
  分隔符同时认**半角 `,` / 换行**和**全角 `，` `；` `、`**，中文提示词照样能拆；
  单段超过 2000 字先按句末标点、再按空白切成多条，**从不静默丢弃**（旧版按 200 字直接扔掉，
  界面还谎报「先输入要入库的提示词」）；只有"整块没有任何断点"才会被跳过，且界面会明说
  「另有 N 段过长无法断句」。
* **整条入库**：把输入框里的整段文字当作**一条**词条，存进你指定的分类（适合保存一整段负面提示词）。
* 存到哪：当前**识别到的模型族** + 当前**正面/负面** + 分类；分类不存在会自动新建。
* **「取当前文本框」**：把节点文本框里现有的提示词抓进输入框，改完再入库。
* 重复条目会被识别：批量入库会报「跳过重复 N」，单条会提示"这条已经在词库里了"。
* 护栏：写入前自动备份 `presets.json.bak-last`；写入是"临时文件 + 原子替换 + 先自校验"；
  词库当前是坏 JSON 时**拒绝写入**（绝不覆盖你正在手改的文件）；空内容 / 分类名为空 /
  超过 2000 字 / 非法模型族名都会被拒绝并在界面上说明原因。批量写入是**一次备份、一次原子写**。

### 接口（想自己脚本化时用）

```powershell
# 只分类、不写库（看看会怎么分）
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8188/smart_clip/classify `
  -ContentType 'application/json' `
  -Body '{"text":"masterpiece, 1girl, long hair, red dress, forest"}'

# 单条入库
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8188/smart_clip/presets/save `
  -ContentType 'application/json' `
  -Body '{"model":"sd15","role":"negative","category":"我的库","text":"worst quality, blurry"}'

# 拆分后批量入库（也可以直接给 text，让服务端自己分类）
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8188/smart_clip/presets/save_many `
  -ContentType 'application/json' `
  -Body '{"model":"sd15","role":"positive","text":"masterpiece, 1girl, long hair, red dress, forest"}'
```

* **改了 Python 之后必须重启 ComfyUI**：`/save`、`/save_many`、`/classify` 这些路由只在进程启动时注册。
  没重启时点入库会得到 `HTTP 405`，界面会直接提示
  「写入接口不存在（HTTP 405）—— 需要重启一次 ComfyUI 才能加载新路由」。
  更早的旧后端（响应里没有 `writable` 字段）会让入库按钮**直接置灰**并写明原因，不会让你白点。

批量导入仍然走第八节的 `import_presets.py`。

### 分类管理接口（2026-09-17 修好）

```powershell
# 新建（空）分类：左侧列表立刻出现这一行，才有对象可以右键改名/删除
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8188/smart_clip/presets/create_category `
  -ContentType 'application/json' `
  -Body '{"model":"sdxl","role":"positive","category":"我的新分类"}'

# 重命名整个分类（词条跟着走，不复制）
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8188/smart_clip/presets/rename_category `
  -ContentType 'application/json' `
  -Body '{"model":"sdxl","role":"positive","old":"其它","new":"杂物"}'

# 删除整个分类（含里面所有词条）
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8188/smart_clip/presets/delete_category `
  -ContentType 'application/json' `
  -Body '{"model":"sdxl","role":"positive","category":"我的新分类"}'

# 删除单个词条（把分类删空时，分类本身也会消失）
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8188/smart_clip/presets/delete `
  -ContentType 'application/json' `
  -Body '{"model":"sdxl","role":"positive","category":"质量词","text":"masterpiece"}'
```

* **2026-09-16 的坑（本次修复）**：`delete` / `delete_category` / `rename_category` 三条当时被追加在
  `register_routes()` 的 `return True` **之后**——装饰器永远不执行，源码看着齐全，实际是死代码，
  于是弹窗里「词条 ✕」「右键 → 重命名/删除分类」全部拿到 `HTTP 405`。
  另外空分类以前不会出现在列表里（`_normalise_role` 会把空列表丢掉），所以「+ 新建分类」建完
  当场看不到那一行，也就无从改名/删除。两处都改了。
* 回归防线：`tests/test_routes.py`（拿假 `RouteTableDef` 断言 14 条路由全部注册，并检测
  「函数体级 `return` 之后还有 `@routes` 装饰器」这种死代码；`tests/sanity_routes_catch_old_bug.py`
  会重建旧写法证明该测试确实会失败）；`tests/live_check.py` 第 2b 节对真实实例做
  新建 → 重命名 → 存词条 → 删词条 → 删分类的往返，**跑完自动还原 presets.json**。

## 十、分类规则（可以自己改）

拆分入库用的是纯关键词规则，写在：

```
<ComfyUI>\custom_nodes\ComfyUI_SmartCLIP\prompt_presets\classify_rules.json
```

```json
{
  "fallback": "其它",
  "categories": {
    "发型": ["hair", "bangs", "ponytail", "twintails", "发型", "刘海", "双马尾"],
    "衣服": ["dress", "shirt", "skirt", "uniform", "衣服", "裙", "制服"],
    "环境": ["outdoor", "forest", "city", "背景", "森林", "城市", "夜景"]
  }
}
```

* `categories`: 分类名 → 关键词数组（中英都行，**大小写无关、子串匹配**）。
* 一个词条会归到「匹配到的最长关键词」所属的分类；**完整落在词边界上的匹配优先**
  （所以 `hairband` 判成「配饰」而不是「发型」，`hairstyle` 仍然是「发型」）。
* 谁都没匹配上 → `fallback`（默认「其它」），**不会乱猜**。
* `(red dress:1.2)`、`[long hair]` 这类带权重/括号的写法会按里面的词判断；`BREAK` 会被丢掉。
* **改完保存即生效**（按文件修改时间判断，无需重启 ComfyUI）；删掉这个文件也能用，会回落到代码内置规则
  （内容与默认文件一致，单测会校验两者不脱节）。

想看看某段提示词会被怎么分：

```powershell
& 'C:\ComfyUI_windows_portable\python_embeded\python.exe' `
  C:\ComfyUI-SmartCLIP\tests\probe_classify.py "masterpiece, 1girl, long hair, red dress, forest"
```


