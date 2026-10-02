/**
 * Headless test for the SmartCLIP frontend modules.
 *
 *   node run.mjs
 *
 * It loads the real web/js/*.js (copied next to a stubbed scripts/app.js so the
 * relative imports resolve) against a fake graph that mirrors how this ComfyUI
 * build stores links, and checks the three things the draft implementation got
 * wrong: link traversal, cycle safety, and DOM injection safety.
 */

let fail = 0;
function check(label, got, want) {
    const ok = JSON.stringify(got) === JSON.stringify(want);
    if (!ok) fail++;
    console.log(`  ${ok ? "OK  " : "FAIL"} ${label.padEnd(58)} ${ok ? JSON.stringify(got) : "got " + JSON.stringify(got) + " want " + JSON.stringify(want)}`);
}
function checkTrue(label, value) {
    check(label, !!value, true);
}

/* ------------------------------------------------------------------ *
 * Fake graph (mirrors LiteGraph in this install: links live in _links Map)
 * ------------------------------------------------------------------ */

function makeGraph() {
    const nodes = [];
    const links = new Map();
    let nextId = 1;

    const graph = {
        _nodes: nodes,
        _links: links,
        _nodes_by_id: {},
        getNodeById(id) {
            return this._nodes_by_id[id] || null;
        },
        setDirtyCanvas() {},
    };

    function addNode(type, widgets = {}, id = null) {
        const node = {
            id: id ?? nextId++,
            type,
            widgets: Object.entries(widgets).map(([name, value]) => ({ name, value })),
            inputs: [],
            outputs: [{ name: "out", type: "CLIP", links: [] }],
            properties: {},
            graph,
        };
        nodes.push(node);
        graph._nodes_by_id[node.id] = node;
        return node;
    }

    function connect(src, srcSlot, dstSlot, dst) {
        const id = nextId++;
        links.set(id, { id, origin_id: src.id, origin_slot: srcSlot, target_id: dst.id, target_slot: dstSlot });
        src.outputs[srcSlot] = src.outputs[srcSlot] || { links: [] };
        (src.outputs[srcSlot].links = src.outputs[srcSlot].links || []).push(id);
        dst.inputs[dstSlot] = Object.assign(dst.inputs[dstSlot] || {}, { link: id, type: "CLIP" });
        return id;
    }

    return { graph, addNode, connect };
}

const { graph, addNode, connect } = makeGraph();
globalThis.__FAKE_APP__ = { graph };

const ckpt = addNode("CheckpointLoaderSimple", { ckpt_name: "hassakuXLIllustrious_v13StyleA.safetensors" }, 1);
const combiner = addNode("ConditioningCombine", {}, 2);
const smartPos = addNode("SmartCLIPTextEncode", { text: "", prompt_role: "auto" }, 3);
const sampler = addNode("KSampler", { seed: 1 }, 4);
const smartNeg = addNode("SmartCLIPTextEncode", { text: "", prompt_role: "auto" }, 5);

// ckpt.CLIP -> smartPos.CLIP ; ckpt.CLIP -> combiner -> smartNeg.CLIP
ckpt.outputs = [{ name: "CLIP", type: "CLIP", links: [] }, { name: "MODEL", type: "MODEL", links: [] }];
connect(ckpt, 0, 0, smartPos);
connect(ckpt, 0, 0, combiner);
connect(combiner, 0, 0, smartNeg);

// smartPos -> KSampler.positive (slot 1); smartNeg -> KSampler.negative (slot 2)
connect(smartPos, 0, 1, sampler);
connect(smartNeg, 0, 2, sampler);

const MC = await import("./web/js/model_tracker.js");
const PD = await import("./web/js/prompt_dialog.js");

/* ------------------------------------------------------------------ *
 * 0. the regression the report's code would have hit
 * ------------------------------------------------------------------ */

console.log("[link access on this frontend]");
check("graph.links is not an object", typeof graph.links, "undefined");
let threw = "";
try {
    const linkId = smartPos.outputs[0].links[0];
    void graph.links[linkId];                        // the draft's access pattern
} catch (err) {
    threw = err.constructor.name;
}
check("graph.links[id] throws (as the draft wrote it)", threw, "TypeError");
check("the tracker finds the target anyway", MC.outputTargets(smartPos, 0).map((t) => t.node.type), ["KSampler"]);

/* ------------------------------------------------------------------ *
 * 1. role detection
 * ------------------------------------------------------------------ */

console.log("\n[role detection]");
check("positive slot (KSampler slot 1)", MC.detectRoleFromGraph(smartPos), "positive");
check("negative slot (KSampler slot 2)", MC.detectRoleFromGraph(smartNeg), "negative");
check("unconnected node -> no role", MC.detectRoleFromGraph(ckpt), "");
check("manual widget wins", (() => {
    smartPos.widgets.find((w) => w.name === "prompt_role").value = "negative";
    const got = MC.ModelTracker.detectRole(smartPos);
    smartPos.widgets.find((w) => w.name === "prompt_role").value = "auto";
    return got;
})(), "negative");

/* ------------------------------------------------------------------ *
 * 2. cycle safety (the draft recursed forever)
 * ------------------------------------------------------------------ */

console.log("\n[cycle safety]");
const cycA = addNode("ConditioningCombine", {}, 101);
const cycB = addNode("ConditioningConcat", {}, 102);
cycA.outputs = [{ name: "out", type: "CONDITIONING", links: [] }];
cycB.outputs = [{ name: "out", type: "CONDITIONING", links: [] }];
connect(cycA, 0, 0, cycB);
connect(cycB, 0, 0, cycA);

const started = Date.now();
const cycRole = MC.detectRoleFromGraph(cycA);
const elapsed = Date.now() - started;
check("cyclic conditioning returns without a role", cycRole, "");
checkTrue(`cyclic conditioning terminated fast (${elapsed} ms)`, elapsed < 1000);

// a self-loop, the nastiest case
const selfLoop = addNode("ConditioningSetArea", {}, 103);
selfLoop.outputs = [{ name: "out", type: "CONDITIONING", links: [] }];
connect(selfLoop, 0, 0, selfLoop);
const t2 = Date.now();
check("self-loop returns", MC.detectRoleFromGraph(selfLoop), "");
checkTrue(`self-loop terminated fast (${Date.now() - t2} ms)`, Date.now() - t2 < 1000);

/* ------------------------------------------------------------------ *
 * 3. upstream trace
 * ------------------------------------------------------------------ */

console.log("\n[upstream trace]");
const trace = MC.traceUpstream(smartPos);
check("finds the checkpoint through nothing", trace.names.map((n) => n.name), ["hassakuXLIllustrious_v13StyleA.safetensors"]);
check("reports the model kind", trace.names[0].kind, "checkpoints");

const traceNeg = MC.traceUpstream(smartNeg);
check("follows through ConditioningCombine", traceNeg.names.map((n) => n.name), ["hassakuXLIllustrious_v13StyleA.safetensors"]);

const cyclicTrace = MC.traceUpstream(cycA);
check("cyclic trace terminates", cyclicTrace.names.length, 0);
checkTrue("cyclic trace stays bounded", cyclicTrace.visited <= 64);

console.log("\n[name hints]");
check("pony", MC.hintFromName("ponyDiffusionV6XL_v6.safetensors"), "pony");
check("illustrious", MC.hintFromName("hassakuXLIllustrious_v13.safetensors"), "illustrious");
check("krea", MC.hintFromName("snofs_krea_v1_4.safetensors"), "krea2");
check("plain sdxl model", MC.hintFromName("jewelry_v10.safetensors"), "");
check("sd15", MC.hintFromName("majicmixRealistic_v7.safetensors"), "");
check("empty", MC.hintFromName(""), "");

/* ------------------------------------------------------------------ *
 * 4. tracker merging (graph guess vs runtime truth)
 * ------------------------------------------------------------------ */

