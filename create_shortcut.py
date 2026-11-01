import os
import sys
import subprocess

def get_desktop_path():
    # 1. Try Windows shell user shell folders registry
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders")
        desktop, _ = winreg.QueryValueEx(key, "Desktop")
        desktop = os.path.expandvars(desktop)
        if os.path.exists(desktop):
            return desktop
    except Exception:
        pass
    # 2. Try OneDrive desktop
    onedrive_desktop = os.path.expandvars(r"%USERPROFILE%\OneDrive\Desktop")
    if os.path.exists(onedrive_desktop):
        return onedrive_desktop
    # 3. Fallback standard desktop
    return os.path.expandvars(r"%USERPROFILE%\Desktop")

def create_shortcut():
    desktop = get_desktop_path()
    shortcut_path = os.path.join(desktop, "Canlı Oyun Çevirici.lnk")
    target_dir = os.path.dirname(os.path.abspath(__file__))
    
    pythonw_venv = os.path.join(target_dir, ".venv", "Scripts", "pythonw.exe")
    if os.path.exists(pythonw_venv):
        target_exe = pythonw_venv
    else:
        target_exe = sys.executable.replace("python.exe", "pythonw.exe")

    script_path = os.path.join(target_dir, "main.py")

    ps_cmd = f"""
    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut('{shortcut_path}')
    $Shortcut.TargetPath = '{target_exe}'
    $Shortcut.Arguments = '"{script_path}"'
    $Shortcut.WorkingDirectory = '{target_dir}'
    $Shortcut.Description = 'Language Translator for Games (Real-Time Game Translator)'
    $Shortcut.IconLocation = 'C:\\Windows\\System32\\imageres.dll, 102'
    $Shortcut.Save()
    """
    
    res = subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], capture_output=True, text=True)
    if res.returncode == 0:
        print(f"Kısayol oluşturuldu: {shortcut_path}")
        return True
    else:
        print(f"Hata: {res.stderr}")
        return False

if __name__ == "__main__":
    create_shortcut()
