import os
import time
import math
import random
import ctypes
import threading
import logging
from logging.handlers import RotatingFileHandler

import pydirectinput
import keyboard
import win32gui
import win32con
import cv2
import numpy as np
import mss
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)  # 忽略局域网证书警告

# ==========================================
# 强制开启 Windows DPI 感知
# ==========================================
try:
    # noinspection PyUnresolvedReferences
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # 适用于 Windows 8.1 及以上
except (AttributeError, OSError):
    try:
        # noinspection PyUnresolvedReferences
        ctypes.windll.user32.SetProcessDPIAware()  # 适用于 Windows Vista 及以上
    except (AttributeError, OSError):
        pass

# ==========================================
# 环境与全局配置
# ==========================================
os.makedirs("debug", exist_ok=True)

log_formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
log_file = os.path.join("debug", "yuumi_auto.log")
file_handler = RotatingFileHandler(log_file, maxBytes=2 * 1024 * 1024, backupCount=3, encoding='utf-8')
file_handler.setFormatter(log_formatter)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%H:%M:%S'))

logger = logging.getLogger('YuumiBot')
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)


def log(msg, level="info"):
    if level == "info":
        logger.info(msg)
    elif level == "warning":
        logger.warning(msg)
    elif level == "error":
        logger.error(msg)


TARGET_PROCESS_NAME = "League of Legends.exe"
WINDOW_NAME = "League of Legends (TM) Client"
TRANSITION_TIME = 900.0
TARGET_WINS = 3
mouse_lock = threading.Lock()

