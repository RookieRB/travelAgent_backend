# src/models/llm.py
import os
from typing import Optional
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI

def create_llm(
    provider: str = None,
    model: str = None,
    temperature: float = 0.7,
    base_url: str = None
):
    """
    创建 LLM 实例
    
    Args:
        provider: 提供商 (ollama/openai)，默认从环境变量读取
        model: 模型名称
        temperature: 温度参数
        base_url: API 地址
        
    Returns:
        LLM 实例
    """
    provider = provider or os.getenv("LLM_PROVIDER", "openai")
    print(f"📌 创建 LLM 实例，提供商: {provider}")
    if provider.lower() == "ollama":
        return create_ollama_llm(model, temperature, base_url)
    elif provider.lower() == "openai":
        return create_openai_llm(model, temperature, base_url)
    else:
        raise ValueError(f"Unsupported LLM provider: {provider}")


def create_ollama_llm(
    model: str = None,
    temperature: float = 0.7,
    base_url: str = None
) -> ChatOllama:
    """
    创建 Ollama LLM 实例
    
    Args:
        model: 模型名称，如 llama3, qwen2, mistral 等
        temperature: 温度参数
        base_url: Ollama 服务地址
    """
    model = model or os.getenv("OLLAMA_MODEL", "qwen2:7b")
    base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    
    print(f"🦙 使用 Ollama 本地模型: {model}")
    print(f"   地址: {base_url}")
    
    return ChatOllama(
        model=model,
        temperature=temperature,
        base_url=base_url,
        # Ollama 特有参数
        num_ctx=4096,           # 上下文长度
        num_predict=2048,       # 最大生成 token 数
        repeat_penalty=1.1,     # 重复惩罚
        top_k=40,
        top_p=0.9,
        # 超时设置
        timeout=120,            # Ollama 本地推理可能较慢
    )


def create_openai_llm(
    model: str = None,
    temperature: float = 0.7,
    base_url: str = None
) -> ChatOpenAI:
    """创建 OpenAI LLM 实例"""
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("⚠️ Warning: OPENAI_API_KEY not found")
        api_key = "sk-dummy-key"
    
    model = model or os.getenv("OPENAI_MODEL", "gpt-4")
    base_url = base_url or os.getenv("OPENAI_API_BASE")
    
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=api_key,
        base_url=base_url,
        timeout=60.0,
        max_retries=3
    )


# ===================== 全局 LLM 实例 =====================

Myllm = create_llm()