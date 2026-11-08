const $ = s => document.querySelector(s);
const nodes = ["A", "B", "C"];
let live = false, busy = false, current = null, recording = null, serial = 0;
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const esc = s => String(s ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
function fit() {
  const k = Math.min(innerWidth / 1600, innerHeight / 900);
  $("#stage").style.transform = `translate(${(innerWidth - 1600 * k) / 2}px, ${(innerHeight - 900 * k) / 2}px) scale(${k})`;
}
function buttons() {
  $("#run").disabled = busy || !live;
  $("#replay").disabled = busy || !recording;
  $("#compare").disabled = busy || !current || current.caught;
  $("#tamper").disabled = busy || !current || current.caught;
  $("#prompt").disabled = busy;
  $("#liar").disabled = busy || current?.mode === "recorded";
}
function reset() {
  $("#shares").innerHTML = Array.from({length: 4}, () => `<tr>${nodes.map(() => "<td>—</td>").join("")}</tr>`).join("");
  nodes.forEach(n => $("#head-" + n).classList.remove("altered"));
  $("#outcome").textContent = "";
}
function locations(data) {
  nodes.forEach(n => {
    $("#head-" + n).innerHTML = `Worker ${n}<small>${esc(data.nodes[n])}</small>`;
  });
}
function view(step) {
  if (!step) return;
  $("#shares").innerHTML = Array.from({length: 4}, (_, i) => `<tr>${nodes.map(n => `<td>${esc(step.view.node_shares[n][i])}</td>`).join("")}</tr>`).join("");
  $("#sent").textContent = "Masked input sent: " + step.view.device_sends.slice(0, 2).join("  ");
}
function note(prompt, text) {
  $("#note").innerHTML = `<span class="prompt">${esc(prompt)}</span>${esc(text.slice(prompt.length).trimEnd())}`;
  let size = 42;
  $("#note").style.fontSize = `${size}px`;
  while ($("#note").scrollHeight > 170 && size > 22) $("#note").style.fontSize = `${size -= 2}px`;
}
function compare() {
  if (!current || current.caught || busy) return;
  const match = current.bit_exact;
  $("#evidence").innerHTML = `<table><thead><tr><th>Computed by</th><th>Output</th></tr></thead><tbody>
    <tr><td>Normal integer model</td><td class="text">${esc(current.normal_text.trim())}</td></tr>
    <tr><td>Three workers on shares</td><td class="text">${esc(current.private_text.trim())}</td></tr>
    </tbody></table>`;
  const height = $(".demo-footer").getBoundingClientRect().top - $("#evidence").getBoundingClientRect().top - 14;
  let size = 25;
  while ($("#evidence").getBoundingClientRect().height > height && size > 14) {
    size--;
    $("#evidence").querySelectorAll(".text").forEach(el => { el.style.fontSize = `${size}px`; });
    $("#evidence").querySelectorAll("td").forEach(el => { el.style.paddingBlock = "4px"; });
  }
  $("#status").textContent = match ? "Bit-exact: every output logit matched the reference." : "Mismatch: the private result did not match the reference.";
  $("#status").classList.toggle("alarm", !match);
}
async function request(prompt, lie = null) {
  const response = await fetch("api/run", {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({prompt, lie}),
  });
  const data = await response.json();
  if (!response.ok) throw Error(data.error || "The live engine failed");
  return data;
}
async function display(data) {
  current = data;
  locations(data);
  $("#mode").textContent = data.mode === "recorded"
    ? `Recorded evidence · ${recording.recorded_at}\nNot a live computation`
    : "Fresh computation · three workers\nAnimated playback of the computed trace";
  $("#mode").classList.toggle("alarm", data.mode === "recorded");
  const ticket = ++serial;
  note(data.prompt, data.prompt);
  $("#evidence").innerHTML = '<p class="serif">The workers compute on pieces. Only your device reconstructs the answer.</p>';
  const animate = !matchMedia("(prefers-reduced-motion: reduce)").matches;
  let text = data.prompt;
  for (const step of data.steps) {
    if (ticket !== serial) return;
    text += step.char;
    note(data.prompt, text);
    view(step);
    if (animate) await pause(20);
  }
  note(data.prompt, data.private_text);
  $("#status").textContent = `${data.steps.length} characters accepted · ${data.client_exchange_phases} client exchange phases`;
  $("#evidence").innerHTML = `<p class="serif">${data.bit_exact ? "Same answer. Every output logit matched." : "Output mismatch."}</p>`;
}
async function run(recorded = false) {
  if (busy) return;
  busy = true; buttons(); reset();
  note($("#prompt").value, $("#prompt").value);
  $("#status").classList.remove("alarm");
  $("#status").textContent = recorded ? "Loading recorded evidence" : "Computing on three workers…";
  $("#mode").textContent = recorded ? "Recorded evidence" : "Live computation in progress";
  try {
    const data = recorded ? recording.honest : await request($("#prompt").value);
    if (recorded) { data.mode = "recorded"; $("#prompt").value = data.prompt; $("#liar").value = recording.tampered.attack_node; }
    await display(data);
  } catch (error) {
    current = null;
    $("#mode").textContent = "Live run failed · no replay substituted";
    $("#status").textContent = error.message;
    $("#status").classList.add("alarm");
    $("#evidence").textContent = "Retry the live run, or explicitly choose Play recorded.";
  } finally { busy = false; buttons(); }
}
async function tamper() {
  if (!current || current.caught || busy) return;
  busy = true; buttons();
  const source = current.mode;
  $("#status").textContent = source === "recorded" ? "Loading recorded tampering result" : "Rerunning with a real injected change…";
  try {
    const data = source === "recorded" ? {...recording.tampered, mode: "recorded"} : await request(current.prompt, $("#liar").value);
    current = data;
    reset(); locations(data);
    if (data.rejected_view) view({view: data.rejected_view});
    note(data.prompt, data.private_text);
    $("#head-" + data.attack_node).classList.add("altered");
    $("#outcome").textContent = data.caught ? "CHECK FAILED / output rejected" : "CHECK DID NOT REJECT THE CHANGE";
    $("#evidence").innerHTML = `<p class="stop">${data.caught ? "Stopped before accepting the altered character." : "The altered result was not rejected."}</p>
      <p>Injected at worker ${esc(data.attack_node)} · ${data.steps.length} characters accepted in this run</p>`;
    $("#sent").textContent = "New run with fresh helpers. A worker changes one intermediate value without a matching tag.";
    $("#status").textContent = data.caught ? "The check detects tampering, not the identity of the worker." : "Unexpected result — inspect the protocol.";
    $("#mode").textContent = source === "recorded" ? "Recorded tampering result\nNot a live computation" : "Fresh tampering run\nReal worker arithmetic + real tag check";
  } catch (error) {
    $("#status").textContent = error.message;
    $("#status").classList.add("alarm");
  } finally { busy = false; buttons(); }
}
$("#form").onsubmit = e => { e.preventDefault(); run(); };
$("#replay").onclick = () => run(true);
$("#compare").onclick = compare;
$("#tamper").onclick = tamper;
addEventListener("keydown", async e => {
  if (e.ctrlKey || e.metaKey || e.altKey || ["INPUT", "SELECT", "BUTTON"].includes(e.target.tagName)) return;
  if (e.key === "Enter") { e.preventDefault(); if (live) run(); }
  if (e.key.toLowerCase() === "c") compare();
  if (e.key.toLowerCase() === "l") tamper();
  if (e.key.toLowerCase() === "f") {
    $(".deck-controls").classList.toggle("hidden");
    try { document.fullscreenElement ? await document.exitFullscreen() : await document.documentElement.requestFullscreen(); } catch {}
  }
});
fetch("api/status").then(r => r.ok ? r.json() : null).then(data => {
  live = !!data?.live;
  if (data) locations(data);
  if (!current && !busy) {
    $("#mode").textContent = live ? "Live engine ready\nNo computation run yet" : "Recorded evidence only";
    $("#status").textContent = live ? "Ready · three workers connected" : "Start python3 run.py for live computation";
  }
  buttons();
}).catch(() => { $("#mode").textContent = "Recorded evidence only"; $("#status").textContent = "Start python3 run.py for live computation"; buttons(); });
fetch("data/recording.json").then(r => r.ok ? r.json() : null).then(data => { recording = data; buttons(); }).catch(() => {});
addEventListener("resize", fit);
fit(); reset(); buttons();
