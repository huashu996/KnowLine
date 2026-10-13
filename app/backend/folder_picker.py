"""User-operated native folder picker. No directory discovery or catalog writes."""
import os
import threading
from .safety import DomainError

_dialog_lock = threading.Lock()


def _new_dialog(forms):
    return forms.FolderBrowserDialog()


def _raise_owned_dialog(owner_handle):
    """Raise only this STA thread's folder dialog, never another app's window."""
    import ctypes
    from ctypes import wintypes
    user32 = ctypes.WinDLL('user32', use_last_error=True)
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SetWindowPos.restype = wintypes.BOOL
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.EnumThreadWindows.argtypes = [wintypes.DWORD, callback_type, wintypes.LPARAM]
    raised = []

    @callback_type
    def visit(hwnd, _):
        name = ctypes.create_unicode_buffer(80)
        user32.GetClassNameW(hwnd, name, len(name))
        if name.value != '#32770' or user32.GetWindow(hwnd, 4) != owner_handle:
            return True
        # The transparent owner's TopMost flag is not inherited by the native
        # FolderBrowserDialog. Set the actual dialog's z-order after creation.
        if user32.SetWindowPos(hwnd, wintypes.HWND(-1), 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0040 | 0x0200):
            user32.SetForegroundWindow(hwnd)
            raised.append(True)
        return True

    user32.EnumThreadWindows(kernel32.GetCurrentThreadId(), visit, 0)
    return bool(raised)


def _choose_folder():
    import clr
    clr.AddReference('System.Windows.Forms')
    from System.Threading import Thread, ThreadStart, ApartmentState
    import System.Windows.Forms as forms
    result = {'folder': None, 'failed': False}

    def show():
        owner = forms.Form()
        dialog = _new_dialog(forms)
        timer = forms.Timer()
        try:
            owner.Text = '知序 · 导入知识库'
            owner.ShowInTaskbar = False
            owner.TopMost = True
            owner.Opacity = 0
            owner.Show()
            owner.Activate()
            dialog.Description = '选择要导入的知识库文件夹'
            dialog.ShowNewFolderButton = False
            timer.Interval = 50
            def raise_dialog(sender, event):
                if _raise_owned_dialog(owner.Handle.ToInt64()):
                    timer.Stop()
            timer.Tick += raise_dialog
            timer.Start()
            if dialog.ShowDialog(owner) == forms.DialogResult.OK:
                result['folder'] = str(dialog.SelectedPath)
        except Exception:
            result['failed'] = True
        finally:
            timer.Stop()
            timer.Dispose()
            dialog.Dispose()
            owner.Close()
            owner.Dispose()

    thread = Thread(ThreadStart(show))
    thread.SetApartmentState(ApartmentState.STA)
    thread.Start()
    thread.Join()
    if result['failed']:
        raise DomainError('knowledge_folder_picker_failed', 503)
    return result['folder']


def select_folder():
    if os.name != 'nt':
        raise DomainError('knowledge_folder_picker_unavailable', 503)
    if not _dialog_lock.acquire(blocking=False):
        raise DomainError('knowledge_folder_picker_busy', 409)
    try:
        folder = _choose_folder()
        if not folder:
            return {'cancelled': True}
        from .knowledge_import import selected_folder
        return {'cancelled': False, 'folder': str(selected_folder(folder))}
    finally:
        _dialog_lock.release()
