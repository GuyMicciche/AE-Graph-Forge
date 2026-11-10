#!/usr/bin/env node
/*
 * ae_mock_check.js -- run a generated .jsx against a mock After Effects host,
 * then syntax-check AND evaluate every expression the script installed.
 *
 * This catches the class of bug that .js syntax checking cannot: an expression
 * is just a string at build time, so a typo in an effect name, a bad array
 * index or a malformed literal stays invisible until AE evaluates it. Here we
 * evaluate each one across the full 0..100 Progress sweep with the real
 * MASTER_CONTROLS values the script set, and flag anything that throws or
 * returns NaN.
 *
 *   node tools/ae_mock_check.js chart.jsx [chart2.jsx ...]
 */

const fs = require('fs');
const path = require('path');
const vm = require('vm');

// ---------------------------------------------------------------------------
// mock AE object model
// ---------------------------------------------------------------------------
function makeHost() {
  const installed = [];   // { path, expression }
  const effects = {};     // effect name -> { type, value }
  const layers = [];      // every layer the script created

  function Property(name, ownerPath) {
    this._name = name;
    this._path = ownerPath ? ownerPath + ' > ' + name : name;
    this._kids = {};        // lazily created named sub-properties
    this._children = [];    // properties added via addProperty(), index order
    this._value = null;
    this._expr = null;
    this._keys = [];
  }
  Property.prototype.property = function (k) {
    // 1-based index lookup into added children, which is how vgroup/vprop walk
    if (typeof k === 'number') return this._children[k - 1] || null;
    const key = String(k);
    for (let i = 0; i < this._children.length; i++) {
      if (this._children[i]._name === key) return this._children[i];
    }
    if (!this._kids[key]) {
      this._kids[key] = new Property(key, this._path);
      this._kids[key]._parent = this;
    }
    return this._kids[key];
  };
  Property.prototype.addProperty = function (matchName) {
    const p = new Property(matchName, this._path);
    p._parent = this;
    p._underEffects = (this._name === 'Effects');
    this._children.push(p);
    return p;
  };
  Object.defineProperty(Property.prototype, 'numProperties', {
    get() { return this._children.length; },
  });
  Object.defineProperty(Property.prototype, 'name', {
    get() { return this._name; },
    set(v) {
      this._path = this._path.replace(/[^>]*$/, v);
      this._name = v;
      if (this._underEffects) effects[v] = this;
    },
  });
  Property.prototype.setValue = function (v) { this._value = v; return v; };
  Property.prototype.setValueAtTime = function (t, v) { this._keys.push([t, v]); this._value = v; };
  Property.prototype.setTemporalEaseAtKey = function () {};
  Property.prototype.setInterpolationTypeAtKey = function () {};
  Property.prototype.valueAtTime = function () { return this._value; };
  Object.defineProperty(Property.prototype, 'expression', {
    set(v) { this._expr = v; installed.push({ path: this._path, expression: v, prop: this }); },
    get() { return this._expr; },
  });
  Object.defineProperty(Property.prototype, 'value', {
    get() { return this._value === null ? {} : this._value; },
    set(v) { this._value = v; },
  });

  function Layer(kind, name) {
    layers.push(this);
    this._kind = kind;
    this.name = name || kind;
    this.inPoint = 0;
    this.outPoint = 0;
    this._root = new Property('layer', '');
  }
  Layer.prototype.property = function (k) { return this._root.property(k); };

  const comp = {
    duration: 14,
    layers: {
      addSolid(color, name, w, h) { return new Layer('solid', name); },
      addText(str) {
        const l = new Layer('text', 'text');
        // Source Text .value must expose the TextDocument fields the script sets
        l.property('Source Text')._value = {
          fontSize: 0, fillColor: [1, 1, 1], font: '', justification: 0,
        };
        return l;
      },
      addNull() { return new Layer('null', 'Null'); },
      addShape() { return new Layer('shape', 'Shape Layer'); },
    },
    openInViewer() {},
  };

  const alerts = [];
  const sandbox = {
    app: {
      beginUndoGroup() {}, endUndoGroup() {},
      project: { items: { addComp(name, w, h, par, dur, fps) { comp.duration = dur; comp._name = name; return comp; } } },
    },
    Shape: function () { this.vertices = []; this.inTangents = []; this.outTangents = []; this.closed = false; },
    KeyframeEase: function (speed, influence) { this.speed = speed; this.influence = influence; },
    KeyframeInterpolationType: { LINEAR: 1, BEZIER: 2 },
    ParagraphJustification: { LEFT_JUSTIFY: 0, RIGHT_JUSTIFY: 1, CENTER_JUSTIFY: 2 },
    alert: (m) => alerts.push(m),
    Math, String, Number, Array, Object, JSON, parseInt, parseFloat, isNaN,
    console,
  };
  sandbox.global = sandbox;
  return { sandbox, installed, effects, alerts, comp, layers };
}

