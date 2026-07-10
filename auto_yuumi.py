import time
import psutil
import pydirectinput
import random
import ctypes
import threading
import win32gui
import win32con
import keyboard
import cv2
import numpy as np
import mss
import pytesseract
import math

# ==========================================
# 强制开启 Windows DPI 感知
# ==========================================
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# ==========================================
# 环境与全局配置
# ==========================================
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

TARGET_PROCESS_NAME = "League of Legends.exe"
WINDOW_NAME = "League of Legends (TM) Client"
TRANSITION_TIME = 1600.0

SKILL_UPGRADE_ORDER = ['d', 'w', 'd', 'a', 'd', 'space', 'd', 'a', 'd', 'a', 'space', 'a', 'w', 'w', 'w', 'space', 'w',
                       'w']

DISPLAY_NAMES = {
    'w': 'Q技能',
    'a': 'W技能',
    'd': 'E技能',
    'space': 'R技能',
    'f': '辅助眼',
    '4': '饰品眼',
    'right_click': '移动',
    'q': '虚弱',
    'e': '治疗',
}

game_state = {
    'is_running': False,
    'start_time': None,
    'is_paused': False,
    'current_level': 0,
    'window_moved': False,
    'attach_x': None,
    'attach_y': None,
    'last_auto_attach_time': 0.0,

    # 判断是否是脚本自己在按A
    'is_simulating_a': False,
    # 队友是否残血标志
    'teammate_low_health': False,
    # 屏幕客户区中心坐标
    'center_x': 0,
    'center_y': 0,

    # 记录当前附身的队友序号 (0, 1, 2, 3)，默认为0 (第一个队友)
    'attached_teammate_index': 0,
    # 记录商店购买状态，防止在泉水里无限买东西
    'has_shopped_this_visit': False,
    # 记录紧急救援技能的上一次释放时间
    'last_cast': {'e': 0.0, 'space': 0.0},
    # 记录屏幕亮度动态缩放比例
    'brightness_ratio': 1.0
}

# 如果 condition == 'low_health'，则不仅要等冷却，还要等队友残血才会放。
ACTION_CONFIG = {
    'w': {'key': 'w', 'start': 25.0, 'end': 5.0, 'delay': 0.0, 'condition': 'none'},
    'd': {'key': 'd', 'start': 20.0, 'end': 3.0, 'delay': 0.0, 'condition': 'none'},
    # 加血类 设置为残血才放
    'space': {'key': 'space', 'start': 150.0, 'end': 60.0, 'delay': 480.0, 'condition': 'low_health'},
    'e': {'key': 'e', 'start': 200.0, 'end': 60.0, 'delay': 180.0, 'condition': 'low_health'},

    'right_click': {'key': 'right_click', 'start': 9.0, 'end': 9.0, 'delay': 0.0, 'condition': 'none'},
    'f': {'key': 'f', 'start': 50.0, 'end': 30.0, 'delay': 300.0, 'condition': 'none'},
    '4': {'key': '4', 'start': 100.0, 'end': 50.0, 'delay': 120.0, 'condition': 'none'},
    'q': {'key': 'q', 'start': 160.0, 'end': 60.0, 'delay': 180.0, 'condition': 'none'},
}


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def get_mouse_pos():
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def is_game_running(process_name):
    for proc in psutil.process_iter(['name']):
        try:
            if proc.info['name'] == process_name:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False


def move_window_to_top_right():
    hwnd = win32gui.FindWindow(None, WINDOW_NAME)
    if hwnd:
        screen_w = ctypes.windll.user32.GetSystemMetrics(0)
        rect = win32gui.GetWindowRect(hwnd)
        win_w = rect[2] - rect[0]
        win_h = rect[3] - rect[1]

        new_x = screen_w - win_w
        new_y = 0

        win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, new_x, new_y, win_w, win_h, win32con.SWP_SHOWWINDOW)

        # 记录中心坐标供随机移动使用
        client_point = win32gui.ClientToScreen(hwnd, (0, 0))
        client_rect = win32gui.GetClientRect(hwnd)
        game_state['center_x'] = client_point[0] + client_rect[2] // 2
        game_state['center_y'] = client_point[1] + client_rect[3] // 2

        print(f"🪟 已将游戏窗口移动至右上角: ({new_x}, {new_y})")
        return True
    return False


