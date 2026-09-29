/**
 * The ID of the organization the admin app is working in, for this tab.
 *
 * It lives in sessionStorage next to the session. It is not a secret: the API
 * checks every request against the user's memberships.
 */

const KEY = "signalscope.organization";

export function readOrganization() {
  try {
    return sessionStorage.getItem(KEY);
  } catch {
    return null;
  }
}

export function saveOrganization(organizationId) {
  try {
    if (organizationId) sessionStorage.setItem(KEY, organizationId);
    else sessionStorage.removeItem(KEY);
  } catch {
    // Blocked storage only means the choice is not remembered.
  }
}
