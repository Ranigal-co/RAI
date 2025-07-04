import telebot
import os
import time
import threading
import re
from dotenv import load_dotenv
from model import Model
from collections import defaultdict
from collections import deque
from summarizer import HistorySummarizer

class RequestState:
    def __init__(self, chat_id, status_msg):
        self.full_response = ""
        self.last_msg = status_msg
        self.last_update = time.time()
        self.start_time = time.time()
        self.is_first_chunk = True
        self.final_update_done = False
        self.update_count = 0
        self.chat_id = chat_id
        self.cancelled = False
        self.request_id = None

class RAI:
    def __init__(self):
        load_dotenv()
        bot_token = os.getenv('BOT_TOKEN')
        if not bot_token:
            raise ValueError("BOT_TOKEN not found in environment variables")
            
        self.bot = telebot.TeleBot(bot_token)
        self.model = Model()
        self.active_requests = defaultdict(dict)
        self.chat_histories = defaultdict(deque)
        self.MAX_HISTORY_LENGTH = 10

        self.summarizer = HistorySummarizer()
        self.COMPRESSION_THRESHOLD = 5
        self.MAX_TOKENS_BEFORE_COMPRESS = 1500

        self._register_handlers()
        
        # Запускаем фоновый поток для очистки старых запросов
        self.cleanup_thread = threading.Thread(target=self._cleanup_old_requests, daemon=True)
        self.cleanup_thread.start()

        self.NameBot = os.getenv("NameBot", "Рай")
    
    def _cleanup_old_requests(self):
        """Фоновый поток для очистки старых запросов"""
        while True:
            time.sleep(60)
            current_time = time.time()
            expired_requests = []
            
            for request_id, state in self.active_requests.items():
                if current_time - state.start_time > 500:
                    expired_requests.append(request_id)
            
            for request_id in expired_requests:
                del self.active_requests[request_id]
    
    def _register_handlers(self):
        @self.bot.message_handler(content_types=['text'])
        def handle_message(message):
            if '/stop' in message.text:
                self.handle_stop(message)
            elif '/clear' in message.text:
                chat_id = message.chat.id
                if chat_id in self.chat_histories:
                    self.chat_histories[chat_id] = deque()
                    self.bot.send_message(chat_id, "Моя память очищена!")
                else:
                    self.bot.send_message(chat_id, "Нечего забывать -_-")
            elif '/fullhistory' in message.text:
                self.show_full_history(message)
            else:
                self.process_message(message)
    
    def handle_stop(self, message):
        """Обработчик команды /stop"""
        chat_id = message.chat.id
        user_requests = [req_id for req_id in self.active_requests 
                         if req_id.startswith(f"{chat_id}_")]
        
        if not user_requests:
            return
        
        # Отменяем все активные запросы пользователя
        for request_id in user_requests:
            state = self.active_requests[request_id]
            state.cancelled = True
            del self.active_requests[request_id]
        
        self.bot.send_message(message.chat.id, "Молчу :3")
    
    def compress_history(self, chat_id):
        """Сжимает историю диалога и заменяет ее сжатой версией"""
        history = list(self.chat_histories[chat_id])
        history_text = "\n".join([f"User: {u}\nBot: {b}" for u,b in history])
        
        try:
            summary = self.summarizer.summarize(history_text)
            # Заменяем историю на сжатую версию
            self.chat_histories[chat_id] = deque([("История диалога", summary)])
            return summary
        except Exception as e:
            print(f"Ошибка сжатия истории: {e}")
            return None
    
    def show_full_history(self, message):
        """Показывает пользователю полную историю диалога"""
        chat_id = message.chat.id
        if chat_id not in self.chat_histories or not self.chat_histories[chat_id]:
            self.bot.send_message(chat_id, "История диалога пуста")
            return
        
        history_text = "Полная история:\n\n"
        for i, (user, bot) in enumerate(self.chat_histories[chat_id], 1):
            history_text += f"{i}. Вы: {user}\n   Бот: {bot}\n\n"
        
        self.bot.send_message(chat_id, history_text[:4000])  # Обрезаем если слишком длинное
    
    def process_message(self, message):
        try:
            # Проверяем количество активных запросов для пользователя
            user_requests = [req_id for req_id in self.active_requests 
                             if req_id.startswith(f"{message.chat.id}_")]
            
            if len(user_requests) >= 3:
                self.bot.send_message(
                    message.chat.id,
                    "Хозяин слишком много работы -_-"
                )
                return
            
            # Создаем уникальный идентификатор запроса
            request_id = f"{message.chat.id}_{message.message_id}"
            
            # Отправляем статусное сообщение
            status_msg = self.bot.send_message(
                message.chat.id, 
                "..."
            )
            
            # Создаем изолированное состояние для этого запроса
            state = RequestState(message.chat.id, status_msg)
            state.request_id = request_id
            self.active_requests[request_id] = state
            
            def chunk_handler(chunk):
                # Проверяем, не отменен ли запрос
                if request_id not in self.active_requests or state.cancelled:
                    return
                    
                # Фильтрация think-блоков
                if '<think>' in chunk or '</think>' in chunk or not chunk.strip():
                    return
                
                state.full_response += chunk
                
                # Обновляем сообщение не чаще чем раз в 1.5 секунды
                current_time = time.time()
                update_interval = 1.5
                
                if (current_time - state.last_update > update_interval or 
                    state.is_first_chunk) and state.full_response.strip():
                    
                    state.update_count += 1
                    
                    # Создаем "снимок" текущего состояния для безопасной отправки
                    response_snapshot = state.full_response
                    
                    try:
                        if state.is_first_chunk:
                            state.last_msg = self.bot.edit_message_text(
                                chat_id=state.chat_id,
                                message_id=state.last_msg.message_id,
                                text=response_snapshot
                            )
                            state.is_first_chunk = False
                        else:
                            state.last_msg = self.bot.edit_message_text(
                                chat_id=state.chat_id,
                                message_id=state.last_msg.message_id,
                                text=response_snapshot
                            )
                        state.last_update = current_time
                    except telebot.apihelper.ApiTelegramException as e:
                        if "retry after" in str(e):
                            retry_after = int(str(e).split('retry after ')[-1])
                            time.sleep(retry_after + 1)
                            try:
                                state.last_msg = self.bot.edit_message_text(
                                    chat_id=state.chat_id,
                                    message_id=state.last_msg.message_id,
                                    text=response_snapshot
                                )
                            except Exception:
                                pass
                        else:
                            if response_snapshot.strip():
                                state.last_msg = self.bot.send_message(
                                    state.chat_id, 
                                    response_snapshot
                                )
                    except Exception as e:
                        if response_snapshot.strip():
                            state.last_msg = self.bot.send_message(
                                state.chat_id, 
                                response_snapshot
                            )
            if len(self.chat_histories[message.chat.id]) >= self.COMPRESSION_THRESHOLD:
                self.compress_history(message.chat.id)
            
            # Вызываем модель
            self.model.modelMessage(
                userMessage=message.text.replace(self.NameBot, ""),
                history=list(self.chat_histories[message.chat.id]),
                callback=chunk_handler
            )
            
            # Финальная обработка
            if not state.cancelled and not state.is_first_chunk and state.full_response.strip():
                self._send_long_message(state)
                # Сохраняем в историю
                self.chat_histories[message.chat.id].append((message.text.replace(self.NameBot, ""), state.full_response))
                # Ограничиваем размер истории
                if len(self.chat_histories[message.chat.id]) > self.MAX_HISTORY_LENGTH:
                    self.chat_histories[message.chat.id].popleft()
                
            # Удаляем состояние запроса после завершения
            if request_id in self.active_requests:
                del self.active_requests[request_id]
                
        except Exception as e:
            self.bot.send_message(message.chat.id, f"⚠️ Error: {str(e)}")
            print(f"Error: {e}")
    
    def _send_long_message(self, state):
        """Отправляет длинное сообщение, разбивая его на части"""
        MAX_LENGTH = 3000
        
        if len(state.full_response) <= MAX_LENGTH:
            try:
                self.bot.edit_message_text(
                    chat_id=state.chat_id,
                    message_id=state.last_msg.message_id,
                    text=state.full_response
                )
            except Exception:
                self.bot.send_message(state.chat_id, state.full_response)
            return
        
        parts = []
        text = state.full_response
        while text:
            if len(text) > MAX_LENGTH:
                split_index = text.rfind('\n', 0, MAX_LENGTH)
                if split_index == -1:
                    split_index = text.rfind(' ', 0, MAX_LENGTH)
                if split_index == -1:
                    split_index = MAX_LENGTH
                
                part = text[:split_index].strip()
                if part:
                    parts.append(part)
                text = text[split_index:].strip()
            else:
                parts.append(text)
                text = ""
        
        for i, part in enumerate(parts):
            if i == 0:
                try:
                    self.bot.edit_message_text(
                        chat_id=state.chat_id,
                        message_id=state.last_msg.message_id,
                        text=part
                    )
                except Exception:
                    self.bot.send_message(state.chat_id, part)
            else:
                self.bot.send_message(state.chat_id, part)
                time.sleep(0.5)

if __name__ == "__main__":
    try:
        BOT = RAI()
        BOT.bot.polling(non_stop=True, interval=0)
    except Exception as e:
        print(f"Bot startup error: {e}")