"""mesh_prep: validate, repair, remesh, unwrap, simplify, LOD and compress a glTF asset, then prove the output still
looks like the input. Standard library only; each step installs what it needs on first use (uv for Python packages,
npm into a cache folder for glTF Transform, meshoptimizer and glTF-Validator) and Blender runs the renders and bakes.

Usage:
    uv run --no-project python mesh_prep.py run <in.glb|in.gltf> [options]
    uv run --no-project python mesh_prep.py compare <reference.glb> <candidate.glb> [--out DIR] [--profile NAME]
    uv run --no-project python mesh_prep.py gate <retopo|uv|bake|texture|rig> <file> [gate options]

Gate options (the stage gates of references/asset-pipeline.md; each writes report.md and exits 0 or 1):
    retopo  --deforms (quad share and poles are gated) --quad-share 0.9 --budget N; give it the .blend or quad OBJ
    uv      --uv-mode bake|atlas [bake] --texture-size 2048 --padding 8 --texel-density PX_PER_M
    bake    --high HIGH --ray-distance D (or read from the .blend); gates gap, normal texels and the render compare
    texture --channels "Base Color,Normal,Roughness" --max-texture 4096; colour space only from a .blend
    rig     skin weights and a 70 degree bend test of each elbow, knee and spine bone

Run options (every step is a flag; defaults in brackets):
    --out DIR                output folder [<input stem>.prep next to the input]
    --profile NAME           prop | dataset | scan | hero: sets thresholds and limits [prop]
    --no-repair              skip dedup, weld and degenerate or duplicate triangle removal
    --watertight             also write <stem>_watertight.glb, geometry only (collision, print, booleans)
    --remesh METHOD          quadriflow | qremeshify, refused for scan and hero without --force
    --faces N                remesh target faces [5000]
    --uv MODE                auto (unwrap only primitives without UVs) | off [auto]
    --simplify RATIO         keep this share of triangles (meshopt), e.g. 0.5
    --error E                simplify error limit, fraction of mesh radius [0.01]
    --lod LIST               extra LOD files, e.g. 0.5,0.2,0.06
    --bake MODE              auto (after remesh, or simplify below 0.5) | on | off [auto]
    --bake-size N            baked texture edge [1024]
    --textures MODE          keep | webp | ktx2 [keep]; ktx2 needs toktx (MESH_PREP_TOKTX or PATH)
    --max-texture N          texture edge limit for webp and ktx2 [2048]
    --no-compress            skip meshopt compression of the final file
    --budget N               fail if the final file has more triangles than N
    --threshold KEY=VALUE    override one gate threshold (repeatable), keys as in PROFILES
    --no-render              skip the render comparison (geometry gates only); never for hero or scan sign-off
    --force                  allow remesh and heavy simplify on scan and hero profiles

Environment: BLENDER (path to blender; otherwise PATH, then the default Windows install folder), MESH_PREP_TOKTX,
MESH_PREP_CACHE (npm cache folder), MESH_PREP_GPU_WRAPPER (command prefix for Blender renders, e.g. a GPU queue).

Exit code 0 means every gate passed; 1 means at least one failed (see report.md); 2 means a usage or tool error.
"""

import argparse
import glob
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCRIPTS = Path(__file__).resolve().parent
PYTHON_VERSION = "3.12"
NODE_PACKAGES = [
    "@gltf-transform/core@4.5.1",
    "@gltf-transform/extensions@4.5.1",
    "@gltf-transform/functions@4.5.1",
    "meshoptimizer@1.3.0",
    "sharp@0.35.5",
    "gltf-validator@2.0.0-dev.3.10",
]
PYTHON_PACKAGES = {
    "topology": ["trimesh", "numpy", "scipy", "manifold3d"],
    "hausdorff": ["trimesh", "numpy", "scipy", "pymeshlab"],
    "uv-metrics": ["trimesh", "numpy", "scipy", "pillow"],
    "uv-layout": ["trimesh", "numpy", "scipy", "pillow"],
    "uv-unwrap": ["numpy", "xatlas"],
    "watertight": ["trimesh", "numpy", "scipy", "pymeshlab", "manifold3d"],
    "compare-views": ["numpy", "scipy", "pillow"],
}
# Gate thresholds. Hausdorff values are percent of the input's bounding-box diagonal; angles in degrees.
PROFILES = {
    "prop": {
        "hausdorff_max": 1.0, "hausdorff_p95": 0.3, "silhouette_iou_min": 0.98, "normal_mean_max": 6.0,
        "normal_p95_max": 30.0, "albedo_ssim_min": 0.90, "uv_overlap_max_generated": 2.0, "min_simplify_ratio": 0.0,
        "new_non_manifold_per_10k": 2.0,
        "allow_remesh": True,
    },
    "dataset": {
        "hausdorff_max": 1.0, "hausdorff_p95": 0.3, "silhouette_iou_min": 0.98, "normal_mean_max": 6.0,
        "normal_p95_max": 30.0, "albedo_ssim_min": 0.90, "uv_overlap_max_generated": 2.0, "min_simplify_ratio": 0.0,
        "new_non_manifold_per_10k": 2.0,
        "allow_remesh": True,
    },
    "scan": {
        "hausdorff_max": 0.5, "hausdorff_p95": 0.15, "silhouette_iou_min": 0.985, "normal_mean_max": 5.0,
        "normal_p95_max": 25.0, "albedo_ssim_min": 0.92, "uv_overlap_max_generated": 1.0, "min_simplify_ratio": 0.5,
        "new_non_manifold_per_10k": 0.0,
        "allow_remesh": False,
    },
    "hero": {
        "hausdorff_max": 0.3, "hausdorff_p95": 0.1, "silhouette_iou_min": 0.99, "normal_mean_max": 4.0,
        "normal_p95_max": 20.0, "albedo_ssim_min": 0.95, "uv_overlap_max_generated": 1.0, "min_simplify_ratio": 0.5,
        "new_non_manifold_per_10k": 0.0,
        "allow_remesh": False,
    },
}


