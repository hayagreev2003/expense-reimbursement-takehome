/**
 * Runtime configuration, read once.
 *
 * Every module imports `baseUrl` from here rather than reading `process.env` at the call site.
 * Next.js inlines NEXT_PUBLIC_* at build time, so a scattered read is also a scattered rebuild
 * dependency, and a typo in one of them fails only on the route that uses it.
 */

export const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://127.0.0.1:8000';

/** Prefix for every application endpoint. The API is path-versioned. */
export const apiPrefix = '/api/v1';

export const apiUrl = (path: string): string =>
  `${baseUrl.replace(/\/$/, '')}${apiPrefix}${path.startsWith('/') ? path : `/${path}`}`;

/**
 * The demo reset, and whether the UI offers it.
 *
 * Two honest caveats. `NEXT_PUBLIC_*` is inlined into the bundle, so this token is readable by
 * anyone who opens the page - it keeps a passing scanner off the endpoint, it is not a secret.
 * And the flag only hides the button: the server decides whether the route exists at all, via
 * DEMO_RESET_ENABLED, and answers 404 when it does not.
 */
export const demoResetEnabled = process.env.NEXT_PUBLIC_DEMO_RESET_ENABLED === 'true';

export const demoResetToken = process.env.NEXT_PUBLIC_DEMO_RESET_TOKEN ?? '';
