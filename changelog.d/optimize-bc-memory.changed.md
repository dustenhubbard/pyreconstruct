- **Optimize brightness and contrast needs far less memory on large sections.**
  It used to copy the whole image to floating point first, about 2 GB extra on
  a 16384 by 16384 section. Now it counts the pixel levels in place.