# 键位绑定
KEY_BINDINGS = {
    'Q': 'w',  # Q技能摸鱼飞弹
    'W': 'a',  # W技能附身
    'E': 'd',  # E技能加盾
    'R': 'space',  # R技能加血
    'SUMMONER_EXHAUST': 'q',  # 召唤师技能1：虚弱
    'SUMMONER_HEAL': 'e',  # 召唤师技能2：治疗
    'WARD_AUX_EQUIP': 'f',  # 装备栏1：辅助装眼位
    'WARD_ACCESSORY': '4',  # 饰品眼位
    'MOVE': 'right_click'  # 移动指令
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
    'Q': {'base_cd': 6.5, 'mana_delay': 30.0, 'delay': 0.0, 'radius': [300, 450], 'is_poke': True},
    'E': {'base_cd': 10.0, 'delay': 0.0, 'condition': 'hp_drop'},
    'R': {'base_cd': 120.0, 'delay': 0.0, 'condition': 'hp_low', 'radius': [50, 150], 'is_poke': True},
    'SUMMONER_HEAL': {'base_cd': 240.0, 'delay': 0.0, 'condition': 'hp_low'},
    'SUMMONER_EXHAUST': {'base_cd': 240.0, 'delay': 0.0, 'radius': [50, 150]},
    'WARD_AUX_EQUIP': {'base_cd': 45.0, 'delay': 600.0, 'radius': [60, 120]},
    'WARD_ACCESSORY': {'base_cd': 150.0, 'delay': 0.0, 'radius': [60, 120]},
}
game_state: dict = {
    'is_running': False,  # 游戏对局进程是否运行
    'is_paused': False,  # 是否暂停动作
    'start_time': None,  # 游戏开始时间
    'window_moved': False,  # 窗口移动到右上角
    'win_count': 0,  # 胜局计数

    'brightness_ratio': 1.0,  # 屏幕亮度缩放比例
    'is_brightness_calibrated': False,  # 是否已完成本局亮度校准

    'current_level': 0,  # 当前等级

    # 全局坐标
    'center_x': 0,
    'center_y': 0,
    'client_x': 0,
    'client_y': 0,
    'client_w': 0,
    'client_h': 0,
    'w_region': {},         # W 技能
    'shop_region': {},      # 商店
    'teammate_avatars': [], # 队友头像
    'teammate_hps': [],     # 队友血条

    'attach_x': None,  # 附身x坐标
    'attach_y': None,  # 附身y坐标
    'last_auto_attach_time': 0.0, # 上次自动附身触发时间
    'is_simulating_attach': False,  # 判断是否是脚本自己在模拟附身按键

    # 附身队友状态
    'attached_teammate_index': 0,
    'attached_teammate_is_dead': False,
    'attached_teammate_hp_percent': 1.0,
    'attached_teammate_respawn_timer': 0.0,
    'last_hp_drop_time':0.0,

    # 商店购买状态
    'has_shopped_this_visit': False,
    'last_shop_time': 0.0,

    # 记录玩家真实按下A键的时间，防止手动换乘时被误判为掉落
    'last_manual_attach_time': 0.0,

    # 记录 Q 技能霸占鼠标的结束时间
    'exclusive_mouse_until': 0.0,
    # 记录当前处于哪一方：'ORDER' (蓝方/左下) 或 'CHAOS' (红方/右上)
    'team_side': None,
    # 记录技能极速
    'ability_haste': 0.0,

    # 存储敌人坐标与检测时间
    'enemy_positions': [],
    'last_enemy_track_time': 0.0,
}
# 高频下路英雄清单 (包含常规ADC与法核)
COMMON_BOT_CHAMPIONS = [
    "戏命师", "不破之誓", "涤魂圣枪", "圣枪游侠", "虚空之女", "祖安花火", "麦林炮手", "战争女神", "赏金猎人",
    "荣耀行刑官", "逆羽", "复仇之矛", "暴走萝莉", "皮城女警", "暗夜猎手", "寒冰射手", "残月之肃", "瘟疫之源",
    "英勇投弹手", "深渊巨口", "炽炎雏龙", "惩戒之箭", "沙漠玫瑰", "不羁之悦", "探险家", "疾风剑豪",
    "远古巫灵", "奥术先驱", "星籁歌姬", "异画师", "魔蛇之拥", "暗黑元首", "邪恶小法师", "诺克萨斯统领", "虚空之眼",
    "岩雀", "光辉女郎", "爆破鬼才", "解脱者", "死亡颂唱者", "猩红收割者", "铸星龙王", "流光镜影"
]
# 分辨率比例常量，统一采用 (left_x, top_y, width, height) 格式
RATIO_W = (0.4043, 0.8984, 0.0352, 0.0469)      # W技能框
RATIO_SHOP = (0.5967, 0.9713, 0.0250, 0.0250)   # 商店框
RATIO_ROLE = (0.6492, 0.8333, 0.022, 0.028)     # 分路任务
RATIO_TEAMMATE_AVATARS = [                      # 队友头像
    (0.8040, 0.6350, 0.0350, 0.0450),
    (0.8550, 0.6350, 0.0350, 0.0450),
    (0.9060, 0.6350, 0.0350, 0.0450),
    (0.9570, 0.6350, 0.0350, 0.0450)
]
RATIO_TEAMMATE_HPS = [                          # 队友血条
    (0.8030, 0.6830, 0.0380, 0.010),
    (0.8540, 0.6830, 0.0380, 0.010),
    (0.9050, 0.6830, 0.0380, 0.010),
    (0.9560, 0.6830, 0.0380, 0.010)
]
RATIO_ZONE1 = (0.7812, 0.5750, 0.2188, 0.1171)  # 禁区1右侧血条
RATIO_ZONE2 = (0.3134, 0.8393, 0.3292, 0.3007)  # 禁区2底部OCR


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def get_mouse_pos():
    pt = POINT()
    # noinspection PyUnresolvedReferences
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def human_move(dest_x, dest_y, duration_min=0.01, duration_max=0.04, safe_zone=False):
    """
    基于三次贝塞尔曲线(Cubic Bézier Curve)的仿生鼠标移动
    """
    start_x, start_y = get_mouse_pos()
    hwnd = win32gui.FindWindow(None, WINDOW_NAME)
    if hwnd:
        client_pt = win32gui.ClientToScreen(hwnd, (0, 0))
        rect = win32gui.GetClientRect(hwnd)
        base_x, base_y = client_pt[0], client_pt[1]
        win_w, win_h = rect[2], rect[3]
    else:
        base_x, base_y, win_w, win_h = 0, 0, 1024, 768

    def enforce_safe_zone(cx, cy):
        if not safe_zone:
            return cx, cy
        r1_left, r1_top = base_x + int(win_w * RATIO_ZONE1[0]), base_y + int(win_h * RATIO_ZONE1[1])
        r1_right, r1_bottom = r1_left + int(win_w * RATIO_ZONE1[2]), r1_top + int(win_h * RATIO_ZONE1[3])

        r2_left, r2_top = base_x + int(win_w * RATIO_ZONE2[0]), base_y + int(win_h * RATIO_ZONE2[1])
        r2_right, r2_bottom = r2_left + int(win_w * RATIO_ZONE2[2]), r2_top + int(win_h * RATIO_ZONE2[3])

        if r1_left <= cx <= r1_right and r1_top <= cy <= r1_bottom:
            cx = r1_left - 5
        if r2_left <= cx <= r2_right and r2_top <= cy <= r2_bottom:
            cy = r2_top - 5
        return cx, cy

    # 目标点加入正态分布的微小偏差
    dest_x = int(dest_x + random.gauss(0, 3))
    dest_y = int(dest_y + random.gauss(0, 3))
    dest_x, dest_y = enforce_safe_zone(dest_x, dest_y)

    distance = math.hypot(dest_x - start_x, dest_y - start_y)
    if distance < 10:
        pydirectinput.moveTo(dest_x, dest_y)
        return

    # 生成两个随机的控制点，使得轨迹变成一条随机弧线。控制点在起点和终点连线的两侧随机偏移
    offset = distance * 0.3
    p1_x = int(start_x + (dest_x - start_x) * 0.33 + random.uniform(-offset, offset))
    p1_y = int(start_y + (dest_y - start_y) * 0.33 + random.uniform(-offset, offset))

    p2_x = int(start_x + (dest_x - start_x) * 0.66 + random.uniform(-offset, offset))
    p2_y = int(start_y + (dest_y - start_y) * 0.66 + random.uniform(-offset, offset))

    # 动态步数和总时间
    steps = int(max(5, min(distance / 25, 20)))
    total_time = random.uniform(duration_min, duration_max)
    sleep_per_step = total_time / steps

    for i in range(steps):
        t = i / float(steps)
        # Ease-Out 缓动算法，模拟人手快到目标时的减速
        ease_t = 1 - math.pow(1 - t, 3)

        # 三次贝塞尔曲线公式求解当前坐标
        u = 1 - ease_t
        cur_x = int(u ** 3 * start_x + 3 * u ** 2 * ease_t * p1_x + 3 * u * ease_t ** 2 * p2_x + ease_t ** 3 * dest_x)
        cur_y = int(u ** 3 * start_y + 3 * u ** 2 * ease_t * p1_y + 3 * u * ease_t ** 2 * p2_y + ease_t ** 3 * dest_y)

        # 叠加上高频微小手抖
        wobble_x = random.randint(-1, 1)
        wobble_y = random.randint(-1, 1)

        final_x, final_y = enforce_safe_zone(cur_x + wobble_x, cur_y + wobble_y)
        pydirectinput.moveTo(final_x, final_y)
        time.sleep(sleep_per_step)

    # 最终确保精准落位
    pydirectinput.moveTo(dest_x, dest_y)


