import cv2
import pytesseract

# ==========================================
# 1. 配置 Tesseract 路径 (跟主脚本保持一致)
# ==========================================
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'

# 填写你需要测试的图片相对路径
# 如果你的图片叫 ocr_level.png 并且在 debug 文件夹里，就这样写：
TEST_IMAGE_PATH = r'debug\ocr_level.png'


def run_test():
    img = cv2.imread(TEST_IMAGE_PATH, cv2.IMREAD_GRAYSCALE)
    if img is None:
        print(f"❌ 找不到图片: {TEST_IMAGE_PATH}，请检查路径！")
        return

    print(f"🖼️ 成功读取图片，开始测试 Tesseract 识别能力...\n")

    # 测试 1：你的原版配置 (带严格白名单)
    config_1 = r'--oem 3 --psm 8 -c tessedit_char_whitelist=0123456789'
    res_1 = pytesseract.image_to_string(img, config=config_1).strip()
    print(f"🧪 [测试 1] 原版带白名单输出     : '{res_1}'")

    # 测试 2：取消白名单，看看它到底认成了什么鬼东西
    config_2 = r'--oem 3 --psm 8'
    res_2 = pytesseract.image_to_string(img, config=config_2).strip()
    print(f"🧪 [测试 2] 取消白名单裸奔输出   : '{res_2}'")

    # 测试 3：单字符模式 (psm 10)
    config_3 = r'--oem 3 --psm 10'
    res_3 = pytesseract.image_to_string(img, config=config_3).strip()
    print(f"🧪 [测试 3] 单字符模式裸奔输出   : '{res_3}'")

    # 模拟我们在主脚本里的暴力纠错逻辑
    print("\n🛠️ --- 开始模拟 Python 暴力纠错 ---")
    raw_text = res_2 if res_2 else res_3  # 取不带白名单的结果

    if raw_text:
        # 常见易混淆字母替换
        corrected = raw_text.replace('I', '1').replace('l', '1').replace('i', '1').replace('|', '1')
        corrected = corrected.replace('O', '0').replace('o', '0').replace('S', '5').replace('s', '5')
        # 过滤非数字字符
        final_text = ''.join(filter(str.isdigit, corrected))
        print(f"✅ 最终提取出的有效数字       : '{final_text}'")
    else:
        print("❌ 完蛋，Tesseract 什么字符都没吐出来！可能是图片太粗糙/噪点太多。")
        print("💡 建议：去主代码里把 cv2.threshold 的 165 提高到 185 试试，让字变细一点。")


if __name__ == "__main__":
    run_test()


# level_img = np.array(sct.grab(level_region))
# gray_lvl = cv2.cvtColor(level_img, cv2.COLOR_BGRA2GRAY)
# enlarged_lvl = cv2.resize(gray_lvl, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)
#
# # 圆环掩码：创建一个纯黑背景，中间画一个白圆，只保留圆形区域内的图像，抹除四个角的边框残影
# mask = np.zeros(enlarged_lvl.shape, dtype=np.uint8)
# center_x, center_y = enlarged_lvl.shape[1] // 2, enlarged_lvl.shape[0] // 2
# # 半径，原图13*5=65，中心点32
# cv2.circle(mask, (center_x, center_y), 35, 255, -1)
# enlarged_lvl = cv2.bitwise_and(enlarged_lvl, enlarged_lvl, mask=mask)
#
# # y在二值化前加入 3x3 的高斯模糊，彻底消除放大带来的锯齿，让数字边缘如德芙般顺滑
# enlarged_lvl = cv2.GaussianBlur(enlarged_lvl, (3, 3), 0)
#
# # 阈值越高，画面中被判定为黑字的像素就越少，数字自然就变细了，完美保留字体圆弧形状且剥离粘连！
# _, thresh_lvl = cv2.threshold(enlarged_lvl, 165, 255, cv2.THRESH_BINARY_INV)
#
# # 继续添加白色边框 Padding。这正是解决 11 级贴边被当成噪点过滤的核心办法
# thresh_lvl = cv2.copyMakeBorder(thresh_lvl, 10, 10, 10, 10, cv2.BORDER_CONSTANT,
#                                 value=[255, 255, 255])
# # 将最终送给 OCR 识别的图像保存到本地，方便排查错认问题
# cv2.imwrite(os.path.join('debug', 'ocr_level.png'), thresh_lvl)
