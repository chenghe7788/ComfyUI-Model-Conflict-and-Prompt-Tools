# ComfyUI-AutoSavePreview

> 让标准的「预览图像 PreviewImage」节点在写 temp 预览的同时，把整张图**另存一份到 output**。
> *Keep the stock preview node — but also leave a real file in `output/`.*

| | |
|---|---|
| 提供节点 | **无**（运行时接管标准 `PreviewImage`） |
| 依赖 | 无 |
| 安装目录名 | `custom_nodes\ComfyUI_AutoSavePreview` |
| 逃生开关 | 环境变量 `COMFYUI_AUTO_SAVE_PREVIEW=0` |

---

## 为什么需要它

`PreviewImage` 只把图写进 `temp\`（前端拿它做预览），**temp 每次启动都会被清空**。
于是"我只是预览一下"跑出来的图，重启之后就没了 —— 要么忘了换 `SaveImage`，要么事后找不到。
这个插件让预览节点顺手在 `output\` 留一份，命名与 `SaveImage` 同一条序列（`ComfyUI_00001_.png`），
**prompt / workflow 元数据也一起写进去**（可以直接拖回 ComfyUI 复现）。

## 怎么做到的（为什么不用改工作流）

启动时用同名类**覆盖 `nodes.PreviewImage`**，并把 `nodes.NODE_CLASS_MAPPINGS` /
`NODE_DISPLAY_NAME_MAPPINGS` 一起改写。工作流只按节点名 `PreviewImage` 引用，注册表就是唯一的真相 ——
所以**任何工作流、任何已保存的文件都不用改，也不用重开**，包括官方模板。

三个关键设计：

1. **只动标准预览节点**：包装类继承的是原类，别处继承 `PreviewImage` 的插件节点
   （impact-pack 的 `ImageSender`、rgthree 的 `ImageComparer` 等）行为完全不变，
   不会凭空多出一堆文件。
2. **两边都留**：temp 那份原样保留（前端 `type=temp` 预览流程不动），
   output 那份用干净的标准命名（**故意不带** `_temp_xxxxx` 前缀），与 `SaveImage` 共享计数序列。
3. **失败绝不连坐**：写 output 出错只会打印一行日志，预览照常返回。
   output 那份也**不会**塞进 `ui.images` —— 否则前端会渲染成"两张一模一样的图"。

## 不碰核心文件

不改 `nodes.py`，只做运行时替换。卸载 = 删掉目录，重启即恢复原生行为。

## 安装

把本目录复制到 `custom_nodes`，重启 ComfyUI：

```
<ComfyUI>\custom_nodes\ComfyUI_AutoSavePreview\
```

启动日志里会出现：

```
[AutoSavePreview] 已接管标准「预览图像」节点：预览写 temp 的同时，整图另存一份到 output (12:34:56)
[AutoSavePreview] 逃生开关: 设环境变量 COMFYUI_AUTO_SAVE_PREVIEW=0 可关闭
```

## 关掉它

```powershell
$env:COMFYUI_AUTO_SAVE_PREVIEW = "0"   # 再启动 ComfyUI
```

或直接删目录。两种方式都不影响任何工作流文件。

## 已知边界

* 每跑一次预览就多一份 output 文件，磁盘占用按你的出图量涨 —— 这是这个插件的**目的**，不是 bug。
* 它接管的是**节点类**，所以对 `--preview-method` 那类"采样过程中的潜变量预览"没有影响。
* 与其它同样覆盖 `PreviewImage` 的插件（如果有）会互相顶掉，先看启动日志确认谁最后注册。
