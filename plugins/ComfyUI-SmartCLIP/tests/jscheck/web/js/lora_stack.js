/**
 * Josia LoRA Stack v8 - 修复滑块单击后跟随鼠标
 * 根因：LiteGraph 不保证 onMouseDown 返回 true 的节点能收到 onMouseUp
 *       当鼠标移出节点时 node_over 改变，onMouseUp 分发到其他节点
 *       导致 _md 永远为 true，滑块持续跟随
 * 修复：1) 滑块拖拽开始时调用 captureInput(true) 捕获输入
 *       2) onMM 中使用 e.buttons & 1 检测鼠标按键状态（原生DOM）
 *       3) 拖拽结束时调用 captureInput(false) 释放捕获
 *
 * 2026-09-15 追加：与底模架构不兼容的 LoRA，名字直接标红（#ff5f56）。
 * 判定走后端 POST /modelconflict/check（与 ModelImagePicker 弹窗同一套引擎），
 * 参考系是工作流里挂着的大模型；只有 state === "conflict" 才标红，
 * "unknown"（判不出来 / 没有可参照的底模）保持原色——绝不猜。
 */
import { app } from "../../scripts/app.js";

const NN = "JosiaLoraStack", NT = "JosiaLoRA堆叠", MG = 10;
const PT = 52, PX = 10, PY = 6, HH = 34, DH = 1;
const LH = 28, SH = 24, LG = 2, SG = 10;
const MW = 500;
const AW = 18, BH = 22, SW = 50, SHh = 22;
const RR = 4, DT = 5;

const Cmod = "#4a9eff", Cclip = "#ff6b9d";
const Cbg = "rgba(255,255,255,0.1)", CbgOff = "rgba(255,255,255,0.06)";
const Cblk = "#3a7bd5", CblkOff = "#555";
const Ctx = "#ddd", Cdim = "#666", Cdiv = "rgba(255,255,255,0.06)";
const CSync = "#4a9eff";
/** 架构冲突（与模型弹窗同色）。 */
const CCf = "#ff5f56";

function rr(c, x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    if (typeof c.roundRect === "function") { c.roundRect(x, y, w, h, r); return; }
    c.moveTo(x + r, y); c.lineTo(x + w - r, y);
    c.quadraticCurveTo(x + w, y, x + w, y + r);
    c.lineTo(x + w, y + h - r); c.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    c.lineTo(x + r, y + h); c.quadraticCurveTo(x, y + h, x, y + h - r);
    c.lineTo(x, y + r); c.quadraticCurveTo(x, y, x + r, y); c.closePath();
}
function cl(v, a, b) { return Math.min(Math.max(v, a), b); }
function rd(v, s) { return Math.round(v / s) * s; }
function ht(mx, my, a) { return a && mx >= a.x && mx <= a.x + a.w && my >= a.y && my <= a.y + a.h; }
function nH(gc) { return PT + HH + DH + gc * (LH + LG + SH) + (gc - 1) * SG + PY; }

function init(n) {
    if (n._li) return;
    n._li = true; n._hw = {}; n._list = ["None"]; n._st = [];
    n._ac = 1; n._dr = null; n._ha = {}; n._bk = null; n._md = false; n._fixed = null;
    if (!n.properties) n.properties = {};
    if (typeof n.properties.ts !== 'boolean') n.properties.ts = true;
    if (typeof n.properties.co !== 'boolean') n.properties.co = false;
    n.serialize_widgets = true; n.size = [MW, nH(1)];
}

function killW(n) {
    if (!n.widgets) return;
    for (const w of n.widgets) {
        if (w.name === 'model' || w.name === 'clip') continue;
        n._hw[w.name] = w;
        w.draw = function(){}; w.computeSize = function(){ return [0, -4]; }; w.last_y = -9999;
    }
}

function readSt(n) {
    const h = n._hw; if (!h || !Object.keys(h).length) return;
    // 保留已有的 sync 状态
    const oldSync = n._st.length > 0 ? n._st.map(s => !!s.sync) : [];
    n._ac = cl(h.lora_count ? Math.round(h.lora_count.value) : 1, 1, MG);
    // 列表已知的情况下，隐藏控件里的失效名字一律读作 None，
    // 避免 readSt/writeSt 互相回灌形成死循环（见 reconcile 注释）
    const list = pickList(n);
    if (list) n._list = list;
    const known = (list && list.length > 1) ? new Set(list) : null;
    n._st = [];
    for (let i = 1; i <= MG; i++) {
        let nm = h[`lora_name_${i}`] ? String(h[`lora_name_${i}`].value) : "None";
        if (known && nm && nm !== "None" && !known.has(nm)) nm = "None";
        n._st.push({
            name: nm,
            en: h[`lora_switch_${i}`] ? !!h[`lora_switch_${i}`].value : true,
            sm: h[`strength_model_${i}`] ? parseFloat(h[`strength_model_${i}`].value) : 0.8,
            sc: h[`strength_clip_${i}`] ? parseFloat(h[`strength_clip_${i}`].value) : 0.0,
            sync: oldSync[i - 1] || false,
        });
    }
    if (h.total_switch) n.properties.ts = !!h.total_switch.value;
    if (h.cpu_offload) n.properties.co = !!h.cpu_offload.value;
}

// ═════════════════════════════════════════════
// LoRA 列表读取与失效名自动修复
// ═════════════════════════════════════════════

// 插件自带的权威列表（后端 /josia_lora/list）。
// 因为 Python 端 lora_name_i 已从 COMBO 改为 STRING（避免失效文件名
// 否决整个 prompt），前端不再能靠控件属性拿到可选列表。
let LORA_LIST = null;      // string[] | null（null 表示尚未取到）
let LORA_FETCHING = false;

