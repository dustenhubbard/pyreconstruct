- **Opening a series while another is open needs less memory.** The open
  series closes before the new one loads, so the two are never in memory at
  once. If the new series fails to open or the open is canceled, no series
  stays open; open one again from `File`.