class ToolError(Exception):
    pass


def last_json_line(text):
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            return json.loads(line)
    raise ToolError(f"no JSON result in output:\n{text[-2000:]}")


def low_priority_flags():
    if os.name == "nt":
        return {"creationflags": subprocess.BELOW_NORMAL_PRIORITY_CLASS}
    return {"preexec_fn": lambda: os.nice(10)}


def run_tool(command, environment=None, low_priority=False):
    extra = low_priority_flags() if low_priority else {}
    completed = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, **(environment or {})}, **extra,
    )
    if completed.returncode != 0:
        raise ToolError(f"{' '.join(map(str, command[:6]))} ... failed ({completed.returncode}):\n{completed.stderr[-3000:]}\n{completed.stdout[-1500:]}")
    return last_json_line(completed.stdout)


def cache_folder():
    return Path(os.environ.get("MESH_PREP_CACHE", Path.home() / ".cache" / "mesh-prep"))


def node_dependencies():
    folder = cache_folder() / "node"
    marker = folder / "installed.json"
    if marker.exists() and json.loads(marker.read_text()) == NODE_PACKAGES:
        return folder
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "package.json").write_text(json.dumps({"name": "mesh-prep-deps", "private": True}))
    npm = shutil.which("npm") or shutil.which("npm.cmd")
    if not npm:
        raise ToolError("npm not found: install Node.js 20 or newer")
    print("installing glTF Transform, meshoptimizer and glTF-Validator (first run only)...", flush=True)
    installed = subprocess.run([npm, "install", "--no-audit", "--no-fund", "--loglevel", "error", *NODE_PACKAGES], cwd=folder)
    if installed.returncode != 0:
        raise ToolError(f"npm install failed in {folder}")
    marker.write_text(json.dumps(NODE_PACKAGES))
    return folder


def gltf(command, *arguments):
    node = shutil.which("node")
    if not node:
        raise ToolError("node not found: install Node.js 20 or newer")
    return run_tool([node, str(SCRIPTS / "mesh_gltf.mjs"), command, *map(str, arguments)], {"MESH_PREP_NODE_DEPS": str(node_dependencies())})


def geometry(command, *arguments):
    uv = shutil.which("uv")
    if not uv:
        raise ToolError("uv not found: install it from https://docs.astral.sh/uv/")
    with_flags = [flag for package in PYTHON_PACKAGES[command] for flag in ("--with", package)]
    return run_tool([uv, "run", "--no-project", "--python", PYTHON_VERSION, *with_flags, "python", str(SCRIPTS / "mesh_geometry.py"), command, *map(str, arguments)], low_priority=True)


def version_key(path):
    name = Path(path).parent.name.replace("Blender ", "")
    return [int(part) if part.isdigit() else 0 for part in name.split(".")]


def find_blender():
    configured = os.environ.get("BLENDER")
    if configured and Path(configured).exists():
        return configured
    on_path = shutil.which("blender")
    if on_path:
        return on_path
    found = sorted(glob.glob("C:/Program Files/Blender Foundation/Blender */blender.exe"), key=version_key)
    if found:
        return found[-1]
    raise ToolError("Blender not found: set BLENDER to the blender executable")


def blender(script, *arguments, render=False, threads=None):
    command = [find_blender(), "--background", "--factory-startup"]
    if threads:
        command += ["--threads", str(threads)]
    command += ["--python", str(SCRIPTS / script), "--", *map(str, arguments)]
    wrapper = os.environ.get("MESH_PREP_GPU_WRAPPER")
    if render and wrapper:
        command = shlex.split(wrapper) + command
    return run_tool(command, low_priority=True)