async function loadLoraList() {
    if (LORA_FETCHING) return;
    LORA_FETCHING = true;
    try {
        const r = await fetch("/josia_lora/list");
        if (r.ok) {
            const j = await r.json();
            if (j && Array.isArray(j.items) && j.items.length) {
                LORA_LIST = j.items;
                // 列表到手后立刻让所有已存在的节点自检一遍
                for (const n of (app.graph?._nodes || [])) {
                    if (n.type === NN || n.comfyClass === NN) {
                        n._list = LORA_LIST;
                        try { killW(n); readSt(n); if (reconcile(n)) notifyFixed(n); writeSt(n); } catch (e) { }
                    }
                }
                app.graph?.setDirtyCanvas?.(true, false);
            }
        }
    } catch (e) {
        console.warn("[JosiaLoraStack] 获取 LoRA 列表失败：", e);
    } finally {
        LORA_FETCHING = false;
    }
}

/**
 * 取当前可用的 LoRA 列表。
 * 优先级：
 *   1) 隐藏控件上的 options.values（若前端仍为下拉控件）
 *   2) 插件接口返回的 LORA_LIST（权威来源）
 *   3) 节点缓存 n._list
 * 都拿不到时返回 null，表示“列表未知”——此时绝不做任何清理，
 * 否则会在列表尚未到达时把用户选好的 LoRA 全部误清成 None。
 */
function pickList(n) {
    const h = n && n._hw;
    if (h) {
        for (let i = 1; i <= MG; i++) {
            const w = h[`lora_name_${i}`];
            const v = w && w.options && w.options.values;
            if (Array.isArray(v) && v.length > 1) return v;
        }
    }
    if (Array.isArray(LORA_LIST) && LORA_LIST.length > 1) return LORA_LIST;
    if (Array.isArray(n && n._list) && n._list.length > 1) return n._list;
    return null;
}

/**
 * 读取当前可用的 LoRA 列表；确实无法获知时回退为 ["None"]。
 */
function getLst(n) {
    const l = pickList(n);
    if (l) { n._list = l; return l; }
    return ["None"];
}

/** 列表内容是否发生变化（用于界面刷新判断） */
function listChanged(n, l) {
    const old = n._list;
    if (!Array.isArray(old) || old.length !== l.length) return true;
    for (let i = 0; i < l.length; i++) { if (old[i] !== l[i]) return true; }
    return false;
}

/**
 * 把状态里“已经不存在的 LoRA 文件名”归零为 None。
 *
 * 这是本插件此前最致命的 bug：
 * 工作流里存了某个 LoRA 名，之后该文件被删除/改名/移走
 * （最常见的是把 embedding 当 LoRA 填了进来），
 * 而 writeSt() 会把这个失效名字原样写回隐藏控件并提交给后端，
 * 导致 ComfyUI 校验直接否决整个 prompt：
 *     Value not in list: lora_name_8: 'xxx.safetensors' not in (list of length NN)
 *     Output will be ignored
 * 画布上看不到该隐藏控件，用户完全无从修复。
 *
 * 现在改为：只要确认列表已知，就把失效名字就地清零，并提示一次。
 * 注意必须在「列表可信」时才动手，见 pickList 的说明。
 */
function reconcile(n) {
    const list = pickList(n);
    if (!list) return false;
    n._list = list;

    const index = new Set(list);
    let fixed = false;
    for (let i = 0; i < MG; i++) {
        const s = n._st[i];
        if (!s || !s.name) continue;
        if (s.name === "None") continue;
        if (index.has(s.name)) continue;
        // 失效：保留信息在控制台，界面归零
        console.warn(`[JosiaLoraStack] 第 ${i + 1} 组 LoRA 已失效，自动重置为 None：${s.name}`);
        n._fixed = n._fixed || [];
        n._fixed.push({ slot: i + 1, name: s.name });
        s.name = "None";
        fixed = true;
    }
    return fixed;
}

/** 提示用户哪些槽位被自动修复了（避免“我明明选过”的困惑） */
function notifyFixed(n) {
    const f = n._fixed;
    if (!f || !f.length) return;
    n._fixed = null;
    const txt = f.map(x => `第${x.slot}组 ${x.name}`).join("、");
    try {
        const s = app.ui?.settings?.getSettingValue?.("Comfy.Toast.Enabled");
        if (typeof app.extensionManager?.toast?.add === "function") {
            app.extensionManager.toast.add({
                severity: "warn",
                summary: "LoRA 已自动重置",
                detail: `以下 LoRA 文件已不存在，已置为 None：${txt}`,
                life: 8000,
            });
            return;
        }
    } catch (e) { /* 提示失败不影响主流程 */ }
    console.warn(`[JosiaLoraStack] 以下 LoRA 文件已不存在，已置为 None：${txt}`);
}

function writeSt(n) {
    const h = n._hw; if (!h) return;
    // 提交前先清理失效的 LoRA 名（核心修复）
    if (reconcile(n)) notifyFixed(n);
    if (h.lora_count) h.lora_count.value = n._ac;
    if (h.total_switch) h.total_switch.value = n.properties.ts ?? true;
    if (h.cpu_offload) h.cpu_offload.value = n.properties.co ?? false;
    for (let i = 0; i < MG; i++) {
        const idx = i + 1, s = n._st[i]; if (!s) continue;
        // 双保险：绝不把“不在列表里”的名字写进隐藏控件
        let nm = s.name;
        if (nm && nm !== "None") {
            const l = n._list;
            if (Array.isArray(l) && l.length > 1 && !l.includes(nm)) { nm = "None"; s.name = "None"; }
        }
        if (h[`lora_name_${idx}`]) h[`lora_name_${idx}`].value = nm;
        if (h[`lora_switch_${idx}`]) h[`lora_switch_${idx}`].value = s.en;
        if (h[`strength_model_${idx}`]) h[`strength_model_${idx}`].value = s.sm;
        if (h[`strength_clip_${idx}`]) h[`strength_clip_${idx}`].value = s.sc;
    }
}

// ═════════════════════════════════════════════
// 绘制
// ═════════════════════════════════════════════

