/** Two organizations for content tests, and the GET /organizations answer. */
export const HARBOUR = { id: "org-a", name: "Harbour Watch", slug: "harbour" };
export const RIVER = { id: "org-b", name: "River Desk", slug: "river" };

export function organizations(items = [HARBOUR, RIVER], role = "owner") {
  return {
    "GET /organizations": { body: items.map((organization) => ({ organization, role })) },
  };
}
