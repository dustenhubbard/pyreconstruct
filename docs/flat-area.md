# Flat area

**Flat area** is a column in the Object List. It measures the area of a surface, such
as a synapse, from the traces of one object. The unit is the square of the series unit
(µm² for a series in micrometers).

## The formula

PyReconstruct adds one term for each trace of the object, on every section:

> Flat area = Σ<sub>sections</sub> [ Σ<sub>open traces</sub> length × T + Σ<sub>closed traces</sub> area ]

- **Open trace** (a line). Its length is the sum of the straight steps between its
  points, Σ √(Δx² + Δy²). PyReconstruct multiplies the length by T, the thickness of
  the section the trace is on.
- **Closed trace** (a loop). Its area comes from the shoelace formula,
  ½ |Σ (x<sub>i</sub>·y<sub>i+1</sub> − x<sub>i+1</sub>·y<sub>i</sub>)|. PyReconstruct
  adds the area with no thickness. A negative closed trace subtracts its area.

Each trace is open or closed, and that alone sets its term. Flat area does not detect
the orientation of a synapse, and it makes no correction for tilt. An open trace on a
tilted surface adds its length × T, which is less than the area of the tilted strip.

## Three synapse orientations

The figures show how the traces can fall for three orientations. Each side view is a
stack of sections, 50 nm thick. The thick line is the synapse seen edge-on. The green
marks are the traces on each section. The trace choices on each section are examples,
not a tracing rule. All traces are positive. The values are chosen so that each case
totals 0.066 µm², with lengths in µm and areas in µm².

<div class="fa-grid">
<div class="fa-card">
<div class="fa-title">1. Cross-sectioned</div>
<div class="fa-sub">The sections cut across the synapse. Each section shows a thin line.</div>
<svg viewBox="0 0 240 172" role="img" aria-label="Side view: a vertical synapse crosses four sections. Each of the four sections has an open trace, L1 to L4.">
<rect class="fa-slab-a" x="10" y="12" width="140" height="26"/><rect class="fa-slab-b" x="10" y="38" width="140" height="26"/><rect class="fa-slab-a" x="10" y="64" width="140" height="26"/><rect class="fa-slab-b" x="10" y="90" width="140" height="26"/><rect class="fa-slab-a" x="10" y="116" width="140" height="26"/><rect class="fa-slab-b" x="10" y="142" width="140" height="26"/>
<line class="fa-psd" x1="80" y1="39" x2="80" y2="141"/>
<line class="fa-open" x1="166" y1="51" x2="196" y2="51"/><line class="fa-open" x1="166" y1="77" x2="204" y2="77"/><line class="fa-open" x1="166" y1="103" x2="202" y2="103"/><line class="fa-open" x1="166" y1="129" x2="194" y2="129"/>
<text class="fa-label" x="210" y="54">L1</text><text class="fa-label" x="210" y="80">L2</text><text class="fa-label" x="210" y="106">L3</text><text class="fa-label" x="210" y="132">L4</text>
<text class="fa-none" x="170" y="29">—</text><text class="fa-none" x="170" y="159">—</text>
</svg>
<div class="fa-math">(L1+L2+L3+L4) × T<br>= (0.30+0.38+0.36+0.28) × 0.05<br>= 1.32 × 0.05<br>= <strong>0.066 µm²</strong></div>
</div>
<div class="fa-card">
<div class="fa-title">2. Oblique</div>
<div class="fa-sub">The sections cut the synapse at an angle. Steep parts show a line. Shallow parts show a wide smear.</div>
<svg viewBox="0 0 240 172" role="img" aria-label="Side view: a bent synapse crosses four sections. The two steep sections have open traces, L1 and L2. The two shallow sections have closed traces, A3 and A4.">
<rect class="fa-slab-a" x="10" y="12" width="140" height="26"/><rect class="fa-slab-b" x="10" y="38" width="140" height="26"/><rect class="fa-slab-a" x="10" y="64" width="140" height="26"/><rect class="fa-slab-b" x="10" y="90" width="140" height="26"/><rect class="fa-slab-a" x="10" y="116" width="140" height="26"/><rect class="fa-slab-b" x="10" y="142" width="140" height="26"/>
<path class="fa-psd" d="M58 39 L72 90 L140 141"/>
<line class="fa-open" x1="166" y1="51" x2="198" y2="51"/><line class="fa-open" x1="166" y1="77" x2="194" y2="77"/>
<ellipse class="fa-closed" cx="184" cy="103" rx="19" ry="8"/><ellipse class="fa-closed" cx="183" cy="129" rx="18" ry="7.5"/>
<text class="fa-label" x="210" y="54">L1</text><text class="fa-label" x="210" y="80">L2</text><text class="fa-label" x="210" y="106">A3</text><text class="fa-label" x="210" y="132">A4</text>
<text class="fa-none" x="170" y="29">—</text><text class="fa-none" x="170" y="159">—</text>
</svg>
<div class="fa-math">(L1+L2) × T + (A3+A4)<br>= (0.32+0.28) × 0.05<br>&nbsp;&nbsp;+ (0.019+0.017)<br>= 0.030 + 0.036<br>= <strong>0.066 µm²</strong></div>
</div>
<div class="fa-card">
<div class="fa-title">3. En face</div>
<div class="fa-sub">The sections are parallel to the synapse. The whole face is in one section.</div>
<svg viewBox="0 0 240 172" role="img" aria-label="Side view: a flat synapse lies inside one section. That section has one closed trace, A.">
<rect class="fa-slab-a" x="10" y="12" width="140" height="26"/><rect class="fa-slab-b" x="10" y="38" width="140" height="26"/><rect class="fa-slab-a" x="10" y="64" width="140" height="26"/><rect class="fa-slab-b" x="10" y="90" width="140" height="26"/><rect class="fa-slab-a" x="10" y="116" width="140" height="26"/><rect class="fa-slab-b" x="10" y="142" width="140" height="26"/>
<line class="fa-psd" x1="30" y1="77" x2="130" y2="77"/>
<ellipse class="fa-closed" cx="186" cy="77" rx="22" ry="10"/>
<text class="fa-label" x="214" y="80">A</text>
<text class="fa-none" x="170" y="29">—</text><text class="fa-none" x="170" y="55">—</text><text class="fa-none" x="170" y="107">—</text><text class="fa-none" x="170" y="133">—</text><text class="fa-none" x="170" y="159">—</text>
</svg>
<div class="fa-math">A (one closed trace)<br>= <strong>0.066 µm²</strong></div>
</div>
</div>

In each case, an open trace adds a strip one section thick, and a closed trace adds the
area it encloses. The same synapse traced at a different orientation can give a
different flat area.

## Flat area and volume

Volume uses closed traces only: Σ closed-trace area × T, where a negative closed trace
subtracts. Open traces add nothing to volume. Flat area uses both kinds of trace, as
above.

## In the code

- `SeriesData.getFlatArea` in `PyReconstruct/modules/datatypes/series_data.py` adds the
  terms.
- `traceGeometry` in `PyReconstruct/modules/calc/quantification.py` measures the length
  and area of each trace.