function drawBtn(c, x, y, w, h, lbl, act, ac, gd) {
    c.save();
    c.fillStyle = act ? ac : "rgba(255,255,255,0.06)";
    c.beginPath(); rr(c, x, y, w, h, RR); c.fill();
    c.fillStyle = act ? "rgba(255,255,255,0.92)" : "#888";
    c.font = "bold 12px sans-serif"; c.textAlign = "center"; c.textBaseline = "middle";
    c.fillText(lbl, x + w / 2, y + h / 2);
    if (gd) {
        const tw = c.measureText(lbl).width;
        c.strokeStyle = "rgba(255,255,255,0.5)"; c.lineWidth = 1;
        c.beginPath(); c.moveTo(x + (w - tw) / 2, y + h / 2); c.lineTo(x + (w + tw) / 2, y + h / 2); c.stroke();
    }
    c.restore();
}

function drawSw(c, x, y, w, h, en, gd) {
    const on = en && !gd;
    c.save(); c.fillStyle = on ? "#155c30" : "#7a1515";
    c.beginPath(); rr(c, x, y, w, h, h / 2); c.fill();
    c.fillStyle = "rgba(255,255,255,0.9)";
    c.font = "bold 11px sans-serif"; c.textAlign = "center"; c.textBaseline = "middle";
    c.fillText(on ? "开" : "关", x + w / 2, y + h / 2);
    c.restore();
}

function drawAr(c, x, y, w, h, d) {
    c.save(); c.fillStyle = "rgba(255,255,255,0.12)";
    c.beginPath(); rr(c, x, y, w, h, RR); c.fill();
    c.fillStyle = "#ccc"; c.font = "bold 11px sans-serif";
    c.textAlign = "center"; c.textBaseline = "middle";
    c.fillText(d === "left" ? "◀" : "▶", x + w / 2, y + h / 2 + 1);
    c.restore();
}

function drawDv(c, x, y, w) {
    c.save(); c.strokeStyle = Cdiv; c.lineWidth = 1;
    c.beginPath(); c.moveTo(x, y + 0.5); c.lineTo(x + w, y + 0.5); c.stroke();
    c.restore();
}

function drawEdit(c, x, y, w, h) {
    c.save(); c.fillStyle = "rgba(255,255,255,0.10)";
    c.beginPath(); rr(c, x, y, w, h, RR); c.fill();
    c.fillStyle = "#aaa"; c.font = "13px sans-serif";
    c.textAlign = "center"; c.textBaseline = "middle";
    c.fillText("✏️", x + w / 2, y + h / 2 + 1);
    c.restore();
}

function drawSync(c, x, y, w, h, on) {
    c.save(); c.fillStyle = on ? CSync : "rgba(255,255,255,0.08)";
    c.beginPath(); rr(c, x, y, w, h, RR); c.fill();
    c.fillStyle = on ? "#fff" : "#666";
    c.font = "bold 13px sans-serif";
    c.textAlign = "center"; c.textBaseline = "middle";
    c.fillText("🔗", x + w / 2, y + h / 2 + 1);
    c.restore();
}

/* ═════════════════════════════════════════════
 * 架构冲突判定（LoRA 名字标红）
 *
 * 判定源与 ModelImagePicker 的模型弹窗完全相同：POST /modelconflict/check，
 * kind = "loras"，参考系（picks）是工作流里当前挂着的大模型。这里自己读一次
 * /modelconflict/index 把控件里的模型名归到 checkpoints / diffusion_models，
 * 是为了不让本插件依赖另一个插件目录。
 * 后端对每个名字返回 state：conflict（架构不同）/ ok / unknown。
 * ═════════════════════════════════════════════ */

const API_MC_INDEX = "/modelconflict/index";
const API_MC_CHECK = "/modelconflict/check";
const MC_BASE_KINDS = ["checkpoints", "diffusion_models"];
const MC_PROBE_MS = 1200;
const SMART_PUNCT = /[\u2010-\u2015\u2212\ufe63\uff0d]/g;
const ZERO_WIDTH = /[\u200b-\u200d\ufeff]/g;

/** normalize 过的 LoRA 名 -> state */
const CF_ST = new Map();
/** { names: Map, basenames: Map }，只收底模类 */
let CF_INDEX = null;
let CF_INDEX_PROMISE = null;
/** 上次成功检测的输入签名（名字 + picks），没变就不重复请求 */
let CF_SIG = "";
let CF_BUSY = false;
let CF_LAST_PROBE = 0;

function cfNorm(name) {
    return String(name == null ? "" : name)
        .replace(SMART_PUNCT, "-")
        .replace(ZERO_WIDTH, "")
        .replace(/\\/g, "/")
        .trim()
        .toLowerCase();
}

/** 某个 LoRA 的判定结果："conflict" | "ok" | "unknown" | ""。 */
export function conflictState(name) {
    return CF_ST.get(cfNorm(name)) || "";
}

/** 测试/调试用：丢掉索引与判定缓存，下一次 refresh 会重新请求。 */
export function resetConflictCache() {
    CF_ST.clear();
    CF_SIG = "";
    CF_INDEX = null;
    CF_INDEX_PROMISE = null;
}

async function ensureBaseIndex() {
    if (CF_INDEX) return CF_INDEX;
    if (CF_INDEX_PROMISE) return CF_INDEX_PROMISE;

    CF_INDEX_PROMISE = (async () => {
        try {
            const r = await fetch(API_MC_INDEX);
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const data = await r.json();
            const names = new Map(), basenames = new Map();
            for (const kind of MC_BASE_KINDS) {
                for (const nm of (data?.kinds?.[kind] || [])) {
                    const key = cfNorm(nm);
                    if (!key) continue;
                    names.set(key, kind);
                    const base = key.split("/").pop();
                    if (base) basenames.set(base, kind);
                }
            }
            CF_INDEX = { names, basenames };
        } catch (e) {
            console.warn("[JosiaLoraStack] 模型索引不可用，LoRA 不标红：", e);
            CF_INDEX = { names: new Map(), basenames: new Map() };
        }
        return CF_INDEX;
    })();

    return CF_INDEX_PROMISE;
}

