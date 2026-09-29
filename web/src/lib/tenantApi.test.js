import { describe, expect, it, vi } from "vitest";

import { createApiClient } from "./api.js";
import { createTenantApi } from "./tenantApi.js";

describe("createTenantApi", () => {
  it("adds organization_id to content calls only", async () => {
    const fetchImpl = vi.fn(async () => new Response("{}", { status: 200 }));
    const api = createApiClient({ baseUrl: "/api", getToken: () => "t", fetchImpl });
    const tenant = createTenantApi(api, "org-1");

    await tenant.get("/dashboard/overview", { query: { days: 7 } });
    await tenant.post("/research/context", { query: "x" });
    await api.get("/organizations");

    const urls = fetchImpl.mock.calls.map(([url]) => url);
    expect(urls).toEqual([
      "/api/dashboard/overview?days=7&organization_id=org-1",
      "/api/research/context?organization_id=org-1",
      "/api/organizations",
    ]);
    expect(fetchImpl.mock.calls[0][1].headers.Authorization).toBe("Bearer t");
  });
});
