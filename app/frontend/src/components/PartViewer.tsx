import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";
import styles from "./PartViewer.module.css";

type PartViewerProps = {
  url: string; // a binary STL in the table frame (z up, resting on z = 0), e.g. /api/parts/{id}/mesh
  label: string; // the text alternative, e.g. "Vial cap, standing on its end"
  mode?: "interactive" | "thumbnail"; // thumbnail: a still image, for grids of parts and the wizard's pose choices
  height?: number; // px, interactive only; a thumbnail is 16:10 at the width it's given
  arrows?: GraspArrow[]; // interactive only: grasp directions drawn over the part
  markers?: { point: readonly [number, number, number] }[]; // interactive only: picked points, e.g. two faces
  onPick?: (pick: PartPick) => void; // interactive only: a click on the part (not a drag), raycast in the table frame
};

/** A jaw-closing direction over the part: two arrows coming in from either side, `angle_deg` from +x through
 *  `centre_mm`, in the table frame. */
export type GraspArrow = {
  angle_deg: number;
  centre_mm: readonly [number, number];
  tone: "acc" | "active" | "faint"; // acc: the chosen one; faint: other candidates; active: a manual choice
};

/** A point clicked on the part, and the outward normal of the face it's on, in the table frame (mm). */
export type PartPick = { point: [number, number, number]; normal: [number, number, number] };

// Thumbnails are rendered at this size by one shared offscreen renderer, then shown as images: a grid of parts never
// holds more than one WebGL context, however many cards it has (browsers cap them at about 16).
const THUMB_WIDTH = 640;
const THUMB_HEIGHT = 400;

/** A part in 3D: orbit it in the interactive mode, or a still in the thumbnail mode. The one viewer for parts; the
 *  wizard's poses, grasp arrows and finger previews build on it. Colours come from the design tokens. */
export function PartViewer({ url, label, mode = "interactive", height = 360, arrows, markers, onPick }: PartViewerProps) {
  return mode === "thumbnail" ? (
    <Thumbnail url={url} label={label} />
  ) : (
    <Interactive url={url} label={label} height={height} arrows={arrows} markers={markers} onPick={onPick} />
  );
}

type Stage = { render: () => void; overlay: THREE.Group; radius: number; top: number };

