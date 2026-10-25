// User Guide clips. In the Markdown each clip is its poster image and a link to
// its MP4 (figure.clip > img, a.clip-src), so the page reads the same with no
// script. Here the image becomes a muted, looping video that plays while it is
// on screen, with a Replay button and the link's "N s · loops" as a tag. With
// reduced motion the poster stays and a Play button plays the clip once.
(function () {
  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)");
  var watcher = "IntersectionObserver" in window
    ? new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          var video = entry.target;
          if (entry.isIntersecting) video.play().catch(function () {});
          else video.pause();
        });
      }, { threshold: 0.5 })
    : null;

  function upgrade(figure) {
    var poster = figure.querySelector("img");
    var link = figure.querySelector("a.clip-src");
    if (!poster || !link || figure.querySelector("video")) return;

    var video = document.createElement("video");
    video.muted = true;
    video.playsInline = true;
    video.preload = "metadata";
    video.poster = poster.currentSrc || poster.src;
    // the clip's own size: a poster that is not 2240 x 1520 names its size
    // in data-width and data-height, so it is known before anything loads
    video.width = Number(poster.dataset.width) || 1120;
    video.height = Number(poster.dataset.height) || 760;
    video.setAttribute("aria-label", poster.alt);
    var source = document.createElement("source");
    source.src = link.href;
    source.type = "video/mp4";
    video.appendChild(source);

    var frame = document.createElement("div");
    frame.className = "clip-frame";
    frame.appendChild(video);
    var button = document.createElement("button");
    button.type = "button";
    button.className = "clip-replay";
    button.addEventListener("click", function () {
      video.currentTime = 0;
      video.play().catch(function () {});
    });
    if (reduced.matches) {
      button.textContent = "Play";
    } else {
      var tag = document.createElement("span");
      tag.className = "clip-tag";
      tag.setAttribute("aria-hidden", "true");
      tag.textContent = link.textContent.replace(/^\W+/, "");
      frame.appendChild(tag);
      video.loop = true;
      button.textContent = "Replay";
      if (watcher) watcher.observe(video);
      else video.autoplay = true;
    }
    frame.appendChild(button);

    var holder = poster.closest("p") || poster;
    holder.replaceWith(frame);
    (link.closest("p") || link).remove();
  }

  function init() {
    document.querySelectorAll(".md-typeset figure.clip").forEach(upgrade);
  }

  // Material's instant navigation swaps pages without a reload
  if (window.document$) window.document$.subscribe(init);
  else document.addEventListener("DOMContentLoaded", init);
})();