function cfKindOf(value) {
    if (!CF_INDEX) return "";
    const key = cfNorm(value);
    if (CF_INDEX.names.has(key)) return CF_INDEX.names.get(key);
    const alt = key.includes("/") ? key.replace(/\//g, "\\") : key.replace(/\\/g, "/");
    if (CF_INDEX.names.has(alt)) return CF_INDEX.names.get(alt);
    const base = key.split("/").pop();
    return base && CF_INDEX.basenames.has(base) ? CF_INDEX.basenames.get(base) : "";
}

function cfWidgetText(value) {
    if (value == null) return "";
    if (typeof value === "string") return value;
    if (typeof value === "object" && typeof value.content === "string") return value.content;
    return "";
}

/** 工作流里当前挂着的大模型——后端 check 的参考系。 */
function collectBasePicks() {
    const picks = {};
    for (const node of (app?.graph?._nodes || [])) {
        for (const w of (node?.widgets || [])) {
            const text = cfWidgetText(w?.value);
            if (!text || text.length > 400) continue;
            const kind = cfKindOf(text);
            if (!kind) continue;
            const arr = picks[kind] || (picks[kind] = []);
            if (!arr.includes(text) && arr.length < 40) arr.push(text);
        }
    }
    return picks;
}

function stackNodes() {
    return (app?.graph?._nodes || []).filter((n) => n && (n.type === NN || n.comfyClass === NN));
}

/** 所有 LoRA 堆叠节点上选中的名字（去重，跳过 None）。 */
function stackLoraNames() {
    const out = [];
    for (const n of stackNodes()) {
        for (const s of (n._st || [])) {
            const nm = s && s.name;
            if (nm && nm !== "None" && !out.includes(nm)) out.push(nm);
        }
    }
    return out;
}

/**
 * 重新判定当前工作流里所有堆叠用的 LoRA。
 * 输入（名字集合 + 参考系）没变时不发请求；失败就保持上一次的结果。
 */
export async function refreshConflicts() {
    const names = stackLoraNames();
    if (!names.length) {
        if (CF_ST.size) {
            CF_ST.clear();
            app.graph?.setDirtyCanvas?.(true, false);
        }
        CF_SIG = "";
        return null;
    }

    const index = await ensureBaseIndex();
    if (!index.names.size) return null;      // 没有索引 = 判不出来，保持原色

    const picks = collectBasePicks();
    const sig = JSON.stringify([names.slice().sort(), picks]);
    if (sig === CF_SIG || CF_BUSY) return null;

    CF_BUSY = true;
    try {
        const r = await fetch(API_MC_CHECK, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ kind: "loras", names, picks }),
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        const data = await r.json();
        const items = data?.items || {};
        CF_ST.clear();
        for (const nm of Object.keys(items)) CF_ST.set(cfNorm(nm), items[nm]?.state || "");
        CF_SIG = sig;
        app.graph?.setDirtyCanvas?.(true, false);
        return data;
    } catch (e) {
        console.warn("[JosiaLoraStack] LoRA 兼容检测失败，保持原色：", e);
        return null;
    } finally {
        CF_BUSY = false;
    }
}

/** 画布每帧都会走这里：节流到 1.2s 一次，签名没变时不会真的发请求。 */
function probeConflicts() {
    const now = Date.now();
    if (now - CF_LAST_PROBE < MC_PROBE_MS) return;
    CF_LAST_PROBE = now;
    refreshConflicts();
}

export function drawName(c, n, W, y, idx, s, gd) {
    const rw = W - PX * 2, rh = LH - 2, ry = y + (LH - rh) / 2;
    const ena = s.en && !gd;
    c.save(); c.fillStyle = ena ? "rgba(255,255,255,0.05)" : "rgba(255,255,255,0.02)";
    c.beginPath(); rr(c, PX, ry, rw, rh, RR); c.fill(); c.restore();
    c.save(); c.fillStyle = ena ? Cblk : CblkOff;
    c.beginPath(); rr(c, PX + 5, ry + (rh - 14) / 2, 5, 14, 2); c.fill(); c.restore();
    const tx = PX + 16, swX = W - PX - SW - 2;
    const mw = swX - tx - 8;
    // 与底模架构不符的名字用冲突红，其余保持原色（开关关闭时仍是灰+删除线）
    const hot = s.name !== "None" && conflictState(s.name) === "conflict";
    c.save(); c.fillStyle = ena ? Ctx : Cdim;
    c.font = "bold 12px sans-serif"; c.textAlign = "left"; c.textBaseline = "middle";
    const pre = `LoRA ${idx}: `;
    const pw = c.measureText(pre).width;
    const label = s.name !== "None"
        ? trunc(c, s.name.replace(/\.(safetensors|pt|bin)$/i, ""), mw - pw)
        : "None";
    c.fillText(pre, tx, y + LH / 2);
    c.fillStyle = hot ? CCf : (ena ? Ctx : Cdim);
    c.fillText(label, tx + pw, y + LH / 2);
    if (!ena) { const tw = pw + c.measureText(label).width;
        c.strokeStyle = hot ? CCf : Cdim; c.lineWidth = 1;
        c.beginPath(); c.moveTo(tx, y + LH / 2); c.lineTo(tx + tw, y + LH / 2); c.stroke(); }
    c.restore();
    const swY = y + (LH - SHh) / 2;
    drawSw(c, swX, swY, SW, SHh, s.en, gd);
    return { sw: { x: swX, y: swY, w: SW, h: SHh, gi: idx - 1 }, na: { x: PX, y: ry, w: rw, h: rh, gi: idx - 1 } };
}

function trunc(c, t, mw) {
    if (!t) return ""; if (c.measureText(t).width <= mw) return t;
    let s = t; while (s.length > 0 && c.measureText(s + "…").width > mw) s = s.slice(0, -1);
    return s + "…";
}

