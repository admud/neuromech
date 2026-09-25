// Minimal CDP driver for headless Chrome (no deps; Node 24 global WebSocket).
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
/** Repo root (forward slashes), from this file's location. */
export const REPO = resolve(dirname(fileURLToPath(import.meta.url)), "..").split("\\").join("/");
export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

export async function openPage(url, port, { w = 1400, h = 800 } = {}) {
  const chrome = spawn("C:/Program Files/Google/Chrome/Application/chrome.exe", [
    "--headless=new", `--remote-debugging-port=${port}`, `--user-data-dir=${process.env.TEMP}\\nmtest\\prof-${port}`,
    "--no-first-run", `--window-size=${w},${h}`, "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding", "--disable-backgrounding-occluded-windows", "--enable-gpu",
    "--ignore-gpu-blocklist", "about:blank"], { stdio: "ignore" });
  let t;
  for (let i = 0; i < 60; i++) { try { t = await (await fetch(`http://127.0.0.1:${port}/json`)).json(); break; } catch { await sleep(250); } }
  const ws = new WebSocket(t.find((x) => x.type === "page").webSocketDebuggerUrl);
  await new Promise((r) => (ws.onopen = r));
  let id = 0; const pend = new Map(); const errors = [];
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pend.has(m.id)) { pend.get(m.id)(m); pend.delete(m.id); }
    if (m.method === "Runtime.exceptionThrown") errors.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
    if (m.method === "Runtime.consoleAPICalled" && m.params.type === "error") errors.push(m.params.args.map((a) => a.value ?? a.description).join(" "));
  };
  const send = (method, params = {}) => new Promise((r) => { const i = ++id; pend.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  const ev = async (expr) => {
    const r = await send("Runtime.evaluate", { expression: expr, awaitPromise: true, returnByValue: true });
    if (r.result?.exceptionDetails) throw new Error("eval: " + JSON.stringify(r.result.exceptionDetails.exception?.description || r.result.exceptionDetails.text));
    return r.result?.result?.value;
  };
  await send("Runtime.enable"); await send("Page.enable");
  await send("Page.navigate", { url });
  const key = async (k, code, vk, type = "both") => {
    if (type !== "up") await send("Input.dispatchKeyEvent", { type: "keyDown", key: k, code, windowsVirtualKeyCode: vk });
    if (type !== "down") await send("Input.dispatchKeyEvent", { type: "keyUp", key: k, code, windowsVirtualKeyCode: vk });
  };
  const shot = async (path) => { const r = await send("Page.captureScreenshot", { format: "png" }); (await import("node:fs")).writeFileSync(path, Buffer.from(r.result.data, "base64")); };
  const close = () => { try { ws.close(); } catch {} chrome.kill(); };
  return { send, ev, key, shot, close, errors, chrome };
}

export async function hubWatcher(hub) {
  const w = { state: null, config: null, ws: new WebSocket(`ws://${hub}/ws/dashboard`) };
  w.ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.type === "state") w.state = m; if (m.type === "config") w.config = m; };
  await new Promise((r) => (w.ws.onopen = r));
  w.send = (o) => w.ws.send(JSON.stringify(o));
  w.waitFor = async (pred, timeoutMs) => { const t0 = Date.now(); while (Date.now() - t0 < timeoutMs) { if (w.state && pred(w.state)) return (Date.now() - t0) / 1000; await sleep(50); } return null; };
  return w;
}
