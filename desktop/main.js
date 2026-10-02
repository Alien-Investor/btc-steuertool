'use strict';
// BTC Steuertool Desktop — Hauptprozess.
// Lädt ausschließlich die gebündelte Web-Version (web/dist) über app://steuertool/ — kein Netz, keine Navigation, keine fremden Fenster.
// Im Flatpak nimmt zusätzlich das System das Netz weg (keine --share=network); diese Datei ist die zweite Schicht.
// Härtung 1:1 aus Alien Pass desktop/main.js (Audits run-6 bis run-8); Begründungen in DESKTOP-INVARIANTEN.md.
const {app,BrowserWindow,protocol,session,ipcMain,Menu,dialog,shell}=require('electron');
const path=require('path'); const fs=require('fs');
const {writeFull,writeAtomic}=require('./atomic.js');

const ORIGIN='app://steuertool';
const ENTRY=ORIGIN+'/index.html';
const WWW=path.join(__dirname,'www');
// .wasm muss application/wasm sein (WebAssembly.instantiateStreaming), .py/.csv/.json holt der Pyodide-Worker per fetch
const TYPES={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.mjs':'text/javascript; charset=utf-8',
  '.css':'text/css; charset=utf-8','.woff2':'font/woff2','.png':'image/png','.wasm':'application/wasm','.zip':'application/zip',
  '.whl':'application/zip','.json':'application/json','.py':'text/plain; charset=utf-8','.csv':'text/csv; charset=utf-8'};
// Ersetzt die nginx-CSP der Web-Version. connect-src 'self' statt 'none': Pyodide holt wasm, Stdlib und src/*.py per fetch vom eigenen Ursprung.
const CSP="default-src 'self'; script-src 'self' 'unsafe-inline' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "+
  "font-src 'self'; connect-src 'self'; worker-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; frame-src 'none'";
const SAVE_MAX=50*1024*1024;
const SAVE_NAME=/^[\w.-]{1,120}\.(txt|csv|zip)$/;
const SAVE_FILTER={txt:'Text',csv:'CSV',zip:'ZIP'};
// Links der Oberfläche, die im System-Browser aufgehen dürfen (OpenURI-Portal, kein Flatpak-Recht nötig). Exakter Vergleich, keine Präfixe.
const LINKS=new Set(['https://alien-investor.org/','https://alien-investor.org/en/',
  'https://alien-investor.org/steuertool-guide.html','https://alien-investor.org/en/steuertool-guide.html',
  'https://alien-investor.org/steuertool-rechtliches.html#datenschutz','https://alien-investor.org/en/steuertool-rechtliches.html#privacy',
  'https://github.com/Alien-Investor/btc-steuertool']);
const MAIL='kontakt@alien-investor.org', MAIL_MAX=8000;

// Fernsteuerung verweigern: die Fuses sperren nur --inspect (Node), nicht Chromiums DevTools-Protokoll
for(const s of ['remote-debugging-port','remote-debugging-pipe','remote-debugging-address','remote-allow-origins'])
  if(app.commandLine.hasSwitch(s)){ console.error('BTC Steuertool: --'+s+' wird nicht unterstützt.'); app.exit(1); process.exit(1); }

// Vor app.ready: Schema anmelden, Hintergrund-Netzdienste von Chromium aus, Namensauflösung ins Leere.
// supportFetchAPI: ohne hängt der Pyodide-Worker beim Start (fetch auf app:// scheitert) — gemessen 02.10.2026
protocol.registerSchemesAsPrivileged([{scheme:'app',privileges:{standard:true,secure:true,supportFetchAPI:true}}]);
for(const s of ['disable-background-networking','disable-component-update','disable-domain-reliability','no-pings','disable-breakpad'])
  app.commandLine.appendSwitch(s);
app.commandLine.appendSwitch('host-resolver-rules','MAP * ~NOTFOUND');
app.commandLine.appendSwitch('force-webrtc-ip-handling-policy','disable_non_proxied_udp');
app.enableSandbox();

// Ein mailto nur an die feste Adresse, nur mit subject/body (Bug-Report) — öffnet das Mailprogramm, gesendet wird dort vom Nutzer
// Kaputte %-Kodierung (decodeURIComponent wirft) und ein #-Fragment gelten als ungültig — nie eine Ausnahme im Hauptprozess.
function mailOk(u){
  if(u.length>MAIL_MAX) return false;
  try{
    const p=new URL(u);
    if(p.protocol!=='mailto:'||p.hash||decodeURIComponent(p.pathname).toLowerCase()!==MAIL) return false;
    for(const k of p.searchParams.keys()) if(k!=='subject'&&k!=='body') return false;
    return true;
  }catch(_){ return false; }
}
function linkOk(u){
  if(typeof u!=='string') return false;
  if(u.startsWith('mailto:')) return mailOk(u);
  try{ return LINKS.has(new URL(u).href); }catch(_){ return false; }
}
function openOutside(u){ if(linkOk(u)) shell.openExternal(u).catch(()=>{}); }