/** 滑块轨道 */
function drawSld(c, x, y, h, w, val, mn, mx, color, ena, lbl, gd) {
    const oh = BH, oy = y + (h - oh) / 2; const show = ena && !gd;
    c.save(); c.fillStyle = show ? Cbg : CbgOff;
    c.beginPath(); rr(c, x, oy, w, oh, RR); c.fill(); c.restore();
    if (show) {
        const norm = (mx > mn) ? (val - mn) / (mx - mn) : 0.5;
        const fw = cl(Math.round(norm * w), 0, w);
        if (fw > 0) {
            c.save(); c.fillStyle = color; c.beginPath();
            const rr2 = Math.min(RR, fw / 2, oh / 2);
            if (rr2 > 0 && fw > rr2) {
                c.moveTo(x + fw, oy); c.lineTo(x + rr2, oy);
                c.quadraticCurveTo(x, oy, x, oy + rr2);
                c.lineTo(x, oy + oh - rr2); c.quadraticCurveTo(x, oy + oh, x + rr2, oy + oh);
                c.lineTo(x + fw, oy + oh); c.closePath(); c.fill();
            } else { rr(c, x, oy, fw, oh, RR); c.fill(); }
            c.restore();
        }
    }
    const txt = `${lbl} ${val.toFixed(2)}`;
    c.save(); c.fillStyle = "rgba(255,255,255,0.95)";
    c.font = "bold 11px sans-serif"; c.textAlign = "center"; c.textBaseline = "middle";
    c.fillText(txt, x + w / 2, oy + oh / 2);
    if (!show) {
        const tw = c.measureText(txt).width;
        c.strokeStyle = "rgba(255,255,255,0.4)"; c.lineWidth = 1;
        c.beginPath(); c.moveTo(x + (w - tw) / 2, oy + oh / 2); c.lineTo(x + (w + tw) / 2, oy + oh / 2); c.stroke();
    }
    c.restore();
    return { x, y: oy, w, h: oh };
}

/** 滑块行：模型[◄][slider][✏️][►]  [🔗]  [◄][slider][✏️][►]CLIP */
function drawSldR(c, n, W, y, idx, s, gd) {
    const ena = s.en && !gd;
    const gap = 3, editW = AW, syncW = 26, gapSync = 6;
    const fixed = 6 * AW + 6 * gap + 2 * gapSync + syncW;
    const sldW = Math.max(50, Math.floor((W - PX * 2 - fixed) / 2));
    const ay = y + (SH - BH) / 2;

    // 模型（从左）
    const mL = { x: PX, y: ay, w: AW, h: BH };
    const mSX = mL.x + mL.w + gap;
    const mSW = sldW;
    const mEX = mSX + mSW + gap;
    const mR = { x: mEX + editW + gap, y: ay, w: AW, h: BH };
    // 同步
    const syncX = mR.x + mR.w + gapSync;
    // CLIP（从右）
    const cR = { x: W - PX - AW, y: ay, w: AW, h: BH };
    const cEX = cR.x - gap - editW;
    const cSX = cEX - gap - sldW;
    const cL = { x: cSX - gap - AW, y: ay, w: AW, h: BH };

    // 溢出处理
    if (cL.x < syncX + syncW + gapSync) {
        const overlap = (syncX + syncW + gapSync) - cL.x;
        const newW = Math.max(40, sldW - Math.ceil(overlap / 2));
        const nmEX = mSX + newW + gap;
        const nmR = { x: nmEX + editW + gap, y: ay, w: AW, h: BH };
        const nSyncX = nmR.x + nmR.w + gapSync;
        const ncR = { x: W - PX - AW, y: ay, w: AW, h: BH };
        const ncEX = ncR.x - gap - editW;
        const ncSX = ncEX - gap - newW;
        const ncL = { x: ncSX - gap - AW, y: ay, w: AW, h: BH };

        drawAr(c, mL.x, mL.y, mL.w, mL.h, "left");
        const ma = drawSld(c, mSX, y, SH, newW, s.sm, -3, 3, Cmod, ena, "模型强度", gd);
        drawEdit(c, nmEX, ay, editW, BH);
        drawAr(c, nmR.x, nmR.y, nmR.w, nmR.h, "right");
        drawSync(c, nSyncX, ay, syncW, BH, s.sync);
        drawAr(c, ncL.x, ncL.y, ncL.w, ncL.h, "left");
        const ca = drawSld(c, ncSX, y, SH, newW, s.sc, -3, 3, Cclip, ena, "CLIP强度", gd);
        drawEdit(c, ncEX, ay, editW, BH);
        drawAr(c, ncR.x, ncR.y, ncR.w, ncR.h, "right");
        return {
            model: { ta: { x: mSX, y: ay, w: newW, h: BH }, al: mL, ar: nmR, ed: { x: nmEX, y: ay, w: editW, h: BH, gi: idx - 1, type: "model" } },
            sync: { x: nSyncX, y: ay, w: syncW, h: BH, gi: idx - 1 },
            clip: { ta: { x: ncSX, y: ay, w: newW, h: BH }, al: ncL, ar: ncR, ed: { x: ncEX, y: ay, w: editW, h: BH, gi: idx - 1, type: "clip" } },
        };
    }
    drawAr(c, mL.x, mL.y, mL.w, mL.h, "left");
    const ma = drawSld(c, mSX, y, SH, sldW, s.sm, -3, 3, Cmod, ena, "模型强度", gd);
    drawEdit(c, mEX, ay, editW, BH);
    drawAr(c, mR.x, mR.y, mR.w, mR.h, "right");
    drawSync(c, syncX, ay, syncW, BH, s.sync);
    drawAr(c, cL.x, cL.y, cL.w, cL.h, "left");
    const ca = drawSld(c, cSX, y, SH, sldW, s.sc, -3, 3, Cclip, ena, "CLIP强度", gd);
    drawEdit(c, cEX, ay, editW, BH);
    drawAr(c, cR.x, cR.y, cR.w, cR.h, "right");
    return {
        model: { ta: { x: mSX, y: ay, w: sldW, h: BH }, al: mL, ar: mR, ed: { x: mEX, y: ay, w: editW, h: BH, gi: idx - 1, type: "model" } },
        sync: { x: syncX, y: ay, w: syncW, h: BH, gi: idx - 1 },
        clip: { ta: { x: cSX, y: ay, w: sldW, h: BH }, al: cL, ar: cR, ed: { x: cEX, y: ay, w: editW, h: BH, gi: idx - 1, type: "clip" } },
    };
}

