// Handshake with the comfyui-mcp stdio server and list tools. Exit 1 if < 5 tools.
import { spawn } from "node:child_process";
const version = process.env.COMFYUI_MCP_VERSION || "latest";
const url = process.env.COMFYUI_URL || "http://localhost:8188";
if (Number(process.versions.node.split(".")[0]) < 22) { console.error(`Node >= 22 required (have ${process.versions.node})`); process.exit(1); }
const p = spawn("npx", ["-y", `comfyui-mcp@${version}`], {
  env: { ...process.env, COMFYUI_URL: url, COMFYUI_MCP_FORCE_REMOTE: "1" }, stdio: ["pipe", "pipe", "inherit"] });
let buf = "", id = 0; const pending = new Map();
const send = (method, params) => new Promise((res, rej) => { const i = ++id; pending.set(i, res);
  p.stdin.write(JSON.stringify({ jsonrpc: "2.0", id: i, method, params }) + "\n"); setTimeout(() => rej(new Error(`timeout: ${method}`)), 120000); });
p.stdout.on("data", d => { buf += d; let n; while ((n = buf.indexOf("\n")) >= 0) { const l = buf.slice(0, n); buf = buf.slice(n + 1);
  try { const m = JSON.parse(l); if (m.id && pending.has(m.id)) pending.get(m.id)(m); } catch {} } });
try {
  await send("initialize", { protocolVersion: "2024-11-05", capabilities: {}, clientInfo: { name: "mcp-doctor", version: "1" } });
  p.stdin.write(JSON.stringify({ jsonrpc: "2.0", method: "notifications/initialized" }) + "\n");
  const r = await send("tools/list", {});
  const tools = r.result?.tools ?? [];
  console.log(`comfyui-mcp@${version} -> ${url}: ${tools.length} tools`);
  for (const t of tools) console.log(" -", t.name);
  p.kill(); process.exit(tools.length >= 5 ? 0 : 1);
} catch (e) { console.error("mcp-doctor failed:", e.message); p.kill(); process.exit(1); }
