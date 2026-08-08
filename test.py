import cv2
import mss
import win32gui
import numpy as np
import time
import keyboard
import pydirectinput
import ctypes
import os

WINDOW_NAME = "League of Legends (TM) Client"

# 强制开启 Windows DPI 感知
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except:
    pass


def draw_transparent_rect(img, top_left, bottom_right, color, alpha=0.4):
    """绘制半透明矩形框"""
    overlay = img.copy()
    cv2.rectangle(overlay, top_left, bottom_right, color, -1)
    cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)
    cv2.rectangle(img, top_left, bottom_right, color, 2)
    return img


def get_enemy_positions_and_debug(img_bgr, win_w, win_h):
    hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)

    # 锁定暗红色/深褐色的血条底板和等级框
    lower_red1 = np.array([0, 150, 100])
    upper_red1 = np.array([10, 255, 255])
    lower_red2 = np.array([170, 150, 100])
    upper_red2 = np.array([180, 255, 255])

    mask1 = cv2.inRange(hsv, lower_red1, upper_red1)
    mask2 = cv2.inRange(hsv, lower_red2, upper_red2)
    raw_mask = mask1 + mask2  # 保存未经任何形态学处理的原始掩码，用于后续密度计算

    # =======================================================
    # 【新增保险1】垂直开运算：专门克制小兵血条
    # 策略：直接切断并抹除小兵的细长血条（厚度约4px）
    # 英雄血条较厚(>10px)，且等级框左右两侧边缘较高(>15px)，能完美存活
    # =======================================================
    kh_open = max(4, int(win_h * 0.007))  # 在 1080p 下约 7px, 768p 下约 5px
    kernel_open = np.ones((kh_open, 1), np.uint8)
    mask = cv2.morphologyEx(raw_mask, cv2.MORPH_OPEN, kernel_open)

    # =======================================================
    # 【新增保险2】水平闭运算：修补英雄血条
    # 策略：将刚才可能被开运算切断的英雄等级框左右两侧重新拼接，并桥接血条的黑色刻度线
    # =======================================================
    kw_close = max(1, int(win_w * 0.02))
    kernel_close_w = np.ones((1, kw_close), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close_w)

    # 垂直闭运算（收尾）：使边缘平整，填补微小纵向缺口
    kh_close = max(1, int(win_h * 0.005))
    kernel_close_h = np.ones((kh_close, 1), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close_h)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    targets = []
    debug_img = img_bgr.copy()

    # 固定的完整血条物理尺寸
    full_w = int(win_w * 0.125)
    full_h = int(win_h * 0.027)
    # 【纠正】极度残血时只剩下等级框，宽度约等于 full_h，因此 min_w 改为 full_h 的 75% 保证1滴血也能被识别
    min_w = int(full_h * 0.75)

    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)

        # 1. 高度必须严格符合英雄血条高度（容差±3像素）
        if abs(h - full_h) > 3:
            continue
        # 2. 宽度必须在【残血等级框宽度】到【满血血条宽度】之间
        if w < min_w or w > full_w:
            continue

        # =======================================================
        # 【新增保险3】像素密度校验：终极防误判
        # 在原始纯净掩码中，英雄血条区域是一个高密度的红块（填充率通常>50%）
        # 而小兵即便碰巧挤成了类似大小的矩形，内部也全都是空隙，密度极低
        # =======================================================
        roi = raw_mask[y:y + h, x:x + w]
        fill_ratio = cv2.countNonZero(roi) / (w * h)
        if fill_ratio < 0.35:
            continue

        # 一旦走到这里，必然是纯正的敌方英雄
        cx = x + full_w // 2

        # 下移偏移量，锁定模型中心
        y_offset = int(win_h * 0.08)
        cy = y + full_h + y_offset

        targets.append((cx, cy))

        # 在 debug 图上画出识别到的整体预估血条底板框
        debug_img = draw_transparent_rect(debug_img, (x, y), (x + full_w, y + full_h), (0, 255, 0), 0.4)

        # 画出目标点击准星框
        target_box_r = int(win_h * 0.015)
        target_tl = (cx - target_box_r, cy - target_box_r)
        target_br = (cx + target_box_r, cy + target_box_r)
        debug_img = draw_transparent_rect(debug_img, target_tl, target_br, (0, 255, 255), 0.5)

        cv2.line(debug_img, (cx, y + full_h), (cx, cy), (255, 255, 255), 2)

    return targets, debug_img


def main():
    hwnd = win32gui.FindWindow(None, WINDOW_NAME)
    if not hwnd:
        print("❌ 找不到游戏窗口，请确保已经进入对局。")
        return

    client_pt = win32gui.ClientToScreen(hwnd, (0, 0))
    rect = win32gui.GetClientRect(hwnd)
    base_x, base_y = client_pt[0], client_pt[1]
    win_w, win_h = rect[2], rect[3]

    monitor = {"top": base_y, "left": base_x, "width": win_w, "height": win_h}
    print(f"✅ 成功锁定游戏窗口，分辨率: {win_w}x{win_h}")
    print("🚀 开始通过【暗色底板算法】追踪敌方血条...")
    print("⚠️ 按 [Ctrl + F12] 立即退出测试！\n")

    os.makedirs("debug", exist_ok=True)

    keyboard.add_hotkey('ctrl+f12', lambda: os._exit(0))

    with mss.MSS() as sct:
        while True:
            sct_img = sct.grab(monitor)
            img = np.array(sct_img)
            img_bgr = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

            targets, debug_img = get_enemy_positions_and_debug(img_bgr, win_w, win_h)

            if targets:
                targets.sort(key=lambda t: t[0])
                target_x, target_y = targets[0]

                screen_x = base_x + target_x
                screen_y = base_y + target_y

                pydirectinput.moveTo(screen_x, screen_y)
                print(f"🎯 锁定敌人！鼠标坐标: ({screen_x}, {screen_y})")

                out_path = os.path.join("debug", "debug_enemy_target.png")
                cv2.imwrite(out_path, debug_img)

            time.sleep(3.05)


if __name__ == "__main__":
    main()