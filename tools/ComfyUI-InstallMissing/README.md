# ComfyUI-InstallMissing

> 扫描你的工作流 → 列出**缺失的节点类型** → 找出对应插件 → 批量下载安装；再补上缺的 Python 依赖。
> *Find the custom nodes your workflows need but your install does not have, then install them.*

| | |
|---|---|
| 类型 | 一次性排障工具（**不是** custom_nodes 插件） |
| 语言 | PowerShell + Python（用 ComfyUI 自带的 `python_embeded` 跑） |
| 平台 | Windows |

---

## 脚本清单

| 文件 | 作用 |
|---|---|
| `scan_missing.py` | 扫 `user\default\workflows\*.json`，汇总用到的节点类型，减去已注册的，输出**缺失清单**和涉及的工作流 |
| `probe_packs.py` | 用 ComfyUI 自己的注册表盘点：当前已注册多少节点类型、哪些插件包已装 |
| `probe_packs.json` | 节点类型 → 插件仓库的对照表（**人工核对过的**，不是从 Manager 数据库瞎猜的） |
| `probe_imports.py` | 在一个干净的桩环境里逐个 `import` 各插件包，定位"这个包到底为什么没注册" |
| `probe_deps.py` | 扫已装插件的 `requirements.txt`，比对当前 python 里实际装了哪些 |
| `probe_gemini_sufficiency.py` | 单个插件的专项核对（桩掉 google 依赖后真实导入，数它注册了几个节点） |
| `install_missing.ps1` | 按清单下载 zip 并解压到 `custom_nodes`（`-DryRun` 只看计划，`-InstallDeps` 顺带装依赖） |
| `install_deps.bat` | 装缺失的 Python 依赖（默认"安全集"；`--full` 追加需要编译器/CUDA 的那些） |

## 怎么用

```powershell
# 1) 先看缺什么（只读，不改任何东西）
<python_embeded>\python.exe scan_missing.py

# 2) 看装机脚本打算做什么
powershell -ExecutionPolicy Bypass -File install_missing.ps1 -DryRun

# 3) 真装（下载 + 解压到 custom_nodes）
powershell -ExecutionPolicy Bypass -File install_missing.ps1
powershell -ExecutionPolicy Bypass -File install_missing.ps1 -ComfyUI "D:\ComfyUI_windows_portable\ComfyUI"

# 4) 补 Python 依赖
install_deps.bat
```

每次运行会在脚本旁边留一个 `log-<时间戳>\` 目录，里面的 `install_result.json` 记录
每个包用了哪个 URL / 哪个分支、成功还是失败。

## 有几件事值得先知道

* **Manager 推荐的仓库不一定有你要的节点。** 典型例子：`ConcatText_Zho` / `DisplayText_Zho` 在
  Manager 数据库里被映射到某个 fork，实测那个 fork 只注册 1 个节点、**不含**这两个；
  真正有的是原作者仓库。`probe_packs.json` 就是逐个核对过之后的对照表。
* **"安装路径已存在" ≠ 已装好。** 残留的坏 `.git` 目录会让 Manager 判定成已装却加载失败，
  这种情况下要删掉重下。
* **有些包不是节点包**（比如纯工作流合集），放进 `custom_nodes` 只会每次启动刷
  `IMPORT FAILED` 噪音，应该移出去。
* **有些依赖必须由你自己在可见的控制台装**：内嵌 Python 的 `site-packages` 在沙箱里不可写，
  而且需要看到 pip 的实时输出才能判断是编译失败还是网络超时。
* `[Comfy3D]` 这类要 `git clone --recursive` + CUDA 编译的包，脚本**不会**碰 ——
  装不动就别硬装，先确认你工作流真的用到它。

## 原始报告

[`docs/REPORT.md`](docs/REPORT.md) 是当初在某一台机器上跑完之后的完整执行报告
（含每个包的来源、修过哪些上游不兼容代码、哪些依赖为什么没装）。路径与结论都绑定当时那台机器，
**当作"这类问题长什么样"的参考**，不是通用文档。
