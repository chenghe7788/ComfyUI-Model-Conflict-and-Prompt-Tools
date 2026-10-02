/**
 * SmartCLIP prompt dialog (最终增强版)
 * 功能：清空/撤销、可编辑当前提示词、词条常显删除按钮、快速新建分类、
 *      拆分入当前分类、自动分类拆分（可手动调整）、分类右键重命名/删除
 */
import {
    EMBEDDING_PREFIX,
    openEmbeddingPicker,
    closeEmbeddingPicker,
    isEmbeddingPickerOpen,
    setEmbeddingFamily,
} from "./embedding_picker.js";

const API_PRESETS = "/smart_clip/presets";
const API_SAVE = "/smart_clip/presets/save";
const API_SAVE_MANY = "/smart_clip/presets/save_many";
const API_CLASSIFY = "/smart_clip/classify";
const API_DELETE = "/smart_clip/presets/delete";
const API_RENAME_CAT = "/smart_clip/presets/rename_category";
const API_DELETE_CAT = "/smart_clip/presets/delete_category";
const API_CREATE_CAT = "/smart_clip/presets/create_category";

const MSG = {
    title: "选择提示词",
    positive: "正向",
    negative: "负面",
    search: "搜索词条（跨分类）…",
    append: "追加",
    overwrite: "覆盖",
    insert: "插入",
    weight: "权重",
    empty: "这个词库还没有词条，可以在 prompt_presets/presets.json 里添加",
    noMatch: "没有匹配的词条",
    loading: "加载中…",
    failed: "词库加载失败",
    close: "关闭",
    sourceFile: "词库文件",
    sourceBuiltin: "内置词库",
    detected: "识别架构",
    notRun: "尚未执行过节点，当前是连线预判",
    copied: "已加入",
    drop: "清空",
    undo: "撤销",
    refresh: "重新加载",
    categories: "分类",
    newCategory: "+ 新建分类",
    globalBadge: "全局",
    globalHint: "自建分类：所有工作流的提示词弹窗都能看到（正向的只进正向、反向的只进反向）",
    newCategoryDone: "已新建分类「%s」（现在是空的，已同步到所有模型族的弹窗），右键它可重命名 / 删除",
    clickToAdd: "点击加入提示词，右侧✕删除",
    embeddings: "词嵌入",
    embeddingsHint: "打开词嵌入选择器（带预览图与兼容标记），点一下就把 embedding:名字 加进提示词",
    noWidget: "找不到 text 控件",
    addTitle: "新增到词库",
    addPlaceholder: "在这里输入或粘贴提示词，Ctrl+Enter 拆分入库",
    addCategoryPlaceholder: "分类（留空 = 当前分类）",
    addWhole: "整条入库",
    addWholeHint: "把输入框里的内容当作一条词条，存进当前分类",
    addSplitCurrent: "拆分入当前分类",
    addSplitCurrentHint: "按逗号拆成词条，全部存入当前选中的分类",
    addSplitAuto: "自动分类拆分",
    addSplitAutoHint: "按逗号拆成词条，自动分到 人物 / 衣服 / 发型 / 环境 … 各分类，可手动调整",
    addConfirm: "确认入库（%s 条）",
    addCancel: "取消",
    splitting: "正在分类…",
    addPlanFailed: "分类失败",
    planReady: "已分好 %s 条，可手动调整分类，确认后写入词库",
    addSplitDone: "已入库 %s 条",
    addSaveHint: "写进 prompt_presets/presets.json，以后随时可用",
    addTake: "取当前文本框",
    addTakeHint: "把节点文本框里的内容填到这里，整理后再入库",
    addSaving: "保存中…",
    addSaved: "已入库到「%s」",
    addDuplicate: "这条已经在词库里了",
    addEmpty: "先输入要入库的提示词",
    addPlanEmpty: "拆不出任何词条：这段内容没有任何可断句的位置，请自己插入逗号或换行再试",
    addDroppedNote: "（另有 %s 段过长无法断句，已跳过）",
    addNoCategory: "请先选择或填写一个分类",
    addFailed: "入库失败",
    addNoRoute: "写入接口不存在（HTTP %s）—— 需要重启一次 ComfyUI 才能加载新路由",
    addStale: "后端还是旧版本：重启一次 ComfyUI 后即可入库",
    takeEmpty: "节点文本框是空的",
    takeDone: "已取到输入框",
    deleteConfirm: "确定删除词条「%s」吗？",
    deleteCategoryConfirm: "确定删除整个分类「%s」吗？分类下所有词条都会被删除！",
    renameCategory: "重命名分类",
    deleteEntry: "删除该词条",
    moveCategory: "移动到分类",
    clearConfirm: "确定清空当前所有提示词吗？",
    undoEmpty: "没有可撤销的操作",
    embeddingStates: {
        ok: "兼容",
        partial: "半兼容",
        incompatible: "不兼容",
        missing: "未安装",
        unknown: "未知",
    },
};