// ═════════════════════════════════════════════
// 主绘制
// ═════════════════════════════════════════════
function drawNode(n, c) {
    if (n.flags?.collapsed) return;
    if (!n._li) init(n);
    killW(n); readSt(n);

    // 列表同步：下拉列表通常晚于节点创建才到达。
    // 一旦拿到真实列表，立刻改写状态中那些已失效的 LoRA 名，
    // 使画布上的显示与即将提交给后端的数据保持一致。
    const _pl = pickList(n);
    if (_pl) {
        if (listChanged(n, _pl)) {
            n._list = _pl;
            app.graph?.setDirtyCanvas?.(true, false);
        }
        if (reconcile(n)) {
            notifyFixed(n);
            writeSt(n);
        }
    }

    // 名字/底模变了就重新判定一次（内部节流 + 签名比对，不会每帧发请求）
    probeConflicts();

    const W = Math.max(n.size[0], MW);
    const H = nH(n._ac); if (Math.abs(n.size[1] - H) > 1) n.size[1] = H;
    const tOn = n.properties.ts ?? true;
    const gd = !tOn;

    n._ha = { ts: null, co: null, cL: null, cR: null, cD: null, sw: [], na: [], tr: [], ar: [], ed: [], sy: [] };

    let y = PT;

    // ═══ Header: 数量模块从右计算，按钮从左计算 ═══
    // 先计算数量模块宽度（以10组为基准）
    c.save(); c.font = "bold 13px sans-serif";
    const txt10w = c.measureText("LoRA数量: 10组").width;
    c.restore();
    const gapText = 16;
    // 数量模块固定宽度 = 左箭头 + gap + 文本10 + gap + 右箭头
    const cntModW = AW + gapText + txt10w + gapText + AW;

    // 数量模块从右边开始
    const rAx = W - PX - AW; // 右箭头贴右边界
    const nTextLeft = rAx - gapText - txt10w;
    const nLAx = nTextLeft - gapText - AW;

    // 当前文本
    const cTxt = `LoRA数量: ${n._ac}组`;
    c.save(); c.font = "bold 13px sans-serif";
    const cTw = c.measureText(cTxt).width;
    c.restore();
    // 当前文本放置在固定位置（与10组时的位置对齐）
    const curTextX = rAx - gapText - cTw; // 右对齐文本

    // 按钮可用宽度 = 模块左边界 - PX - 固定间距
    const gapBtn = 16; // 按钮区和数量区之间的固定间距
    const btnAvail = nLAx - PX - gapBtn;
    const btnW = Math.max(85, Math.floor((btnAvail - 8) / 2));
    const btnAH = HH - 8;
    const btnAY = y + (HH - btnAH) / 2;

    // 总控
    n._ha.ts = { x: PX, y: btnAY, w: btnW, h: btnAH };
    drawBtn(c, PX, btnAY, btnW, btnAH, "总控开关", tOn, "#1a6b3c", gd);
    // CPU
    const cpuX = PX + btnW + 8;
    const cpuOn = n.properties.co ?? false;
    n._ha.co = { x: cpuX, y: btnAY, w: btnW, h: btnAH };
    drawBtn(c, cpuX, btnAY, btnW, btnAH, cpuOn ? "内存加载" : "显存加载", cpuOn, "#7a4c15", gd);

    // 数量箭头
    const ah = HH - 8;
    n._ha.cL = { x: nLAx, y: y + (HH - ah) / 2, w: AW, h: ah };
    drawAr(c, nLAx, y + (HH - ah) / 2, AW, ah, "left");
    c.save(); c.fillStyle = gd ? Cdim : Ctx;
    c.font = "bold 13px sans-serif"; c.textAlign = "left"; c.textBaseline = "middle";
    c.fillText(cTxt, curTextX, y + HH / 2);
    if (gd) { c.strokeStyle = Cdim; c.lineWidth = 1;
        c.beginPath(); c.moveTo(curTextX, y + HH / 2); c.lineTo(curTextX + cTw, y + HH / 2); c.stroke(); }
    c.restore();
    n._ha.cD = { x: curTextX, y, w: cTw, h: HH };
    n._ha.cR = { x: rAx, y: y + (HH - ah) / 2, w: AW, h: ah };
    drawAr(c, rAx, y + (HH - ah) / 2, AW, ah, "right");

    y += HH;
    drawDv(c, PX, y, W - PX * 2);
    y += DH;

    // ═══ LoRA组 ═══
    for (let i = 0; i < n._ac; i++) {
        const s = n._st[i]; if (!s) continue;
        if (i > 0) { y += SG / 2; drawDv(c, PX, y, W - PX * 2); y += SG / 2; }
        const la = drawName(c, n, W, y, i + 1, s, gd);
        n._ha.sw.push(la.sw); n._ha.na.push(la.na);
        y += LH + LG;
        const sa = drawSldR(c, n, W, y, i + 1, s, gd);
        n._ha.tr.push({
            model: { area: sa.model.ta, gi: i, type: "model" },
            clip: { area: sa.clip.ta, gi: i, type: "clip" },
        });
        n._ha.ar.push({
            model: { left: sa.model.al, right: sa.model.ar, gi: i, type: "model" },
            clip: { left: sa.clip.al, right: sa.clip.ar, gi: i, type: "clip" },
        });
        n._ha.ed.push(sa.model.ed);
        n._ha.ed.push(sa.clip.ed);
        n._ha.sy.push(sa.sync);
        y += SH;
    }
}

// ═════════════════════════════════════════════
// 交互
// ═════════════════════════════════════════════
// getLst 已在文件上方统一实现（含多路兜底与 n._list 回退），此处不再重复定义。

function upd(n, gi, ty, val) {
    const s = n._st[gi]; if (!s) return;
    const v = rd(cl(val, -3, 3), 0.05);
    if (ty === "model") { s.sm = v; if (s.sync) s.sc = v; }
    else { s.sc = v; if (s.sync) s.sm = v; }
    writeSt(n); app.graph?.setDirtyCanvas?.(true, false);
}

