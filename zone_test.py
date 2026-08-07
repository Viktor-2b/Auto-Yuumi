import os
import cv2
import mss
import win32gui
import numpy as np
from PIL import Image, ImageDraw, ImageFont

WINDOW_NAME = "League of Legends (TM) Client"


def save_image_safe(file_path: str, img_bgr: np.ndarray):
    """安全的图片保存函数，防止中文路径报错"""
    success, encoded_image = cv2.imencode('.png', img_bgr)
    if success:
        encoded_image.tofile(file_path)


def draw_transparent_rect_with_text(
        img: np.ndarray,
        top_left: tuple[int, int],
        bottom_right: tuple[int, int],
        text: str,
        color_bgr: tuple[int, int, int] = (0, 0, 255),
        alpha: float = 0.4
) -> np.ndarray:
    """画一个半透明矩形盖在原图上，并在下方用红色中文字体标注"""
    overlay = img.copy()
    cv2.rectangle(overlay, top_left, bottom_right, color_bgr, -1)
    cv2.addWeighted(overlay, alpha, img, 1 - alpha, 0, img)
    cv2.rectangle(img, top_left, bottom_right, color_bgr, 1)

    img_rgb: np.ndarray = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    img_pil = Image.fromarray(img_rgb)
    draw = ImageDraw.Draw(img_pil)

    try:
        font = ImageFont.truetype("msyh.ttc", 16)  # 微软雅黑
    except IOError:
        try:
            font = ImageFont.truetype("simhei.ttf", 16)  # 黑体
        except IOError:
            font = ImageFont.load_default()

    text_color_rgb = (255, 0, 0)

    text_x = top_left[0]
    text_y = bottom_right[1] + 5
    if text_y + 20 > img_pil.size[1]:
        text_y = top_left[1] - 22

    draw.text((text_x, text_y), text, font=font, fill=text_color_rgb)

    return cv2.cvtColor(np.asarray(img_pil), cv2.COLOR_RGB2BGR)


def main():
    hwnd = win32gui.FindWindow(None, WINDOW_NAME)
    if not hwnd:
        print("❌ 找不到游戏窗口，请确保已经进入对局。")
        return

    print("=== 🚀 比例系数动态测试工具 (XYWH 规范) ===")
    print("💡 提示：支持持续输入，输入 'q' 或 'exit' 退出测试。\n")

    client_pt = win32gui.ClientToScreen(hwnd, (0, 0))
    rect = win32gui.GetClientRect(hwnd)
    base_x, base_y = client_pt[0], client_pt[1]
    win_w, win_h = rect[2], rect[3]

    print(f"📏 抓取到窗口分辨率: {win_w}x{win_h}")

    monitor = {"top": base_y, "left": base_x, "width": win_w, "height": win_h}
    os.makedirs("debug", exist_ok=True)

    with mss.MSS() as sct:
        while True:
            raw_ratio = input(f"▶ 请粘贴比例: ").strip()

            if raw_ratio.lower() in ['q', 'exit']:
                print("👋 已退出测试工具。")
                break

            # 智能清理用户输入可能带有的括号，方便直接从代码里复制粘贴
            raw_ratio = raw_ratio.replace('(', '').replace(')', '').replace('[', '').replace(']', '')

            try:
                ratios = [float(x.strip()) for x in raw_ratio.split(',')]
                if len(ratios) != 4:
                    raise ValueError("参数数量不是 4 个")
                r_left, r_top, r_width, r_height = ratios
            except Exception as e:
                print(f"❌ 输入格式错误！请确保输入了 4 个由逗号分隔的小数。({e})\n")
                continue

            # 每次重新抓取屏幕，支持边玩边测
            sct_img = sct.grab(monitor)
            img: np.ndarray = cv2.cvtColor(np.asarray(sct_img), cv2.COLOR_BGRA2BGR)

            # 按统一规范 (left, top, width, height) 计算像素坐标
            top_left_x = int(win_w * r_left)
            top_left_y = int(win_h * r_top)

            # 智能判定：如果宽和高都是 0，说明是点击中心点，画一个 16x16 的小框示意即可
            if r_width == 0.0 and r_height == 0.0:
                tl = (top_left_x - 8, top_left_y - 8)
                br = (top_left_x + 8, top_left_y + 8)
                display_text = f"(中心点)"
            else:
                tl = (top_left_x, top_left_y)
                br = (top_left_x + int(win_w * r_width), top_left_y + int(win_h * r_height))
                display_text = "测试区域"

            # 绘制并覆盖
            img = draw_transparent_rect_with_text(img, tl, br, display_text)

            # 保存为单张截图 (每次覆盖同一张图，可以在图片浏览器中保持打开实时查看)
            out_path = os.path.join("debug", "zone_test_manual.png")
            save_image_safe(out_path, img)

            print(f"✅ 测试完成！已在屏幕上框出该位置，图片保存至: {out_path}\n")


if __name__ == "__main__":
    main()

