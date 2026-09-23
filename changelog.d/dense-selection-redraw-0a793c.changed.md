- **Faster selection redraws when many visible traces share an object name.**
  The field checks cached traces in one pass per object, while still stopping
  early in sparse views and refreshing replaced traces after attribute edits.
