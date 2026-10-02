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

      // Quellcode (unverändert aus dem Open-Source-Repo) einmalig ins Worker-FS holen
      if (!srcLoaded) {
        for (const p of srcFiles) {
          const resp = await fetch(BASE + p);
          if (!resp.ok) throw new Error(`HTTP ${resp.status} für ${p}`);
          writeFS('/work/' + p, new Uint8Array(await resp.arrayBuffer()));
        }
        srcLoaded = true;
      }

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
  } catch (err) {
    self.postMessage({
      type: msg.cmd === 'init' ? 'init-error' : 'error',
      id: msg.id,
      message: String((err && err.message) || err),
    });
  }
};
