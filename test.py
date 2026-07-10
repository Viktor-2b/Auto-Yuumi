import ctypes
import win32gui
import win32con
import time
import pydirectinput

lobby_hwnd = win32gui.FindWindow(None, "League of Legends")
if lobby_hwnd:
    screen_w = ctypes.windll.user32.GetSystemMetrics(0)
    rect = win32gui.GetWindowRect(lobby_hwnd)
    win_w = rect[2] - rect[0]
    win_h = rect[3] - rect[1]
    new_x = screen_w - win_w
    new_y = 0
    win32gui.SetWindowPos(lobby_hwnd, win32con.HWND_TOP, new_x, new_y, win_w, win_h,
                                              win32con.SWP_SHOWWINDOW)

    print(f"🪟 已将游戏大厅移动至右上角: ({new_x}, {new_y})")
    # 2. 移动鼠标到大厅底部正中间并双击，触发 LeagueAkari 所需的重新匹配

    # Y轴偏移减去 40 像素，确保点在“再来一局”等底部按钮区域上
    target_x = new_x + win_w // 2 -100
    target_y = win_h - 40
    time.sleep(1.0)  # 窗口移动后稍微等一下
    pydirectinput.moveTo(target_x, target_y)
    time.sleep(0.5)
    pydirectinput.click()
    time.sleep(0.5)
    pydirectinput.click()
    time.sleep(0.5)
    pydirectinput.click()