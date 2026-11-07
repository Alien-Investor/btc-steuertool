# mobile/apk-bytecode.sh — Bytecode-Endkontrolle der fertigen APK (v1.6, Querfunde Alien Pass v1.23 d-1…d-6, r2d-1/-2, nb-1).
# Eingebunden von build-apk.sh (Endkontrolle), steht in release-quellen.sh (apk). Auch als Werkzeug aufrufbar:
#   bash mobile/apk-bytecode.sh <apk>   prüft eine fertige APK, legt die Ist-Fassung nach mobile/build/apk-bytecode.ist
#
# Bis v1.5 sah die Endkontrolle nur, ob die Plugin-Klassen und einige Zeichenketten vorkommen, und in onCreate 8192 → Window.addFlags. Grün blieben
# (gemessen an Dump-Mutanten der 1.6-Test-APK): setFlags direkt nach addFlags, ein Sprung über addFlags, addFlags auf einem fremden Fenster, LinkGuard
# nicht registriert (Capacitor öffnet dann jede URL per ACTION_VIEW, die feste Link-Liste fiele weg), setFlags in SaveFilePlugin.save, eine weitere App-Klasse.
# Zwei Schichten:
#  (a) Regeln, die auch eine achtlos neu erzeugte Pin-Datei nicht aushebelt: FLAG_SECURE auf getWindow() ohne Sprung, beide Plugins vor super.onCreate,
#      Fenster-Positivliste, keine Reflection, Annotationen (Namen SaveFile/LinkGuard nutzt web/index.html), genau eine Activity, keine npm-Plugins,
#      Capacitor-Konfiguration als exakte Schlüsselmenge.
#  (b) App-Code WÖRTLICH gegen mobile/apk-bytecode.pin: Klassen mit Oberklasse, Annotationen, jede Methode als Befehlsfolge mit catch-Tabelle.
#      LinkGuardPlugin.<clinit> nur als Gerüst; die Links darin müssen genau die Liste aus desktop/main.js sein (sie wechselt ohne Bytecode-Prüfung).
# Ändert ein Werkzeug- oder Vorlagen-Update eine Folge (D8/AGP/Capacitor, patch-hardening.mjs, MAIL oder CSP in desktop/main.js), bricht der Build ab:
# Unterschied ansehen (diff mobile/apk-bytecode.pin mobile/build/apk-bytecode.ist) und nur bewusst übernehmen (cp …ist …pin, Commit mit Begründung).

BC_PKG="Lorg/alieninvestor/steuertool/"

# bc_dumps <apk> <ordner> <build-tools>: Rohdaten für bc_pruefen (dexdump-Fehler brechen ab, nichts wird still übergangen)
bc_dumps() {
  local apk="$1" dir="$2" bt="$3" d
  mkdir -p "$dir/dex"; unzip -q -o "$apk" 'classes*.dex' -d "$dir/dex" || { echo "FEHLER: dex-Dateien nicht lesbar"; return 1; }
  : > "$dir/all.txt"; : > "$dir/ann.txt"
  for d in "$dir"/dex/classes*.dex; do
    "$bt/dexdump" -d "$d" >> "$dir/all.txt" 2>/dev/null || { echo "FEHLER: dexdump -d $(basename "$d") gescheitert"; return 1; }
    # Annotationen zeigt nur `dexdump -a` (Ausgabe mit Binärbytes, darum LC_ALL=C; behalten werden Annotations- und Klassenzeilen)
    "$bt/dexdump" -a "$d" 2>/dev/null | LC_ALL=C awk '/^Class #[0-9]+ annotations:$|^Annotations on |^  VISIBILITY_|^Class #[0-9]+ +-$|^  Class descriptor  : /' >> "$dir/ann.txt" \
      || { echo "FEHLER: dexdump -a $(basename "$d") gescheitert"; return 1; }
  done
  "$bt/aapt" dump xmltree "$apk" AndroidManifest.xml > "$dir/man.txt" || { echo "FEHLER: Manifest der APK nicht lesbar"; return 1; }
  unzip -p "$apk" assets/capacitor.config.json > "$dir/cfg.json" 2>/dev/null || : > "$dir/cfg.json"
  unzip -p "$apk" assets/capacitor.plugins.json > "$dir/plugins.json" 2>/dev/null || : > "$dir/plugins.json"
}

