'use strict';
// BTC Steuertool Desktop — Brücke zur Web-Oberfläche. Mehr als dieser Aufruf existiert nicht; die Seite sieht weder Node noch Pfade.
// Links öffnet der Hauptprozess selbst (feste Liste), dafür braucht es keine Brücke.
const {contextBridge,ipcRenderer}=require('electron');

contextBridge.exposeInMainWorld('AlienDesktop',{
  saveFile:(name,data)=>ipcRenderer.invoke('file:save',String(name),data instanceof Uint8Array?data:new Uint8Array(0))   // → Dateiname oder null (abgebrochen)
});
