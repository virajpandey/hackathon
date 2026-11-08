const slides = [...document.querySelectorAll(".slide")];
const stage = document.querySelector("#stage");
const notes = document.querySelector("#notes");
const controls = document.querySelector(".deck-controls");
let index = Math.max(0, Math.min(slides.length - 1, Number(new URLSearchParams(location.search).get("slide") || 1) - 1));
function fit() {
  const k = Math.min(innerWidth / 1600, innerHeight / 900);
  stage.style.transform = `translate(${(innerWidth - 1600 * k) / 2}px, ${(innerHeight - 900 * k) / 2}px) scale(${k})`;
}
function show(i) {
  index = Math.max(0, Math.min(slides.length - 1, i));
  slides.forEach((slide, n) => slide.classList.toggle("active", n === index));
  notes.textContent = slides[index].dataset.note;
  document.querySelector("#position").textContent = `${index + 1} / ${slides.length}`;
}
document.querySelector("#prev").onclick = () => show(index - 1);
document.querySelector("#next").onclick = () => show(index + 1);
addEventListener("keydown", async e => {
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (["ArrowRight", " ", "PageDown"].includes(e.key)) { e.preventDefault(); show(index + 1); }
  if (["ArrowLeft", "PageUp"].includes(e.key)) { e.preventDefault(); show(index - 1); }
  if (e.key.toLowerCase() === "n") notes.hidden = !notes.hidden;
  if (e.key.toLowerCase() === "f") {
    controls.classList.toggle("hidden");
    try { document.fullscreenElement ? await document.exitFullscreen() : await document.documentElement.requestFullscreen(); } catch {}
  }
});
addEventListener("resize", fit);
fetch("data/numbers.json").then(r => {
  if (!r.ok) throw Error("Evidence unavailable");
  return r.json();
}).then(numbers => {
  document.querySelectorAll("[data-number]").forEach(el => {
    el.textContent = numbers[el.dataset.number].toLocaleString("en-US");
  });
  document.body.dataset.ready = "true";
}).catch(() => { document.body.dataset.ready = "error"; });
fit(); show(index);
