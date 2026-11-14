import { useEffect, useState } from "react";
import { markSplashSeen, splashAlreadySeen } from "../lib/splash";
import { useTheme } from "../lib/theme";
import logoLight from "../assets/brand/costoad-logo.png";
import logoDark from "../assets/brand/costoad-logo-dark.png";
import loaderSvg from "../assets/brand/costoad-loader-clear.svg";
import animationLight from "../assets/brand/costoad-animation.svg";
import animationDark from "../assets/brand/costoad-animation-dark.svg";

/** Horizontal wordmark; swaps to the light-ink variant in dark mode. */
export function BrandLogo({ height = 32 }: { height?: number }) {
  const { theme } = useTheme();
  return <img className="brand-logo" src={theme === "dark" ? logoDark : logoLight} alt="CostOad" style={{ height }} />;
}

/** Brand loader for any background process (loading lists, scanning, uploads). */
export function Loader({ label, size = 72 }: { label?: string; size?: number }) {
  return (
    <div className="loader" role="status" aria-live="polite">
      <img src={loaderSvg} alt="" width={size} height={size} />
      {label && <span className="loader-label">{label}</span>}
    </div>
  );
}

// One full cycle of costoad-animation.svg (4.65s: logo -> collapses into the O -> opens
// again), so the splash ends on the complete logo, plus the fade-out below.
const SPLASH_MS = 4900;
/**
 * Entrance animation shown once per browser session, right after login.
 * Click (or Esc / Enter) skips it; users who prefer reduced motion never see it.
 */
export function Splash({ onDone }: { onDone: () => void }) {
  const { theme } = useTheme();
  const [skip] = useState(
    () => splashAlreadySeen() || window.matchMedia("(prefers-reduced-motion: reduce)").matches,
  );

  useEffect(() => {
    if (skip) {
      onDone();
      return;
    }
    markSplashSeen();
    const timer = window.setTimeout(onDone, SPLASH_MS);
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" || event.key === "Enter") onDone();
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.clearTimeout(timer);
      window.removeEventListener("keydown", onKey);
    };
  }, [skip, onDone]);

  if (skip) return null;

  return (
    <div className="splash" onClick={onDone} role="presentation">
      <img src={theme === "dark" ? animationDark : animationLight} alt="CostOad" />
    </div>
  );
}
