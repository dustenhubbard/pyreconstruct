// Password gate for pyreconstruct.org/class/. Every request on the route comes
// here first (assets.run_worker_first), HTML and files alike.
//   student password: the current term (/class/<CURRENT_TERM>/) and the shared
//     theme files; /class/ itself sends a student on to the current term.
//   teaching-team password: everything under /class/.
// The browser asks with HTTP Basic auth; the user name is ignored.

const SHARED = ["/class/assets/", "/class/stylesheets/", "/class/javascripts/"];
const NO_STORE = "private, no-store";

export default {
  async fetch(request, env) {
    if (!env.STUDENT_PASSWORD || !env.STAFF_PASSWORD || !env.CURRENT_TERM) {
      return reply(500, "The class site is not set up yet.");
    }

    let path;
    try {
      path = decodeURIComponent(new URL(request.url).pathname);
    } catch {
      return reply(400, "Bad request.");
    }
    if (path.includes("\\") || path.split("/").includes("..")) {
      return reply(400, "Bad request.");
    }

    const role = await roleFor(request, env);
    if (!role) {
      return reply(401, "Enter the class password.", {
        "WWW-Authenticate": 'Basic realm="PyReconstruct class", charset="UTF-8"',
      });
    }

    const term = `/class/${env.CURRENT_TERM}`;
    if (role === "student") {
      if (path === "/class" || path === "/class/") {
        return reply(302, "", { Location: `${term}/` });
      }
      const allowed =
        path === term ||
        path.startsWith(`${term}/`) ||
        SHARED.some((prefix) => path.startsWith(prefix));
      if (!allowed) return reply(403, "This page is for the teaching team.");
    }

    const response = await ranged(request, await env.ASSETS.fetch(request));
    const headers = new Headers(response.headers);
    headers.set("Cache-Control", NO_STORE);
    return new Response(response.body, { status: response.status, headers });
  },
};

// Safari plays a video only from a server that answers byte ranges. If the
// asset came back whole, cut out the one range asked for.
async function ranged(request, response) {
  const video = (response.headers.get("Content-Type") || "").startsWith("video/");
  if (!video || response.status !== 200) return response;
  const headers = new Headers(response.headers);
  headers.set("Accept-Ranges", "bytes");
  const match = /^bytes=(\d*)-(\d*)$/.exec(request.headers.get("Range") || "");
  if (!match || (!match[1] && !match[2])) return new Response(response.body, { headers });

  const body = await response.arrayBuffer();
  const size = body.byteLength;
  const start = match[1] ? Number(match[1]) : Math.max(0, size - Number(match[2]));
  const end = match[1] && match[2] ? Math.min(Number(match[2]), size - 1) : size - 1;
  if (start > end) {
    headers.set("Content-Range", `bytes */${size}`);
    return new Response(null, { status: 416, headers });
  }
  headers.set("Content-Range", `bytes ${start}-${end}/${size}`);
  headers.delete("Content-Length");
  return new Response(body.slice(start, end + 1), { status: 206, headers });
}

async function roleFor(request, env) {
  const given = password(request.headers.get("Authorization"));
  if (given === null) return null;
  // Compare against both every time, so the timing says nothing either way.
  const [staff, student] = await Promise.all([
    same(given, env.STAFF_PASSWORD),
    same(given, env.STUDENT_PASSWORD),
  ]);
  if (staff) return "staff";
  if (student) return "student";
  return null;
}

function password(header) {
  const match = /^Basic\s+([A-Za-z0-9+/=]+)$/i.exec(header || "");
  if (!match) return null;
  let text;
  try {
    const bytes = Uint8Array.from(atob(match[1]), (c) => c.charCodeAt(0));
    text = new TextDecoder().decode(bytes);
  } catch {
    return null;
  }
  const colon = text.indexOf(":");
  return colon < 0 ? null : text.slice(colon + 1);
}

// Hash first so both sides have the same length, then compare in constant time.
async function same(a, b) {
  const encoder = new TextEncoder();
  const [x, y] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(a)),
    crypto.subtle.digest("SHA-256", encoder.encode(b)),
  ]);
  return crypto.subtle.timingSafeEqual(x, y);
}

function reply(status, text, headers = {}) {
  return new Response(text, {
    status,
    headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": NO_STORE, ...headers },
  });
}
