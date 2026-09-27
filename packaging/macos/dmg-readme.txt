Install and open @APP_NAME@
==========================

1. Drag @APP_NAME@ onto the Applications folder in this window.
   Wait for copying to finish.

2. Hold the Command key and press the space bar. A search box opens.
   Type Terminal, then press Return. A window with a text prompt opens.

3. Select the entire line below, including the quotation marks.
   Hold Command and press C to copy it:

   xattr -dr com.apple.quarantine "/Applications/@APP_NAME@.app"

4. Click inside the Terminal window. Hold Command and press V to paste.
   Press Return to run the command.

5. If another prompt appears with no message, it worked. Close Terminal.

6. Double-click the Applications folder, then double-click @APP_NAME@.

Next time, open the app normally from Applications.

If Terminal shows an error, copy the message and send it to the person who
sent you this installer. If it says "No such file or directory," check that
step 1 finished and that the app is in Applications.
