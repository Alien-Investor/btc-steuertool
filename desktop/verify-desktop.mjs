// verify-desktop.mjs — prüft die ECHTE Desktop-Hülle (main.js + preload.js) mit dem gepinnten Electron.
// Läuft außerhalb des Flatpaks mit --no-sandbox (die Chromium-Sandbox braucht hier den Flatpak-Käfig); geprüft wird die Hülle,
// nicht der Käfig — Netz/Dateisystem des Käfigs prüft die Endkontrolle von build-desktop.sh.
// Das Prüfprogramm test/harness.cjs läuft IN der Hülle (keine Fernsteuerung). Reports müssen byte-gleich zur CLI sein.
// Voraussetzung: einmal build-desktop.sh (lädt das Electron-Archiv in den Cache).    Aufruf: node desktop/verify-desktop.mjs
import { spawn, execFileSync } from 'node:child_process';
import { mkdirSync, rmSync, cpSync, writeFileSync, existsSync, readFileSync, readdirSync } from 'node:fs';
import path from 'node:path';
const D=path.dirname(new URL(import.meta.url).pathname), ROOT=path.dirname(D), B=path.join(D,'build');
const EL_VER=readFileSync(path.join(D,'build-desktop.sh'),'utf8').match(/^EL_VER="([^"]+)"/m)[1];
const ZIP=path.join(process.env.HOME,'.cache/btc-steuertool-desktop',`electron-v${EL_VER}-linux-x64.zip`);
const EL_DIR=path.join(B,'test-electron'), APP=path.join(B,'test-app'), EL=path.join(EL_DIR,'electron');
const TMP=path.join(B,'test-home'), REF=path.join(B,'test-ref');
let ok=0, bad=0; const t=(c,m,info)=>{ if(c){ ok++; console.log('  ✓',m,info!==undefined&&info!==null?JSON.stringify(info):''); } else { bad++; console.log('  ✗',m,info!==undefined&&info!==null?JSON.stringify(info):''); } };
if(!existsSync(ZIP)){ console.error('FEHLER: '+ZIP+' fehlt — erst desktop/build-desktop.sh'); process.exit(2); }

// Aufbau: web/dist frisch, unveränderte Hülle + Prüfprogramm, Electron aus dem gepinnten Archiv (ohne Fuses — sonst kein fremder Einstieg)
execFileSync(path.join(ROOT,'web','build.sh'),{stdio:'ignore'});
const elVer=()=>{ try{ return readFileSync(path.join(EL_DIR,'version'),'utf8').trim(); }catch(_){ return ''; } };
if(!existsSync(EL)||elVer()!==EL_VER){ rmSync(EL_DIR,{recursive:true,force:true}); mkdirSync(EL_DIR,{recursive:true}); execFileSync('unzip',['-q',ZIP,'-d',EL_DIR]); }
if(elVer()!==EL_VER){ console.error('FEHLER: entpackte Engine ist '+elVer()+', erwartet '+EL_VER); process.exit(2); }
rmSync(APP,{recursive:true,force:true}); mkdirSync(APP,{recursive:true});
for(const f of ['main.js','preload.js','atomic.js','icon.png']) cpSync(path.join(D,f),path.join(APP,f));
cpSync(path.join(D,'test','harness.cjs'),path.join(APP,'harness.cjs')); cpSync(path.join(ROOT,'web','dist'),path.join(APP,'www'),{recursive:true});
writeFileSync(path.join(APP,'package.json'),JSON.stringify({name:'btc-steuertool',productName:'BTC Steuertool',version:'0.0.0-test',main:'harness.cjs',private:true}));
rmSync(TMP,{recursive:true,force:true}); mkdirSync(TMP,{recursive:true});
const ENV={...process.env, XDG_DATA_HOME:path.join(TMP,'data'), XDG_CONFIG_HOME:path.join(TMP,'config'), ST_OUT:TMP};

// CLI-Referenz: dieselben Beispieldaten, --all --nachweis --csv
rmSync(REF,{recursive:true,force:true}); cpSync(path.join(ROOT,'examples'),path.join(REF,'examples'),{recursive:true});
rmSync(path.join(REF,'examples','reports'),{recursive:true,force:true});
execFileSync('python3',[path.join(ROOT,'src','main.py'),'--all','--nachweis','--csv','--data-dir',path.join(REF,'examples')],{stdio:'ignore'});