console.log("\n[merged model view]");
const node = smartPos;
MC.ModelTracker.init(node);
node.properties.smart_clip = {
    graph: { name: "ponyDiffusionV6XL.safetensors", kind: "checkpoints", hint: "pony", family: "sdxl", label: "SDXL", preset: "pony" },
};
check("graph-only guess uses the flavour preset", MC.ModelTracker.getModel(node).preset, "pony");
check("...and is marked as not-yet-run", MC.ModelTracker.getModel(node).runtimeSeen, false);

MC.ModelTracker.setRuntime(node, {
    family: "sdxl", label: "SDXL", preset: "sdxl", score_tags: false,
    evidence: "cond_stage_model=SDXLClipModel", source: "cond_stage_model", role: "auto", raw_text: "hello",
});
check("runtime family wins", MC.ModelTracker.getModel(node).family, "sdxl");
check("pony flavour still upgrades the preset", MC.ModelTracker.getModel(node).preset, "pony");
check("runtime is marked as authoritative", MC.ModelTracker.getModel(node).runtimeSeen, true);
check("state is persisted on the node", !!node.properties.smart_clip.runtime, true);

/* ------------------------------------------------------------------ *
 * 5. dialog: injection safety + widget writing
 * ------------------------------------------------------------------ */

console.log("\n[dialog DOM safety]");
const NASTY = 'he said "hi" & <b>bold</b> \'quote\'';
const CANNED = {
    model: "pony", role: "positive", source: "file",
    categories: {
        "rating": ["score_9", NASTY],
        "quality": ["masterpiece"],
        "embeddings": ["embedding:deep_negative_pony", "embedding:EasyNegative"],
    },
    annotations: {
        "embedding:deep_negative_pony": {
            kind: "embedding", name: "deep_negative_pony", state: "incompatible",
            arch: "ti_sdxl", short: "TI-SDXL",
            why: "与当前 SD 1.5 不兼容（本项 SDXL 词嵌入）",
        },
        "embedding:EasyNegative": {
            kind: "embedding", name: "EasyNegative", state: "ok",
            arch: "ti_sd", short: "TI-SD1.5", why: "与当前 SD 1.5 兼容（TI-SD1.5）",
        },
    },
    embedding_stats: { total: 2, ok: 1, incompatible: 1, missing: 0, unknown: 0 },
    // 后端标出的全局分类（用户自建的，任何工作流的弹窗都能看到）
    shared: ["quality"],
    // The backend advertises that /smart_clip/presets/save exists in this build.
    writable: true,
    models: ["pony"], roles: ["positive", "negative"],
};
const SAVED = [];
const SAVED_BATCHES = [];
const CLASSIFIED = [];
const DELETED = [];          // POST /smart_clip/presets/delete
const DELETED_CATS = [];     // POST /smart_clip/presets/delete_category
const RENAMED = [];          // POST /smart_clip/presets/rename_category
const CREATED = [];          // POST /smart_clip/presets/create_category
globalThis.__SAVE_FAIL__ = "";
globalThis.__SAVE_STATUS__ = 400;
globalThis.__STALE_BACKEND__ = false;

/** Embedding names the picker shows as a grid. */
const EMBS = ["deep_negative_pony", "EasyNegative", "bad_vae_embedding"];

/** embeddding_compat.annotate() verdicts, keyed by name (mirrors the backend). */
const EMB_COMPAT = {
    "deep_negative_pony": {
        kind: "embedding", name: "deep_negative_pony", state: "incompatible",
        arch: "ti_sd", short: "TI-SD1.5", why: "与当前 SDXL 词嵌入不兼容（本项 SD1.5 词嵌入）",
    },
    "EasyNegative": {
        kind: "embedding", name: "EasyNegative", state: "partial",
        arch: "ti_sd", short: "TI-SD1.5",
        why: "半兼容：768 维 SD1.5 词嵌入，SDXL 的 CLIP-G(1280) 会忽略它（TI-SD1.5）",
    },
    "bad_vae_embedding": {
        kind: "embedding", name: "bad_vae_embedding", state: "missing",
        arch: "unknown", short: "?", why: "文件不在 models/embeddings 里",
    },
};

/* Model-conflict backend (ModelImagePicker). The stack node in the last test
   group asks /modelconflict/index to classify the graph's base model and
   /modelconflict/check for the LoRA verdicts. */
globalThis.__MC_INDEX__ = {
    kinds: {
        checkpoints: ["hassakuXLIllustrious_v13StyleA.safetensors"],
        diffusion_models: ["flux1-dev.safetensors"],
        loras: ["fluxLora.safetensors", "ponyLora.safetensors", "mysteryLora.safetensors"],
    },
    labels: { checkpoints: "大模型", loras: "LoRA" },
    roles: { checkpoints: "base", loras: "dependent" },
};
globalThis.__MC_ITEMS__ = {
    "fluxLora.safetensors": { state: "conflict", short: "FLUX", family: "flux", why: "与当前 SDXL 底模不兼容" },
    "ponyLora.safetensors": { state: "ok", short: "SDXL", family: "sdxl", why: "与当前 SDXL 兼容" },
    "mysteryLora.safetensors": { state: "unknown", short: "?", family: "unknown", why: "解析不出架构" },
};
globalThis.__MC_CALLS__ = [];

/** Stand-in for classify.py: enough keywords to prove the wiring. */
const FAKE_RULES = [
    ["red dress", "衣服"], ["long hair", "发型"], ["1girl", "人物"],
    ["forest", "环境"], ["masterpiece", "质量词"],
];

