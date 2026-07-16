import cv2
import numpy as np
import pytesseract
import os

# 配置 Tesseract
pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
# 读取刚才主脚本保存的原始截图
RAW_IMAGE_PATH = os.path.join('debug', 'raw_level.png')


def test_ocr():
    img = cv2.imread(RAW_IMAGE_PATH, cv2.IMREAD_GRAYSCALE)
    if img is None:
        print(f"❌ 找不到原始图片: {RAW_IMAGE_PATH}")
        return

    print("🖼️ 已加载原始像素图，开始炼丹...\n")

    # 共同步骤：放大 5 倍
    enlarged = cv2.resize(img, None, fx=5, fy=5, interpolation=cv2.INTER_CUBIC)

    # 构建圆环掩码 (将圆圈缩小到 25，避开 UI 光泽边缘)
    mask = np.zeros(enlarged.shape, dtype=np.uint8)
    cx, cy = enlarged.shape[1] // 2, enlarged.shape[0] // 2
    cv2.circle(mask, (cx, cy), 25, 255, -1)

    # ---------------------------------------------------------
    # 🧪 配方 1：固定阈值二值化 (最锐利，过滤灰边)
    # ---------------------------------------------------------
    _, thresh1 = cv2.threshold(enlarged, 140, 255, cv2.THRESH_BINARY_INV)
    final_1 = np.where(mask == 255, thresh1, 255)  # 圈外涂成纯白
    cv2.imwrite(os.path.join('debug', 'test_recipe_1.png'), final_1)

    # ---------------------------------------------------------
    # 🧪 配方 2：自适应阈值 (Otsu算法，AI自己找最佳阈值)
    # ---------------------------------------------------------
    _, thresh2 = cv2.threshold(enlarged, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    final_2 = np.where(mask == 255, thresh2, 255)
    cv2.imwrite(os.path.join('debug', 'test_recipe_2.png'), final_2)

    # ---------------------------------------------------------
    # 🧪 配方 3：暴力加粗 (腐蚀暗部)
    # ---------------------------------------------------------
    # 基于配方1，加一步腐蚀操作，让黑色的字变粗
    kernel = np.ones((2, 2), np.uint8)
    final_3 = cv2.erode(final_1, kernel, iterations=1)
    cv2.imwrite(os.path.join('debug', 'test_recipe_3.png'), final_3)

    # 测试 OCR 识别率
    config = r'--oem 3 --psm 8 -c tessedit_char_whitelist=0123456789'

    res1 = pytesseract.image_to_string(final_1, config=config).strip()
    res2 = pytesseract.image_to_string(final_2, config=config).strip()
    res3 = pytesseract.image_to_string(final_3, config=config).strip()

    print(f"🎯 配方 1 (固定阈值) 识别结果: '{res1}'")
    print(f"🎯 配方 2 (Otsu阈值) 识别结果: '{res2}'")
    print(f"🎯 配方 3 (暴力加粗) 识别结果: '{res3}'")

    print("\n💡 接下来请打开 debug 文件夹，对比 test_recipe_1.png、2.png、3.png。")
    print("哪张图肉眼看着最像打印出来的纯白底纯黑字，且识别出了 1，我们就用哪个代码合入主脚本！")


if __name__ == "__main__":
    test_ocr()