def human_click(button='left'):
    """
    仿生学鼠标点击：按压时间服从高斯正态分布
    """
    # 均值 0.06秒，标准差 0.015秒的按压时长 (极度逼近真人微动开关的数据)
    hold_time = max(0.02, random.gauss(0.06, 0.015))

    pydirectinput.mouseDown(button=button)
    time.sleep(hold_time)
    pydirectinput.mouseUp(button=button)


def human_keypress(key, hold_time=None):
    """
    仿生学键盘按压：按键触底到回弹的停留时间服从高斯正态分布
    """
    if hold_time is None:
        # 确保每次调用函数时，都会重新生成一个新的随机数
        hold_time = max(0.02, random.gauss(0.06, 0.015))
    pydirectinput.keyDown(key)
    time.sleep(hold_time)
    pydirectinput.keyUp(key)


def is_game_running():
    try:
        # 如果能获取到游戏基础数据且状态码200，说明已经进入召唤师峡谷
        res = requests.get("https://127.0.0.1:2999/liveclientdata/gamestats", verify=False, timeout=1.0)
        return res.status_code == 200
    except (requests.exceptions.RequestException, ValueError):
        return False


def move_window_to_top_right():
    """将游戏窗口移动到屏幕右上角并聚焦"""
    hwnd = win32gui.FindWindow(None, WINDOW_NAME)
    if hwnd:
        # noinspection PyUnresolvedReferences
        screen_w = ctypes.windll.user32.GetSystemMetrics(0)
        win_rect = win32gui.GetWindowRect(hwnd)
        win_w = win_rect[2] - win_rect[0]
        win_h = win_rect[3] - win_rect[1]

        new_x = screen_w - win_w
        new_y = 0

        win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, new_x, new_y, win_w, win_h, win32con.SWP_SHOWWINDOW)
        log(f"🪟 已将游戏窗口移动至右上角: ({new_x}, {new_y})")
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            win32gui.SetForegroundWindow(hwnd)
            log("🪟 已激活并聚焦游戏窗口")
        except Exception as e:
            log(f"窗口聚焦失败: {e}", level="warning")
        return True
    return False


def calculate_and_cache_regions():
    """计算所有关联坐标与区域，并注入全局缓存"""
    hwnd = win32gui.FindWindow(None, WINDOW_NAME)
    if hwnd:
        client_point = win32gui.ClientToScreen(hwnd, (0, 0))
        client_rect = win32gui.GetClientRect(hwnd)
        cx, cy = client_point[0], client_point[1]
        cw, ch = client_rect[2], client_rect[3]

        # 基础宽高与中心点
        game_state['client_x'] = cx
        game_state['client_y'] = cy
        game_state['client_w'] = cw
        game_state['client_h'] = ch
        game_state['center_x'] = cx + cw // 2
        game_state['center_y'] = cy + ch // 2

        # 预计算 mss 截图字典
        game_state['w_region'] = {
            'top': cy + int(ch * RATIO_W[1]),
            'left': cx + int(cw * RATIO_W[0]),
            'width': int(cw * RATIO_W[2]),
            'height': int(ch * RATIO_W[3])
        }
        game_state['shop_region'] = {
            'top': cy + int(ch * RATIO_SHOP[1]),
            'left': cx + int(cw * RATIO_SHOP[0]),
            'width': int(cw * RATIO_SHOP[2]),
            'height': int(ch * RATIO_SHOP[3])
        }

        # 预计算队友头像
        game_state['teammate_avatars'] = [{
            'center_x': cx + int(cw * (r[0] + r[2] / 2)),
            'center_y': cy + int(ch * (r[1] + r[3] / 2))
        } for r in RATIO_TEAMMATE_AVATARS]

        # 预计算队友血条
        game_state['teammate_hps'] = [{
            'top': cy + int(ch * r[1]),
            'left': cx + int(cw * r[0]),
            'width': int(cw * r[2]),
            'height': int(ch * r[3])
        } for r in RATIO_TEAMMATE_HPS]
        return True
    return False


# 键盘监听钩子 - 模糊吸附
def on_manual_attach(event):
    # 屏蔽脚本模拟的按键，屏蔽升级技能用的 Ctrl+按键
    if not game_state['is_running'] or game_state['is_simulating_attach'] or keyboard.is_pressed('ctrl'):
        return

    x, y = get_mouse_pos()

    # 寻找距离鼠标最近的队友头像
    closest_pos = None
    closest_index = 0
    min_dist = float('inf')

    for i, avatar in enumerate(game_state['teammate_avatars']):
        abs_px = avatar['center_x']
        abs_py = avatar['center_y']
        dist = math.hypot(x - abs_px, y - abs_py)
        if dist < min_dist:
            min_dist = dist
            closest_pos = (abs_px, abs_py)
            closest_index = i

    if closest_pos:
        game_state['attach_x'] = closest_pos[0]
        game_state['attach_y'] = closest_pos[1]

        game_state['attached_teammate_index'] = closest_index
        game_state['last_auto_attach_time'] = time.time()
        game_state['last_manual_attach_time'] = time.time()
        log(f"[按键捕捉] 手动按下 {str(event.name).upper()} 键！已吸附队友 {closest_index + 1} 坐标: {closest_pos}")


def level_up_skill(target_level):
    if target_level > len(SKILL_UPGRADE_ORDER):
        return
    logical_action = str(SKILL_UPGRADE_ORDER[int(target_level) - 1])
    physical_key = KEY_BINDINGS.get(logical_action, logical_action)
    display_name = DISPLAY_NAMES.get(logical_action, logical_action)

    # 上锁，防止被其他技能消耗
    game_state['exclusive_mouse_until'] = time.time() + 1.0
    time.sleep(0.2)

    with mouse_lock:
        pydirectinput.keyDown('ctrl')
        time.sleep(max(0.02, random.gauss(0.05, 0.015)))  # 仿生按压延迟
        human_keypress(physical_key)
        time.sleep(max(0.02, random.gauss(0.05, 0.015)))  # 仿生回弹延迟
        pydirectinput.keyUp('ctrl')
    log(f"🔼 升级啦！当前等级 {target_level}，自动加点: {display_name}")