// ---------------------------------------------------------------------------
// mock expression evaluation context
// ---------------------------------------------------------------------------
function makeExprContext(effects, progress) {
  function effectAccessor(name) {
    const fx = effects[name];
    if (!fx) throw new Error(`no such effect on MASTER_CONTROLS: "${name}"`);
    return function (propName) {
      if (name === 'Progress' && propName === 'Slider') return progress;
      const p = fx._kids && fx._kids[propName];
      if (!p) throw new Error(`effect "${name}" has no property "${propName}"`);
      let v = p._value;
      if (v === null || v === undefined) v = 0;
      return v;
    };
  }
  const masterLayer = { effect: effectAccessor };
  return {
    thisComp: {
      layer(n) {
        if (n !== 'MASTER_CONTROLS') throw new Error(`unknown layer "${n}"`);
        return masterLayer;
      },
      width: 1920, height: 1080, duration: 14,
    },
    time: progress / 100 * 14,
    value: progress,
    createPath(points, inTangents, outTangents, closed) {
      if (!points.length || points.length !== inTangents.length || points.length !== outTangents.length)
        throw new Error('createPath: mismatched geometry');
      if (!points.every(p => p.every(Number.isFinite))) throw new Error('createPath: nonfinite vertex');
      if (![...inTangents,...outTangents].every(p => p.every(Number.isFinite))) throw new Error('createPath: nonfinite tangent');
      return { points, inTangents, outTangents, closed };
    },
    linear(t, tMin, tMax, v1, v2) {
      if (arguments.length === 3) { v1 = tMin; v2 = tMax; tMin = 0; tMax = 1; }
      if (tMax === tMin) return t < tMin ? v1 : v2;
      const u = Math.min(Math.max((t - tMin) / (tMax - tMin), 0), 1);
      if (Array.isArray(v1)) return v1.map((a, i) => a + (v2[i] - a) * u);
      return v1 + (v2 - v1) * u;
    },
    ease(t, tMin, tMax, v1, v2) {
      if (tMax === tMin) return t < tMin ? v1 : v2;
      let u = Math.min(Math.max((t - tMin) / (tMax - tMin), 0), 1);
      u = u * u * (3 - 2 * u);
      if (Array.isArray(v1)) return v1.map((a, i) => a + (v2[i] - a) * u);
      return v1 + (v2 - v1) * u;
    },
    Math, String, Number, Array, isNaN, parseInt, parseFloat,
  };
}

function finite(v) {
  if (typeof v === 'number') return Number.isFinite(v);
  if (Array.isArray(v)) return v.every(finite);
  if (typeof v === 'string') return true;
  return v !== undefined && v !== null;
}

