'use strict';
/* Pyodide-Worker: hält den Rechenkern (Pyodide/WASM) in einem Hintergrund-Thread,
   damit der WASM-Compile und die FIFO-Berechnung den Main-Thread (UI) NICHT mehr blockieren.
   Geladen als gleich-origin Datei (kein blob:) — fällt unter `worker-src` auf `default-src 'self'`
   zurück, darum KEINE nginx/CSP-Änderung nötig. `wasm-unsafe-eval` aus script-src gilt auch hier.
   Netzzugriffe macht der Kern keine (Kurse sind gebündelt) — nur fetch() der eigenen src-Dateien. */

const BASE = self.location.href.replace(/[^/]*$/, '');   // Verzeichnis der App (z. B. .../steuertool/)
importScripts(BASE + 'vendor/pyodide/pyodide.js');

let pyodide = null;
let srcLoaded = false;

function writeFS(fullPath, bytes) {
  const dir = fullPath.substring(0, fullPath.lastIndexOf('/'));
  if (dir) pyodide.FS.mkdirTree(dir);
  pyodide.FS.writeFile(fullPath, bytes);
}

// Quellcode (unverändert aus dem Open-Source-Repo) einmalig ins Worker-FS holen
async function loadSrc(srcFiles) {
  if (srcLoaded) return;
  for (const p of srcFiles) {
    const resp = await fetch(BASE + p);
    if (!resp.ok) throw new Error(`HTTP ${resp.status} für ${p}`);
    writeFS('/work/' + p, new Uint8Array(await resp.arrayBuffer()));
  }
  srcLoaded = true;
}

async function init() {
  pyodide = await loadPyodide({ indexURL: BASE + 'vendor/pyodide/' });
  // tzdata: Zeitzonen-Datenbank für Europe/Berlin im Steuernachweis. pandas wird seit 10/2026
  // nicht mehr geladen — der Kern importiert es nicht (nur Standardbibliothek), das spart
  // pandas + numpy (~den Großteil der Wheels) beim Start.
  await pyodide.loadPackage(['tzdata']);
  await pyodide.runPythonAsync('import zoneinfo');
}

self.onmessage = async (e) => {
  const msg = e.data || {};
  try {
    if (msg.cmd === 'init') {
      await init();
      self.postMessage({ type: 'ready' });
      return;
    }
    if (msg.cmd === 'run') {
      const { srcFiles, bootstrap, fxCache, dataFiles } = msg.payload;
      await loadSrc(srcFiles);

      // Datenverzeichnis frisch aufsetzen. Kein ignore_errors mehr (H7): scheiterte
      // das Löschen teilweise, blieben Dateien des vorherigen Laufs liegen, und
      // das glob("*") des nächsten Laufs hätte sie in die Ergebnisse und ins ZIP
      // übernommen. Lieber laut scheitern als stillschweigend Fremddaten mischen.
      pyodide.runPython(
        'import os, shutil\n' +
        'if os.path.isdir("/work/data"): shutil.rmtree("/work/data")\n' +
        'assert not os.path.exists("/work/data"), "/work/data liess sich nicht leeren"\n'
      );
      pyodide.FS.mkdirTree('/work/data');
      writeFS('/work/data/fx_cache.json', new TextEncoder().encode(JSON.stringify(fxCache, null, 2)));
      for (const f of dataFiles) writeFS(f.target, f.bytes);

      const result = JSON.parse(pyodide.runPython(bootstrap));
      self.postMessage({ type: 'result', id: msg.id, result });   // Lauf-ID zurück: die GUI nimmt nur die passende Antwort an
      return;
    }
    if (msg.cmd === 'diagnose') {
      // Diagnose für den Bug-Report: Schwärzung in Python (src/diagnose.py), Eingabe nur als JSON-Daten
      // über globals — nie in den Code-String eingesetzt
      await loadSrc(msg.payload.srcFiles);
      pyodide.globals.set('diag_info', JSON.stringify(msg.payload.info));
      const text = pyodide.runPython(
        'import sys, json\n' +
        'if "/work" not in sys.path: sys.path.insert(0, "/work")\n' +
        'from src.diagnose import build\n' +
        'build(json.loads(diag_info))\n'
      );
      self.postMessage({ type: 'result', id: msg.id, result: { text } });
      return;
    }
  } catch (err) {
    // Python-Fehler kommen als voller Traceback (Pyodide-Interna, Pfade) — dem Nutzer nur die
    // Meldung selbst zeigen: ab der letzten Zeile „XyzError: …“ (Audit v1.4, R2-H1b)
    // Robust (Audit v1.4, R3-B7): letzte Zeile ohne Einrückung, die wie „Typ: Meldung“ oder nur „Typ“
    // aussieht; ValueError/RuntimeError ohne Typname, sonst mit. Kein Treffer → fester Text statt Traceback.
    // (Python-Abbrüche der Berechnung kommen seit R3 als Daten aus dem Bootstrap, nicht hierher.)
    let text = String((err && err.message) || err);
    if (/Traceback \(most recent call last\)/.test(text)) {
      const lines = text.split('\n');
      let found = null;
      for (let i = lines.length - 1; i >= 0; i--) {
        const m = /^([A-Za-z_][\w.]*)(?::\s?(.*))?$/.exec(lines[i]);
        if (m && !/^\s/.test(lines[i]) && !/^(Traceback|During|The above)/.test(lines[i])) {
          const rest = [m[2] || ''].concat(lines.slice(i + 1)).join('\n').trim();
          const name = m[1].split('.').pop();
          found = ['ValueError', 'RuntimeError'].includes(name) && rest ? rest : (rest ? `${name}: ${rest}` : name);
          break;
        }
      }
      text = found || 'Interner Fehler im Rechenkern';
    }
    self.postMessage({
      type: msg.cmd === 'init' ? 'init-error' : 'error',
      id: msg.id,
      message: text,
    });
  }
};