def level_up_skill(target_level):
    if target_level > len(SKILL_UPGRADE_ORDER):
        return
    skill_to_upgrade = SKILL_UPGRADE_ORDER[target_level - 1]
    display_name = DISPLAY_NAMES.get(skill_to_upgrade, skill_to_upgrade.upper())

    pydirectinput.keyDown('ctrl')
    time.sleep(0.05)
    pydirectinput.press(skill_to_upgrade)
    time.sleep(0.05)
    pydirectinput.keyUp('ctrl')
    print(f"🔼 升级啦！当前等级 {target_level}，自动加点: {display_name}")


def visual_monitor_thread():
    # 动态校准常量基准 (基于本机环境)
    base_w_normal = 112.12
    base_w_attach = 122.0
    base_health_black = 100.0
    base_shop_bright = 85.0

    last_print_time = 0.0

    # 队友血条的相对X坐标中心点列表
    teammate_x_list = [840, 894, 945, 996]

    while True:
        if game_state['is_running'] and game_state['window_moved']:
            try:
                hwnd = win32gui.FindWindow(None, WINDOW_NAME)
                if not hwnd:
                    continue

                client_point = win32gui.ClientToScreen(hwnd, (0, 0))

                # ================= 1. 区域坐标计算 =================
                abs_x_lvl = client_point[0] + 310
                abs_y_lvl = client_point[1] + 744
                level_region = {'top': abs_y_lvl, 'left': abs_x_lvl, 'width': 13, 'height': 13}

                abs_x_w = client_point[0] + 414
                abs_y_w = client_point[1] + 690
                w_region = {'top': abs_y_w, 'left': abs_x_w, 'width': 36, 'height': 36}

                # 商城图标区域 (X:611~694, Y:746~762 => width:83, height:16)
                shop_region = {
                    'top': client_point[1] + 746,
                    'left': client_point[0] + 611,
                    'width': 20,
                    'height': 16
                }

                with mss.MSS() as sct:
                    # ---- 等级处理 ----
                    level_img = np.array(sct.grab(level_region))
                    gray_lvl = cv2.cvtColor(level_img, cv2.COLOR_BGRA2GRAY)
                    enlarged_lvl = cv2.resize(gray_lvl, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)

                    # 圆环掩码：创建一个纯黑背景，中间画一个白圆，只保留圆形区域内的图像，抹除四个角的边框残影
                    mask = np.zeros(enlarged_lvl.shape, dtype=np.uint8)
                    center_x, center_y = enlarged_lvl.shape[1] // 2, enlarged_lvl.shape[0] // 2
                    # 半径设为 28 (原图13*5=65，中心点32，半径28刚好能切掉四个角的边框)
                    cv2.circle(mask, (center_x, center_y), 35, 255, -1)
                    enlarged_lvl = cv2.bitwise_and(enlarged_lvl, enlarged_lvl, mask=mask)

                    # y在二值化前加入 3x3 的高斯模糊，彻底消除放大带来的锯齿，让数字边缘如德芙般顺滑
                    enlarged_lvl = cv2.GaussianBlur(enlarged_lvl, (3, 3), 0)

                    # 【优化】移除粗暴的 dilate 操作，将阈值从 150 提升到 165。
                    # 阈值越高，画面中被判定为黑字的像素就越少，数字自然就变细了，完美保留字体圆弧形状且剥离粘连！
                    _, thresh_lvl = cv2.threshold(enlarged_lvl, 165, 255, cv2.THRESH_BINARY_INV)

                    # 继续添加白色边框 Padding。这正是解决 11 级贴边被当成噪点过滤的核心办法
                    thresh_lvl = cv2.copyMakeBorder(thresh_lvl, 10, 10, 10, 10, cv2.BORDER_CONSTANT,
                                                    value=[255, 255, 255])
                    # 将最终送给 OCR 识别的图像保存到本地，方便排查错认问题
                    cv2.imwrite('debug_ocr_level.png', thresh_lvl)

                    # 如果等级框全白（二值化反转后全白，说明原图UI消失了），说明游戏退出了结算
                    if game_state['current_level'] > 0 and np.mean(thresh_lvl) >= 250.0:
                        print(f"[{time.strftime('%H:%M:%S')}] 🛑 识别到等级框全白，游戏结束，点击屏幕中心退出！")
                        pydirectinput.moveTo(game_state['center_x'], game_state['center_y'])
                        time.sleep(0.1)
                        pydirectinput.click()
                        time.sleep(1.5)  # 休眠一会，避免疯狂连点
                        game_state['current_level'] = 0  # 🐛修复：归零等级，切断当前及后续所有附身/商城的视觉计算
                        game_state['is_paused'] = True  # 🐛修复：全局挂起，彻底冻结所有 action_worker 动作线程
                        continue # 退出视觉循环

                    custom_config = r'--oem 3 --psm 7 -c tessedit_char_whitelist=0123456789'
                    level_text = pytesseract.image_to_string(thresh_lvl, config=custom_config).strip()

                    if level_text.isdigit():
                        read_level = int(level_text)
                        if 0 < read_level <= 18:
                            if game_state['current_level'] == 0:
                                print(f"⚔️ 识别到等级 {read_level}，确认进入游戏！")
                                time.sleep(10.0)
                                # ================= 动态亮度校准 =================
                                w_img_calib = np.array(sct.grab(w_region))
                                w_base_now = np.mean(cv2.cvtColor(w_img_calib, cv2.COLOR_BGRA2GRAY))

                                # 防止异常黑屏导致除以0。如果你是在附身状态下重启脚本(亮度约131)，这里给个警告
                                if w_base_now < 10.0: w_base_now = base_w_normal
                                game_state['brightness_ratio'] = w_base_now / base_w_normal

                                print(
                                    f"🔆 屏幕亮度校准完成！W技能基准: {w_base_now:.2f} (适应比例: {game_state['brightness_ratio']:.2f})")
                                if w_base_now > 180.0:
                                    print(
                                        "⚠️ [警告] 初始亮度偏高，若您是在附身状态下启动的脚本，校准可能会产生偏差！建议下车后重启脚本。")
                                # 在真正进入游戏地图时，将时间锚点重置。
                                # 否则，几分钟的加载界面时长会被提前算入全局推移时间里，导致技能CD逻辑错乱。
                                game_state['start_time'] = time.time()

                                # 1. 中心点聚焦点击 (拆分按下与松开)
                                pydirectinput.moveTo(game_state['center_x'], game_state['center_y'])
                                time.sleep(0.1)
                                pydirectinput.mouseDown()
                                time.sleep(0.05)
                                pydirectinput.mouseUp()
                                print("🖱️ 已点击屏幕中心聚焦游戏窗口")
                                time.sleep(0.5)

                                pydirectinput.press('y')
                                print("👁️ 已自动按下 Y 键锁定视角")
                                time.sleep(0.5)

                                # 2. 分路选择点击 (拆分按下与松开)
                                role_x = client_point[0] + 675
                                role_y = client_point[1] + 650
                                pydirectinput.moveTo(role_x, role_y)
                                time.sleep(0.1)
                                pydirectinput.mouseDown()
                                time.sleep(0.05)
                                pydirectinput.mouseUp()
                                print("🎯 已自动点击分路任务 (辅助位置)")

                                # 默认跟随右边第一个队友
                                game_state['attached_teammate_index'] = 0
                                game_state['attach_x'] = client_point[0] + 840
                                game_state['attach_y'] = client_point[1] + 505
                                print("🎯 已设置默认跟随：右边第一个队友 (脚本将自动触发附身)")

                                game_state['current_level'] = read_level
                                level_up_skill(read_level)

                            elif read_level > game_state['current_level']:
                                game_state['current_level'] = read_level
                                level_up_skill(read_level)

                    if game_state['current_level'] > 0 and game_state['start_time'] is not None:
                        # ================= 商城回城状态处理 =================
                        shop_img = np.array(sct.grab(shop_region))
                        shop_gray = cv2.cvtColor(shop_img, cv2.COLOR_BGRA2GRAY)
                        cv2.imwrite('debug_ocr_shop.png', shop_gray)
                        shop_mean = np.mean(shop_gray)

                        is_in_base = shop_mean > (base_shop_bright * game_state['brightness_ratio'])

                        if is_in_base:
                            if not game_state['has_shopped_this_visit']:
                                print(f"\n[{time.strftime('%H:%M:%S')}] 🏠 检测到商城点亮(在泉水中)，执行自动购买！")
                                game_state['is_paused'] = True

                                pydirectinput.press('p')
                                time.sleep(0.5)

                                pydirectinput.moveTo(game_state['center_x'], game_state['center_y'])
                                time.sleep(0.1)
                                for i in range(2):
                                    pydirectinput.mouseDown(button='right')
                                    time.sleep(0.05)
                                    pydirectinput.mouseUp(button='right')
                                    time.sleep(0.5)
                                print("💰 装备购买完成")
                                time.sleep(0.2)

                                pydirectinput.press('p')
                                time.sleep(0.5)

                                game_state['has_shopped_this_visit'] = True
                        else:
                            game_state['has_shopped_this_visit'] = False

                        # ---- 血条状态处理 (动态追踪) ----
                        # 读取当前记录的队友索引，计算他专属的血条坐标
                        current_teammate_idx = game_state['attached_teammate_index']
                        # 计算随时间递减的X轴偏移量 (从 10 递减到 0)
                        t_elapsed = time.time() - game_state['start_time']
                        ratio = min(1.0, t_elapsed / TRANSITION_TIME)
                        shift_x = int(10 - 20 * ratio)

                        # 原始X中心加上偏移量，提前探测掉血
                        hp_center_x = client_point[0] + teammate_x_list[current_teammate_idx] + shift_x
                        # Y 轴取528中心，高度6
                        # X 轴取中心点左右各 5 像素 (width=10)，组成一个探测框
                        health_region = {
                            'top': client_point[1] + 525,
                            'left': hp_center_x - 5,
                            'width': 10,
                            'height': 6
                        }

                        hp_img = np.array(sct.grab(health_region))
                        hp_gray = cv2.cvtColor(hp_img, cv2.COLOR_BGRA2GRAY)
                        cv2.imwrite('debug_ocr_hp.png', hp_gray)
                        hp_mean = np.mean(hp_gray)

                        # 只有当这个区域变成暗黑，才判定为残血（掉血超过一半经过了中心点）
                        game_state['teammate_low_health'] = hp_mean < (
                                    base_health_black * game_state['brightness_ratio'])

                        # ================= 紧急技能释放 (E & Space) =================
                        # 如果没有被暂停，且队友残血，立即进行CD判定并释放
                        if game_state['teammate_low_health'] and not game_state['is_paused']:
                            current_time = time.time()
                            elapsed = current_time - game_state['start_time']

                            # E 技能动态冷却 (200秒 -> 60秒)
                            e_cd = max(60.0, 200.0 - ((200.0 - 60.0) / TRANSITION_TIME) * elapsed)
                            if current_time - game_state['last_cast']['e'] >= e_cd:
                                pydirectinput.press('e')
                                print(f"[{time.strftime('%H:%M:%S')}] 🚨 [紧急救援] 触发 治疗(E)！(冷却: {e_cd:.1f}s)")
                                game_state['last_cast']['e'] = current_time
                                time.sleep(0.1)

                            # Space 技能动态冷却 (150秒 -> 60秒)
                            space_cd = max(100.0, 150.0 - ((150.0 - 60.0) / TRANSITION_TIME) * elapsed)
                            if current_time - game_state['last_cast']['space'] >= space_cd:
                                pydirectinput.press('space')
                                print(
                                    f"[{time.strftime('%H:%M:%S')}] 🚨 [紧急救援] 触发 大招(Space)！(冷却: {space_cd:.1f}s)")
                                game_state['last_cast']['space'] = current_time
                                time.sleep(0.1)
                        # ---- W 技能图标状态处理 ----
                        w_img = np.array(sct.grab(w_region))
                        w_gray = cv2.cvtColor(w_img, cv2.COLOR_BGRA2GRAY)
                        cv2.imwrite('debug_ocr_w.png', w_gray)
                        w_mean_brightness = np.mean(w_gray)

                        current_time = time.time()
                        is_attached = w_mean_brightness > (base_w_attach * game_state['brightness_ratio'])

                        if current_time - last_print_time > 5.0:
                            state_str = "附身中" if is_attached else "未附身"
                            hp_str = "⚠️残血!" if game_state['teammate_low_health'] else "健康"
                            # 调试开关：你可以在这取消注释来看看血条的判定数值准不准
                            # print(f"[Debug] W亮度:{w_mean_brightness:.1f}({state_str}) | 队友{current_teammate_idx+1} 血条亮度:{hp_mean:.1f}({hp_str})")
                            last_print_time = current_time

                        if not is_attached:
                            if not game_state['is_paused']:
                                print(f"[{time.strftime('%H:%M:%S')}] 📉 未附身/回城/死亡，暂停其余动作循环！")
                                game_state['is_paused'] = True

                            if game_state['attach_x'] and game_state['attach_y']:
                                if current_time - game_state['last_auto_attach_time'] > 5.0:
                                    print(
                                        f"[{time.strftime('%H:%M:%S')}] 🔗 尝试自动附身到队友 {game_state['attached_teammate_index'] + 1}...")
                                    pydirectinput.moveTo(game_state['attach_x'], game_state['attach_y'])
                                    time.sleep(0.1)

                                    game_state['is_simulating_a'] = True
                                    pydirectinput.press('a')
                                    time.sleep(0.1)
                                    game_state['is_simulating_a'] = False

                                    game_state['last_auto_attach_time'] = current_time
                        else:
                            if game_state['is_paused'] and not is_in_base: # 确保在泉水买东西时不要马上重置暂停状态
                                print(f"[{time.strftime('%H:%M:%S')}] 📈 判定已成功附身，恢复动作循环！")
                                game_state['is_paused'] = False

            except Exception as e:
                print(f"视觉线程异常: {e}")

        time.sleep(1.0)