const CSS = `
.sc-overlay {
    position: fixed; inset: 0; z-index: 13000;
    background: rgba(0,0,0,.6);
    display: flex; align-items: center; justify-content: center;
    transform: none !important;
    font: 13px/1.45 system-ui, "Microsoft YaHei", sans-serif;
}
.sc-modal {
    background: #17171c; color: #e8e8ea;
    border: 1px solid rgba(255,255,255,.16); border-radius: 12px;
    width: min(1020px, 94vw); height: min(80vh, 780px);
    display: flex; flex-direction: column; overflow: hidden;
    box-shadow: 0 20px 60px rgba(0,0,0,.7);
}
.sc-head {
    display: flex; align-items: center; gap: 10px; flex-wrap: wrap;
    padding: 12px 16px; background: #1e1e24;
    border-bottom: 1px solid rgba(255,255,255,.09);
}
.sc-title { font-size: 15px; font-weight: 700; color: #4a9eff; }
.sc-meta { color: #8a8a95; }
.sc-meta b { color: #5bc27e; font-weight: 600; }
.sc-spacer { flex: 1 1 auto; }
.sc-input {
    flex: 1 1 180px; min-width: 130px; background: #101014; color: #e8e8ea;
    border: 1px solid rgba(255,255,255,.18); border-radius: 7px;
    padding: 6px 10px; font: inherit; outline: none;
}
.sc-input:focus { border-color: #4a9eff; }
.sc-btn {
    background: #26262e; border: 1px solid rgba(255,255,255,.16);
    border-radius: 7px; color: #d8d8dd; cursor: pointer;
    padding: 5px 12px; font: inherit;
}
.sc-btn:hover { background: #33333d; color: #fff; }
.sc-btn.sc-on { background: #2f4d33; border-color: #5bc27e; color: #d9ffe8; }
.sc-btn.sc-danger { background: #4d2f2f; border-color: #ff5f56; color: #ffd9d9; }
.sc-btn.sc-danger:hover { background: #5c3838; }
.sc-btn.sc-emb-open-btn { border-color: rgba(74,158,255,.55); color: #cfe4ff; }
.sc-btn.sc-emb-open-btn:hover { background: #23334d; color: #eaf3ff; }

.sc-main { flex: 1 1 auto; display: flex; min-height: 0; }
.sc-side {
    flex: 0 0 190px; display: flex; flex-direction: column; min-height: 0;
    background: #141419; border-right: 1px solid rgba(255,255,255,.09);
}
.sc-side-head {
    padding: 8px 12px 6px; color: #6f6f7c; font-size: 11px;
    text-transform: uppercase; letter-spacing: .08em;
    display: flex; justify-content: space-between; align-items: center;
}
.sc-new-cat-btn {
    background: transparent; border: none; color: #4a9eff; cursor: pointer;
    font-size: 12px; padding: 0; font-weight: 600;
}
.sc-new-cat-btn:hover { color: #7ab8ff; }
.sc-cats { flex: 1 1 auto; overflow-y: auto; padding: 0 8px 10px; }
.sc-cat {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
    width: 100%; box-sizing: border-box; text-align: left;
    background: transparent; border: 1px solid transparent; border-radius: 7px;
    color: #b8b8c2; cursor: pointer; padding: 6px 9px; font: inherit;
    word-break: break-word;
}
.sc-cat:hover { background: #202027; border-color: rgba(74,158,255,.55); color: #eaeaf0; }
.sc-cat.sc-on { background: #23334d; border-color: #4a9eff; color: #dceaff; }
.sc-cat b { color: #6f6f7c; font-weight: 500; font-size: 11px; flex: 0 0 auto; }
.sc-cat.sc-on b { color: #9fc6ff; }
.sc-cat-name { flex: 1 1 auto; min-width: 0; }
/* 全局分类（_shared）：所有工作流的弹窗都能看到 */
.sc-global {
    flex: 0 0 auto; font-size: 10px; font-weight: 700; letter-spacing: .02em;
    padding: 1px 6px; border-radius: 999px; white-space: nowrap;
    color: #8fd8ab; background: rgba(91,194,126,.14); border: 1px solid rgba(91,194,126,.4);
}
.sc-cat.sc-on .sc-global { color: #bff0d0; background: rgba(91,194,126,.22); }

.sc-right { flex: 1 1 auto; display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.sc-body { flex: 1 1 auto; overflow-y: auto; padding: 12px 14px; overscroll-behavior: contain; }
.sc-list { display: flex; flex-direction: column; gap: 5px; }
.sc-item {
    background: #202027; border: 1px solid rgba(255,255,255,.09);
    border-radius: 7px; padding: 6px 10px; cursor: pointer;
    color: #d8d8dd; word-break: break-word;
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
}
.sc-item:hover { border-color: #4a9eff; background: #262630; }
.sc-item.sc-flash { border-color: #5bc27e; background: #24322a; }
.sc-item-text { flex: 1 1 auto; }
/* 修复：删除按钮默认常显 */
.sc-item-del {
    flex: 0 0 auto; opacity: 0.8; color: #ff9c95; font-size: 14px; font-weight: bold;
    background: transparent; border: none; cursor: pointer; padding: 0 6px;
}
.sc-item-del:hover { opacity: 1; color: #ff5f56; background: rgba(255,95,86,.1); border-radius: 4px; }
.sc-hint { color: #6f6f7c; padding: 18px 4px; }

.sc-tag {
    margin-left: 8px; font-size: 10px; font-weight: 700;
    padding: 1px 7px; border-radius: 999px; white-space: nowrap;
    background: #2b2b33; color: #a9a9b4; border: 1px solid rgba(255,255,255,.16);
}
.sc-item.sc-ok .sc-tag { background: #1e3325; color: #9be2b4; border-color: #5bc27e; }
/* 半兼容：还能用，只是只有一半文本编码器吃到 —— 不置灰，给个黄标 */
.sc-item.sc-partial .sc-tag { background: #3a2f1c; color: #ffc978; border-color: #f0a132; }
.sc-item.sc-incompatible { opacity: .55; }
.sc-item.sc-incompatible .sc-tag { background: #3a1f22; color: #ff9c95; border-color: #ff5f56; }
.sc-item.sc-missing { opacity: .7; }
.sc-item.sc-missing .sc-tag { background: #2f2b1c; color: #e8d08a; border-color: #c9a227; }
.sc-item.sc-unknown .sc-tag { background: #26262e; color: #a9a9b4; }
.sc-where { margin-left: 8px; color: #6f6f7c; font-size: 11px; }

.sc-foot {
    flex: 0 0 auto; padding: 8px 16px; background: #141419;
    border-top: 1px solid rgba(255,255,255,.08);
    color: #6f6f7c; font-size: 11px;
    display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
}

.sc-add {
    flex: 0 0 auto; padding: 8px 14px 10px; background: #16161b;
    border-top: 1px solid rgba(255,255,255,.09);
    display: flex; flex-direction: column; gap: 6px;
}
.sc-add-head { display: flex; align-items: center; gap: 10px; color: #6f6f7c; font-size: 11px; }
.sc-add-status { color: #8a8a95; }
.sc-add-status.sc-ok { color: #5bc27e; }
.sc-add-status.sc-bad { color: #ff9c95; }
.sc-add-text {
    width: 100%; box-sizing: border-box; resize: vertical; min-height: 46px;
    background: #101014; color: #e8e8ea; border: 1px solid rgba(255,255,255,.18);
    border-radius: 7px; padding: 6px 9px; font: inherit; outline: none;
}
.sc-add-text:focus { border-color: #4a9eff; }
.sc-add-row { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.sc-add-cat { flex: 1 1 130px; min-width: 100px; }

.sc-plan {
    display: flex; flex-direction: column; gap: 3px;
    max-height: 132px; overflow-y: auto;
    background: #101014; border: 1px solid rgba(255,255,255,.12);
    border-radius: 7px; padding: 6px 9px;
}
.sc-plan:empty { display: none; }
.sc-plan-line { display: flex; gap: 8px; align-items: center; font-size: 12px; padding: 2px 0; }
.sc-plan-cat { flex: 0 0 110px; }
.sc-plan-cat select {
    width: 100%; background: #1a1a20; color: #4a9eff; border: 1px solid rgba(255,255,255,.15);
    border-radius: 4px; padding: 2px 4px; font: inherit;
}
.sc-plan-tags { color: #b8b8c2; word-break: break-word; flex: 1 1 auto; }
.sc-btn.sc-primary { background: #23402c; border-color: #5bc27e; color: #d9ffe8; }
.sc-btn.sc-primary:hover { background: #2c5138; }
.sc-btn[disabled] { opacity: .55; cursor: default; }
.sc-preview {
    padding: 8px 16px; background: #101014; border-top: 1px solid rgba(255,255,255,.06);
}
.sc-preview textarea {
    width: 100%; box-sizing: border-box; min-height: 60px; max-height: 120px;
    background: #16161b; color: #e8e8ea; border: 1px solid rgba(255,255,255,.12);
    border-radius: 7px; padding: 6px 9px; font: inherit; outline: none; resize: vertical;
}
.sc-preview textarea:focus { border-color: #4a9eff; }
.sc-preview-label { color: #6f6f7c; font-size: 11px; margin-bottom: 4px; }
.sc-weight { display: flex; align-items: center; gap: 8px; color: #8a8a95; }
.sc-weight input { width: 110px; accent-color: #4a9eff; }
.sc-context-menu {
    position: fixed; z-index: 13001; background: #1e1e24;
    border: 1px solid rgba(255,255,255,.16); border-radius: 8px;
    padding: 4px; box-shadow: 0 8px 24px rgba(0,0,0,.5);
    min-width: 140px;
}
.sc-context-menu-item {
    padding: 6px 12px; border-radius: 5px; cursor: pointer;
    color: #d8d8dd; font-size: 12px;
}
.sc-context-menu-item:hover { background: #2a2a33; color: #fff; }
.sc-context-menu-item.sc-danger { color: #ff9c95; }
.sc-context-menu-item.sc-danger:hover { background: #3a1f22; }
`;

