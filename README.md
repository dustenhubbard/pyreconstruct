<p align="center">
  <img src="PyReconstruct/assets/img/logo.png" alt="PyReconstruct" width="120">
</p>

<h1 align="center">PyReconstruct</h1>

<p align="center">
  <a href="https://www.gnu.org/licenses/gpl-3.0"><img alt="License: GPL v3" src="https://img.shields.io/badge/License-GPLv3-blue.svg"></a>
</p>

PyReconstruct is an open-source application for annotating and 3D-reconstructing
serial-section and volume electron-microscopy data — a modern, actively
maintained successor to *Reconstruct*, developed in the Kristen Harris Lab at
The University of Texas at Austin.

## Install

### One-click installers (recommended)

Download the latest from **[Releases](https://github.com/dustenhubbard/PyReconstruct/releases)** — no Python required:

- **Windows** — `PyReconstruct-<version>-Windows-x86_64-Setup.exe`. (Builds are
  unsigned for now; if SmartScreen warns, choose **More info → Run anyway**.)
- **macOS (Apple Silicon)** — `PyReconstruct-<version>-macOS-arm64.dmg`, then drag
  PyReconstruct to Applications. Builds are unsigned for now, so the first launch
  is blocked — clear the quarantine flag once in Terminal:
  ```
  xattr -dr com.apple.quarantine /Applications/PyReconstruct.app
  ```

The app keeps itself up to date — **Help ▸ Check for updates** — on a **Release**
(stable) or **Pre-release (experimental)** channel.

### From source (developers)

In a Python 3.11 environment:

```
pip install git+https://github.com/dustenhubbard/PyReconstruct
PyReconstruct
```

## Documentation

Installation guides, a quickstart, and manuals live on the
[lab wiki](https://wikis.utexas.edu/display/khlab/PyReconstruct+user+guide)
(UT Austin) and the [repo wiki](https://github.com/SynapseWeb/PyReconstruct/wiki),
and in-app under **Help ▸ Online resources**.

## Bug reports & feature requests

Found a problem, have a feature idea, or want to improve the docs? Please
**[open an issue](https://github.com/dustenhubbard/PyReconstruct/issues)**.
Thanks for the help!

## Credits

PyReconstruct was created by Michael A. Chirillo, Julian N. Falco,
Michael D. Musslewhite, Larry F. Lindsey, and Kristen M. Harris (Kristen Harris
Lab, Department of Neuroscience, Center for Learning and Memory, The University
of Texas at Austin) and introduced in *PNAS* (2025; see [Citation](#citation)).
It is the modern successor to the original **Reconstruct** by John C. Fiala — a
long-standing, Windows-only serial-section reconstruction program.

This distribution is independently developed and maintained by **Dusten Hubbard**
(Kristen Harris Lab, Department of Neuroscience, Center for Learning and Memory,
The University of Texas at Austin).

## Citation

If you use PyReconstruct in published work, please cite
[the paper](https://doi.org/10.1073/pnas.2505822122):

```
@article{Chirillo2025,
	title = {{PyReconstruct}: {A} fully open-source, collaborative successor to {Reconstruct}},
	author = {Chirillo, Michael A. and Falco, Julian N. and Musslewhite, Michael D. and Lindsey, Larry F. and Harris, Kristen M.},
	journal = {Proceedings of the National Academy of Sciences},
	volume = {122},
	number = {31},
	pages = {e2505822122},
	year = {2025},
	doi = {10.1073/pnas.2505822122},
}
```

## License

[GPL-3.0-or-later](LICENSE.md).
