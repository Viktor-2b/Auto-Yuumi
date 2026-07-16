import os
import time
import math
import random
import ctypes
import threading

import psutil
import pydirectinput
import keyboard
import win32gui
import win32con
import cv2
import numpy as np
import mss
import pytesseract
import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning) # 忽略局域网证书警告

# ==========================================
# 强制开启 Windows DPI 感知
# ==========================================
try:
    # noinspection PyUnresolvedReferences
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # 适用于 Windows 8.1 及以上
except (AttributeError, OSError):
    try:
        # noinspection PyUnresolvedReferences
        ctypes.windll.user32.SetProcessDPIAware()   # 适用于 Windows Vista 及以上
    except (AttributeError, OSError):
        pass

# ==========================================
# 环境与全局配置
# ==========================================
os.makedirs("debug", exist_ok=True)
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

TARGET_PROCESS_NAME = "League of Legends.exe"
WINDOW_NAME = "League of Legends (TM) Client"
TRANSITION_TIME = 1600.0

# 键位绑定
KEY_BINDINGS = {
    'Q': 'w',               # Q技能摸鱼飞弹
    'W': 'a',               # W技能附身
    'E': 'd',               # E技能加盾
    'R': 'space',           # R技能加血
    'SUMMONER_EXHAUST': 'q',# 召唤师技能1：虚弱
    'SUMMONER_HEAL': 'e',   # 召唤师技能2：治疗
    'WARD_AUX_EQUIP': 'f',  # 装备栏1：辅助装眼位
    'WARD_ACCESSORY': '4',  # 饰品眼位
    'MOVE': 'right_click'   # 移动指令
}
# 加点顺序
SKILL_UPGRADE_ORDER = ['E', 'Q', 'E', 'W', 'E', 'R', 'E', 'W', 'E', 'W', 'R', 'W', 'Q', 'Q', 'Q', 'R', 'Q', 'Q']
# 按键名称显示
DISPLAY_NAMES = {
    'Q': 'Q技能 摸鱼飞弹',
    'W': 'W技能 悠米出动',
    'E': 'E技能 旺盛精力',
    'R': 'R技能 魔典终章',
    'WARD_AUX_EQUIP': '辅助眼',
    'WARD_ACCESSORY': '饰品眼',
    'MOVE': '移动指令',
    'SUMMONER_EXHAUST': '虚弱',
    'SUMMONER_HEAL': '治疗',
}
# 键位循环配置
ACTION_CONFIG: dict = {
    'Q': {'start': 35.0, 'end': 5.0, 'delay': 0.0, 'condition': 'none', 'radius': [300, 450]},
    'E': {'start': 20.0, 'end': 3.0, 'delay': 0.0, 'condition': 'none', 'radius': [0, 10]},
    'R': {'start': 150.0, 'end': 60.0, 'delay': 480.0, 'condition': 'low_health', 'radius': [50, 150]},
    'SUMMONER_HEAL': {'start': 200.0, 'end': 60.0, 'delay': 180.0, 'condition': 'low_health', 'radius': [0, 10]},
    'SUMMONER_EXHAUST': {'start': 20.0, 'end': 5.0, 'delay': 0.0, 'condition': 'none', 'radius': [50, 150]},
    'MOVE': {'start': 4.0, 'end': 4.0, 'delay': 0.0, 'condition': 'none', 'radius': [50, 100]},
    'WARD_AUX_EQUIP': {'start': 50.0, 'end': 30.0, 'delay': 300.0, 'condition': 'none', 'radius': [60, 120]},
    'WARD_ACCESSORY': {'start': 100.0, 'end': 50.0, 'delay': 120.0, 'condition': 'none', 'radius': [60, 120]},
}
game_state: dict = {
    'is_running': False,
    'start_time': None,
    'is_paused': False,
    'current_level': 0,
    'window_moved': False,
    'attach_x': None,
    'attach_y': None,
    'last_auto_attach_time': 0.0,

    # 判断是否是脚本自己在模拟附身按键
    'is_simulating_attach': False,
    # 队友是否残血标志
    'teammate_low_health': False,
    # 屏幕客户区中心坐标
    'center_x': 0,
    'center_y': 0,

    # 记录当前附身的队友序号 (0, 1, 2, 3)，默认为0 (第一个队友)
    'attached_teammate_index': 0,
    # 记录商店购买状态，防止在泉水里无限买东西
    'has_shopped_this_visit': False,
    'last_shop_time': 0.0,  # 记录上一次成功购买的时间戳
    # 记录紧急救援技能上一次释放时间
    'last_cast': {'SUMMONER_HEAL': 0.0, 'R': 0.0},
    # 记录屏幕亮度动态缩放比例
    'brightness_ratio': 1.0,
    # 记录野外意外脱落后，按下B键回城的时间
    'last_recall_time': 0.0,
    # 记录玩家真实按下A键的时间，防止手动换乘时被误判为掉落
    'last_manual_attach_time': 0.0,

    # 记录 Q 技能霸占鼠标的结束时间
    'exclusive_mouse_until': 0.0,
    # 记录当前处于哪一方：'ORDER' (蓝方/左下) 或 'CHAOS' (红方/右上)
    'team_side': None
}

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def get_mouse_pos():
    pt = POINT()
    # noinspection PyUnresolvedReferences
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
        # noinspection PyUnresolvedReferences
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
    logical_action = SKILL_UPGRADE_ORDER[target_level - 1]
    physical_key = KEY_BINDINGS.get(logical_action, logical_action)  # 查字典获取真实按键
    display_name = DISPLAY_NAMES.get(logical_action, logical_action)

    # 上锁，防止被其他技能消耗
    game_state['exclusive_mouse_until'] = time.time() + 1.0
    time.sleep(0.2)

    pydirectinput.keyDown('ctrl')
    time.sleep(0.05)
    pydirectinput.press(physical_key)
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

                # ================= 区域坐标计算 =================
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

                    # 圆环掩码：创a建一个纯黑背景，中间画一个白圆，只保留圆形区域内的图像，抹除四个角的边框残影
                    mask = np.zeros(enlarged_lvl.shape, dtype=np.uint8)
                    center_x, center_y = enlarged_lvl.shape[1] // 2, enlarged_lvl.shape[0] // 2
                    # 半径，原图13*5=65，中心点32
                    cv2.circle(mask, (center_x, center_y), 33, 255, -1)
                    masked_lvl = cv2.bitwise_and(enlarged_lvl, enlarged_lvl, mask=mask)

                    final_lvl = cv2.bitwise_not(masked_lvl)

                    _, binary_lvl = cv2.threshold(final_lvl, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

                    # 将最终送给 OCR 识别的图像保存到本地，方便排查错认问题
                    cv2.imwrite(os.path.join('debug', 'ocr_level.png'), binary_lvl)

                    # 如果等级框全白（二值化反转后全白，说明原图UI消失了），说明游戏退出了结算
                    if game_state['current_level'] > 0 and np.mean(final_lvl) >= 250.0:
                        print(f"[{time.strftime('%H:%M:%S')}] 🛑 识别到等级框全白，游戏结束，点击屏幕中心退出！")
                        pydirectinput.moveTo(game_state['center_x'], game_state['center_y'])
                        time.sleep(0.1)
                        pydirectinput.click()
                        time.sleep(1.5)  # 休眠一会，避免疯狂连点
                        game_state['current_level'] = 0
                        game_state['is_paused'] = True
                        continue

                    custom_config = r'--oem 3 --psm 8 -c tessedit_char_whitelist=0123456789'
                    level_text = pytesseract.image_to_string(final_lvl, config=custom_config).strip()

                    if level_text.isdigit():
                        read_level = int(level_text)
                        if 0 < read_level <= 18:
                            if game_state['current_level'] == 0:
                                print(f"⚔️ 识别到等级 {read_level}，确认进入游戏！")
                                # 开局直接标记为已购买
                                game_state['has_shopped_this_visit'] = True
                                game_state['last_shop_time'] = time.time()

                                time.sleep(5.0)
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

                                game_state['current_level'] = read_level
                                level_up_skill(read_level)
                                # 在真正进入游戏地图时，将时间锚点重置。
                                game_state['start_time'] = time.time()
                                try:
                                    # 直接请求 allgamedata，一份数据包含所有所需信息
                                    res = requests.get("https://127.0.0.1:2999/liveclientdata/allgamedata",
                                                       verify=False, timeout=2)
                                    if res.status_code == 200:
                                        data = res.json()

                                        # 1. 获取当前玩家名字（完美兼容 Riot ID 时代的新老键值）
                                        active_player = data.get('activePlayer', {})
                                        active_name = active_player.get('riotIdGameName') or active_player.get(
                                            'summonerName')

                                        # 2. 去 10 人大名单里找到自己，提取 team 字段
                                        all_players = data.get('allPlayers', [])
                                        for player in all_players:
                                            p_name = player.get('riotIdGameName') or player.get('summonerName')
                                            if p_name == active_name:
                                                game_state['team_side'] = player.get('team')
                                                break

                                        if game_state.get('team_side'):
                                            side_cn = "蓝色方(基地在左下)" if game_state[
                                                                                  'team_side'] == 'ORDER' else "红色方(基地在右上)"
                                            print(f"🚩 局内 API 连通！识别到玩家 [{active_name}]，当前阵营: {side_cn}")
                                            # 取出所有队友（排除自己）
                                            allies = [p for p in all_players if
                                                      p.get('team') == game_state['team_side'] and (
                                                                  p.get('riotIdGameName') or p.get(
                                                              'summonerName')) != active_name]

                                            # 默认跟随 UI 上的第 4 个队友 (索引3)，如果有人的位置是 BOTTOM，则自动纠正
                                            adc_idx = 3
                                            for i, ally in enumerate(allies):
                                                if ally.get('position') == 'BOTTOM':
                                                    adc_idx = i
                                                    adc_name = ally.get('riotIdGameName') or ally.get('summonerName')
                                                    print(
                                                        f"🎯 API 分析完毕：下路射手是 [{adc_name}]，位于 UI 列表第 {adc_idx + 1} 位")
                                                    break

                                            game_state['attached_teammate_index'] = adc_idx
                                            game_state['attach_x'] = client_point[0] + teammate_x_list[adc_idx]
                                            game_state['attach_y'] = client_point[1] + 505
                                            print(f"🎯 已根据官方 API 设定默认跟随目标！")

                                        else:
                                            print(f"⚠️ API 通信正常，但在名单中未找到匹配的阵营信息！")
                                except Exception as e:
                                    print(f"⚠️ 无法获取阵营信息，Q技能将使用全向随机盲打。错误: {e}")


                            elif read_level > game_state['current_level']:
                                game_state['current_level'] = read_level
                                level_up_skill(read_level)

                    if game_state['current_level'] > 0 and game_state['start_time'] is not None:
                        # ================= 商城回城状态处理 =================
                        shop_img = np.array(sct.grab(shop_region))
                        shop_gray = cv2.cvtColor(shop_img, cv2.COLOR_BGRA2GRAY)
                        cv2.imwrite(os.path.join('debug', 'ocr_shop.png'), shop_gray)
                        shop_mean = np.mean(shop_gray)

                        is_in_base = shop_mean > (base_shop_bright * game_state['brightness_ratio'])

                        if is_in_base:
                            if not game_state['has_shopped_this_visit']and (time.time() - game_state.get('last_shop_time', 0.0) > 30.0):
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
                                game_state['last_shop_time'] = time.time()
                        else:
                            if time.time() - game_state.get('last_shop_time', 0.0) > 30.0:
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
                        # Y 轴取528，高度6；X 轴取中心点左右各 5 像素 (width=10)，组成一个探测框
                        health_region = {
                            'top': client_point[1] + 525,
                            'left': hp_center_x - 5,
                            'width': 10,
                            'height': 6
                        }

                        hp_img = np.array(sct.grab(health_region))
                        hp_gray = cv2.cvtColor(hp_img, cv2.COLOR_BGRA2GRAY)
                        cv2.imwrite(os.path.join('debug', 'ocr_hp.png'), hp_gray)
                        hp_mean = np.mean(hp_gray)

                        # 只有当这个区域变成暗黑，才判定为残血（掉血超过一半经过了中心点）
                        game_state['teammate_low_health'] = hp_mean < (
                                    base_health_black * game_state['brightness_ratio'])

                        # ================= 紧急技能释放 =================
                        # 如果没有被暂停，且队友残血，立即进行CD判定并释放
                        if game_state['teammate_low_health'] and not game_state['is_paused']:
                            current_time = time.time()
                            elapsed = current_time - game_state['start_time']

                            # 遍历所有被定性为“紧急救援”的逻辑动作
                            for action_name in ['SUMMONER_HEAL', 'R']:
                                config = ACTION_CONFIG[action_name]
                                start_cd = config['start']
                                end_cd = config['end']

                                # 动态冷却计算 (根据全局配置的起止时间计算)
                                current_cd = max(end_cd, start_cd - ((start_cd - end_cd) / TRANSITION_TIME) * elapsed)

                                if current_time - game_state['last_cast'][action_name] >= current_cd:
                                    physical_key = KEY_BINDINGS[action_name]
                                    display_name = DISPLAY_NAMES.get(action_name, action_name)

                                    pydirectinput.press(physical_key)
                                    print(
                                        f"[{time.strftime('%H:%M:%S')}] 🚨 [紧急救援] 触发 {display_name}！(冷却: {current_cd:.1f}s)")

                                    game_state['last_cast'][action_name] = current_time
                                    time.sleep(0.1)
                        # ---- W 技能图标状态处理 ----
                        w_img = np.array(sct.grab(w_region))
                        w_gray = cv2.cvtColor(w_img, cv2.COLOR_BGRA2GRAY)
                        cv2.imwrite(os.path.join('debug', 'ocr_w.png'), w_gray)
                        w_mean_brightness = np.mean(w_gray)

                        current_time = time.time()
                        is_attached = w_mean_brightness > (base_w_attach * game_state['brightness_ratio'])

                        if current_time - last_print_time > 5.0:
                            last_print_time = current_time

                        if not is_attached:
                            if not game_state['is_paused']:
                                print(f"[{time.strftime('%H:%M:%S')}] 📉 未附身/死亡，暂停其余动作循环！")
                                game_state['is_paused'] = True

                                # 紧急判断：如果不在泉水，且距离上次手动按A超过3秒（排除玩家正常换人），说明是队友阵亡
                                if not is_in_base and (current_time - game_state.get('last_manual_attach_time', 0.0) > 3.0):
                                    print(f"[{time.strftime('%H:%M:%S')}] ⚠️ 检测到野外意外脱落，按下B键紧急回城！")
                                    pydirectinput.press('b')
                                    game_state['last_recall_time'] = current_time

                            if game_state['attach_x'] and game_state['attach_y']:
                                # 如果刚刚按了回城，必须等 9 秒读条结束，期间不准执行任何附身动作
                                if current_time - game_state.get('last_recall_time', 0.0) > 9.0:
                                    if current_time - game_state['last_auto_attach_time'] > 5.0:
                                        print(
                                            f"[{time.strftime('%H:%M:%S')}] 🔗 尝试自动附身到队友 {game_state['attached_teammate_index'] + 1}...")
                                        pydirectinput.moveTo(game_state['attach_x'], game_state['attach_y'])
                                        time.sleep(0.1)

                                        game_state['is_simulating_attach'] = True
                                        pydirectinput.press(KEY_BINDINGS['W'])
                                        time.sleep(0.1)
                                        game_state['is_simulating_attach'] = False

                                        game_state['last_auto_attach_time'] = current_time
                        else:
                            if game_state['is_paused'] and not is_in_base: # 确保在泉水买东西时不要马上重置暂停状态
                                print(f"[{time.strftime('%H:%M:%S')}] 📈 判定已成功附身，恢复动作循环！")
                                game_state['is_paused'] = False
                                # 成功上车后，立即将鼠标移回屏幕中间，并点一下右键
                                pydirectinput.moveTo(game_state['center_x'], game_state['center_y'])
                                time.sleep(0.05)
                                pydirectinput.mouseDown(button='right')
                                time.sleep(0.05)
                                pydirectinput.mouseUp(button='right')

            except Exception as e:
                print(f"视觉线程异常: {e}")

        time.sleep(1.0)


def action_worker(action_name, config, start_offset):
    session_started = False
    last_time = 0.0
    active_start_time = 0.0
    next_interval = config['start']
    was_paused = False
    physical_key = KEY_BINDINGS.get(action_name, action_name)
    condition = config.get('condition', 'none')
    display_name = f"[{DISPLAY_NAMES.get(action_name, action_name)}] ({str(physical_key).upper()})"

    while True:
        is_paused_now = game_state['is_paused']

        # 冻结时间逻辑：刚刚从暂停恢复时，重置上一次释放时间，防止技能狂泻
        if not is_paused_now and was_paused:
            last_time = time.time()

        was_paused = is_paused_now
        # 检查互斥锁，如果 Q 技能正在霸占鼠标，其他线程强制睡眠等待
        if time.time() < game_state.get('exclusive_mouse_until', 0.0):
            time.sleep(0.1)
            continue
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

                # 获取该技能配置的施法距离范围，使用极坐标算法随机计算坐标
                radius_range = config.get('radius', [0, 80])
                r = random.uniform(radius_range[0], radius_range[1])
                # 根据阵营智能设定 Q 技能的攻击象限 (敌方所在位置)
                if action_name == 'Q' and game_state.get('team_side'):
                    if game_state['team_side'] == 'ORDER':
                        # 蓝色方：向右上角打
                        theta = random.uniform(-math.pi / 2, 0)
                    else:
                        # 红色方：向左下角打
                        theta = random.uniform(math.pi / 2, math.pi)
                else:
                    # 其他技能或未获取到阵营：全图360度随机
                    theta = random.uniform(0, 2 * math.pi)

                rx = int(game_state['center_x'] + r * math.cos(theta))
                ry = int(game_state['center_y'] + r * math.sin(theta))
                # ========================================================
                # 精准矩形禁区防误触 (相对坐标转绝对屏幕坐标)
                # ========================================================
                hwnd = win32gui.FindWindow(None, WINDOW_NAME)
                if hwnd:
                    client_pt = win32gui.ClientToScreen(hwnd, (0, 0))
                    rect = win32gui.GetClientRect(hwnd)
                    win_w, win_h = rect[2], rect[3]
                    base_x, base_y = client_pt[0], client_pt[1]
                else:
                    # 备用回退机制
                    base_x, base_y = game_state['center_x'] - 512, game_state['center_y'] - 384
                    win_w, win_h = 1024, 768

                # 禁区 1 (右侧队友血条) 转换为屏幕绝对坐标
                r1_left, r1_top = base_x + 800, base_y + 480
                r1_right, r1_bottom = base_x + win_w, base_y + 570

                # 禁区 2 (底部 OCR 识图区) 转换为屏幕绝对坐标
                r2_left, r2_top = base_x + 280, base_y + 660
                r2_right, r2_bottom = base_x + 740, base_y + win_h

                # 碰撞检测过滤函数：如果掉进禁区，强行把它推出来
                def enforce_safe_zone(cx, cy):
                    if r1_left <= cx <= r1_right and r1_top <= cy <= r1_bottom:
                        cx = r1_left - 3  # 从左边弹出去
                    if r2_left <= cx <= r2_right and r2_top <= cy <= r2_bottom:
                        cy = r2_top - 3  # 从上面弹出去
                    return cx, cy

                # 主坐标先过一次安检
                rx, ry = enforce_safe_zone(rx, ry)

                if physical_key == 'right_click':
                    # 模拟真人狂点右键的习惯：随机点 2 到 5 下
                    click_times = random.randint(2, 5)
                    lock_duration = click_times * 0.25
                    game_state['exclusive_mouse_until'] = time.time() + lock_duration
                    for _ in range(click_times):
                        # 在原始落点附近，加上 -20 到 20 像素的微小抖动偏移
                        offset_x = rx + random.randint(-20, 20)
                        offset_y = ry + random.randint(-20, 20)
                        offset_x, offset_y = enforce_safe_zone(offset_x, offset_y)
                        pydirectinput.moveTo(offset_x, offset_y)
                        time.sleep(random.uniform(0.02, 0.05))  # 鼠标移动后的微小停顿
                        pydirectinput.mouseDown(button='right')
                        time.sleep(random.uniform(0.02, 0.06))  # 按下到松开的时间
                        pydirectinput.mouseUp(button='right')

                        # 两次点击之间的间隔 (极速连点)
                        time.sleep(random.uniform(0.05, 0.15))
                else:
                    pydirectinput.moveTo(rx, ry)
                    time.sleep(0.05)
                    pydirectinput.press(physical_key)
                    if action_name == 'Q': # 如果是 Q 技能，释放后锁死所有其他鼠标线程 2 秒
                        game_state['exclusive_mouse_until'] = time.time() + 2.0

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


# 键盘监听钩子 - 模糊吸附
def on_manual_attach(event):
    # 屏蔽脚本模拟的按键，屏蔽升级技能用的 Ctrl+按键
    if not game_state['is_running'] or game_state['is_simulating_attach'] or keyboard.is_pressed('ctrl'):
        return

    x, y = get_mouse_pos()

    hwnd = win32gui.FindWindow(None, WINDOW_NAME)
    if not hwnd: return
    client_point = win32gui.ClientToScreen(hwnd, (0, 0))
    base_x, base_y = client_point

    # 填入你校准的4个队友头像相对中心点坐标
    teammate_rel_positions = [
        (840, 505),  # 队友 1
        (894, 505),  # 队友 2
        (945, 505),  # 队友 3
        (996, 505)  # 队友 4
    ]

    # 寻找距离鼠标最近的队友头像
    closest_pos = None
    closest_index = 0
    min_dist = float('inf')

    for i, (rel_x, rel_y) in enumerate(teammate_rel_positions):
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
        game_state['last_manual_attach_time'] = time.time()
        print(f"\n[按键捕捉] 手动按下 {str(event.name).upper()} 键！已吸附队友 {closest_index + 1} 坐标: {closest_pos}\n")

def main_controller():
    print("🤖 悠米专属高级自动化脚本已启动...")
    print("提示：按 [Ctrl + C] 终止。\n")

    attach_key = KEY_BINDINGS.get('W', 'w')
    keyboard.on_press_key(attach_key, on_manual_attach)

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
                    # noinspection PyUnresolvedReferences
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
                    # 2. 点击底部三角标跳过结算等待动画
                    time.sleep(2.0)
                    skip_x = new_x + win_w // 2
                    skip_y = win_h - 55
                    pydirectinput.moveTo(skip_x, skip_y)
                    time.sleep(0.5)
                    pydirectinput.click()
                    print("⏭️ 已点击跳过结算动画")

                    # 3. 移动鼠标到大厅底部左侧位置并连续点击，触发 LeagueAkari 所需的重新匹配
                    time.sleep(3.0)
                    target_x = new_x + win_w // 2 - 100
                    target_y = win_h - 40
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