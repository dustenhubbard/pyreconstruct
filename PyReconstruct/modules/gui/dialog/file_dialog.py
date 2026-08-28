import os

from PySide6.QtCore import QSettings, QDir
from PySide6.QtWidgets import QFileDialog
from PyReconstruct.modules.constants.settings_domain import settings_domain

class FileDialog(QFileDialog):

    def __init__(self, parent):
        super().__init__(parent)

        # Retrieve the last opened folder path from QSettings
        settings = QSettings(*settings_domain())
        last_folder = settings.value("last_folder", QDir.homePath())

        # Set the current directory to the last opened folder
        self.setDirectory(last_folder)
    
    @staticmethod
    def updateSettings(response):
        """Update last_folder in QSettings based on response."""

        if not response:
            return
        
        if isinstance(response, (tuple, list)):
            response = response[0]
        
        # initialized: a path whose directory vanished between the pick and
        # here (unmounted drive, portal path) hit an UnboundLocalError and
        # crashed the gesture that had just succeeded (found 2026-08-28)
        new_dir = None
        if os.path.isdir(response):
            new_dir = response
        elif os.path.isdir(os.path.dirname(response)):
            new_dir = os.path.dirname(response)
                
        if new_dir:
            settings = QSettings(*settings_domain())
            settings.setValue("last_folder", new_dir)

    @staticmethod
    def get(file_mode: str, parent=None, caption="", filter=None, file_name=""):
        """One gesture, one native dialog, nothing left behind.

        The static QFileDialog functions run the native dialog themselves.
        This used to ALSO construct a FileDialog instance just to be their
        parent: never shown, never deleted, one dead child on the main
        window per gesture for the whole session -- and its setDirectory
        never reached the static dialogs, so the remembered last folder was
        silently dead for the open modes (found 2026-08-28). The remembered
        folder now rides the dir argument, which the statics honor.
        """
        settings = QSettings(*settings_domain())
        last_folder = settings.value("last_folder", QDir.homePath())

        if file_mode == "dir":
            if not caption: caption = "Open Folder"
            response = QFileDialog.getExistingDirectory(parent, caption, last_folder)
        elif file_mode == "file":
            if not caption: caption = "Open File"
            response = QFileDialog.getOpenFileName(parent, caption, dir=last_folder, filter=filter)[0]
        elif file_mode == "files":
            if not caption: caption = "Open Files"
            response = QFileDialog.getOpenFileNames(parent, caption, dir=last_folder, filter=filter)[0]
        elif file_mode == "save":
            if not caption: caption = "Save File"
            d = os.path.join(last_folder, file_name)
            response = QFileDialog.getSaveFileName(parent, caption, dir=d, filter=filter)[0]

        FileDialog.updateSettings(response)
        return response
