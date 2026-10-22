import type { Schemas } from "../../backend/client";

export type Results = Schemas["ResultsView"];

/** A grasp picked for an Isaac Sim clip: a final design at one offset, e.g. a dot clicked on the held map. */
export type ClipPick = { design: string; offset: { dx: number; dy: number; yaw_deg: number } };
