#!/usr/bin/env bash
# Behaviour test for `mesh_prep.py gate`: every stage passes its good fixture (exit 0) and fails its known-bad
# fixture (exit 1) on the gate that names the fault. Run: bash tests/test_asset_gates.sh [work folder]
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PREP="$HERE/../scripts/mesh_prep.py"
WORK="${1:-$(mktemp -d)}"
status=0
if [ -z "${BLENDER:-}" ]; then
  BLENDER="$(ls -d "C:/Program Files/Blender Foundation/Blender "*/blender.exe 2>/dev/null | sort -V | tail -1)"
fi
export BLENDER
[ -f "$WORK/fixtures/rig_bad.blend" ] || "$BLENDER" -b --factory-startup -t 6 --python "$HERE/make_gate_fixtures.py" -- "$WORK/fixtures" > "$WORK/fixtures.log" 2>&1
F="$WORK/fixtures"

expect() {
  local want="$1" name="$2" phrase="$3"
  shift 3
  uv run --no-project python "$PREP" gate "$@" --out "$WORK/$name" > "$WORK/$name.log" 2>&1
  local got=$?
  if [ "$got" != "$want" ]; then
    echo "FAIL $name: exit $got, wanted $want ($(tail -1 "$WORK/$name.log"))"
    status=1
  elif [ -n "$phrase" ] && ! grep -q -- "$phrase.*FAIL" "$WORK/$name/report.md"; then
    echo "FAIL $name: gate '$phrase' not reported as failed"
    status=1
  else
    echo "ok   $name (exit $got)"
  fi
}

H="--high $F/retopo_high.glb --no-render"
expect 0 retopo_good "" retopo "$F/retopo_good.blend" --deforms $H
expect 1 retopo_bad "quad share" retopo "$F/retopo_bad.blend" --deforms $H
expect 0 retopo_bad_static "" retopo "$F/retopo_bad.blend" $H
expect 1 retopo_torn "hausdorff max" retopo "$F/retopo_torn.blend" --deforms $H
if grep -q "contact crease" "$WORK/retopo_torn/report.md"; then
  echo "FAIL retopo_torn: a torn mesh was explained as a contact crease"
  status=1
fi
expect 1 retopo_no_high "shape compared" retopo "$F/retopo_good.blend" --deforms
expect 0 uv_good "" uv "$F/uv_good.glb" --texture-size 1024 --padding 4
expect 1 uv_overlap "UV overlap" uv "$F/uv_overlap.glb" --texture-size 1024 --padding 4
expect 0 uv_overlap_atlas "" uv "$F/uv_overlap.glb" --texture-size 1024 --padding 4 --uv-mode atlas
expect 1 uv_padding "closer than" uv "$F/uv_padding.glb" --texture-size 1024 --padding 4
expect 0 texture_good "" texture "$F/texture_good.blend"
expect 1 texture_bad "Normal: colour space" texture "$F/texture_bad.blend"
expect 0 bake_good "" bake "$F/bake_low.blend" --high "$F/bake_high.glb"
expect 1 bake_inverted "pointing inward" bake "$F/bake_bad.blend" --high "$F/bake_high.glb" --no-render
expect 1 bake_short_rays "ray distance covers" bake "$F/bake_low.blend" --high "$F/bake_high.glb" --ray-distance 0.001 --no-render
expect 0 rig_good "" rig "$F/rig_good.blend"
expect 1 rig_bad "unweighted" rig "$F/rig_bad.blend"
expect 1 rig_stray "stray vertices" rig "$F/rig_stray.blend"
[ "$status" = 0 ] && echo "ok: every gate passes its good fixture and fails its bad one"
exit $status
