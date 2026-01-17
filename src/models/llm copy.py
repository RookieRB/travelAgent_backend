# src/models/llm.py
import os
from typing import Optional, Literal
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from langchain_core.language_models.chat_models import BaseChatModel


class LLMFactory:
    """
    LLM 工厂 - 支持多提供商 + 模型分层
    
    使用方式:
        # 获取轻量模型（摘要、格式化）
        llm = LLMFactory.get_light_model()
        
        # 获取智能模型（规划、创意）
        llm = LLMFactory.get_smart_model()
        
        # 获取默认模型（向后兼容）
        llm = LLMFactory.get_default()
    """
    
    _instances: dict = {}
    
    # ===================== 配置 =====================
    
    @classmethod
    def _get_provider(cls) -> str:
        """获取 LLM 提供商"""
        return os.getenv("LLM_PROVIDER", "openai").lower()
    
    @classmethod
    def _get_config(cls, model_type: Literal["light", "smart", "default"]) -> dict:
        """
        获取模型配置
        
        环境变量优先级：
        - LLM_LIGHT_MODEL: 轻量模型名称
        - LLM_SMART_MODEL: 智能模型名称
        - LLM_MODEL / OPENAI_MODEL / OLLAMA_MODEL: 默认模型
        """
        provider = cls._get_provider()
        
        # 模型名称配置
        model_configs = {
            "openai": {
                "light": os.getenv("LLM_LIGHT_MODEL", "qwen-turbo"),
                "smart": os.getenv("LLM_SMART_MODEL", "qwen-long-latest"),
                "default": os.getenv("LLM_MODEL", os.getenv("OPENAI_MODEL", "qwen-long-latest")),
            },
            "ollama": {
                "light": os.getenv("LLM_LIGHT_MODEL", "qwen2:7b"),
                "smart": os.getenv("LLM_SMART_MODEL", "qwen2:14b"),
                "default": os.getenv("LLM_MODEL", os.getenv("OLLAMA_MODEL", "qwen2:7b")),
            }
        }
        
        # 温度配置
        temperature_configs = {
            "light": 0.3,   # 轻量模型更确定性
            "smart": 0.7,   # 智能模型更有创意
            "default": 0.7,
        }
        
        return {
            "provider": provider,
            "model": model_configs.get(provider, model_configs["openai"])[model_type],
            "temperature": float(os.getenv("LLM_TEMPERATURE", temperature_configs[model_type])),
        }
    
    # ===================== 创建实例 =====================
    
    @classmethod
    def _create_openai(cls, model: str, temperature: float) -> ChatOpenAI:
        """创建 OpenAI 兼容的 LLM"""
        api_key = os.getenv("OPENAI_API_KEY","sk-34752fb47e9b4a6dac314b0feb64e13e")
        base_url = os.getenv("OPENAI_API_BASE","https://dashscope.aliyuncs.com/compatible-mode/v1")
        
        if not api_key:
            print("⚠️ Warning: OPENAI_API_KEY not found")
            api_key = "sk-dummy-key"
        
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=api_key,
            base_url=base_url,
            timeout=60.0,
            max_retries=3,
        )
    
    @classmethod
    def _create_ollama(cls, model: str, temperature: float) -> ChatOllama:
        """创建 Ollama 本地 LLM"""
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        
        return ChatOllama(
            model=model,
            temperature=temperature,
            base_url=base_url,
            num_ctx=4096,
            num_predict=2048,
            repeat_penalty=1.1,
            top_k=40,
            top_p=0.9,
            timeout=120,
        )
    
    @classmethod
    def _create_instance(cls, model_type: Literal["light", "smart", "default"]) -> BaseChatModel:
        """创建 LLM 实例"""
        config = cls._get_config(model_type)
        provider = config["provider"]
        model = config["model"]
        temperature = config["temperature"]
        
        print(f"🤖 创建 {model_type} 模型: {provider}/{model} (temp={temperature})")
        
        if provider == "ollama":
            return cls._create_ollama(model, temperature)
        else:
            return cls._create_openai(model, temperature)
    
    # ===================== 公共接口 =====================
    
    @classmethod
    def get_light_model(cls) -> BaseChatModel:
        """
        获取轻量模型 - 用于简单任务
        
        适用场景:
        - 信息提取
        - 格式转换
        - 简单摘要
        - JSON 解析
        
        特点: 速度快、成本低、确定性高
        """
        if "light" not in cls._instances:
            cls._instances["light"] = cls._create_instance("light")
        return cls._instances["light"]
    
    @classmethod
    def get_smart_model(cls) -> BaseChatModel:
        """
        获取智能模型 - 用于复杂任务
        
        适用场景:
        - 行程规划
        - 创意写作
        - 复杂推理
        - 个性化建议
        
        特点: 质量高、更有创意
        """
        if "smart" not in cls._instances:
            cls._instances["smart"] = cls._create_instance("smart")
        return cls._instances["smart"]
    
    @classmethod
    def get_default(cls) -> BaseChatModel:
        """获取默认模型（向后兼容）"""
        if "default" not in cls._instances:
            cls._instances["default"] = cls._create_instance("default")
        return cls._instances["default"]
    
    @classmethod
    def get(cls, model_type: str = "default") -> BaseChatModel:
        """
        通用获取方法
        
        Args:
            model_type: "light" | "smart" | "default"
        """
        if model_type == "light":
            return cls.get_light_model()
        elif model_type == "smart":
            return cls.get_smart_model()
        else:
            return cls.get_default()
    
    @classmethod
    def clear_cache(cls):
        """清除缓存的实例（用于测试或重新加载配置）"""
        cls._instances.clear()
        print("🔄 LLM 实例缓存已清除")


# ===================== 向后兼容 =====================

# 保持原有的 Myllm 变量，使用默认模型
# Myllm = LLMFactory.get_default()

# 便捷别名
def get_llm(model_type: str = "default") -> BaseChatModel:
    """便捷函数：获取 LLM 实例"""
    return LLMFactory.get(model_type)


# ===================== 旧接口兼容（可选删除）=====================

def create_llm(
    provider: str = None,
    model: str = None,
    temperature: float = 0.7,
    base_url: str = None
) -> BaseChatModel:
    """
    [已废弃] 创建 LLM 实例 - 保留用于向后兼容
    
    推荐使用: LLMFactory.get_light_model() 或 LLMFactory.get_smart_model()
    """
    print("⚠️ create_llm() 已废弃，请使用 LLMFactory")
    
    provider = provider or os.getenv("LLM_PROVIDER", "openai")
    
    if provider.lower() == "ollama":
        model = model or os.getenv("OLLAMA_MODEL", "qwen2:7b")
        base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        return ChatOllama(
            model=model,
            temperature=temperature,
            base_url=base_url,
            num_ctx=4096,
            timeout=120,
        )
    else:
        model = model or os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        api_key = os.getenv("OPENAI_API_KEY", "sk-dummy-key")
        base_url = base_url or os.getenv("OPENAI_API_BASE")
        return ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=api_key,
            base_url=base_url,
            timeout=60.0,
        )