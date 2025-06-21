import requests
import json
import os

class Model:
    def __init__(self):
        self.url = os.getenv('MODEL_API_URL', "http://localhost:1234/v1/chat/completions")
        self.headers = {"Content-Type": "application/json"}
        self.system_prompt = os.getenv('SYSTEM_PROMPT', 'Тебя зовут Рай, ты кошкодевочка, будь вежливой и приятной в общении')

    def modelMessage(self, userMessage: str, history=None, callback=None):
        if history is None:
            history = []
        
        messages = [
            {"role": "system", "content": self.system_prompt}
        ]
        
        # Добавляем историю диалога
        for msg in history:
            if msg[0] == "История диалога":
                messages.append({
                    "role": "system",
                    "content": f"Контекст предыдущего диалога (сжатая версия): {msg[1]}"
                })
            else:
                messages.append({"role": "user", "content": msg[0]})
                messages.append({"role": "assistant", "content": msg[1]})
        
        # Добавляем текущее сообщение (убираем /no_think)
        messages.append({"role": "user", "content": f"{userMessage} /no_think"})
        
        data = {
            "model": "qwen/qwen3-8b",
            "messages": messages,
            "stream": True,
            "temperature": 0.5
        }

        try:
            with requests.post(self.url, headers=self.headers, json=data, stream=True) as response:
                if response.status_code != 200:
                    raise Exception(f"API Error: {response.status_code} - {response.text}")
                
                for line in response.iter_lines():
                    if line:
                        decoded_line = line.decode('utf-8').strip()
                        if decoded_line.startswith('data:') and decoded_line != 'data: [DONE]':
                            try:
                                json_data = json.loads(decoded_line[5:])
                                if 'choices' in json_data and json_data['choices']:
                                    delta = json_data['choices'][0].get('delta', {})
                                    if 'content' in delta:
                                        # Упрощенная фильтрация без сложных регулярных выражений
                                        content = delta['content']
                                        if callback:
                                            callback(content)
                            except json.JSONDecodeError as e:
                                print(f"JSON decode error: {e}")
        except requests.exceptions.RequestException as e:
            raise Exception(f"Connection error: {e}")