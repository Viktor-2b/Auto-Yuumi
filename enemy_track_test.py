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
    mask = mask1 + mask2

    kh = max(1, int(win_h * 0.005))
    kw = max(1, int(win_w * 0.02))
    kernel = np.ones((kh, kw), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    targets = []
    debug_img = img_bgr.copy()
    # 固定的完整血条物理尺寸
    min_w = int(win_w * 0.025)
    full_w = int(win_w * 0.125)
    full_h = int(win_h * 0.027)

    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)

        # 高度符合（容差±3像素）
        if abs(h - full_h) > 3:
            continue
        # 宽度符合
        if w < min_w or w> full_w:
            continue

        cx = x + full_w // 2

        # 下移偏移量
        y_offset = int(win_h * 0.08)
        cy = y + full_h + y_offset

        targets.append((cx, cy))

        # 在 debug 图上画出识别到的整体血条底板框
        debug_img = draw_transparent_rect(debug_img, (x, y), (x + full_w, y + full_h), (0, 255, 0), 0.4)

        # 画出目标点击框
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