globalThis.fetch = async (url, init = {}) => {
    const target = String(url);
    if (target.includes("smart_clip/embeddings")) {
        // 名字列表给打字补全；带 family 时后端会一并给出兼容判定（picker 用）。
        const family = /[?&]family=([^&]*)/.exec(target)?.[1] || "";
        return {
            ok: true,
            status: 200,
            async json() {
                return {
                    family: family || "generic",
                    withPreview: 1,
                    items: EMBS.map((name) => ({
                        name,
                        hasPreview: name === "deep_negative_pony",
                        compat: family ? (EMB_COMPAT[name] || null) : null,
                    })),
                };
            },
        };
    }
    if (target.includes("modelconflict/index")) {
        return { ok: true, status: 200, async json() { return globalThis.__MC_INDEX__; } };
    }
    if (target.includes("modelconflict/check")) {
        const body = JSON.parse(init.body || "{}");
        globalThis.__MC_CALLS__.push(body);
        return {
            ok: true,
            status: 200,
            async json() {
                return {
                    kind: "loras", role: "dependent",
                    reference: { family: "sdxl", arch: "sdxl", name: "hassakuXLIllustrious_v13StyleA.safetensors" },
                    counts: { conflict: 1, ok: 1, unknown: 1 },
                    items: globalThis.__MC_ITEMS__,
                };
            },
        };
    }
    if (target.includes("smart_clip/classify")) {
        const body = JSON.parse(init.body || "{}");
        CLASSIFIED.push(body);
        const forced = globalThis.__CLASSIFY_FORCE__ || null;
        const tags = forced ? (forced.tags || []) : String(body.text || "")
            .split(",")
            .map((part) => part.trim())
            .filter(Boolean)
            .map((text) => {
                const hit = FAKE_RULES.find(([key]) => text.toLowerCase().includes(key));
                return { text, category: hit ? hit[1] : "其它" };
            });
        return {
            ok: true,
            status: 200,
            async json() {
                return {
                    ok: true, tags, total: tags.length, fallback: "其它",
                    dropped: forced ? (forced.dropped || []) : [],
                    categories: [...new Set(tags.map((t) => t.category))],
                };
            },
        };
    }
    if (target.includes("smart_clip/presets/save_many")) {
        const body = JSON.parse(init.body || "{}");
        SAVED_BATCHES.push(body);
        const entries = Array.isArray(body.entries) ? body.entries : [];
        let added = 0;
        const categories = {};
        for (const entry of entries) {
            const list = CANNED.categories[entry.category]
                || (CANNED.categories[entry.category] = []);
            if (!list.includes(entry.text)) {
                list.push(entry.text);
                added++;
                categories[entry.category] = (categories[entry.category] || 0) + 1;
            }
        }
        return {
            ok: true,
            status: 200,
            async json() {
                return { ok: true, added, duplicates: entries.length - added, categories };
            },
        };
    }
    // 分类管理：删除词条 / 重命名分类 / 删除分类 / 新建分类
    // (2026-09-16 加的功能；2026-09-17 发现后端把路由声明写在了 return 之后，
    //  这四条全部 405。前端这边必须保证请求体形状正确。)
    if (target.includes("smart_clip/presets/create_category")
        || target.includes("smart_clip/presets/delete_category")
        || target.includes("smart_clip/presets/rename_category")
        || target.includes("smart_clip/presets/delete")) {
        const body = JSON.parse(init.body || "{}");
        if (target.includes("create_category")) {
            CREATED.push(body);
            const existed = Object.prototype.hasOwnProperty.call(CANNED.categories, body.category);
            if (!existed) CANNED.categories[body.category] = [];
            return {
                ok: true, status: 200,
                async json() { return { ok: true, created: !existed, category: body.category }; },
            };
        }
        if (target.includes("delete_category")) {
            DELETED_CATS.push(body);
            const existed = Object.prototype.hasOwnProperty.call(CANNED.categories, body.category);
            delete CANNED.categories[body.category];
            return {
                ok: true, status: 200,
                async json() {
                    return existed ? { ok: true, deleted: body.category }
                                   : { ok: false, error: "分类不存在" };
                },
            };
        }
        if (target.includes("rename_category")) {
            RENAMED.push(body);
            const existed = Object.prototype.hasOwnProperty.call(CANNED.categories, body.old);
            if (existed) {
                CANNED.categories[body.new] = CANNED.categories[body.old];
                delete CANNED.categories[body.old];
            }
            return {
                ok: true, status: 200,
                async json() {
                    return existed ? { ok: true, old: body.old, new: body.new }
                                   : { ok: false, error: "原分类不存在" };
                },
            };
        }
        DELETED.push(body);
        const list = CANNED.categories[body.category] || [];
        const at = list.indexOf(body.text);
        if (at >= 0) list.splice(at, 1);
        if (!list.length) delete CANNED.categories[body.category];   // presets.py 的行为
        return {
            ok: true, status: 200,
            async json() { return { ok: true, deleted: body.text }; },
        };
    }
    if (target.includes("smart_clip/presets/save")) {
        if (globalThis.__SAVE_FAIL__) {
            const status = globalThis.__SAVE_STATUS__;
            return {
                ok: false,
                status,
                async json() {
                    return status === 404 || status === 405
                        ? {}
                        : { ok: false, error: globalThis.__SAVE_FAIL__ };
                },
            };
        }
        const body = JSON.parse(init.body || "{}");
        SAVED.push(body);
        const list = CANNED.categories[body.category] || (CANNED.categories[body.category] = []);
        if (!list.includes(body.text)) list.push(body.text);
        return {
            ok: true,
            status: 200,
            async json() {
                return { ok: true, duplicate: false, category: body.category, count: list.length };
            },
        };
    }
    if (target.includes("smart_clip/presets")) {
        // The stale variant mirrors a backend that predates the write route: no
        // annotations, no stats, and no `writable` flag.
        const payload = globalThis.__STALE_BACKEND__
            ? {
                model: CANNED.model, role: CANNED.role, source: CANNED.source,
                categories: CANNED.categories,
            }
            : CANNED;
        return { ok: true, status: 200, async json() { return payload; } };
    }
    return {
        ok: true,
        status: 200,
        async json() {
            return { items: [{ name: "ponyDiffusionV6XL.safetensors", family: "sdxl", label: "SDXL", preset: "pony", hint: "pony" }] };
        },
    };
};

const textWidget = {
    name: "text",
    value: "",
    element: { value: "", tagName: "TEXTAREA", dispatchEvent() {} },
    callback() {},
};
const dialogNode = {
    id: 900,
    type: "SmartCLIPTextEncode",
    widgets: [textWidget, { name: "prompt_role", value: "auto" }, { name: "prompt_category", value: "" }],
    properties: {},
};

globalThis.__INNER_HTML_WRITES__.length = 0;
const dialog = await PD.PromptDialog.open(dialogNode, { preset: "pony", label: "Pony (SDXL)", family: "sdxl" }, "positive");
checkTrue("dialog opened", !!dialog.overlay);
check("no innerHTML was ever assigned", globalThis.__INNER_HTML_WRITES__.length, 0);

const items = dialog.overlay.findAll("sc-item");
checkTrue("category entries rendered", items.length >= 2);
const nasty = items.find((el) => el.textContent.includes("he said"));
checkTrue("nasty prompt rendered verbatim as text", !!nasty);
const nastyText = nasty.findAll("sc-item-text")[0];
check("...exactly, with quotes and tags intact", nastyText.textContent, NASTY);
checkTrue("no element parsed the tags into children", nastyText.children.length === 0);
check("the row carries its ✕ delete button", nasty.findAll("sc-item-del").length, 1);

nasty.click();
check("click appends to the text widget", textWidget.value, NASTY);
check("the DOM textarea is updated too", textWidget.element.value, NASTY);
check("category annotation is written back",
      dialogNode.widgets.find((w) => w.name === "prompt_category").value, "rating");

console.log("\n[dialog modes]");
dialog.mode = "overwrite";
items[0].click();
check("overwrite mode replaces the text", textWidget.value, "score_9");

dialog.mode = "append";
dialog.weight = 1.2;
items[0].click();
check("weight wraps the appended word", textWidget.value, "score_9, (score_9:1.2)");
dialog.weight = 1;
textWidget.value = "already,";
items[0].click();
check("trailing comma is respected", textWidget.value, "already, score_9");

console.log("\n[dialog role switch]");
dialog.setRole("negative");
await new Promise((r) => setTimeout(r, 10));
check("role widget on the node is updated",
      dialogNode.widgets.find((w) => w.name === "prompt_role").value, "negative");

/* ------------------------------------------------------------------ *
 * 5b. category list layout + embedding badges
 * ------------------------------------------------------------------ */

console.log("\n[dialog category list]");
/** the row's rendered category name (the title also carries hints) */
const catName = (row) => row.findAll("sc-cat-name")[0].textContent;
const catRow = (name) => dialog.overlay.findAll("sc-cat").find((c) => catName(c) === name);
const catTick = () => new Promise((r) => setTimeout(r, 10));

const cats = dialog.overlay.findAll("sc-cat");
check("categories are a list on the left", cats.map(catName), ["rating", "quality", "embeddings"]);
check("each row advertises rename/delete", cats[0].title.includes("右键"), true);
check("the active category is marked", cats[0].classList.contains("sc-on"), true);
check("each row carries its entry count", cats[0].children.at(-1).textContent, "2");
checkTrue("the tabs row is gone", dialog.overlay.findAll("sc-tab").length === 0);

/* 全局分类（后端 shared 列表里的）要能一眼看出来 —— 用户自建、处处可见 */
check("a global category is badged", catRow("quality").findAll("sc-global").length, 1);
check("...with the label", catRow("quality").findAll("sc-global")[0].textContent, "全局");
check("...explaining itself on hover",
      catRow("quality").findAll("sc-global")[0].title.includes("所有工作流"), true);
check("...and the row title says so too", catRow("quality").title.includes("所有工作流"), true);
check("family presets carry no global badge", catRow("rating").findAll("sc-global").length, 0);

