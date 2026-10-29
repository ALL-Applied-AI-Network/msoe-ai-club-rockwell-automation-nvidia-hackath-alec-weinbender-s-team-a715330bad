import { useLocation, useNavigate } from "react-router";
import { Button, LinkButton } from "./Button";

/** Goes back to the page the user came from. Opened from a bookmark or a pasted link there is nothing behind it, so it
 *  goes to `fallback` instead. */
export function BackButton({ fallback = "/jobs", label = "Back" }: { fallback?: string; label?: string }) {
  const navigate = useNavigate();
  const { key } = useLocation();
  if (key === "default") return <LinkButton variant="secondary" to={fallback}>{label}</LinkButton>;
  return (
    <Button variant="secondary" onClick={() => navigate(-1)}>
      {label}
    </Button>
  );
}
