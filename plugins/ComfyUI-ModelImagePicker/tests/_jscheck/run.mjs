/**
 * Headless harness for the picker's conflict module.
 *
 * It loads the real web/js/model_conflict.js (copied next to a stubbed
 * scripts/app.js so the relative import resolves), stubs fetch's base URL plus
 * the two DOM APIs the module uses, and drives it with a fake graph that mirrors
 * workflow.json: an SD1.5 checkpoint plus a LoRA stack mixing Krea2 / SDXL LoRAs and
 * SD1.5 + SDXL textual inversions.
 */

const BASE = process.env.MCM_BASE || "http://127.0.0.1:8189";

/* ------------------------------------------------------------------ *
 * Minimal DOM stub (only what model_conflict.js touches)
 * ------------------------------------------------------------------ */
class StubElement {
    constructor(tag) {
        this.tagName = String(tag).toUpperCase();
        this.children = [];
        this.style = {};
        this.dataset = {};
        this._text = "";
        this._classes = new Set();
        this.classList = {
            add: (...c) => c.forEach((x) => this._classes.add(x)),
            remove: (...c) => c.forEach((x) => this._classes.delete(x)),
            contains: (c) => this._classes.has(c),
        };
    }
    set className(v) {
        this._classes = new Set(String(v).split(/\s+/).filter(Boolean));
    }
    get className() {
        return [...this._classes].join(" ");
    }
    set textContent(v) {
        this._text = String(v);
        this.children = [];
    }
    get textContent() {
        return this._text + this.children.map((c) => c.textContent || "").join("");
    }
    append(...nodes) {
        for (const n of nodes) {
            this.children.push(typeof n === "string" ? { textContent: n } : n);
        }
    }
    appendChild(n) {
        this.append(n);
        return n;
    }
    querySelectorAll() {
        return [];
    }
}

globalThis.document = {
    createElement: (tag) => new StubElement(tag),
    createTextNode: (text) => ({ textContent: String(text) }),
    head: { appendChild() {} },
    body: { appendChild() {} },
};

globalThis.__FAKE_GRAPH = {
    _nodes: [
        {
            type: "CheckpointLoaderSimple",
            widgets: [{ name: "ckpt_name", value: "majicmixRealistic_v7.safetensors" }],
        },
        {
            type: "VAELoader",
            widgets: [{ name: "vae_name", value: "sd1.5\\vae-ft-mse-840000-ema-pruned.safetensors" }],
        },
        {
            // LoRA stack: ten STRING slots, exactly like ComfyUI_JosiaNodes
            type: "JosiaLoraStack",
            widgets: [
                { name: "lora_name_1", value: "写实\\snofs_krea_v1_4文件超级大.safetensors" },
                { name: "lora_name_2", value: "add-detail-xl.safetensors" },
                { name: "lora_name_3", value: "None" },
                { name: "lora_name_4", value: "写实\\ass_v2_krea2_loraholic.safetensors" },
                { name: "lora_name_5", value: "privet-part.safetensors" },
            ],
        },
        {
            type: "CLIPTextEncode",
            widgets: [{
                name: "text",
                value: "masterpiece, embedding:EasyNegative, embedding:deep_negative_pony, "
                    + "embedding:badhandv4, best quality",
            }],
        },
    ],
};

globalThis.fetch = ((orig) => (url, init) => orig(url.startsWith("http") ? url : BASE + url, init))(
    globalThis.fetch,
);

let fail = 0;
function expect(label, got, want) {
    const ok = JSON.stringify(got) === JSON.stringify(want);
    if (!ok) fail++;
    console.log(`  ${ok ? "OK  " : "FAIL"} ${label.padEnd(46)} ${ok ? JSON.stringify(got) : "got " + JSON.stringify(got) + " want " + JSON.stringify(want)}`);
}

const MC = await import("./web/js/model_conflict.mjs");

