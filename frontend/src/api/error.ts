/**
 * One error type for every failed request.
 *
 * The split that matters: `userMessage` is safe to render, `detail` and `status` are for
 * logging. FastAPI's `detail` can carry a raw validation echo or an internal message written
 * for a developer, and neither belongs in a toast. `Error.message` is set to the safe copy too,
 * so a careless `{error.message}` in a component is still safe.
 */

export type ApiErrorCategory =
  | 'unauthenticated'
  | 'forbidden'
  | 'not_found'
  | 'invalid_input'
  | 'conflict'
  | 'rate_limited'
  | 'server'
  | 'network'
  | 'unknown';

const DEFAULT_MESSAGES: Record<ApiErrorCategory, string> = {
  unauthenticated: 'Please sign in again.',
  forbidden: 'You do not have access to this.',
  not_found: 'We could not find that.',
  invalid_input: 'Some details need correcting.',
  conflict: 'This changed while you were looking at it. Reload and try again.',
  rate_limited: 'Too many requests. Try again shortly.',
  server: 'Something went wrong at our end. Please try again.',
  network: 'Could not reach the server. Check your connection.',
  unknown: 'Something went wrong.',
};

function categorise(status: number): ApiErrorCategory {
  if (status === 401) return 'unauthenticated';
  if (status === 403) return 'forbidden';
  if (status === 404) return 'not_found';
  if (status === 409) return 'conflict';
  if (status === 422 || status === 400) return 'invalid_input';
  if (status === 429) return 'rate_limited';
  if (status >= 500) return 'server';
  return 'unknown';
}

export class ApiError extends Error {
  readonly status: number;
  readonly category: ApiErrorCategory;
  readonly userMessage: string;
  readonly detail: unknown;

  constructor(args: {
    status: number;
    category: ApiErrorCategory;
    userMessage: string;
    detail?: unknown;
  }) {
    // Error.message carries the *safe* copy, so an accidental render leaks nothing.
    super(args.userMessage);
    this.name = 'ApiError';
    this.status = args.status;
    this.category = args.category;
    this.userMessage = args.userMessage;
    this.detail = args.detail;
  }

  /** Parses all three shapes FastAPI's `detail` takes. */
  static async fromResponse(response: Response): Promise<ApiError> {
    const category = categorise(response.status);
    let detail: unknown;
    let userMessage = DEFAULT_MESSAGES[category];

    try {
      const body = await response.json();
      detail = body?.detail ?? body;

      if (typeof detail === 'string') {
        // A plain string detail is written for a person, so it is safe to show.
        userMessage = detail;
      } else if (detail && typeof detail === 'object' && 'message' in detail) {
        // The structured form: { code, message }. The message is deliberate copy.
        userMessage = String((detail as { message: unknown }).message);
      }
      // A Pydantic error array stays in `detail` only - it echoes submitted values.
    } catch {
      // No JSON body. The default for the category is the honest thing to show.
    }

    return new ApiError({ status: response.status, category, userMessage, detail });
  }

  static network(cause: unknown): ApiError {
    return new ApiError({
      status: 0,
      category: 'network',
      userMessage: DEFAULT_MESSAGES.network,
      detail: cause,
    });
  }
}
