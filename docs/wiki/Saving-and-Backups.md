# Saving and Backups

### Saving

**File ▸ Save** (`Ctrl+S`) writes the series back to its `.jser`. **File ▸ Save
as…** writes a copy to a new location. PyReconstruct does **not** auto-save on a
timer, so save regularly. (If you close with unsaved changes, you are prompted to
save; and if a session ends uncleanly, reopening offers to recover it — see
[Opening and creating a series](Opening-and-Creating-a-Series).)

### Backups

A backup is a complete copy of the series saved as an ordinary `.jser` into a
folder you choose, with a filename you configure. There are two ways to make one:

- **File ▸ Backup ▸ Backup now…** (`Ctrl+Shift+B`) — save the current data and write
  a backup, optionally with a comment appended to the filename.
- **Automatic backups** — enable **Auto-backup (create backup on every save)** in
  the backup settings, and a backup is written every time you Save or Save As.

**File ▸ Backup ▸ Settings…** configures the **Backup Folder** and the filename
template, assembled from optional parts — a prefix, the series code, the series
name, the date and time (with customizable strftime patterns), the username, and a
suffix — joined by a delimiter. A live preview shows the resulting filename, and
name collisions get a numeric suffix (`-01`, `-02`, …). The folder and the
auto-backup toggle are remembered **per series**; the naming template is shared
across all series. (The backup folder and naming are also available under **Series ▸
Options ▸ Backup**.)

> 📸 *Screenshot: the Backup Settings dialog showing the folder, the auto-backup checkbox, and the filename preview.*

Because backups are just `.jser` files, **restore a backup by opening it** with
**File ▸ Open**. If the configured backup folder is missing at save time (for
example a disconnected network drive), PyReconstruct prompts you to set it, or
disables auto-backup until you do.

> **Tip.** Keep your backup folder on separate storage from your working `.jser`,
> and turn on auto-backup for active projects.

---
‹ [3D Reconstruction](3D-Reconstruction) · [Home](Home) · [Keyboard Shortcuts](Keyboard-Shortcuts) ›