catRow("embeddings").click();
check("clicking a category marks it active",
      catRow("embeddings").classList.contains("sc-on"), true);

const embItems = dialog.overlay.findAll("sc-item");
check("its entries are listed on the right", embItems.length, 2);

const badItem = embItems.find((i) => i.textContent.startsWith("embedding:deep_negative_pony"));
checkTrue("incompatible embedding rendered", !!badItem);
check("...greyed out", badItem.classList.contains("sc-incompatible"), true);
check("...with exactly one badge element", badItem.findAll("sc-tag").length, 1);
check("badge class", badItem.findAll("sc-tag")[0].className, "sc-tag");
check("badge names architecture + verdict", badItem.findAll("sc-tag")[0].textContent, "TI-SDXL · 不兼容");
check("tooltip carries the reason", badItem.title.includes("不兼容"), true);

const goodItem = embItems.find((i) => i.textContent.startsWith("embedding:EasyNegative"));
check("compatible embedding badge", goodItem.findAll("sc-tag")[0].textContent, "TI-SD1.5 · 兼容");
check("...and is not greyed", goodItem.classList.contains("sc-incompatible"), false);

catRow("rating").click();
const plainItems = dialog.overlay.findAll("sc-item");
checkTrue("plain words are back", plainItems.length >= 2);
check("plain words carry no annotation badge",
      plainItems.every((i) => i.findAll("sc-tag").length === 0), true);

console.log("\n[dialog cross-category search]");
dialog.searchEl.value = "masterpiece";
dialog.searchEl.dispatchEvent({ type: "input", target: dialog.searchEl });
const hits = dialog.overlay.findAll("sc-item");
check("search finds entries outside the active category", hits.length, 1);
check("...and says where they came from", hits[0].findAll("sc-where")[0].className, "sc-where");
check("...with the category name", hits[0].findAll("sc-where")[0].textContent, "· quality");

dialog.searchEl.value = "zzz-nothing";
dialog.searchEl.dispatchEvent({ type: "input", target: dialog.searchEl });
check("no match shows a hint instead of an empty pane",
      dialog.overlay.findAll("sc-hint").length, 1);

dialog.searchEl.value = "";
dialog.searchEl.dispatchEvent({ type: "input", target: dialog.searchEl });
check("clearing the search restores the category",
      dialog.overlay.findAll("sc-item").length, 2);

console.log("\n[dialog add to library]");
checkTrue("the add box exists", !!dialog.newTextEl && !!dialog.newCatEl);
check("its hint follows the active category",
      dialog.newCatEl.placeholder.includes("rating"), true);

dialog.newTextEl.value = "my brand new word";
dialog.newCatEl.value = "我的库";
await dialog.saveEntry();
check("the request carries model/role/category/text", SAVED.at(-1),
      { model: "pony", role: "negative", category: "我的库", text: "my brand new word" });
check("the input is cleared after saving", dialog.newTextEl.value, "");
check("the status names the category", dialog.addStatusEl.textContent, "已入库到「我的库」");
check("the new category is selected", dialog.activeCategory, "我的库");
const listed = (word) => dialog.overlay.findAll("sc-item")
    .some((i) => i.findAll("sc-item-text")[0]?.textContent === word);
checkTrue("the entry is listed right away", listed("my brand new word"));
check("the category list gained the new row",
      dialog.overlay.findAll("sc-cat").some((c) => catName(c) === "我的库"), true);

/* ------------------------------------------------------------------ *
 * 5c. 分类管理：删除词条 / 右键重命名 / 删除分类 / 新建分类
 * ------------------------------------------------------------------ */

console.log("\n[dialog category management]");
const CAT_SNAPSHOT = JSON.parse(JSON.stringify(CANNED.categories));
globalThis.confirm = () => true;          // the real dialog asks before deleting
let promptAnswer = "";
globalThis.prompt = () => promptAnswer;

// --- ✕ 删除词条
catRow("rating").click();
const delTarget = dialog.overlay.findAll("sc-item")[0];
const delText = delTarget.findAll("sc-item-text")[0].textContent;
delTarget.findAll("sc-item-del")[0].click();
await catTick();
check("✕ posts the entry to /presets/delete", DELETED.at(-1),
      { model: "pony", role: "negative", category: "rating", text: delText });
check("...and the list reloads without it", dialog.overlay.findAll("sc-item").length, 1);

// --- 右键分类 → 重命名
catRow("quality").contextMenu(12, 34);
const menu = document.body.findAll("sc-context-menu");
check("right click opens the category menu", menu.length, 1);
check("the menu offers rename + delete",
      menu[0].findAll("sc-context-menu-item").map((i) => i.textContent),
      ["重命名分类", "删除分类"]);

promptAnswer = "画质词";
menu[0].findAll("sc-context-menu-item")[0].click();
await catTick();
check("重命名 posts old/new", RENAMED.at(-1),
      { model: "pony", role: "negative", old: "quality", new: "画质词" });
check("...and the menu closes", document.body.findAll("sc-context-menu").length, 0);
check("the renamed row is on screen", !!catRow("画质词"), true);

// --- 右键分类 → 删除整个分类
catRow("画质词").contextMenu(1, 1);
document.body.findAll("sc-context-menu")[0].findAll("sc-context-menu-item")[1].click();
await catTick();
check("删除分类 posts the category", DELETED_CATS.at(-1),
      { model: "pony", role: "negative", category: "画质词" });
check("...and the row is gone", !catRow("画质词"), true);

// --- 新建分类：必须真的落盘，否则空分类没有行可以右键
promptAnswer = "我的新分类";
dialog.overlay.findAll("sc-new-cat-btn")[0].click();
await catTick();
check("新建分类 posts create_category", CREATED.at(-1),
      { model: "pony", role: "negative", category: "我的新分类" });
check("the empty category is on screen right away", !!catRow("我的新分类"), true);
check("...and becomes the active one", dialog.activeCategory, "我的新分类");
check("...the status says it is still empty",
      dialog.addStatusEl.textContent.includes("空的"), true);
check("...and no entry row is rendered for it", dialog.overlay.findAll("sc-item").length, 0);

promptAnswer = "";
const createdBefore = CREATED.length;
dialog.overlay.findAll("sc-new-cat-btn")[0].click();
await catTick();
check("cancelling the name prompt sends nothing", CREATED.length, createdBefore);

CANNED.categories = CAT_SNAPSHOT;          // later sections expect the original list

console.log("\n[dialog take-from-node / error paths]");
textWidget.value = "a prompt built in the node";
dialog.takeFromNode();
check("the node's text lands in the box", dialog.newTextEl.value, "a prompt built in the node");
textWidget.value = "";
dialog.takeFromNode();
check("an empty widget is reported", dialog.addStatusEl.textContent, "节点文本框是空的");

dialog.newTextEl.value = "will fail";
globalThis.__SAVE_FAIL__ = "磁盘只读";
await dialog.saveEntry();
check("a server error is shown, not swallowed",
      dialog.addStatusEl.textContent.includes("磁盘只读"), true);
check("...and the text is kept for a retry", dialog.newTextEl.value, "will fail");

globalThis.__SAVE_FAIL__ = "route missing";
globalThis.__SAVE_STATUS__ = 405;
await dialog.saveEntry();
check("a missing route explains the restart",
      dialog.addStatusEl.textContent.includes("重启一次 ComfyUI"), true);
check("...and names the status code", dialog.addStatusEl.textContent.includes("405"), true);
globalThis.__SAVE_FAIL__ = "";
globalThis.__SAVE_STATUS__ = 400;

dialog.newTextEl.value = "   ";
await dialog.saveEntry();
check("an empty box is refused before any request",
      dialog.addStatusEl.textContent, "先输入要入库的提示词");
check("...and nothing was sent", SAVED.length, 1);

