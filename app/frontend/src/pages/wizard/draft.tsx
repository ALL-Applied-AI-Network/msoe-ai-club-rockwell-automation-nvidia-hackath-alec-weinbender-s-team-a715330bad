import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { api, unwrapAs, type Schemas } from "../../backend/client";

// The new-experiment wizard's draft: the job spec as the user fills it in, step by step (docs/notes/frontend-plan.md,
// 5.0). Parts and cell profiles are stored on the server as soon as they're made; the spec itself isn't stored until
// Run, so it lives here, and in localStorage so a reload doesn't lose a half-filled wizard.

export type Spec = Schemas["JobSpec"];
/** The spec so far, plus the experiment it was duplicated from (sent with Run; the plan ignores it). */
export type Draft = Partial<Spec> & { duplicated_from?: string | null };
export type Plan = Schemas["JobPlan"];

/** Whether a step lets the user go on: steps report it, the step list and the Next button read it. */
export type Gate = { ok: boolean; reason?: string };

type DraftContext = {
  draft: Draft;
  /** Merges fields into the draft. */
  update: (patch: Draft) => void;
  /** Starts again, from `next` (a duplicated spec, a part from the library) or empty. */
  reset: (next?: Draft) => void;
  /** The draft as a full job spec, once every required field is set; null before. */
  spec: Spec | null;
  /** `POST /api/jobs/plan` on the current spec, debounced: the single source of truth from step 4 on. Its `blockers`
   *  mark steps blocked, its `warnings` show on the review step, its `estimate` feeds the summary rail. */
  plan: { data: Plan | undefined; isFetching: boolean; error: Error | null };
  gates: Partial<Record<number, Gate>>;
  setGate: (step: number, gate: Gate) => void;
};

const STORAGE_KEY = "auto-grasp:wizard-draft";
const Context = createContext<DraftContext | null>(null);

export function DraftProvider({ children, initial }: { children: ReactNode; initial?: Draft }) {
  const [draft, setDraft] = useState<Draft>(() => initial ?? load() ?? {});
  const [gates, setGates] = useState<Partial<Record<number, Gate>>>({});

  useEffect(() => save(draft), [draft]);

  const update = useCallback((patch: Draft) => setDraft((current) => ({ ...current, ...patch })), []);
  const reset = useCallback((next: Draft = {}) => {
    setDraft(next);
    setGates({});
  }, []);
  const setGate = useCallback(
    (step: number, gate: Gate) =>
      setGates((current) =>
        current[step]?.ok === gate.ok && current[step]?.reason === gate.reason ? current : { ...current, [step]: gate },
      ),
    [],
  );

  const spec = useMemo(() => complete(draft), [draft]);
  const debounced = useDebounced(spec, 400);
  const planQuery = useQuery({
    queryKey: ["plan", debounced],
    queryFn: () => unwrapAs<Plan>(api.POST("/api/jobs/plan", { body: debounced! })),
    enabled: debounced !== null,
    placeholderData: keepPreviousData,
    staleTime: 60_000,
  });

  const value: DraftContext = {
    draft,
    update,
    reset,
    spec,
    plan: { data: planQuery.data, isFetching: planQuery.isFetching, error: planQuery.error },
    gates,
    setGate,
  };
  return <Context.Provider value={value}>{children}</Context.Provider>;
}

/** The wizard's draft, from any step. */
export function useDraft(): DraftContext {
  const context = useContext(Context);
  if (!context) throw new Error("useDraft is used outside the wizard's DraftProvider");
  return context;
}

/** Reports whether this step lets the user go on, e.g. `useStepGate(5, { ok: false, reason: "Nothing fits the jaws" })`.
 *  Next stays disabled while it's not ok, and the step list marks the step. */
export function useStepGate(step: number, gate: Gate) {
  const { setGate } = useDraft();
  const { ok, reason } = gate; // by value, so a fresh object each render doesn't re-run it
  useEffect(() => setGate(step, { ok, reason }), [setGate, step, ok, reason]);
}

/** Clears the stored draft, after a run starts. */
export function clearStoredDraft() {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // storage unavailable (private window, blocked site data): nothing to clear
  }
}

function complete(draft: Draft): Spec | null {
  const { part_id, cell_profile_id, task, grasp, error, seed } = draft;
  if (!part_id || cell_profile_id == null || !task || !grasp || !error || seed == null) return null;
  return { ...draft, part_id, cell_profile_id, task, grasp, error, seed };
}

function load(): Draft | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as Draft) : null;
  } catch {
    return null;
  }
}

function save(draft: Draft) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(draft));
  } catch {
    // storage unavailable: the draft still lives in memory for this visit
  }
}

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(timer);
  }, [value, ms]);
  return debounced;
}
