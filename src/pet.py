# -*- coding: utf-8 -*-
"""主程序：透明置顶窗口 + 物理 + 交互 + 菜单。

窗口行为对齐 dsh-pet 的桌面端：

* 透明无边框置顶窗口，**只有宠物实心像素接收点击**（透明处鼠标穿透到下层应用）；
* 点击 → 播放点击回应动画 + Q 弹挤压；
* 拖拽 → 过阻尼弹簧跟手；
* 甩出 → 抛物线飞行、屏幕边缘反弹、落地摩擦停稳；
* 屏幕漫游 → 移动动画期间真实前进，先探测空间不走出屏幕；
* 右键菜单 → 动作 / 分类 / 具体动画点播，以及模式、大小、穿透、置顶等；
* 工作状态 → 由 DSH 会话事件驱动（见 dsh_bridge 与 README）。
"""

import math
import os
import random
import sys
import time

from PyQt5.QtCore import QPoint, QRect, QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import (QBitmap, QColor, QFont, QFontMetrics, QIcon, QImage,
                         QPainter, QPainterPath, QPen, QPixmap, QTransform)
from PyQt5.QtWidgets import (QAction, QActionGroup, QApplication, QMenu,
                             QSystemTrayIcon, QWidget)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

from animator import Animator, MoveSpec          # noqa: E402
from chat import ChatClient                      # noqa: E402
from config import PetConfig, load, single_pet   # noqa: E402
from frames import FrameStore                    # noqa: E402
from notify import notify                        # noqa: E402

ICON_PATH = os.path.join(ROOT, "assets", "icon.png")
ICON_ICO = os.path.join(ROOT, "assets", "icon.ico")
# 碎碎念逐步日志。写成模块级常量而不是在函数里拼路径：第一版用了 `ROOT`，
# 而 pet.py 里并没有这个变量，NameError 被 except 吞掉，日志为空被误读成
# "函数没被调用"，白白多查了一轮。
WHISPER_STEPS_LOG = os.path.join(ROOT, "logs", "whisper-steps.log")
# 拖动诊断日志：每次"按下 -> 松手"记一行。
#
# 为什么值得单独记：用户报"拖不动、松手回出生点"时，两种可能的原因给出的
# 处置完全不同，而**光看现象分不出来**：
#   * 按下根本没到桌宠（窗口掩膜不含那一点 / 事件被别的窗口吃掉）
#     -> 日志里连 press 行都不会有；
#   * 按到了但窗口没跟着动（自动对齐把它拽回去 / 鼠标抓取被打断）
#     -> 有 press 行，但位移接近 0。
# 这条日志只在用户主动拖动时写一行，不会刷屏。
DRAG_LOG = os.path.join(ROOT, "logs", "drag.log")
MEME_DIR = os.path.join(ROOT, "memes")
FONT_FAMILY = "Microsoft YaHei UI"
# 「给用户看的名字」只有一个来源：`config.jsonc` 里的 `displayName`（见 `PetConfig`）。
# 这里留一个**兜底常量**，用于配置里没写 displayName 的情况。
#
# 为什么不在这里写死名字：早先窗口标题用的是 `config.name`（内部物种名，同时也是
# 素材目录键），于是任务栏里显示的是"蓝毛小女仆"而不是用户叫的"大肥鱼"；
# 而托盘提示又硬编了另一个字符串——同一只宠物在三处名字都不一样。
DEFAULT_DISPLAY_NAME = "大肥鱼"
# 启动后多久之内，掩膜一变就重新按角色对齐初始位置（秒）。
# 需要它是因为不同动画的角色宽度不同，启动时会连切几个动画；只对齐一次会偏十几像素。
# 窗口期结束后不再自动对齐，否则用户把宠物拖到别处后一换动画就会被拽回角落。
SETTLE_WINDOW_SEC = 4.0
# alpha 高于这个值才算"实心"，用于生成输入掩膜的边界。
# 这套素材的"透明"是**低 alpha**而不是 0（背景 alpha 1–8、角色约 17% 面积），
# 所以阈值要卡在两者之间；取太小会把背景也算成实心，取太大则会把角色边缘裁掉。
MASK_ALPHA_MIN = 16
# 气泡里表情包画成多大（像素）。原来按气泡高度放大到约 50px，用户觉得太大。
STICKER_SIZE = 38
# 气泡尖角与头顶之间留的空隙（像素）
BUBBLE_TAIL_GAP = 6
# 气泡再往画面里压多少像素。精灵帧顶部自带约 31px 透明边（实测占帧高 17.4%~17.8%），
# 压进这段透明区之后，视觉上气泡就贴着头发了，而不会盖住脸。
BUBBLE_SINK = 26
# 系统通知的最小间隔（秒）。DSH 状态变化很频繁，不限流会刷屏。
NOTIFY_COOLDOWN = 90.0
FPS_MS = 33
DT = FPS_MS / 1000.0


def screen_area_for(point):
    """返回全局坐标 `point` 所在屏幕的**可用区域**（多显示器安全）。

    为什么不直接用 `QApplication.screenAt()`：那个 API 是 **Qt 5.10** 才有的，
    而本项目要在 PyQt5 5.9.2（Qt 5.9.7）上跑。所以退回到遍历 `screens()`。
    """
    screens = QApplication.screens()
    for screen in screens:
        if screen.geometry().contains(point):
            return screen.availableGeometry()
    if screens:
        # 落在所有屏幕之外（例如正被拖到两块屏中间的空隙）：取中心最近的那块
        def distance(screen):
            centre = screen.geometry().center()
            return (centre.x() - point.x()) ** 2 + (centre.y() - point.y()) ** 2
        return min(screens, key=distance).availableGeometry()
    return QApplication.primaryScreen().availableGeometry()


# 工作状态档位 → 配置里 events.workStatus 的哪一档。
# 文案取自 workStatusTexts（六组，和档位一一对应）。
MOOD_ORDER = ("thinking", "busy", "filing", "roaming", "celebrating", "sighing")
MOOD_TO_TIER = {
    "thinking": 0, "busy": 1, "filing": 2, "roaming": 3, "celebrating": 4, "sighing": 5,
    "approval": 0,
}
# 值得弹系统通知的状态：这两档是**一次性事件**（干完了 / 出错了），不是持续状态。
# 其余几档（思考/忙碌/归档/漫游）会连续变化，拿它们通知只会刷屏。
NOTIFY_MOODS = {
    "celebrating": "干完啦",
    "sighing": "出错了",
}


def mask_bitmap(mask_image):
    """把"可点区域"的图变成 `QBitmap`。

    **黑 = 位置位 = 可点，白 = 位清零 = 点击穿透**（与直觉相反，实测得出）。
    调用方只要保证"想让它可点的地方是黑的"即可。

    写成一个模块级函数是有意的：掩膜的位语义在这个项目里反复出错，独立出来才能单独
    测（`tools/probe_mask_bits.py`），而不是每次都要起一个真窗口去猜。
    """
    return QBitmap.fromImage(mask_image.convertToFormat(QImage.Format_Mono))


def solid_bitmap(solid_bytes, width, height):
    """"实心区域"（numpy 阈值算出的白=实心）直接变成掩膜位图。

    全程只做一次格式转换：先按 alpha 阈值得到白=实心的灰阶图，取反成黑=实心，
    再转 1bpp。不再叠加 `QBitmap.fromImage` 的二次处理——它因图而异（全白图可用、
    半白半黑却被整体清零），那正是气泡整块被裁掉的原因。
    """
    image = QImage(solid_bytes, width, height, width, QImage.Format_Grayscale8)
    image = image.copy()          # QImage 不持有这份 bytes，必须立刻复制
    image.invertPixels()          # 白=实心 -> 黑=可点
    return mask_bitmap(image)


def user_is_watching():
    """用户是不是正看着 DSH。

    用 `GetForegroundWindow` 取前台窗口的**进程名**来判断，而不是 Qt 的焦点事件。
    原因：桌宠窗口带 `WA_ShowWithoutActivating`，**本来就极少拿到焦点**，所以
    `focusInEvent`/`focusOutEvent` 那对事件基本不会成对发生——原先用
    "先获得过焦点、再失去焦点"作为通知条件，结果是通知几乎永远不弹。

    早先这里还接受一个 `pet_name`（想把"桌宠自己在前台"也算作在看），但传进去的是
    **内部物种名**，而进程名是 `pythonw.exe`，永远匹配不上——是个没用的分支，已去掉。

    前台判断失败时**返回 False**（即允许通知）：宁可多弹一条，也不要让这个功能
    静默失效——那正是它之前的状态。
    """
    if not sys.platform.startswith("win"):
        return False
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        handle = user32.GetForegroundWindow()
        if not handle:
            return False
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(pid))
        if not pid.value:
            return False
        # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000，够拿镜像名
        process = kernel32.OpenProcess(0x1000, False, pid.value)
        if not process:
            return False
        try:
            size = wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(1024)
            if not kernel32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
                return False
        finally:
            kernel32.CloseHandle(process)
        return os.path.basename(buffer.value) in ("DeepSeek Harness.exe", "dsh.exe")
    except Exception:
        return False


