/**
 * The bearer token for this browser tab.
 *
 * It lives in sessionStorage, never localStorage, so it is gone when the
 * browser session ends. If storage is blocked it is kept in memory for this
 * page only. It is never logged, rendered or put in a URL.
 */

const KEY = "signalscope.session";
let memoryToken = null;

export function readToken() {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return memoryToken;
  }
}

export function saveToken(token) {
  try {
    sessionStorage.setItem(KEY, token);
    memoryToken = null;
  } catch {
    // Blocked storage: keep the token in memory for this page instead.
    memoryToken = token;
  }
}

export function clearToken() {
  memoryToken = null;
  try {
    sessionStorage.removeItem(KEY);
  } catch {
    // Nothing was stored.
  }
}
