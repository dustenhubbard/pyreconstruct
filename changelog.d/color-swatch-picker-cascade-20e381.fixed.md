- **Fixed the color picker opening painted in the last color that was
  applied.** Setting a color painted the swatch button with a selector-less
  `background-color` style rule, and Qt style rules cascade into every
  descendant widget. The picker dialog is a child of the swatch (on purpose:
  that parenting keeps it modal and in front of the dialog that opened it), so
  reopening it showed a solid yellow, green, or purple window instead of a
  normally styled one. Reported with screenshots on Windows and macOS. The
  rule is now scoped to the swatch alone, and a swatch handed a blank color
  now clears its old color instead of keeping it.
