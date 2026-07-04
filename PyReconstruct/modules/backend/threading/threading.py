"""

Threading source:

https://www.pythonguis.com/tutorials/multithreading-pyside6-applications-qthreadpool/

"""

import sys
import traceback

from PySide6.QtWidgets import (
    QProgressDialog,
    QProgressBar,
    QApplication,
    QLabel,
    QMessageBox
)

from PyReconstruct.modules.gui.utils import getProgbar

from PySide6.QtCore import (
    QRunnable,
    Slot,
    Signal,
    QObject,
    QThreadPool,
    QEventLoop,
    Qt
)


class WorkerSignals(QObject):
    '''
    Defines the signals available from a running worker thread.

    Supported signals are:

    finished
        No data

    error
        tuple (exctype, value, traceback.format_exc() )

    result
        object data returned from processing, anything

    progress
        int indicating % progress

    '''
    error = Signal(tuple)
    result = Signal(tuple)
    finished = Signal()
    progress = Signal(int)


class Worker(QRunnable, QObject):
    '''
    Worker thread

    Inherits from QRunnable to handler worker thread setup, signals and wrap-up.

    :param callback: The function callback to run on this worker thread. Supplied args and
                     kwargs will be passed through to the runner.
    :type callback: function
    :param args: Arguments to pass to the callback function
    :param kwargs: Keywords to pass to the callback function

    '''

    def __init__(self, fn, *args):
        super(Worker, self).__init__()

        # Store constructor arguments (re-used for processing)
        self.fn = fn
        self.args = args
        self.signals = WorkerSignals()

    @Slot()
    def run(self):
        '''
        Initialise the runner function with passed args.
        '''

        # Retrieve args/kwargs here; and fire processing using them
        try:
            result = self.fn(*self.args)
        except:
            traceback.print_exc()
            exctype, value = sys.exc_info()[:2]
            self.signals.error.emit((exctype, value, traceback.format_exc()))
        else:
            self.signals.result.emit(result)  # Return the result of the processing
        finally:
            self.signals.finished.emit()

class ThreadPool(QThreadPool):
    """Extended from QThreadPool class."""

    def __init__(self):
        """Overwritten from parent class.
        
        Params:
            update (function): the update functino for a loading bar
        """
        super().__init__()
        if self.maxThreadCount() > 10:
            self.setMaxThreadCount(10)
        self.workers = []
        self.n_finished = 0
        self.finished_fn = None

    def createWorker(self, fn, *args):
        """Create and return a worker object.
        
            Params:
                fn (function): the function for the worker to run
                *args: the args to be passed into the function"""
        w = Worker(fn, *args)
        self.workers.append(w)
        return w

class MemoryInt():

    def __init__(self):
        self.n = 0
    
    def inc(self):
        self.n += 1

class ThreadPoolProgBar(ThreadPool):

    def startAll(self, text="", status_bar=None):
        """Start all queued workers and block until they finish.

            Params:
                text (str): the text to display next to the progress indicator
                status_bar: if given, show progress in this status bar instead
                    of a progress dialog
            Returns:
                (bool) True if every worker finished without error
        """
        final_value = len(self.workers)
        maximum = final_value if final_value >= 4 else 0

        lbl = None
        if status_bar is None:
            progbar = getProgbar(text, cancel=False, maximum=maximum)
            if isinstance(progbar, QProgressDialog):
                # show immediately and block interaction with the rest of
                # the app so the series cannot be mutated mid-run
                progbar.setWindowModality(Qt.ApplicationModal)
                progbar.setMinimumDuration(0)
                if maximum == 0:
                    # indeterminate: setValue(0) would hit the maximum and
                    # auto-reset the dialog, so show it directly
                    progbar.show()
                else:
                    progbar.setValue(0)
        else:  # custom progbar for status bar
            lbl = QLabel()
            lbl.setText(text)
            progbar = QProgressBar()
            progbar.setMaximumHeight(status_bar.height() - 6)
            progbar.setMinimum(0)
            progbar.setMaximum(0)
            status_bar.addPermanentWidget(lbl)
            status_bar.addPermanentWidget(progbar)

        counter = MemoryInt()
        errors = []
        loop = QEventLoop()
        use_event_loop = QApplication.instance() is not None

        def onWorkerFinished():
            counter.inc()
            progbar.setValue(counter.n)
            if use_event_loop and counter.n >= final_value:
                loop.quit()

        # queued connections deliver the signals on the GUI thread while
        # the local event loop below is running
        conn_type = Qt.QueuedConnection if use_event_loop else Qt.AutoConnection
        for worker in self.workers:
            worker.signals.error.connect(errors.append, conn_type)
            worker.signals.finished.connect(onWorkerFinished, conn_type)
            self.start(worker)

        # wait for the workers without busy-spinning processEvents
        if use_event_loop:
            if counter.n < final_value:
                if status_bar is None:
                    loop.exec()
                else:
                    # no modal dialog in this mode: keep user input out
                    # while the workers run
                    loop.exec(QEventLoop.ExcludeUserInputEvents)
        else:  # headless (no QApplication): just wait on the pool
            self.waitForDone()

        # tear down the progress indicators
        if status_bar is None:
            progbar.close()
        else:
            status_bar.removeWidget(lbl)
            status_bar.removeWidget(progbar)
            lbl.deleteLater()
            progbar.deleteLater()

        # report any worker errors instead of silently succeeding
        if errors:
            exctype, value, tb_str = errors[0]
            message = (
                f"{len(errors)} of {final_value} task(s) failed.\n\n"
                f"First error:\n\n{tb_str}"
            )
            if QApplication.instance() is not None:
                QMessageBox.critical(None, "Task Error", message)
            else:
                print(message, file=sys.stderr)
            return False

        return True
