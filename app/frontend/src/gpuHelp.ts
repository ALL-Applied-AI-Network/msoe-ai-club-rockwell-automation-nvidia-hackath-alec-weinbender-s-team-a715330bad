// What the GPU's error messages mean and how to fix them (docs/notes/frontend-plan.md, 4.5). The API sends compute errors
// as text only, so they're matched here by substring, in one place, until it sends stable codes (plan, section 13). The
// help cards double as the app's setup guide: a new user who has never connected sees the one their first error needs.

export type GpuHelp = {
  meaning: string; // what went wrong, in a sentence
  fix: string[]; // what to do, in one or two steps
  setup?: string; // the SETUP.md section that covers it
  action: "retry" | "switch" | "none"; // retry: try again; switch: stop the current target and start the chosen one
};

const RULES: { test: RegExp; help: GpuHelp }[] = [
  {
    test: /before starting another target/,
    help: {
      meaning: "Another target is still connected, and the app uses one at a time.",
      fix: ["Stop or disconnect it, then start the one you chose. The button below does both."],
      action: "switch",
    },
  },
  {
    test: /can't reach the GB10/,
    help: {
      meaning: "The GB10 can't be reached: the MSOE VPN isn't connected, or you're off campus without it.",
      fix: ["Connect GlobalProtect, the MSOE VPN.", "Then try again."],
      setup: "MSOE VPN",
      action: "retry",
    },
  },
  {
    test: /refused the login/,
    help: {
      meaning: "The GB10 doesn't know your SSH key yet.",
      fix: [
        "Add your SSH key to the team account, once, with the steps in SETUP.md.",
        "Check it with the command there, then try again.",
      ],
      setup: "Your SSH key on the GB10",
      action: "retry",
    },
  },
  {
    test: /host key changed/,
    help: {
      meaning: "The GB10's identity changed since you last connected.",
      fix: ["Don't work around it: ask in #compute-questions. It can mean you're not talking to the real GB10."],
      action: "none",
    },
  },
  {
    test: /GB10 not set up/,
    help: {
      meaning: "The repo or Isaac Sim is missing on the GB10.",
      fix: ["Whoever maintains the GB10 sets it up again, with the GPU test plan. It can't be fixed from the app."],
      action: "none",
    },
  },
  {
    test: /held by another account/,
    help: {
      meaning: "Another team is using the team's port on the GB10.",
      fix: [
        "Agree a new port with the team.",
        "Everyone sets COMPUTE_GB10_SIM_PORT to it in their .env and restarts the API.",
      ],
      setup: "GPU from the web app",
      action: "none",
    },
  },
  {
    test: /teammate is starting/,
    help: {
      meaning: "A teammate's Connect is starting the GB10's sim server right now.",
      fix: ["Wait a minute, then connect again."],
      action: "retry",
    },
  },
  {
    test: /didn't start on .* in \d+ tries/,
    help: {
      meaning: "Isaac Sim failed to start three times in a row, which is rare.",
      fix: ["Connect again.", "If it happens again, read runs/sim_server.log on the GB10 and ask the team."],
      action: "retry",
    },
  },
  {
    test: /brev ls|can't run the Brev CLI/,
    help: {
      meaning: "The Brev CLI isn't installed, isn't logged in, or can't be reached through WSL.",
      fix: ["Run brev login in Ubuntu.", "On Windows, set COMPUTE_BREV_WSL=Ubuntu in your .env and restart the API."],
      setup: "Brev CLI",
      action: "retry",
    },
  },
  {
    test: /after the start request/,
    help: {
      meaning: "Brev couldn't start the instance.",
      fix: [
        "Check the Brev console for a service notice first, then the instance's Activity Logs.",
        "If no GPU of that type is free, try again later, or use the GB10.",
      ],
      action: "retry",
    },
  },
  {
    test: /port forward.*exited/,
    help: {
      meaning: "The tunnel from this laptop to the GPU closed.",
      fix: [
        "Often something else is using local port 9000: compute_forward.log in the app's data folder says.",
        "Then try again.",
      ],
      setup: "GPU from the web app",
      action: "retry",
    },
  },
  {
    test: /isn't answering/,
    help: {
      meaning: "The connection dropped mid-session, usually because the VPN did.",
      fix: ["Reconnect the VPN. The app reconnects by itself, and running jobs carry on."],
      setup: "GPU from the web app",
      action: "none",
    },
  },
  {
    test: /can't run ssh/,
    help: {
      meaning: "The app can't find ssh on this computer.",
      fix: ["Install OpenSSH (SETUP.md), or set COMPUTE_SSH in your .env and restart the API."],
      setup: "Install the tools",
      action: "retry",
    },
  },
];

const FALLBACK: GpuHelp = {
  meaning: "The GPU couldn't be reached or started.",
  fix: ["Try again.", "If it happens again, keep the message above and ask in #compute-questions."],
  setup: "GPU from the web app",
  action: "retry",
};

/** The help for a compute error message: a failed session's message, an instance-list error, or a start call's detail. */
export function gpuHelp(message: string): GpuHelp {
  return RULES.find((rule) => rule.test.test(message))?.help ?? FALLBACK;
}