function openEdit(n, gi, ty) {
    const s = n._st[gi]; if (!s) return;
    const cur = ty === "model" ? s.sm : s.sc;
    const label = ty === "model" ? "模型强度" : "CLIP强度";
    try {
        LiteGraph.prompt(`输入${label} (-10 ~ 10)`, String(cur.toFixed(2)), function(val) {
            if (val === null || val === undefined || val === "") return;
            const p = parseFloat(val);
            if (isNaN(p)) return;
            const v = rd(cl(p, -10, 10), 0.01);
            const s2 = n._st[gi]; if (!s2) return;
            if (ty === "model") { s2.sm = v; if (s2.sync) s2.sc = v; }
            else { s2.sc = v; if (s2.sync) s2.sm = v; }
            writeSt(n); app.graph?.setDirtyCanvas?.(true, false);
        }, "text");
    } catch(e) {
        // fallback
        const inp = prompt(`输入${label} (-10 ~ 10)`, cur.toFixed(2));
        if (inp == null) return;
        const p = parseFloat(inp);
        if (isNaN(p)) return;
        const v = rd(cl(p, -10, 10), 0.01);
        const s2 = n._st[gi]; if (!s2) return;
        if (ty === "model") { s2.sm = v; if (s2.sync) s2.sc = v; }
        else { s2.sc = v; if (s2.sync) s2.sm = v; }
        writeSt(n); app.graph?.setDirtyCanvas?.(true, false);
    }
}

function onMD(n, e, lp) {
    if (!lp) return false;
    if (!n._li) init(n);
    // 清理旧的拖拽状态并释放输入捕获
    if (n._dr) {
        n._dr = null;
        try { n.captureInput(false); } catch(_ex) {}
    }
    n._md = true;
    const [mx, my] = lp;
    const h = n._ha;

    if (h.ts && ht(mx, my, h.ts)) {
        if (n.properties?.ts) n._bk = n._st.map(s => s.en);
        else if (n._bk) n._st.forEach((s, i) => { if (s) s.en = n._bk[i]; });
        n.properties.ts = !(n.properties?.ts ?? true);
        writeSt(n); app.graph?.setDirtyCanvas?.(true, false); return true;
    }
    if (h.co && ht(mx, my, h.co)) {
        n.properties.co = !(n.properties?.co ?? false);
        writeSt(n); app.graph?.setDirtyCanvas?.(true, false); return true;
    }
    if (h.cL && ht(mx, my, h.cL)) { n._ac = cl(n._ac - 1, 1, MG); writeSt(n); app.graph?.setDirtyCanvas?.(true, false); return true; }
    if (h.cR && ht(mx, my, h.cR)) { n._ac = cl(n._ac + 1, 1, MG); writeSt(n); app.graph?.setDirtyCanvas?.(true, false); return true; }
    if (h.cD && ht(mx, my, h.cD)) { showCM(n, e); return true; }

    for (const s of h.sw) {
        if (ht(mx, my, s)) {
            const i = s.gi;
            if (i >= 0 && i < n._st.length) {
                n._st[i].en = !n._st[i].en;
                if (!(n.properties?.ts ?? true) && n._bk) n._bk[i] = n._st[i].en;
                writeSt(n); app.graph?.setDirtyCanvas?.(true, false);
            }
            return true;
        }
    }
    for (const na of h.na) {
        if (ht(mx, my, na)) {
            if (h.sw.find(s => s.gi === na.gi && ht(mx, my, s))) continue;
            showLM(n, e, na.gi); return true;
        }
    }
    // 同步按钮
    for (const sy of h.sy) {
        if (ht(mx, my, sy)) {
            const s = n._st[sy.gi];
            if (s) {
                s.sync = !s.sync;
                if (!s.sync) s.sc = 0;
                else s.sc = s.sm;
                writeSt(n); app.graph?.setDirtyCanvas?.(true, false);
            }
            return true;
        }
    }
    // 编辑按钮
    for (const ed of h.ed) {
        if (ht(mx, my, ed)) {
            openEdit(n, ed.gi, ed.type);
            return true;
        }
    }
    // 箭头
    for (const a of h.ar) {
        for (const side of ["model", "clip"]) {
            const aa = a[side]; if (!aa) continue;
            const st = n._st[aa.gi]; if (!st) continue;
            const v = side === "model" ? st.sm : st.sc;
            if (ht(mx, my, aa.left)) { upd(n, aa.gi, side, v - 0.05); return true; }
            if (ht(mx, my, aa.right)) { upd(n, aa.gi, side, v + 0.05); return true; }
        }
    }
    // 滑块轨道：立即定位，捕获输入确保收到 onMouseUp
    for (const t of h.tr) {
        for (const side of ["model", "clip"]) {
            const tt = t[side]; if (!tt || !tt.area) continue;
            if (ht(mx, my, tt.area)) {
                // 立即定位到点击位置
                const norm = (mx - tt.area.x) / tt.area.w;
                const val = -3 + norm * 6;
                upd(n, tt.gi, side, rd(cl(val, -3, 3), 0.05));
                // 标记拖拽开始 + 捕获输入（确保收到 onMouseUp）
                n._dr = { gi: tt.gi, type: side };
                try { n.captureInput(true); } catch(_ex) {}
                return true;
            }
        }
    }
    return false;
}

function onMM(n, e, lp) {
    if (!lp) return false;
    // 使用浏览器原生 e.buttons 检测鼠标按键状态（bit 0 = 左键）
    // 这比 _md 标志更可靠，因为即使 onMouseUp 未被调用，e.buttons 也能反映真实状态
    const btnHeld = (typeof e?.buttons === 'number') ? !!(e.buttons & 1) : !!n._md;
    if (!btnHeld) {
        // 鼠标未按住 — 清理残留拖拽状态并释放捕获
        if (n._dr) {
            n._dr = null;
            try { n.captureInput(false); } catch(_ex) {}
        }
        return false;
    }
    if (n._dr) {
        const [mx] = lp;
        const tr = n._ha.tr[n._dr.gi]; if (!tr) return false;
        const tk = tr[n._dr.type]; if (!tk || !tk.area) return false;
        const norm = (mx - tk.area.x) / tk.area.w;
        upd(n, n._dr.gi, n._dr.type, rd(cl(-3 + norm * 6, -3, 3), 0.05));
        return true;
    }
    return false;
}

