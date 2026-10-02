// Härtet das (regenerierbare) Capacitor-Projekt mobile/android idempotent. Läuft in build-apk.sh nach `npx cap sync`.
// Vorlage Alien Pass (patch-hardening.mjs), ohne dessen Passwort-Teile (Autofill, Biometrie, Zwischenablage).
//   1) Manifest: keine INTERNET-Berechtigung, allowBackup=false, dataExtractionRules (nichts sichern)
//   2) MainActivity: FLAG_SECURE, WebView-Einstellungen enger als Capacitor-Standard, CSP-Header auch für den Worker
//   3) Plugin SaveFile: Speichern über den Android-Speichern-Dialog (SAF ACTION_CREATE_DOCUMENT) — einzige Brücke zur Seite
//   4) Plugin LinkGuard: keine Navigation; nur die feste Link-Liste und mailto an kontakt@ gehen nach außen
// Link-Liste und CSP kommen aus desktop/main.js (eine Quelle für Flatpak und APK).
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';

const die = m => { console.error('FEHLER: ' + m + ' — Build abgebrochen!'); process.exit(1); };
const jstr = s => '"' + s.replace(/\\/g, '\\\\').replace(/"/g, '\\"') + '"';

// ── Quelle: desktop/main.js ──
const MAINJS = readFileSync('../desktop/main.js', 'utf8');
const linksSrc = (MAINJS.match(/const LINKS=new Set\(\[([\s\S]*?)\]\)/) || [])[1] || die('LINKS in desktop/main.js nicht gefunden');
const LINKS = [...linksSrc.matchAll(/'([^']+)'/g)].map(m => m[1]);
if (LINKS.length < 3 || !LINKS.every(u => u.startsWith('https://'))) die('Link-Liste aus desktop/main.js unplausibel');
const MAIL = (MAINJS.match(/const MAIL='([^']+)', MAIL_MAX=(\d+)/) || []);
if (!MAIL[1]) die('MAIL in desktop/main.js nicht gefunden');
const cspM = MAINJS.match(/const CSP="([^"]+)"\+\s*"([^"]+)";/);
if (!cspM) die('CSP in desktop/main.js nicht gefunden');
const CSP = cspM[1] + cspM[2];
if (!/connect-src 'self'/.test(CSP) || !/worker-src 'self'/.test(CSP)) die('CSP unplausibel');

// ── 1) Manifest ──
const MANIFEST = 'android/app/src/main/AndroidManifest.xml';
let m = readFileSync(MANIFEST, 'utf8');
m = m.replace(/android:allowBackup="true"/g, 'android:allowBackup="false"');
m = m.replace(/^\s*<uses-permission android:name="android\.permission\.INTERNET"\s*\/>\s*$/gm, '');
const XML_DIR = 'android/app/src/main/res/xml';
mkdirSync(XML_DIR, { recursive: true });
writeFileSync(XML_DIR + '/data_extraction_rules.xml', `<?xml version="1.0" encoding="utf-8"?>
<!-- BTC Steuertool: nichts sichern — weder Cloud-Backup noch Geraet-zu-Geraet-Transfer. Die App legt ohnehin keine Nutzerdaten ab. -->
<data-extraction-rules>
    <cloud-backup disableIfNoEncryptionCapabilities="true">
        <exclude domain="root"/><exclude domain="file"/><exclude domain="database"/><exclude domain="sharedpref"/><exclude domain="external"/>
    </cloud-backup>
    <device-transfer>
        <exclude domain="root"/><exclude domain="file"/><exclude domain="database"/><exclude domain="sharedpref"/><exclude domain="external"/>
    </device-transfer>
</data-extraction-rules>
`);
if (!/android:dataExtractionRules=/.test(m)) m = m.replace(/<application\b/, '<application android:dataExtractionRules="@xml/data_extraction_rules"');
writeFileSync(MANIFEST, m);
if (!/android:allowBackup="false"/.test(m) || /android\.permission\.INTERNET/.test(m) || !/android:dataExtractionRules="@xml\/data_extraction_rules"/.test(m))
  die('Manifest-Härtung unvollständig');
if (/<uses-permission/.test(m)) die('Quell-Manifest deklariert eine Berechtigung');

// ── 2–4) Java ──
const DIR = 'android/app/src/main/java/org/alieninvestor/steuertool';
mkdirSync(DIR, { recursive: true });

writeFileSync(DIR + '/MainActivity.java', `package org.alieninvestor.steuertool;

import android.os.Bundle;
import android.view.WindowManager;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import com.getcapacitor.BridgeActivity;
import com.getcapacitor.BridgeWebViewClient;
import java.util.HashMap;
import java.util.Map;

// Erzeugt von mobile/patch-hardening.mjs — nicht von Hand ändern.
public class MainActivity extends BridgeActivity {
    // Dieselbe CSP wie die Desktop-Hülle (desktop/main.js). Als Antwort-Header gilt sie auch für den Pyodide-Worker;
    // das Meta-Tag in index.html (mobile/build-www.sh) deckt die Seite schon vor dem Tausch des WebViewClient ab.
    static final String CSP = ${jstr(CSP)};

    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(SaveFilePlugin.class);
        registerPlugin(LinkGuardPlugin.class);
        super.onCreate(savedInstanceState);
        // Kein Screenshot/Screen-Recording, keine Vorschau in der App-Übersicht (Steuerzahlen, Bestände)
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        WebView wv = getBridge().getWebView();
        WebSettings s = wv.getSettings();
        s.setGeolocationEnabled(false);
        s.setJavaScriptCanOpenWindowsAutomatically(false);
        s.setSupportMultipleWindows(false);
        s.setAllowFileAccess(false);          // Inhalte kommen nur vom App-eigenen Server (https://localhost), nie über file://
        getBridge().setWebViewClient(new BridgeWebViewClient(getBridge()) {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest request) {
                WebResourceResponse r = super.shouldInterceptRequest(view, request);
                if (r != null) {
                    Map<String, String> h = new HashMap<>();
                    if (r.getResponseHeaders() != null) h.putAll(r.getResponseHeaders());
                    h.put("Content-Security-Policy", CSP);
                    h.put("X-Content-Type-Options", "nosniff");
                    r.setResponseHeaders(h);
                }
                return r;
            }
        });
    }
}
`);

writeFileSync(DIR + '/SaveFilePlugin.java', `package org.alieninvestor.steuertool;

import android.app.Activity;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.provider.OpenableColumns;
import android.util.Base64;
import androidx.activity.result.ActivityResult;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.ActivityCallback;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.io.OutputStream;
import java.util.regex.Pattern;

/** Einzige Brücke zur Seite: save({name, data}) öffnet den Android-Speichern-Dialog (SAF) und schreibt die Bytes an den
 *  gewählten Ort. Gleiche Regeln wie saveFile der Desktop-Hülle: Name ^[\\w.-]{1,120}\\.(txt|csv|zip)$, höchstens 50 MB.
 *  Keine Berechtigung nötig — Android gibt nur für das eine gewählte Dokument Schreibzugriff. Erzeugt von mobile/patch-hardening.mjs. */
@CapacitorPlugin(name = "SaveFile")
public class SaveFilePlugin extends Plugin {
    private static final Pattern NAME = Pattern.compile("^[\\\\w.-]{1,120}\\\\.(txt|csv|zip)$");
    private static final int MAX = 50 * 1024 * 1024;

    @PluginMethod
    public void save(PluginCall call) {
        String name = call.getString("name", "");
        String data = call.getString("data");
        if (name == null || !NAME.matcher(name).matches()) { call.reject("Ungültiger Dateiname"); return; }
        if (data == null || data.length() > (MAX / 3 + 1) * 4) { call.reject("Datei zu groß oder leer"); return; }
        String mime = name.endsWith(".zip") ? "application/zip" : name.endsWith(".csv") ? "text/csv" : "text/plain";
        Intent i = new Intent(Intent.ACTION_CREATE_DOCUMENT);
        i.addCategory(Intent.CATEGORY_OPENABLE);
        i.setType(mime);
        i.putExtra(Intent.EXTRA_TITLE, name);
        startActivityForResult(call, i, "onPicked");
    }

    @ActivityCallback
    private void onPicked(PluginCall call, ActivityResult result) {
        if (call == null) return;
        JSObject ret = new JSObject();
        Uri uri = (result.getResultCode() == Activity.RESULT_OK && result.getData() != null) ? result.getData().getData() : null;
        if (uri == null) { ret.put("saved", false); call.resolve(ret); return; }   // abgebrochen
        byte[] bytes;
        try { bytes = Base64.decode(call.getString("data", ""), Base64.DEFAULT); }
        catch (IllegalArgumentException e) { call.reject("Daten unlesbar"); return; }
        try (OutputStream os = getContext().getContentResolver().openOutputStream(uri, "wt")) {
            if (os == null) throw new java.io.IOException("kein Ziel");
            os.write(bytes);
        } catch (Exception e) { call.reject("Speichern fehlgeschlagen: " + e.getMessage()); return; }
        String shown = call.getString("name");
        try (Cursor c = getContext().getContentResolver().query(uri, new String[] { OpenableColumns.DISPLAY_NAME }, null, null, null)) {
            if (c != null && c.moveToFirst() && c.getString(0) != null) shown = c.getString(0);
        } catch (Exception ignored) { }
        ret.put("saved", true);
        ret.put("name", shown);
        call.resolve(ret);
    }
}
`);

const linksJava = LINKS.map(u => '        ' + jstr(u)).join(',\n');
writeFileSync(DIR + '/LinkGuardPlugin.java', `package org.alieninvestor.steuertool;

import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.net.Uri;
import com.getcapacitor.Plugin;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Locale;
import java.util.Set;

/** Keine Navigation weg von der App. Capacitor fragt vor jedem Seitenwechsel die Plugins (Bridge.launchIntent) — hier endet jeder:
 *  die eigene Seite (https://localhost) lädt normal, Links der festen Liste (aus desktop/main.js) und ein mailto an die feste Adresse
 *  mit höchstens subject/body gehen an Browser bzw. Mailprogramm, alles andere wird verworfen. Erzeugt von mobile/patch-hardening.mjs. */
@CapacitorPlugin(name = "LinkGuard")
public class LinkGuardPlugin extends Plugin {
    private static final Set<String> LINKS = new HashSet<>(Arrays.asList(
${linksJava}
    ));
    private static final String MAIL = ${jstr(MAIL[1])};
    private static final int MAIL_MAX = ${MAIL[2]};

    static String norm(Uri u) {   // wie new URL(u).href: leerer Pfad → "/"
        String p = u.getEncodedPath();
        String s = u.getScheme() + "://" + u.getEncodedAuthority() + (p == null || p.isEmpty() ? "/" : p);
        if (u.getEncodedQuery() != null) s += "?" + u.getEncodedQuery();
        if (u.getEncodedFragment() != null) s += "#" + u.getEncodedFragment();
        return s;
    }

    static boolean mailOk(Uri u) {
        String s = u.toString();
        if (s.length() > MAIL_MAX) return false;
        String ssp = u.getEncodedSchemeSpecificPart();
        if (ssp == null) return false;
        int q = ssp.indexOf('?');
        String addr = Uri.decode(q < 0 ? ssp : ssp.substring(0, q)).toLowerCase(Locale.ROOT);
        if (!MAIL.equals(addr)) return false;
        if (q >= 0) for (String kv : ssp.substring(q + 1).split("&")) {
            if (kv.isEmpty()) continue;
            String k = Uri.decode(kv.split("=", 2)[0]);
            if (!k.equals("subject") && !k.equals("body")) return false;
        }
        return true;
    }

    @Override
    public Boolean shouldOverrideLoad(Uri url) {
        String scheme = url.getScheme() == null ? "" : url.getScheme();
        if (scheme.equals("https") && "localhost".equals(url.getHost()) && url.getPort() == -1) return null;   // eigene Seite
        Intent i = null;
        if (scheme.equals("mailto") && mailOk(url)) i = new Intent(Intent.ACTION_SENDTO, url);
        else if (scheme.equals("https") && LINKS.contains(norm(url))) {
            i = new Intent(Intent.ACTION_VIEW, url);
            i.addCategory(Intent.CATEGORY_BROWSABLE);
        }
        if (i != null) {
            i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            try { getContext().startActivity(i); } catch (ActivityNotFoundException ignored) { }
        }
        return true;   // nie in der App-WebView öffnen
    }
}
`);

// Invarianten
const main = readFileSync(DIR + '/MainActivity.java', 'utf8');
if (!main.includes('FLAG_SECURE') || !main.includes('registerPlugin(SaveFilePlugin.class)') || !main.includes('registerPlugin(LinkGuardPlugin.class)'))
  die('MainActivity unvollständig');
console.log(`Gehärtet: Manifest (keine Berechtigung, kein Backup), FLAG_SECURE, CSP-Header, SaveFile, LinkGuard (${LINKS.length} Links + mailto ${MAIL[1]}).`);
