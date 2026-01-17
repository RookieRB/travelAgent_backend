# 测试图片识别
from src.tools.image_ocr import ImageOCRTool, get_ocr_tool

# 单独测试OCR
ocr = ImageOCRTool(debug=True)
result = ocr.recognize_single_image(
    "http://sns-webpic-qc.xhscdn.com/202601171250/0f944906e8decc23deb35c8b7c5d25b2/notes_pre_post/1040g3k831qlvmkjqn21g4939oss7gkhrrecd6e8!nd_dft_wlteh_webp_3"
)
print(result)

# 测试搜索（包含OCR）
from src.tools.xiaohongshu import XiaohongshuSearchTool

tool = XiaohongshuSearchTool()
result = tool._run("西安3天旅游攻略")
print(result)