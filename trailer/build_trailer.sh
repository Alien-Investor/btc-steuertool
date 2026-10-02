#!/usr/bin/env bash
# build_trailer.sh <de|en> [16x9]  → out/trailer-<lang>-16x9.mp4   (BTC Steuertool, nach dem Muster der App-Trailer)
# Szenen-Clips ohne Karten (zoompan) → Kreuzblenden (xfade) → Karten als Overlay mit Zeitfenster → Musik.
# Voraussetzungen: node make_shots.mjs, python3 make_frames.py, python3 make_cards.py
set -euo pipefail
cd "$(dirname "$0")"
L=${1:-de}; F=${2:-16x9}
case $F in 16x9) W=1920; H=1080;; *) echo "nur 16x9 (9:16 wäre eine zweite Szenenliste)"; exit 1;; esac
FPS=25; X=0.7   # Kreuzblende in Sekunden
FR=frames/$L; C=cards/$L; MUSIK=${MUSIK:-musik/steuertool-web-bett.wav}
O=out/clips-$L-$F; mkdir -p out "$O"; rm -f "$O"/*
CLIPS=(); DURS=(); CARDS=()

# zoompan: anchor center|right (right = Fixpunkt bei 72 % Breite, dort steht das Handy)
zp() { local d=$1 zf=$2 zt=$3 anchor=$4
  local x="iw/2-iw/zoom/2"; [ "$anchor" = right ] && x="(iw-iw/zoom)*0.72"
  echo "scale=$((2*W)):$((2*H)):flags=lanczos,zoompan=z='${zf}+(${zt}-${zf})*on/${d}':x='${x}':y='ih/2-ih/zoom/2':d=${d}:s=${W}x${H}:fps=${FPS}"; }
scene() { local zf=$1 zt=$2 anchor=$3 name=$4 img=$5 dur=$6
  local d; d=$(python3 -c "print(round($dur*$FPS))")
  local f="$O/$(printf %02d ${#CLIPS[@]})-$name.mp4"
  ffmpeg -v error -y -i "$img" -filter_complex "[0:v]scale=${W}:${H}:force_original_aspect_ratio=increase,crop=${W}:${H},$(zp $d $zf $zt $anchor),format=yuv420p[vo]" \
    -map "[vo]" -r $FPS -frames:v $d -c:v libx264 -preset medium -crf 18 "$f"
  CLIPS+=("$f"); DURS+=("$dur"); echo "  ${#CLIPS[@]} $name ${dur}s"; }
card() { CARDS+=("$1|$2|${3:-$2}"); }
last() { echo $(( ${#CLIPS[@]} - 1 )); }

scene 1.00 1.06 center s01-hook      $FR/motiv.jpg     4.5; card c01 $(last)
scene 1.06 1.14 center s02-cloud     $FR/motiv.jpg     5.5; card c02 $(last)
scene 1.00 1.04 center s03-dropzone  $FR/dropzone.jpg  5;   card c03 $(last)
scene 1.04 1.00 center s04-start     $FR/start.jpg     5;   card c04 $(last)
scene 1.00 1.04 center s05-files     $FR/files.jpg     4.4; card l05 $(last)
scene 1.04 1.00 center s06-report    $FR/report.jpg    4.4; card l06 $(last)
scene 1.00 1.04 center s07-fees      $FR/fees.jpg      4.4; card l07 $(last)
scene 1.04 1.00 center s08-proof     $FR/proof.jpg     4.4; card l08 $(last)
scene 1.00 1.04 center s09-nokyc     $FR/nokyc.jpg     4.4; card l09 $(last)
scene 1.04 1.00 center s10-save      $FR/save.jpg      4.4; card l10 $(last)
scene 1.00 1.04 center s11-help      $FR/help.jpg      4.4; card l11 $(last)
scene 1.00 1.06 center s12-kern      $FR/motiv.jpg     5.5; card c12 $(last)
scene 1.08 1.00 center s13-title     $FR/title.jpg     5
scene 1.00 1.00 center s14-ende      $C/end.png        5

# ── Zeitleiste: Startzeiten mit Kreuzblenden ──
N=${#CLIPS[@]}; START=(); acc=0
for ((i=0;i<N;i++)); do START+=("$(python3 -c "print(round($acc - $i*$X, 3))")"); acc=$(python3 -c "print($acc + ${DURS[$i]})"); done
TOTAL=$(python3 -c "print(round($acc - ($N-1)*$X, 3))")
INPUTS=(); for f in "${CLIPS[@]}"; do INPUTS+=(-i "$f"); done
FC=""; prev="0:v"
for ((i=1;i<N;i++)); do
  off=$(python3 -c "print(round(${START[$i]}, 3))")
  FC+="[${prev}][${i}:v]xfade=transition=fade:duration=${X}:offset=${off}[x${i}];"; prev="x${i}"
done
# ── Karten als Overlay mit Zeitfenster ──
k=0
for spec in "${CARDS[@]}"; do IFS='|' read cname a b <<<"$spec"
  S=${START[$a]}; E=$(python3 -c "print(round(${START[$b]} + ${DURS[$b]} - $X, 3))")
  S=$(python3 -c "print(round($S + $X*0.6, 3))")
  INPUTS+=(-loop 1 -framerate $FPS -t "$TOTAL" -i "$C/$cname.png")
  idx=$((N+k))
  FC+="[${idx}:v]format=rgba,fade=t=in:st=${S}:d=0.5:alpha=1,fade=t=out:st=$(python3 -c "print(round($E-0.5,3))"):d=0.5:alpha=1[c${k}];"
  FC+="[${prev}][c${k}]overlay=0:0:enable='between(t,${S},${E})':format=auto[o${k}];"; prev="o${k}"; k=$((k+1))
done
FC+="[${prev}]fade=t=in:st=0:d=0.8,fade=t=out:st=$(python3 -c "print($TOTAL-1.0)"):d=1.0,format=yuv420p[vo]"
ffmpeg -v error -y "${INPUTS[@]}" -filter_complex "$FC" -map "[vo]" -r $FPS -c:v libx264 -preset medium -crf 18 "$O/video.mp4"
DUR=$(ffprobe -v quiet -show_entries format=duration -of csv=p=0 "$O/video.mp4")
OUT="out/trailer-$L-$F.mp4"
ffmpeg -v error -y -i "$O/video.mp4" -i "$MUSIK" -filter_complex \
  "[1:a]atrim=0:${DUR},afade=t=in:st=0:d=1,afade=t=out:st=$(python3 -c "print(float('$DUR')-3)"):d=3,loudnorm=I=-16:TP=-1.5:LRA=11[a]" \
  -map 0:v -map "[a]" -c:v copy -c:a aac -b:a 192k -shortest -movflags +faststart "$OUT"
ffmpeg -v error -y -i "$OUT" -c:v libx264 -preset fast -crf 27 -c:a copy -movflags +faststart "out/preview-$L-$F.mp4"
echo "FERTIG $OUT ($DUR s, $N Szenen, ${#CARDS[@]} Karten, Blende ${X}s) + Vorschau out/preview-$L-$F.mp4"