if(!app.requestSingleInstanceLock()){ app.quit(); }
else {
  let win=null;
  app.on('second-instance',()=>{ if(win){ if(win.isMinimized()) win.restore(); win.focus(); } });

  // Nur Dateien aus www/, nur bekannte Typen, kein Weg nach außen
  function serve(req){
    let p; try{ const u=new URL(req.url); if(u.host!=='steuertool') return new Response(null,{status:404}); p=decodeURIComponent(u.pathname); }
    catch(_){ return new Response(null,{status:400}); }
    if(p==='/') p='/index.html';
    const file=path.normalize(path.join(WWW,p));
    const type=TYPES[path.extname(file).toLowerCase()];
    if(!file.startsWith(WWW+path.sep)||!type) return new Response(null,{status:404});
    try{ return new Response(fs.readFileSync(file),{headers:{'content-type':type,'x-content-type-options':'nosniff','content-security-policy':CSP}}); }
    catch(_){ return new Response(null,{status:404}); }
  }

  // IPC nur vom obersten Frame der eigenen Seite. Nicht über u.origin prüfen: für eigene Schemata liefert URL dort immer "null".
  function fromApp(e){
    try{ const f=e.senderFrame; if(!f||f.parent) return false; const u=new URL(f.url);
      return u.protocol==='app:'&&u.host==='steuertool'&&u.pathname==='/index.html'; }
    catch(_){ return false; }
  }

  // Reports und Beispieldaten: Speichern-Dialog (im Flatpak über das Portal). null = abgebrochen.
  ipcMain.handle('file:save',async(e,name,data)=>{
    if(!fromApp(e)) throw new Error('denied');
    if(typeof name!=='string'||!SAVE_NAME.test(name)||!(data instanceof Uint8Array)||!data.length||data.length>SAVE_MAX) throw new Error('bad');
    const ext=name.split('.').pop();
    const r=await dialog.showSaveDialog(win,{defaultPath:name,filters:[{name:SAVE_FILTER[ext],extensions:[ext]}]});
    if(r.canceled||!r.filePath) return null;
    const buf=Buffer.from(data.buffer,data.byteOffset,data.byteLength);
    // Rückfall nur für ein NEUES Ziel (Portal ohne Schreibrecht neben der Datei): eine bestehende Datei nie direkt überschreiben
    try{ writeAtomic(r.filePath,buf); }
    catch(err){
      if(fs.existsSync(r.filePath)) throw err;
      const fd=fs.openSync(r.filePath,'wx',0o600);
      try{ writeFull(fd,buf); }catch(e2){ fs.closeSync(fd); try{ fs.unlinkSync(r.filePath); }catch(_){} throw e2; }
      fs.closeSync(fd);
    }
    return path.basename(r.filePath);
  });

  // Jede Webansicht: keine Navigation, keine neuen Fenster, keine <webview>. Bekannte Links gehen an den System-Browser.
  app.on('web-contents-created',(_e,wc)=>{
    wc.on('will-navigate',(ev,url)=>{ ev.preventDefault(); openOutside(url); });
    wc.on('will-redirect',ev=>ev.preventDefault());
    wc.on('will-attach-webview',ev=>ev.preventDefault());
    wc.setWindowOpenHandler(({url})=>{ openOutside(url); return {action:'deny'}; });
    wc.setWebRTCIPHandlingPolicy('disable_non_proxied_udp');
  });

  app.whenReady().then(async()=>{
    const ses=session.defaultSession;
    // Toter Proxy: die App braucht kein Netz (app:// läuft nicht über Proxys)
    await ses.setProxy({proxyRules:'http://127.0.0.1:9'});
    protocol.handle('app',serve);
    ses.setPermissionRequestHandler((_wc,_perm,cb)=>cb(false));
    ses.setPermissionCheckHandler(()=>false);
    ses.setSpellCheckerEnabled(false);   // lädt sonst Wörterbücher aus dem Netz
    ses.on('will-download',ev=>ev.preventDefault());   // Dateien entstehen nur über file:save, nie über Browser-Downloads
    ses.webRequest.onBeforeRequest((d,cb)=>{
      const u=d.url; cb({cancel:!(u.startsWith(ORIGIN+'/')||u.startsWith('blob:app://steuertool/')||u.startsWith('data:'))});
    });
    Menu.setApplicationMenu(null);

    // Fenster-Icon (_NET_WM_ICON) für Taskleiste/Alt+Tab; Zuordnung zur .desktop-Datei über StartupWMClass = package.json "name"
    const ICON=path.join(__dirname,'icon.png');
    win=new BrowserWindow({width:1200,height:900,minWidth:360,minHeight:520,backgroundColor:'#000000',title:'BTC Steuertool',show:false,
      ...(fs.existsSync(ICON)?{icon:ICON}:{}),
      webPreferences:{preload:path.join(__dirname,'preload.js'),sandbox:true,contextIsolation:true,nodeIntegration:false,webSecurity:true,
        devTools:false,spellcheck:false,webviewTag:false,navigateOnDragDrop:false,safeDialogs:true}});
    win.once('ready-to-show',()=>win.show());
    win.on('closed',()=>{ win=null; });
    win.loadURL(ENTRY);
  });

  app.on('window-all-closed',()=>app.quit());
}
