// Packt die App in app.asar und legt die Electron-Fuses um — danach werden sie aus dem Binary zurückgelesen.
// Aufruf: node pack.mjs <app-ordner> <electron-ordner>
import {createPackage} from '@electron/asar';
import {flipFuses,getCurrentFuseWire,FuseVersion,FuseV1Options,FuseState} from '@electron/fuses';
import path from 'node:path';

const [appDir, elDir]=process.argv.slice(2);
if(!appDir||!elDir){ console.error('Aufruf: node pack.mjs <app-ordner> <electron-ordner>'); process.exit(2); }

await createPackage(appDir, path.join(elDir,'resources','app.asar'));

// Soll-Zustand wie Alien Pass (Begründung je Fuse in DESKTOP-INVARIANTEN.md):
const WANT={
  [FuseV1Options.RunAsNode]:false,                               // kein ELECTRON_RUN_AS_NODE
  [FuseV1Options.EnableCookieEncryption]:true,                   // schadet nicht (keine Cookies)
  [FuseV1Options.EnableNodeOptionsEnvironmentVariable]:false,    // kein NODE_OPTIONS
  [FuseV1Options.EnableNodeCliInspectArguments]:false,           // kein --inspect / SIGUSR1
  [FuseV1Options.EnableEmbeddedAsarIntegrityValidation]:true,    // unter Linux (noch) wirkungslos, zukunftssicher
  [FuseV1Options.OnlyLoadAppFromAsar]:true,                      // kein resources/app daneben
  [FuseV1Options.GrantFileProtocolExtraPrivileges]:false,        // App läuft über app://, nicht file://
  [FuseV1Options.WasmTrapHandlers]:true                          // an lassen: schnelle Bounds-Checks für WASM (Pyodide)
};
const bin=path.join(elDir,'electron');
await flipFuses(bin,{version:FuseVersion.V1,...WANT});

const wire=await getCurrentFuseWire(bin);
let bad=0;
for(const [k,v] of Object.entries(WANT)){
  const got=wire[k], want=v?FuseState.ENABLE:FuseState.DISABLE;
  if(got!==want){ console.error(`FEHLER: Fuse ${FuseV1Options[k]} ist ${got}, erwartet ${want}`); bad++; }
}
if(bad) process.exit(1);
console.log('app.asar gepackt, Fuses gesetzt und zurückgelesen: OK');
