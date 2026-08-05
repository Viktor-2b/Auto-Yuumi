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
file_handler = RotatingFileHandler(log_file, maxBytes=2*1024*1024, backupCount=3, encoding='utf-8')
file_handler.setFormatter(log_formatter)
console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter('[%(asctime)s] %(message)s', datefmt='%H:%M:%S'))

logger = logging.getLogger('YuumiBot')
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

def log(msg, level="info"):
    if level == "info": logger.info(msg)
    elif level == "warning": logger.warning(msg)
    elif level == "error": logger.error(msg)

TARGET_PROCESS_NAME = "League of Legends.exe"
WINDOW_NAME = "League of Legends (TM) Client"
TRANSITION_TIME = 1600.0
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
    'Q': {'base_cd': 6.5, 'mana_delay': 30.0, 'delay': 0.0, 'condition': 'none', 'radius': [300, 450]},
    'E': {'base_cd': 10.0, 'mana_delay': 10.0, 'delay': 0.0, 'condition': 'none', 'radius': [0, 10]},
    'R': {'base_cd': 120.0, 'delay': 0.0, 'condition': 'low_health', 'radius': [50, 150]},
    'SUMMONER_HEAL': {'base_cd': 240.0, 'delay': 0.0, 'condition': 'low_health', 'radius': [0, 10]},
    'SUMMONER_EXHAUST': {'base_cd': 240.0, 'delay': 0.0, 'condition': 'none', 'radius': [50, 150]},
    'WARD_AUX_EQUIP': {'base_cd': 45.0, 'delay': 600.0, 'condition': 'none', 'radius': [60, 120]},
    'WARD_ACCESSORY': {'base_cd': 150.0, 'delay': 0.0, 'condition': 'none', 'radius': [60, 120]},
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
    'team_side': None,
    # 记录技能极速
    'abilityHaste': 0.0,
    # 记录在泉水里附身停留的起始时间，用于防挂机
    'in_base_start_time': 0.0
}
# 高频下路英雄清单 (包含常规ADC与法核)
COMMON_BOT_CHAMPIONS = [
    "戏命师", "不破之誓", "涤魂圣枪", "圣枪游侠", "虚空之女", "祖安花火", "麦林炮手", "战争女神", "赏金猎人",
    "荣耀行刑官", "逆羽", "复仇之矛", "暴走萝莉", "皮城女警", "暗夜猎手", "寒冰射手", "残月之肃", "瘟疫之源",
    "英勇投弹手", "深渊巨口", "炽炎雏龙", "惩戒之箭", "沙漠玫瑰", "不羁之悦", "探险家", "疾风剑豪",
    "远古巫灵", "奥术先驱", "星籁歌姬", "异画师", "魔蛇之拥", "暗黑元首", "邪恶小法师", "诺克萨斯统领", "虚空之眼",
    "岩雀", "光辉女郎", "爆破鬼才", "解脱者", "死亡颂唱者", "猩红收割者", "铸星龙王", "流光镜影"
]
# 分辨率比例常量
RATIO_W = (0.4043, 0.8984, 0.0352, 0.0469)  # W技能框
RATIO_SHOP = (0.5967, 0.9713, 0.0195, 0.0208)  # 商店框
RATIO_ROLE = (0.6592, 0.8463)  # 分路任务点击 (X, Y)
RATIO_ATTACH_Y = 0.6575  # 队友头像Y坐标
RATIO_TEAMMATE_X = [0.8203, 0.8730, 0.9228, 0.9726]  # 四个队友头像X坐标
RATIO_HP_Y_W_H = (0.6836, 0.0097, 0.0078)  # 血条探测框 (Y, W, H)
RATIO_ZONE1 = (0.7812, 0.6250, 0.7421)  # 禁区1右侧血条 (left_x, top_y, bottom_y)
RATIO_ZONE2 = (0.2734, 0.8593, 0.7226)  # 禁区2底部OCR (left_x, top_y, right_x)


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
        r1_right, r1_bottom = base_x + win_w, base_y + int(win_h * RATIO_ZONE1[2])

        r2_left, r2_top = base_x + int(win_w * RATIO_ZONE2[0]), base_y + int(win_h * RATIO_ZONE2[1])
        r2_right, r2_bottom = base_x + int(win_w * RATIO_ZONE2[2]), base_y + win_h

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


