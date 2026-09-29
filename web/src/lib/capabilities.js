/**
 * What the UI offers for a role in the active organization.
 *
 * Only for hiding buttons that would fail: the API checks every request.
 * Viewers read, members also add and remove documents and research, owners
 * and admins also manage sources. System admins may do everything.
 */
const RANK = { viewer: 1, member: 2, admin: 3, owner: 3 };
const NEEDED = { read: 1, contribute: 2, manage: 3 };

export function contentCapabilities(role, isSystemAdmin) {
  const rank = isSystemAdmin ? 3 : (RANK[role] ?? 0);
  return Object.fromEntries(
    Object.entries(NEEDED).map(([capability, needed]) => [capability, rank >= needed]),
  );
}
