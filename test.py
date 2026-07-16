import os
import ctypes
import win32gui
import numpy as np
import cv2
import mss

# ==========================================
# 必须加上！强制开启 Windows DPI 感知，防止截图坐标偏移
# ==========================================
try:
    # noinspection PyUnresolvedReferences
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except (AttributeError, OSError):
    try:
        # noinspection PyUnresolvedReferences
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass

WINDOW_NAME = "League of Legends (TM) Client"

def test_restrict_areas():
    os.makedirs("debug", exist_ok=True)
    hwnd = win32gui.FindWindow(None, WINDOW_NAME)
    if not hwnd:
        print("❌ 未找到游戏窗口！请确保游戏正在运行。")
        return

    # 获取游戏窗口客户区相对屏幕的绝对物理坐标
    client_point = win32gui.ClientToScreen(hwnd, (0, 0))
    rect = win32gui.GetClientRect(hwnd)
    win_w = rect[2]
    win_h = rect[3]

    print(f"🎮 成功定位游戏窗口，尺寸: {win_w}x{win_h}，正在截取全图...")

    monitor = {
        "top": client_point[1],
        "left": client_point[0],
        "width": win_w,
        "height": win_h
    }

    with mss.MSS() as sct:
        # 截取完整游戏画面
        img = np.array(sct.grab(monitor))
        # 复制一层作为半透明叠加层
        overlay = img.copy()

        # ==========================================
        # 🚫 禁区 1：右侧队友血条区 (红色)
        # ==========================================
        r1_x1 = 800  # 左边界
        r1_y1 = 480  # 顶边界
        r1_x2 = win_w # 右边界拉满
        r1_y2 = 570  # 底边界

        cv2.rectangle(overlay, (r1_x1, r1_y1), (r1_x2, r1_y2), (0, 0, 255, 255), -1)

        # ==========================================
        # 🚫 禁区 2：底部 OCR 识图区 (红色)
        # ==========================================
        r2_x1 = 280  # 左边界
        r2_y1 = 660  # 顶边界
        r2_x2 = 740  # 右边界
        r2_y2 = win_h # 底边界拉满

        cv2.rectangle(overlay, (r2_x1, r2_y1), (r2_x2, r2_y2), (0, 0, 255, 255), -1)

        # ==========================================
        # 混合原图与红色色块 (透明度 0.4)
        # ==========================================
        alpha = 0.4
        result = cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0)

        # 画个绿色的十字架标记中心点
        center_x = win_w // 2
        center_y = win_h // 2
        cv2.line(result, (center_x - 20, center_y), (center_x + 20, center_y), (0, 255, 0, 255), 2)
        cv2.line(result, (center_x, center_y - 20), (center_x, center_y + 20), (0, 255, 0, 255), 2)

        save_path = os.path.join('debug', 'test_restricted_areas.png')
        cv2.imwrite(save_path, result)
        print(f"✅ 禁区图已生成！请打开 {save_path} 查看。")
        print("💡 确认红色区域完美覆盖了血条、W技能、等级和商店后，告诉我！")

if __name__ == "__main__":
    test_restrict_areas()