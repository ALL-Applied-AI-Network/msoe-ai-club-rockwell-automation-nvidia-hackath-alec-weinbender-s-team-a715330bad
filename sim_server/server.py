"""Simulation service to run next to Isaac Sim (e.g. headless on a Brev GPU instance).

    pip install fastapi uvicorn
    uvicorn sim_server.server:app --host 0.0.0.0 --port 9000
Then on the web-app machine:   SIM_BACKEND=http  SIM_URL=http://<instance>:9000/evaluate
(Reach the instance via a Brev Secure Link or `brev port-forward`; don't expose it publicly.)

Contract: POST {part, design:{template,params}, offsets:[{dx,dy,yaw_deg},...]} -> {successes:[bool,...]}
"""
from fastapi import FastAPI

app = FastAPI()

def load_scene():
    """TODO: start Isaac Sim headless (SimulationApp({"headless": True})), load fanuc_er4ia_sim from the
    supplied digital twin, and keep it loaded between requests - startup is the expensive part."""
    return None

SCENE = load_scene()

def run_grasps(scene, part, design, offsets):
    """TODO per offset: (1) build finger geometry from design (template+params) and swap it onto the SCHUNK gripper,
    (2) spawn the part, shifted by (dx, dy, yaw) from where the 'camera' believes it is, (3) execute the grasp pose
    the design implies, lift, move, and check the part is still held / reached the target.
    Run offsets as parallel environments (Isaac Lab-style) for GPU throughput. Return one bool per offset."""
    raise NotImplementedError("wire up the FANUC ER-4iA digital twin here")

@app.post("/evaluate")
def evaluate(req: dict):
    return {"successes": run_grasps(SCENE, req["part"], req["design"], req["offsets"])}
