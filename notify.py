"""Windows 데스크톱 알림 (의존성 없음, 최선노력).

Wscript.Shell Popup은 지정 초 뒤 자동으로 닫히는 알림창을 띄운다.
실패해도 조용히 무시(알림은 부가기능, 핵심 채널은 alerts.json).
"""

from __future__ import annotations

import subprocess


def notify(title: str, message: str, seconds: int = 12) -> bool:
    title = title.replace('"', "'")
    message = message.replace('"', "'")
    ps = (f'$w = New-Object -ComObject Wscript.Shell; '
          f'$w.Popup("{message}", {seconds}, "{title}", 64) | Out-Null')
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception:
        return False