console.log("[index]");
await MC.ensureIndex();
expect("kindOf(checkpoint)", MC.kindOf("majicmixRealistic_v7.safetensors"), "checkpoints");
expect("kindOf(lora, ascii)", MC.kindOf("add-detail-xl.safetensors"), "loras");
expect("kindOf(lora, chinese folder + backslash)",
    MC.kindOf("写实\\snofs_krea_v1_4文件超级大.safetensors"), "loras");
expect("kindOf(vae in subfolder)",
    MC.kindOf("sd1.5\\vae-ft-mse-840000-ema-pruned.safetensors"), "vae");
expect("kindOf(unknown string)", MC.kindOf("masterpiece, best quality"), "");
expect("kindOf(vae named with U+2011 smart hyphens)",
    MC.kindOf("vae\u2011ft\u2011mse\u2011840000\u2011ema\u2011pruned.safetensors"), "vae");
expect("kindOf(vae quoted without its subfolder)",
    MC.kindOf("vae-ft-mse-840000-ema-pruned.safetensors"), "vae");
expect("kindOf(embedding referenced without extension)",
    MC.kindOf("EasyNegative"), "embeddings");

console.log("\n[graphPicks]");
const picks = MC.graphPicks();
expect("checkpoints", picks.checkpoints, ["majicmixRealistic_v7.safetensors"]);
expect("vae", picks.vae, ["sd1.5\\vae-ft-mse-840000-ema-pruned.safetensors"]);
expect("loras found in the stack", picks.loras, [
    "写实\\snofs_krea_v1_4文件超级大.safetensors",
    "add-detail-xl.safetensors",
    "写实\\ass_v2_krea2_loraholic.safetensors",
    "privet-part.safetensors",
]);
expect("embeddings from prompt text", picks.embeddings,
    ["EasyNegative", "deep_negative_pony", "badhandv4"]);

console.log("\n[statusFor -> live backend]");
const status = await MC.statusFor("loras", [
    "add-detail-xl.safetensors",
    "privet-part.safetensors",
    "约尔4V.safetensors",
    "写实\\snofs_krea_v1_4文件超级大.safetensors",
]);
expect("status returned", !!status, true);
expect("reference label", status.reference.label, "SD 1.5");
expect("add-detail-xl red", status.items["add-detail-xl.safetensors"].state, "conflict");
expect("privet-part red", status.items["privet-part.safetensors"].state, "conflict");
expect("krea2 red", status.items["写实\\snofs_krea_v1_4文件超级大.safetensors"].state, "conflict");
expect("sd1.5 lora blue", status.items["约尔4V.safetensors"].state, "ok");
expect("arch tag shown on the card", status.items["add-detail-xl.safetensors"].short, "SDXL");
expect("counts", status.counts, { conflict: 3, ok: 1, unknown: 0 });

console.log("\n[card painting]");
const card = new StubElement("div");
MC.applyCardState(card, status, "add-detail-xl.safetensors");
expect("red class added", card.classList.contains("mip-cf-red"), true);
expect("tooltip carries the reason", card.title.includes("SDXL") && card.title.includes("基准"), true);
expect("arch badge appended", card.children.at(-1).textContent, "SDXL");
expect("badge is the arch chip", card.children.at(-1).className, "mip-arch");

const blue = new StubElement("div");
MC.applyCardState(blue, status, "约尔4V.safetensors");
expect("blue class added", blue.classList.contains("mip-cf-blue"), true);
expect("no red on a compatible card", blue.classList.contains("mip-cf-red"), false);

const active = new StubElement("div");
active.className = "mip-card mip-sel";
MC.applyCardState(active, status, "add-detail-xl.safetensors");
expect("active card keeps its class and gains red", active.className, "mip-card mip-sel mip-cf-red");

const unknown = new StubElement("div");
MC.applyCardState(unknown, { items: { "x.safetensors": { state: "unknown", label: "未识别", short: "?" } } }, "x.safetensors");
expect("unknown cards stay unpainted", [unknown.className, unknown.children.length], ["", 0]);

