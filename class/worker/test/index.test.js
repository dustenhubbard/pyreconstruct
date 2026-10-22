import { describe, expect, it } from "vitest";
import worker from "../src/index.js";

const ETAG = '"v1"';
const MODIFIED = "Wed, 21 Oct 2026 07:28:00 GMT";

const env = {
  STUDENT_PASSWORD: "student-pass",
  STAFF_PASSWORD: "staff-pass",
  CURRENT_TERM: "2026-fall",
  // Stands in for the static files: answers 200 with the path it was asked for
  // (no body for HEAD), as video for an MP4, and never answers a byte range.
  ASSETS: {
    fetch: async (request) => {
      const path = new URL(request.url).pathname;
      const type = path.endsWith(".mp4") ? "video/mp4" : "text/html";
      return new Response(request.method === "HEAD" ? null : path, {
        headers: {
          "Content-Type": type,
          "Cache-Control": "public, max-age=14400",
          ETag: ETAG,
          "Last-Modified": MODIFIED,
        },
      });
    },
  },
};

const STUDENT = "Basic " + btoa("anyone:student-pass");
const STAFF = "Basic " + btoa("ta:staff-pass");
const WRONG = "Basic " + btoa("anyone:guess");

function get(path, authorization, overrides = {}, extra = {}, method = "GET") {
  const headers = { ...extra, ...(authorization ? { Authorization: authorization } : {}) };
  const request = new Request(`https://pyreconstruct.org${path}`, { headers, method });
  return worker.fetch(request, { ...env, ...overrides });
}

const HANDOUT = "/class/2026-fall/lab-1-1-dendritic-spines/";
const CLIP = "/class/2026-fall/videos/lab-1-1/group-filter.mp4";
const STAFF_PAGE = "/class/staff/teaching-notes/";
const OLD_TERM = "/class/2026-spring/";

describe("no password", () => {
  it.each([HANDOUT, CLIP, "/class/", "/class/assets/javascripts/bundle.js", "/class/sitemap.xml"])(
    "%s is 401 and asks for one",
    async (path) => {
      const response = await get(path);
      expect(response.status).toBe(401);
      expect(response.headers.get("WWW-Authenticate")).toMatch(/^Basic realm=/);
      expect(response.headers.get("Cache-Control")).toBe("private, no-store");
    },
  );
});

describe("wrong password", () => {
  it.each([HANDOUT, CLIP, STAFF_PAGE])("%s is 401", async (path) => {
    expect((await get(path, WRONG)).status).toBe(401);
  });

  it("is 401 for a header that is not Basic", async () => {
    expect((await get(HANDOUT, "Bearer student-pass")).status).toBe(401);
  });
});

describe("student password", () => {
  it.each([HANDOUT, CLIP, "/class/2026-fall", "/class/stylesheets/extra.css", "/class/javascripts/clips.js"])(
    "%s is 200",
    async (path) => {
      const response = await get(path, STUDENT);
      expect(response.status).toBe(200);
      expect(await response.text()).toBe(path);
      expect(response.headers.get("Cache-Control")).toBe("private, no-store");
    },
  );

  it.each([
    STAFF_PAGE,
    OLD_TERM,
    "/class/2026-fall-old/",
    "/class/sitemap.xml",
    "/class/404.html",
    "/class/2026-fall/../staff/teaching-notes/",
    "/class/2026-fall/..%2Fstaff/teaching-notes/",
    "/class%2Fstaff/teaching-notes/",
  ])("%s is refused", async (path) => {
    expect([400, 403]).toContain((await get(path, STUDENT)).status);
  });

  it("is refused before any file is read", async () => {
    const ASSETS = { fetch: () => { throw new Error("read a file for a refused request"); } };
    const response = await get(STAFF_PAGE, STUDENT, { ASSETS }, { Range: "bytes=0-5" });
    expect(response.status).toBe(403);
  });

  it("is sent from /class/ to the current term", async () => {
    const response = await get("/class/", STUDENT);
    expect(response.status).toBe(302);
    expect(response.headers.get("Location")).toBe("/class/2026-fall/");
  });

  it("follows CURRENT_TERM", async () => {
    expect((await get(OLD_TERM, STUDENT, { CURRENT_TERM: "2026-spring" })).status).toBe(200);
    expect((await get(HANDOUT, STUDENT, { CURRENT_TERM: "2026-spring" })).status).toBe(403);
  });
});

describe("teaching-team password", () => {
  it.each([HANDOUT, CLIP, STAFF_PAGE, OLD_TERM, "/class/", "/class/sitemap.xml"])("%s is 200", async (path) => {
    const response = await get(path, STAFF);
    expect(response.status).toBe(200);
    expect(response.headers.get("Cache-Control")).toBe("private, no-store");
  });
});

describe("clips", () => {
  it("answers a byte range with 206", async () => {
    const response = await get(CLIP, STUDENT, {}, { Range: "bytes=0-5" });
    expect(response.status).toBe(206);
    expect(response.headers.get("Content-Range")).toBe(`bytes 0-5/${CLIP.length}`);
    expect(await response.text()).toBe(CLIP.slice(0, 6));
    expect(response.headers.get("Cache-Control")).toBe("private, no-store");
  });

  it("answers an open and a suffix range", async () => {
    expect(await (await get(CLIP, STUDENT, {}, { Range: "bytes=6-" })).text()).toBe(CLIP.slice(6));
    expect(await (await get(CLIP, STUDENT, {}, { Range: "bytes=-4" })).text()).toBe(CLIP.slice(-4));
  });

  it("is 416 for a range past the end", async () => {
    expect((await get(CLIP, STUDENT, {}, { Range: "bytes=9999-" })).status).toBe(416);
  });

  it("answers HEAD with a range as the whole file, never 416", async () => {
    const response = await get(CLIP, STUDENT, {}, { Range: "bytes=0-5" }, "HEAD");
    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Range")).toBeNull();
    expect(response.headers.get("Accept-Ranges")).toBe("bytes");
  });

  it.each([ETAG, MODIFIED])("answers a range when If-Range is %s", async (validator) => {
    const response = await get(CLIP, STUDENT, {}, { Range: "bytes=0-5", "If-Range": validator });
    expect(response.status).toBe(206);
    expect(await response.text()).toBe(CLIP.slice(0, 6));
  });

  it.each(['"definitely-stale"', "W/\"v1\"", "Tue, 20 Oct 2026 07:28:00 GMT"])(
    "sends the whole clip when If-Range is %s",
    async (validator) => {
      const response = await get(CLIP, STUDENT, {}, { Range: "bytes=0-5", "If-Range": validator });
      expect(response.status).toBe(200);
      expect(response.headers.get("Content-Range")).toBeNull();
      expect(await response.text()).toBe(CLIP);
    },
  );

  it("still asks for a password before any range", async () => {
    expect((await get(CLIP, undefined, {}, { Range: "bytes=0-5" })).status).toBe(401);
  });
});

describe("setup", () => {
  it("refuses everyone while a password is missing", async () => {
    expect((await get(HANDOUT, STUDENT, { STAFF_PASSWORD: undefined })).status).toBe(500);
    expect((await get(HANDOUT, "Basic " + btoa("x:"), { STUDENT_PASSWORD: "" })).status).toBe(500);
  });
});