# Schnitt-Helfer (wie Alien Pass v1.23): Klassenblock, Methode nach Name UND Signatur, Befehlsfolge, catch-Tabelle, Methodenliste
bc_cls() { awk -v c="Class descriptor  : '$1'" 'index($0,c){f=1;next} f&&/Class descriptor/{f=0} f' <<<"$BC_APPDEX"; }
bc_methT() { awk -v m="name          : '$1'" -v t="type          : '$2'" '/^ +name +: /{f=0; n=index($0,m)>0; next} n{n=0; if(index($0,t)) f=1; next} f'; }
bc_ins() { grep -E '\|[0-9a-f]{4}: ' | sed -E 's/^.*\|[0-9a-f]{4}: //; s/ \/\/ .*$//' || true; }
bc_fang() { awk '/^ +catches +:/{f=1} /^ +positions +:/{f=0} f' | sed -E 's/^ +//'; }
bc_meths() { awk '/^  (Static fields|Instance fields|Direct methods|Virtual methods) /{s=$1; next} (s=="Direct"||s=="Virtual") && /^      name          : /{n=$3; next}
  (s=="Direct"||s=="Virtual") && /^      type          : / && n!=""{print n $3; n=""}' | tr -d "'" | LC_ALL=C sort; }

# bc_pruefen <ordner> <pin-datei> <desktop/main.js>: alle Regeln (a) und der wörtliche Vergleich (b); schreibt <ordner>/ist.txt
bc_pruefen() {
  local dir="$1" pin="$2" mainjs="$3" main oc appins n c nt m t ann cpn acts cfgok links clinit
  BC_APPDEX="$(awk -v p="'$BC_PKG" '/^  Class descriptor  : /{f=index($0, p)>0} f' "$dir/all.txt")"
  main="$(bc_cls "${BC_PKG}MainActivity;")"; [ -n "$main" ] || { echo "FEHLER: MainActivity nicht im Bytecode"; return 1; }
  oc="$(bc_methT onCreate '(Landroid/os/Bundle;)V' <<<"$main" | bc_ins)"
  appins="$(grep -E '\|[0-9a-f]{4}: ' <<<"$BC_APPDEX" || true)"
  nins() { grep -cE -- "$1" <<<"$appins" || true; }

  # (a1) onCreate: beide Plugins VOR super.onCreate (danach registriert Capacitor sie nicht mehr), dann FLAG_SECURE auf genau dem Fenster aus getWindow(),
  #      unmittelbar hintereinander; in onCreate kein Sprung (if/goto/switch/throw) — ein Sprung über addFlags blieb vorher grün
  grep -qzP '^const-class (v\d+), Lorg/alieninvestor/steuertool/SaveFilePlugin;\ninvoke-virtual \{(v\d+), \1\}, Lorg/alieninvestor/steuertool/MainActivity;\.registerPlugin:\(Ljava/lang/Class;\)V\nconst-class (v\d+), Lorg/alieninvestor/steuertool/LinkGuardPlugin;\ninvoke-virtual \{\2, \3\}, Lorg/alieninvestor/steuertool/MainActivity;\.registerPlugin:\(Ljava/lang/Class;\)V\ninvoke-super \{\2, v\d+\}, Lcom/getcapacitor/BridgeActivity;\.onCreate:\(Landroid/os/Bundle;\)V\ninvoke-virtual \{\2\}, Lorg/alieninvestor/steuertool/MainActivity;\.getWindow:\(\)Landroid/view/Window;\nmove-result-object (v\d+)\nconst/16 (v\d+), #int 8192\ninvoke-virtual \{\4, \5\}, Landroid/view/Window;\.addFlags:\(I\)V\n' <<<"$oc"$'\n' \
    || { echo "FEHLER: MainActivity.onCreate: nicht SaveFile + LinkGuard vor super.onCreate, danach FLAG_SECURE auf getWindow()"; return 1; }
  ! grep -qE '^(if-|goto|packed-switch|sparse-switch|throw)' <<<"$oc" || { echo "FEHLER: Sprung in MainActivity.onCreate"; return 1; }
  # (a2) Fenster-Positivliste über allen App-Code: addFlags genau einmal (onCreate), nichts, das FLAG_SECURE wieder wegnimmt (setFlags, setAttributes,
  #      clearFlags, LayoutParams schreiben, WindowManager/ViewManager); die Regel muss an einer Probe greifen (sonst wäre sie still wirkungslos)
  local winrx='Landroid/view/Window;\.(setFlags|setAttributes|getAttributes|clearFlags)|Landroid/view/(WindowManager|ViewManager)|onWindowAttributesChanged|LayoutParams;\.copyFrom|iput [^,]+, [^,]+, L[^;]+;\.flags:I'
  grep -qE "$winrx" <<<'001236: 6e20 0000 0000  |0000: invoke-virtual {v1, v0}, Landroid/view/Window;.clearFlags:(I)V' || { echo "FEHLER: Fenster-Regel greift nicht (Probe)"; return 1; }
  [ "$(nins "$winrx")" = 0 ] || { echo "FEHLER: App-Code ändert Fenster-Flags/Attribute (Fenster-Positivliste)"; return 1; }
  [ "$(nins 'Landroid/view/Window;\.addFlags')" = 1 ] || { echo "FEHLER: Window.addFlags im App-Code nicht genau einmal"; return 1; }
  # (a3) Plugins nur über die zwei registerPlugin in onCreate, keine Reflection (ein per Zeichenkette gebauter Methodenname ginge an a2 vorbei)
  [ "$(nins ';\.registerPlugin')" = 2 ] && [ "$(nins ';\.addPlugin')" = 0 ] || { echo "FEHLER: Plugin-Registrierung außerhalb der zwei registerPlugin in onCreate"; return 1; }
  for p in 'Ljava/lang/reflect/' 'Ljava/lang/invoke/' 'Ljava/lang/Class;\.forName:' 'Ljava/lang/Class;\.get(Declared)?(Method|Field|Constructor)' \
           'Ldalvik/system/' '"(clearFlags|setFlags|setAttributes)"'; do
    [ "$(nins "$p")" = 0 ] || { echo "FEHLER: Reflection bzw. Fenster-Methodenname als Zeichenkette im App-Code ($p)"; return 1; }
  done
  # (a4) wie bis v1.5: CSP-Header und Speichern-Dialog im App-Code
  for p in '"Content-Security-Policy"' "connect-src 'self'" '"android.intent.action.CREATE_DOCUMENT"'; do
    [ "$(nins "$p")" -ge 1 ] || { echo "FEHLER: fehlt im Bytecode: $p"; return 1; }
  done
  # (a5) Annotationen exakt (dexdump -d zeigt keine): Plugin-Namen, die web/index.html ruft (ein anderer Name machte DROID still zu null), @PluginMethod
  #      und @ActivityCallback an den richtigen Methoden; im ganzen Dump genau die Capacitor-Kernplugins ohne Namen + SaveFile + LinkGuard, kein @NativePlugin
  ann="$(LC_ALL=C awk -v p="$BC_PKG" '/^Class #[0-9]+ annotations:$/{an=$2; buf=""; w=""; next}
    /^Annotations on class/{w="class"; next} /^Annotations on (method|field) /{w=$3 " " $5; gsub(/\047/, "", w); next}
    /^  VISIBILITY_RUNTIME /{buf=buf w " " substr($0, 22) "\n"; next}
    /^Class #[0-9]+ +-$/{cur=($2==an) ? buf : ""; next}
    /^  Class descriptor  : /{c=$4; gsub(/\047/, "", c); if (index(c, p)==1 && cur!="") {n=split(cur, L, "\n"); for (i=1; i<n; i++) print c " " L[i]} cur=""}' "$dir/ann.txt" | LC_ALL=C sort)"
  [ "$ann" = "${BC_PKG}LinkGuardPlugin; class Lcom/getcapacitor/annotation/CapacitorPlugin; name=\"LinkGuard\"
${BC_PKG}SaveFilePlugin; class Lcom/getcapacitor/annotation/CapacitorPlugin; name=\"SaveFile\"
${BC_PKG}SaveFilePlugin; method onPicked Lcom/getcapacitor/annotation/ActivityCallback;
${BC_PKG}SaveFilePlugin; method save Lcom/getcapacitor/PluginMethod;" ] || { echo "FEHLER: Annotationen der App-Klassen ≠ geprüfte (Plugin-Namen, @PluginMethod)"; return 1; }
  cpn="$(LC_ALL=C grep -a '^  VISIBILITY_RUNTIME Lcom/getcapacitor/annotation/CapacitorPlugin;' "$dir/ann.txt" | LC_ALL=C grep -aoE 'CapacitorPlugin;( name="[^"]*")?' \
         | sed -E 's/^CapacitorPlugin;( name="([^"]*)")?$/\2/; s/^$/-/' | LC_ALL=C sort | tr '\n' ' ' || true)"
  [ "$cpn" = "- - - LinkGuard SaveFile " ] && ! LC_ALL=C grep -aq '^  VISIBILITY_RUNTIME Lcom/getcapacitor/NativePlugin;' "$dir/ann.txt" \
    || { echo "FEHLER: Plugin-Menge im Bytecode ≠ Kern + SaveFile + LinkGuard (${cpn:-keine})"; return 1; }
  [ "$(tr -d '[:space:]' < "$dir/plugins.json")" = "[]" ] || { echo "FEHLER: assets/capacitor.plugins.json nicht leer (npm-Plugin in der APK?)"; return 1; }
  # (a6) Komponenten: genau EINE Activity = MainActivity, kein activity-alias, MAIN + LAUNCHER genau einmal und nur dort (eine zweite Activity
  #      ohne FLAG_SECURE oder ein anderer Launcher fiele sonst nirgends auf)
  acts="$(awk '/^ *E: /{ind=index($0,"E:"); if (inact && ind<=ai) inact=0} /^ *E: activity \(/{inact=1; ai=index($0,"E:"); n++}
    inact{a=index($0,"A: "); print n ":" (a==ai+2 ? "attr" : "sub") ": " $0}' "$dir/man.txt")"
  [ "$(grep -cE '^ *E: activity \(' "$dir/man.txt" || true)" = 1 ] && ! grep -q 'E: activity-alias' "$dir/man.txt" \
    && [ "$(grep -cE '^1:attr: +A: android:name\(0x01010003\)="org\.alieninvestor\.steuertool\.MainActivity" ' <<<"$acts" || true)" = 1 ] \
    && [ "$(grep -c '"android.intent.category.LAUNCHER"' "$dir/man.txt" || true)" = 1 ] && [ "$(grep -c '"android.intent.category.LAUNCHER"' <<<"$acts" || true)" = 1 ] \
    && [ "$(grep -c '"android.intent.action.MAIN"' "$dir/man.txt" || true)" = 1 ] && [ "$(grep -c '"android.intent.action.MAIN"' <<<"$acts" || true)" = 1 ] \
    || { echo "FEHLER: Manifest: nicht genau eine Activity org.alieninvestor.steuertool.MainActivity mit dem einzigen Launcher (oder activity-alias)"; return 1; }
  # (a7) Capacitor-Konfiguration der APK als exakte Schlüsselmenge (Pass r2d-2), wortgleich patch-hardening.mjs: webContentsDebuggingEnabled (WebView
  #      samt Steuerdaten über adb inspizierbar), loggingBehavior, server.url/plugins … liefen sonst durch. jq liest Escapes und bei doppelten Schlüsseln
  #      den letzten — wie Androids org.json. Ein jq-Fehler (kein JSON) gilt als Abweichung.
  cfgok="$(jq -r '(type == "object") and ((.android | type) == "object")
    and ((keys - ["appId", "appName", "webDir", "android", "loggingBehavior"]) == [])
    and (((.android | keys) - ["allowMixedContent", "webContentsDebuggingEnabled", "loggingBehavior"]) == [])
    and (.appId == "org.alieninvestor.steuertool") and (.webDir == "www") and ((.appName | type) == "string") and (.appName != "")
    and (.android.allowMixedContent == false)
    and ((.android | has("webContentsDebuggingEnabled") | not) or (.android.webContentsDebuggingEnabled == false))
    and ([., .android] | all((has("loggingBehavior") | not) or (.loggingBehavior == "none")))' "$dir/cfg.json" 2>/dev/null || true)"
  [ "$cfgok" = true ] || { echo "FEHLER: Capacitor-Konfiguration der APK ≠ erlaubte Schlüsselmenge (webContentsDebuggingEnabled/loggingBehavior/server …)"; return 1; }
  # (a8) Links in LinkGuardPlugin.<clinit> = die Liste aus desktop/main.js (gleicher Ausdruck wie patch-hardening.mjs), in derselben Reihenfolge
  clinit="$(bc_cls "${BC_PKG}LinkGuardPlugin;" | bc_methT '<clinit>' '()V' | bc_ins)"
  links="$(node -e 'const s=require("fs").readFileSync(process.argv[1],"utf8").match(/const LINKS=new Set\(\[([\s\S]*?)\]\)/); if(!s) process.exit(1);
    console.log([...s[1].matchAll(/'"'"'([^'"'"']+)'"'"'/g)].map(m=>m[1]).join("\n"))' "$mainjs")" || { echo "FEHLER: LINKS in desktop/main.js nicht lesbar"; return 1; }
  [ -n "$links" ] && [ "$(sed -nE 's/^const-string v[0-9]+, "(.*)"$/\1/p' <<<"$clinit")" = "$links" ] \
    || { echo "FEHLER: Links in LinkGuardPlugin ≠ LINKS in desktop/main.js"; return 1; }

  # (b) Ist-Fassung des App-Codes und wörtlicher Vergleich mit der Pin-Datei
  {
    echo "# Bytecode der App-Klassen (mobile/apk-bytecode.sh erzeugt, nie von Hand ändern)"
    echo "# Klassen → Oberklasse"
    awk -v p="$BC_PKG" '/^  Class descriptor  : /{c=$4; gsub(/\047/,"",c); f=index(c,p)==1; next} f && /^  Superclass +: /{s=$3; gsub(/\047/,"",s); print c " → " s; f=0}' <<<"$BC_APPDEX" | LC_ALL=C sort
    echo "# Annotationen"; echo "$ann"
    for c in $(awk -v p="$BC_PKG" '/^  Class descriptor  : /{c=$4; gsub(/\047/,"",c); if (index(c,p)==1) print c}' <<<"$BC_APPDEX" | LC_ALL=C sort); do
      m="$(bc_cls "$c")"
      while read -r nt; do
        [ -n "$nt" ] || continue; n="${nt%%(*}"; t="(${nt#*(}"
        echo "## $c $n $t"
        if [ "$c $n" = "${BC_PKG}LinkGuardPlugin; <clinit>" ]; then   # Gerüst ohne die Links (a8 prüft sie)
          bc_methT "$n" "$t" <<<"$m" | bc_ins | sed -E 's/^const-string v[0-9]+, ".*"$/const-string <LINK aus desktop\/main.js>/; s/^(filled-new-array\/range) \{[^}]*\}/\1 {…}/' | uniq
        else
          bc_methT "$n" "$t" <<<"$m" | bc_ins
        fi
        bc_methT "$n" "$t" <<<"$m" | bc_fang
      done < <(bc_meths <<<"$m")
    done
  } > "$dir/ist.txt"
  if ! cmp -s "$pin" "$dir/ist.txt"; then
    echo "FEHLER: Bytecode der App-Klassen ≠ $(basename "$pin") — Unterschied (Anfang):"
    diff -u "$pin" "$dir/ist.txt" | head -60 || true
    echo "  Ist-Fassung: mobile/build/apk-bytecode.ist. Nur bewusst übernehmen (Kopf von mobile/apk-bytecode.sh)."
    return 1
  fi
  echo "Bytecode = $(basename "$pin") ($(grep -c '^## ' "$dir/ist.txt") Methoden wörtlich), Regeln a1–a8 OK."
}

# Als Werkzeug: bash mobile/apk-bytecode.sh <apk>
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  set -euo pipefail
  [ "$#" = 1 ] && [ -f "$1" ] || { echo "Aufruf: bash mobile/apk-bytecode.sh <apk>"; exit 1; }
  APKARG="$(realpath "$1")"; cd "$(dirname "$0")"
  ANDROID_HOME="$(bash -c 'source ~/Apps/android-build/env.sh >/dev/null 2>&1; printf %s "$ANDROID_HOME"')"
  [ -n "$ANDROID_HOME" ] || { echo "FEHLER: ANDROID_HOME aus ~/Apps/android-build/env.sh nicht lesbar"; exit 1; }
  W="$(mktemp -d)"; trap 'rm -rf "$W"' EXIT
  bc_dumps "$APKARG" "$W" "$ANDROID_HOME/build-tools/34.0.0"
  rc=0; bc_pruefen "$W" apk-bytecode.pin ../desktop/main.js || rc=$?
  mkdir -p build; cp "$W/ist.txt" build/apk-bytecode.ist 2>/dev/null || true
  exit "$rc"
fi