console.log("\n[dialog split into categories]");
dialog.newTextEl.value = "masterpiece, 1girl, long hair, red dress, forest";
await dialog.splitEntry();
check("the text is sent to the classifier", CLASSIFIED.at(-1),
      { text: "masterpiece, 1girl, long hair, red dress, forest", model: "pony" });
check("one preview line per target category", dialog.planEl.findAll("sc-plan-line").length, 5);
check("...each line lets the user re-pick the category",
      dialog.planEl.findAll("sc-plan-cat").map((n) => {
          const select = n.children[0];
          return select.children.find((o) => o.selected)?.textContent;
      }),
      ["质量词", "人物", "发型", "衣服", "环境"]);
check("...with the tags listed", dialog.planEl.findAll("sc-plan-tags")[2].textContent, "long hair");
check("the primary button becomes a confirm",
      dialog.splitBtn.textContent, "确认入库（5 条）");
check("whole-entry saving is disabled while a plan is pending",
      dialog.wholeBtn.disabled, true);
check("a cancel button appears", dialog.cancelBtn.style.display, "");
check("the status explains the plan", dialog.addStatusEl.textContent,
      "已分好 5 条，可手动调整分类，确认后写入词库");

// second click writes the plan
await dialog.splitEntry();
check("the batch carries every classified entry", SAVED_BATCHES.at(-1), {
    model: "pony", role: "negative",
    entries: [
        { category: "质量词", text: "masterpiece" },
        { category: "人物", text: "1girl" },
        { category: "发型", text: "long hair" },
        { category: "衣服", text: "red dress" },
        { category: "环境", text: "forest" },
    ],
});
check("the status tallies per category", dialog.addStatusEl.textContent,
      "已入库 5 条：质量词 1 / 人物 1 / 发型 1 / 衣服 1 / 环境 1");
check("the input is cleared", dialog.newTextEl.value, "");
check("the preview is cleared", dialog.planEl.textContent, "");
check("...and the button is back to normal", dialog.splitBtn.textContent, "自动分类拆分");
check("...and whole-entry saving is available again", dialog.wholeBtn.disabled, false);
check("the first new category is selected", dialog.activeCategory, "质量词");
checkTrue("the entries are in the list now", listed("masterpiece"));

console.log("\n[dialog split: cancel + guards]");
dialog.newTextEl.value = "1girl, long hair";
await dialog.splitEntry();
check("a plan is pending", !!dialog.plan, true);
dialog.clearPlan();
check("cancel drops the plan", dialog.plan, null);
check("...clears the preview", dialog.planEl.textContent, "");
check("...restores the label", dialog.splitBtn.textContent, "自动分类拆分");
check("...hides the cancel button", dialog.cancelBtn.style.display, "none");
check("...and re-enables whole-entry saving", dialog.wholeBtn.disabled, false);

const classifyCalls = CLASSIFIED.length;
dialog.newTextEl.value = "   ";
await dialog.splitEntry();
check("an empty box is refused before classifying",
      dialog.addStatusEl.textContent, "先输入要入库的提示词");
check("...and no request was made", CLASSIFIED.length, classifyCalls);

console.log("\n[dialog split: unbreakable / partially dropped input]");
globalThis.__CLASSIFY_FORCE__ = { tags: [], dropped: ["x".repeat(60)] };
dialog.newTextEl.value = "x".repeat(2100);
await dialog.splitEntry();
check("a non-empty box is no longer blamed for being empty",
      dialog.addStatusEl.textContent,
      "拆不出任何词条：这段内容没有任何可断句的位置，请自己插入逗号或换行再试");
check("...and no plan is created", dialog.plan, null);
globalThis.__CLASSIFY_FORCE__ = { tags: [{ text: "1girl", category: "人物" }], dropped: ["y".repeat(60)] };
await dialog.splitEntry();
check("a partially dropped paste still opens a plan",
      dialog.planEl.findAll("sc-plan-line").length, 1);
check("...and the status admits what was skipped",
      dialog.addStatusEl.textContent.includes("另有 1 段过长无法断句"), true);
check("...the plan carries the dropped count", dialog.plan.dropped, 1);
dialog.clearPlan();
globalThis.__CLASSIFY_FORCE__ = null;

console.log("\n[dialog singleton]");
const second = await PD.PromptDialog.open(dialogNode, { preset: "pony" }, "positive");
check("opening again replaces the first", PD.PromptDialog._current === second, true);
checkTrue("the first overlay was removed from the body", !globalThis.document.body.children.includes(dialog.overlay));

console.log("\n[stale backend (no write route yet)]");
globalThis.__STALE_BACKEND__ = true;
const stale = await PD.PromptDialog.open(dialogNode, { preset: "pony" }, "positive");
check("the split button is disabled", stale.splitBtn.disabled, true);
check("the whole-entry button is disabled", stale.wholeBtn.disabled, true);
check("...with the restart explanation", stale.addStatusEl.textContent,
      "后端还是旧版本：重启一次 ComfyUI 后即可入库");
stale.newTextEl.value = "nope";
const batchesBefore = SAVED_BATCHES.length;
await stale.splitEntry();
await stale.saveEntry();
check("clicking does not send anything", [SAVED.length, SAVED_BATCHES.length], [1, batchesBefore]);
globalThis.__STALE_BACKEND__ = false;
stale.close();

console.log("\n[combo widget write shape]");
const combo = { name: "text", value: { content: "old" }, callback() {} };
PD.writeWidget(combo, "new");
check("{content:...} shape is preserved", combo.value, { content: "new" });

console.log("\n[extension registration]");
await import("./web/js/smart_clip_extension.js");
const { registry, StubElement } = await import("./scripts/app.js");
const clipExt = registry.extensions.find((e) => e.name === "SmartCLIP.Extension");
checkTrue("SmartCLIP 主扩展已注册", clipExt);
checkTrue("debug helper exposed", typeof globalThis.SmartCLIPDebug?.model === "function");

/* 词嵌入的图片弹窗（含节点上的按钮）已于 2026-09-15 删除，只保留打字补全，
   但补全引擎住在同一个扩展的 setup() 里，所以扩展本身必须还在。 */
const embExt = registry.extensions.find((e) => e.name === "SmartCLIP.Embedding");
checkTrue("词嵌入扩展随插件一起注册", embExt);
check("SmartCLIP 的两个扩展共存",
    registry.extensions.filter((e) => String(e.name).startsWith("SmartCLIP.")).length, 2);

/* ------------------------------------------------------------------ *
 * 6. the button must also appear on the STOCK CLIPTextEncode
 * ------------------------------------------------------------------ */

console.log("\n[dialog button on native nodes]");
const extension = clipExt;

function makeNode(withTextWidget) {
    const node = {
        comfyClass: "CLIPTextEncode",
        widgets: [],
        properties: {},
        inputs: [],
        outputs: [],
        graph,
        addWidget(type, label, value, callback) {
            const widget = { type, name: label, label, value, callback, options: {} };
            this.widgets.push(widget);
            return widget;
        },
    };
    if (withTextWidget) {
        node.widgets.push({
            name: "text", value: "", callback() {},
            element: { value: "", tagName: "TEXTAREA", dispatchEvent() {} },
        });
    }
    return node;
}

async function buttonFor(typeName, withTextWidget) {
    const nodeType = { prototype: { onNodeCreated: null } };
    await extension.beforeRegisterNodeDef(nodeType, { name: typeName });
    const node = makeNode(withTextWidget);
    if (typeof nodeType.prototype.onNodeCreated === "function") {
        nodeType.prototype.onNodeCreated.call(node);
    }
    const button = node.widgets.find((w) => String(w.label || w.name || "").includes("选择提示词"));
    return { node, button };
}

