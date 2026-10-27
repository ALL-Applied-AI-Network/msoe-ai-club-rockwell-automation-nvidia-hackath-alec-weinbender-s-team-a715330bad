import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import type { Schemas } from "../backend/client";
import { useTheme } from "../theme";
import { niceSize, token } from "./PartViewer";
import styles from "./FingerViewer.module.css";

type Piece = Schemas["Piece"];
type Part = Schemas["Part"];

/** One finger's convex pieces, as the API sends them (the same solids the sim runs and the STEP exports). */
export type FingerShape = {
  key: string;
  pieces: Piece[];
  tone: "finger" | "min" | "max"; // finger: solid green; min and max: see-through ghosts for a parameter's two ends
  mirrored?: boolean; // also draw its mirror across the jaws' centre plane (x = 0): the right finger, for a preview
};

type FingerViewerProps = {
  part?: Part; // the part as the gripper meets it, in the grasp frame
  fingers: FingerShape[]; // pass a stable array (useMemo or query data): a new one rebuilds the scene
  label: string; // the text alternative, e.g. "D1's fingers closed on the vial cap"
  height?: number; // px
  frameKey?: string; // the camera re-frames when it changes (another design); otherwise it stays where the user left it
};

/** Fingers on the part in 3D, in the grasp frame: x along the jaws' closing direction, z up from the table. The wizard's
 *  ghost previews and the results page's best finger. Colours come from the design tokens. */
export function FingerViewer({ part, fingers, label, height = 360, frameKey = "" }: FingerViewerProps) {
  const frame = useRef<HTMLDivElement>(null);
  const [stage, setStage] = useState<Stage | null>(null);
  const [noWebGl, setNoWebGl] = useState(false);
  const framed = useRef<string | null>(null);
  const theme = useTheme(); // colours are read when the scene is built, so a new theme rebuilds it

  // The renderer, camera and controls live as long as the viewer; the content below swaps in and out.
  useEffect(() => {
    const container = frame.current;
    if (!container) return;
    let renderer: THREE.WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    } catch {
      setNoWebGl(true);
      return;
    }
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.domElement.className = styles.canvas;
    container.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    scene.add(new THREE.HemisphereLight(token("--viewer-light"), token("--bg"), 1.4));
    const sun = new THREE.DirectionalLight(token("--viewer-light"), 1.6);
    sun.position.set(1, -1.5, 3);
    scene.add(sun);
    const content = new THREE.Group();
    scene.add(content);

    const camera = new THREE.PerspectiveCamera(35, 1, 0.1, 10_000);
    camera.up.set(0, 0, 1);
    const controls = new OrbitControls(camera, renderer.domElement);
    const render = () => renderer.render(scene, camera);
    controls.addEventListener("change", render);

    const resize = () => {
      const width = container.clientWidth;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
      render();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    resize();
    setStage({ content, camera, controls, render });

    return () => {
      setStage(null);
      framed.current = null;
      observer.disconnect();
      clear(content);
      controls.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [height, theme]);

  useEffect(() => {
    if (!stage) return;
    clear(stage.content);
    if (part) stage.content.add(partObject(part));
    for (const finger of fingers) {
      stage.content.add(fingerObject(finger.pieces, finger.tone, false));
      if (finger.mirrored) stage.content.add(fingerObject(finger.pieces, finger.tone, true));
    }
    const box = new THREE.Box3().setFromObject(stage.content);
    if (!box.isEmpty()) {
      stage.content.add(floor(box));
      if (framed.current !== frameKey) {
        frameCamera(stage, box);
        framed.current = frameKey;
      }
    }
    stage.render();
  }, [stage, part, fingers, frameKey]);

  return (
    <div className={styles.viewer}>
      <div ref={frame} className={styles.frame} style={{ height }} role="img" aria-label={label}>
        {noWebGl && <p className={styles.status}>The 3D view needs WebGL, which this browser has turned off.</p>}
      </div>
      <p className={styles.caption}>Drag to turn, scroll to zoom, right-drag to move.</p>
    </div>
  );
}

type Stage = { content: THREE.Group; camera: THREE.PerspectiveCamera; controls: OrbitControls; render: () => void };

/** Looks at the fingers from in front, a little to the right and above, with the jaws closing left to right. */
function frameCamera({ camera, controls }: Stage, box: THREE.Box3) {
  const target = box.getCenter(new THREE.Vector3());
  const radius = Math.max(box.getBoundingSphere(new THREE.Sphere()).radius, 1);
  const distance = (radius / Math.sin(THREE.MathUtils.degToRad(35 / 2))) * 1.05;
  camera.near = radius / 100;
  camera.far = radius * 100;
  camera.position.copy(target).add(new THREE.Vector3(0.45, -1.3, 0.75).normalize().multiplyScalar(distance));
  camera.updateProjectionMatrix();
  controls.target.copy(target);
  controls.update();
}

/** Convex pieces as one solid, flat-shaded. Mirroring negates x and flips each triangle, so its faces still point out. */
function piecesGeometry(pieces: Piece[], mirrored: boolean): THREE.BufferGeometry {
  const positions: number[] = [];
  for (const piece of pieces) {
    for (const triangle of piece.triangles) {
      const corners = mirrored ? [triangle[0], triangle[2], triangle[1]] : triangle;
      for (const index of corners) {
        const [x, y, z] = piece.points[index];
        positions.push(mirrored ? -x : x, y, z);
      }
    }
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.Float32BufferAttribute(positions, 3));
  geometry.computeVertexNormals();
  return geometry;
}

function fingerObject(pieces: Piece[], tone: FingerShape["tone"], mirrored: boolean): THREE.Group {
  const geometry = piecesGeometry(pieces, mirrored);
  const ghost = tone !== "finger";
  const color = token(tone === "min" ? "--active" : tone === "max" ? "--warn" : "--viewer-finger");
  const material = new THREE.MeshStandardMaterial({
    color,
    roughness: 0.6,
    transparent: ghost,
    opacity: ghost ? 0.35 : 1,
    depthWrite: !ghost,
  });
  const group = new THREE.Group();
  group.add(new THREE.Mesh(geometry, material));
  group.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 20), new THREE.LineBasicMaterial({ color })));
  return group;
}

