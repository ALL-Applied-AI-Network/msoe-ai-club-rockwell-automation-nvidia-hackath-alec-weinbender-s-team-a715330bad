"""Bridges to the backend AI models. Swap these in via environment variables:

  LLM_BACKEND=mock|anthropic|http   (http: POST LLM_URL  {part,task,k} -> {suggestions:[{template,params,rationale}]})
  SIM_BACKEND=mock|http             (http: POST SIM_URL   {part,design,offsets:[...]} -> {successes:[bool,...]})

The mock versions let the whole UI/queue/storage flow run end to end before the
real LLM and FANUC ER-4iA digital twin are wired up.
"""
import json, math, os, random, urllib.request, zlib

# ---- design space --------------------------------------------------------
SPACE = {
    "flat_pad": {"finger_length": (15, 60), "pad_width": (8, 40), "pad_thickness": (2, 10), "pad_friction_texture": (0, 1)},
    "v_groove": {"finger_length": (15, 60), "groove_angle": (60, 140), "groove_depth": (2, 20), "pad_width": (8, 40)},
    "pocket":   {"finger_length": (15, 60), "pocket_clearance": (0, 6), "pocket_depth": (2, 25), "pocket_radius_scale": (0.8, 1.2)},
}
TEMPLATES = list(SPACE)

def clamp_design(template, params):
    out = {}
    for k, (lo, hi) in SPACE[template].items():
        v = params.get(k, (lo + hi) / 2)
        out[k] = min(hi, max(lo, float(v)))
    return out

def _post(url, payload, timeout=600):
    req = urllib.request.Request(url, json.dumps(payload).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())

# ---- LLM step ------------------------------------------------------------
PROMPT_VERSION = "v1"
PROMPT = """You design 3D-printed parallel-jaw gripper fingers for a SCHUNK gripper.
Part (mm): {part}
Task: {task}
Choose {k} diverse starting designs. Templates and parameter ranges:
{space}
Reply with ONLY JSON: {{"suggestions":[{{"template":..., "params":{{...}}, "rationale":"..."}}]}}"""

def llm_suggest(part, task, k):
    """Returns (list of {template, params, rationale}, source, model, raw_text)."""
    backend = os.environ.get("LLM_BACKEND") or ("anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "mock")
    if backend == "anthropic":
        import anthropic
        model = os.environ.get("LLM_MODEL", "claude-sonnet-5-5")
        msg = anthropic.Anthropic().messages.create(
            model=model, max_tokens=2000,
            messages=[{"role": "user", "content": PROMPT.format(part=json.dumps(part), task=task, k=k, space=json.dumps(SPACE))}])
        raw = msg.content[0].text
        data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
        return data["suggestions"][:k], "anthropic", model, raw
    if backend == "http":
        data = _post(os.environ["LLM_URL"], {"part": part, "task": task, "k": k})
        return data["suggestions"][:k], "http", data.get("model", "custom"), json.dumps(data)
    # mock: deliberately noisy so there are good AND bad suggestions to learn from
    rng = random.Random(zlib.crc32((json.dumps(part, sort_keys=True) + task).encode()))
    d = part.get("diameter_mm", 40)
    out = []
    for i in range(k):
        t = TEMPLATES[i % 3]
        p = {n: rng.uniform(lo, hi) for n, (lo, hi) in SPACE[t].items()}
        if t == "pocket": p["pocket_radius_scale"] = rng.uniform(0.9, 1.1)
        out.append({"template": t, "params": p, "rationale": f"mock heuristic for ~{d}mm part"})
    return out, "mock", "mock", json.dumps(out)

# ---- simulator -----------------------------------------------------------
def offset_for(i, sigma_mm, sigma_deg, seed):
    """Deterministic per-grasp perturbation => all designs face the same
    'camera errors' (common random numbers => fairer, lower-variance comparison)."""
    r = random.Random(seed * 100003 + i)
    return {"dx": r.gauss(0, sigma_mm), "dy": r.gauss(0, sigma_mm), "yaw_deg": r.gauss(0, sigma_deg)}

def sim_batch(part, design, offsets):
    """Many grasps -> list[bool]. With SIM_BACKEND=http the whole batch is ONE request to the Isaac Sim
    service (e.g. on a Brev GPU), so network/startup overhead is paid once per batch, not per grasp."""
    if os.environ.get("SIM_BACKEND") == "http":
        return [bool(x) for x in _post(os.environ["SIM_URL"], {"part": part, "design": design, "offsets": offsets})["successes"]]
    return [sim_grasp(part, design, o) for o in offsets]

def sim_grasp(part, design, offset):
    """One mock grasp -> bool (stand-in for the FANUC ER-4iA digital twin)."""
    t, p = design["template"], design["params"]
    d = part.get("diameter_mm", 40)
    err = math.hypot(offset["dx"], offset["dy"])
    if t == "flat_pad":
        base = 0.62 + 0.25 * p["pad_friction_texture"] + 0.01 * min(p["pad_width"], d) / 4
        tol = 4 + p["pad_width"] / 6
    elif t == "v_groove":
        ang_fit = math.exp(-((p["groove_angle"] - 95) / 30) ** 2)
        base = 0.55 + 0.4 * ang_fit * min(1, p["groove_depth"] / (0.25 * d))
        tol = 6 + p["groove_depth"] / 2
    else:
        clear_fit = math.exp(-((p["pocket_clearance"] - 1.5) / 2.5) ** 2)
        base = 0.5 + 0.35 * clear_fit * math.exp(-((p["pocket_radius_scale"] - 1) / 0.15) ** 2) + 0.01 * min(p["pocket_depth"], d / 2)
        tol = 3 + p["pocket_depth"] / 4 + p["pocket_clearance"]
    reach = min(1.0, p["finger_length"] / (0.6 * d + 5))
    prob = base * reach * math.exp(-((err / tol) ** 2)) * math.exp(-(offset["yaw_deg"] / 25) ** 2)
    return random.random() < max(0.0, min(0.99, prob))

# ---- outputs -------------------------------------------------------------
def grasp_pose(part, design):
    p = design["params"]
    return {"frame": "part_centroid", "approach_axis": "-Z",
            "standoff_mm": round(p["finger_length"] * 0.5, 1), "tcp_offset_mm": [0, 0, round(p["finger_length"], 1)],
            "gripper_opening_mm": round(part.get("diameter_mm", 40) + 6, 1)}

def make_scad(part, design):
    """Printable CAD placeholder: parametric OpenSCAD. Replace with real CAD kernel (CadQuery) export."""
    t, p = design["template"], design["params"]
    L = p["finger_length"]; W = p.get("pad_width", 20); T = p.get("pad_thickness", 6)
    body = f"cube([{W},{T + 10},{L}]);"
    if t == "v_groove":
        body = f"difference(){{cube([{W},20,{L}]); translate([{W/2},20,{L*0.7}]) rotate([90,0,0]) rotate([0,0,45]) scale([1,{math.tan(math.radians(p['groove_angle']/2)):.3f},1]) cylinder(h={p['groove_depth']*2},r1=0,r2={p['groove_depth']*2},center=true);}}"
    elif t == "pocket":
        r = part.get("diameter_mm", 40) / 2 * p["pocket_radius_scale"] + p["pocket_clearance"]
        body = f"difference(){{cube([{max(W,2*r+6)},{p['pocket_depth']+6},{L}]); translate([{max(W,2*r+6)/2},{p['pocket_depth']+6},{L*0.7}]) sphere(r={r:.2f});}}"
    return f"// {t} finger  params={json.dumps(p)}\n{body}\n"
