---
title: Home
hide:
  - navigation
  - toc
template: home.html
---

<div class="pr-hero" markdown>
<div class="pr-hero-copy" markdown>

<p class="pr-eyebrow">OPEN SOURCE · ELECTRON MICROSCOPY</p>

# PyReconstruct

An open-source desktop application for tracing, annotating, and 3D reconstruction of serial-section and volume electron microscopy (EM) data.
{ .pr-lead }

<div class="pr-actions" markdown>

[Download PyReconstruct :material-arrow-down:](#install){ .md-button .md-button--primary }
[User guide :material-arrow-right:](USER_GUIDE.md){ .md-button }

</div>

<p class="pr-platforms">Windows, macOS & Linux <span aria-hidden="true">/</span> Free and open source</p>

</div>
<div class="pr-hero-visual" role="img" aria-label="Electron microscopy image with colorful segmented structures, from the PyReconstruct welcome artwork">
  <div class="pr-visual-label"><span class="pr-status-dot"></span> ELECTRON MICROSCOPY / SEGMENTATION</div>
</div>
</div>

<div class="pr-intro" markdown>

## Who it's for

Neuroscientists and EM researchers who trace neural structures across stacks of serial sections, measure morphology, and build 3D reconstructions of cells, organelles, and synapses.

</div>

<div class="pr-features" markdown>
<div markdown>

<span class="pr-feature-number">01</span>

### Trace & annotate

Outline structures across serial sections. Refine segmentation, organize objects, and keep your annotations together.

[Learn the tracing tools :material-arrow-right:](USER_GUIDE.md#8-working-with-traces)

</div>
<div markdown>

<span class="pr-feature-number">02</span>

### Align & reconstruct

Align your image stack and build 3D views to understand how structures connect across sections.

[Explore 3D reconstruction :material-arrow-right:](USER_GUIDE.md#11-3d-reconstruction)

</div>
<div markdown>

<span class="pr-feature-number">03</span>

### Measure & explore

Inspect object measurements and work with large autosegmented series in the `.jser` series format.

[Work with your data :material-arrow-right:](USER_GUIDE.md#9-data-lists)

</div>
</div>

<section class="pr-download-section" markdown>
<div class="pr-section-heading" markdown>

## Install

Download the current stable release, **v1.24.0**, for your computer.

</div>
<div class="pr-downloads" markdown>
<div class="pr-download" markdown>

:fontawesome-brands-windows:
{ .pr-os-icon }

### Windows

64-bit · Windows 10 or later

[Download for Windows :material-arrow-down:](https://github.com/dustenhubbard/PyReconstruct/releases/download/v1.24.0/PyReconstruct-1.24.0-Windows-x86_64-Setup.exe){ .md-button }

Includes Python. Builds are unsigned; see the [first-launch instructions](USER_GUIDE.md#1-installing-pyreconstruct) if Windows shows a SmartScreen warning.
{ .pr-small }

</div>
<div class="pr-download" markdown>

:fontawesome-brands-apple:
{ .pr-os-icon }

### macOS

macOS 12 or later

[Apple Silicon :material-arrow-down:](https://github.com/dustenhubbard/PyReconstruct/releases/download/v1.24.0/PyReconstruct-1.24.0-macOS-arm64.dmg){ .md-button }
[Intel :material-arrow-down:](https://github.com/dustenhubbard/PyReconstruct/releases/download/v1.24.0/PyReconstruct-1.24.0-macOS-x86_64.dmg){ .md-button }

Includes Python. See the [first-launch instructions](USER_GUIDE.md#1-installing-pyreconstruct).
{ .pr-small }

</div>
<div class="pr-download" markdown>

:fontawesome-brands-linux:
{ .pr-os-icon }

### Linux

64-bit · glibc 2.28 or later

[Download AppImage :material-arrow-down:](https://github.com/dustenhubbard/PyReconstruct/releases/download/v1.24.0/PyReconstruct-1.24.0-linux-x86_64.AppImage){ .md-button }

Includes Python. Or install with `curl -fsSL https://pyreconstruct.org/install.sh | bash`.
{ .pr-small }

</div>
</div>

[Installation help](USER_GUIDE.md#1-installing-pyreconstruct) · [All releases & checksums](https://github.com/dustenhubbard/PyReconstruct/releases/latest) · [Stable & Beta channels](RELEASE_CHANNELS.md)
{ .pr-download-help }

</section>

<div class="pr-resources" markdown>
<div markdown>

## Documentation {#where-to-go-next}

The user guide, performance notes, developer setup, and the Harris lab wiki.

</div>
<div class="pr-resource-links" markdown>

[**User guide** <span>Installation, tools, alignment, and backups ↗</span>](USER_GUIDE.md)

[**Performance** <span>Benchmarks and working with large series ↗</span>](performance.md)

[**Developer resources** <span>Set up a source install with uv ↗</span>](DEV_UV.md)

[**Contribute on GitHub** <span>Source code, issues, and contributions ↗</span>](https://github.com/dustenhubbard/PyReconstruct)

[**Harris lab wiki** <span>Lab protocols and EM image processing guides ↗</span>](https://cloud.wikis.utexas.edu/wiki/spaces/khlab/overview)

</div>
</div>

<div class="pr-project-note" markdown>
<div markdown>

## About this distribution

PyReconstruct is the modern successor to *Reconstruct*. This site documents an independently maintained distribution that tracks [SynapseWeb/PyReconstruct](https://github.com/SynapseWeb/PyReconstruct), with performance improvements, installers, and ongoing interface updates.

</div>
<div markdown>

## Citation

The upstream PyReconstruct project was developed in the Kristen Harris Lab at **The University of Texas at Austin** and introduced in *PNAS* (2025).

[Read the paper :material-arrow-top-right:](https://doi.org/10.1073/pnas.2505822122) · [Project credits](https://github.com/dustenhubbard/PyReconstruct/blob/main/README.md#credits)

</div>
</div>
