import ctypes
import win32gui
import win32con
import time
import cv2
import numpy as np
from mss import mss
import pytesseract

# ==========================================
# 【重要配置】请修改为你电脑上 Tesseract 的实际安装路径！
# ==========================================
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# 强制开启 Windows DPI 感知
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

WINDOW_NAME = "League of Legends (TM) Client"


def setup_game_window():
    """将游戏窗口移动到屏幕右上角并返回真实客户区原点"""
    hwnd = win32gui.FindWindow(None, WINDOW_NAME)
    if not hwnd:
        print(f"❌ 未找到游戏窗口: '{WINDOW_NAME}'")
        return None, None

    screen_w = ctypes.windll.user32.GetSystemMetrics(0)
    rect = win32gui.GetWindowRect(hwnd)
    win_w = rect[2] - rect[0]
    win_h = rect[3] - rect[1]

    new_x = screen_w - win_w
    new_y = 0

    win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, new_x, new_y, win_w, win_h, win32con.SWP_SHOWWINDOW)
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(hwnd)

    # 获取客户区物理起点
    client_point = win32gui.ClientToScreen(hwnd, (0, 0))
    print(f"🪟 游戏窗口已锁定至右上角。客户区真实原点: {client_point}")
    return hwnd, client_point


def interactive_debug_loop(client_point):
    """交互式循环，允许用户不断输入坐标进行测试"""
    base_x, base_y = client_point
    sct = mss()

    print("\n" + "=" * 50)
    print("🛠️ 交互式 OCR & 血条亮度 调试器已启动！")
    print("规则：默认你输入的是【中心点坐标】。")
    print("输入格式：中心X 中心Y 宽度 高度 二值化阈值(可选,默认150)")
    print("-" * 50)
    print("【测试推荐参数】")
    print("👉 测试英雄等级：310 744 13 13")
    print("👉 测试 W技能图标：432 708 36 36")
    print("👉 测试队友1血条：840 527 10 6 (高度很小时，会自动进入血条模式)")
    print("👉 测试队友2血条：894 527 10 6")
    print("=" * 50 + "\n")

    while True:
        user_input = input("\n👉 请输入参数 (或输入 q 退出): ").strip()
        if user_input.lower() == 'q':
            print("⏹️ 调试结束。")
            break

        parts = user_input.split()
        if len(parts) < 4:
            print("⚠️ 格式错误！请输入至少4个数字，用空格隔开。")
            continue

        try:
            center_x = int(parts[0])
            center_y = int(parts[1])
            box_w = int(parts[2])
            box_h = int(parts[3])
            threshold_val = int(parts[4]) if len(parts) >= 5 else 150

            left = center_x - (box_w // 2)
            top = center_y - (box_h // 2)

            abs_x = base_x + left
            abs_y = base_y + top

            region = {'top': abs_y, 'left': abs_x, 'width': box_w, 'height': box_h}
            print(f"📍 正在截取: {region} (二值化阈值: {threshold_val})")

            # 1. 截图并保存原图 (去目录看 debug_01_raw.png 确认是否框准了血条)
            img_bgra = np.array(sct.grab(region))
            cv2.imwrite('debug_01_raw.png', img_bgra)

            # 2. 转灰度图，计算亮度
            gray = cv2.cvtColor(img_bgra, cv2.COLOR_BGRA2GRAY)
            mean_brightness = np.mean(gray)

            print("-" * 30)
            print(f"🌟 当前区域平均亮度: 【 {mean_brightness:.2f} 】")

            # 如果高度很小（比如小于等于15），我们判定为正在测血条
            if box_h <= 15:
                print("🩸 [血条模式] 识别到你可能在测血条！")
                if mean_brightness < 60.0:
                    print("   => 结果分析：亮度极低，如果是血条，目前为【残血/黑色】状态！")
                else:
                    print("   => 结果分析：亮度正常，如果是血条，目前为【健康/绿色】状态！")
                print("-" * 30)
                print("跳过 OCR 识别。请打开 'debug_01_raw.png' 确认是否完美框住了血条的中心区域。")
                continue  # 血条模式下跳过后面的 OCR 逻辑

            print("-" * 30)

            # 3. 放大 (5倍) 并二值化 (针对等级和技能)
            enlarged = cv2.resize(gray, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
            _, thresh = cv2.threshold(enlarged, threshold_val, 255, cv2.THRESH_BINARY_INV)
            cv2.imwrite('debug_02_thresh.png', thresh)

            # 4. OCR 识别
            custom_config = r'--oem 3 --psm 8 -c tessedit_char_whitelist=1234567890'
            text = pytesseract.image_to_string(thresh, config=custom_config).strip()

            if text:
                print(f"✅ OCR 识别成功: 【 {text} 】")
            else:
                print("❌ OCR 识别为空 (如果是测试技能图标亮度，请忽略此项)。")

        except ValueError:
            print("⚠️ 错误：请输入纯数字！")
        except Exception as e:
            print(f"❌ 发生异常: {e}")


if __name__ == "__main__":
    hwnd, client_pt = setup_game_window()
    if hwnd and client_pt:
        interactive_debug_loop(client_pt)