let cssInjected = false;
function injectCss() {
    if (cssInjected) return;
    const style = document.createElement("style");
    style.textContent = CSS;
    document.head.appendChild(style);
    cssInjected = true;
}

function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = String(text);
    return node;
}

export function readWidget(widget) {
    const raw = widget?.value;
    if (raw == null) return "";
    if (typeof raw === "string") return raw;
    if (typeof raw === "object" && typeof raw.content === "string") return raw.content;
    return String(raw);
}

export function writeWidget(widget, value) {
    if (!widget) return false;
    try {
        const raw = widget.value;
        if (raw !== null && typeof raw === "object" && "content" in raw) {
            widget.value = Object.assign({}, raw, { content: value });
        } else {
            widget.value = value;
        }
        const element = widget.element || widget.inputEl || widget.textarea;
        if (element && typeof element === "object" && "value" in element) {
            element.value = value;
            element.dispatchEvent?.(new Event("input", { bubbles: true }));
            element.dispatchEvent?.(new Event("change", { bubbles: true }));
        }
        widget.callback?.(value);
        return true;
    } catch (err) {
        console.warn("[SmartCLIP] writeWidget failed:", err);
        return false;
    }
}

function findTextWidget(node) {
    const widgets = node?.widgets || [];
    return widgets.find((w) => w?.name === "text")
        || widgets.find((w) => w?.type === "customtext" || w?.type === "text")
        || null;
}

function joinPrompt(existing, addition, mode, weight) {
    const word = Math.abs(weight - 1) < 1e-6 ? addition : `(${addition}:${weight})`;
    const trimmed = String(existing || "").replace(/\s+$/, "");
    if (mode === "overwrite" || !trimmed) return word;
    const separator = /[,\n]$/.test(trimmed) ? " " : ", ";
    return trimmed + separator + word;
}

function annotationTag(annotation) {
    if (!annotation) return "";
    const state = annotation.state || "unknown";
    const label = MSG.embeddingStates[state] || state;
    // 没有可用的架构短标签时只写状态：missing 的 short 就是"未安装"，
    // unknown 的 short 是 "TI-?"（带上只会显示成「TI-? · 未知」）。
    if (state === "missing" || state === "unknown") return label;
    const short = annotation.short && annotation.short !== "?" ? `${annotation.short} · ` : "";
    return `${short}${label}`;
}

export class PromptDialog {
    static async open(node, model, role) {
        if (PromptDialog._current) {
            PromptDialog._current.close();
        }
        const dialog = new PromptDialog(node, model, role);
        PromptDialog._current = dialog;
        await dialog.start();
        return dialog;
    }

    constructor(node, model, role) {
        this.node = node;
        this.model = model || { preset: "generic", family: "unknown", label: "" };
        this.role = role === "negative" ? "negative" : "positive";
        this.mode = "append";
        this.weight = 1.0;
        this.categories = {};
        this.annotations = {};
        this.embeddingStats = {};
        this.shared = new Set();
        this.activeCategory = "";
        this.query = "";
        this.closed = false;
        this.history = [];
        this.maxHistory = 10;
    }

    async start() {
        injectCss();
        this.build();
        await this.reload();
    }

