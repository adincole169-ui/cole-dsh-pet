# -*- coding: utf-8 -*-
"""通知：宠物不在前台时，用系统通知告诉用户。

为什么用 PowerShell 而不是第三方库
----------------------------------
Windows 的 toast 需要一个带 AppUserModelID 的快捷方式，或者引入 `win10toast` /
`winrt` 之类的依赖。前者要写注册表、后者要给用户装包——都用不着：PowerShell 的
`Windows.UI.Notifications` 就能弹原生通知，且零依赖。

调用放在**后台线程**：PowerShell 冷启动要几百毫秒，放在 GUI 线程里会让宠物卡一下。
"""

import subprocess
import sys
from threading import Thread

# 单引号里的内容要转义，避免用户/模型文本里的引号把脚本撑破
_SCRIPT = (
    "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] > $null;"
    "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom, ContentType=WindowsRuntime] > $null;"
    "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
    "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
    "$n = $t.GetElementsByTagName('text');"
    "$n.Item(0).AppendChild($t.CreateTextNode(%s)) > $null;"
    "$n.Item(1).AppendChild($t.CreateTextNode(%s)) > $null;"
    "$toast = [Windows.UI.Notifications.ToastNotification]::new($t);"
    "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('大肥鱼桌宠').Show($toast);"
)


def _quote(text):
    return "'" + str(text).replace("'", "''") + "'"


def notify(title, message):
    """异步弹一条系统通知；失败就静默（通知不该影响桌宠本身）。"""
    script = _SCRIPT % (_quote(title), _quote(message))

    def worker():
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                capture_output=True,
                timeout=15,
            )
        except Exception as error:
            sys.stderr.write("dsh-pet: 通知失败: %s\n" % error)

    Thread(target=worker, daemon=True).start()
