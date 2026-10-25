The application: Auto-Grasp

Auto-Grasp answers one question for a factory before a new part reaches the robot cell: can we grip this reliably, and if not, what finger should we use?

Inputs: the CAD of the incoming part (or a batch of parts), the factory’s existing finger library, the gripper model, and the grasp policy they want to evaluate (for example, their VLM+IK pipeline).

1. Finger library evaluation. Every existing finger is simulated against the new part in Isaac Sim using the chosen policy. The output is a ranked success rate per finger.

Why it’s useful: the factory learns whether it can run the part with what’s already on the shelf, without trial and error at the cell, and without buying or printing anything.
Side benefit: it shows when one finger covers many parts, so the factory can group jobs and swap fingers less often.

2. Decision point (the factory’s call). The factory sees the best achievable success rate with its current fingers and decides whether that’s good enough or whether to design a new finger.

3. Automatic finger generation. Bayesian optimization tunes the parameters of a starting finger family, such as a V-pad’s angle, depth, and pad width. It can optimize for a single part or across several parts at once. The output is a printable finger and its predicted success rate.

Why it’s useful: it replaces days of manual design and repeated physical test-and-revise cycles. Optimizing across several parts produces fewer, more general fingers.

4. The library grows. Each new finger is added to the library, so future parts are more likely to be covered by existing fingers. The longer a factory uses Auto-Grasp, the less often it needs new fingers.