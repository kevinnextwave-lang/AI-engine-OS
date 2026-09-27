/**
 * Whether an unreachable API may be answered with bundled sample data.
 *
 * Development only. In production a misconfigured API URL or broken CORS
 * must surface as an honest error state — never as plausible-looking sample
 * numbers in front of a real customer. (The "no project selected" demo
 * experience is unaffected; this gates only the network-failure fallback.)
 */
export const MOCK_FALLBACK_ALLOWED = process.env.NODE_ENV !== "production";

export const API_UNREACHABLE_MESSAGE =
  "The API could not be reached. Check your connection and try again.";
