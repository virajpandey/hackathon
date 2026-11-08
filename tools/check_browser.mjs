import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import {fileURLToPath} from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
fs.mkdirSync(path.join(root, "qa/screens"), {recursive: true});
const base = process.env.BLINDFOLD_URL || "http://127.0.0.1:8876";
const port = Number(fs.readFileSync(path.join(root, "qa/chrome/DevToolsActivePort"), "utf8").split("\n")[0]);
const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const target = targets.find(t => t.type === "page");
const socket = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
let next = 0;
const pending = new Map(), errors = [], external = new Set();
socket.onmessage = event => {
  const message = JSON.parse(event.data);
  if (message.id) {
    const task = pending.get(message.id);
    if (!task) return;
    pending.delete(message.id);
    clearTimeout(task.timeout);
    message.error ? task.reject(Error(JSON.stringify(message.error))) : task.resolve(message.result);
  } else if (message.method === "Runtime.exceptionThrown") {
    errors.push(message.params.exceptionDetails);
  } else if (message.method === "Network.requestWillBeSent") {
    const url = message.params.request.url;
    if (/^https?:/.test(url) && !url.startsWith(base + "/")) external.add(url);
  }
};
function cdp(method, params = {}) {
  return new Promise((resolve, reject) => {
    const id = ++next;
    const timeout = setTimeout(() => { pending.delete(id); reject(Error(`Timeout: ${method}`)); }, 20000);
    pending.set(id, {resolve, reject, timeout});
    socket.send(JSON.stringify({id, method, params}));
  });
}
async function evaluate(expression) {
  const result = await cdp("Runtime.evaluate", {expression, returnByValue: true, awaitPromise: true});
  if (result.exceptionDetails) throw Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
async function until(expression) {
  for (let attempt = 0; attempt < 160; attempt++) {
    if (await evaluate(expression)) return;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  throw Error(`Condition not met: ${expression}`);
}
async function open(route) {
  await cdp("Page.navigate", {url: base + route});
  await until(`location.href === ${JSON.stringify(base + route)} && document.readyState === "complete"`);
  await evaluate("document.fonts.ready.then(() => true)");
}
async function screenshot(name) {
  const result = await cdp("Page.captureScreenshot", {format: "png", captureBeyondViewport: false});
  fs.writeFileSync(path.join(root, "qa/screens", name + ".png"), Buffer.from(result.data, "base64"));
}
async function key(key) {
  await cdp("Input.dispatchKeyEvent", {type: "keyDown", key});
  await cdp("Input.dispatchKeyEvent", {type: "keyUp", key});
}
async function pdf(filename) {
  await cdp("Emulation.setEmulatedMedia", {media: "print"});
  const overlaps = await evaluate(`(() => [...document.querySelectorAll(".slide")].flatMap((slide, index) => {
    const limit = slide.querySelector("footer").getBoundingClientRect().top - 15;
    return [...slide.querySelectorAll(".content table, .content p, .content img")]
      .filter(e => e.getBoundingClientRect().bottom > limit)
      .map(e => "Printed slide " + (index + 1) + ": " + e.tagName);
  }))()`);
  assert.deepEqual(overlaps, [], "Printed footer overlap");
  const result = await cdp("Page.printToPDF", {
    printBackground: true, preferCSSPageSize: true,
    marginTop: 0, marginBottom: 0, marginLeft: 0, marginRight: 0,
  });
  fs.writeFileSync(path.join(root, "web", filename), Buffer.from(result.data, "base64"));
  await cdp("Emulation.setEmulatedMedia", {media: "screen", features: [{name: "prefers-reduced-motion", value: "reduce"}]});
}
await cdp("Page.enable");
await cdp("Runtime.enable");
await cdp("Network.enable");
await cdp("Emulation.setDeviceMetricsOverride", {width: 1600, height: 900, deviceScaleFactor: 1, mobile: false});
await cdp("Emulation.setEmulatedMedia", {features: [{name: "prefers-reduced-motion", value: "reduce"}]});
try {
  await open("/");
  await screenshot("desk");
  await open("/whiteboard.html");
  await pdf("whiteboard.pdf");
  await open("/assets/whiteboard.svg");
  await screenshot("whiteboard");
  await open("/slides.html");
  await until('document.body.dataset.ready === "true"');
  await evaluate('document.querySelector(".deck-controls").classList.add("hidden")');
  for (let slide = 1; slide <= 5; slide++) {
    await screenshot(`slide-${slide}`);
    const overflow = await evaluate(`(() => {
      const parent = document.querySelector(".slide.active"), p = parent.getBoundingClientRect();
      return [...parent.querySelectorAll("h1, td, img, .side, footer")].filter(e => {
        const r = e.getBoundingClientRect();
        return r.right > p.right + 1 || r.bottom > p.bottom + 1 || e.scrollWidth > e.clientWidth + 3;
      }).map(e => e.tagName + ": " + e.textContent.slice(0, 80));
    })()`);
    assert.deepEqual(overflow, [], `Slide ${slide} overflow`);
    const footerOverlap = await evaluate(`(() => {
      const parent = document.querySelector(".slide.active");
      const limit = parent.querySelector("footer").getBoundingClientRect().top - 15;
      return [...parent.querySelectorAll(".content table, .content p, .content img")]
        .filter(e => e.getBoundingClientRect().bottom > limit)
        .map(e => e.tagName + ": " + e.textContent.slice(0, 80));
    })()`);
    assert.deepEqual(footerOverlap, [], `Slide ${slide} footer overlap`);
    if (slide < 5) await key("ArrowRight");
  }
  await pdf("slides.pdf");
  await open("/demo.html");
  await until('!document.querySelector("#run").disabled && !document.querySelector("#replay").disabled');
  await screenshot("demo-ready");
  await evaluate('document.querySelector("#prompt").value = "patient reports knee"; document.querySelector("#run").click()');
  await until('!document.querySelector("#compare").disabled');
  assert.equal(await evaluate('document.querySelector("#mode").textContent.includes("Live run")'), true);
  await screenshot("demo-live");
  await evaluate('document.querySelector("#compare").click()');
  assert.equal(await evaluate('document.querySelector("#status").textContent.includes("Exact match")'), true);
  await screenshot("demo-compare");
  const servers = await evaluate('[...document.querySelectorAll("#liar option")].map(o => o.value)');
  assert.equal(servers.length, Number(process.env.BLINDFOLD_SERVERS || 3), "Server count on the page");
  for (const node of servers) {
    if (node !== servers[0]) {
      await evaluate('document.querySelector("#run").click()');
      await until('!document.querySelector("#compare").disabled');
    }
    await evaluate(`document.querySelector("#liar").value = ${JSON.stringify(node)}; document.querySelector("#tamper").click()`);
    await until('!document.querySelector("#run").disabled && document.querySelector("#outcome").textContent.includes("CHECK FAILED")');
    assert.equal(await evaluate(`document.querySelector("#head-${node}").classList.contains("altered")`), true);
    await screenshot("demo-tamper-" + node);
  }
  await evaluate('document.querySelector("#replay").click()');
  await until('!document.querySelector("#compare").disabled && document.querySelector("#mode").textContent.includes("Recorded evidence")');
  await screenshot("demo-recorded");
  await evaluate('document.querySelector("#tamper").click()');
  await until('document.querySelector("#mode").textContent.includes("Recorded tampering")');
  assert.equal(await evaluate('document.querySelector("#outcome").textContent.includes("CHECK FAILED")'), true);
  await evaluate('document.querySelector("#prompt").value = "w".repeat(120); document.querySelector("#run").click()');
  await until('!document.querySelector("#compare").disabled');
  await evaluate('document.querySelector("#compare").click()');
  assert.equal(await evaluate('document.querySelector("#sent").getBoundingClientRect().bottom < document.querySelector(".evidence-panel").getBoundingClientRect().top'), true, "Long prompt overlaps controls");
  assert.equal(await evaluate('document.querySelector("#evidence").getBoundingClientRect().bottom < document.querySelector(".demo-footer").getBoundingClientRect().top'), true, "Long comparison overlaps footer");
  await screenshot("demo-long-input");
  await evaluate(`window.fetch = async (url, options) => { if (url === "api/run") throw Error("Intentional QA disconnect"); return {}; }; document.querySelector("#run").click()`);
  await until('document.querySelector("#mode").textContent.includes("no replay substituted")');
  assert.equal(await evaluate('document.querySelector("#compare").disabled'), true);
  await screenshot("demo-failure");
  assert.deepEqual(errors, [], "Browser exceptions");
  assert.deepEqual([...external], [], "External page requests");
  console.log(`Browser checks passed: five slides, PDFs, live output, tampering at each of ${servers.length} servers, replay, explicit failure, no external requests.`);
} finally {
  socket.close();
}
