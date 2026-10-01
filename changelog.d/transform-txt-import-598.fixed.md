- **Importing transforms from a .txt file skips blank lines and says when it
  fails.** A file that ended with a blank line, or started with a header line,
  imported nothing and still showed the success message. A line that does not
  fit now stops the import with a message that names it.