def action_worker(action_name, config, start_offset):
    session_started = False
    last_time = 0.0
    active_start_time = 0.0
    next_interval = config['start']
    was_paused = False

    physical_key = config['key']
    condition = config.get('condition', 'none')
    display_name = f"[{action_name}] {DISPLAY_NAMES.get(physical_key, physical_key.upper())}"

    while True:
        is_paused_now = game_state['is_paused']

        # 冻结时间逻辑：刚刚从暂停恢复时，重置上一次释放时间，防止上车瞬间技能狂泻
        if not is_paused_now and was_paused:
            last_time = time.time()

        was_paused = is_paused_now

        if game_state['is_running'] and game_state['start_time'] is not None and not is_paused_now and game_state[
            'current_level'] > 0:
            current_time = time.time()
            global_elapsed_time = current_time - game_state['start_time']

            if not session_started:
                if global_elapsed_time >= (config['delay'] + start_offset):
                    last_time = current_time
                    active_start_time = current_time
                    next_interval = random.uniform(config['start'] - 0.5, config['start'] + 0.5)
                    session_started = True
                    print(f"[{time.strftime('%H:%M:%S')}] ⏳ {display_name} 达到启动时间！")
                else:
                    time.sleep(0.5)
                    continue

            # 检查时间间隔
            if current_time - last_time >= next_interval:

                # 残血条件判定
                if condition == 'low_health' and not game_state['teammate_low_health']:
                    # 虽然冷却好了，但队友不残血，憋着不放，睡一小会继续查
                    time.sleep(0.5)
                    continue

                # 释放前先将鼠标移动到屏幕中心附近的随机位置
                rx = game_state['center_x'] + random.randint(-80, 80)
                ry = game_state['center_y'] + random.randint(-80, 80)
                pydirectinput.moveTo(rx, ry)
                time.sleep(0.05)

                if physical_key == 'right_click':
                    pydirectinput.mouseDown(button='right')
                    time.sleep(0.05)
                    pydirectinput.mouseUp(button='right')
                else:
                    pydirectinput.press(physical_key)

                msg = f"[{time.strftime('%H:%M:%S')}] 触发 {display_name} (距上次 {next_interval:.2f}s)"
                if condition == 'low_health':
                    msg += " [⚠️队友残血触发]"
                print(msg)

                last_time = time.time()
                active_elapsed_time = current_time - active_start_time
                base_interval = max(
                    config['end'],
                    config['start'] - ((config['start'] - config['end']) / TRANSITION_TIME) * active_elapsed_time
                )
                next_interval = random.uniform(base_interval - 0.5, base_interval + 0.5)
        else:
            if not game_state['is_running']:
                session_started = False

        time.sleep(0.05)


