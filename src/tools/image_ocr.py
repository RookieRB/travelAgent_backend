# src/tools/image_ocr.py
import os
import base64
import httpx
from typing import List, Dict, Any, Optional
from langchain_core.messages import HumanMessage
from src.models.llm import LLMFactory


class ImageOCRTool:
    """
    图片OCR识别工具
    
    使用阿里云 qwen-omni-turbo-latest 模型进行图文识别
    """
    
    def __init__(
        self,
        max_images: int = 4,
        timeout: float = 30.0,
        debug: bool = False
    ):
        """
        初始化图片识别工具
        
        Args:
            max_images: 最多处理的图片数量
            timeout: 下载图片超时时间
            debug: 是否开启调试模式
        """
        self.max_images = int(os.getenv("XHS_OCR_MAX_IMAGES", max_images))
        self.timeout = timeout
        self.debug = debug or os.getenv("XHS_DEBUG", "").lower() == "true"
        self._vision_llm = None
    
    @property
    def vision_llm(self):
        """懒加载视觉模型"""
        if self._vision_llm is None:
            self._vision_llm = LLMFactory.get_vision_model()
        return self._vision_llm
    
    def _dprint(self, msg: str, payload: Any = None):
        """调试输出"""
        if not self.debug:
            return
        if payload:
            print(f"[OCR] {msg}: {str(payload)[:200]}")
        else:
            print(f"[OCR] {msg}")
    
    def extract_image_urls(self, image_list: List[Dict]) -> List[str]:
        """
        从 imageList 中提取图片URL
        
        优先使用 urlDefault，否则使用 urlPre
        """
        urls = []
        for img in image_list[:self.max_images]:
            if not isinstance(img, dict):
                continue
            url =  img.get("urlPre") or img.get("urlDefault") 
            if url:
                urls.append(url)
        return urls
    
    def recognize_single_image(self, image_url: str, prompt: str = None) -> str:
        """
        识别单张图片
        
        Args:
            image_url: 图片URL
            prompt: 自定义提示词
            
        Returns:
            识别出的文字内容
        """
        if not prompt:
            prompt = """请仔细识别这张旅游攻略图片中的所有文字内容。

要求：
1. 提取所有可见的文字，包括标题、正文、标注等
2. 保持原有的结构和层次
3. 如果有景点名称、地址、价格、时间等信息，请准确识别
4. 如果有路线图或行程安排，请描述清楚
5. 忽略装饰性文字和水印

直接输出识别到的内容，不需要额外说明。"""

        try:
            # 构建多模态消息
            message = HumanMessage(
                content=[
                    {
                        "type": "image_url",
                        "image_url": {"url": image_url}
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            )
            
            self._dprint(f"识别图片", image_url[:80])
            
            response = self.vision_llm.invoke([message])
            result = response.content.strip()
            
            self._dprint(f"识别结果长度", len(result))
            self._dprint(f"识别结果", result[:300])
            return result
            
        except Exception as e:
            self._dprint(f"识别失败", str(e))
            return ""
    
    def recognize_multiple_images(
        self,
        image_urls: List[str],
        merge: bool = True
    ) -> str | List[str]:
        """
        识别多张图片
        
        Args:
            image_urls: 图片URL列表
            merge: 是否合并结果
            
        Returns:
            合并后的文字 或 各图片识别结果列表
        """
        results = []
        
        for i, url in enumerate(image_urls[:self.max_images]):
            self._dprint(f"处理第 {i+1}/{len(image_urls)} 张图片")
            
            # 为不同位置的图片使用不同提示
            if i == 0:
                prompt = """这是一篇旅游攻略的封面/首图。请识别图片中的所有文字，包括：
- 标题
- 目的地名称
- 天数/行程概要
- 其他重要信息

直接输出识别到的文字内容。"""
            else:
                prompt = """请识别这张旅游攻略图片中的所有文字内容，包括：
- 景点名称和介绍
- 地址、交通、门票等信息
- 美食推荐
- 行程安排
- 实用tips

直接输出识别到的内容，保持原有结构。"""
            
            text = self.recognize_single_image(url, prompt)
            if text:
                results.append(f"【图片{i+1}内容】\n{text}")
        
        if merge:
            return "\n\n".join(results)
        return results
    
    def recognize_from_note_detail(self, note_detail: Dict) -> str:
        """
        从笔记详情中提取图片并识别
        
        Args:
            note_detail: get_feed_detail 返回的原始数据
            
        Returns:
            识别出的图片文字内容
        """
        # 提取 imageList
        data = note_detail.get("data", {})
        note = data.get("note", {}) or note_detail.get("note", {})
        image_list = note.get("imageList", [])
        
        if not image_list:
            self._dprint("未找到图片列表")
            return ""
        
        self._dprint(f"找到 {len(image_list)} 张图片")
        
        # 提取URL并识别
        urls = self.extract_image_urls(image_list)
        if not urls:
            return ""
        
        return self.recognize_multiple_images(urls, merge=True)


# ==================== 便捷函数 ====================

_ocr_tool: Optional[ImageOCRTool] = None

def get_ocr_tool() -> ImageOCRTool:
    """获取OCR工具单例"""
    global _ocr_tool
    if _ocr_tool is None:
        _ocr_tool = ImageOCRTool()
    return _ocr_tool


def recognize_note_images(note_detail: Dict) -> str:
    """便捷函数：识别笔记中的图片"""
    return get_ocr_tool().recognize_from_note_detail(note_detail)