class Report:
    def __init__(self, output_folder, profile_name, thresholds):
        self.output_folder = output_folder
        self.data = {"profile": profile_name, "thresholds": thresholds, "steps": [], "gates": [], "notes": []}
        self.started = time.monotonic()
        self.last_step_end = self.started

    def step(self, name, result):
        now = time.monotonic()
        seconds = round(now - self.last_step_end, 1)
        self.last_step_end = now
        self.data["steps"].append({"step": name, "seconds": seconds, **result})
        print(f"  {name}: {seconds} s", flush=True)

    def note(self, text):
        self.data["notes"].append(text)
        print(f"  note: {text}", flush=True)

    def gate(self, name, value, limit, passed):
        self.data["gates"].append({"gate": name, "value": value, "limit": limit, "passed": bool(passed)})

    def passed(self):
        return all(gate["passed"] for gate in self.data["gates"])

    def write(self):
        self.data["passed"] = self.passed()
        self.data["total_seconds"] = round(time.monotonic() - self.started, 1)
        (self.output_folder / "report.json").write_text(json.dumps(self.data, indent=1))
        lines = [f"# mesh_prep report: {'PASS' if self.data['passed'] else 'FAIL'}", "", f"Profile: {self.data['profile']}, {self.data['total_seconds']} s", ""]
        lines += ["| Gate | Value | Limit | Result |", "|---|---|---|---|"]
        for gate in self.data["gates"]:
            lines.append(f"| {gate['gate']} | {gate['value']} | {gate['limit']} | {'pass' if gate['passed'] else 'FAIL'} |")
        if self.data["notes"]:
            lines += ["", "## Notes", ""] + [f"- {note}" for note in self.data["notes"]]
        lines += ["", "## Steps", ""]
        shown = ("step", "seconds", "triangles", "triangles_before", "bytes", "dropped", "errors", "warnings", "quad_share", "path", "polygons", "primitives_unwrapped", "baked", "watertight", "manifold3d_status", "output")
        for step in self.data["steps"]:
            summary = {key: value for key, value in step.items() if key in shown}
            lines.append(f"- {json.dumps(summary)}")
        lines += ["", "Contact sheet: `sheet.png` (reference albedo, output albedo, reference normals, output normals, difference)."]
        (self.output_folder / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def gate_ratio(report, label, result, target):
    """A simplify that stops far above its target did not do the job, even if it looks fine."""
    limit = round(target * 1.25, 4)
    report.gate(f"{label} triangle share reached", result["achieved_ratio"], f"<= {limit}", result["achieved_ratio"] <= limit)
    if result["mode"] != "seam-preserving":
        report.note(f"{label}: seam-preserving simplify missed the target, used {result['mode']}")


def will_bake(options, ratio):
    return options.bake == "on" or (options.bake == "auto" and ratio < 0.5)


def simplify_purpose(options, ratio):
    """Tells the simplifier to keep UVs bakeable when a normal bake follows."""
    return "bake" if will_bake(options, ratio) else "geometry"


def bake_normals_if_heavy(report, label, ratio, bake_source, mesh_path, baked_path, options):
    """Below half the triangles a mesh loses shading detail; a normal map baked from the source puts it back.
    On a 66k scan boulder at 20% the normal angle was 9.6 to 11.1 degrees with no bake, whichever simplify ran."""
    if not will_bake(options, ratio):
        return mesh_path
    uv_report = geometry("uv-metrics", mesh_path)
    single_material = gltf("inspect", mesh_path)["materials"] <= 1
    if (uv_report["overlap_percent"] or 0) > 1.0 or not single_material:
        report.note(f"{label}: normal bake skipped, UV overlap {uv_report['overlap_percent']}% or more than one material would smear the bake; unwrap a second UV set first")
        return mesh_path
    report.step(f"bake normals ({label})", blender("blender_remesh_bake.py", "bake", bake_source, mesh_path, baked_path, options.bake_size, "normal", threads=6))
    return baked_path


def gate_non_manifold(report, label, input_topology, candidate_topology, thresholds):
    """Non-manifold edges must not grow beyond the profile's allowance. Simplify used to fold faces into reversed
    twins (15 on a 20% scan LOD); those are removed now, and the allowance covers what is left. Physics and booleans
    need none, so scan and hero allow none and --watertight writes a closed copy with its own gate."""
    allowance = int(thresholds["new_non_manifold_per_10k"] * candidate_topology["triangles"] / 10000)
    limit = input_topology["non_manifold_edges"] + allowance
    report.gate(
        f"{label} (input {input_topology['non_manifold_edges']} + {allowance} allowed)",
        candidate_topology["non_manifold_edges"], f"<= {limit}",
        candidate_topology["non_manifold_edges"] <= limit,
    )


def note_contact_crease(report, distance, thresholds):
    """Explain a Hausdorff max failure that comes from one small region while the rest of the surface fits."""
    if distance["max_percent"] <= thresholds["hausdorff_max"] or distance.get("p99_percent") is None:
        return
    report.note(f"hausdorff p99 {distance['p99_percent']}% of the diagonal (max {distance['max_percent']}%)")
    if distance["p99_percent"] <= thresholds["hausdorff_p95"] and (distance["worst_share_near_max_percent"] or 0) >= 60:
        report.note(
            f"contact crease likely: {distance['worst_share_near_max_percent']}% of the {distance['worst_samples']} "
            f"worst samples sit within 5% of the diagonal of {distance['worst_point']}. Where the high "
            "touches itself (crotch, armpits, fingers) no low can follow: pose the high apart (A-pose, legs apart) or "
            "separate the contact before retopo. The limit stays."
        )


def gate_comparison(report, reference, candidate, thresholds, work, render=True, input_topology=None, render_candidate=None, appearance=True):
    """The quality gate: geometry distance, topology and renders. Adds gates to the report."""
    render_candidate = render_candidate or candidate
    distance = geometry("hausdorff", reference, candidate)
    report.step("hausdorff", distance)
    report.gate("hausdorff max %diag", distance["max_percent"], thresholds["hausdorff_max"], distance["max_percent"] <= thresholds["hausdorff_max"])
    report.gate("hausdorff p95 %diag", distance["p95_percent"], thresholds["hausdorff_p95"], distance["p95_percent"] <= thresholds["hausdorff_p95"])
    note_contact_crease(report, distance, thresholds)
    candidate_topology = geometry("topology", candidate)
    report.step("topology output", candidate_topology)
    report.gate("degenerate faces", candidate_topology["degenerate_faces"], 0, candidate_topology["degenerate_faces"] == 0)
    if input_topology is not None:
        gate_non_manifold(report, "non-manifold edges", input_topology, candidate_topology, thresholds)
    if not render:
        return candidate_topology
    reference_views = work / "views_reference"
    candidate_views = work / "views_output"
    framing = work / "framing.json"
    framing.unlink(missing_ok=True)
    blender("blender_views.py", reference, reference_views, framing, 512, render=True)
    blender("blender_views.py", render_candidate, candidate_views, framing, 512, render=True)
    views = geometry("compare-views", reference_views, candidate_views, report.output_folder / "sheet.png")
    report.step("views", views)
    # An empty render would give IoU 1 and SSIM 1 for free; the input must fill part of every view.
    report.gate("render not empty (input coverage min)", views["reference_coverage_min"], 0.01, views["reference_coverage_min"] >= 0.01)
    report.gate("silhouette IoU min", views["silhouette_iou_min"], thresholds["silhouette_iou_min"], views["silhouette_iou_min"] >= thresholds["silhouette_iou_min"])
    if not appearance:
        report.note("shape stage: normal angle and albedo are not gated before the bake and texture stages")
        return candidate_topology
    report.gate("normal angle mean max (deg)", views["normal_angle_mean_deg_max"], thresholds["normal_mean_max"], views["normal_angle_mean_deg_max"] <= thresholds["normal_mean_max"])
    report.gate("normal angle p95 max (deg)", views["normal_angle_p95_deg_max"], thresholds["normal_p95_max"], views["normal_angle_p95_deg_max"] <= thresholds["normal_p95_max"])
    report.gate("albedo SSIM min", views["albedo_ssim_min"], thresholds["albedo_ssim_min"], views["albedo_ssim_min"] >= thresholds["albedo_ssim_min"])
    return candidate_topology


def thresholds_for(profile_name, overrides):
    thresholds = dict(PROFILES[profile_name])
    for override in overrides or []:
        key, value = override.split("=", 1)
        if key not in thresholds:
            raise ToolError(f"unknown threshold {key}; keys: {', '.join(thresholds)}")
        thresholds[key] = float(value)
    return thresholds


def unwrap(input_path, output_path, raw_folder):
    """xatlas for primitives without UVs: glTF Transform exports raw arrays, Python unwraps, glTF Transform remaps."""
    gltf("uv-export", input_path, raw_folder)
    result = geometry("uv-unwrap", raw_folder)
    return {**result, **gltf("uv-apply", input_path, raw_folder, output_path)}


def toktx_path():
    configured = os.environ.get("MESH_PREP_TOKTX")
    if configured and Path(configured).exists():
        return configured
    return shutil.which("toktx")


def check_refusals(options, thresholds, input_description):
    if options.textures == "ktx2" and not toktx_path():
        raise ToolError("--textures ktx2 needs toktx from KTX-Software (https://github.com/KhronosGroup/KTX-Software/releases); set MESH_PREP_TOKTX")
    if options.remesh and not thresholds["allow_remesh"] and not options.force:
        raise ToolError(f"--remesh is refused for the {options.profile} profile: it replaces the surface. Pass --force only after looking at the asset")
    if options.simplify and options.simplify < thresholds["min_simplify_ratio"] and not options.force:
        raise ToolError(f"--simplify {options.simplify} is below {thresholds['min_simplify_ratio']} for the {options.profile} profile; use --lod for distant copies or --force")
    deforming = input_description["skins"] or input_description["morph_targets"]
    if deforming and (options.remesh or options.watertight or options.bake == "on"):
        raise ToolError("skinned or morph-target meshes cannot be remeshed, made watertight or baked here: those steps drop weights and targets")


def run_pipeline(options):
    source = Path(options.input).resolve()
    output_folder = Path(options.out).resolve() if options.out else source.parent / f"{source.stem}.prep"
    work = output_folder / "stages"
    work.mkdir(parents=True, exist_ok=True)
    thresholds = thresholds_for(options.profile, options.threshold)
    report = Report(output_folder, options.profile, thresholds)
    print(f"mesh_prep {source.name} -> {output_folder} (profile {options.profile})", flush=True)

    current = work / "00_input.glb"
    report.step("decode input", gltf("plain", source, current))
    input_description = gltf("inspect", current)
    report.step("inspect input", input_description)
    check_refusals(options, thresholds, input_description)
    input_validation = gltf("validate", current)
    report.step("validate input", input_validation)
    if input_validation["errors"]:
        report.note(f"input has {input_validation['errors']} validator errors: {input_validation['messages'][:3]}")
    input_topology = geometry("topology", current)
    report.step("topology input", input_topology)
    reference = current

    if not options.no_repair:
        cleaned = work / "01_clean.glb"
        report.step("repair", gltf("clean", current, cleaned))
        current = cleaned

    if options.watertight:
        watertight_path = output_folder / f"{source.stem}_watertight.glb"
        result = geometry("watertight", current, watertight_path)
        report.step("watertight", {**result, "output": str(watertight_path)})
        report.gate("watertight copy is watertight", result["watertight"], True, result["watertight"])
        report.gate("watertight copy manifold3d status", result["manifold3d_status"], "NoError", result["manifold3d_status"] in (None, "NoError"))
        distance = geometry("hausdorff", reference, watertight_path)
        report.step("watertight hausdorff", distance)
        report.gate("watertight hausdorff max %diag", distance["max_percent"], thresholds["hausdorff_max"], distance["max_percent"] <= thresholds["hausdorff_max"])

    bake_source = current
    if options.remesh:
        remeshed = work / "02_remesh.glb"
        quads = output_folder / f"{source.stem}_quads.obj"
        # QuadriFlow runs on the original surface only when it is closed and manifold; the watertight copy makes it so
        # without the voxel pass that loses rings and wires.
        remesh_input = watertight_path if options.watertight else work / "02_remesh_input_watertight.glb"
        if not options.watertight:
            report.step("watertight (remesh input)", geometry("watertight", current, remesh_input))
        remesh_result = blender("blender_remesh_bake.py", "remesh", remesh_input, remeshed, quads, options.remesh, options.faces, threads=6)
        report.step("remesh", {**remesh_result, "output": str(quads)})
        unwrapped = work / "02_remesh_uv.glb"
        report.step("uv unwrap (remesh)", unwrap(remeshed, unwrapped, work / "uv_remesh"))
        current = unwrapped
        if options.bake != "off":
            baked = work / "02_remesh_baked.glb"
            report.step("bake (remesh)", blender("blender_remesh_bake.py", "bake", bake_source, current, baked, options.bake_size, "basecolor,normal,roughness", threads=6))
            current = baked
        else:
            report.note("remesh without bake: the output has no textures")

    description = gltf("inspect", current)
    if options.uv == "auto" and description["primitives_without_uv"] and not options.remesh:
        unwrapped = work / "03_uv.glb"
        report.step("uv unwrap", unwrap(current, unwrapped, work / "uv_raw"))
        current = unwrapped
        uv_report = geometry("uv-metrics", current)
        report.step("uv metrics (generated)", uv_report)
        overlap = uv_report["overlap_percent"] or 0
        report.gate("generated UV overlap %", overlap, thresholds["uv_overlap_max_generated"], overlap <= thresholds["uv_overlap_max_generated"])

    lod_source = current
    if options.simplify:
        simplified = work / "04_simplify.glb"
        simplify_result = gltf("simplify", current, simplified, options.simplify, options.error, simplify_purpose(options, options.simplify))
        report.step("simplify", simplify_result)
        gate_ratio(report, "simplify", simplify_result, options.simplify)
        current = bake_normals_if_heavy(report, "simplify", options.simplify, bake_source, simplified, work / "04_simplify_baked.glb", options)

    final = output_folder / f"{source.stem}.glb"
    if options.no_compress and options.textures == "keep":
        shutil.copyfile(current, final)
    else:
        report.step("compress", gltf("compress", current, final, options.textures, options.max_texture, toktx_path() or ""))
    final_validation = gltf("validate", final)
    report.step("validate output", final_validation)
    report.gate("validator errors (output)", final_validation["errors"], 0, final_validation["errors"] == 0)
    final_description = gltf("inspect", final)
    report.step("inspect output", {**final_description, "output": str(final)})
    if options.budget:
        report.gate("triangle budget", final_description["triangles"], options.budget, final_description["triangles"] <= options.budget)

    plain = work / "05_output_plain.glb"
    plain_result = gltf("plain", final, plain)
    render_candidate = plain
    if plain_result["ktx2_textures_not_viewable"]:
        report.note("Blender cannot read KTX2: renders used the textures before KTX2 encoding; geometry gates used the final file")
        render_candidate = current
    render = not options.no_render
    if not render:
        report.note("render comparison skipped (--no-render): silhouette, normals and albedo were not checked")
    gate_comparison(report, reference, plain, thresholds, work, render=render, input_topology=None if options.remesh else input_topology, render_candidate=render_candidate)
    report.step("uv metrics (output)", geometry("uv-metrics", plain))

    for ratio_text in [value for value in (options.lod or "").split(",") if value]:
        ratio = float(ratio_text)
        error = max(options.error, (1 - ratio) * 0.05)
        limit = round(error * 100, 3)
        lod_plain = work / f"lod_{ratio_text}.glb"
        # The Hausdorff limit below is passed in as the budget, so simplify lowers its error until the LOD fits
        # instead of failing the gate after the fact.
        lod_result = gltf("simplify", lod_source, lod_plain, ratio, error, simplify_purpose(options, ratio), limit)
        gate_ratio(report, f"lod {ratio_text}", lod_result, ratio)
        lod_baked = bake_normals_if_heavy(report, f"lod {ratio_text}", ratio, bake_source, lod_plain, work / f"lod_{ratio_text}_baked.glb", options)
        lod_final = output_folder / f"{source.stem}_lod{ratio_text}.glb"
        report.step(f"lod {ratio_text}", gltf("compress", lod_baked, lod_final, options.textures, options.max_texture, toktx_path() or ""))
        lod_validation = gltf("validate", lod_final)
        report.gate(f"lod {ratio_text} validator errors", lod_validation["errors"], 0, lod_validation["errors"] == 0)
        distance = geometry("hausdorff", reference, lod_plain)
        report.step(f"lod {ratio_text} hausdorff", distance)
        report.gate(f"lod {ratio_text} hausdorff max %diag", distance["max_percent"], limit, distance["max_percent"] <= limit)
        if not options.remesh:
            lod_topology = geometry("topology", lod_plain)
            report.gate(f"lod {ratio_text} degenerate faces", lod_topology["degenerate_faces"], 0, lod_topology["degenerate_faces"] == 0)
            gate_non_manifold(report, f"lod {ratio_text} non-manifold edges", input_topology, lod_topology, thresholds)

    report.write()
    print(f"{'PASS' if report.passed() else 'FAIL'}: {output_folder / 'report.md'}")
    return 0 if report.passed() else 1


def run_compare(options):
    output_folder = Path(options.out).resolve() if options.out else Path(options.candidate).resolve().parent / "compare"
    work = output_folder / "stages"
    work.mkdir(parents=True, exist_ok=True)
    thresholds = thresholds_for(options.profile, options.threshold)
    report = Report(output_folder, options.profile, thresholds)
    reference = work / "reference.glb"
    candidate = work / "candidate.glb"
    gltf("plain", options.reference, reference)
    gltf("plain", options.candidate, candidate)
    validation = gltf("validate", options.candidate)
    report.step("validate candidate", validation)
    report.gate("validator errors (candidate)", validation["errors"], 0, validation["errors"] == 0)
    input_topology = geometry("topology", reference)
    report.step("topology reference", input_topology)
    gate_comparison(report, reference, candidate, thresholds, work, render=not options.no_render, input_topology=input_topology)
    report.write()
    print(f"{'PASS' if report.passed() else 'FAIL'}: {output_folder / 'report.md'}")
    return 0 if report.passed() else 1


def gate_shape(report, options, thresholds, low_path):
    """Topology numbers say nothing about shape: a torn QuadriFlow result passed them with a silhouette IoU of 0.46.
    So the low is always compared with the high it replaces."""
    if not options.high:
        report.gate("shape compared with the high (--high)", None, "given", False)
        return
    work = report.output_folder / "stages"
    work.mkdir(parents=True, exist_ok=True)
    low_gltf = work / "low.glb"
    if Path(low_path).suffix.lower() in (".glb", ".gltf"):
        gltf("plain", low_path, low_gltf)
    else:
        blender("blender_asset_gates.py", "export", low_path, low_gltf)
    reference = work / "high.glb"
    gltf("plain", options.high, reference)
    gate_comparison(report, reference, low_gltf, thresholds, work, render=not options.no_render, input_topology=geometry("topology", reference), appearance=False)


def gate_retopo(report, options, thresholds):
    measured = blender("blender_asset_gates.py", "retopo", options.input, threads=6)
    report.step("retopo measure", measured)
    gate_shape(report, options, thresholds, options.input)
    if measured["source_is_triangulated_format"]:
        report.note("glTF is always triangles: run the retopo gate on the .blend or the quad OBJ to measure quads")
    report.gate("n-gons", measured["ngons"], 0, measured["ngons"] == 0)
    if not options.high:
        report.gate("non-manifold edges", measured["non_manifold_edges"], 0, measured["non_manifold_edges"] == 0)
    report.gate("loose vertices and edges", measured["loose_vertices"] + measured["loose_edges"], 0, measured["loose_vertices"] + measured["loose_edges"] == 0)
    if options.deforms:
        report.gate("quad share (deforming mesh)", measured["quad_share"], f">= {options.quad_share}", measured["quad_share"] >= options.quad_share)
        report.gate("pole share (6+ edges)", measured["pole_share"], "<= 0.03", measured["pole_share"] <= 0.03)
    else:
        report.note("static asset: triangles and decimation are allowed, quad share not gated")
    if options.budget:
        report.gate("triangle budget", measured["triangle_equivalent"], options.budget, measured["triangle_equivalent"] <= options.budget)


def gate_uv(report, options):
    metrics = geometry("uv-metrics", options.input)
    report.step("uv metrics", metrics)
    layout = geometry("uv-layout", options.input, options.texture_size, options.padding)
    report.step("uv layout", layout)
    report.gate("primitives without UVs", metrics["primitives_without_uv"], 0, metrics["primitives_without_uv"] == 0)
    if options.uv_mode == "bake":
        report.gate("UV overlap % (bake set)", metrics["overlap_percent"], "<= 0.1", (metrics["overlap_percent"] or 0) <= 0.1)
        report.gate("texel density: area outside 0.5x..2x median %", layout["area_outside_half_to_double_density_percent"], "<= 10", layout["area_outside_half_to_double_density_percent"] <= 10)
    else:
        report.note("atlas mode: stacked and mirrored UVs and swatch-mapped faces are intended, overlap and density spread not gated")
    report.gate("flipped UV faces %", metrics["flipped_faces_percent"], "<= 1", (metrics["flipped_faces_percent"] or 0) <= 1)
    report.gate("area stretched beyond 0.5x..2x %", metrics["area_outside_half_to_double_percent"], "<= 10", (metrics["area_outside_half_to_double_percent"] or 0) <= 10)
    report.gate(f"island pairs closer than {options.padding} px at {options.texture_size}", layout["island_pairs_closer_than_padding"], 0, layout["island_pairs_closer_than_padding"] == 0)
    if options.texel_density:
        low, high = options.texel_density * 0.75, options.texel_density * 1.25
        median = layout["texel_density_median_px_per_m"]
        report.gate("texel density median px/m", median, f"{low:.0f}..{high:.0f}", low <= median <= high)
    if layout["uv_space_used_percent"] < 55:
        report.note(f"islands fill {layout['uv_space_used_percent']}% of the UV square: pack tighter (UVPackmaster, or pack with rotation) to raise texel density for free")
    if layout["texels_in_border_margin"]:
        report.note(f"{layout['texels_in_border_margin']} texels sit inside the {options.padding} px border margin")


def gate_bake(report, options, thresholds):
    if not options.high:
        raise ToolError("the bake gate needs --high <high-poly file>")
    work = report.output_folder / "stages"
    work.mkdir(parents=True, exist_ok=True)
    flat = work / "low_without_normal_map.glb"
    arguments = ["bake", options.input, options.high, flat] + ([options.ray_distance] if options.ray_distance else [])
    measured = blender("blender_asset_gates.py", *arguments, threads=6)
    report.step("bake measure", measured)
    report.gate("low mesh has a normal map", measured["has_normal_map"], True, measured["has_normal_map"])
    missing = measured["faces_without_high_surface"] / max(measured["face_count"], 1)
    report.gate("low faces with no high surface in reach %", round(100 * missing, 2), "<= 1", missing <= 0.01)
    ray_distance = measured.get("ray_distance")
    if ray_distance:
        report.gate("ray distance covers gap p99", ray_distance, f">= {measured['gap_p99']}", ray_distance >= measured["gap_p99"])
        report.gate("ray distance not past 10% of size (skew, wrong surface)", ray_distance, f"<= {round(measured['size'] * 0.1, 4)}", ray_distance <= measured["size"] * 0.1)
    else:
        report.gate("ray distance recorded (--ray-distance or the .blend bake settings)", None, f">= gap p99 {measured['gap_p99']}", False)
    if measured["has_normal_map"]:
        report.gate("normal texels pointing inward %", round(100 * measured.get("inward_texel_share", 0), 3), "<= 0.5", measured.get("inward_texel_share", 0) <= 0.005)
        report.gate("normal texels not unit length %", round(100 * measured.get("bad_length_texel_share", 0), 3), "<= 1", measured.get("bad_length_texel_share", 0) <= 0.01)
        if Path(options.input).suffix.lower() == ".blend":
            colour_space = measured["normal_map_colour_space"]
            report.gate("normal map colour space", colour_space, "Non-Color", colour_space in ("Non-Color", "Raw"))
    gltf_input = work / "low.glb"
    if Path(options.input).suffix.lower() == ".blend":
        blender("blender_asset_gates.py", "export", options.input, gltf_input)
    else:
        gltf("plain", options.input, gltf_input)
    reference = work / "high.glb"
    gltf("plain", options.high, reference)
    gate_comparison(report, reference, gltf_input, thresholds, work, render=not options.no_render)
    if options.no_render:
        report.note("--no-render: the render compare and the 'bake improves shading' gate did not run; never sign off a bake this way")
        return
    baked_views = report.data["steps"][-1]
    flat_views = geometry("compare-views", work / "views_reference", render_views(flat, work / "views_flat", work / "framing.json"), work / "sheet_flat.png")
    report.step("views without normal map", flat_views)
    baked_angle = baked_views["normal_angle_mean_deg_max"]
    flat_angle = flat_views["normal_angle_mean_deg_max"]
    report.gate("bake improves shading (normal angle mean, baked vs none)", baked_angle, f"<= {round(flat_angle * 0.95, 2)}", baked_angle <= flat_angle * 0.95)


def render_views(path, folder, framing):
    blender("blender_views.py", path, folder, framing, 512, render=True)
    return folder


def gate_texture(report, options):
    measured = blender("blender_asset_gates.py", "texture", options.input, threads=6)
    report.step("texture measure", measured)
    required = [name.strip() for name in options.channels.split(",") if name.strip()]
    if not measured["colour_space_checkable"]:
        report.note("glTF fixes colour space by slot: colour space is NOT checked here, run this gate on the .blend")
    report.gate("materials found", len(measured["materials"]), ">= 1", len(measured["materials"]) >= 1)
    for material in measured["materials"]:
        name = material["material"]
        if material.get("error"):
            report.gate(f"{name}: {material['error']}", None, "Principled BSDF", False)
            continue
        channels = material["channels"]
        missing = [channel for channel in required if channel not in channels]
        report.gate(f"{name}: required channels", ",".join(channels) or "none", ",".join(required), not missing)
        for channel, info in channels.items():
            width, height = info["size"]
            power_of_two = width > 0 and height > 0 and width & (width - 1) == 0 and height & (height - 1) == 0
            report.gate(f"{name} {channel}: size", f"{width}x{height}", f"power of two, <= {options.max_texture}", power_of_two and max(width, height) <= options.max_texture)
            if info["colour_space_ok"] is not None:
                report.gate(f"{name} {channel}: colour space", info["colour_space"], info["expected"], info["colour_space_ok"])
            if info["flat"]:
                report.note(f"{name} {channel}: image is one flat value; use a number instead and save the memory")


def gate_rig(report, options):
    measured = blender("blender_asset_gates.py", "rig", options.input, threads=6)
    report.step("rig measure", {key: value for key, value in measured.items() if key != "bends"})
    report.gate("armature present", measured["armatures"], ">= 1", measured["armatures"] >= 1)
    report.gate("skinned meshes", measured["skinned_objects"], ">= 1", measured["skinned_objects"] >= 1)
    report.gate("unweighted vertices", measured["unweighted_vertices"], 0, measured["unweighted_vertices"] == 0)
    report.gate("vertices with more than 4 influences", measured["over_four_influences"], 0, measured["over_four_influences"] == 0)
    report.gate("vertices with weights not summing to 1", measured["unnormalised_vertices"], 0, measured["unnormalised_vertices"] == 0)
    if measured["deform_bones_without_weights_count"]:
        report.note(f"{measured['deform_bones_without_weights_count']} deform bones carry no weights (end and twist bones are fine): {', '.join(measured['deform_bones_without_weights'][:8])}")
    report.gate("bend test bones found (elbows, knees, spine)", len(measured["bends"]), ">= 1", len(measured["bends"]) >= 1)
    for bend in measured["bends"]:
        report.step(f"bend {bend['bone']}", bend)
        report.gate(f"bend {bend['bone']} {measured['bend_degrees']:.0f} deg: collapsed faces %", round(100 * bend["collapsed_share"], 3), "<= 2", bend["collapsed_share"] <= 0.02)
        report.gate(f"bend {bend['bone']}: stray vertices (move, but far from every bent bone)", bend["jumped_vertices"], 0, bend["jumped_vertices"] == 0)


def run_gate(options):
    source = Path(options.input).resolve()
    output_folder = Path(options.out).resolve() if options.out else source.parent / f"{source.stem}.gate-{options.stage}"
    output_folder.mkdir(parents=True, exist_ok=True)
    thresholds = thresholds_for(options.profile, options.threshold)
    if options.object:
        os.environ["MESH_PREP_GATE_OBJECTS"] = options.object
    report = Report(output_folder, f"{options.stage} gate, {options.profile}", thresholds)
    if options.stage == "retopo":
        gate_retopo(report, options, thresholds)
    elif options.stage == "uv":
        gate_uv(report, options)
    elif options.stage == "bake":
        gate_bake(report, options, thresholds)
    elif options.stage == "texture":
        gate_texture(report, options)
    elif options.stage == "rig":
        gate_rig(report, options)
    report.write()
    print(f"{'PASS' if report.passed() else 'FAIL'}: {output_folder / 'report.md'}")
    return 0 if report.passed() else 1


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("input")
    run.add_argument("--out")
    run.add_argument("--profile", choices=list(PROFILES), default="prop")
    run.add_argument("--no-repair", action="store_true")
    run.add_argument("--watertight", action="store_true")
    run.add_argument("--remesh", choices=["quadriflow", "qremeshify"])
    run.add_argument("--faces", type=int, default=5000)
    run.add_argument("--uv", choices=["auto", "off"], default="auto")
    run.add_argument("--simplify", type=float)
    run.add_argument("--error", type=float, default=0.01)
    run.add_argument("--lod")
    run.add_argument("--bake", choices=["auto", "on", "off"], default="auto")
    run.add_argument("--bake-size", type=int, default=1024)
    run.add_argument("--textures", choices=["keep", "webp", "ktx2"], default="keep")
    run.add_argument("--max-texture", type=int, default=2048)
    run.add_argument("--no-compress", action="store_true")
    run.add_argument("--budget", type=int)
    run.add_argument("--threshold", action="append")
    run.add_argument("--no-render", action="store_true")
    run.add_argument("--force", action="store_true")
    compare = commands.add_parser("compare")
    compare.add_argument("reference")
    compare.add_argument("candidate")
    compare.add_argument("--out")
    compare.add_argument("--profile", choices=list(PROFILES), default="prop")
    compare.add_argument("--threshold", action="append")
    compare.add_argument("--no-render", action="store_true")
    gate = commands.add_parser("gate")
    gate.add_argument("stage", choices=["retopo", "uv", "bake", "texture", "rig"])
    gate.add_argument("input")
    gate.add_argument("--high")
    gate.add_argument("--out")
    gate.add_argument("--profile", choices=list(PROFILES), default="prop")
    gate.add_argument("--threshold", action="append")
    gate.add_argument("--deforms", action="store_true")
    gate.add_argument("--quad-share", type=float, default=0.9)
    gate.add_argument("--budget", type=int)
    gate.add_argument("--uv-mode", choices=["bake", "atlas"], default="bake")
    gate.add_argument("--texture-size", type=int, default=2048)
    gate.add_argument("--padding", type=int, default=8)
    gate.add_argument("--texel-density", type=float)
    gate.add_argument("--ray-distance", type=float)
    gate.add_argument("--channels", default="Base Color,Normal,Roughness")
    gate.add_argument("--max-texture", type=int, default=4096)
    gate.add_argument("--no-render", action="store_true")
    gate.add_argument("--object", help="comma list of mesh objects to gate in a .blend (e.g. the low poly); default all")
    return parser


def main():
    options = build_parser().parse_args()
    try:
        if options.command == "run":
            code = run_pipeline(options)
        elif options.command == "gate":
            code = run_gate(options)
        else:
            code = run_compare(options)
    except ToolError as error:
        print(f"mesh_prep error: {error}", file=sys.stderr)
        code = 2
    raise SystemExit(code)


if __name__ == "__main__":
    main()
