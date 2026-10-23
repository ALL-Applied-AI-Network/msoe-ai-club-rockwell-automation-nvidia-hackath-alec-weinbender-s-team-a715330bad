// The caveats the UI shows next to the numbers they qualify (docs/notes/frontend-plan.md, section 10). The wording lives
// only here, so every screen says the same thing. When an open problem is fixed, drop its caveat (CONTEXT.md, risks).

export const CAVEATS = {
  mock: "Mock sim: geometry only. Not a prediction.",
  gpuCopies:
    "Exploratory: the GPU path with copies holds about 9 of 81 more grasps than the reference sim. Re-run on the " +
    "reference or CPU-copies path for results you report.",
  landingCapture:
    "A finger that lands on the part can push it into the gap, and the sim counts that as held. Real-twin scores are " +
    "optimistic, and tight and loose pads can score alike.",
  weakGrip:
    "The twin grips with only about 2.5 N per jaw. Parts over about 100 g, or slippery ones, score as dropped for " +
    "every design.",
  captureEdge: "Grasps beyond about 5 mm along the jaws aren't repeatable, so small differences there mean little.",
  placeholderError: "This camera error is a placeholder until it's measured on the cell.",
  placeholderCell: "Placeholder: not yet measured at the cell.",
  twinMismatch: "The sim models the twin's SMC MHZL2-16D2 gripper; this profile differs in:",
  estimatedFriction: "Friction values are estimates until measured.",
  poseRecognition:
    "Scored over several resting poses: the cell has to recognise how each part landed and run that pose's grasp. The " +
    "poses' shares are trimesh's estimates, not measured.",
  demoData:
    "Demo data: these experiments ran on the mock sim, and their physical trials are made up. Unset DEMO_DATA for " +
    "real data.",
} as const;
