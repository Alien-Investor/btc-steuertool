'use strict';
// Prüfprogramm für die echte Hülle: lädt main.js wie die App und prüft von innen (keine Fernsteuerung von außen —
// die Hülle verweigert --remote-debugging-*, und die Fuses sperren --inspect). Aufruf über desktop/verify-desktop.mjs.
// Gibt je Prüfung eine Zeile "R <json>" aus. System-Browser und Speichern-Dialog werden hier durch Rekorder ersetzt.
const electron=require('electron');
const {app,BrowserWindow,Menu,session}=electron;
const path=require('path'); const fs=require('fs');

const STEP=process.env.ST_STEP, OUT=process.env.ST_OUT;
const opened=[]; electron.shell.openExternal=async u=>{ opened.push(u); };
let saveTo=null; electron.dialog.showSaveDialog=async()=>saveTo?{canceled:false,filePath:saveTo}:{canceled:true};
require('./main.js');

const R=(name,ok,info)=>console.log('R '+JSON.stringify({name,ok:!!ok,info:info===undefined?null:info}));
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
let win=null;
const js=code=>win.webContents.executeJavaScript(code,true);
async function until(code,ms=60000){ const t0=Date.now(); while(Date.now()-t0<ms){ try{ if(await js(code)) return true; }catch(_){} await sleep(100); } return false; }

