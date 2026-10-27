/**
 * Liveness check for local tooling and load balancers: the web server is up and serving. It says
 * nothing about the API (that is GET /api/v1/health) and needs no session, so the auth proxy skips
 * it. Without it, probes of /health were redirected to /login and never saw the server as ready.
 */
export function GET(): Response {
  return new Response("ok", {
    headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
  });
}