def get_enemy_positions(img_bgr, win_w, win_h):
    """敌人血条检测"""
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)

    lower_red1, upper_red1 = np.array([0, 150, 100]), np.array([10, 255, 255])
    lower_red2, upper_red2 = np.array([170, 150, 100]), np.array([180, 255, 255])

    mask = cv2.inRange(hsv, lower_red1, upper_red1) + cv2.inRange(hsv, lower_red2, upper_red2)
    kernel = np.ones((max(1, int(win_h * 0.005)), max(1, int(win_w * 0.02))), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    targets = []

    min_w, full_w, full_h = int(win_w * 0.025), int(win_w * 0.125), int(win_h * 0.027)
    y_offset = int(win_h * 0.08)

    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if abs(h - full_h) > 3 or w < min_w or w > full_w:
            continue
        targets.append((x + full_w // 2, y + full_h + y_offset))

    return targets


def api_monitor_thread():
    """API 数据监控线程"""
    while True:
        if game_state['is_running'] and game_state['window_moved']:
            api_success = False
            data = {}
            try:
                res = requests.get("https://127.0.0.1:2999/liveclientdata/allgamedata", verify=False, timeout=0.5)
                if res.status_code == 200:
                    data = res.json()
                    api_success = True
            except Exception as e:
                log(f"API 请求失败，失败原因： {e}")

            if api_success and data:
                events = data.get('events', {}).get('Events', [])
                game_started = any(e.get('EventName') == 'GameStart' for e in events)
                game_end_event = next((e for e in events if e.get('EventName') == 'GameEnd'), {})

                if game_end_event and not game_state['is_paused']:
                    result = game_end_event.get('Result', 'Unknown')

                    if result == "Win":
                        game_state['win_count'] = game_state.get('win_count', 0) + 1
                        log(f"🏆 游戏胜利！当前已累计胜利 {game_state['win_count']} 场。")
                        if game_state['win_count'] >= TARGET_WINS:
                            log("🎉 达到设定的胜利局数，圆满下班！")
                            os._exit(0)
                    else:
                        log(f"💔 游戏失败！别气馁，下一把会更好。")

                    log(f"🛑 识别到 GameEnd 事件，游戏结束，等待退出！")
                    time.sleep(3.0)
                    game_state['current_level'] = 0
                    game_state['is_paused'] = True
                    continue

                # 提取自己当前的等级和极速
                active_player = data.get('activePlayer', {})
                read_level = active_player.get('level', 0)
                game_state['ability_haste'] = active_player.get('championStats', {}).get('abilityHaste', 0.0)

                # 确认己方阵营
                active_name = active_player.get('summonerName')
                all_players = data.get('allPlayers', [])
                if not game_state.get('team_side'):
                    for player in all_players:
                        if player.get('summonerName') == active_name:
                            game_state['team_side'] = player.get('team')
                            break

                # 提取附身队友状态
                allies = [p for p in all_players if
                          p.get('team') == game_state['team_side'] and p.get('summonerName') != active_name]
                current_idx = game_state['attached_teammate_index']
                ally_data = allies[current_idx] if current_idx < len(allies) else {}
                if isinstance(ally_data, dict):
                    game_state['attached_teammate_is_dead'] = ally_data.get('isDead', False)
                    game_state['attached_teammate_respawn_timer'] = ally_data.get('respawnTimer', 0.0)

                if game_started and not game_end_event:
                    if game_state['current_level'] == 0:
                        log(f"⚔️ 识别到等级 {read_level}，确认进入游戏！")
                        # 猫咪出门无需购买
                        game_state['has_shopped_this_visit'] = True
                        game_state['last_shop_time'] = time.time()

                        role_x = game_state['client_x'] + int(
                            game_state['client_w'] * (RATIO_ROLE[0] + RATIO_ROLE[2] / 2))
                        role_y = game_state['client_y'] + int(
                            game_state['client_h'] * (RATIO_ROLE[1] + RATIO_ROLE[3] / 2))
                        with mouse_lock:
                            human_move(role_x, role_y)
                            time.sleep(0.1)
                            human_click('left')
                            time.sleep(0.1)
                            human_click('left') # 点两次防止未聚焦
                        log("🎯 已自动点击分路任务 (辅助位置)")

                        with mouse_lock:
                            human_keypress('y')
                        log("👁️ 已自动按下 Y 键锁定视角")
                        time.sleep(0.5)

                        game_state['current_level'] = read_level
                        level_up_skill(read_level)

                        game_time = data.get('gameData', {}).get('gameTime', 0.0)
                        game_state['start_time'] = time.time() - game_time
                        log(f"⏱️ 游戏时间校准完成！当前对局已进行 {float(game_time) / 60:.1f} 分钟。")

                        side_cn = "蓝色方(基地在左下)" if game_state[
                                                              'team_side'] == 'ORDER' else "红色方(基地在右上)"
                        log(f"🚩 识别到玩家 [{active_name}]，当前阵营: {side_cn}")

                        target_idx = None
                        target_reason = ""
                        # 优先级 1: 官方分路标签为 BOTTOM
                        for i, ally in enumerate(allies):
                            if ally.get('position') == 'BOTTOM':
                                target_idx = i
                                target_reason = "官方分路标签 [BOTTOM]"
                                break
                        # 优先级 2: 常用下路英雄名单匹配
                        if target_idx is None:
                            best_rank = float('inf')  # 初始排名设为无限大
                            for i, ally in enumerate(allies):
                                champ_name = ally.get('championName')
                                if champ_name in COMMON_BOT_CHAMPIONS:
                                    # 获取该英雄在名单里的索引号，越小排名越高
                                    rank = COMMON_BOT_CHAMPIONS.index(champ_name)
                                    # 如果当前英雄的排名比之前找到的还要高，就替换目标
                                    if rank < best_rank:
                                        best_rank = rank
                                        target_idx = i
                                        target_reason = f"高频下路英雄 [{champ_name}] (优先级 {rank + 1})"
                        # 优先级 3: 寻找带惩戒的打野
                        if target_idx is None:
                            for i, ally in enumerate(allies):
                                spells = ally.get('summonerSpells', {})
                                s1 = spells.get('summonerSpellOne', {}).get('displayName', '')
                                s2 = spells.get('summonerSpellTwo', {}).get('displayName', '')
                                if '惩戒' in s1 or '惩戒' in s2:
                                    target_idx = i
                                    target_reason = f"召唤师技能 [惩戒打野 - {ally.get('championName')}]"
                                    break
                        # 优先级 4: 无特征，维持开局时的第 4 位
                        if target_idx is None:
                            target_idx = 3
                            target_reason = "保底匹配"
                        target_name = allies[target_idx].get('summonerName') if target_idx < len(allies) else "未知队友"
                        game_state['attached_teammate_index'] = target_idx
                        game_state['attach_x'] = game_state['teammate_avatars'][target_idx]['center_x']
                        game_state['attach_y'] = game_state['teammate_avatars'][target_idx]['center_y']
                        log(f"🎯 锁定跟随目标: [{target_name}] (UI 第 {target_idx + 1} 位) 锁定原因: {target_reason}")

                    elif read_level > game_state['current_level']:
                        for lvl in range(game_state['current_level'] + 1, read_level + 1):
                            level_up_skill(lvl)
                            time.sleep(0.3)
                        game_state['current_level'] = read_level
        time.sleep(1.0)


def visual_monitor_thread():
    """视觉识别线程"""
    # 动态校准常量基准
    base_w_normal, base_w_attach = 112.12, 122.0
    base_hp_threshold, base_shop_bright = 40.0, 85.0

    in_base_start_time = 0.0
    last_recall_time = 0.0

    with mss.MSS() as sct:
        while True:
            if game_state['is_running'] and game_state['window_moved'] and game_state['current_level'] > 0:
                try:
                    w_region = game_state['w_region']
                    shop_region = game_state['shop_region']

                    # 动态亮度校准
                    if not game_state['is_brightness_calibrated']:
                        log("⏳ 等待 5 秒初始 W 技能冷却，以便进行准确亮度校准...")
                        time.sleep(5.0)

                        w_img_calib = np.array(sct.grab(w_region))
                        w_base_now = np.mean(cv2.cvtColor(w_img_calib, cv2.COLOR_BGRA2GRAY))

                        game_state['brightness_ratio'] = w_base_now / base_w_normal
                        game_state['is_brightness_calibrated'] = True
                        log(f"🔆 屏幕亮度校准完成！W技能基准: {float(w_base_now):.2f} ，亮度系数：{game_state['brightness_ratio']:.2f}")

                    # 商城购买
                    shop_img = np.array(sct.grab(shop_region))
                    shop_gray = cv2.cvtColor(shop_img, cv2.COLOR_BGRA2GRAY)
                    shop_mean = np.mean(shop_gray)

                    is_in_base = shop_mean > (base_shop_bright * game_state['brightness_ratio'])

                    if is_in_base:
                        if not game_state['has_shopped_this_visit'] and (
                                time.time() - game_state.get('last_shop_time', 0.0) > 30.0):
                            log(f"🏠 检测到商城点亮(在泉水)，执行自动购买！")
                            game_state['is_paused'] = True
                            game_state['exclusive_mouse_until'] = time.time() + 4.0
                            with mouse_lock:
                                human_keypress('p')
                                time.sleep(0.5)
                                human_move(game_state['center_x'], game_state['center_y'])
                                time.sleep(0.1)
                                for _ in range(2):
                                    human_click('right')
                                    time.sleep(0.5)
                            log("💰 装备购买完成")
                            time.sleep(0.2)

                            with mouse_lock:
                                human_keypress('p')
                            time.sleep(0.5)

                            game_state['has_shopped_this_visit'] = True
                            game_state['last_shop_time'] = time.time()
                    else:
                        if time.time() - game_state.get('last_shop_time', 0.0) > 30.0:
                            game_state['has_shopped_this_visit'] = False

                    # 确认附身状态
                    w_img = np.array(sct.grab(w_region))
                    w_gray = cv2.cvtColor(w_img, cv2.COLOR_BGRA2GRAY)
                    is_attached = np.mean(w_gray) > (base_w_attach * game_state['brightness_ratio'])
                    current_time = time.time()

                    # 在泉水+已附身->防挂机检测
                    if is_in_base and is_attached:
                        if in_base_start_time == 0.0:
                            in_base_start_time = current_time
                        elif current_time - in_base_start_time > 40.0:
                            log(f"⚠️ 附身队友在泉水挂机！执行自动换乘...")
                            game_state['is_paused'] = True
                            game_state['exclusive_mouse_until'] = time.time() + 2.0
                            game_state['is_simulating_attach'] = True
                            with mouse_lock:
                                human_move(game_state['center_x'], game_state['center_y'])
                                time.sleep(0.1)
                                human_keypress(KEY_BINDINGS['W'])
                            game_state['is_simulating_attach'] = False
                            time.sleep(0.5)

                            new_idx = (game_state['attached_teammate_index'] + 1) % len(game_state['teammate_avatars'])
                            game_state['attached_teammate_index'] = new_idx
                            game_state['attach_x'] = game_state['teammate_avatars'][new_idx]['center_x']
                            game_state['attach_y'] = game_state['teammate_avatars'][new_idx]['center_y']
                            log(f"🎯 已抛弃挂机玩家，目标切换为: 队友 {new_idx + 1}")

                            in_base_start_time = 0.0
                            game_state['last_auto_attach_time'] = 0.0
                    # 在泉水+未附身->执行附身
                    elif is_in_base and not is_attached:
                        in_base_start_time = 0.0
                        game_state['is_paused'] = True

                        if current_time - game_state.get('last_auto_attach_time', 0.0) > 4.0:
                            if game_state.get('attached_teammate_is_dead'):
                                respawn_t = game_state.get('attached_teammate_respawn_timer', 0.0)
                                log(f"⏳ 队友正在复活中 (剩余 {respawn_t:.1f} 秒)，原地右键等待...")
                                game_state['exclusive_mouse_until'] = current_time + 1.0
                                with mouse_lock:
                                    human_move(game_state['center_x'], game_state['center_y'])
                                    time.sleep(0.1)
                                    human_click('right')
                            else:
                                log(f"🔗 在泉水，尝试附身队友 {game_state['attached_teammate_index'] + 1} ...")
                                game_state['exclusive_mouse_until'] = current_time + 1.5
                                game_state['is_simulating_attach'] = True
                                with mouse_lock:
                                    human_move(game_state['attach_x'], game_state['attach_y'])
                                    time.sleep(0.1)
                                    human_keypress(KEY_BINDINGS['W'])
                                game_state['is_simulating_attach'] = False
                                game_state['last_auto_attach_time'] = current_time
                    # 在野外+已附身->恢复动作线程
                    elif not is_in_base and is_attached:
                        in_base_start_time = 0.0
                        if game_state['is_paused']:
                            log(f"📈 已附身，恢复动作线程...")
                            game_state['is_paused'] = False
                            with mouse_lock:
                                human_move(game_state['center_x'], game_state['center_y'])
                                time.sleep(0.05)
                                human_click('right')
                    # 在野外+未附身->回城
                    else:
                        in_base_start_time = 0.0
                        just_detached = False
                        if not game_state['is_paused']:
                            log(f"📉 野外脱落，暂停动作线程...")
                            game_state['is_paused'] = True
                            just_detached = True

                        is_manual_detach = (current_time - game_state.get('last_manual_attach_time', 0.0) < 3.0)

                        # 如果附身队友阵亡，或者刚刚脱落且不是手动脱落，执行反向逃跑
                        if game_state.get('attached_teammate_is_dead') or (just_detached and not is_manual_detach):
                            # 如果距离上次回城超过了 15 秒，才触发新一轮逃跑
                            if current_time - last_recall_time > 15.0:
                                log(f"🚨 队友阵亡或意外脱落，执行反向逃跑与回城！")

                                game_state['exclusive_mouse_until'] = current_time + 10.0
                                with mouse_lock:
                                    if game_state.get('team_side') == 'ORDER':
                                        escape_x = game_state['client_x'] + int(game_state['client_w'] * 0.2)
                                        escape_y = game_state['client_y'] + int(game_state['client_h'] * 0.8)
                                    else:
                                        escape_x = game_state['client_x'] + int(game_state['client_w'] * 0.8)
                                        escape_y = game_state['client_y'] + int(game_state['client_h'] * 0.2)

                                    for _ in range(3):
                                        human_move(escape_x, escape_y)
                                        time.sleep(0.05)
                                        human_click('right')
                                        time.sleep(1.0)

                                    human_keypress('b')
                                    log("🌀 已按下 B 键，回城中...")

                                last_recall_time = time.time()
                        elif current_time - last_recall_time > 9.0 and not game_state.get('attached_teammate_is_dead'):
                            if current_time - game_state.get('last_auto_attach_time', 0.0) > 5.0:
                                log(f"🔗 在野外，尝试附身队友 {game_state['attached_teammate_index'] + 1}...")
                                game_state['exclusive_mouse_until'] = current_time + 1.5
                                game_state['is_simulating_attach'] = True
                                with mouse_lock:
                                    human_move(game_state['attach_x'], game_state['attach_y'])
                                    time.sleep(0.1)
                                    human_keypress(KEY_BINDINGS['W'])
                                game_state['is_simulating_attach'] = False
                                game_state['last_auto_attach_time'] = current_time

                    # 附身队友血条监控
                    is_recently_attached = (current_time - game_state.get('last_auto_attach_time', 0.0) < 2.5) or \
                                           (current_time - game_state.get('last_manual_attach_time', 0.0) < 2.5)
                    if game_state.get('attached_teammate_is_dead') or game_state.get('is_paused'):
                        game_state['attached_teammate_hp_percent'] = 1.0
                    elif not is_recently_attached:
                        current_teammate_idx = game_state['attached_teammate_index']
                        health_region = game_state['teammate_hps'][current_teammate_idx]

                        hp_img = np.array(sct.grab(health_region))
                        hp_gray = cv2.cvtColor(hp_img, cv2.COLOR_BGRA2GRAY)
                        middle_row = hp_gray[hp_gray.shape[0] // 2, :] # 提取血条最中间一行的纯色像素
                        current_hp_threshold = base_hp_threshold * game_state['brightness_ratio']
                        valid_pixels = middle_row > current_hp_threshold
                        if np.any(valid_pixels):
                            # 找到最后一个亮色像素的位置，除以总长度得出百分比
                            current_hp_percent = float(np.max(np.nonzero(valid_pixels)) + 1) / len(valid_pixels)
                        else:
                            current_hp_percent = 0.0
                        # 掉血检测
                        last_hp = game_state.get('attached_teammate_hp_percent', 1.0)
                        if last_hp - current_hp_percent > 0.05:
                            game_state['last_hp_drop_time'] = time.time()
                        game_state['attached_teammate_hp_percent'] = current_hp_percent

                    if not game_state['is_paused'] and current_time - game_state.get('last_enemy_track_time',
                                                                                     0.0) > 0.1:
                        client_monitor = {
                            'top': game_state['client_y'],
                            'left': game_state['client_x'],
                            'width': game_state['client_w'],
                            'height': game_state['client_h']
                        }
                        client_img = np.array(sct.grab(client_monitor))
                        client_bgr = cv2.cvtColor(client_img, cv2.COLOR_BGRA2BGR)
                        raw_targets = get_enemy_positions(client_bgr, game_state['client_w'], game_state['client_h'])

                        # 将相对坐标转换为绝对屏幕坐标，并按距离自己的远近排序
                        global_targets = [(game_state['client_x'] + tx, game_state['client_y'] + ty) for tx, ty in
                                          raw_targets]
                        global_targets.sort(
                            key=lambda t: math.hypot(t[0] - game_state['center_x'], t[1] - game_state['center_y']))

                        game_state['enemy_positions'] = global_targets
                        game_state['last_enemy_track_time'] = current_time
                except Exception as e:
                    log(f"视觉线程异常: {e}")
            time.sleep(0.01)


def action_worker(action_name:str, config, start_offset):
    session_started = False
    last_time = 0.0
    active_start_time = 0.0

    physical_key = KEY_BINDINGS.get(action_name, action_name)
    condition = config.get('condition', 'none')
    logical_name = DISPLAY_NAMES.get(action_name, action_name)
    display_name = f"[{logical_name}] ({physical_key.upper()})"

    def get_actual_cd():
        base_cd = config['base_cd']
        ah = game_state['ability_haste']
        lvl = game_state['current_level']
        if action_name == 'Q' and lvl < 2:
            return 9999.0
        if action_name == 'R':
            if lvl < 6:
                return 9999.0
            elif lvl < 11:
                base_cd = 120.0
            elif lvl < 16:
                base_cd = 110.0
            else:
                base_cd = 100.0

        # 召唤师技能和装备饰品不受常规英雄技能极速加成
        if action_name in ['SUMMONER_HEAL', 'SUMMONER_EXHAUST', 'WARD_AUX_EQUIP', 'WARD_ACCESSORY']:
            return base_cd

        # 常规英雄技能计算公式
        return base_cd * (100.0 / (100.0 + ah))

    while True:
        # 检查互斥锁
        if time.time() < game_state.get('exclusive_mouse_until', 0.0) and action_name != 'Q':
            time.sleep(0.1)
            continue

        if game_state['is_running'] and not game_state['is_paused'] and game_state['current_level'] > 0:
            current_time = time.time()

            if not session_started:
                if current_time - game_state['start_time'] >= (config.get('delay', 0.0) + start_offset):
                    last_time = current_time - 9999.0
                    active_start_time = current_time
                    session_started = True
                    log(f"⏳ {display_name} 达到启动时间！")
                else:
                    time.sleep(0.5)
                    continue

            # CD 检查
            actual_cd = get_actual_cd()
            if actual_cd == 9999.0:
                time.sleep(1.0)
                continue
            if current_time - last_time < actual_cd:
                time.sleep(0.1)
                continue

            # 触发条件
            triggered = False
            target_x, target_y = None, None
            enemies = game_state.get('enemy_positions', [])

            if condition == 'hp_low': # 残血条件
                if game_state.get('attached_teammate_hp_percent', 1.0) < 0.60:
                    triggered = True

            elif condition == 'hp_drop': # 掉血条件
                if current_time - game_state.get('last_hp_drop_time', 0.0) <= 1.0:
                    triggered = True
            elif action_name == 'Q':
                if enemies:
                    triggered = True
                    target_x, target_y = enemies[0]  # 锁定最近的敌人
            elif action_name == 'SUMMONER_EXHAUST':
                # 虚弱判断：遍历所有敌人，只要有进入屏幕 450 像素距离内的就触发
                for ex, ey in enemies:
                    if math.hypot(ex - game_state['center_x'], ey - game_state['center_y']) <= 450:
                        triggered = True
                        target_x, target_y = ex, ey
                        break
            else:
                triggered = True


            # 满足条件后施法
            if triggered:
                if action_name == 'Q':
                    game_state['exclusive_mouse_until'] = current_time + 2.2  # 锁死鼠标防干扰
                    log(f"🎯 发现敌人，触发 {display_name} 并开始制导！")
                    with mouse_lock:
                        human_move(target_x, target_y, safe_zone=True)
                        time.sleep(0.05)
                        human_keypress(physical_key)

                    # Q技能专属：2秒内强制鼠标追踪敌人
                    guide_end = time.time() + 2.0
                    while time.time() < guide_end:
                        current_enemies = game_state.get('enemy_positions', [])
                        if current_enemies:
                            ex, ey = current_enemies[0]
                            with mouse_lock:
                                # 导弹制导要求快狠准，不需要仿生平滑
                                pydirectinput.moveTo(ex, ey)
                        time.sleep(0.03)  # 高频修正坐标

                elif action_name == 'SUMMONER_EXHAUST':
                    game_state['exclusive_mouse_until'] = current_time + 1.0
                    log(f"⚠️ 敌人贴脸！紧急触发 {display_name}！")
                    with mouse_lock:
                        human_move(target_x, target_y, safe_zone=True)
                        time.sleep(0.05)
                        human_keypress(physical_key)

                else:
                    # R技能与眼位：保留原生随机/方向逻辑。如果 R 遇到敌人，会向敌人方向释放。
                    radius_range = config.get('radius')
                    if radius_range is not None:
                        if config.get('is_poke') and enemies:
                            tx, ty = enemies[0]  # R 追踪敌人
                        else:
                            r = random.uniform(radius_range[0], radius_range[1])
                            if config.get('is_poke'):
                                theta = random.uniform(-math.pi / 2, 0) if game_state[
                                                                               'team_side'] == 'ORDER' else random.uniform(
                                    math.pi / 2, math.pi)
                            else:
                                theta = random.uniform(0, 2 * math.pi)
                            tx = int(game_state['center_x'] + r * math.cos(theta))
                            ty = int(game_state['center_y'] + r * math.sin(theta))

                        game_state['exclusive_mouse_until'] = current_time + 1.0
                        with mouse_lock:
                            human_move(tx, ty, safe_zone=True)
                            time.sleep(0.05)
                            human_keypress(physical_key)
                    else:
                        with mouse_lock:
                            human_keypress(physical_key)
                    log(f"✅ 条件触发 {display_name}")

                last_time = time.time()
        else:
            if not game_state['is_running']:
                session_started = False

        time.sleep(0.01)


def idle_mouse_worker():
    """
    低优先级发呆滑鼠线程：模拟真人玩家附身时的无聊乱晃
    """
    while True:
        # 如果游戏没运行、正在买东西暂停、或者鼠标被其他技能霸占，就静静等待
        if not game_state['is_running'] or game_state['is_paused'] or time.time() < game_state.get(
                'exclusive_mouse_until', 0.0):
            time.sleep(1.0)
            continue

        # 悠米专属：如果确定在附身状态且没有事干，有 30% 概率触发一次发呆动作
        if game_state['current_level'] > 0 and random.random() < 0.3:
            # 霸占鼠标互斥锁，防止晃动到一半时 Q 技能突然抢鼠标
            game_state['exclusive_mouse_until'] = time.time() + 1.0

            if random.random() < 0.3:
                with mouse_lock:
                    human_keypress('tab', random.uniform(0.8, 2.5))
            else:
                # 在屏幕中心附近随机生成一个闲逛坐标
                rx = int(game_state['center_x'] + random.uniform(-400, 400))
                ry = int(game_state['center_y'] + random.uniform(-300, 300))

                with mouse_lock:
                    human_move(rx, ry, duration_min=0.4, duration_max=0.8, safe_zone=True)
                # 晃完之后，偶尔会有真人的发呆停顿 (0.5 到 3 秒不动)
                time.sleep(random.uniform(0.5, 3.0))

        # 线程循环检测间隔
        time.sleep(random.uniform(1.0, 2.5))


def main_controller():
    log("🤖 悠米专属高级自动化脚本已启动...")
    log("提示：按 [Ctrl + F12] 终止。")

    attach_key = KEY_BINDINGS.get('W', 'w')
    keyboard.on_press_key(attach_key, on_manual_attach)
    keyboard.add_hotkey('ctrl+f12', lambda: os._exit(0))

    cv_thread = threading.Thread(target=visual_monitor_thread, daemon=True)
    cv_thread.start()

    api_thread = threading.Thread(target=api_monitor_thread, daemon=True)
    api_thread.start()

    offset = 0.5
    for action, config in ACTION_CONFIG.items():
        t = threading.Thread(target=action_worker, args=(action, config, offset), daemon=True)
        t.start()
        offset += 1.2
    idle_thread = threading.Thread(target=idle_mouse_worker, daemon=True)
    idle_thread.start()

    try:
        while True:
            running = is_game_running()

            if running and not game_state['is_running']:
                game_state['is_running'] = True
                game_state['start_time'] = time.time()
                game_state['current_level'] = 0
                game_state['is_paused'] = False
                game_state['window_moved'] = False
                game_state['has_shopped_this_visit'] = False
                log(f"🎮 游戏进程启动！等待进入游戏界面...")
                time.sleep(1.0)
                if move_window_to_top_right() and calculate_and_cache_regions():
                    game_state['window_moved'] = True
            elif running and game_state['is_running'] and not game_state['window_moved']:
                if move_window_to_top_right() and calculate_and_cache_regions():
                    game_state['window_moved'] = True


            elif not running and game_state['is_running']:
                game_state['is_running'] = False
                game_state['start_time'] = None
                game_state['window_moved'] = False
                log(f"🛑 游戏结束...")

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

                    log(f"🪟 已将游戏大厅移动至右上角: ({new_x}, {new_y})")
                    # 2. 点击底部三角标跳过结算等待动画
                    time.sleep(2.0)
                    skip_x = new_x + win_w // 2
                    skip_y = win_h - 55
                    with mouse_lock:
                        human_move(skip_x, skip_y)
                        time.sleep(0.5)
                        human_click('left')
                    log("⏭️ 已点击跳过结算动画")

                    # 3. 移动鼠标到大厅底部左侧位置并连续点击，触发 LeagueAkari 所需的重新匹配
                    time.sleep(3.0)
                    target_x = new_x + win_w // 2 - 70
                    target_y = win_h - 40
                    with mouse_lock:
                        human_move(target_x, target_y)
                        for _ in range(5):
                            time.sleep(2.5)
                            human_click('left')

                    log("🖱️ 已点击大厅底部中央，准备衔接 LeagueAkari 自动匹配！")

            time.sleep(2.0)

    except KeyboardInterrupt:
        log("⏹️ 接收到中断信号，脚本已安全停止。")


if __name__ == "__main__":
    main_controller()