async function fresh(){
  const t0=Date.now();
  R('lädt nur app://steuertool/index.html', win.webContents.getURL()==='app://steuertool/index.html', win.webContents.getURL());
  R('kein Node im Renderer', await js(`typeof require==='undefined'&&typeof process==='undefined'&&typeof module==='undefined'`));
  const keys=await js(`Object.keys(window.AlienDesktop).sort().join(',')`);
  R('Brücke hat genau saveFile', keys==='saveFile', keys);

  // Desktop-Weiche in der Oberfläche
  R('Privacy-Strip mit Desktop-Text', await js(`document.getElementById('privacy-strip').textContent.includes('Desktop-App ohne Netzzugriff')`));
  R('kein Server-Hinweis der Web-Version', await js(`!document.getElementById('privacy-strip').textContent.includes('vom Server')`));
  R('Knöpfe heißen „speichern“', await js(`document.getElementById('btn-download').textContent.includes('speichern')&&document.getElementById('btn-download-all').textContent.includes('speichern')`));
  R('Fenstertitel ohne „im Browser“', await js(`document.title==='BTC Steuertool — Bitcoin Steuerreport'`), await js('document.title'));
  R('Website-Leiste (Zentrale, BETA) ausgeblendet', await js(`document.getElementById('back-link').offsetParent===null&&getComputedStyle(document.querySelector('.top-nav')).display==='none'`));
  R('App-Kopf wie die anderen Apps: Sprache links, „?“ rechts', await js(`(()=>{const l=document.getElementById('app-lang').getBoundingClientRect(),h=document.getElementById('app-help').getBoundingClientRect(),g=document.getElementById('logo').getBoundingClientRect();return l.width>0&&h.width>0&&l.right<g.left+60&&h.left>g.right-60&&document.getElementById('app-lang').textContent==='DE';})()`));
  R('Darstellung im Fuß umschaltbar', await js(`(()=>{document.getElementById('th-soft').click();const a=document.documentElement.dataset.theme==='soft'&&document.getElementById('th-soft').classList.contains('on');document.getElementById('th-dark').click();return a&&!document.documentElement.dataset.theme;})()`));

  // Handbuch („?“) offline in der App; Links darin gehen nur über die feste Liste
  await js(`document.getElementById('app-help').click()`);
  R('Handbuch öffnet offline', await js(`!document.getElementById('help-overlay').classList.contains('hidden')&&document.getElementById('help-de').textContent.includes('Erkennung prüfen')`));
  { await sleep(1100); opened.length=0; await js(`document.querySelector('#help-de a[href^="https://"]').click()`); await sleep(300);
    R('Handbuch-Link extern über die Liste', opened.length===1&&opened[0]==='https://alien-investor.org/steuertool-guide.html'&&win.webContents.getURL()==='app://steuertool/index.html', opened.slice()); }
  { await sleep(1100); opened.length=0; await js(`document.querySelector('#help-de a[href^="mailto:"]').click()`); await sleep(300);
    R('Handbuch-mailto über die Liste', opened.length===1&&opened[0]==='mailto:kontakt@alien-investor.org', opened.slice()); }
  await js(`document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape'}))`);
  R('Escape schließt das Handbuch', await js(`document.getElementById('help-overlay').classList.contains('hidden')`));

  // Rechenkern: Startzeit bis „bereit“ (die Seite wärmt am Desktop nach 1,5 s selbst vor), Demo-Lauf, Reports
  await js(`document.getElementById('btn-demo').click()`);
  const filesIn=await until(`!document.getElementById('btn-run').disabled`,30000);
  R('Beispieldaten geladen', filesIn);
  const t1=Date.now(); await js(`document.getElementById('btn-run').click()`);
  const done=await until(`window.__GUI_DONE===true`,120000);
  R('Demo-Lauf fertig', done, {ab_start_ms:Date.now()-t0, lauf_ms:Date.now()-t1});
  if(done&&OUT){ fs.writeFileSync(path.join(OUT,'reports.json'),await js(`JSON.stringify(window.__GUI_RESULT.reports)`)); }
  const mem=app.getAppMetrics().reduce((a,m)=>a+m.memory.workingSetSize,0);
  R('Speicher gesamt (MB, Info)', true, Math.round(mem/1024));

  // Netz und Navigation
  R('fetch nach außen scheitert', await js(`fetch('https://example.org/').then(()=>false,()=>true)`));
  R('window.open verweigert', await js(`window.open('https://example.org/')===null`));
  await js(`location.href='https://example.org/'`).catch(()=>{}); await sleep(600);
  R('Navigation verweigert', win.webContents.getURL()==='app://steuertool/index.html', win.webContents.getURL());
  const ses=session.defaultSession;
  const st=async u=>{ try{ return (await ses.fetch(u)).status; }catch(e){ return 'FEHLER'; } };
  R('Protokoll liefert index.html', await st('app://steuertool/index.html')===200);
  const h=await ses.fetch('app://steuertool/vendor/pyodide/pyodide.asm.wasm');
  R('wasm als application/wasm', h.headers.get('content-type')==='application/wasm', h.headers.get('content-type'));
  const csp=(await ses.fetch('app://steuertool/index.html')).headers.get('content-security-policy')||'';
  R('CSP gesetzt (connect-src self, kein unsafe-eval)', /connect-src 'self'/.test(csp)&&!/'unsafe-eval'/.test(csp), csp);
  for(const u of ['app://steuertool/%2e%2e/main.js','app://steuertool/..%2fpackage.json','app://steuertool/vendor/../../main.js','app://anders/index.html','app://steuertool/worker.js.map'])
    { const c=await st(u); R('Protokoll verweigert '+u, c===404||c==='FEHLER', c); }
  R('Hauptprozess erreicht kein Netz (webRequest)', await st('https://example.org/')==='FEHLER');
  R('kein Anwendungsmenü', Menu.getApplicationMenu()===null);
  R('.desktop StartupWMClass = package.json name', (()=>{ try{ const d=fs.readFileSync(path.join(__dirname,'..','..','flatpak','org.alieninvestor.steuertool.desktop'),'utf8'); return /^StartupWMClass=btc-steuertool$/m.test(d); }catch(_){ return 'n/a'; } })());

  // Links: nur die feste Liste geht an den System-Browser, alles andere verpufft
  // openOutside lässt höchstens einen Link je Sekunde durch → vor jedem Versuch 1,1 s Abstand
  const tryOpen=async(u,how)=>{ await sleep(1100); opened.length=0;
    if(how==='open') await js(`window.open(${JSON.stringify(u)})`); else await js(`location.href=${JSON.stringify(u)}`).catch(()=>{});
    await sleep(300); return opened.slice(); };
  const ok=['https://github.com/Alien-Investor/btc-steuertool','https://alien-investor.org/en/steuertool-guide.html','https://alien-investor.org/steuertool-rechtliches.html#datenschutz'];
  for(const u of ok){ const o=await tryOpen(u,'open'); R('Link extern geöffnet: '+u, o.length===1&&o[0]===u, o); }
  const navOk=await tryOpen('https://alien-investor.org/steuertool-guide.html','nav');
  R('Link per Navigation extern, Seite bleibt', navOk.length===1&&win.webContents.getURL()==='app://steuertool/index.html', navOk);
  { const o=await tryOpen('HTTPS://ALIEN-INVESTOR.ORG:443/steuertool-guide.html','open');
    R('nicht-kanonische Schreibweise geht als kanonischer href hinaus', o.length===1&&o[0]==='https://alien-investor.org/steuertool-guide.html', o); }
  { await sleep(1100); opened.length=0; await js(`for(let i=0;i<20;i++) window.open('https://alien-investor.org/steuertool-guide.html')`); await sleep(400);
    R('Fensterflut gedrosselt (20 × window.open → 1)', opened.length===1, opened.length); }
  // Spenden-Blitz im Fuß (v1.1): Klick öffnet genau die Spendenseite der eingestellten Sprache im System-Browser
  { await sleep(1100); opened.length=0; await js(`document.getElementById('donate-link').click()`); await sleep(300);
    const want=await js(`document.getElementById('donate-link').href`);
    R('Spenden-Blitz extern geöffnet', opened.length===1&&opened[0]===want&&/^https:\/\/alien-investor\.org\/(en\/)?spenden\.html$/.test(want)&&win.webContents.getURL()==='app://steuertool/index.html', opened.slice()); }
  const onApp=()=>win.webContents.getURL()==='app://steuertool/index.html';
  for(const u of ['https://example.org/','https://alien-investor.org/anderes.html','https://github.com/Alien-Investor/btc-steuertool/evil','http://alien-investor.org/','https://alien-investor.org.evil.com/','file:///etc/passwd','javascript:alert(1)',
      'https://alien-investor.org/steuertool-guide.html?ref=x','https://alien-investor.org/steuertool-guide.html#x','https://user:pw@alien-investor.org/steuertool-guide.html',
      'https://alien-investor.org:8443/steuertool-guide.html','https://www.alien-investor.org/steuertool-guide.html','https://alien-investor.org/steuertool-guide.html/'])
    for(const how of (u.startsWith('javascript:')?['open']:['open','nav']))   // javascript: per location.href liefe im Renderer (alert blockiert)
      { const o=await tryOpen(u,how); R('Link verweigert ('+how+'): '+u, o.length===0&&onApp(), {o,url:win.webContents.getURL()}); }
  const mail='mailto:kontakt@alien-investor.org?subject=%5BBTC%20Steuertool%5D%20Bug&body=Version%3A%20BTC%20Steuertool%20Desktop';
  { const o=await tryOpen(mail,'nav'); R('Bug-Report-mailto erlaubt', o.length===1&&o[0]===mail, o); }
  for(const u of ['mailto:andere@example.org','mailto:kontakt@alien-investor.org?cc=x@example.org','mailto:kontakt@alien-investor.org,x@example.org','mailto:kontakt@alien-investor.org?body='+'a'.repeat(9000)])
    { const o=await tryOpen(u,'nav'); R('mailto verweigert: '+u.slice(0,70), o.length===0, o); }
  // Bug-Report: Menü mit Kästchen (Vorauswahl = erkannte Typen) + freies Feld, Senden öffnet das Mailprogramm, Text bleibt kopierbar
  await js(`openBugReport()`);
  R('Bug-Menü hat alle 12 Typen (seit v1.4 mit Wallet-Exporten)', await js(`document.querySelectorAll('#bug-menu input[type=checkbox]').length`)===12);
  const pre=await js(`bugPicked().join(',')`);
  // noKYC-Typen bewusst NICHT vorausgewählt (Klartext-Mail verriete sonst noKYC-Bestände, Audit run-1)
  R('Vorauswahl = erkannte KYC-Typen der Beispieldaten', pre.includes('btc21')&&pre.includes('bitbox')&&!pre.includes('fxcache')
    &&!pre.includes('bitbox_nokyc')&&!pre.includes('bisq')&&!pre.includes('manual_buys'), pre);
  await js(`document.getElementById('bug-pick-btn').click()`);
  R('Menü klappt auf', await js(`!document.getElementById('bug-menu').classList.contains('hidden')`));
  await js(`document.querySelectorAll('#bug-menu input').forEach(i=>{ if(i.checked) i.click(); }); document.querySelector('#bug-menu input[value=swissquote]').click()`);
  R('Auswahl im Knopf sichtbar', await js(`document.getElementById('bug-pick-text').textContent==='Swissquote'`), await js(`document.getElementById('bug-pick-text').textContent`));
  await js(`document.querySelector('#bug-title').click()`);
  R('Klick daneben schließt das Menü', await js(`document.getElementById('bug-menu').classList.contains('hidden')`));
  await js(`document.getElementById('bug-broker').value='Kraken'; document.getElementById('bug-desc').value='x'.repeat(9000)`);
  await sleep(1100); opened.length=0; await js(`sendBugReport()`); await sleep(400);
  R('Senden öffnet mailto trotz langem Text (gekürzt)', opened.length===1&&opened[0].startsWith('mailto:kontakt@alien-investor.org?subject=')&&decodeURIComponent(opened[0]).includes('Swissquote, Kraken'), opened.map(u=>u.length));
  R('voller Text bleibt zum Kopieren sichtbar', await js(`!document.getElementById('bug-sent').classList.contains('hidden')&&document.getElementById('bug-sent-body').value.length>9000`));
  await js(`closeBugReport()`);
  R('Bug-Report nennt Desktop', await js(`i18n.de.bugBody('x','y').startsWith('Version: BTC Steuertool Desktop')`));

  // Speichern: über die Brücke, nur gültige Namen, Abbruch = null, bestehende Datei wird ersetzt
  const dir=path.join(process.env.XDG_DATA_HOME,'save'); fs.mkdirSync(dir,{recursive:true});
  saveTo=null;
  R('Abbruch → null', await js(`DESK.saveFile('a.txt',new Uint8Array([65]))`)===null);
  saveTo=path.join(dir,'steuerreport_2024.txt'); fs.writeFileSync(saveTo,'ALT');
  const n=await js(`DESK.saveFile('steuerreport_2024.txt',new TextEncoder().encode(window.__GUI_RESULT.reports['steuerreport_2024.txt']))`);
  R('Report gespeichert, alte Datei ersetzt', n==='steuerreport_2024.txt'&&fs.readFileSync(saveTo,'utf8')===await js(`window.__GUI_RESULT.reports['steuerreport_2024.txt']`), n);
  R('keine Temp-Reste', fs.readdirSync(dir).every(x=>!x.includes('.tmp-')), fs.readdirSync(dir));
  for(const bad of ['../x.txt','x.exe','x','.txt','a/b.txt','x.txt.sh'])
    R('Name verweigert: '+bad, await js(`DESK.saveFile(${JSON.stringify(bad)},new Uint8Array([65])).then(()=>false,()=>true)`));
  R('leere Daten verweigert', await js(`DESK.saveFile('a.txt',new Uint8Array(0)).then(()=>false,()=>true)`));
  R('Text statt Bytes verweigert', await js(`DESK.saveFile('a.txt','hallo').then(()=>false,()=>true)`));
  // Knöpfe der Oberfläche: Alle Dateien (ZIP) und Beispieldaten-Link landen im Speichern-Dialog
  saveTo=path.join(dir,'alle.zip');
  await js(`document.getElementById('btn-download-all').click()`);
  let z=false; for(let i=0;i<50&&!z;i++){ await sleep(100); z=fs.existsSync(saveTo); }
  R('ZIP-Knopf speichert über den Dialog', z&&fs.readFileSync(saveTo).subarray(0,2).toString()==='PK', z?fs.statSync(saveTo).size:null);
  saveTo=path.join(dir,'beispiel.zip');
  await js(`document.querySelector('#dropzone a[download]').click()`);
  let b=false; for(let i=0;i<50&&!b;i++){ await sleep(100); b=fs.existsSync(saveTo); }
  R('Beispieldaten-Link speichert über den Dialog', b&&fs.readFileSync(saveTo).equals(fs.readFileSync(path.join(__dirname,'www','examples','beispieldaten.zip'))));
  R('Seite nach Klicks unverändert', win.webContents.getURL()==='app://steuertool/index.html');
}

app.whenReady().then(async()=>{
  let w=0; while(!(win=BrowserWindow.getAllWindows()[0])&&w++<100) await sleep(100);
  if(!win){ R('Fenster',false); app.exit(1); return; }
  if(win.webContents.isLoading()) await new Promise(r=>win.webContents.once('did-finish-load',r));
  try{
    if(STEP==='fresh') await fresh();
    else if(STEP==='hold'){ R('läuft',true); await sleep(Number(process.env.ST_HOLD||3000)); }
  }catch(e){ R('Ausnahme',false,String(e&&e.stack||e)); }
  app.exit(0);
});
