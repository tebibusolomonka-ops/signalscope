/**
 * An API client for organization content: every call carries organization_id.
 *
 * Only content routes (dashboard, search, documents and the like) use it.
 * Sign in, user administration, organization management and security routes
 * have their own organization rules and use the plain client.
 */
export function createTenantApi(api, organizationId) {
  const scoped = (options = {}) => ({
    ...options,
    query: { ...options.query, organization_id: organizationId },
  });
  return {
    organizationId,
    get: (path, options) => api.get(path, scoped(options)),
    post: (path, body, options) => api.post(path, body, scoped(options)),
  };
}
