import type { ButtonHTMLAttributes } from "react";
import { Link, type LinkProps } from "react-router";
import styles from "./Button.module.css";

type Look = {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "md" | "sm";
};

/** The app's one button. Primary for the one main action in view, secondary for the rest, ghost for quiet actions in
 *  dense places (card footers), danger for actions that stop or throw away work (always behind a ConfirmDialog). */
export function Button({ variant = "primary", size = "md", className, type = "button", ...props }: ButtonHTMLAttributes<HTMLButtonElement> & Look) {
  return <button type={type} className={classes(variant, size, className)} {...props} />;
}

/** A link that looks like a Button, for actions that go to another page ("Open", "New experiment"). */
export function LinkButton({ variant = "secondary", size = "md", className, ...props }: LinkProps & Look) {
  return <Link className={classes(variant, size, className)} {...props} />;
}

function classes(variant: NonNullable<Look["variant"]>, size: NonNullable<Look["size"]>, extra?: string): string {
  return [styles.button, styles[variant], styles[size], extra].filter(Boolean).join(" ");
}
