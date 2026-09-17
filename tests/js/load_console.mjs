// Loads a console script (src/admin/static/*.js) into a stubbed browser and hands back the
// document + the controllable network. The script is a classic script, not a module: wrapping
// it in a Function gives it its own scope with our globals injected.

import { readFileSync } from "node:fs";
import { makeDocument, makeNetwork, tick } from "./dom_stub.mjs";

export async function loadConsole(path) {
  const src = readFileSync(path, "utf8");
  const document = makeDocument();
  const net = makeNetwork();
  const globals = {
    document,
    fetch: net.fetch,
    localStorage: { getItem: () => null, setItem() {} },
    matchMedia: () => ({ matches: false }),
    setInterval: () => 1,
    clearInterval: () => {},
    setTimeout: () => 0,
    confirm: () => false,
    alert: () => {},
    navigator: { clipboard: { writeText() {} } },
  };
  const names = Object.keys(globals);
  // eslint-disable-next-line no-new-func
  const factory = new Function(...names, src);
  factory(...names.map((n) => globals[n]));
  await tick();
  return { document, net, $: (sel) => document.querySelector(sel) };
}
