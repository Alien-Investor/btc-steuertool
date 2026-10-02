'use strict';
// BTC Steuertool Desktop — gespeicherte Reports vollständig und atomar schreiben (aus Alien Pass desktop/atomic.js).
// Nur fs, kein Electron: so lässt sich das Verhalten bei voller Platte einzeln prüfen (test/atomic-test.cjs unter ulimit).
const fs=require('fs'); const path=require('path'); const crypto=require('crypto');

// Vollständig schreiben: writeSync ist EIN write(2) und schreibt bei voller Platte nur einen Teil, ohne Fehler (Alien Pass Audit run-6 #2).
function writeFull(fd,data){
  const b=Buffer.isBuffer(data)?data:Buffer.from(data,'utf8'); let o=0;
  while(o<b.length){ const n=fs.writeSync(fd,b,o,b.length-o); if(!(n>0)) throw new Error('short write'); o+=n; }
  fs.fsyncSync(fd);
  if(fs.fstatSync(fd).size!==b.length) throw new Error('short write');
}
// Atomar schreiben: Temp-Datei daneben, vollständig schreiben + fsync, umbenennen, Ordner fsyncen — nie eine halbe Datei.
// Temp mit Zufallsnamen, exklusiv und ohne Symlink-Folgen (O_EXCL|O_NOFOLLOW, Audit run-1): ein vorbereiteter Symlink am
// Temp-Namen lenkt die Reports nicht um, und ein Absturz-Rest sperrt kein späteres Speichern (die PID ist im Flatpak je Start gleich).
const TMP_FLAGS=fs.constants.O_WRONLY|fs.constants.O_CREAT|fs.constants.O_EXCL|fs.constants.O_NOFOLLOW;
function writeAtomic(file,data){
  const dir=path.dirname(file); const tmp=path.join(dir,'.'+path.basename(file)+'.tmp-'+crypto.randomBytes(6).toString('hex'));
  try{
    const fd=fs.openSync(tmp,TMP_FLAGS,0o600); try{ writeFull(fd,data); }finally{ fs.closeSync(fd); }
    fs.renameSync(tmp,file);
  }catch(err){ try{ fs.unlinkSync(tmp); }catch(_){} throw err; }
  try{ const d=fs.openSync(dir,'r'); try{ fs.fsyncSync(d); }finally{ fs.closeSync(d); } }catch(_){}
}

module.exports={writeFull,writeAtomic};