function onMU(n, e, lp) {
    // 松开鼠标，清除所有拖拽/点击状态，释放输入捕获
    n._md = false;
    if (n._dr) {
        n._dr = null;
        try { n.captureInput(false); } catch(_ex) {}
        return true;
    }
    return false;
}

// ═════════════════════════════════════════════
// 菜单
// ═════════════════════════════════════════════
function showCM(n, e) {
    const items = [];
    for (let i = 1; i <= MG; i++) items.push({
        content: i === n._ac ? `✓ ${i} 组` : `${i} 组`,
        callback: () => { n._ac = i; writeSt(n); app.graph?.setDirtyCanvas?.(true, false); },
    });
    new LiteGraph.ContextMenu(items, { event: e, callback: null, parentMenu: null });
}

function showLM(n, e, gi) {
    const list = getLst(n), cur = n._st[gi]?.name || "None";
    const items = list.map(nm => ({
        content: nm === cur ? `✓ ${nm}` : nm,
        callback: () => { if (n._st[gi]) { n._st[gi].name = nm; writeSt(n); app.graph?.setDirtyCanvas?.(true, false); refreshConflicts(); } },
    }));
    new LiteGraph.ContextMenu(items, { event: e, callback: null, parentMenu: null });
}

// ═════════════════════════════════════════════
// 扩展
// ═════════════════════════════════════════════
app.registerExtension({
    name: "JosiaLoraStack",
    async setup() {
        // 启动时拉取一次权威 LoRA 列表（供下拉菜单与失效名判定使用）
        loadLoraList();
        // 架构冲突：图可能还没装好，稍后再判定一次；此后由画布探针维持
        setTimeout(() => { refreshConflicts(); }, 1200);
    },
    async beforeRegisterNodeDef(nt, nd) {
        if (nd.name !== NN) return;
        // 保险：setup() 执行时 app.graph 可能尚未就绪，此后再拉一次
        if (!Array.isArray(LORA_LIST)) loadLoraList();
        const oa = nt.prototype.onAdded;
        nt.prototype.onAdded = function(g) {
            init(this); const self = this;
            // 统一的刷新动作：读控件 → 同步列表 → 清理失效名 → 写回
            function dk() {
                killW(self); readSt(self);
                const l = pickList(self); if (l) self._list = l;
                if (reconcile(self)) notifyFixed(self);
                writeSt(self);
                app.graph?.setDirtyCanvas?.(true, false);
            }
            setTimeout(() => { requestAnimationFrame(dk); }, 10);
            oa?.call(this, g);
        };
        const oc = nt.prototype.onNodeCreated;
        nt.prototype.onNodeCreated = function() {
            const r = oc?.apply(this, arguments); init(this); const self = this;
            function dk() {
                killW(self); readSt(self); writeSt(self);
                const l = pickList(self);
                if (l) {
                    self._list = l;
                    if (reconcile(self)) { notifyFixed(self); writeSt(self); }
                }
                app.graph?.setDirtyCanvas?.(true, false);
            }
            killW(this); readSt(this); writeSt(this);
            setTimeout(() => { requestAnimationFrame(dk); }, 10);
            setTimeout(() => { requestAnimationFrame(dk); }, 100);
            return r;
        };
        nt.prototype.computeSize = function() { init(this); return [MW, nH(this._ac || 1)]; };
        nt.prototype.onDrawForeground = function(c) { init(this); drawNode(this, c); };
        const omd = nt.prototype.onMouseDown;
        nt.prototype.onMouseDown = function(e, lp, c) { init(this); if (onMD(this, e, lp)) return true; return omd?.call(this, e, lp, c) ?? false; };
        const omm = nt.prototype.onMouseMove;
        nt.prototype.onMouseMove = function(e, lp, c) { if (onMM(this, e, lp)) return true; return omm?.call(this, e, lp, c) ?? false; };
        const omu = nt.prototype.onMouseUp;
        nt.prototype.onMouseUp = function(e, lp, c) { if (onMU(this, e, lp)) return true; return omu?.call(this, e, lp, c) ?? false; };
        const om = nt.prototype.getExtraMenuOptions;
        nt.prototype.getExtraMenuOptions = function(c, o) {
            om?.call(this, c, o); const self = this;
            o.unshift(
                { content: "启用所有LoRA组", callback: () => { self._st.forEach(s => { if (s) s.en = true; }); writeSt(self); app.graph?.setDirtyCanvas?.(true, false); } },
                { content: "禁用所有LoRA组", callback: () => { self._st.forEach(s => { if (s) s.en = false; }); writeSt(self); app.graph?.setDirtyCanvas?.(true, false); } },
                { content: "全部强度归零", callback: () => { self._st.forEach(s => { if (s) { s.sm = 0; s.sc = 0; } }); writeSt(self); app.graph?.setDirtyCanvas?.(true, false); } },
                { content: "全部强度重置默认", callback: () => { self._st.forEach(s => { if (s) { s.sm = 0.8; s.sc = 0.0; } }); writeSt(self); app.graph?.setDirtyCanvas?.(true, false); } },
                { content: "刷新LoRA列表", callback: () => { LORA_LIST = null; loadLoraList(); } },
                null
            );
        };
    },
    loadedGraphNode(node) {
        if (node.type !== NT && node.comfyClass !== NN) return;
        const self = node;
        // 打开旧工作流时的关键时机：此处把失效的 LoRA 名就地清零。
        // 列表可能晚于本回调到达，因此多跑几轮（列表到达后自动修复）。
        function dk() {
            init(self); killW(self); readSt(self);
            const l = pickList(self); if (l) self._list = l;
            if (reconcile(self)) notifyFixed(self);
            writeSt(self);
            self.size[1] = nH(self._ac);
            app.graph?.setDirtyCanvas?.(true, false);
        }
        dk();
        setTimeout(() => { requestAnimationFrame(dk); }, 10);
        setTimeout(() => { requestAnimationFrame(dk); }, 300);
        setTimeout(() => { requestAnimationFrame(dk); }, 1200);
    },
});