function Interactive({
  url,
  label,
  height,
  arrows,
  markers,
  onPick,
}: {
  url: string;
  label: string;
  height: number;
  arrows?: GraspArrow[];
  markers?: { point: readonly [number, number, number] }[];
  onPick?: (pick: PartPick) => void;
}) {
  const mesh = useQuery(meshQuery(url));
  const frame = useRef<HTMLDivElement>(null);
  const [noWebGl, setNoWebGl] = useState(false);
  const [stage, setStage] = useState<Stage | null>(null);
  const pick = useRef(onPick);
  useEffect(() => {
    pick.current = onPick;
  }, [onPick]);

  useEffect(() => {
    const container = frame.current;
    if (!container || !mesh.data) return;
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

    const view = buildScene(mesh.data.clone()); // a copy: the cached geometry is shared with the thumbnail
    const controls = new OrbitControls(view.camera, renderer.domElement);
    controls.target.copy(view.target);
    controls.update();
    const render = () => renderer.render(view.scene, view.camera);
    controls.addEventListener("change", render);
    const overlay = new THREE.Group();
    view.scene.add(overlay);
    setStage({ render, overlay, radius: view.radius, top: view.top });

    // A click picks a point on the part; a drag only turns the view.
    let down: { x: number; y: number } | null = null;
    const onDown = (event: PointerEvent) => (down = { x: event.clientX, y: event.clientY });
    const onUp = (event: PointerEvent) => {
      const moved = down ? Math.hypot(event.clientX - down.x, event.clientY - down.y) : Infinity;
      down = null;
      if (moved > 4 || !pick.current) return;
      const rect = renderer.domElement.getBoundingClientRect();
      const pointer = new THREE.Vector2(
        ((event.clientX - rect.left) / rect.width) * 2 - 1,
        -((event.clientY - rect.top) / rect.height) * 2 + 1,
      );
      const ray = new THREE.Raycaster();
      ray.setFromCamera(pointer, view.camera);
      const hit = ray.intersectObject(view.part)[0];
      if (!hit?.face) return;
      const n = hit.face.normal;
      pick.current({ point: [hit.point.x, hit.point.y, hit.point.z], normal: [n.x, n.y, n.z] });
    };
    renderer.domElement.addEventListener("pointerdown", onDown);
    renderer.domElement.addEventListener("pointerup", onUp);

    const resize = () => {
      const width = container.clientWidth;
      renderer.setSize(width, height, false);
      view.camera.aspect = width / height;
      view.camera.updateProjectionMatrix();
      render();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    resize();

    return () => {
      setStage(null);
      renderer.domElement.removeEventListener("pointerdown", onDown);
      renderer.domElement.removeEventListener("pointerup", onUp);
      clearOverlay(overlay);
      observer.disconnect();
      controls.dispose();
      view.dispose();
      renderer.dispose();
      renderer.domElement.remove();
    };
  }, [mesh.data, height]);

  // The arrows and markers sit in their own group, redrawn without rebuilding the scene or moving the camera. Keyed by
  // value, so a parent passing fresh arrays each render doesn't redraw them.
  const overlayKey = JSON.stringify([arrows ?? [], markers ?? []]);
  useEffect(() => {
    if (!stage) return;
    const [arrowList, markerList] = JSON.parse(overlayKey) as [GraspArrow[], { point: [number, number, number] }[]];
    clearOverlay(stage.overlay);
    for (const arrow of arrowList) stage.overlay.add(arrowObject(arrow, stage.radius, stage.top));
    for (const marker of markerList) {
      const dot = new THREE.Mesh(
        new THREE.SphereGeometry(Math.max(stage.radius * 0.035, 0.3), 16, 12),
        new THREE.MeshBasicMaterial({ color: token("--active"), depthTest: false }),
      );
      dot.position.set(...marker.point);
      dot.renderOrder = 10;
      stage.overlay.add(dot);
    }
    stage.render();
  }, [stage, overlayKey]);

  return (
    <div className={styles.viewer}>
      <div ref={frame} className={styles.frame} style={{ height }} role="img" aria-label={label}>
        {mesh.isPending && <p className={styles.status}>Loading the 3D view</p>}
        {mesh.isError && <p className={styles.status}>Couldn't load the 3D view: {mesh.error.message}</p>}
        {noWebGl && <p className={styles.status}>The 3D view needs WebGL, which this browser has turned off.</p>}
      </div>
      <p className={styles.caption}>
        Drag to turn, scroll to zoom, right-drag to move.{onPick ? " Click the part to pick a face." : ""}
      </p>
    </div>
  );
}

function Thumbnail({ url, label }: { url: string; label: string }) {
  const queryClient = useQueryClient();
  const image = useQuery({
    queryKey: ["mesh", url, "thumbnail"],
    queryFn: async () => renderThumbnail(await queryClient.fetchQuery(meshQuery(url))),
    staleTime: Infinity,
  });
  return (
    <div className={styles.thumb}>
      {image.data ? (
        <img src={image.data} alt={label} className={styles.image} />
      ) : (
        <p className={styles.status}>{image.isError ? "No 3D preview" : "Loading the 3D view"}</p>
      )}
    </div>
  );
}

/** The STL, fetched and parsed. Cached per URL, so a part's thumbnail and its full view load it once. */
function meshQuery(url: string) {
  return {
    queryKey: ["mesh", url],
    queryFn: async () => {
      const response = await fetch(url);
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      return new STLLoader().parse(await response.arrayBuffer());
    },
    staleTime: Infinity,
  };
}

let sharedRenderer: THREE.WebGLRenderer | null = null;

function renderThumbnail(geometry: THREE.BufferGeometry): string {
  sharedRenderer ??= new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
  sharedRenderer.setPixelRatio(1);
  sharedRenderer.setSize(THUMB_WIDTH, THUMB_HEIGHT, false);
  const view = buildScene(geometry.clone());
  view.camera.aspect = THUMB_WIDTH / THUMB_HEIGHT;
  view.camera.updateProjectionMatrix();
  sharedRenderer.render(view.scene, view.camera);
  const image = sharedRenderer.domElement.toDataURL("image/png");
  view.dispose();
  return image;
}

/** The part on a grid floor, lit, with its edges drawn, and a camera framing it from the front right, above. */
function buildScene(source: THREE.BufferGeometry) {
  const geometry = source;
  geometry.computeVertexNormals();
  geometry.computeBoundingBox();
  const box = geometry.boundingBox!;
  const target = box.getCenter(new THREE.Vector3());
  const radius = Math.max(box.getBoundingSphere(new THREE.Sphere()).radius, 1);

  const scene = new THREE.Scene();
  const material = new THREE.MeshStandardMaterial({ color: token("--mute"), roughness: 0.55, metalness: 0.1 });
  const part = new THREE.Mesh(geometry, material);
  scene.add(part);
  const edges = new THREE.EdgesGeometry(geometry, 30);
  const edgeMaterial = new THREE.LineBasicMaterial({ color: token("--surface-3") });
  scene.add(new THREE.LineSegments(edges, edgeMaterial));

  // The table: a grid on z = 0, a few times the part's size, one line every tenth of it.
  const size = niceSize(radius * 4);
  const grid = new THREE.GridHelper(size, 10, token("--line-strong"), token("--line"));
  grid.rotation.x = Math.PI / 2;
  grid.position.set(target.x, target.y, 0);
  scene.add(grid);

  scene.add(new THREE.HemisphereLight(token("--ink"), token("--bg"), 1.4));
  const sun = new THREE.DirectionalLight(token("--ink"), 1.6);
  sun.position.set(radius, -radius * 1.5, radius * 3);
  scene.add(sun);

  const camera = new THREE.PerspectiveCamera(35, 1, radius / 100, radius * 100);
  camera.up.set(0, 0, 1);
  const distance = (radius / Math.sin(THREE.MathUtils.degToRad(35 / 2))) * 1.1;
  camera.position.copy(target).add(new THREE.Vector3(0.9, -1.3, 0.9).normalize().multiplyScalar(distance));
  camera.lookAt(target);

  const dispose = () => {
    geometry.dispose();
    material.dispose();
    edges.dispose();
    edgeMaterial.dispose();
    grid.dispose();
  };
  return { scene, camera, target, part, radius, top: box.max.z, dispose };
}

/** Two arrows coming in from either side of the centre along the closing direction, like the jaws, drawn over the
 *  part so it never hides them. */
function arrowObject(arrow: GraspArrow, radius: number, top: number): THREE.Group {
  const group = new THREE.Group();
  const faint = arrow.tone === "faint";
  const material = new THREE.MeshBasicMaterial({
    color: token(arrow.tone === "acc" ? "--acc" : arrow.tone === "active" ? "--active" : "--faint"),
    depthTest: false,
    transparent: faint,
    opacity: faint ? 0.7 : 1,
  });
  const angle = THREE.MathUtils.degToRad(arrow.angle_deg);
  const direction = new THREE.Vector3(Math.cos(angle), Math.sin(angle), 0);
  const centre = new THREE.Vector3(arrow.centre_mm[0], arrow.centre_mm[1], top + radius * 0.05);
  const head = radius * 0.16;
  const shaft = radius * (faint ? 0.015 : 0.025);
  for (const side of [1, -1]) {
    const inward = direction.clone().multiplyScalar(-side);
    const start = centre.clone().addScaledVector(direction, side * radius * 1.25);
    const tip = centre.clone().addScaledVector(direction, side * radius * 0.25);
    const length = start.distanceTo(tip) - head;
    const rod = new THREE.Mesh(new THREE.CylinderGeometry(shaft, shaft, length, 8), material);
    rod.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), inward);
    rod.position.copy(start).addScaledVector(inward, length / 2);
    const cone = new THREE.Mesh(new THREE.ConeGeometry(head * 0.45, head, 16), material);
    cone.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), inward);
    cone.position.copy(tip).addScaledVector(inward, -head / 2);
    for (const object of [rod, cone]) {
      object.renderOrder = 10;
      group.add(object);
    }
  }
  return group;
}

function clearOverlay(overlay: THREE.Group) {
  const materials = new Set<THREE.Material>();
  overlay.traverse((object) => {
    if (object instanceof THREE.Mesh) {
      object.geometry.dispose();
      materials.add(object.material as THREE.Material);
    }
  });
  materials.forEach((material) => material.dispose());
  overlay.clear();
}

/** A design token's colour, read from the page, so the 3D view follows tokens.css like everything else. */
export function token(name: string): THREE.Color {
  return new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue(name).trim());
}

/** A round grid size: 1, 2 or 5 times a power of ten. */
export function niceSize(value: number): number {
  const power = 10 ** Math.floor(Math.log10(value));
  return [1, 2, 5, 10].map((step) => step * power).find((size) => size >= value) ?? value;
}