let res = await buttonFor("CLIPTextEncode", true);
checkTrue("stock CLIPTextEncode got the button", !!res.button);
check("button is not serialised into the workflow", res.button && res.button.serialize, false);
checkTrue("callback opens the dialog", !!(res.button && typeof res.button.callback === "function"));

res = await buttonFor("CLIPTextEncodeSDXL", true);
checkTrue("CLIPTextEncodeSDXL got the button", !!res.button);

res = await buttonFor("CLIPTextEncode", false);
check("a node without a text widget gets no button", res.button, undefined);

res = await buttonFor("KSampler", true);
check("unrelated node types are untouched", res.button, undefined);

res = await buttonFor("SmartCLIPTextEncode", true);
checkTrue("SmartCLIPTextEncode still gets it", !!res.button);

/* ------------------------------------------------------------------ *
 * 7. 词嵌入：独立弹窗已删除，只留打字补全
 * ------------------------------------------------------------------ */

console.log("\n[embedding: popup gone, type-ahead kept]");
const EMB = await import("./web/js/embedding_picker.js");
check("the deleted global picker entry point is still gone", typeof EMB.openPicker, "undefined");
check("the picker is only reachable from the prompt dialog",
    typeof EMB.openEmbeddingPicker, "function");
check("no external-target hook is exported", typeof EMB.setExternalTarget, "undefined");
check("no model-family hook is exported", typeof EMB.setCompatFamily, "undefined");
check("the extension no longer hooks node definitions",
    typeof embExt.beforeRegisterNodeDef, "undefined");

/* setup() is where the completion engine lives - it must survive the删改. */
await embExt.setup();
check("no floating button was created", globalThis.document.body.findAll("sc-emb-fab").length, 0);
check("no picker backdrop was created", globalThis.document.body.findAll("sc-emb-backdrop").length, 0);

function makePromptBox(value) {
    const box = new StubElement("textarea");
    box.nodeType = 1;
    box.isConnected = true;
    box.value = value;
    box.selectionStart = box.selectionEnd = value.length;
    box.matches = (sel) => String(sel).includes("comfy-multiline-input");
    box.setRangeText = function (text, start, end) {
        this.value = this.value.slice(0, start) + text + this.value.slice(end);
        this.selectionStart = this.selectionEnd = start + text.length;
    };
    box.getBoundingClientRect = () => ({ left: 10, top: 10, right: 210, bottom: 40, width: 200, height: 30 });
    return box;
}

const box = makePromptBox("embedding:deep");
globalThis.document.dispatch("input", { target: box, isComposing: false });
const rows = globalThis.document.body.findAll("sc-emb-popup-row");
check("typing the prefix suggests the matching name", rows.map((r) => r.textContent), ["deep_negative_pony"]);
const popup = globalThis.document.body.findAll("sc-emb-popup")[0];
check("the suggestion list is shown", popup && popup.style.display, "block");

let swallowed = 0;
globalThis.document.dispatch("keydown", {
    key: "Enter", target: box,
    preventDefault() { swallowed++; }, stopPropagation() {},
});
check("Enter completes at the caret", box.value, "embedding:deep_negative_pony");
check("...and the key is swallowed", swallowed, 1);
check("...and the list is hidden again", popup.style.display, "none");

/* 裸名字也要补 embedding: 前缀，否则 ComfyUI 根本不会解析 */
const box2 = makePromptBox("ea");
globalThis.document.dispatch("input", { target: box2, isComposing: false });
const rows2 = globalThis.document.body.findAll("sc-emb-popup-row");
check("a bare name is offered with its prefix", rows2.map((r) => r.textContent), ["embedding:EasyNegative"]);
globalThis.document.dispatch("keydown", {
    key: "Tab", target: box2,
    preventDefault() {}, stopPropagation() {},
});
check("Tab writes the prefix too", box2.value, "embedding:EasyNegative");

/* ------------------------------------------------------------------ *
 * 7b. 词嵌入选择器：提示词弹窗头部按钮 + 卡片兼容标记
 *
 * 颜色语义直接抄模型弹窗（model_conflict.js）：红 = 不兼容、蓝 = 兼容、
 * 绿 = 当前使用（绿优先）。判定来自 /smart_clip/embeddings?family=... ，
 * 与词条徽标同源。负面提示词下同样要标（role=negative 用例）。
 * ------------------------------------------------------------------ */

console.log("\n[词嵌入 picker: header button + compat colours]");
/** The picker fetches its (family-specific) list asynchronously - let it land. */
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

const embNode = addNode("SmartCLIPTextEncode", {
    text: "1girl, embedding:EasyNegative",
    prompt_role: "negative",
}, 200);

const embDialog = await PD.PromptDialog.open(
    embNode, { preset: "pony", label: "Pony (SDXL)", family: "sdxl" }, "negative");

check("header carries the 词嵌入 button", embDialog.embedBtn.textContent, "词嵌入");
check("the picker starts closed", EMB.isEmbeddingPickerOpen(), false);

embDialog.embedBtn.click();
await tick();
check("clicking it opens the picker", EMB.isEmbeddingPickerOpen(), true);
check("...as a sub-dialog (one backdrop, created lazily)",
    globalThis.document.body.findAll("sc-emb-backdrop").length, 1);
check("...which says where the pick goes",
    globalThis.document.body.findAll("sc-emb-where")[0].textContent,
    "插入到: 负面提示词 · 模型族 pony");

/* 选择器开着的时候打字补全要闭嘴（插入会写回节点文本框并派发 input） */
const popupWhileOpen = globalThis.document.body.findAll("sc-emb-popup")[0];
globalThis.document.dispatch("input", {
    target: makePromptBox("embedding:deep"), isComposing: false,
});
check("the completion popup stays shut while the picker is open",
    popupWhileOpen.style.display, "none");

const embCards = globalThis.document.body.findAll("sc-emb-card");
check("one card per embedding", embCards.map((c) => c.dataset.name),
    ["EasyNegative", "deep_negative_pony", "bad_vae_embedding"]);
const cardOf = (name) => embCards.find((c) => c.dataset.name === name);

check("incompatible embedding is red (same as the LoRA popup)",
    cardOf("deep_negative_pony").classList.contains("sc-emb-cf-red"), true);
check("...and carries its verdict badge",
    cardOf("deep_negative_pony").findAll("sc-emb-badge")[0].textContent,
    "TI-SD1.5 · 不兼容");
check("a halved embedding is amber, not blue (SDXL drops it on CLIP-G)",
    cardOf("EasyNegative").classList.contains("sc-emb-cf-amber"), true);
check("...so it is not painted as fully compatible",
    cardOf("EasyNegative").classList.contains("sc-emb-cf-blue"), false);
check("...with 半兼容 in the badge",
    cardOf("EasyNegative").findAll("sc-emb-badge")[0].textContent,
    "TI-SD1.5 · 半兼容");
check("a missing file is labelled, not coloured",
    cardOf("bad_vae_embedding").findAll("sc-emb-badge")[0].textContent, "未安装");
check("an embedding already in the prompt is green + marked 当前使用",
    cardOf("EasyNegative").classList.contains("sc-emb-current"), true);
check("...and sorted first",
    globalThis.document.body.findAll("sc-emb-card")[0].dataset.name, "EasyNegative");
check("...with the green ribbon",
    cardOf("EasyNegative").findAll("sc-emb-now")[0].textContent, "当前使用");

/* 单击插入：走的是提示词弹窗自己的追加/权重逻辑（单击延迟 240ms 等双击判定） */
const settle = () => new Promise((resolve) => setTimeout(resolve, 320));

cardOf("deep_negative_pony").click();
await settle();
check("a click inserts embedding:NAME", embNode.widgets[0].value,
    "1girl, embedding:EasyNegative, embedding:deep_negative_pony");
check("...and the picker stays open for the next one",
    EMB.isEmbeddingPickerOpen(), true);
