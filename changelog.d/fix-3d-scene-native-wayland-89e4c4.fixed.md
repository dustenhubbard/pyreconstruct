- **The 3D scene opens on a Linux Wayland desktop instead of closing the app.**
  On a Wayland session such as GNOME on Ubuntu 24.04, adding an object to the
  scene ended the app with no message, because the 3D view asked the X server
  to resize a window that only existed in Wayland. The 3D view now draws
  through Qt's own OpenGL view on Wayland, so it no longer needs
  `QT_QPA_PLATFORM=xcb` to start.
