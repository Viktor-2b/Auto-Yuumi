import ctypes
import win32gui
import win32con
import time
import cv2
import numpy as np
from mss import mss

# ==========================================
# 核心修复：强制开启 Windows DPI 感知，解决 2.5K 屏幕缩放导致的截图错位
# ==========================================
try:
    # 尝试调用 Windows 8.1+ 的 Per-Monitor DPI 感知
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        # 退回 Windows Vista/7 的全局 DPI 感知
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

WINDOW_NAME = "League of Legends (TM) Client"


def test_capture_full_window():
    print("🔍 正在寻找游戏窗口...")
    hwnd = win32gui.FindWindow(None, WINDOW_NAME)

    if not hwnd:
        print(f"❌ 未找到游戏窗口: '{WINDOW_NAME}'")
        print("请确认你现在已经进入了召唤师峡谷/训练营，而不是在大厅。")
        return

    # 尝试把游戏窗口呼唤到最前台
    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
        print("🪟 已将游戏窗口置于前台，等待 1 秒缓冲...")
        time.sleep(1)
    except Exception as e:
        print(f"⚠️ 窗口置于前台失败: {e}")

    # 获取窗口在屏幕上的确切位置和大小 (由于开启了DPI感知，这里获取的将是真实的物理像素)
    rect = win32gui.GetWindowRect(hwnd)
    left, top, right, bottom = rect

    # 获取客户区大小（排除掉 Windows 系统的不可见边框阴影）
    client_rect = win32gui.GetClientRect(hwnd)
    client_point = win32gui.ClientToScreen(hwnd, (0, 0))

    # 重新计算更精确的截图区域
    real_left = client_point[0]
    real_top = client_point[1]
    real_width = client_rect[2] - client_rect[0]
    real_height = client_rect[3] - client_rect[1]

    print(f"📍 锁定游戏精准坐标: 左上角 X={real_left}, Y={real_top} | 尺寸 {real_width}x{real_height}")

    # 配置 mss 的抓取区域
    region = {
        'top': real_top,
        'left': real_left,
        'width': real_width,
        'height': real_height
    }

    print("📸 咔嚓！正在截取画面...")
    with mss() as sct:
        try:
            # 抓取图像
            img_bgra = np.array(sct.grab(region))

            # 保存图像
            filename = 'debug_full_window_fixed.png'
            cv2.imwrite(filename, img_bgra)

            print("\n" + "=" * 45)
            print(f"✅ 截图成功！图片已保存为: 【 {filename} 】")
            print("=" * 45)
            print("🧐 请打开图片确认。这次应该完美贴合游戏画面了。")

        except Exception as e:
            print(f"❌ 截图过程发生异常: {e}")


if __name__ == "__main__":
    print("=" * 45)
    print("🛠️ 英雄联盟全窗口截图验证工具 (高分辨率修复版)")
    print("=" * 45)
    test_capture_full_window()