const embCards2 = globalThis.document.body.findAll("sc-emb-card");
check("...and the new one is marked 当前使用",
    embCards2.find((c) => c.dataset.name === "deep_negative_pony")
        .classList.contains("sc-emb-current"), true);

embDialog.weight = 1.2;
embCards2.find((c) => c.dataset.name === "bad_vae_embedding").click();
await settle();
check("weight != 1 wraps it as (embedding:name:w) - valid for the tokenizer",
    embNode.widgets[0].value,
    "1girl, embedding:EasyNegative, embedding:deep_negative_pony, (embedding:bad_vae_embedding:1.2)");

const embSearch = globalThis.document.body.findAll("sc-emb-search")[0];
embSearch.value = "vae";
embSearch.dispatchEvent({ type: "input" });
check("search filters the grid",
    globalThis.document.body.findAll("sc-emb-card").map((c) => c.dataset.name),
    ["bad_vae_embedding"]);
embSearch.value = "";
embSearch.dispatchEvent({ type: "input" });
check("clearing the search restores every card",
    globalThis.document.body.findAll("sc-emb-card").length, 3);

const embUndo = globalThis.document.body.findAll("sc-emb-btn")
    .find((b) => b.textContent.startsWith("撤销插入"));
check("the undo button counts the insertions", embUndo.textContent, "撤销插入 (2)");
embUndo.click();
check("undo takes the last insertion back", embNode.widgets[0].value,
    "1girl, embedding:EasyNegative, embedding:deep_negative_pony");

/* 双击必须只插一次（浏览器会先派两次 click）——这是单点延迟 240ms 的原因 */
const dblCard = globalThis.document.body.findAll("sc-emb-card")
    .find((c) => c.dataset.name === "bad_vae_embedding");
dblCard.dispatchEvent({ type: "click" });
dblCard.dispatchEvent({ type: "click" });
dblCard.dispatchEvent({ type: "dblclick" });
await settle();
check("double-click inserts exactly once",
    embNode.widgets[0].value,
    "1girl, embedding:EasyNegative, embedding:deep_negative_pony, (embedding:bad_vae_embedding:1.2)");
check("...and closes the picker", EMB.isEmbeddingPickerOpen(), false);

/* Esc 只关子弹窗，不能把「选择提示词」一起关掉 */
embDialog.embedBtn.click();
await tick();
globalThis.document.dispatch("keydown", { key: "Escape", stopPropagation() {} });
check("Esc closes the picker only", EMB.isEmbeddingPickerOpen(), false);
check("...the prompt dialog stays open", PD.PromptDialog._current === embDialog, true);

embDialog.embedBtn.click();
await tick();
check("reopening reuses the same picker element",
    globalThis.document.body.findAll("sc-emb-backdrop").length, 1);
embDialog.close();
check("closing the prompt dialog closes the picker too",
    EMB.isEmbeddingPickerOpen(), false);

/* ------------------------------------------------------------------ *
 * 8. LoRA 堆叠：与底模不兼容的名字标红
 * ------------------------------------------------------------------ */

console.log("\n[LoRA stack: incompatible names go red]");
const LS = await import("./web/js/lora_stack.js");

function makeCtx() {
    const ctx = {
        fillStyle: "", strokeStyle: "", lineWidth: 1,
        font: "", textAlign: "", textBaseline: "",
        texts: [],
        save() {}, restore() {}, beginPath() {}, closePath() {},
        fill() {}, stroke() {}, moveTo() {}, lineTo() {},
        quadraticCurveTo() {}, roundRect() {},
        measureText(text) { return { width: String(text).length * 7 }; },
        fillText(text) { ctx.texts.push({ text: String(text), colour: ctx.fillStyle }); },
    };
    return ctx;
}

const stackNode = {
    id: 77, type: "JosiaLoraStack", comfyClass: "JosiaLoraStack",
    properties: {}, size: [500, 320], widgets: [],
    _st: [
        { name: "fluxLora.safetensors", en: true, sm: 0.8, sc: 0 },
        { name: "ponyLora.safetensors", en: true, sm: 0.8, sc: 0 },
        { name: "mysteryLora.safetensors", en: true, sm: 0.8, sc: 0 },
    ],
};
graph._nodes.push(stackNode);

await LS.refreshConflicts();
check("the stack asked the conflict backend", globalThis.__MC_CALLS__.length, 1);
const call = globalThis.__MC_CALLS__[0] || {};
check("...for kind=loras", call.kind, "loras");
check("...with every name on the stack", call.names,
    ["fluxLora.safetensors", "ponyLora.safetensors", "mysteryLora.safetensors"]);
check("...and the graph's checkpoint as the reference", call.picks,
    { checkpoints: ["hassakuXLIllustrious_v13StyleA.safetensors"] });
check("conflict verdict is cached", LS.conflictState("fluxLora.safetensors"), "conflict");
check("ok verdict is cached", LS.conflictState("ponyLora.safetensors"), "ok");
check("unknown verdict is cached", LS.conflictState("mysteryLora.safetensors"), "unknown");

function nameColour(index, enabled = true) {
    const ctx = makeCtx();
    const state = Object.assign({}, stackNode._st[index], { en: enabled });
    LS.drawName(ctx, null, 500, 0, index + 1, state, false);
    const wanted = state.name.replace(/\.safetensors$/, "");
    const row = ctx.texts.find((t) => t.text === wanted);
    return row ? row.colour : "(name not drawn)";
}

check("incompatible LoRA name is red", nameColour(0), "#ff5f56");
check("...while the row prefix keeps its colour", (() => {
    const ctx = makeCtx();
    LS.drawName(ctx, null, 500, 0, 1, stackNode._st[0], false);
    return ctx.texts.find((t) => t.text === "LoRA 1: ").colour;
})(), "#ddd");
check("compatible LoRA name keeps its colour", nameColour(1), "#ddd");
check("unknown architecture is not painted red", nameColour(2), "#ddd");
check("a switched-off row is still greyed", nameColour(1, false), "#666");
check("...unless it is incompatible", nameColour(0, false), "#ff5f56");

const callsBefore = globalThis.__MC_CALLS__.length;
await LS.refreshConflicts();
check("an unchanged stack does not re-ask", globalThis.__MC_CALLS__.length, callsBefore);

/* ------------------------------------------------------------------ *
 * 9. 底模兜底：连线走 LoRA 堆叠 / 断线 / 检测失败时别退化成「未知」
 *
 * 用户那张图的形状是 CheckpointLoaderSimple -> JosiaLoraStack -> CLIPTextEncode。
 * 只要有一条环节走不通（中间隔了社区节点、页面比服务端先起来、浏览器拿着旧
 * 缓存），前端就只能报 generic，词嵌入弹窗会整片变成「未知」——所以现在：
 * 走不动线就读加载器控件本身，检测失败重试一次，已经有判定就不许被清空。
 * ------------------------------------------------------------------ */

console.log("\n[base-model fallback]");

const stackNode2 = addNode("JosiaLoraStack", { lora_name_1: "None" }, 301);
const stackEnc = addNode("CLIPTextEncode", { text: "embedding:easynegativev2" }, 302);
connect(ckpt, 0, 0, stackNode2);
connect(stackNode2, 0, 0, stackEnc);

check("the trace follows a LoRA stack in the middle",
    MC.traceUpstream(stackEnc).names.map((n) => n.name),
    ["hassakuXLIllustrious_v13StyleA.safetensors"]);
check("the graph scan reads the loader widget itself",
    MC.graphLoaderNames(graph).map((n) => n.name),
    ["hassakuXLIllustrious_v13StyleA.safetensors"]);
