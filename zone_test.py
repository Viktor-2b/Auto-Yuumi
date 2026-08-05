import win32gui
import mss
import numpy as np
import cv2
import os

WINDOW_NAME = "League of Legends (TM) Client"

# ==========================================
# 在这里填入你想要测试的比例
# ==========================================
RATIO_ZONE1 = (0.7812, 0.6250, 0.7421)             # 禁区1: 右侧血条 (left_x, top_y, bottom_y)
RATIO_ZONE2 = (0.2500, 0.7000, 0.7500)             # 禁区2: 底部HUD与状态栏 (left_x, top_y, right_x)
RATIO_ZONE3 = (0.8000, 0.7000, 1.0000)             # 禁区3: 右下角小地图 (left_x, top_y, right_x)

def draw_transparent_rect(img, top_left, bottom_right, color=(0, 0, 255), alpha=0.5):
    """画一个半透明矩形盖在原图上"""
    overlay = img.copy()
    cv2.rectangle(overlay, top_left, bottom_right, color, -1)
    cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)
    return img

def main():
    hwnd = win32gui.FindWindow(None, WINDOW_NAME)
    if not hwnd:
        print("❌ 找不到游戏窗口，请确保已经进入游戏。")
        return

    client_pt = win32gui.ClientToScreen(hwnd, (0, 0))
    rect = win32gui.GetClientRect(hwnd)
    base_x, base_y = client_pt[0], client_pt[1]
    win_w, win_h = rect[2], rect[3]

    print(f"📏 抓取到窗口分辨率: {win_w}x{win_h}")

    monitor = {"top": base_y, "left": base_x, "width": win_w, "height": win_h}

    with mss.mss() as sct:
        sct_img = sct.grab(monitor)
        img = np.array(sct_img)  # 转为 BGRA 数组

        # 渲染 禁区 1
        z1_tl = (int(win_w * RATIO_ZONE1[0]), int(win_h * RATIO_ZONE1[1]))
        z1_br = (win_w, int(win_h * RATIO_ZONE1[2]))
        img = draw_transparent_rect(img, z1_tl, z1_br, color=(0, 0, 255)) # 红色

        # 渲染 禁区 2
        z2_tl = (int(win_w * RATIO_ZONE2[0]), int(win_h * RATIO_ZONE2[1]))
        z2_br = (int(win_w * RATIO_ZONE2[2]), win_h)
        img = draw_transparent_rect(img, z2_tl, z2_br, color=(0, 255, 0)) # 绿色

        # 渲染 禁区 3
        z3_tl = (int(win_w * RATIO_ZONE3[0]), int(win_h * RATIO_ZONE3[1]))
        z3_br = (int(win_w * RATIO_ZONE3[2]), win_h)
        img = draw_transparent_rect(img, z3_tl, z3_br, color=(255, 0, 0)) # 蓝色

        # 存图
        os.makedirs("debug", exist_ok=True)
        out_path = os.path.join("debug", "zone_test.png")
        cv2.imwrite(out_path, img)
        print(f"✅ 测试截图成功！已保存至: {out_path}")
        print("💡 提示：血条区为红色，状态栏为绿色，小地图为蓝色。如果不准，微调代码里的 RATIO 重试即可。")

if __name__ == "__main__":
    main()