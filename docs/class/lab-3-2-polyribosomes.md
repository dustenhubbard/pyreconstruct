---
title: "Lab 3.2: Polyribosomes"
search:
  exclude: true
robots: noindex
---

# Lab 3.2: Polyribosomes

NEU466G, Dr. Kirk · [Class documents](index.md)
{ .class-doc-meta }

## Overview

Polyribosomes are clusters of 3 or more ribosomes in close proximity. In EM images, they look like dark round dots (approx. 10-30 nm in width). Because of their small size, individual ribosomes cannot be seen on more than one section, although a particularly large cluster may spread across 2 or 3 sections.

## Identifying polyribosomes in dendritic spines

Here is an example polyribosome (PR) from the class dataset ZGBJY, d03p31.

<figure class="class-fig" markdown="span">
  ![Section 124 with traces hidden and a red circle around the polyribosome cluster](img/lab-3-2/01.png){ width="520" }
  <figcaption>Polyribosomes (red circle) in ZGBJY - d03rh31.</figcaption>
</figure>

## 5 additional spines

**To learn to identify polyribosomes, search in the same 5 spines where you looked for SER and SA:**

- **d03p12**
- **d03p14**
- **d03p37_branched**
- **d03p40**
- **d03p42**

2 of these 5 spines will have polyribosomes.

## Stamp polyribosomes in the 5 spines

Create a trace palette circle with this naming convention: **d03r##** (with r = ribosomes and ## corresponding to spine ##). For example, d03r31 are ribosomes in the spine d03p31.

<figure class="class-fig" markdown="span">
  ![Set Attributes for d03r31: blue, circle, Fill None, Stamp radius 0.05, Object Groups Polyribosomes](img/lab-3-2/02.png){ width="318" }
  <figcaption>Set Attributes for d03r31.</figcaption>
</figure>

Stamp each polyribosome cluster on a single section where the PR is present. In the case that your spine has multiple PRs, stamp each cluster once (each using the same name and palette attributes) to reconstruct each PR as a sphere in 3D (instructions below).

<figure class="class-fig" markdown="span">
  ![Section 124 without traces](img/lab-3-2/03.png){ width="350" }
  ![Section 124 with d03sp31, d03c31, d03cfa31 and the blue d03rh31 circle](img/lab-3-2/04.png){ width="350" }
  <figcaption>Section 124 without traces (left) and with d03sp31, d03c31, d03cfa31 and d03rh31 (right).</figcaption>
</figure>

## Adding polyribosomes to the 3D scene

To view your ribosome stamps in the 3D reconstruction, right-click on the object in the object list > **3D > Edit 3D settings...** > in the drop-down menu set 3D Type to spheres > OK.

<figure class="class-fig" markdown="span">
  ![The 3D Object Settings dialog with 3D Type spheres and Opacity 1.0](img/lab-3-2/05.png){ width="219" }
  <figcaption>3D Object Settings.</figcaption>
</figure>

<figure class="clip" markdown>

![Clip: in the Object List the pointer clicks d03rh31, right-clicks it and chooses 3D > Edit 3D settings...; in 3D Object Settings it opens 3D Type, picks spheres in place of surface, and clicks OK.](img/lab-3-2/3d-spheres-poster.jpg)

[▶ 7 s · loops](videos/lab-3-2/3d-spheres.mp4){ .clip-src }

<figcaption markdown>Right-click > 3D > Edit 3D settings... > 3D Type: spheres > OK.</figcaption>
</figure>

Add polyribosomes to the 3D scene by right clicking on the object in the object list > **3D > Add to scene**.

You may need to lower the opacity of your spine object (d03sp##) to about 0.3-0.4 to see the polyribosomes in the 3D scene: right-click it > **3D > Edit 3D settings...** > Opacity (0-1). The opacity changes right away.

<figure class="class-fig" markdown="span">
  ![3D scene of d03sp31 at opacity 0.4 with d03rh31 and d03rb31 as spheres](img/lab-3-2/06.png){ width="371" }
  <figcaption>d03sp31 at opacity 0.4, with polyribosomes d03rh31 (head) and d03rb31 (base).</figcaption>
</figure>

<figure class="clip" markdown>

![Clip: the 3D scene of d03sp31 at opacity 0.4 with the blue spheres d03rh31 and d03rb31; two drags across the window turn the scene all the way around.](img/lab-3-2/3d-turn-poster.jpg)

[▶ 7 s · loops](videos/lab-3-2/3d-turn.mp4){ .clip-src }

<figcaption markdown>Drag in the 3D window to turn the scene.</figcaption>
</figure>
