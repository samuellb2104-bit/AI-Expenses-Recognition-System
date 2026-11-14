const SPLASH_KEY = "costoad-splash-seen";

export function splashAlreadySeen(): boolean {
  try {
    return sessionStorage.getItem(SPLASH_KEY) === "1";
  } catch {
    return false;
  }
}

export function markSplashSeen() {
  try {
    sessionStorage.setItem(SPLASH_KEY, "1");
  } catch {
    /* private mode: the splash simply shows again next time */
  }
}

/** Call on sign-out so the next login plays the entrance animation again. */
export function resetSplash() {
  try {
    sessionStorage.removeItem(SPLASH_KEY);
  } catch {
    /* nothing to reset */
  }
}