check("...ranking a checkpoint above a bare CLIP loader", (() => {
    const g = {
        _nodes: [
            { type: "CLIPLoader", widgets: [{ name: "clip_name", value: "clip_l.safetensors" }] },
            { type: "CheckpointLoaderSimple", widgets: [{ name: "ckpt_name", value: "base.safetensors" }] },
        ],
    };
    return MC.graphLoaderNames(g).map((n) => n.name);
})(), ["base.safetensors", "clip_l.safetensors"]);
check("...and ignoring a loader whose widget is still empty", (() => {
    const g = { _nodes: [{ type: "CheckpointLoaderSimple", widgets: [{ name: "ckpt_name", value: "None" }] }] };
    return MC.graphLoaderNames(g).length;
})(), 0);

const realFetch = globalThis.fetch;
const detectCalls = [];

/** fetch that answers /smart_clip/detect from a table: name -> record. */
function scriptedDetect(records) {
    globalThis.fetch = async (url, init) => {
        const target = String(url);
        if (target.includes("/smart_clip/detect")) {
            detectCalls.push(decodeURIComponent(/[?&]names=([^&]*)/.exec(target)?.[1] || ""));
            const record = records[decodeURIComponent(/[?&]names=([^&]*)/.exec(target)?.[1] || "")];
            return {
                ok: true,
                status: 200,
                async json() {
                    return { kind: "checkpoints", items: record ? [record] : [] };
                },
            };
        }
        return realFetch(url, init);
    };
}

const SDXL_RECORD = {
    name: "hassakuXLIllustrious_v13StyleA.safetensors",
    family: "sdxl", label: "SDXL", preset: "illustrious",
    score_tags: false, evidence: "keys~sdxl", hint: "",
};

/** A graph with exactly one loader, so a scripted detect answer is enough. */
function graphWithLoader(name, type = "CheckpointLoaderSimple", field = "ckpt_name") {
    return {
        _nodes: [{ type, comfyClass: type, widgets: [{ name: field, value: name }], properties: {} }],
        _links: new Map(),
        getNodeById: () => null,
    };
}

try {
    /* (a) 断线的节点：线走不动，但图里写着底模 */
    scriptedDetect({
        "graph_base.safetensors": Object.assign({}, SDXL_RECORD, { name: "graph_base.safetensors" }),
    });
    const orphan = addNode("CLIPTextEncode", { text: "" }, 303);
    orphan.graph = graphWithLoader("graph_base.safetensors");
    MC.ModelTracker.init(orphan);
    await MC.ModelTracker.refreshFromGraph(orphan);
    check("a cut CLIP wire still finds the base model",
        MC.ModelTracker.getModel(orphan).preset, "illustrious");
    check("...and admits it came from the graph scan",
        MC.ModelTracker.state(orphan).graph.via, "graph");
    check("...with the file the loader widget names",
        MC.ModelTracker.getModel(orphan).name, "graph_base.safetensors");
    check("...while a walkable wire keeps claiming the wire", (() => {
        const wired = addNode("SmartCLIPTextEncode", { text: "", prompt_role: "auto" }, 307);
        MC.ModelTracker.init(wired);
        return MC.traceUpstream(stackEnc).names.length > 0;
    })(), true);

    /* (b) 图里根本没有加载器：上一份判定不许被清空 */
    const lonely = addNode("CLIPTextEncode", { text: "" }, 304);
    lonely.graph = { _nodes: [], _links: new Map(), getNodeById: () => null };
    lonely.properties = {
        smart_clip: {
            graph: {
                name: "old.safetensors", kind: "checkpoints", hint: "",
                family: "sdxl", label: "SDXL", preset: "sdxl", evidence: "cached",
            },
        },
    };
    await MC.ModelTracker.refreshFromGraph(lonely);
    check("a graph that names no loader keeps the last verdict",
        MC.ModelTracker.getModel(lonely).preset, "sdxl");
    check("...and keeps the model it belonged to",
        MC.ModelTracker.getModel(lonely).name, "old.safetensors");

    /* (c) 服务端认不出来时，旧判定必须让位（不许假装还认识） */
    scriptedDetect({
        "mystery_base.safetensors": {
            name: "mystery_base.safetensors", family: "unknown", label: "未识别",
            preset: "generic", score_tags: false, evidence: "unreadable", hint: "",
        },
    });
    const mystery = addNode("CLIPTextEncode", { text: "" }, 305);
    mystery.graph = graphWithLoader("mystery_base.safetensors");
    mystery.properties = {
        smart_clip: { graph: { name: "old.safetensors", family: "sdxl", preset: "sdxl", label: "SDXL" } },
    };
    await MC.ModelTracker.refreshFromGraph(mystery);
    check("a server 'unknown' is not hidden by an older model",
        MC.ModelTracker.getModel(mystery).preset, "generic");

    /* (d) 页面比服务端先起来：一次失败要重试，第二次不许白等 */
    let attempts = 0;
    globalThis.fetch = async (url, init) => {
        const target = String(url);
        if (target.includes("/smart_clip/detect")) {
            attempts++;
            if (attempts === 1) throw new Error("routes not up yet");
            return {
                ok: true,
                status: 200,
                async json() {
                    return {
                        kind: "checkpoints",
                        items: [{
                            name: "retry_me.safetensors", family: "sdxl", label: "SDXL",
                            preset: "sdxl", score_tags: false, evidence: "keys~sdxl", hint: "",
                        }],
                    };
                },
            };
        }
        return realFetch(url, init);
    };
    const retried = addNode("CLIPTextEncode", { text: "" }, 306);
    retried.graph = graphWithLoader("retry_me.safetensors");
    MC.ModelTracker.init(retried);
    await MC.ModelTracker.refreshFromGraph(retried);
    check("a detect that failed while the server started is retried", attempts, 2);
    check("...and the retry's verdict is the one shown",
        MC.ModelTracker.getModel(retried).preset, "sdxl");

    /* (e) 弹窗要说出「这个判定是谁给的」 */
    const pickerCalls = [];
    globalThis.fetch = async (url, init) => {
        const target = String(url);
        if (target.includes("/smart_clip/embeddings")) {
            const family = decodeURIComponent(/[?&]family=([^&]*)/.exec(target)?.[1] || "");
            pickerCalls.push(family);
            return {
                ok: true,
                status: 200,
                async json() {
                    const judged = family === "generic" ? "illustrious" : family;
                    return {
                        family: judged,
                        familySource: family === "generic" ? "workflow" : "client",
                        items: EMBS.map((name) => ({
                            name, hasPreview: false,
                            compat: {
                                kind: "embedding", name, state: "partial", short: "TI-SD1.5",
                                why: "半兼容：只有 CLIP-L 吃它",
                            },
                        })),
                    };
                },
            };
        }
        return realFetch(url, init);
    };
    EMB.openEmbeddingPicker({ family: "generic", role: "negative", getText: () => "", onPick: () => true });
    await tick();
    check("the picker names the family the backend judged with",
        globalThis.document.body.findAll("sc-emb-where")[0].textContent,
        "插入到: 负面提示词 · 模型族 illustrious（按工作流推断）");
    check("...and the cards carry that verdict",
        globalThis.document.body.findAll("sc-emb-card")[0].findAll("sc-emb-badge")[0].textContent,
        "TI-SD1.5 · 半兼容");

    await EMB.setEmbeddingFamily("sd15");
    check("re-detecting the model re-judges the open list",
        globalThis.document.body.findAll("sc-emb-where")[0].textContent,
        "插入到: 负面提示词 · 模型族 sd15");
    check("...by asking the backend for the new family", pickerCalls, ["generic", "sd15"]);
    check("...without closing the picker", EMB.isEmbeddingPickerOpen(), true);
    await EMB.setEmbeddingFamily("sd15");
    check("...and not re-asking when nothing changed", pickerCalls, ["generic", "sd15"]);
    EMB.closeEmbeddingPicker();
} finally {
    globalThis.fetch = realFetch;
}

console.log("\nFAILURES:", fail);
process.exitCode = fail ? 1 : 0;
