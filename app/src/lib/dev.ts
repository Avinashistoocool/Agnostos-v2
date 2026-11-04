import { useEffect, useState } from "react";

const KEY = "agnostos.devMode";
const EVENT = "agnostos-dev-mode";

export function isDevMode(): boolean {
  try {
    if (new URLSearchParams(window.location.search).has("dev")) {
      window.localStorage.setItem(KEY, "1");
      return true;
    }
    return window.localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function setDevMode(on: boolean) {
  try {
    window.localStorage.setItem(KEY, on ? "1" : "0");
  } catch {
    /* storage unavailable */
  }
  window.dispatchEvent(new Event(EVENT));
}

/** Raw job logs and the terminal view are only shown in developer mode. */
export function useDevMode(): [boolean, (on: boolean) => void] {
  const [on, setOn] = useState(isDevMode);
  useEffect(() => {
    const sync = () => setOn(isDevMode());
    window.addEventListener(EVENT, sync);
    window.addEventListener("storage", sync);
    return () => {
      window.removeEventListener(EVENT, sync);
      window.removeEventListener("storage", sync);
    };
  }, []);
  return [on, setDevMode];
}
