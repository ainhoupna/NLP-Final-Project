"""Pipeline RAG (Retrieval-Augmented Generation) de MisogynAI."""

from __future__ import annotations
import requests
import structlog

logger = structlog.get_logger()

SYSTEM_PROMPT: str = (
    "Eres MisogynAI, un analista experto especializado en detectar y explicar "
    "contenido misógino en redes sociales. Recibirás posts recuperados de Bluesky "
    "Social y debes analizarlos para responder a la pregunta del usuario. "
    "Basa tu respuesta SIEMPRE en los posts proporcionados y cita ejemplos específicos. "
    "Si la información no está en los posts, indícalo claramente. "
    "Responde siempre en español de forma profesional y objetiva."
)

def build_prompt(question: str, posts: list[dict]) -> list[dict]:
    """Construye la lista de mensajes para la API del LLM."""
    
    # Construir el contexto a partir de los posts
    context_blocks = []
    for i, post in enumerate(posts):
        block = f"--- POST {i+1} ---\n"
        block += f"Autor: {post['author_handle']}\n"
        block += f"Contenido: {post['text']}\n"
        context_blocks.append(block)
    
    context_text = "\n".join(context_blocks)
    
    user_content = (
        "Analiza los siguientes posts de Bluesky y responde a la pregunta.\n\n"
        f"CONTEXTO (POSTS RECUPERADOS):\n{context_text}\n\n"
        f"PREGUNTA DEL USUARIO: {question}\n\n"
        "RESPUESTA:"
    )
    
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content}
    ]

def call_llm(messages: list[dict], llm_url: str, max_tokens: int = 1000) -> str:
    """Llama al endpoint del LLM (Qwen server)."""
    try:
        # El servidor (SGLang/vLLM/llama.cpp) expone /v1/chat/completions (OpenAI compat)
        endpoint = f"{llm_url}/v1/chat/completions"
        payload = {
            "model": "Qwen3.5-35B-A3B-Uncensored-HauhauCS-Aggressive",
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.2, # Baja para mayor fidelidad a los datos
            "stream": False
        }
        
        logger.info("calling_llm", url=endpoint)
        response = requests.post(endpoint, json=payload, timeout=300)
        response.raise_for_status()
        
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error("llm_call_failed", error=str(e))
        return "Lo siento, hubo un error al consultar el modelo de lenguaje."

def run_rag(question: str, retriever, llm_url: str, top_k: int = 5) -> dict:
    """Pipeline completo RAG."""
    # 1. Recuperar posts
    posts = retriever.retrieve(question, top_k=top_k)
    
    if not posts:
        return {
            "question": question,
            "answer": "No se han encontrado posts relacionados en la base de datos de las últimas 24 horas.",
            "sources": []
        }
    
    # 2. Construir prompt
    messages = build_prompt(question, posts)
    
    # 3. Generar respuesta
    answer = call_llm(messages, llm_url)
    
    # 4. Return results with full post data
    return {
        "question": question,
        "answer": answer,
        "sources": posts
    }