def human_keypress(key):
    """
    仿生学键盘按压：按键触底到回弹的停留时间服从高斯正态分布
    """
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

        log(f"🪟 已将游戏窗口移动至右上角: ({new_x}, {new_y})")
        return True
    return False


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


def visual_monitor_thread():
    # 动态校准常量基准 (基于本机环境)
    base_w_normal = 112.12
    base_w_attach = 122.0
    base_health_black = 100.0
    base_shop_bright = 100.0

    last_print_time = 0.0

    while True:
        if game_state['is_running'] and game_state['window_moved']:
            try:
                hwnd = win32gui.FindWindow(None, WINDOW_NAME)
                if not hwnd:
                    continue

                client_point = win32gui.ClientToScreen(hwnd, (0, 0))
                client_rect = win32gui.GetClientRect(hwnd)
                win_w, win_h = client_rect[2], client_rect[3]

                # ================= 区域坐标计算 =================
                abs_x_w = client_point[0] + int(win_w * RATIO_W[0])
                abs_y_w = client_point[1] + int(win_h * RATIO_W[1])
                w_region = {'top': abs_y_w, 'left': abs_x_w, 'width': int(win_w * RATIO_W[2]),
                            'height': int(win_h * RATIO_W[3])}

                shop_region = {
                    'top': client_point[1] + int(win_h * RATIO_SHOP[1]),
                    'left': client_point[0] + int(win_w * RATIO_SHOP[0]),
                    'width': int(win_w * RATIO_SHOP[2]),
                    'height': int(win_h * RATIO_SHOP[3])
                }

                teammate_x_list = [int(win_w * rx) for rx in RATIO_TEAMMATE_X]

                api_success = False
                data = {}
                try:
                    res = requests.get("https://127.0.0.1:2999/liveclientdata/allgamedata", verify=False, timeout=1.0)
                    if res.status_code == 200:
                        data = res.json()
                        api_success = True
                except Exception as e:
                    log(e)
                    pass

                if api_success and data:
                    # 检查是否出现游戏结束事件 (GameEnd)
                    events_data = data.get('events') or {}
                    events = events_data.get('Events') or []
                    game_ended = any(e.get('EventName') == 'GameEnd' for e in events)
                    game_started = any(e.get('EventName') == 'GameStart' for e in events)

                    if game_ended and game_state['current_level'] > 0:
                        log(f"🛑 识别到 GameEnd 事件，游戏结束，点击屏幕中心退出！")
                        with mouse_lock:
                            human_move(game_state['center_x'], game_state['center_y'])
                            time.sleep(0.1)
                            human_click('left')
                        time.sleep(1.5)
                        game_state['current_level'] = 0
                        game_state['is_paused'] = True
                        continue

                    # 提取自己当前的等级
                    active_player = data.get('activePlayer', {})
                    read_level = active_player.get('level', 0)
                    # 提取自己当前的技能极速
                    champ_stats = active_player.get('championStats', {})
                    game_state['abilityHaste'] = champ_stats.get('abilityHaste', 0.0)
                    if 0 < read_level <= 18 and game_started and not game_ended:
                        if game_state['current_level'] == 0:
                            log(f"⚔️ 识别到等级 {read_level}，确认进入游戏！")
                            # 开局直接标记为已购买
                            game_state['has_shopped_this_visit'] = True
                            game_state['last_shop_time'] = time.time()

                            time.sleep(5.0)
                            # ================= 动态亮度校准 =================
                            with mss.MSS() as sct:
                                w_img_calib = np.array(sct.grab(w_region))
                                w_base_now = np.mean(cv2.cvtColor(w_img_calib, cv2.COLOR_BGRA2GRAY))

                            # 防止异常黑屏导致除以0。如果你是在附身状态下重启脚本(亮度约131)，这里给个警告
                            if w_base_now < 10.0: w_base_now = base_w_normal
                            game_state['brightness_ratio'] = w_base_now / base_w_normal
                            log(f"🔆 屏幕亮度校准完成！W技能基准: {float(w_base_now):.2f} ")

                            # 1. 中心点聚焦点击
                            with mouse_lock:
                                human_move(game_state['center_x'], game_state['center_y'])
                                time.sleep(0.1)
                                human_click('left')
                            log("🖱️ 已点击屏幕中心聚焦游戏窗口")
                            time.sleep(0.5)

                            with mouse_lock:
                                human_keypress('y')
                            log("👁️ 已自动按下 Y 键锁定视角")
                            time.sleep(0.5)

                            # 2. 分路选择点击 (拆分按下与松开)
                            role_x = client_point[0] + int(win_w * RATIO_ROLE[0])
                            role_y = client_point[1] + int(win_h * RATIO_ROLE[1])
                            with mouse_lock:
                                human_move(role_x, role_y)
                                time.sleep(0.1)
                                human_click('left')
                            log("🎯 已自动点击分路任务 (辅助位置)")

                            game_state['current_level'] = read_level
                            level_up_skill(read_level)

                            game_time = data.get('gameData', {}).get('gameTime', 0.0)

                            game_state['start_time'] = time.time() - game_time
                            log(f"⏱️ 游戏时间校准完成！当前对局已进行 {float(game_time) / 60:.1f} 分钟。")

                            # 1. 获取当前玩家名字
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
                                log(f"🚩 识别到玩家 [{active_name}]，当前阵营: {side_cn}")
                                # 取出所有队友（排除自己）
                                allies = [p for p in all_players if
                                          p.get('team') == game_state['team_side'] and (
                                                  p.get('riotIdGameName') or p.get(
                                              'summonerName')) != active_name]

                                target_idx = None
                                target_reason = ""

                                # 优先级 1: 官方分路标签为 BOTTOM (适用于排位/征召)
                                for i, ally in enumerate(allies):
                                    if ally.get('position') == 'BOTTOM':
                                        target_idx = i
                                        target_reason = "官方分路标签 [BOTTOM]"
                                        break

                                # 优先级 2: 常用下路英雄名单匹配 (适用于匹配/人机)
                                if target_idx is None:
                                    best_rank = float('inf')  # 初始排名设为无限大
                                    for i, ally in enumerate(allies):
                                        champ_name = ally.get('championName')
                                        if champ_name in COMMON_BOT_CHAMPIONS:
                                            # 获取该英雄在名单里的索引号（越小排名越高）
                                            rank = COMMON_BOT_CHAMPIONS.index(champ_name)
                                            # 如果当前英雄的排名比之前找到的还要高，就替换目标
                                            if rank < best_rank:
                                                best_rank = rank
                                                target_idx = i
                                                target_reason = f"高频下路英雄 [{champ_name}] (优先级 {rank + 1})"

                                # 优先级 3: 寻找带惩戒的打野 (超级兜底)
                                if target_idx is None:
                                    for i, ally in enumerate(allies):
                                        spells = ally.get('summonerSpells', {})
                                        s1 = spells.get('summonerSpellOne', {}).get('displayName', '')
                                        s2 = spells.get('summonerSpellTwo', {}).get('displayName', '')
                                        if '惩戒' in s1 or '惩戒' in s2:
                                            target_idx = i
                                            target_reason = f"召唤师技能 [惩戒打野 - {ally.get('championName')}]"
                                            break

                                # 优先级 4: 无特征，维持开局时的第 4 位盲猜
                                if target_idx is None:
                                    target_idx = 3
                                    target_reason = "保底匹配"
                                target_name = allies[target_idx].get('riotIdGameName') or allies[
                                    target_idx].get('summonerName')
                                game_state['attached_teammate_index'] = target_idx
                                game_state['attach_x'] = client_point[0] + teammate_x_list[target_idx]
                                game_state['attach_y'] = client_point[1] + int(win_h * RATIO_ATTACH_Y)
                                log(
                                    f"🎯 锁定跟随目标: [{target_name}] (UI 第 {target_idx + 1} 位) 锁定原因: {target_reason}")


                        elif read_level > game_state['current_level']:
                            game_state['current_level'] = read_level
                            level_up_skill(read_level)

                    if game_state['current_level'] > 0 and game_state['start_time'] is not None:
                        with mss.MSS() as sct:
                            # ================= 商城回城状态处理 =================
                            shop_img = np.array(sct.grab(shop_region))
                            shop_gray = cv2.cvtColor(shop_img, cv2.COLOR_BGRA2GRAY)
                            cv2.imwrite(os.path.join('debug', 'ocr_shop.png'), shop_gray)
                            shop_mean = np.mean(shop_gray)

                            is_in_base = shop_mean > (base_shop_bright * game_state['brightness_ratio'])

                            if is_in_base:
                                if not game_state['has_shopped_this_visit'] and (
                                        time.time() - game_state.get('last_shop_time', 0.0) > 30.0):
                                    log(f"🏠 检测到商城点亮(在泉水中)，执行自动购买！")
                                    game_state['is_paused'] = True
                                    game_state['exclusive_mouse_until'] = time.time() + 4.0
                                    with mouse_lock:
                                        human_keypress('p')
                                        time.sleep(0.5)
                                        human_move(game_state['center_x'], game_state['center_y'])
                                        time.sleep(0.1)
                                        for i in range(2):
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

                            # ---- W 技能图标状态处理 ----
                            w_img = np.array(sct.grab(w_region))
                            w_gray = cv2.cvtColor(w_img, cv2.COLOR_BGRA2GRAY)
                            cv2.imwrite(os.path.join('debug', 'ocr_w.png'), w_gray)
                            w_mean_brightness = np.mean(w_gray)

                            current_time = time.time()
                            is_attached = w_mean_brightness > (base_w_attach * game_state['brightness_ratio'])

                            if is_in_base and is_attached:
                                if game_state.get('in_base_start_time', 0.0) == 0.0:
                                    game_state['in_base_start_time'] = current_time
                                elif current_time - game_state['in_base_start_time'] > 40.0:
                                    log(f"⚠️ 检测到当前队友在泉水挂机！执行自动换乘...")
                                    game_state['is_paused'] = True
                                    game_state['exclusive_mouse_until'] = time.time() + 2.0
                                    with mouse_lock:
                                        # 移动到屏幕中心按 W 下车
                                        human_move(game_state['center_x'], game_state['center_y'], safe_zone=True)
                                        time.sleep(0.1)
                                        human_keypress(str(KEY_BINDINGS['W']))
                                    time.sleep(0.5)

                                    # 轮换到下一个队友 (0->1->2->3->0 循环)
                                    old_idx = int(game_state['attached_teammate_index'])
                                    new_idx = (old_idx + 1) % len(teammate_x_list)
                                    game_state['attached_teammate_index'] = new_idx
                                    game_state['attach_x'] = int(client_point[0]) + int(teammate_x_list[new_idx])
                                    log(f"🎯 已抛弃挂机玩家，目标自动切换为: 队友 {new_idx + 1}")

                                    # 重置时间，强制下一秒立刻飞向新队友
                                    game_state['in_base_start_time'] = 0.0
                                    game_state['last_auto_attach_time'] = 0.0
                            else:
                                # 只要出泉水，或者当前没附身，立刻清零挂机计时器
                                game_state['in_base_start_time'] = 0.0

                            if current_time - last_print_time > 5.0:
                                last_print_time = current_time

                            if not is_attached:
                                if not game_state['is_paused']:
                                    log(f"📉 未附身/死亡，暂停其余动作循环！")
                                    game_state['is_paused'] = True

                                    # 紧急判断：如果不在泉水，且距离上次手动按A超过3秒（排除玩家正常换人），说明是队友阵亡
                                    if not is_in_base and (
                                            current_time - game_state.get('last_manual_attach_time', 0.0) > 3.0):
                                        log(f"⚠️ 检测到野外意外脱落，按下B键紧急回城！")
                                        with mouse_lock:
                                            human_keypress('b')
                                        game_state['last_recall_time'] = current_time

                                if game_state['attach_x'] and game_state['attach_y']:
                                    # 如果刚刚按了回城，必须等 9 秒读条结束，期间不准执行任何附身动作
                                    if current_time - game_state.get('last_recall_time', 0.0) > 9.0:
                                        if current_time - game_state['last_auto_attach_time'] > 5.0:
                                            log(
                                                f"🔗 尝试自动附身到队友 {game_state['attached_teammate_index'] + 1}...")
                                            game_state['exclusive_mouse_until'] = time.time() + 1.5
                                            game_state['is_simulating_attach'] = True
                                            with mouse_lock:
                                                human_move(game_state['attach_x'], game_state['attach_y'])
                                                time.sleep(0.1)
                                                human_keypress(KEY_BINDINGS['W'])
                                            time.sleep(0.1)
                                            game_state['is_simulating_attach'] = False

                                            game_state['last_auto_attach_time'] = current_time
                            else:
                                if game_state['is_paused'] and not is_in_base:  # 确保在泉水买东西时不要马上重置暂停状态
                                    log(f"📈 判定已成功附身，恢复动作循环！")
                                    game_state['is_paused'] = False
                                    # 成功上车后，立即将鼠标移回屏幕中间，并点一下右键
                                    with mouse_lock:
                                        human_move(game_state['center_x'], game_state['center_y'])
                                        time.sleep(0.05)
                                        human_click('right')
                            # ---- 血条状态处理 (动态追踪) ----
                            # 读取当前记录的队友索引，计算他专属的血条坐标
                            current_teammate_idx = game_state['attached_teammate_index']
                            # 计算随时间递减的X轴偏移量 (从 10 递减到 0)
                            t_elapsed = time.time() - game_state['start_time']
                            ratio = min(1.0, t_elapsed / TRANSITION_TIME)
                            shift_x = int(10 - 20 * ratio)

                            # 原始X中心加上偏移量，提前探测掉血
                            hp_center_x = int(client_point[0]) + teammate_x_list[current_teammate_idx] + shift_x
                            hp_w = int(win_w * RATIO_HP_Y_W_H[1])
                            health_region = {
                                'top': client_point[1] + int(win_h * RATIO_HP_Y_W_H[0]),
                                'left': hp_center_x - (hp_w // 2),
                                'width': hp_w,
                                'height': int(win_h * RATIO_HP_Y_W_H[2])
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
                            if game_state['teammate_low_health'] and not game_state['is_paused'] and not is_in_base:
                                current_time = time.time()

                                # 遍历所有被定性为“紧急救援”的逻辑动作
                                for action_name in ['SUMMONER_HEAL', 'R']:
                                    if action_name == 'R' and game_state['current_level'] < 6:
                                        continue

                                    config = ACTION_CONFIG[action_name]
                                    base_cd = config['base_cd']
                                    if action_name == 'R':
                                        lvl = game_state['current_level']
                                        base_cd = 120.0 if lvl < 11 else (110.0 if lvl < 16 else 100.0)
                                    # 动态冷却计算。治疗等召唤师技能不受常规技能极速影响，R受到极速影响
                                    ah = game_state['abilityHaste']
                                    current_cd = base_cd if action_name == 'SUMMONER_HEAL' else base_cd * (
                                            100.0 / (100.0 + ah))
                                    if current_time - game_state['last_cast'][action_name] >= current_cd:
                                        physical_key = KEY_BINDINGS[action_name]
                                        display_name = DISPLAY_NAMES.get(action_name, action_name)

                                        with mouse_lock:
                                            human_keypress(physical_key)
                                        log(
                                            f"🚨 [紧急救援] 触发 {display_name}！(当前真实冷却: {float(current_cd):.1f}s)")

                                        game_state['last_cast'][action_name] = current_time
                                        time.sleep(0.1)
            except Exception as e:
                log(f"视觉线程异常: {e}")

        time.sleep(0.2)


def action_worker(action_name, config, start_offset):
    session_started = False
    last_time = 0.0
    active_start_time = 0.0

    action_name_str = str(action_name)
    physical_key = str(KEY_BINDINGS.get(action_name_str, action_name_str))
    condition = str(config.get('condition', 'none'))
    logical_name = str(DISPLAY_NAMES.get(action_name_str, action_name_str))
    display_name = f"[{logical_name}] ({physical_key.upper()})"

    def get_actual_cd():
        base_cd = config['base_cd']
        ah = game_state['abilityHaste']
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

    next_interval = config['base_cd']

    while True:
        is_paused_now = game_state['is_paused']

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
                    next_interval = random.uniform(1.0, 3.0)
                    session_started = True
                    log(f"⏳ {display_name} 达到启动时间！")
                else:
                    time.sleep(0.5)
                    continue

            # 双重同步验证：防止和紧急救援模块冲突双次释放
            if action_name in ['SUMMONER_HEAL', 'R']:
                last_time = max(last_time, game_state['last_cast'][action_name])
            # CD 检查完毕
            if current_time - last_time >= next_interval:

                # 残血条件判定
                if condition == 'low_health' and not game_state['teammate_low_health']:
                    # 虽然冷却好了，但队友不残血，憋着不放，睡一小会继续查
                    time.sleep(0.5)
                    continue
                actual_cd = get_actual_cd()
                if actual_cd == 9999.0:  # 比如不到6级，憋着不放
                    time.sleep(1.0)
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

                game_state['exclusive_mouse_until'] = time.time() + 1.5
                with mouse_lock:
                    human_move(rx, ry, safe_zone=True)
                    time.sleep(0.05)
                    human_keypress(physical_key)
                if action_name == 'Q':  # 如果是 Q 技能，释放后锁死所有其他鼠标线程 2 秒
                    game_state['exclusive_mouse_until'] = time.time() + 2.0

                msg = f"触发 {display_name} (距上次 {next_interval:.2f}s)"
                if condition == 'low_health':
                    msg += " [⚠️队友残血触发]"
                log(msg)

                last_time = time.time()
                if action_name in ['SUMMONER_HEAL', 'R']:
                    game_state['last_cast'][action_name] = last_time
                active_elapsed_time = current_time - active_start_time
                base_mana_delay = config.get('mana_delay', 0.0)

                if base_mana_delay > 0:
                    # 随着游戏时间推移(TRANSITION_TIME)，额外延迟线性衰减到 0
                    current_mana_delay = max(0.0, base_mana_delay - (
                            base_mana_delay / TRANSITION_TIME) * active_elapsed_time)
                else:
                    current_mana_delay = 0.0

                # 最终释放间隔 = 面板真实CD + 当前剩余的省蓝额外延迟 + 真人反应手抖
                next_interval = actual_cd + current_mana_delay + random.uniform(0.1, 0.5)
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
    client_rect = win32gui.GetClientRect(hwnd)
    base_x, base_y = client_point
    win_w, win_h = client_rect[2], client_rect[3]

    # 填入你校准的4个队友头像相对中心点坐标
    teammate_rel_positions = [
        (int(win_w * rx), int(win_h * RATIO_ATTACH_Y)) for rx in RATIO_TEAMMATE_X
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
        log(
            f"[按键捕捉] 手动按下 {str(event.name).upper()} 键！已吸附队友 {closest_index + 1} 坐标: {closest_pos}")


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

        # 悠米专属：如果确定在附身状态且没有事干，有 30% 概率触发一次鼠标乱晃
        if game_state['current_level'] > 0 and random.random() < 0.3:
            # 霸占鼠标互斥锁，防止晃动到一半时 Q 技能突然抢鼠标
            game_state['exclusive_mouse_until'] = time.time() + 1.0

            # 在屏幕中心附近随机生成一个闲逛坐标
            rx = int(game_state['center_x'] + random.uniform(-400, 400))
            ry = int(game_state['center_y'] + random.uniform(-300, 300))

            # 缓慢而慵懒地滑过去 (耗时 0.4 到 0.8 秒)
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
                if move_window_to_top_right():
                    game_state['window_moved'] = True
            elif running and game_state['is_running'] and not game_state['window_moved']:
                if move_window_to_top_right():
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
                        for i in range(5):
                            time.sleep(2.5)
                            human_click('left')

                    log("🖱️ 已点击大厅底部中央，准备衔接 LeagueAkari 自动匹配！")

            time.sleep(2.0)

    except KeyboardInterrupt:
        log("⏹️ 接收到中断信号，脚本已安全停止。")


if __name__ == "__main__":
    main_controller()
