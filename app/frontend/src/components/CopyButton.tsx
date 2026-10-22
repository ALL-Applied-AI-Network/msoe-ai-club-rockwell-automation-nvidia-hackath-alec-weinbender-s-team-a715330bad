import { useState } from "react";
import { Button } from "./Button";
import { Icon } from "./Icon";

/** Copies text to the clipboard, and says so for two seconds: finger IDs, the grasp pose. */
export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      variant="secondary"
      size="sm"
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 2000);
      }}
    >
      <Icon name="copy" />
      {copied ? "Copied" : label}
    </Button>
  );
}