function run(step,extra=[],opts={}){ return new Promise(res=>{
  const t0=Date.now(); const args=['--no-sandbox',...extra,APP], env={...ENV,ST_STEP:step,...(opts.env||{})};
  const pr=spawn(EL,args,{env});
  let out='', err=''; pr.stdout.on('data',d=>out+=d); pr.stderr.on('data',d=>err+=d);
  const kill=setTimeout(()=>pr.kill('SIGKILL'),opts.timeout||180000);
  pr.on('exit',(code,sig)=>{ if(sig) err+='\nSIGNAL '+sig; clearTimeout(kill); const rs=out.split('\n').filter(l=>l.startsWith('R ')).map(l=>JSON.parse(l.slice(2))); res({code,rs,ms:Date.now()-t0,err}); });
}); }
const report=r=>{ if(!r.rs.length) t(false,'keine Ergebnisse (Exit '+r.code+')',r.err.split('\n').filter(l=>/error|Error|FATAL|SIGNAL/.test(l)).slice(0,5)); r.rs.forEach(x=>t(x.ok,x.name,x.info)); };

console.log('[1] Härtung, Weiche, Rechenkern, Links, Speichern'); report(await run('fresh'));
console.log('[2] Reports byte-gleich zur CLI (--all --nachweis --csv)');
{ const f=path.join(TMP,'reports.json');
  if(!existsSync(f)) t(false,'keine Reports aus [1]');
  else { const rep=JSON.parse(readFileSync(f,'utf8')), refDir=path.join(REF,'examples','reports');
    const n=s=>s.replace(/\r\n/g,'\n').replace(/\n+$/,'');
    const refs=readdirSync(refDir);
    t(refs.length>0&&refs.every(x=>x in rep),'alle '+refs.length+' CLI-Reports vorhanden',refs.filter(x=>!(x in rep)));
    t(Object.keys(rep).every(x=>refs.includes(x)),'keine zusätzlichen Reports',Object.keys(rep).filter(x=>!refs.includes(x)));
    const diff=refs.filter(x=>x in rep&&n(readFileSync(path.join(refDir,x),'utf8'))!==n(rep[x]));
    t(diff.length===0,'Inhalte identisch',diff); } }
console.log('[3] Volle Platte (ulimit, atomic.js einzeln — Chromium selbst stürzt unter ulimit ab)');
{ const pr=await new Promise(res=>{ const c=spawn('bash',['-c','trap "" XFSZ; ulimit -f 64; exec node "$0" "$1"',path.join(D,'test','atomic-test.cjs'),path.join(TMP,'atomic')]);
    let out='', err=''; c.stdout.on('data',d=>out+=d); c.stderr.on('data',d=>err+=d); c.on('exit',(code,sig)=>res({code,rs:out.split('\n').filter(l=>l.startsWith('R ')).map(l=>JSON.parse(l.slice(2))),err:err+(sig?'\nSIGNAL '+sig:'')})); });
  report(pr); }
console.log('[4] Nur eine Instanz');
const first=run('hold',[],{env:{ST_HOLD:'9000'}}); await new Promise(r=>setTimeout(r,3500));
const second=await run('hold',[],{env:{ST_HOLD:'1000'},timeout:15000});
t(second.rs.length===0&&second.ms<8000,'zweite Instanz beendet sich sofort ohne Fenster',{ms:second.ms,rs:second.rs.length});
const f1=await first; t(f1.rs.some(x=>x.name==='läuft'),'erste Instanz lief weiter');
console.log('[5] Fernsteuerung verweigert');
for(const sw of ['--remote-debugging-port=9339','--remote-debugging-pipe']){
  const r=await run('hold',[sw],{timeout:15000}); t(r.code===1&&r.rs.length===0,sw+' → Abbruch mit Exit 1',{code:r.code,rs:r.rs.length}); }

console.log(`\n${ok} OK, ${bad} Fehler`);
process.exit(bad?1:0);
