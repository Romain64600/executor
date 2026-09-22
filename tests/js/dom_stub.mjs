// Minimal DOM + browser stub, just wide enough to LOAD src/admin/static/*.js and drive its
// handlers. Not a browser: every method here exists because the console calls it.
// Written 2026-09-17 when Romain approved node as a TEST-ONLY dependency.

export function makeEl(tag = "div") {
  const listeners = {};
  const el = {
    tagName: String(tag).toUpperCase(),
    nodeType: 1,
    children: [],
    attrs: {},
    _text: "",
    value: "",
    disabled: false,
    // `el()` in the console sets `className` directly, while our selector matching reads
    // classList — keep the two the same object, or a ".go-in" lookup finds nothing.
    get className() { return [...el.classList._s].join(" "); },
    set className(v) { el.classList._s = new Set(String(v || "").split(/\s+/).filter(Boolean)); },
    checked: false,
    innerHTML: "",
    scrollTop: 0,
    scrollHeight: 0,
    style: { setProperty() {} },
    classList: {
      _s: new Set(),
      add(...c) { c.forEach((x) => this._s.add(x)); },
      remove(...c) { c.forEach((x) => this._s.delete(x)); },
      contains(c) { return this._s.has(c); },
      toggle(c, on) { if (on === undefined) on = !this._s.has(c); on ? this._s.add(c) : this._s.delete(c); },
    },
    get textContent() {
      return el._text || el.children.map((c) => (typeof c === "string" ? c : c.textContent || "")).join("");
    },
    set textContent(v) { el._text = String(v); el.children = []; },
    setAttribute(k, v) { el.attrs[k] = v; },
    getAttribute(k) { return el.attrs[k]; },
    addEventListener(kind, fn) { (listeners[kind] = listeners[kind] || []).push(fn); },
    fire(kind, ev) { return Promise.all((listeners[kind] || []).map((f) => f(ev || { target: el }))); },
    has(kind) { return !!(listeners[kind] || []).length; },
    append(...kids) { kids.forEach((k) => { if (k != null) el.children.push(k); }); },
    // `appendChild` manquait : renderGroups() l'appelle, l'exception partait dans le
    // try/catch de l'init et la console restait MUETTE — soit exactement la panne que
    // Romain a signalée. Un bouchon incomplet cache le défaut qu'il devrait montrer.
    appendChild(kid) { if (kid != null) el.children.push(kid); return kid; },
    replaceChildren(...kids) { el.children = []; el.append(...kids); },
    remove() {},
    focus() {},
    showModal() { el.open = true; },
    // A real <dialog> QUEUES its "close" event (HTML standard: the close steps queue an
    // element task). Firing it synchronously would hide exactly the defect Romain found —
    // an awaited continuation resumes between the gesture and the handler. So the stub
    // defers it too, and `close()` returns a promise the test can await.
    close() {
      el.open = false;
      return new Promise((r) => setImmediate(() => { el.fire("close"); r(); }));
    },
    // Échap: "cancel" is dispatched with the key event (synchronous), then the dialog closes
    // and its "close" event is queued like any other.
    pressEscape() { el.fire("cancel"); return el.close(); },
    querySelector(sel) { return find(el, sel)[0] || null; },
    querySelectorAll(sel) { return find(el, sel); },
    options: [],
  };
  return el;
}

// Only the selector shapes the console actually uses: ".class", "tag", "button,input".
function matches(node, sel) {
  return sel.split(",").map((s) => s.trim()).some((s) => {
    if (s.startsWith(".")) return node.classList.contains(s.slice(1));
    return node.tagName === s.toUpperCase();
  });
}

function find(root, sel, out = []) {
  for (const c of root.children || []) {
    if (typeof c === "string") continue;
    if (matches(c, sel)) out.push(c);
    find(c, sel, out);
  }
  return out;
}

/** Every element the page asks for by id, created on demand and remembered. */
export function makeDocument() {
  const byId = new Map();
  const doc = {
    documentElement: makeEl("html"),
    body: makeEl("body"),
    createElement: (t) => makeEl(t),
    createTextNode: (t) => String(t),
    querySelector(sel) {
      // Un id posé par le CODE (renderGroups crée ses boutons et leur donne un id) doit se
      // retrouver par `$("#launch-group-A")`, sinon le test regarde un élément fantôme et
      // ne voit jamais le bouton réel. On cherche donc d'abord dans l'arbre déjà construit,
      // puis on retombe sur la fabrique à la demande pour les ids de la page statique.
      if (sel.startsWith("#")) {
        const want = sel.slice(1);
        const seen = new Set();
        const walk = (n) => {
          for (const c of (n && n.children) || []) {
            if (typeof c === "string" || seen.has(c)) continue;
            seen.add(c);
            if (c.id === want) return c;
            const hit = walk(c);
            if (hit) return hit;
          }
          return null;
        };
        for (const racine of [doc.body, ...byId.values()]) {
          const hit = walk(racine);
          if (hit) return hit;
        }
      }
      if (!byId.has(sel)) byId.set(sel, makeEl("div"));
      return byId.get(sel);
    },
    _byId: byId,
  };
  return doc;
}

/** fetch() whose answers YOU release, so two loads can be interleaved on purpose. */
export function makeNetwork() {
  const pending = [];
  const calls = [];
  const fetch = (url, opts = {}) => {
    const call = { url, method: opts.method || "GET", body: opts.body ? JSON.parse(opts.body) : null };
    calls.push(call);
    return new Promise((resolve) => {
      pending.push({
        url,
        call,
        release(payload, ok = true) {
          // sort.js reads r.json(), auto.js reads r.text() then parses — serve both.
          resolve({
            ok, status: ok ? 200 : 500,
            json: async () => payload,
            text: async () => (payload === undefined ? "" : JSON.stringify(payload)),
          });
        },
      });
    });
  };
  return {
    fetch,
    calls,
    /** Release the OLDEST unanswered request whose URL contains `frag`. */
    async release(frag, payload, ok = true) {
      const i = pending.findIndex((p) => p.url.includes(frag));
      if (i < 0) throw new Error(`aucune requête en attente contenant ${frag}\nen attente: ${pending.map((p) => p.url).join(", ")}`);
      const [p] = pending.splice(i, 1);
      p.release(payload, ok);
      await tick();
      return p.call;
    },
    waiting: () => pending.map((p) => p.url),
  };
}

/** Let every already-resolved promise run its continuations. */
export async function tick(n = 12) {
  for (let i = 0; i < n; i++) await Promise.resolve();
  await new Promise((r) => setImmediate(r));
}

/** Every clickable element of a subtree whose text contains `txt`, in document order. */
export function byTextAll(root, txt) {
  const out = [];
  (function walk(n) {
    for (const c of n.children || []) {
      if (typeof c === "string") continue;
      if ((c.textContent || "").includes(txt) && c.has("click")) out.push(c);
      walk(c);
    }
  })(root);
  return out;
}

/** Walk a subtree for the first element whose text contains `txt`. */
export function byText(root, txt) {
  const out = [];
  (function walk(n) {
    for (const c of n.children || []) {
      if (typeof c === "string") continue;
      if ((c.textContent || "").includes(txt)) out.push(c);
      walk(c);
    }
  })(root);
  return out.find((e) => e.has("click")) || out[0] || null;
}
