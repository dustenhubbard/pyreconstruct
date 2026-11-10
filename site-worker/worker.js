// Serves the built docs site (the `site/` folder from `mkdocs build`) on
// pyreconstruct.org. www.pyreconstruct.org answers with a permanent redirect
// to the same path on the bare domain, as GitHub Pages did before.
export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.hostname === "www.pyreconstruct.org") {
      url.hostname = "pyreconstruct.org";
      return Response.redirect(url.toString(), 301);
    }
    return env.ASSETS.fetch(request);
  },
};