console.log("\n[legend]");
const legend = MC.buildLegend(status);
expect("legend shows the baseline", legend.textContent.includes("基准: SD 1.5"), true);
expect("legend shows the source", legend.textContent.includes("majicmixRealistic_v7.safetensors"), true);
expect("legend tallies conflicts", legend.textContent.includes("3 冲突"), true);
expect("legend tallies compatibility", legend.textContent.includes("1 兼容"), true);
const tally = legend.children.find((c) => c.className === "mip-tally");
expect("legend chips are coloured", tally.children[0].style.background, MC.COLOURS.conflict);
expect("legend has a conflict chip and a compatible chip", tally.children.length, 2);

const noRef = await MC.statusFor("loras", ["add-detail-xl.safetensors"]);
expect("no reference without a workflow", MC.buildLegend({
    reference: null, counts: { conflict: 0, ok: 0, unknown: 1 }, graph: {}, items: {},
}).textContent.includes("暂不着色"), true);
expect("statusFor still works with an empty graph", !!noRef, true);

console.log("\n[patched picker wiring]");
const src = await (await fetch("/extensions/ComfyUI_ModelImagePicker/model_image_picker.js")).text();
expect("picker imports the conflict module", src.includes('from "./model_conflict.js"'), true);
expect("picker asks for the status", src.includes("await statusFor(this.kind"), true);
expect("picker paints each card", src.includes("applyCardState(card, this.status, item.name)"), true);
expect("picker shows the legend", src.includes("buildLegend(this.status)"), true);
expect("green wins over red/blue on the active card",
    src.includes(".mip-card.mip-cf-red:not(.mip-sel)") &&
    src.includes(".mip-card.mip-cf-blue:not(.mip-sel)"), true);
expect("new model kinds are pickable", src.includes("controlnet") && src.includes("text_encoders"), true);

console.log("\n[single-dismiss fix]");
expect("a pick closes the picker", src.includes("this.select(item.name, true)"), true);
expect("no keep-open click handler is left", src.includes("this.select(item.name, false)"), false);
expect("a duplicate menu during the async takeover is dropped",
    src.includes("takeoverPending"), true);
expect("...and the duplicate is closed, not stacked", src.includes("menu-duplicate-dropped"), true);
expect("native menus are cleared before the modal is shown",
    src.includes("closeNativeMenus"), true);
expect("the leftover native menu is removed from the DOM",
    src.includes(".litecontextmenu"), true);

console.log("\n[every picker kind has a working list endpoint]");
// The 2026-09-15 bug: /modelpreview/list only knew checkpoints/loras/vae, so
// opening the upscale dialog returned HTTP 400 and the modal showed an empty
// "no models" grid. Every kind the picker can open must answer 200.
const labelBlock = src.slice(src.indexOf("const LABEL = {"), src.indexOf("const MSG = {"));
const pickerKinds = [...labelBlock.matchAll(/^\s{4}([a-z_]+):/gm)].map((m) => m[1]);
expect("picker kinds found in source", pickerKinds.length, 10);
for (const kind of pickerKinds) {
    const res = await fetch(`/modelpreview/list?kind=${encodeURIComponent(kind)}`);
    expect(`HTTP 200 for ${kind}`, res.status, 200);
    if (res.ok) {
        const body = await res.json();
        expect(`  ${kind} reports a folder`, typeof body.folder === "string" && body.folder.length > 0, true);
        expect(`  ${kind} item count matches`, body.total, (body.items || []).length);
    }
}
const bad = await fetch("/modelpreview/list?kind=not_a_kind");
expect("an unknown kind is still a 400", bad.status, 400);
const up = await (await fetch("/modelpreview/list?kind=upscale_models")).json();
expect("the upscale dialog has models to show", up.total > 0, true);
expect("...and says so in its folder field", up.folder, "upscale_models");

console.log("\nFAILURES:", fail);
// Do not process.exit() here: force-quitting with undici's keep-alive sockets
// open trips a libuv teardown assertion on Windows.
process.exitCode = fail ? 1 : 0;