// ---------------------------------------------------------------------------
// run one file
// ---------------------------------------------------------------------------
function check(file) {
  const src = fs.readFileSync(file, 'utf8').replace(/^\uFEFF/, '');
  const host = makeHost();
  const ctx = vm.createContext(host.sandbox);

  try {
    vm.runInContext(src, ctx, { filename: file, timeout: 20000 });
  } catch (e) {
    return { file, fatal: `script threw: ${e.message}` };
  }

  const problems = [];
  const sweep = [0, 0.5, 7, 23.7, 50, 76.3, 99.4, 100];

  // AE returns the COMPLETION VALUE of the last statement, with no explicit
  // `return`. vm.runInContext has exactly those semantics, so the expression
  // text is executed here the same way the AE engine executes it.
  host.installed.forEach(({ path: ppath, expression }) => {
    let script;
    try {
      script = new vm.Script(expression);
    } catch (e) {
      problems.push(`SYNTAX  ${ppath}: ${e.message}`);
      return;
    }
    for (const prog of sweep) {
      try {
        const exprCtx = vm.createContext(makeExprContext(host.effects, prog));
        const out = script.runInContext(exprCtx, { timeout: 3000 });
        if (!finite(out)) {
          problems.push(`VALUE   ${ppath} @${prog}%: returned ${JSON.stringify(out)}`);
          break;
        }
      } catch (e) {
        problems.push(`THROW   ${ppath} @${prog}%: ${e.message}`);
        break;
      }
    }
  });

  // Reveal invariant: at Progress 0 the graph must be empty, and at Progress
  // 100 fully drawn. Checked on the properties that actually gate visibility.
  // Only properties whose value actually depends on Progress. Gridline and
  // label opacity bind to their own controls and are meant to be visible at
  // Progress 0, so they are not reveal-gated and must not be flagged.
  const revealing = host.installed.filter(({ path: pp, expression }) =>
    (/Opacity$/.test(pp) || /Trim > End$/.test(pp) || /Scale$/.test(pp))
    && /\("Progress"\)\("Slider"\)|'Progress'\)\('Slider'\)/.test(expression));
  let atZero = 0;
  let atFull = 0;
  let checked = 0;
  for (const { path: pp, expression, prop } of revealing) {
    let script;
    try { script = new vm.Script(expression); } catch { continue; }
    const read = (prog) => {
      try {
        const v = script.runInContext(
          vm.createContext(makeExprContext(host.effects, prog)), { timeout: 3000 });
        // A bar's Scale is [100, g] or [g, 100], so the growing component is
        // the minimum. For scalar opacity min and max are the same value.
        return Array.isArray(v) ? Math.min(...v.map(x => Math.abs(Number(x)))) : Number(v);
      } catch { return NaN; }
    };
    // A Trim Paths End is "empty" when it equals its own Start, not when it
    // is zero: a wedge starting at 72% draws nothing while End is also 72%.
    let baseline = 0;
    if (/Trim > End$/.test(pp)) {
      // Use the property object itself, not a path lookup: every donut wedge
      // produces the same path string, so searching by path would compare a
      // wedge against the first wedge's Start.
      const start = prop && prop._parent ? prop._parent.property('Start') : null;
      if (start) {
        if (start._expr) {
          try {
            baseline = Number(new vm.Script(start._expr).runInContext(
              vm.createContext(makeExprContext(host.effects, 0)), { timeout: 3000 }));
          } catch { baseline = 0; }
        } else if (typeof start._value === 'number') {
          baseline = start._value;
        }
      }
      if (!Number.isFinite(baseline)) baseline = 0;
    }

    const lo = read(0);
    // The playhead and tip dot deliberately fade out over the last half
    // percent, so "visible by the end" is checked across the tail rather than
    // at exactly 100.
    const hi = Math.max(read(95), read(99), read(100));
    if (!Number.isFinite(lo) || !Number.isFinite(hi)) continue;
    checked++;
    if (lo - baseline > 0.01) {
      atZero++;
      if (problems.length < 40) {
        problems.push(`REVEAL  ${pp}: ${lo.toFixed(3)} at Progress 0, expected `
          + `${baseline.toFixed(3)}`);
      }
    }
    if (hi - baseline <= 0.01) {
      atFull++;
      if (problems.length < 40) {
        problems.push(`REVEAL  ${pp}: ${hi.toFixed(3)} at Progress 100, expected `
          + `above ${baseline.toFixed(3)}`);
      }
    }
  }

  // Shape layers built from precomputed comp-space vertices need an identity
  // transform, or the graph renders offset from the text and gridlines. Anchor
  // and Position must match on both the layer and its vector group.
  let placed = 0;
  for (const layer of host.layers) {
    if (layer._kind !== 'shape') continue;
    const contents = layer._root._kids['Contents'];
    if (!contents) continue;
    const group = contents._children.find((g) => /LineGroup|AreaGroup/.test(g._name));
    if (!group) continue;
    const tr = layer._root.property('Transform');
    const ap = tr.property('Anchor Point')._value;
    const pos = tr.property('Position')._value;
    const gt = group.property('Transform');
    const gap = gt.property('Anchor Point')._value;
    const gpos = gt.property('Position')._value;
    const same = (a, b) => Array.isArray(a) && Array.isArray(b)
      && Math.abs(a[0] - b[0]) < 1e-6 && Math.abs(a[1] - b[1]) < 1e-6;
    if (!same(ap, pos)) {
      problems.push(`ANCHOR  ${layer.name}: layer anchor ${JSON.stringify(ap)} `
        + `!= position ${JSON.stringify(pos)}`);
    } else if (!same(gap, gpos)) {
      problems.push(`ANCHOR  ${layer.name}: group anchor ${JSON.stringify(gap)} `
        + `!= position ${JSON.stringify(gpos)}`);
    } else {
      placed++;
    }
  }

  return {
    file,
    placed,
    exprCount: host.installed.length,
    effectNames: Object.keys(host.effects),
    alerts: host.alerts,
    reveal: { checked, atZero, atFull },
    problems,
  };
}

// ---------------------------------------------------------------------------
const files = process.argv.slice(2);
if (!files.length) {
  console.error('usage: node ae_mock_check.js <file.jsx> [...]');
  process.exit(2);
}
let bad = 0;
for (const f of files) {
  const r = check(f);
  const name = path.basename(f);
  if (r.fatal) {
    console.log(`FAIL ${name}\n     ${r.fatal}`);
    bad++;
    continue;
  }
  if (r.problems.length) {
    bad++;
    console.log(`FAIL ${name}  (${r.exprCount} expressions)`);
    r.problems.slice(0, 12).forEach((p) => console.log('     ' + p));
    if (r.problems.length > 12) console.log(`     ... +${r.problems.length - 12} more`);
  } else {
    console.log(`PASS ${name}  ${String(r.exprCount).padStart(4)} expressions, `
      + `${r.effectNames.length} controls, `
      + `reveal clean on ${r.reveal.checked} gating props, `
      + `${r.placed} path layers placed`);
  }
}
process.exit(bad ? 1 : 0);