    build() {
        const overlay = el("div", "sc-overlay");
        this.overlay = overlay;
        overlay.addEventListener("pointerdown", (event) => {
            if (event.target === overlay) this.close();
        });

        const modal = el("div", "sc-modal");
        overlay.appendChild(modal);

        const head = el("div", "sc-head");
        head.appendChild(el("div", "sc-title", MSG.title));

        this.metaEl = el("div", "sc-meta", "");
        head.appendChild(this.metaEl);

        head.appendChild(el("div", "sc-spacer"));

        this.positiveBtn = el("button", "sc-btn", MSG.positive);
        this.positiveBtn.addEventListener("click", () => this.setRole("positive"));
        this.negativeBtn = el("button", "sc-btn", MSG.negative);
        this.negativeBtn.addEventListener("click", () => this.setRole("negative"));
        head.appendChild(this.positiveBtn);
        head.appendChild(this.negativeBtn);

        this.modeBtn = el("button", "sc-btn", MSG.append);
        this.modeBtn.title = "点击切换：追加 / 覆盖";
        this.modeBtn.addEventListener("click", () => {
            this.mode = this.mode === "append" ? "overwrite" : "append";
            this.modeBtn.textContent = this.mode === "append" ? MSG.append : MSG.overwrite;
        });
        head.appendChild(this.modeBtn);

        this.undoBtn = el("button", "sc-btn", MSG.undo);
        this.undoBtn.title = "撤销上一次插入（Ctrl+Z）";
        this.undoBtn.addEventListener("click", () => this.undo());
        head.appendChild(this.undoBtn);

        this.clearBtn = el("button", "sc-btn sc-danger", MSG.drop);
        this.clearBtn.title = "清空当前所有提示词";
        this.clearBtn.addEventListener("click", () => this.clearText());
        head.appendChild(this.clearBtn);

        this.embedBtn = el("button", "sc-btn sc-emb-open-btn", MSG.embeddings);
        this.embedBtn.type = "button";
        this.embedBtn.title = MSG.embeddingsHint;
        this.embedBtn.addEventListener("click", () => this.openEmbeddingPicker());
        head.appendChild(this.embedBtn);

        this.searchEl = el("input", "sc-input");
        this.searchEl.type = "text";
        this.searchEl.placeholder = MSG.search;
        this.searchEl.addEventListener("input", () => {
            this.query = this.searchEl.value.trim().toLowerCase();
            this.renderList();
        });
        this.searchEl.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                const first = this.visiblePrompts()[0];
                if (first) this.pick(first);
            }
            event.stopPropagation();
        });
        head.appendChild(this.searchEl);

        const reloadBtn = el("button", "sc-btn", MSG.refresh);
        reloadBtn.addEventListener("click", () => this.reload(true));
        head.appendChild(reloadBtn);

        const closeBtn = el("button", "sc-btn", "✕");
        closeBtn.title = MSG.close;
        closeBtn.addEventListener("click", () => this.close());
        head.appendChild(closeBtn);

        const weightWrap = el("div", "sc-weight");
        weightWrap.appendChild(el("span", null, MSG.weight));
        this.weightEl = el("input", null);
        this.weightEl.type = "range";
        this.weightEl.min = "0.1";
        this.weightEl.max = "2";
        this.weightEl.step = "0.05";
        this.weightEl.value = "1";
        this.weightLabel = el("span", null, "1.00");
        this.weightEl.addEventListener("input", () => {
            this.weight = Number(this.weightEl.value);
            this.weightLabel.textContent = this.weight.toFixed(2);
        });
        weightWrap.appendChild(this.weightEl);
        weightWrap.appendChild(this.weightLabel);
        head.appendChild(weightWrap);

        const main = el("div", "sc-main");

        const side = el("div", "sc-side");
        const sideHead = el("div", "sc-side-head");
        sideHead.appendChild(el("span", null, MSG.categories));
        const newCatBtn = el("button", "sc-new-cat-btn", MSG.newCategory);
        newCatBtn.addEventListener("click", () => this.newCategory());
        sideHead.appendChild(newCatBtn);
        side.appendChild(sideHead);
        this.catsEl = el("div", "sc-cats");
        side.appendChild(this.catsEl);

        const right = el("div", "sc-right");
        this.bodyEl = el("div", "sc-body");
        this.previewBox = el("div", "sc-preview");
        this.previewBox.appendChild(el("div", "sc-preview-label", "当前提示词（可直接编辑）"));
        this.previewEl = el("textarea");
        this.previewEl.placeholder = "提示词为空";
        this.previewEl.addEventListener("input", () => {
            const widget = findTextWidget(this.node);
            if (widget) writeWidget(widget, this.previewEl.value);
        });
        this.previewBox.appendChild(this.previewEl);
        this.addBox = this.buildAddBox();
        right.appendChild(this.bodyEl);
        right.appendChild(this.previewBox);
        right.appendChild(this.addBox);

        main.appendChild(side);
        main.appendChild(right);

        const foot = el("div", "sc-foot");
        this.footEl = el("span", null, "");
        foot.appendChild(this.footEl);

        modal.appendChild(head);
        modal.appendChild(main);
        modal.appendChild(foot);

        document.body.appendChild(overlay);

        this.onKey = (event) => {
            if (event.key === "Escape") {
                event.stopPropagation();
                if (isEmbeddingPickerOpen()) {
                    closeEmbeddingPicker();
                    return;
                }
                this.close();
            }
            if ((event.ctrlKey || event.metaKey) && event.key === "z") {
                event.preventDefault();
                this.undo();
            }
        };
        document.addEventListener("keydown", this.onKey, true);
        document.addEventListener("click", () => this.closeContextMenu());

        this.renderMeta();
        this.updateUndoBtn();
        setTimeout(() => this.searchEl?.focus(), 0);
    }

    renderMeta() {
        this.metaEl.textContent = "";
        const label = this.model.label || this.model.family || "未识别";
        this.metaEl.append(`${MSG.detected}: `);
        this.metaEl.appendChild(el("b", null, label));
        if (this.model.name) this.metaEl.append(` · ${this.model.name}`);
        const note = this.model.runtimeSeen ? "" : ` · ${MSG.notRun}`;
        if (note) this.metaEl.append(note);
    }

    /**
     * The base model changed under an open dialog.
     *
     * A checkpoint switch is a widget change, which fires no connection
     * callback, so the tracker is re-read when the button is clicked; whatever
     * it learned lands here.  An open embedding picker re-judges its badges
     * instead of keeping the previous model's verdicts.
     */
    setModel(model) {
        if (!model) return;
        this.model = model;
        this.renderMeta();
        if (isEmbeddingPickerOpen()) {
            setEmbeddingFamily(model.preset || "");
        }
    }

    setRole(role) {
        this.role = role;
        const widget = (this.node?.widgets || []).find((w) => w?.name === "prompt_role");
        if (widget) widget.value = role;
        this.reload();
    }

    async reload(force = false) {
        this.footEl.textContent = MSG.loading;
        this.bodyEl.textContent = "";
        this.bodyEl.appendChild(el("div", "sc-hint", MSG.loading));
        try {
            const url = `${API_PRESETS}?model=${encodeURIComponent(this.model.preset || "generic")}` +
                `&role=${encodeURIComponent(this.role)}${force ? `&_=${Date.now()}` : ""}`;
            const res = await fetch(url);
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const data = await res.json();
            this.categories = data.categories || {};
            this.annotations = data.annotations || {};
            this.embeddingStats = data.embedding_stats || {};
            // 后端标出的全局分类（自建的那些）：所有工作流的弹窗都能看到
            this.shared = new Set(Array.isArray(data.shared) ? data.shared : []);
            this.writable = data.writable === true;
            this.activeCategory = Object.keys(this.categories)[0] || "";
            const source = data.source === "file" ? MSG.sourceFile : MSG.sourceBuiltin;
            this.footEl.textContent = `${source} · ${data.model} / ${data.role}` +
                ` · ${Object.keys(this.categories).length} 个分类${this.embeddingNote()}`;
        } catch (err) {
            console.warn("[SmartCLIP] presets failed:", err);
            this.categories = {};
            this.annotations = {};
            this.embeddingStats = {};
            this.shared = new Set();
            this.activeCategory = "";
            this.footEl.textContent = MSG.failed;
            this.bodyEl.textContent = "";
            this.bodyEl.appendChild(el("div", "sc-hint", `${MSG.failed}: ${err.message || err}`));
        }
        this.renderCats();
        this.renderList();
        this.renderPreview();
        this.renderRoleButtons();
        this.applyWritable();
    }

    applyWritable() {
        const ok = this.writable === true;
        for (const button of [this.splitBtn, this.splitCurrentBtn, this.wholeBtn]) {
            if (button) button.disabled = !ok;
        }
        if (!ok) this.setAddStatus(MSG.addStale, "bad");
    }

    embeddingNote() {
        const stats = this.embeddingStats || {};
        if (!stats.total) return "";
        const parts = [];
        if (stats.ok) parts.push(`${stats.ok} 可用`);
        if (stats.partial) parts.push(`${stats.partial} 半兼容`);
        if (stats.incompatible) parts.push(`${stats.incompatible} 不兼容`);
        if (stats.missing) parts.push(`${stats.missing} 未安装`);
        if (stats.unknown) parts.push(`${stats.unknown} 未知`);
        return ` · 词嵌入 ${parts.join(" / ") || stats.total}`;
    }

    renderRoleButtons() {
        this.positiveBtn.classList.toggle("sc-on", this.role === "positive");
        this.negativeBtn.classList.toggle("sc-on", this.role === "negative");
    }

    buildAddBox() {
        const box = el("div", "sc-add");

        const head = el("div", "sc-add-head");
        head.appendChild(el("span", null, MSG.addTitle));
        this.addStatusEl = el("span", "sc-add-status", "");
        head.appendChild(this.addStatusEl);
        box.appendChild(head);

        this.newTextEl = el("textarea", "sc-add-text");
        this.newTextEl.rows = 2;
        this.newTextEl.placeholder = MSG.addPlaceholder;
        this.newTextEl.addEventListener("keydown", (event) => {
            event.stopPropagation();
            if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                event.preventDefault();
                this.splitEntry();
            }
        });
        box.appendChild(this.newTextEl);

        this.planEl = el("div", "sc-plan");
        box.appendChild(this.planEl);

        const row = el("div", "sc-add-row");
        this.newCatEl = el("input", "sc-input sc-add-cat");
        this.newCatEl.type = "text";
        this.newCatEl.placeholder = MSG.addCategoryPlaceholder;
        this.newCatEl.addEventListener("keydown", (event) => {
            event.stopPropagation();
            if (event.key === "Enter") {
                event.preventDefault();
                this.saveEntry();
            }
        });
        row.appendChild(this.newCatEl);

        this.takeBtn = el("button", "sc-btn", MSG.addTake);
        this.takeBtn.title = MSG.addTakeHint;
        this.takeBtn.addEventListener("click", () => this.takeFromNode());
        row.appendChild(this.takeBtn);

        this.wholeBtn = el("button", "sc-btn", MSG.addWhole);
        this.wholeBtn.title = MSG.addWholeHint;
        this.wholeBtn.addEventListener("click", () => this.saveEntry());
        row.appendChild(this.wholeBtn);

        // 新增：拆分入当前分类按钮
        this.splitCurrentBtn = el("button", "sc-btn", MSG.addSplitCurrent);
        this.splitCurrentBtn.title = MSG.addSplitCurrentHint;
        this.splitCurrentBtn.addEventListener("click", () => this.splitToCurrentCategory());
        row.appendChild(this.splitCurrentBtn);

        // 自动分类拆分按钮
        this.splitBtn = el("button", "sc-btn sc-primary", MSG.addSplitAuto);
        this.splitBtn.title = MSG.addSplitAutoHint;
        this.splitBtn.addEventListener("click", () => this.splitEntry());
        row.appendChild(this.splitBtn);

        this.cancelBtn = el("button", "sc-btn", MSG.addCancel);
        this.cancelBtn.addEventListener("click", () => this.clearPlan());
        this.cancelBtn.style.display = "none";
        row.appendChild(this.cancelBtn);

        box.appendChild(row);
        return box;
    }

    setAddStatus(text, kind = "") {
        if (!this.addStatusEl) return;
        this.addStatusEl.textContent = text;
        this.addStatusEl.className = kind ? `sc-add-status sc-${kind}` : "sc-add-status";
    }

    syncAddHint() {
        if (!this.newCatEl) return;
        const active = this.activeCategory || "";
        this.newCatEl.placeholder = active
            ? `${active}（留空 = 当前分类）`
            : MSG.addCategoryPlaceholder;
    }

    takeFromNode() {
        const widget = findTextWidget(this.node);
        const text = readWidget(widget).trim();
        if (!text) {
            this.setAddStatus(MSG.takeEmpty, "bad");
            return;
        }
        if (this.newTextEl) this.newTextEl.value = text;
        this.setAddStatus(MSG.takeDone, "ok");
    }

    async saveEntry() {
        const text = String(this.newTextEl?.value || "").trim();
        const category = String(this.newCatEl?.value || "").trim() || this.activeCategory;
        if (this.writable !== true) {
            this.setAddStatus(MSG.addStale, "bad");
            return;
        }
        if (!text) {
            this.setAddStatus(MSG.addEmpty, "bad");
            this.newTextEl?.focus?.();
            return;
        }
        if (!category) {
            this.setAddStatus(MSG.addNoCategory, "bad");
            return;
        }

        if (this.wholeBtn) this.wholeBtn.disabled = true;
        this.setAddStatus(MSG.addSaving);
        try {
            const res = await fetch(API_SAVE, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    model: this.model.preset || "generic",
                    role: this.role,
                    category,
                    text,
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || data.ok === false) {
                const failure = new Error(data.error || `HTTP ${res.status}`);
                failure.status = res.status;
                throw failure;
            }
            if (data.duplicate) {
                this.setAddStatus(MSG.addDuplicate);
                return;
            }

            if (this.newTextEl) this.newTextEl.value = "";
            this.setAddStatus(MSG.addSaved.replace("%s", category), "ok");

            await this.reload(true);
            if (Object.prototype.hasOwnProperty.call(this.categories, category)) {
                this.activeCategory = category;
                this.renderCats();
                this.renderList();
            }
        } catch (err) {
            console.warn("[SmartCLIP] save to library failed:", err);
            if (err?.status === 404 || err?.status === 405) {
                this.setAddStatus(MSG.addNoRoute.replace("%s", String(err.status)), "bad");
            } else {
                this.setAddStatus(`${MSG.addFailed}: ${err.message || err}`, "bad");
            }
        } finally {
            if (this.wholeBtn) this.wholeBtn.disabled = this.writable !== true;
        }
    }

    /** 新增：拆分入当前分类，全部存入当前选中的分类 */
    async splitToCurrentCategory() {
        if (this.writable !== true) {
            this.setAddStatus(MSG.addStale, "bad");
            return;
        }
        const text = String(this.newTextEl?.value || "").trim();
        if (!text) {
            this.setAddStatus(MSG.addEmpty, "bad");
            this.newTextEl?.focus?.();
            return;
        }
        const category = this.activeCategory || String(this.newCatEl?.value || "").trim();
        if (!category) {
            this.setAddStatus("请先在左侧选择一个分类，或在分类输入框填写分类名", "bad");
            return;
        }

        // 按逗号/换行拆分，去重，过滤空
        const tags = [...new Set(text.split(/[,\n\r]+/).map(t => t.trim()).filter(t => t))];
        if (!tags.length) {
            this.setAddStatus(MSG.addEmpty, "bad");
            return;
        }

        if (this.splitCurrentBtn) this.splitCurrentBtn.disabled = true;
        this.setAddStatus(MSG.addSaving);
        try {
            const entries = tags.map(t => ({ category, text: t }));
            const res = await fetch(API_SAVE_MANY, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    model: this.model.preset || "generic",
                    role: this.role,
                    entries,
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || data.ok === false) {
                const failure = new Error(data.error || `HTTP ${res.status}`);
                failure.status = res.status;
                throw failure;
            }

            const duplicateNote = data.duplicates ? `，跳过重复 ${data.duplicates}` : "";
            this.setAddStatus(
                `已入库 ${data.added || 0} 条到「${category}」` + duplicateNote,
                "ok");

            if (this.newTextEl) this.newTextEl.value = "";
            await this.reload(true);
            if (Object.prototype.hasOwnProperty.call(this.categories, category)) {
                this.activeCategory = category;
                this.renderCats();
                this.renderList();
            }
        } catch (err) {
            console.warn("[SmartCLIP] split to current failed:", err);
            if (err?.status === 404 || err?.status === 405) {
                this.setAddStatus(MSG.addNoRoute.replace("%s", String(err.status)), "bad");
            } else {
                this.setAddStatus(`${MSG.addFailed}: ${err.message || err}`, "bad");
            }
        } finally {
            if (this.splitCurrentBtn) this.splitCurrentBtn.disabled = this.writable !== true;
        }
    }

    async splitEntry() {
        if (this.plan) {
            await this.savePlan();
            return;
        }
        if (this.writable !== true) {
            this.setAddStatus(MSG.addStale, "bad");
            return;
        }
        const text = String(this.newTextEl?.value || "").trim();
        if (!text) {
            this.setAddStatus(MSG.addEmpty, "bad");
            this.newTextEl?.focus?.();
            return;
        }

        if (this.splitBtn) this.splitBtn.disabled = true;
        this.setAddStatus(MSG.splitting);
        try {
            const res = await fetch(API_CLASSIFY, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text, model: this.model.preset || "generic" }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || data.ok === false) {
                const failure = new Error(data.error || `HTTP ${res.status}`);
                failure.status = res.status;
                throw failure;
            }
            const tags = (data.tags || []).filter((item) => item && item.text);
            const dropped = Array.isArray(data.dropped) ? data.dropped.length : 0;
            if (!tags.length) {
                // A box that is not empty must never be reported as empty: when the
                // backend had to skip unbreakable chunks, say so instead.
                this.setAddStatus(dropped ? MSG.addPlanEmpty : MSG.addEmpty, "bad");
                return;
            }
            this.plan = { tags, counts: data.counts || {}, total: tags.length, dropped };
            this.renderPlan();
            this.setAddStatus(
                MSG.planReady.replace("%s", String(tags.length))
                + (dropped ? MSG.addDroppedNote.replace("%s", String(dropped)) : ""));
        } catch (err) {
            console.warn("[SmartCLIP] classify failed:", err);
            if (err?.status === 404 || err?.status === 405) {
                this.setAddStatus(MSG.addNoRoute.replace("%s", String(err.status)), "bad");
            } else {
                this.setAddStatus(`${MSG.addPlanFailed}: ${err.message || err}`, "bad");
            }
        } finally {
            if (this.splitBtn) this.splitBtn.disabled = this.writable !== true;
        }
    }

    renderPlan() {
        if (!this.planEl) return;
        this.planEl.textContent = "";
        if (!this.plan) return;
        const categories = Object.keys(this.categories);
        for (let i = 0; i < this.plan.tags.length; i++) {
            const item = this.plan.tags[i];
            const line = el("div", "sc-plan-line");
            const catWrap = el("div", "sc-plan-cat");
            const select = el("select");
            for (const cat of categories) {
                const opt = el("option", null, cat);
                opt.value = cat;
                if (cat === item.category) opt.selected = true;
                select.appendChild(opt);
            }
            if (!categories.includes(item.category)) {
                const opt = el("option", null, item.category);
                opt.value = item.category;
                opt.selected = true;
                select.appendChild(opt);
            }
            select.addEventListener("change", () => {
                this.plan.tags[i].category = select.value;
            });
            catWrap.appendChild(select);
            line.appendChild(catWrap);
            line.appendChild(el("span", "sc-plan-tags", item.text));
            this.planEl.appendChild(line);
        }
        if (this.splitBtn) this.splitBtn.textContent = MSG.addConfirm.replace("%s", String(this.plan.tags.length));
        if (this.cancelBtn) this.cancelBtn.style.display = "";
        if (this.wholeBtn) this.wholeBtn.disabled = true;
        if (this.splitCurrentBtn) this.splitCurrentBtn.disabled = true;
    }

    clearPlan() {
        this.plan = null;
        if (this.planEl) this.planEl.textContent = "";
        if (this.splitBtn) this.splitBtn.textContent = MSG.addSplitAuto;
        if (this.cancelBtn) this.cancelBtn.style.display = "none";
        if (this.wholeBtn) this.wholeBtn.disabled = this.writable !== true;
        if (this.splitCurrentBtn) this.splitCurrentBtn.disabled = this.writable !== true;
    }

    async savePlan() {
        const entries = (this.plan?.tags || []).map((item) => ({
            category: item.category,
            text: item.text,
        }));
        if (!entries.length) return;

        if (this.splitBtn) this.splitBtn.disabled = true;
        this.setAddStatus(MSG.addSaving);
        try {
            const res = await fetch(API_SAVE_MANY, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    model: this.model.preset || "generic",
                    role: this.role,
                    entries,
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || data.ok === false) {
                const failure = new Error(data.error || `HTTP ${res.status}`);
                failure.status = res.status;
                throw failure;
            }

            const parts = Object.entries(data.categories || {})
                .map(([name, count]) => `${name} ${count}`);
            const duplicateNote = data.duplicates ? `，跳过重复 ${data.duplicates}` : "";
            this.setAddStatus(
                MSG.addSplitDone.replace("%s", String(data.added || 0))
                + (parts.length ? `：${parts.join(" / ")}` : "") + duplicateNote,
                "ok");

            this.clearPlan();
            if (this.newTextEl) this.newTextEl.value = "";
            await this.reload(true);
            const first = entries[0].category;
            if (Object.prototype.hasOwnProperty.call(this.categories, first)) {
                this.activeCategory = first;
                this.renderCats();
                this.renderList();
            }
        } catch (err) {
            console.warn("[SmartCLIP] batch save failed:", err);
            if (err?.status === 404 || err?.status === 405) {
                this.setAddStatus(MSG.addNoRoute.replace("%s", String(err.status)), "bad");
            } else {
                this.setAddStatus(`${MSG.addFailed}: ${err.message || err}`, "bad");
            }
        } finally {
            if (this.splitBtn) this.splitBtn.disabled = this.writable !== true;
        }
    }

    renderCats() {
        this.catsEl.textContent = "";
        for (const name of Object.keys(this.categories)) {
            const row = el("button", "sc-cat");
            row.appendChild(el("span", "sc-cat-name", name));
            if (this.shared?.has?.(name)) {
                const badge = el("span", "sc-global", MSG.globalBadge);
                badge.title = MSG.globalHint;
                row.appendChild(badge);
            }
            row.appendChild(el("b", null, String((this.categories[name] || []).length)));
            if (name === this.activeCategory) row.classList.add("sc-on");
            row.title = (this.shared?.has?.(name) ? `${name}（${MSG.globalHint}）` : name)
                + "（右键重命名/删除）";
            row.addEventListener("click", () => {
                this.activeCategory = name;
                this.query = "";
                if (this.searchEl) this.searchEl.value = "";
                this.renderCats();
                this.renderList();
            });
            row.addEventListener("contextmenu", (e) => {
                e.preventDefault();
                this.showCategoryMenu(e, name);
            });
            this.catsEl.appendChild(row);
        }
        this.syncAddHint();
    }

    entry(text, category) {
        const value = String(text);
        return {
            text: value,
            category,
            annotation: this.annotations[value] || null,
        };
    }

    visiblePrompts() {
        const names = Object.keys(this.categories);
        if (!this.query) {
            const active = this.categories[this.activeCategory] || [];
            return active.map((text) => this.entry(text, this.activeCategory));
        }
        const out = [];
        for (const name of names) {
            for (const text of this.categories[name] || []) {
                if (String(text).toLowerCase().includes(this.query)) {
                    out.push(this.entry(text, name));
                }
            }
        }
        return out;
    }

    renderList() {
        this.bodyEl.textContent = "";
        const entries = this.visiblePrompts();
        if (!entries.length) {
            const hint = this.query ? MSG.noMatch : (Object.keys(this.categories).length ? MSG.empty : MSG.loading);
            this.bodyEl.appendChild(el("div", "sc-hint", hint));
            this.renderPreview();
            return;
        }
        const list = el("div", "sc-list");
        for (const entry of entries) {
            const item = el("div", "sc-item");
            const textWrap = el("div", "sc-item-text");
            textWrap.textContent = entry.text;
            const tag = annotationTag(entry.annotation);
            if (tag) {
                item.classList.add(`sc-${entry.annotation.state || "unknown"}`);
                textWrap.appendChild(el("span", "sc-tag", tag));
                item.title = entry.annotation.why || MSG.clickToAdd;
            } else {
                item.title = MSG.clickToAdd;
            }
            if (this.query) {
                textWrap.appendChild(el("span", "sc-where", `· ${entry.category}`));
            }
            item.appendChild(textWrap);
            // 删除按钮常显
            const delBtn = el("button", "sc-item-del", "✕");
            delBtn.title = "删除该词条";
            delBtn.addEventListener("click", (e) => {
                e.stopPropagation();
                this.deleteEntry(entry);
            });
            item.appendChild(delBtn);
            item.addEventListener("click", () => this.pick(entry, item));
            list.appendChild(item);
        }
        this.bodyEl.appendChild(list);
    }

    pushHistory() {
        const widget = findTextWidget(this.node);
        const text = readWidget(widget);
        this.history.push(text);
        if (this.history.length > this.maxHistory) this.history.shift();
        this.updateUndoBtn();
    }

    undo() {
        if (!this.history.length) {
            this.footEl.textContent = MSG.undoEmpty;
            return;
        }
        const last = this.history.pop();
        const widget = findTextWidget(this.node);
        writeWidget(widget, last);
        this.renderPreview();
        this.updateUndoBtn();
        this.footEl.textContent = "已撤销上一步操作";
    }

    updateUndoBtn() {
        if (this.undoBtn) {
            this.undoBtn.disabled = this.history.length === 0;
        }
    }

    clearText() {
        if (!confirm(MSG.clearConfirm)) return;
        this.pushHistory();
        const widget = findTextWidget(this.node);
        writeWidget(widget, "");
        this.renderPreview();
        this.footEl.textContent = "已清空提示词";
    }

    appendText(text, category = null) {
        const widget = findTextWidget(this.node);
        if (!widget) {
            this.footEl.textContent = MSG.noWidget;
            return false;
        }
        this.pushHistory();
        const next = joinPrompt(readWidget(widget), text, this.mode, this.weight);
        if (!writeWidget(widget, next)) {
            this.footEl.textContent = MSG.noWidget;
            return false;
        }
        if (category) {
            const categoryWidget = (this.node?.widgets || []).find((w) => w?.name === "prompt_category");
            if (categoryWidget) categoryWidget.value = category;
        }
        this.renderPreview();
        this.footEl.textContent = `${MSG.copied}: ${text}`;
        return true;
    }

    openEmbeddingPicker() {
        openEmbeddingPicker({
            family: this.model.preset || "",
            role: this.role,
            getText: () => readWidget(findTextWidget(this.node)),
            setText: (text) => this.appendTextRaw(text),
            onPick: (name) => this.addEmbedding(name),
        });
    }

    addEmbedding(name) {
        return this.appendText(`${EMBEDDING_PREFIX}${name}`);
    }

    appendTextRaw(text) {
        const widget = findTextWidget(this.node);
        if (!widget) return false;
        this.pushHistory();
        const ok = writeWidget(widget, String(text));
        this.renderPreview();
        return ok;
    }

    pick(entry, item) {
        const prompt = typeof entry === "string" ? entry : entry.text;
        const category = typeof entry === "string" ? this.activeCategory : entry.category;
        if (!this.appendText(prompt, category)) return;

        if (item) {
            item.classList.add("sc-flash");
            setTimeout(() => item.classList?.remove("sc-flash"), 500);
        }
    }

    renderPreview() {
        const widget = findTextWidget(this.node);
        const text = readWidget(widget);
        if (this.previewEl) {
            this.previewEl.value = text || "";
        }
    }

    async newCategory() {
        const name = prompt("请输入新分类名称：");
        if (!name?.trim()) return;
        const category = name.trim();
        if (this.newCatEl) this.newCatEl.value = category;
        this.setAddStatus(`正在新建分类「${category}」…`);
        try {
            const res = await fetch(API_CREATE_CAT, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    model: this.model.preset || "generic",
                    role: this.role,
                    category,
                }),
            });
            const data = await res.json().catch(() => ({}));
            if (!res.ok || data.ok === false) {
                const failure = new Error(data.error || `HTTP ${res.status}`);
                failure.status = res.status;
                throw failure;
            }
            this.query = "";
            if (this.searchEl) this.searchEl.value = "";
            await this.reload(true);
            if (Object.prototype.hasOwnProperty.call(this.categories, category)) {
                this.activeCategory = category;
            }
            this.renderCats();
            this.renderList();
            this.setAddStatus(
                data.created === false
                    ? `分类「${category}」已存在，已切换过去`
                    : MSG.newCategoryDone.replace("%s", category),
                "ok");
        } catch (err) {
            console.warn("[SmartCLIP] create category failed:", err);
            if (err?.status === 404 || err?.status === 405) {
                this.setAddStatus(MSG.addNoRoute.replace("%s", String(err.status)), "bad");
            } else {
                this.setAddStatus(`新建分类失败：${err.message || err}`, "bad");
            }
        }
    }

    async deleteEntry(entry) {
        if (!confirm(MSG.deleteConfirm.replace("%s", entry.text))) return;
        try {
            const res = await fetch(API_DELETE, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    model: this.model.preset || "generic",
                    role: this.role,
                    category: entry.category,
                    text: entry.text,
                }),
            });
            const data = await res.json();
            if (!res.ok || data.ok === false) throw new Error(data.error || "删除失败");
            this.footEl.textContent = `已删除词条：${entry.text}`;
            await this.reload(true);
        } catch (err) {
            alert(`删除失败：${err.message || err}`);
        }
    }

    showCategoryMenu(e, category) {
        this.closeContextMenu();
        const menu = el("div", "sc-context-menu");
        menu.style.left = e.pageX + "px";
        menu.style.top = e.pageY + "px";

        const renameItem = el("div", "sc-context-menu-item", MSG.renameCategory);
        renameItem.addEventListener("click", () => {
            this.renameCategory(category);
            this.closeContextMenu();
        });
        menu.appendChild(renameItem);

        const deleteItem = el("div", "sc-context-menu-item sc-danger", "删除分类");
        deleteItem.addEventListener("click", () => {
            this.deleteCategory(category);
            this.closeContextMenu();
        });
        menu.appendChild(deleteItem);

        document.body.appendChild(menu);
        this.contextMenu = menu;
    }

    closeContextMenu() {
        if (this.contextMenu) {
            this.contextMenu.remove();
            this.contextMenu = null;
        }
    }

    async renameCategory(oldName) {
        const newName = prompt(`重命名分类「${oldName}」为：`, oldName);
        if (!newName?.trim() || newName.trim() === oldName) return;
        try {
            const res = await fetch(API_RENAME_CAT, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    model: this.model.preset || "generic",
                    role: this.role,
                    old: oldName,
                    new: newName.trim(),
                }),
            });
            const data = await res.json();
            if (!res.ok || data.ok === false) throw new Error(data.error || "重命名失败");
            if (this.activeCategory === oldName) this.activeCategory = newName.trim();
            this.footEl.textContent = `已重命名分类：${oldName} → ${newName.trim()}`;
            await this.reload(true);
        } catch (err) {
            alert(`重命名失败：${err.message || err}`);
        }
    }

    async deleteCategory(category) {
        if (!confirm(MSG.deleteCategoryConfirm.replace("%s", category))) return;
        try {
            const res = await fetch(API_DELETE_CAT, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    model: this.model.preset || "generic",
                    role: this.role,
                    category,
                }),
            });
            const data = await res.json();
            if (!res.ok || data.ok === false) throw new Error(data.error || "删除失败");
            if (this.activeCategory === category) this.activeCategory = "";
            this.footEl.textContent = `已删除分类：${category}`;
            await this.reload(true);
        } catch (err) {
            alert(`删除分类失败：${err.message || err}`);
        }
    }

    close() {
        if (this.closed) return;
        this.closed = true;
        closeEmbeddingPicker();
        this.closeContextMenu();
        document.removeEventListener("keydown", this.onKey, true);
        this.overlay?.remove();
        if (PromptDialog._current === this) PromptDialog._current = null;
    }
}

PromptDialog._current = null;