# ==========================================
# 键盘监听钩子 - 模糊吸附
# ==========================================
def on_press_a(event):
    # 屏蔽脚本模拟的 A，屏蔽升级技能用的 Ctrl+A
    if not game_state['is_running'] or game_state['is_simulating_a'] or keyboard.is_pressed('ctrl'):
        return

    x, y = get_mouse_pos()

    hwnd = win32gui.FindWindow(None, WINDOW_NAME)
    if not hwnd: return
    client_point = win32gui.ClientToScreen(hwnd, (0, 0))
    base_x, base_y = client_point

    # 填入你校准的4个队友头像相对中心点坐标
    TEAMMATE_REL_POSITIONS = [
        (840, 505),  # 队友 1
        (894, 505),  # 队友 2
        (945, 505),  # 队友 3
        (996, 505)  # 队友 4
    ]

    # 寻找距离鼠标最近的队友头像
    closest_pos = None
    closest_index = 0
    min_dist = float('inf')

    for i, (rel_x, rel_y) in enumerate(TEAMMATE_REL_POSITIONS):
        abs_px = base_x + rel_x
        abs_py = base_y + rel_y
        dist = math.hypot(x - abs_px, y - abs_py)
        if dist < min_dist:
            min_dist = dist
            closest_pos = (abs_px, abs_py)
            closest_index = i

    if closest_pos:
        game_state['attach_x'] = closest_pos[0]
        game_state['attach_y'] = closest_pos[1]
        # 记录当前吸附的是几号队友，供视觉线程读血条使用
        game_state['attached_teammate_index'] = closest_index
        game_state['last_auto_attach_time'] = time.time()
        print(f"\n[按键捕捉] 手动按下A键！已吸附队友 {closest_index + 1} 坐标: {closest_pos}\n")