/** The part as the sim sees it: a cylinder on its end or lying down, a box, or a mesh of convex pieces. */
function partObject(part: Part): THREE.Group {
  let geometry: THREE.BufferGeometry;
  const r = part.diameter_mm / 2;
  if (part.shape === "box") {
    geometry = new THREE.BoxGeometry(part.width_mm, part.depth_mm, part.height_mm).translate(0, 0, part.height_mm / 2);
  } else if (part.shape === "mesh") {
    geometry = piecesGeometry(part.pieces ?? [], false);
  } else {
    geometry = new THREE.CylinderGeometry(r, r, part.length_mm, 48); // along y
    if (part.axis === "z") geometry.rotateX(Math.PI / 2).translate(0, 0, part.length_mm / 2);
    else if (part.axis === "x") geometry.rotateZ(Math.PI / 2).translate(0, 0, r);
    else geometry.translate(0, 0, r);
  }
  const group = new THREE.Group();
  group.add(new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({ color: token("--viewer-part"), roughness: 0.55 })));
  group.add(new THREE.LineSegments(new THREE.EdgesGeometry(geometry, 30), new THREE.LineBasicMaterial({ color: token("--viewer-edge") })));
  return group;
}

/** The table: a grid on z = 0 under everything. */
function floor(box: THREE.Box3): THREE.GridHelper {
  const size = niceSize(Math.max(box.max.x - box.min.x, box.max.y - box.min.y) * 1.6);
  const grid = new THREE.GridHelper(size, 10, token("--line-strong"), token("--line"));
  grid.rotation.x = Math.PI / 2;
  const centre = box.getCenter(new THREE.Vector3());
  grid.position.set(centre.x, centre.y, 0);
  return grid;
}

function clear(group: THREE.Group) {
  group.traverse((object) => {
    if (object instanceof THREE.Mesh || object instanceof THREE.LineSegments) {
      object.geometry.dispose();
      const materials = Array.isArray(object.material) ? object.material : [object.material];
      materials.forEach((material: THREE.Material) => material.dispose());
    }
  });
  group.clear();
}
