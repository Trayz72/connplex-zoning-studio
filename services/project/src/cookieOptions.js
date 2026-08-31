/** Session cookie attributes — centralized so set and clear always agree,
 * and so cross-origin deployment (frontend and this service on two
 * different Render subdomains) actually works.
 *
 * `sameSite: 'lax'` only sends a cookie on same-site requests and top-level
 * cross-site navigations — NOT on cross-site fetch/XHR, which is exactly
 * what happens when the frontend and this API live on different origins.
 * Left as 'lax' (the default, safest for local http dev), login would
 * appear to succeed (the Set-Cookie header still arrives) but every
 * following request would silently go out with no cookie at all, since
 * fetch('...', {credentials:'include'}) still won't attach a Lax cookie
 * cross-site — indistinguishable from "not logged in" with no clear error.
 *
 * Cross-site cookies require sameSite:'none', which browsers only honor
 * alongside secure:true (HTTPS-only) — fine on Render (HTTPS by default),
 * broken on local http dev, where a secure cookie is simply dropped. So
 * this is opt-in via CROSS_ORIGIN_COOKIES=true, set only in the deployed
 * environment, not implied by NODE_ENV (Render doesn't set that itself). */
const crossOrigin = process.env.CROSS_ORIGIN_COOKIES === 'true';

export const SESSION_COOKIE_OPTIONS = {
  httpOnly: true,
  sameSite: crossOrigin ? 'none' : 'lax',
  secure: crossOrigin,
  maxAge: 7 * 24 * 60 * 60 * 1000
};

// clearCookie needs the same sameSite/secure attributes used to set the
// cookie to reliably match and remove it — maxAge is irrelevant here.
export const CLEAR_COOKIE_OPTIONS = {
  httpOnly: true,
  sameSite: crossOrigin ? 'none' : 'lax',
  secure: crossOrigin
};