def main_controller():
    print("🤖 悠米专属高级自动化脚本已启动...")
    print("提示：按 [Ctrl + C] 终止。\n")

    keyboard.on_press_key('a', on_press_a)

    cv_thread = threading.Thread(target=visual_monitor_thread, daemon=True)
    cv_thread.start()

    offset = 0.5
    for action, config in ACTION_CONFIG.items():
        t = threading.Thread(target=action_worker, args=(action, config, offset), daemon=True)
        t.start()
        offset += 1.2

    try:
        while True:
            running = is_game_running(TARGET_PROCESS_NAME)

            if running and not game_state['is_running']:
                game_state['is_running'] = True
                game_state['start_time'] = time.time()
                game_state['current_level'] = 0
                game_state['is_paused'] = False
                game_state['window_moved'] = False
                game_state['has_shopped_this_visit'] = False
                print(f"\n[{time.strftime('%H:%M:%S')}] 🎮 游戏进程启动！等待进入游戏界面...")

            elif running and game_state['is_running'] and not game_state['window_moved']:
                time.sleep(3)
                if move_window_to_top_right():
                    game_state['window_moved'] = True


            elif not running and game_state['is_running']:
                game_state['is_running'] = False
                game_state['start_time'] = None
                game_state['window_moved'] = False
                print(f"\n[{time.strftime('%H:%M:%S')}] 🛑 游戏结束...")

                # 寻找游戏大厅窗口，移动至右上角并双击底部
                time.sleep(3.0)  # 给大厅一点弹出的缓冲时间
                lobby_hwnd = win32gui.FindWindow(None, "League of Legends")
                if lobby_hwnd:
                    screen_w = ctypes.windll.user32.GetSystemMetrics(0)
                    rect = win32gui.GetWindowRect(lobby_hwnd)
                    win_w = rect[2] - rect[0]
                    win_h = rect[3] - rect[1]
                    new_x = screen_w - win_w
                    new_y = 0

                    # 1. 移动大厅到右上角
                    win32gui.SetWindowPos(lobby_hwnd, win32con.HWND_TOP, new_x, new_y, win_w, win_h,
                                          win32con.SWP_SHOWWINDOW)

                    print(f"🪟 已将游戏大厅移动至右上角: ({new_x}, {new_y})")
                    # 2. 移动鼠标到大厅底部正中间并双击，触发 LeagueAkari 所需的重新匹配
                    time.sleep(35.0)
                    # Y轴偏移减去 40 像素，确保点在“再来一局”等底部按钮区域上
                    target_x = new_x + win_w // 2 - 100
                    target_y = win_h - 40
                    time.sleep(1.0)  # 窗口移动后稍微等一下
                    pydirectinput.moveTo(target_x, target_y)
                    for i in range(5):
                        time.sleep(2.5)
                        pydirectinput.click()

                    print("🖱️ 已点击大厅底部中央，准备衔接 LeagueAkari 自动匹配！")

            time.sleep(2.0)

    except KeyboardInterrupt:
        print("\n⏹️ 接收到中断信号，脚本已安全停止。")


if __name__ == "__main__":
    main_controller()