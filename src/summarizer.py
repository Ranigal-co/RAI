import requests
import json
import os

class HistorySummarizer:
    def __init__(self):
        self.url = os.getenv('MODEL_API_URL', "http://localhost:1234/v1/chat/completions")
        self.headers = {"Content-Type": "application/json"}
    
    def summarize(self, history_text):
        """Сжимает историю диалога"""
        messages = [
            {
                "role": "system", 
                "content": "Ты - компрессор контекста. Кратко суммируй историю диалога, сохраняя ключевые факты и контекст. Будь максимально лаконичным и внимателен к деталям."
            },
            {
                "role": "user", 
                "content": f"Сожми эту историю диалога, сохраняя важные детали:\n\n{history_text} /no_think"
            }
        ]
        
        data = {
            "model": "qwen/qwen3-8b",
            "messages": messages,
            "temperature": 0.2,
            "max_tokens": 300
        }
        
        response = requests.post(self.url, headers=self.headers, json=data)
        return response.json()['choices'][0]['message']['content']