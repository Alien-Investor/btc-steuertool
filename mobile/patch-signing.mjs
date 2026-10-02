// Version aus ../VERSION und Release-Signatur (~/.android-keys/steuertool-keystore.properties) idempotent in android/app/build.gradle.
// Muster Alien Pass patch-signing.mjs. versionCode MUSS je Release steigen, sonst kein Update bei Android/Obtainium.
import { readFileSync, writeFileSync } from 'node:fs';
const f = 'android/app/build.gradle';
let g = readFileSync(f, 'utf8');
const v = readFileSync('../VERSION', 'utf8');
const name = (v.match(/^VERSION_NAME=(.+)$/m) || [])[1]?.trim();
const code = (v.match(/^VERSION_CODE=(\d+)$/m) || [])[1]?.trim();
if (!name || !code) { console.error('FEHLER: VERSION_NAME/VERSION_CODE fehlen in VERSION'); process.exit(1); }
g = g.replace(/versionName\s+"[^"]*"/, `versionName "${name}"`).replace(/versionCode\s+\d+/, `versionCode ${code}`);
if (!g.includes('SIGNING-INJECTED')) {
  g = g.replace("apply plugin: 'com.android.application'", `// SIGNING-INJECTED
def keystorePropertiesFile = new File(System.getenv("HOME") + "/.android-keys/steuertool-keystore.properties")
def keystoreProperties = new Properties()
if (keystorePropertiesFile.exists()) { keystoreProperties.load(new FileInputStream(keystorePropertiesFile)) }

apply plugin: 'com.android.application'`);
  g = g.replace('    buildTypes {', `    signingConfigs {
        release {
            if (keystorePropertiesFile.exists()) {
                storeFile file(keystoreProperties['storeFile'])
                storePassword keystoreProperties['storePassword']
                keyAlias keystoreProperties['keyAlias']
                keyPassword keystoreProperties['keyPassword']
            }
        }
    }
    buildTypes {`);
  g = g.replace('        release {\n            minifyEnabled false', '        release {\n            signingConfig signingConfigs.release\n            minifyEnabled false');
}
if (!g.includes('signingConfig signingConfigs.release') || !g.includes(`versionCode ${code}`)) { console.error('FEHLER: Signatur/Version nicht in build.gradle'); process.exit(1); }
writeFileSync(f, g);
console.log(`Version ${name} (code ${code}), Signatur steuertool-keystore.properties`);