def make_icon():
    """窗口与托盘图标。

    优先用**多尺寸的 .ico**：任务栏按钮要 16/32px、托盘要 16/24/32px、alt-tab 要
    更大，Qt 从 `.ico` 里能直接取到对应档位；只给一张 256 的 PNG 时它每次都要现缩，
    小尺寸下细节会糊。`.png` 作为兜底。

    **两个文件都缺时不再静默**：返回空 QIcon 的效果是"窗口和任务栏都没有图标"，
    而用户看不出原因。曾经把 `assets/` 整个排除在仓库外，从 GitHub 装的人就是
    "图标是没有的"。所以这里写一行 stderr 指路。
    """
    if os.path.exists(ICON_ICO):
        icon = QIcon(ICON_ICO)
        if not icon.isNull() and icon.availableSizes():
            return icon
    if os.path.exists(ICON_PATH):
        return QIcon(ICON_PATH)
    sys.stderr.write(
        "dsh-pet: 找不到图标 %s / %s —— 窗口与任务栏将没有图标。\n"
        "         生成方式: python tools/make_icon.py\n"
        % (os.path.relpath(ICON_ICO, ROOT), os.path.relpath(ICON_PATH, ROOT)))
    return QIcon()


class PetWindow(QWidget):
    """一只宠物一个窗口；物理与绘制都在这里。"""

    frame_changed = pyqtSignal()
    # 联动桥是普通线程，所有控制都经这个信号回到 GUI 线程
    mood_signal = pyqtSignal(str, dict)

    def __init__(self, config, store, parent=None):
        super(PetWindow, self).__init__(parent)
        self.config = config
        self.store = store
        self.animator = Animator(store, config, self)
        self.animator.moved.connect(self.on_move)
        # 后台加载完成 → 在 GUI 线程把帧接上（QPixmap 不能跨线程构造）
        store.loaded.connect(self.animator.on_loaded)

        # 初始模式：`fixedEnabled = true` 就当作"原地待着"启动。
        # 这两个原本是两个各自独立的字段——`mode` 只在菜单里赋值（没人读），
        # `fixedEnabled` 只被解析成属性（也没人读），所以"固定住"这件事有两条
        # 都没接线的路。现在统一到 `set_mode()` 一处实现。
        self.mode = "still" if bool(getattr(config, "fixedEnabled", False)) else "roam"
        self.animator.set_movement_allowed(self.mode != "still")
        # 手动走动标记：右键「走走看」会置位，使那一次走动不被"原地待着"拦住。
        # 必须在 `on_move` 可能被触发之前就存在。
        self._manual_move = False

        # --- 联动状态 -------------------------------------------------------- #
        self.mood = "idle"
        self.mood_deadline = 0.0
        self.bubble = None            # [文字, 剩余秒数]
        self.bubble_image = None      # QPixmap 或 None
        self.top_pad = 0              # 气泡占用的顶部高度（0 = 不占）
        self.chat_port = int(config.position.get("chatPort") or 8900)
        self.usage_tier = None
        self._ever_focused = False
        # 上一次弹系统通知的时刻（`time.monotonic()`），用于限流
        self._last_notify = 0.0
        # 上一次碎碎念的时刻（按 `tick` 累计的秒数），用于按周期自己触发
        self._clock_t = 0.0
        self._last_whisper = 0.0
        # 碎碎念每一步的流水，供 `/whisperlog` 查——排查"点了没反应"时不用再猜
        self.whisper_log = []
        # 输入掩膜：透明区域不该挡住下层应用
        self._mask_key = None
        self.bubble_rect = None
        self._source_masks = {}
        # 掩膜位的方向。实测判定（tools/mask_direction.py）：
        #   mask_invert=False -> 显示 37 像素（几乎全被裁掉）
        #   mask_invert=True  -> 显示 10004 像素（与不带掩膜的基准 9998 一致）
        # 也就是说：把这个灰阶图转成 QBitmap 时，**黑才是置位（可见）**，与我原先的
        # 假设正好相反。默认用 True；配置里 maskInvert 可覆盖。
        value = config.position.get("maskInvert")
        self.mask_invert = True if value is None else bool(value)
        self.mask_stats = None
        # 启动窗口期"按角色对齐"的绝对截止时刻（见 _settle_initial_placement）：
        # __init__ 里调 _place_initial 时还没有帧/掩膜，拿不到角色的真实左右留白，
        # 所以要等掩膜算好之后再对齐一次；`_settle_deadline` 在下面首次摆放后设置。
        # 这里**不能**再留一个 `_placed_at` 之类的字段 —— 那个旧写法每次对齐都续期，
        # 导致窗口永不结束（用户报的"拖不动、松手回出生点"）。
        self._settle_deadline = None
        self.mood_signal.connect(self.on_bridge_message)

        # --- 窗口 ----------------------------------------------------------- #
        self.setWindowTitle(self.display_name())
        # 只保留 WA_TranslucentBackground：再加 WA_NoSystemBackground 会让窗口在
        # Windows 上合成成"什么都没有"（窗口存在、坐标正常、就是不上屏）。
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setWindowFlags(self._flags())
        self.setWindowIcon(make_icon())
        self.setMouseTracking(True)

        # --- 物理状态 ------------------------------------------------------- #
        self.vx = 0.0
        self.vy = 0.0
        self.grounded = True
        self.dragging = False
        self.drag_offset = QPoint(0, 0)
        self.drag_history = []
        self.press_pos = None
        self.squash = 1.0            # 1 = 原始；>1 压扁
        self.squash_target = 1.0

        self.size_px = max(120, int(config.size))
        self._resize_window()
        # 首次摆放，然后把"启动对齐"的截止时刻设成**绝对**的一刻。
        # 只能在首次摆放后设一次：早先的写法是每次对齐都刷新计时，
        # 而掩膜在播放动画时持续变化、每次变化都会再对齐一次 —— 于是窗口被无限续期，
        # 宠物在每个动画帧都被搬回出生点。用户若有一次按下没落在角色掩膜上
        # （`dragging` 起不来），就会看到"拖不动、松手又回到出生点"。
        self._place_initial()
        self._settle_deadline = time.monotonic() + SETTLE_WINDOW_SEC

        # --- 事件与时钟 ------------------------------------------------------ #
        self.animator.frame_changed = self.frame_changed
        self.paint_clock = QTimer(self)
        self.paint_clock.timeout.connect(self._repaint)
        self.paint_clock.start(FPS_MS)
        self.physics_clock = QTimer(self)
        self.physics_clock.timeout.connect(self.tick)
        self.physics_clock.start(FPS_MS)

        self._build_menu()
        self._build_tray()
        self.animator.next_auto()

    # -- 时钟 ---------------------------------------------------------------- #
    def _repaint(self):
        """每帧先更新输入掩膜，再重绘。"""
        self._apply_input_mask()
        self.update()

    def tick(self):
        """由 main 的统一定时器驱动：气泡计时 + 物理 + 碎碎念周期。"""
        self._clock_t += DT
        self._tick_bubble()
        self.step_physics()
        self._maybe_whisper()

    # -- 窗口 ---------------------------------------------------------------- #
    def _flags(self):
        flags = Qt.FramelessWindowHint | Qt.Window | Qt.WindowDoesNotAcceptFocus
        if self.config.position.get("topmost", True):
            flags |= Qt.WindowStaysOnTopHint
        return flags

    def sprite_size(self):
        """按配置宽度等比得到精灵绘制尺寸。"""
        animation = self.animator.playing.animation if self.animator.playing else None
        ratio = 9.0 / 16.0
        if animation and animation.width:
            ratio = animation.height / float(animation.width)
        width = self.size_px
        return width, max(1, int(round(width * ratio)))

    def _resize_window(self):
        """窗口 = 精灵尺寸 + 顶部气泡留白。

        气泡必须画在精灵上方，而窗口只有和精灵一样高就没地方画了；所以说话的
        时候把窗口往上长一块，精灵仍然贴着窗口底部——这样"脚底永远在窗口底部"
        这个不变式得以保持，气泡和物理都不用另外改写。
        """
        width, height = self.sprite_size()
        self.setFixedSize(width, height + int(self.top_pad))

    def _place_initial(self):
        """把窗口放到配置指定的角落，**并且站在地面上**。

        坐标只在**一个**体系里算：`availableGeometry()` 与 `move()` 都是 Qt 的逻辑
        坐标。这里绝不能拿 `frameGeometry()` 去求偏移——那在 125% DPI 下是物理坐标，
        混用会让 x 变成约 1.33 倍，宠物直接被放到屏幕外（曾丢过一次：窗口在
        (2073, 104)，而屏幕只有 1707 宽）。

        纵向的默认值是**地面**而不是"距顶 marginY"：重力会立刻把它拽到地面，所以
        按"距顶 100px"摆放只会让它先出现在右上角、然后掉到屏幕最底被任务栏挡住——
        那看起来就是"宠物消失了"。想让它真的挂在上方，要写 `corner: top-*` **并且**
        关掉重力（`physics.gravity: 0`）。

        对齐的是**宠物当前所在那块屏**：多显示器时若一律按主屏算，副屏上的宠物
        点「回到初始位置」会被搬到主屏去。
        """
        area = self.current_screen_area()
        position = self.config.position
        corner = str(position.get("corner") or "bottom-right")
        margin_x = int(position.get("marginX", 24))
        margin_y = int(position.get("marginY", 100))
        width, height = self.width(), self.height()
        # 按**角色**而不是窗口对齐屏幕边：窗口左右各有透明留白，用窗口对齐会让角色
        # 看起来没贴到边。margin 量的是"角色边缘到屏幕边缘"的距离。
        inset_left, inset_right = self.character_insets()
        if "left" in corner:
            x = area.left() + margin_x - inset_left
        else:
            x = area.right() - width + inset_right - margin_x
        # 上下由 corner 决定。**重力不参与这个判断**——重力只决定它随后会不会往下掉，
        # 不该决定"摆在哪一角"。原先写成 `if "top" in corner or not use_gravity()`，
        # 于是 `corner: bottom-right` 配上 `gravity: 0`（本机配置正是如此）会被摆到
        # **顶部**，与配置语义相反。
        if "top" in corner:
            y = area.top() + margin_y
        else:
            # 贴地：底部留出 margin_y，避免被任务栏压住
            y = area.bottom() - height - margin_y
        # 无论配置怎么写，都必须落在屏幕内
        x = max(area.left() - inset_left,
                min(area.right() - width + inset_right, x))
        y = max(area.top(), min(area.top() + area.height() - height, y))
        self.pos_x, self.pos_y = float(x), float(y)
        self.vy = 0.0
        self.vx = 0.0
        self.move(int(self.pos_x), int(self.pos_y))
        # 注意：这里**不碰** `_settle_deadline`。对齐的截止时刻由调用方负责：
        # `__init__` 在首次摆放后设一次；`_user_took_over()` 把它清掉。
        # 早先在这里写 `self._placed_at = time.monotonic()`，等于每次都续期，
        # 让"启动期"永不结束（见 __init__ 里的说明）。

    def apply_flags(self):
        visible = self.isVisible()
        self.setWindowFlags(self._flags())
        if visible:
            self.show()

    # -- 物理 ---------------------------------------------------------------- #
    def use_gravity(self):
        """重力是否生效。

        `gravity: 0` 表示"不要重力"：宠物停在放下它的地方，不会自己往屏幕底部沉。
        首次摆放也要看这个开关——否则关掉重力后它仍会被按"地面"摆放，然后停在
        屏幕最底（那正是"它总是跑到下面挡着我"的来源）。
        """
        try:
            return float(self.config.physics.get("gravity", 1400)) > 0.0
        except (TypeError, ValueError):
            return True

    def ground_line(self):
        """"地面"对应的窗口 y（窗口底部贴着屏幕底部）。

        这里**故意用窗口高度**而不是角色的可见底边：角色脚底就画在窗口底部
        （`sprite_rect` 让精灵贴着 `top_pad + height`），所以窗口底 == 角色底。
        左右方向则不同——那里的透明留白在**两侧**，所以贴边要用 `character_insets()`。

        "地面"取**宠物所在那块屏**的底部：多显示器时，用主屏的地面会让副屏上的
        宠物掉到一个够不着的高度（或者被吸回主屏）。
        """
        area = self.current_screen_area()
        return float(area.bottom() - self.height())

    def set_mode(self, key):
        """切换"自由活动 / 原地待着"。

        原先菜单只是 `setattr(self, "mode", k)`，而**没有任何代码读这个属性**——
        所以"原地待着"是个纯装饰，宠物照样会自己走开（用户报的 bug）。

        现在真正接线：`still` 会禁掉**自动**移动（含把已交代给物理层的速度收回），
        但右键菜单的「走走看」仍可用——那是用户主动点的，不该被模式挡住。
        """
        self.mode = key
        self.animator.set_movement_allowed(key != "still")
        if key == "still":
            # 立刻停下，不等惯性把它拖走
            self.vx = 0.0
            self.vy = 0.0

    def on_move(self, vx, walking):
        """动画机说"该走了"。走动时朝向与速度一起交给物理。

        **"原地待着"的拦截点就在这里**，而不是在 `step_physics` 里无条件清零 `vx`：
        后者会把用户主动点的「走走看」也一起掐掉（实测就是如此——`move_left` 正常
        递减、`vx` 却始终为 0）。分工应当是：`Animator` 那一层不自动挑移动动画，
        这一层拒绝自动移动产生的速度，而**手动**走动带 `_manual_move` 标记放行。
        """
        if walking and vx:
            if self.mode == "still" and not self._manual_move:
                return
            self.animator.facing = 1 if vx > 0 else -1
            self.vx = vx
            return
        # 复位要等**移动真的结束**（`animator.move` 被清空），不能见到
        # `walking=False` 就复位——移动动画有 2 秒前导，前导期间每帧都发
        # `moved(0, False)`，那样会把刚刚置上的手动标记在第 0 帧就抹掉，
        # 于是"手动走走看"在手仍然走不了（实测就是这么失败的）。
        if self.animator.move is None:
            self._manual_move = False

    def current_screen_area(self):
        """宠物**当前所在屏幕**的可用区域。

        为什么要按"所在屏幕"而不是一律取 `primaryScreen()`：多显示器时，
        把宠物拖到副屏之后，物理的墙壁判定若仍按主屏来算，一松手就会把它
        拽回主屏的边角 —— 用户看到的正是"拖过去，松手就消失、又出现在出生点"。
        拖动过程中 `step_physics` 跳过墙壁判定，所以问题只在松手后暴露。

        用**窗口中心**判定所在屏幕：宠物贴边时有一圈透明留白挂在屏幕外，
        但中心一定还在屏内。

        注意启动最早期：`__init__` 里 `_place_initial()` 是在 `pos_x` 赋值**之前**
        调的，这时还没有位置可用 —— 直接退回主屏（宠物本来就诞生在主屏）。
        """
        pos_x = getattr(self, "pos_x", None)
        pos_y = getattr(self, "pos_y", None)
        if pos_x is None or pos_y is None:
            return QApplication.primaryScreen().availableGeometry()
        centre = QPoint(int(pos_x + self.width() / 2.0),
                        int(pos_y + self.height() / 2.0))
        return screen_area_for(centre)

    def step_physics(self):
        # 用宠物所在的那块屏，不用 primaryScreen（见 current_screen_area）
        area = self.current_screen_area()
        if not self.dragging:
            # 重力：`gravity: 0` 表示不要重力，宠物停在原处不再下沉
            if self.use_gravity():
                self.vy += float(self.config.physics.get("gravity", 1400)) * DT
            self.pos_y += self.vy * DT
            floor = self.ground_line()
            if self.pos_y >= floor:
                self.pos_y = floor
                if abs(self.vy) > 60.0:
                    # 落地：反弹并按挤压曲线压一下
                    self.vy = -self.vy * float(self.config.physics.get("restitution", 0.78))
                    self.squash_target = 1.28
                else:
                    self.vy = 0.0
                    if not self.grounded:
                        self.squash_target = 1.18
                    self.grounded = True
                if self.grounded:
                    friction = float(self.config.physics.get("groundFriction", 2.5))
                    self.vx -= self.vx * min(1.0, friction * DT)
                    if abs(self.vx) < 4.0:
                        self.vx = 0.0
            else:
                self.grounded = False
                # 无重力时不能一直保留竖直速度，否则抛出去会朝一个方向永远飘走
                if abs(self.vy) > 0.0:
                    self.vy -= self.vy * min(1.0, 1.6 * DT)
                    if abs(self.vy) < 6.0:
                        self.vy = 0.0
                # **关掉重力时必须自己衰减水平速度。**
                #
                # 为什么：`gravity: 0` 时宠物永远落不到 `ground_line()`（它悬在
                # 放下它的地方），于是上面那个 `if self.pos_y >= floor` 分支
                # **永远不成立**、`self.grounded` 永远是 False —— 而水平摩擦只写在
                # `if self.grounded:` 里面。结果是**任何残余 vx 都永不衰减**：
                # 实测注入 vx=60，5 秒后还剩 -46.80（正好是撞左墙的
                # `60 * restitution 0.78`），也就是说除了撞墙，一点摩擦都没有。
                #
                # 用户看到的现象就是"自由活动时其他动作也在动"：宠物在播
                # 「待机呼吸休闲」这种完全不该移动的动作时，仍以约 5.7 px/s 恒定向右滑。
                # （见 tools/selftest_no_drift.py）
                #
                # 语义上也说得通：关掉重力 = "宠物待在放下它的地方"，那它就是在
                # "停着"，水平速度当然该像地面摩擦一样衰减。
                # 重力**开着**时这里不动：那种情况下 `else` 分支意味着"宠物被抛在空中"，
                # 水平速度保持才是对的（抛物线）。
                if not self.use_gravity():
                    friction = float(self.config.physics.get("groundFriction", 2.5))
                    self.vx -= self.vx * min(1.0, friction * DT)
                    if abs(self.vx) < 4.0:
                        self.vx = 0.0

            # "原地待着"模式：**自动移动**产生的速度要被清掉。拦在 `on_move` 里是
            # 主手段，这里再兜一道——因为惯性、以及别的路径给 `self.vx` 赋的值都会
            # 在这里生效。**手动**走动带 `_manual_move` 标记，放行。
            if self.mode == "still" and not self._manual_move:
                self.vx = 0.0
            self.pos_x += self.vx * DT

            # 左右墙与天花板。
            # 用**角色的可见边界**去贴屏幕边，而不是窗口矩形：窗口比角色宽，
            # 拿窗口贴边等于贴住那圈透明留白，角色会停在离屏幕边约一个留白的地方
            # （用户报的"最右侧了但没到屏幕最右"）。
            inset_left, inset_right = self.character_insets()
            if self.pos_x + inset_left < area.left():
                self.pos_x = float(area.left() - inset_left)
                self.vx = -self.vx * float(self.config.physics.get("restitution", 0.78))
                self.animator.facing = 1
            elif self.pos_x + self.width() - inset_right > area.right():
                self.pos_x = float(area.right() - self.width() + inset_right)
                self.vx = -self.vx * float(self.config.physics.get("restitution", 0.78))
                self.animator.facing = -1
            if self.config.physics.get("ceilingBounce") and self.pos_y < area.top():
                self.pos_y = float(area.top())
                self.vy = -self.vy * float(self.config.physics.get("restitution", 0.78))

        # 挤压回弹（弹簧回 1.0）
        self.squash += (self.squash_target - self.squash) * min(1.0, 10.0 * DT)
        self.squash_target += (1.0 - self.squash_target) * min(1.0, 6.0 * DT)

        self.move(int(self.pos_x), int(self.pos_y))

    def roam(self):
        """让动画机挑一段移动动作（右键菜单"走走看"用）。

        这是**用户主动**要求的走动，所以打上标记：即便当前是"原地待着"，
        这一次也照走——菜单上那个模式管的是"别自己乱跑"，不是"禁止我让它走"。
        """
        specs = self.animator._move_specs()
        if specs:
            self._user_took_over()      # 用户主动让它走：停止启动期的自动对齐
            self._manual_move = True
            self.animator.start_move(random.choice(specs))

    def display_name(self):
        """给用户看的名字（任务栏、托盘提示、系统通知都用它）。

        **与 `config.name` 分开**：后者是内部物种名，同时也是素材目录与物种配置的键
        （`pet/<name>-config.json`），改它会连带影响那些地方。这个纯是面子。
        """
        name = str(getattr(self.config, "display_name", "") or "").strip()
        return name or DEFAULT_DISPLAY_NAME

    # -- 绘制 ---------------------------------------------------------------- #
    def sprite_rect(self):
        """精灵在窗口里的绘制矩形（含 Q 弹挤压）。

        绘制与输入掩膜**共用这一个矩形**：掩膜如果按未挤压的原始尺寸算，被拉宽的那
        部分就会落在掩膜之外，于是"图像显示不全"（裁掉手脚/裙边）。
        """
        width, height = self.sprite_size()
        draw_w = width * self.squash
        draw_h = height / self.squash
        return QRectF((self.width() - draw_w) / 2.0,
                      self.top_pad + height - draw_h,
                      draw_w, draw_h)

    def character_bounds(self):
        """角色**可见部分**在窗口坐标系里的左右边界 (left, right)。

        为什么需要它：窗口宽度是按 `size` 定的，而这套素材里角色只占画面中间一块。
        实测（`size=320` 逻辑）：

            帧 640x360，角色 bbox 约 226x256 —— 只占画面宽的 35%
            窗口 320 逻辑，掩膜包围盒 [108, 32, 105, 133]
            -> 角色可见宽仅 105 逻辑像素，左右各约 107 是透明留白

        所以拿**窗口**去贴屏幕边，贴住的是那圈看不见的留白：角色会停在离屏幕边
        约 107px 的地方。用户报的"已经是最右侧了，但不是屏幕的最右侧"就是这个。

        **数据源是掩膜的实际包围盒**，不是 `sprite_rect()`：后者是窗口内的绘制矩形
        （每段动画等宽），跟角色实际占哪儿无关——第一版就是错在这里，算出留白为 0。
        掩膜正是 `setMask` 决定"实际显示什么、哪里能点"的那个区域，用它才准。

        掩膜还会把**气泡**算进去：气泡在角色上方，横向通常比角色窄，但如果某句话
        很长、气泡比角色宽，包围盒就会变宽。这里取角色与气泡的**并集左/右边**，
        贴边时以更宽的那个为准，避免说话时角色被推出屏幕。
        """
        stats = getattr(self, "mask_stats", None) or {}
        rect = stats.get("rect")
        if rect:
            left = float(rect[0])
            right = float(rect[0] + rect[2])
            # 掩膜可能带 2px 余量（_build_input_bitmap 的 margin），无妨
            return max(0.0, left), min(float(self.width()), right)
        # 还没算过掩膜（启动瞬间）：退回绘制矩形，至少不会崩
        draw = self.sprite_rect()
        return draw.left(), draw.right()

    def character_insets(self):
        """角色离窗口左右边缘的距离 (left, right)。用于按角色而不是窗口对齐屏幕边。"""
        left, right = self.character_bounds()
        return left, max(0.0, self.width() - right)

    def _draw_sprite(self, painter, pixmap):
        """把一帧按当前尺寸与 Q 弹挤压画到画布上（脚底贴着 anchor）。"""
        if pixmap is None or pixmap.isNull():
            return
        painter.drawPixmap(self.sprite_rect(), pixmap, QRectF(pixmap.rect()))

    def _build_input_bitmap(self, frame, rect, bubble):
        """按**当前绘制矩形**尺寸算出输入掩膜。

        关键是顺序：**先把画面缩放到绘制尺寸，再在该尺寸上做一次阈值**。反过来
        （在原始分辨率算掩膜、再用 `QBitmap.transformed` 缩放 1bpp 位图）在这台机器上
        不可靠——实测会把角色本体裁掉，看起来就是"图像几乎看不到"。而且缩放 1bpp 位图
        本身也会把细笔画吃掉。

        掩膜比绘制矩形四周各留 2px 余量：Q 弹挤压是连续变化的，边缘那几像素不该被切。
        """
        margin = 2
        box_w = max(1, int(round(rect.width())) + margin * 2)
        box_h = max(1, int(round(rect.height())))
        left = int(round(rect.left())) - margin
        top = int(round(rect.top()))

        # 按绘制尺寸重采样，再取 alpha 阈值——这是唯一一次逐像素运算
        scaled = frame.toImage().convertToFormat(QImage.Format_ARGB32)
        if scaled.width() != box_w or scaled.height() != box_h:
            scaled = scaled.scaled(box_w, box_h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        solid = self._threshold_bytes(scaled)

        # 拼成整窗掩膜。**用 numpy 直接填**，不走 QPainter：
        # `QPainter.fillRect` 在 `Format_Grayscale8` 画布上实测**完全不生效**
        # （填 255 之后该点读出来仍是 0），于是气泡那条永远进不了掩膜——
        # 用户看到的就是"碎碎念成功了、但屏幕上没有气泡"。
        #
        # 约定：255（白）= 可点，最后统一取反成"黑=可点"再转 1bpp。
        #
        # 合成时**必须取逐点较大值**，不能直接覆盖：精灵在气泡那一段是透明的
        # （阈值后为 0），直接覆盖会把气泡的"可点"抹掉。实测后果是气泡掩膜只剩
        # 上半 30px，下半截被透明像素覆盖，表现为"气泡下面一小部分被遮挡"。
        width, height = self.width(), self.height()
        try:
            import numpy as np
            canvas = np.zeros((height, width), dtype=np.uint8)
            if bubble is not None and not bubble.isEmpty():
                # 气泡那一条**必须并进来**：`setMask` 同时裁绘制，掩膜里没有的区域
                # 连画都画不出来。用气泡的**实际矩形**而不是整条横带——整条横带会让
                # 可点比例从 0.26 涨到 0.95，掩膜等于白做。
                by0 = max(0, int(bubble.top()))
                by1 = min(height, int(bubble.bottom()) + 1)
                bx0 = max(0, int(bubble.left()))
                bx1 = min(width, int(bubble.right()) + 1)
                if by1 > by0 and bx1 > bx0:
                    canvas[by0:by1, bx0:bx1] = 255
            solid_array = np.frombuffer(solid, dtype=np.uint8).reshape(box_h, box_w)
            sy0 = max(0, top)
            sy1 = min(height, top + box_h)
            sx0 = max(0, left)
            sx1 = min(width, left + box_w)
            if sy1 > sy0 and sx1 > sx0:
                piece = solid_array[sy0 - top:sy1 - top, sx0 - left:sx1 - left]
                np.maximum(canvas[sy0:sy1, sx0:sx1], piece,
                           out=canvas[sy0:sy1, sx0:sx1])
            payload = canvas.tobytes()
        except ImportError:
            canvas = bytearray(width * height)
            if bubble is not None and not bubble.isEmpty():
                for row in range(max(0, int(bubble.top())),
                                 min(height, int(bubble.bottom()) + 1)):
                    start = max(0, int(bubble.left()))
                    end = min(width, int(bubble.right()) + 1)
                    if end > start:
                        canvas[row * width + start:row * width + end] = b"\xff" * (end - start)
            for row in range(box_h):
                target = top + row
                if target < 0 or target >= height:
                    continue
                line = solid[row * box_w:(row + 1) * box_w]
                start = max(0, left)
                end = min(width, left + box_w)
                if end <= start:
                    continue
                offset = start - left
                for column in range(start, end):
                    value = line[offset + column - start]
                    if value > canvas[target * width + column]:
                        canvas[target * width + column] = value
            payload = bytes(canvas)

        return solid_bitmap(payload, width, height)

    def _threshold_bytes(self, image):
        """把一张 ARGB 图按 alpha 阈值变成 `width*height` 字节的灰阶掩膜数据。

        用 numpy 算，不用 Python 逐像素循环：同一张 640×360 的帧，逐像素循环要
        **137 ms**（每帧都付这个代价，直接掉到 7fps），numpy 只要几毫秒。本机自带
        numpy 1.18.5，不必新增依赖。没有 numpy 时退回循环，慢但不会崩。
        """
        width, height = image.width(), image.height()
        stride = image.bytesPerLine()
        # 必须**显式**给出字节数：`sip.voidptr` 自己不知道大小，直接 bytes() 会报
        #   IndexError: sip.voidptr object has an unknown size
        # 而尺寸变化时若沿用 `byteCount()` 又可能拿到 0，于是 setsize(0) 再写就报
        #   ValueError: cannot modify the size of a sip.voidptr object
        # 后一个异常在 Qt 回调里没人接住，进程会带致命码直接退出（"点一下就没了"）。
        # 这里两者都避开：只读、且自己算字节数。
        pointer = image.constBits()
        pointer.setsize(stride * height)
        raw = bytes(pointer)

        try:
            import numpy as np
            array = np.frombuffer(raw, dtype=np.uint8).reshape(height, stride)
            alpha = array[:, :width * 4].reshape(height, width, 4)[:, :, 3]
            return ((alpha > MASK_ALPHA_MIN).astype(np.uint8) * 255).tobytes()
        except ImportError:
            return bytes(
                255 if raw[y * stride + x * 4 + 3] > MASK_ALPHA_MIN else 0
                for y in range(height) for x in range(width))

    def _apply_input_mask(self):
        """把窗口的**输入区域**裁到"角色 + 气泡"的实际占位上。

        窗口是个矩形，默认整个矩形都会吃掉鼠标——包括宠物四周那圈完全透明的角落。
        那圈看不见，却是实打实挡着下层应用的（用户原话："占用区域太大，会挡住我操作
        其他地方"）。设置窗口 mask 后，掩膜之外的点击会**穿透到下层窗口**，这才是真正
        意义上的"占用区域变小"，而不只是把画面缩小。

        **掩膜必须包含气泡**：`setMask` 不只限制点击，它同时**裁掉绘制**——掩膜里没有
        的区域连画都画不出来。早期版本漏了这一点，表现为"碎碎念成功了、但屏幕上没有
        气泡"。气泡用它的**实际矩形**而不是整条横带，否则可点比例会从 0.26 涨到 0.95，
        掩膜等于白做。

        重建只在帧/尺寸/气泡/挤压变化时发生。
        """
        pad = int(self.top_pad)
        bubble = self.bubble_rect if (self.bubble or self.bubble_image is not None) else None
        frame = self.animator.current_frame()
        if frame is None or frame.isNull():
            key = ("noframe", self.width(), self.height(), pad)
            if key == self._mask_key:
                return
            # 没有可画帧时：可点区域只留气泡那一块；连气泡都没有就按整窗可点。
            # **绝不能是空掩膜**——实测 Windows 上 `clearMask()` 得到的空区域等于
            # 没有可点区域，窗口会变得既不可见也点不到。宁可短暂多占一点点击。
            width, height = self.width(), self.height()
            canvas = bytearray(width * height)
            if bubble is None or bubble.isEmpty():
                canvas = bytearray(b"\xff" * (width * height))
            else:
                for row in range(max(0, int(bubble.top())),
                                 min(height, int(bubble.bottom()) + 1)):
                    start = max(0, int(bubble.left()))
                    end = min(width, int(bubble.right()) + 1)
                    if end > start:
                        canvas[row * width + start:row * width + end] = b"\xff" * (end - start)
            bitmap = solid_bitmap(bytes(canvas), width, height)
            self.setMask(bitmap)
            self._mask_key = key
            self.mask_stats = self._mask_stats(bitmap)
            return
        rect = self.sprite_rect()
        # 气泡矩形也要进 key：气泡一变（出现/消失/换行导致高度变化）掩膜必须重建，
        # 否则它仍按旧几何，把气泡裁掉。
        bubble_key = None
        if bubble is not None and not bubble.isEmpty():
            bubble_key = (int(bubble.left()), int(bubble.top()),
                          int(bubble.width()), int(bubble.height()))
        key = (frame.cacheKey(), self.width(), self.height(), pad, bubble_key,
               int(rect.left()), int(rect.top()), int(rect.width()), int(rect.height()))
        if key == self._mask_key:
            return

        bitmap = self._build_input_bitmap(frame, rect, bubble)
        self.setMask(bitmap)
        self._mask_key = key
        self.mask_stats = self._mask_stats(bitmap)
        self._settle_initial_placement()

    def _settle_initial_placement(self):
        """启动阶段：等**掩膜算好**之后，按角色对齐初始位置；之后几秒内跟随掩膜修正。

        为什么需要：`_place_initial()` 是在 `__init__` 里调的，那一刻还没有帧、没有
        掩膜，`character_insets()` 只能退回绘制矩形（左右留白算成 0）。于是"按角色
        贴边"这个修正根本没用上——实测角色右边缘停在离屏幕右边 117px 处，而不是
        marginX 的 24px。

        为什么要跟随几秒：不同动画的角色宽度不同（`mask.rect` 实测在 105~238 之间
        浮动），启动时会连切几个动画，只对齐第一次仍会偏（实测偏 14px）。

        **截止时刻是绝对的、且只设一次**（`_settle_deadline`）。这一点是硬要求：
        掩膜在播放动画时持续变化，如果每次对齐都续期，这个"启动期"就永远不会结束，
        宠物会在每个动画帧被搬回角落 —— 用户看到的就是"拖不动、松手回到出生点"。

        **用户一碰就永久停止**（`_user_took_over()`）：否则他刚把宠物拖到别处，
        一换动画就会被拽回角落。
        """
        if self.dragging:
            return
        deadline = getattr(self, "_settle_deadline", None)
        if deadline is None:
            return
        if time.monotonic() > deadline:
            # 过期就彻底关掉，省得每帧都来算一次
            self._settle_deadline = None
            return
        self._place_initial()

    def _user_took_over(self):
        """用户开始自己摆布宠物了：停止启动期的自动对齐。

        由鼠标按下、「走走看」等**用户主动**的移动调用。自检里也可以直接调它，
        把"启动期自动对齐"关掉，这样测的是物理/模式逻辑而不是摆放逻辑。
        """
        self._settle_deadline = None

    def _mask_stats(self, bitmap):
        """占用区域的量化指标。

        用**掩膜区域的几何面积**而不是去数位图的灰阶：`QBitmap.toImage()` 的灰阶与
        置位之间的对应又要再翻一层（掩膜方向本身就已经反了一次，见 `mask_invert`），
        数灰阶很容易得到互补的错误数字。区域面积没有这层歧义：

            cover = 掩膜包围矩形面积 / 窗口面积

        接近 1.0 说明整个矩形都在挡人；0.2~0.3 说明只占了角色本体那一片。
        """
        region = self.mask()
        if region is None or region.isEmpty():
            return {"cover": 0.0, "rect": None}
        rect = region.boundingRect()
        total = max(1, self.width() * self.height())
        return {
            "cover": round(rect.width() * rect.height() / float(total), 3),
            "rect": [rect.left(), rect.top(), rect.width(), rect.height()],
            "window": [self.width(), self.height()],
        }

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.Antialiasing, True)

        # 交叉淡化：垫层（上一段的最后一帧）先满不透明地铺上，新段再叠上去淡入。
        # 只让新段淡入而不铺垫层，中间会出现两头都透明的空档——那正是"切换动作时
        # 短暂消失"的成因。
        outgoing = self.animator.outgoing_frame()
        alpha = self.animator.fade_alpha()
        ready = self.animator.playing is not None and self.animator.playing.ready
        if outgoing is not None and ready and alpha < 1.0:
            painter.setOpacity(1.0)
            self._draw_sprite(painter, outgoing)

        painter.setOpacity(alpha)
        self._draw_sprite(painter, self.animator.current_frame())
        painter.setOpacity(1.0)

        if self.bubble or self.bubble_image is not None:
            self._draw_bubble(painter, self.sprite_size()[0])
        painter.end()

    def _draw_bubble(self, painter, width):
        """气泡：左侧可选配图 + 右侧文字，整体画在精灵上方。

        配图放在**左侧**、按 `STICKER_SIZE` 画成小图（原来是横向铺满气泡的 50px，
        用户觉得"太大"）。小图竖排在文字旁边，气泡因此也更窄。
        """
        area = QRectF(4, 2, self.width() - 8, max(24.0, self.top_pad - 6.0))
        has_image = self.bubble_image is not None and not self.bubble_image.isNull()

        text = self.bubble[0] if self.bubble else ""
        font = QFont(FONT_FAMILY, 9)
        metrics = QFontMetrics(font)

        # 配图固定边长（不再随气泡高度放大），并给文字让出宽度
        sticker = STICKER_SIZE if has_image else 0
        gap = 5 if has_image else 0
        max_w = max(40, self.width() - 28 - sticker - gap)

        lines, current = [], ""
        for char in text:
            if metrics.width(current + char) > max_w:
                lines.append(current)
                current = char
            else:
                current += char
        if current or not lines:
            lines.append(current)

        line_h = metrics.height()
        text_w = max([metrics.width(line) for line in lines] or [0])
        box_w = min(self.width() - 8, sticker + gap + text_w + 18)
        box_h = max(sticker, line_h * len(lines)) + 12
        box_x = (self.width() - box_w) / 2.0
        # 气泡紧贴留白区下沿：留白高度就是按气泡算出来的（见 `bubble_size`），
        # 所以这样画出来必然是"离本体最近"。不再去推"角色头顶在第几像素"——
        # 之前用帧内透明边比例去估，结果气泡在渲染里跑到了窗口顶部。
        # `BUBBLE_SINK` 让它再往画面里压一点：精灵帧顶部自带约 31px 透明边，
        # 压进这段透明区之后，视觉上气泡就贴着头发了（不会盖住脸）。
        box_y = self.top_pad - box_h - BUBBLE_TAIL_GAP + BUBBLE_SINK
        if box_y < 0:
            box_y = 0.0
        if box_y + box_h > self.height():
            box_y = max(0.0, self.height() - box_h)

        path = QPainterPath()
        path.addRoundedRect(QRectF(box_x, box_y, box_w, box_h), 9, 9)
        tail = QPainterPath()
        tail.moveTo(self.width() / 2.0 - 7, box_y + box_h - 1)
        tail.lineTo(self.width() / 2.0, box_y + box_h + 7)
        tail.lineTo(self.width() / 2.0 + 7, box_y + box_h - 1)
        path.addPath(tail)

        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(24, 28, 38, 224))
        painter.drawPath(path)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(120, 170, 255, 130), 1.0))
        painter.drawPath(path)

        # 记下气泡的**实际矩形**：输入掩膜要用它，而不是整条横带。
        # 用整条横带会让可点比例从 0.26 涨到 0.95，等于白做掩膜。
        self.bubble_rect = QRectF(box_x, box_y, box_w, box_h + 8)

        text_x = box_x + 9
        if has_image:
            image_x = box_x + 9
            image_y = box_y + (box_h - sticker) / 2.0
            painter.drawPixmap(QRectF(image_x, image_y, sticker, sticker),
                               self.bubble_image, QRectF(self.bubble_image.rect()))
            text_x = image_x + sticker + gap

        painter.setPen(QColor(233, 240, 255))
        block_h = line_h * len(lines)
        first_baseline = box_y + (box_h - block_h) / 2.0 + line_h - metrics.descent() - 1
        for index, line in enumerate(lines):
            painter.drawText(int(text_x), int(first_baseline + line_h * index), line)

    def _apply_top_pad(self, millimetres):
        """气泡出现/消失时改变窗口高度，并保持"窗口底部不动"。"""
        previous = self.top_pad
        self.top_pad = int(millimetres)
        if self.top_pad == previous:
            return
        bottom = self.pos_y + self.height()
        self._resize_window()
        self.pos_y = bottom - self.height()
        self.move(int(self.pos_x), int(self.pos_y))

    # -- 联动桥 -------------------------------------------------------------- #
    def bubble_size(self, text, has_image):
        """按当前文本与是否有配图算出气泡的尺寸（与 `_draw_bubble` 用同一套规则）。

        单独提出来是因为留白高度要用它：**留白 = 气泡高度**，气泡再贴着留白下沿画，
        这样气泡距本体必然是最近的，不需要去猜"角色头顶在哪一像素"——先前就是靠猜
        （用帧内透明边的比例去推），结果气泡在渲染里落到了窗口顶部。
        """
        font = QFont(FONT_FAMILY, 9)
        metrics = QFontMetrics(font)
        sticker = STICKER_SIZE if has_image else 0
        gap = 5 if has_image else 0
        max_w = max(40, self.width() - 28 - sticker - gap)
        lines, current = [], ""
        for char in text or "":
            if metrics.width(current + char) > max_w:
                lines.append(current)
                current = char
            else:
                current += char
        if current or not lines:
            lines.append(current)
        line_h = metrics.height()
        text_w = max([metrics.width(line) for line in lines] or [0])
        box_w = min(self.width() - 8, sticker + gap + text_w + 18)
        box_h = max(sticker, line_h * len(lines)) + 12
        return box_w, box_h

    def say(self, text, image=None, seconds=6.0):
        text = (text or "").strip()
        if image:
            self.bubble_image = self._load_image(image)
        else:
            self.bubble_image = None
        has_image = self.bubble_image is not None and not self.bubble_image.isNull()
        # 留白 = 气泡高度 + 一点余量（容纳尖角），气泡就在这段里贴着下沿画
        _box_w, box_h = self.bubble_size(text, has_image)
        need = int(box_h + BUBBLE_TAIL_GAP + 4) if text else 0
        self._apply_top_pad(need)
        self.bubble = [text, float(seconds)] if text else None
        self.update()
        return box_h

    def clear_bubble(self):
        self.bubble = None
        self.bubble_image = None
        self._apply_top_pad(0)
        self.update()

    def _load_image(self, name_or_path):
        """表情包：接受直接路径，或 memes 目录下的文件名/键名。"""
        candidates = []
        if os.path.isabs(name_or_path) and os.path.exists(name_or_path):
            candidates.append(name_or_path)
        else:
            for base in (name_or_path, name_or_path + ".png", name_or_path + ".webp"):
                candidates.append(os.path.join(MEME_DIR, base))
        for path in candidates:
            if os.path.exists(path):
                pixmap = QPixmap(path)
                if not pixmap.isNull():
                    return pixmap
        return None

    def apply_usage(self, tier, text=""):
        """用量分档：复用 `events.balance` 的六档动画 + 头顶气泡。

        原本这里应该是"账户余额分档"，但当前 DSH（0.1.0-rc.7）**没有任何余额/额度
        API**，硬编一个数字就是假的。所以改用**真实可得的会话用量**（轮次/步数）分档：
        档位、动画、气泡的位置都与原设计一致，只有"输入量"换成了能拿到的那个。
        以后若有余额接口，把调用方换成余额即可，这里不用改。
        """
        if not bool(getattr(self.config, "balanceEnabled", True)):
            # 关掉了就不该有任何分档表现（连气泡都不冒）
            return False
        names = self.config.event_animations("balance")
        if not names:
            return False
        index = max(0, min(len(names) - 1, int(tier)))
        self.animator.set_work_status_by_anim(names[index])
        self.usage_tier = index
        if text:
            self.say(text, None, 10.0)
        else:
            self.say("本轮用量：第 %d 档" % (index + 1), None, 6.0)
        return True

    def place(self, payload):
        """把宠物搬到指定位置（或屏幕正中）并抬到最前。

        "宠物不见了"时这是最有效的恢复手段：不用猜它去了哪，直接把它挪回屏幕中央
        并重新抬到 Z 序顶部。抬 Z 序是必要的——窗口虽然带 TOPMOST，但被别的置顶
        窗口压住时，`raise_()` 是唯一能把它重新顶出来的动作。
        """
        if payload.get("size"):
            self.size_px = max(120, int(payload["size"]))
            self._resize_window()
        # 显式摆放（`/place`、菜单「回到初始位置」）也算"用户接管"：否则启动期的
        # 自动对齐会把它又拽回角落——实测 `/place {"center":true}` 之后角色中心
        # 停在 1203 而不是屏幕中心 640。
        self._user_took_over()
        # 居中对齐用**宠物当前所在屏幕**，不是主屏：多显示器时按主屏居中，
        # 会把副屏上的宠物直接搬到主屏中央。
        area = self.current_screen_area()
        if payload.get("center") or (payload.get("x") is None and payload.get("y") is None):
            # 居中的是**角色**而不是窗口：窗口左右有透明留白，按窗口居中会让角色
            # 看起来偏了一点。
            inset_left, inset_right = self.character_insets()
            character_width = self.width() - inset_left - inset_right
            self.pos_x = float(area.left()
                               + (area.width() - character_width) / 2.0
                               - inset_left)
            self.pos_y = float(area.top() + (area.height() - self.height()) / 2)
            self.vy = 0.0
            self.vx = 0.0
        else:
            if payload.get("x") is not None:
                self.pos_x = float(payload["x"])
            if payload.get("y") is not None:
                self.pos_y = float(payload["y"])
        self.move(int(self.pos_x), int(self.pos_y))
        self.show()
        self.raise_()
        self.update()

    def on_bridge_message(self, kind, payload):
        """在 GUI 线程处理桥消息。"""
        if kind == "say":
            self.say(payload.get("text", ""), payload.get("image") or None,
                     payload.get("seconds") or 6.0)
            return
        if kind == "anim":
            self.animator.play(payload.get("name", ""), loop=bool(payload.get("loop")))
            return
        if kind == "usage":
            self.apply_usage(payload.get("tier", 0), payload.get("text", ""))
            return
        if kind == "place":
            self.place(payload)
            return
        if kind == "whisper":
            self.whisper_now(announce=bool(payload.get("announce", True)))
            return
        if kind == "mode":
            self.set_mode(payload.get("mode", "roam"))
            return
        if kind == "mood":
            self.apply_mood(payload.get("mood", "idle"), payload.get("text", ""),
                            payload.get("image") or None)

    def apply_mood(self, mood, text="", image=None):
        """把 DSH 侧的状态映射到六档动画 + 对应文案。

        `workStatusEnabled = false` 时**完全忽略**状态推送（只保留台词气泡），否则
        用户关掉了开关却发现宠物照样跟着会话切动画。
        """
        mood = (mood or "idle").strip().lower()
        enabled = bool(getattr(self.config, "workStatusEnabled", True))
        if mood in ("idle", "clear", "none"):
            self.mood = "idle"
            self.animator.set_work_status(None)
            if text:
                self.say(text, image)
            return
        if not enabled:
            if text or image:
                self.say(text, image)
            return

        tier = MOOD_TO_TIER.get(mood, 0)
        # 动画：配置里 events.workStatus 的第 tier 档
        events = self.config.animations.get("events") or {}
        names = events.get("workStatus") if isinstance(events, dict) else None
        if isinstance(names, list) and names:
            self.animator.set_work_status_by_anim(names[tier % len(names)])
        else:
            self.animator.set_work_status("workStatus-%d" % tier)

        self.mood = mood
        # 文案：workStatusTexts 的第 tier 组，随机取一句
        if not text:
            texts = self.config.work_status_texts
            if tier < len(texts) and isinstance(texts[tier], list) and texts[tier]:
                text = random.choice(texts[tier])
        if text or image:
            self.say(text, image)
        self.mood_deadline = 0.0
        # 一次性事件（干完了 / 出错了）才通知，且只在用户没看 DSH 时弹。
        # 挂在**状态本身**而不是焦点事件上：桌宠窗口带 `WA_ShowWithoutActivating`，
        # 焦点事件基本不成对发生，用焦点做触发条件等于永远不弹（原先就是这样）。
        if mood in NOTIFY_MOODS:
            self._maybe_notify("%s：%s" % (NOTIFY_MOODS[mood], self.display_name()))

    def _tick_bubble(self):
        if self.bubble:
            self.bubble[1] -= DT
            if self.bubble[1] <= 0:
                self.clear_bubble()

    # -- 对话与碎碎念 -------------------------------------------------------- #
    def open_chat(self):
        """弹一个小输入框，把提问交给 DSH 侧的模型服务。"""
        from PyQt5.QtWidgets import QInputDialog
        self.chat_client = ChatClient(self.chat_port, self.config)
        if not self.chat_client.available():
            self.say("连不上 DSH 的模型服务呢…（插件没启用？）", None, 5.0)
            return
        text, ok = QInputDialog.getText(self, "和大肥鱼说句话", "说点什么：")
        if not ok or not text.strip():
            return
        self.say("让我想想…", None, 30.0)

        def done(reply, image):
            node = self.mood_signal
            node.emit("say", {"text": reply or "……", "image": image, "seconds": 9.0})

        def failed(reason):
            node = self.mood_signal
            node.emit("say", {"text": "想不出来了…（%s）" % reason[:24], "seconds": 5.0})

        self.chat_client.ask(text.strip(), done, failed, kind="chat")

    def whisper_now(self, announce=True):
        """触发一次碎碎念。

        `whisperEnabled = false` 时**连周期触发一起关掉**——否则用户在配置里关掉了
        碎碎念，插件那边仍按自己的定时器每 5 分钟推一句（那个定时器在插件侧）。

        每一步都记进 `self.whisper_log`：我在独立进程里测得通，但用户那只不出气泡，
        差别只能在"这一只进程的内部状态"上，所以让它自己把过程报出来，而不是在外面猜。
        """
        def note(step, detail=""):
            line = "%s %s%s" % (time.strftime("%H:%M:%S"), step,
                                (" | " + str(detail)) if detail else "")
            self.whisper_log.append(line)
            del self.whisper_log[:-40]
            # 同时落盘并 **flush**：崩溃是靠致命信号退出的，Python 层留不下 traceback，
            # 所以必须每走一步就写穿到磁盘，才能看出死在哪一行。
            # 注意：这里**不能**静默吞异常——第一次就是这么栽的：路径变量名写错、
            # NameError 被 except 吃掉，于是"日志是空的"被误读成"函数没被调用"。
            try:
                with open(WHISPER_STEPS_LOG, "a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception as error:
                sys.stderr.write("dsh-pet: 写碎碎念日志失败: %s\n" % error)

        note("whisper_now 被调用", "announce=%s" % announce)
        if not bool(getattr(self.config, "whisperEnabled", False)):
            note("跳过：配置里 whisperEnabled=false")
            if announce:
                self.say("碎碎念已经在配置里关掉了呢", None, 4.0)
            return
        self.chat_client = ChatClient(self.chat_port, self.config)
        if not self.chat_client.available():
            note("跳过：探不到模型服务", "port=%s" % self.chat_port)
            if announce:
                self.say("碎碎念要连 DSH 才行呢…", None, 5.0)
            return
        note("模型服务可用，准备发请求")
        if announce:
            self.say("……", None, 20.0)
            note("已显示占位气泡", "bubble=%s" % (self.bubble,))

        def done(reply, image):
            note("on_done 回调", "reply=%r image=%r" % (reply, image))
            node = self.mood_signal
            node.emit("say", {"text": reply or "……", "image": image, "seconds": 8.0})

        def failed(_reason):
            note("on_error 回调", _reason)
            if announce:
                node = self.mood_signal
                node.emit("say", {"text": "……", "seconds": 3.0})

        self.chat_client.ask("说一句碎碎念。", done, failed, kind="whisper")
        note("请求已发出（异步）")

    def _maybe_whisper(self):
        """按 `eventsRefreshSec.whisper` 的周期自己触发碎碎念。

        放在桌宠这一侧是有意的：只有桌宠知道 `whisperEnabled` 与周期配置，插件那边
        的定时器无法读到它们。插件收到 `kind=whisper` 的请求时就不再自行周期触发。
        """
        if not bool(getattr(self.config, "whisperEnabled", False)):
            return
        period = float(self.config.refresh.get("whisper", 300) or 300)
        if period <= 0:
            return
        # 用窗口自己的累计时钟（`tick` 里推进），周期触发才有依据
        now = self._clock_t
        if now - self._last_whisper < period:
            return
        self._last_whisper = now
        self.whisper_now(announce=False)

    # -- 鼠标 ---------------------------------------------------------------- #
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            # 用户开始自己摆布了：停止启动期的自动对齐，别把它拽回角落
            self._user_took_over()
            self.press_pos = event.globalPos()
            # 只记按下点，不记 frameGeometry 的偏移：拖动全程用 globalPos 与 pos() 的
            # 差量推进，避免再踩一次逻辑/物理坐标混用的坑。
            self.drag_offset = QPoint(self.pos_x - event.globalPos().x(),
                                      self.pos_y - event.globalPos().y())
            self.dragging = True
            self.drag_history = [(self.pos_x, self.pos_y)]
            self.animator.play_drag()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.dragging:
            target_x = event.globalPos().x() + self.drag_offset.x()
            target_y = event.globalPos().y() + self.drag_offset.y()
            # 过阻尼弹簧跟手：直接跳到位会显得僵硬
            self.pos_x += (target_x - self.pos_x) * 0.55
            self.pos_y += (target_y - self.pos_y) * 0.55
            self.drag_history.append((self.pos_x, self.pos_y))
            del self.drag_history[:-6]
            self.move(int(self.pos_x), int(self.pos_y))
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        moved = (event.globalPos() - self.press_pos).manhattanLength() if self.press_pos else 0
        start = self.drag_history[0] if self.drag_history else (self.pos_x, self.pos_y)
        self.dragging = False
        self.press_pos = None
        # 记一行拖动诊断：位移为 0 还是没记，直接区分"没按到"与"按到了没动"
        self._log_drag(start, (self.pos_x, self.pos_y), moved)
        power = float(self.config.physics.get("throwPower", 1.0))
        if moved < 6:
            self.squash_target = 1.3
            self.animator.play_click()
        else:
            # 甩抛：用最近几帧的位移估算速度
            if len(self.drag_history) >= 2:
                (x0, y0), (x1, y1) = self.drag_history[0], self.drag_history[-1]
                self.vx = (x1 - x0) / (DT * len(self.drag_history)) * power
                self.vy = (y1 - y0) / (DT * len(self.drag_history)) * power
            self.vy = min(self.vy, 0.0) if abs(self.vy) > 1400 else self.vy
        event.accept()

    def _log_drag(self, start, end, moved):
        """把一次"按下 -> 松手"记进 `logs/drag.log`。

        用户报"拖不动"时，两种原因的现象一样但处置完全不同，靠猜会走弯路：

          * **连这一行都没有** -> 按下根本没到桌宠。查窗口掩膜（`setMask` 同时裁输入）、
            是否有别的置顶窗口吃掉了点击、以及那一点是否落在角色的透明区域。
          * **有这一行但窗口位移约 0** -> 按到了，但窗口没跟着动。查自动对齐是否
            还在生效（`_settle_deadline`）、以及拖动中 `setMask` 是否打断了鼠标抓取。

        只写用户主动拖动的次数，不会刷屏；出错也绝不能影响拖动本身。
        """
        try:
            os.makedirs(os.path.dirname(DRAG_LOG), exist_ok=True)
            with open(DRAG_LOG, "a", encoding="utf-8") as handle:
                handle.write("%s press=收到 moved=%d window=(%.0f,%.0f)->(%.0f,%.0f) "
                             "settle=%s anim=%s\n"
                             % (time.strftime("%m-%d %H:%M:%S"), moved,
                                start[0], start[1], end[0], end[1],
                                "还在生效" if self._settle_deadline else "已关闭",
                                (self.animator.playing.name
                                 if self.animator.playing else "")))
        except Exception:
            # 记日志失败不该影响拖动。但**不留静默 except**：写到 stderr，
            # 免得以后又把"日志为空"误读成"没被调用"（这个坑踩过）。
            sys.stderr.write("dsh-pet: 拖动日志写入失败\n")

    def contextMenuEvent(self, event):
        self.menu.popup(event.globalPos())
        event.accept()

    # -- 失焦通知 ------------------------------------------------------------ #
    def _maybe_notify(self, message):
        """在合适的时机弹一条系统通知。

        触发条件是"**用户没有在看 DSH**"（前台窗口不是 DSH、也不是桌宠自己），
        而不是 Qt 的焦点事件——桌宠窗口带 `WA_ShowWithoutActivating`，本来就极少
        拿到焦点，用焦点事件做判断等于永远不弹。

        限流 `NOTIFY_COOLDOWN`：DSH 状态变化很频繁，不限制会刷屏。
        """
        if not bool(getattr(self.config, "notificationsEnabled", True)):
            return False
        now = time.monotonic()
        if now - self._last_notify < NOTIFY_COOLDOWN:
            return False
        if user_is_watching():
            return False
        self._last_notify = now
        notify(self.display_name(), message)
        return True

    def focusOutEvent(self, event):
        """宠物被切到后台时，用系统通知说一句。

        这条路径只在**窗口确实获得过焦点**时才有意义（例如用户点过宠物）；
        常规的"DSH 干完活了"通知走 `apply_mood`，那里不依赖焦点。
        """
        super(PetWindow, self).focusOutEvent(event)
        if not self._ever_focused:
            return
        self._maybe_notify(self.display_name() + "在后台等你了")

    def focusInEvent(self, event):
        super(PetWindow, self).focusInEvent(event)
        self._ever_focused = True

    # -- 菜单 ---------------------------------------------------------------- #
    def _build_menu(self):
        menu = QMenu(self)
        self.menu = menu

        actions_menu = menu.addMenu("动作点播")
        self._fill_actions(actions_menu)

        roam = QAction("走走看", menu)
        roam.triggered.connect(lambda _c: self.roam())
        menu.addAction(roam)

        say = QAction("点一下", menu)
        say.triggered.connect(lambda _c: self.animator.play_click())
        menu.addAction(say)

        chat = QAction("聊两句…", menu)
        chat.triggered.connect(lambda _c: self.open_chat())
        menu.addAction(chat)

        whisper = QAction("现在碎碎念一句", menu)
        whisper.triggered.connect(lambda _c: self.whisper_now())
        menu.addAction(whisper)

        menu.addSeparator()
        sizes = menu.addMenu("大小")
        group = QActionGroup(sizes)
        group.setExclusive(True)
        for px in (240, 320, 420, 520, 640):
            act = QAction("%d px" % px, sizes)
            act.setCheckable(True)
            act.setChecked(abs(self.size_px - px) < 4)
            act.triggered.connect(lambda _c, p=px: self.set_size(p))
            group.addAction(act)
            sizes.addAction(act)

        mode = menu.addMenu("模式")
        mgroup = QActionGroup(mode)
        mgroup.setExclusive(True)
        for key, label in (("roam", "自由活动"), ("still", "原地待着")):
            act = QAction(label, mode)
            act.setCheckable(True)
            act.setChecked(getattr(self, "mode", "roam") == key)
            act.triggered.connect(lambda _c, k=key: self.set_mode(k))
            mgroup.addAction(act)
            mode.addAction(act)

        menu.addSeparator()
        reset = QAction("回到初始位置", menu)
        reset.triggered.connect(lambda _c: self._place_initial())
        menu.addAction(reset)

        top = QAction("总在最前", menu)
        top.setCheckable(True)
        top.setChecked(bool(self.config.position.get("topmost", True)))
        top.triggered.connect(lambda c: (self.config.position.__setitem__("topmost", bool(c)), self.apply_flags()))
        menu.addAction(top)

        quit_act = QAction("退出", menu)
        quit_act.triggered.connect(lambda _c: QApplication.instance().quit())
        menu.addAction(quit_act)

    def _fill_actions(self, parent_menu):
        """动作 → 分类 → 具体动画，任意点播。"""
        idle = self.config.actions("idle")
        if idle:
            sub = parent_menu.addMenu("待机")
            for name in idle:
                act = QAction(name, sub)
                act.triggered.connect(lambda _c, n=name: self.animator.play(n, loop=True))
                sub.addAction(act)

        moves = self.animator._move_specs()
        if moves:
            sub = parent_menu.addMenu("移动")
            for spec in moves:
                act = QAction(spec.name, sub)
                act.triggered.connect(lambda _c, s=spec: self.animator.start_move(s))
                sub.addAction(act)

        for category in self.config.animations.get("categories") or []:
            if not isinstance(category, dict):
                continue
            actions = category.get("actions") or []
            if not actions:
                continue
            sub = parent_menu.addMenu(str(category.get("id") or "?"))
            for name in actions:
                act = QAction(name, sub)
                act.triggered.connect(lambda _c, n=name: self.animator.play(n))
                sub.addAction(act)

        events = self.config.animations.get("events") or {}
        if isinstance(events, dict):
            for group, names in events.items():
                if not isinstance(names, list) or not names:
                    continue
                sub = parent_menu.addMenu(str(group))
                for name in names:
                    act = QAction(name, sub)
                    act.triggered.connect(lambda _c, n=name: self.animator.play(n, loop=True))
                    sub.addAction(act)

        clicks = self.config.actions("clicks")
        if clicks:
            sub = parent_menu.addMenu("点击回应")
            for name in clicks:
                act = QAction(name, sub)
                act.triggered.connect(lambda _c, n=name: self.animator.play(n))
                sub.addAction(act)

    def _build_tray(self):
        icon = make_icon()
        if icon.isNull():
            self.tray = None
            return
        self.tray = QSystemTrayIcon(icon, self)
        self.tray.setToolTip(self.display_name() + "桌宠")
        tray_menu = QMenu()
        toggle = QAction("显示 / 隐藏", tray_menu)
        toggle.triggered.connect(lambda _c: self.setVisible(not self.isVisible()))
        tray_menu.addAction(toggle)
        settings = QAction("菜单…", tray_menu)
        settings.triggered.connect(lambda _c: self.menu.popup(self.cursor().pos()))
        tray_menu.addAction(settings)
        tray_menu.addSeparator()
        quit_act = QAction("退出", tray_menu)
        quit_act.triggered.connect(lambda _c: QApplication.instance().quit())
        tray_menu.addAction(quit_act)
        self.tray.setContextMenu(tray_menu)
        self.tray.show()

    # -- 设置 ---------------------------------------------------------------- #
    def set_size(self, px):
        self.size_px = int(px)
        self._resize_window()
        self.update()

    def set_work_status(self, status):
        self.animator.set_work_status(status)
