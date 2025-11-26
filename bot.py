import logging
import telebot
from telebot import types
import openai
from typing import Optional

from config import config
from database import db_manager, DatabaseError


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

bot = telebot.TeleBot(config.bot_token)
openai.api_key = config.openai_api_key


class OpenAIError(Exception):
    pass


class OpenAIService:
    
    @staticmethod
    def generate_response(prompt: str, max_tokens: int = 1000) -> str:
        try:
            response = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system", 
                        "content": "Ты полезный AI-ассистент. Отвечай понятно и подробно."
                    },
                    {"role": "user", "content": prompt}
                ],
                max_tokens=max_tokens,
                temperature=0.7,
                timeout=config.bot.request_timeout
            )
            
            if not response.choices:
                raise OpenAIError("Empty response from OpenAI")
            
            return response.choices[0].message.content.strip()
            
        except openai.error.AuthenticationError as e:
            logger.error(f"OpenAI authentication failed: {e}")
            raise OpenAIError("Invalid API key configuration")
            
        except openai.error.RateLimitError as e:
            logger.error(f"OpenAI rate limit exceeded: {e}")
            raise OpenAIError("Service temporarily unavailable due to high load")
            
        except openai.error.OpenAIError as e:
            logger.error(f"OpenAI API error: {e}")
            raise OpenAIError("AI service is currently unavailable")
            
        except Exception as e:
            logger.error(f"Unexpected error in OpenAI call: {e}")
            raise OpenAIError("Internal service error")


class MessageHandler:
    
    def __init__(self, bot_instance: telebot.TeleBot):
        self.bot = bot_instance
        self.openai_service = OpenAIService()
    
    def handle_start_command(self, message: types.Message) -> None:
        try:
            user = db_manager.get_or_create_user(
                tg_id=message.from_user.id,
                username=message.from_user.username,
                first_name=message.from_user.first_name,
                last_name=message.from_user.last_name
            )
            
            welcome_text = self._build_welcome_message(
                user['balance'],
                message.from_user.first_name
            )
            
            self.bot.send_message(message.chat.id, welcome_text)
            logger.info(f"New user started: {message.from_user.id}")
            
        except DatabaseError as e:
            logger.error(f"Database error in start command: {e}")
            self.bot.send_message(
                message.chat.id,
                "❌ Произошла ошибка при регистрации. Попробуйте позже."
            )
    
    def handle_text_message(self, message: types.Message) -> None:
        user_id = message.from_user.id
        user_text = message.text.strip()
        
        if not user_text:
            self.bot.send_message(message.chat.id, "❌ Сообщение не может быть пустым.")
            return
        
        try:
            user = db_manager.get_or_create_user(user_id)
            if user['balance'] <= 0:
                self._send_balance_warning(message.chat.id, user['balance'])
                return
            
            processing_msg = self.bot.send_message(
                message.chat.id, 
                "⏳ Обрабатываю запрос..."
            )
            
            response = self.openai_service.generate_response(user_text)
            
            if db_manager.ensure_sufficient_balance(user_id):
                final_text = self._build_response_text(response, user['balance'] - 1)
                self.bot.edit_message_text(
                    final_text,
                    chat_id=message.chat.id,
                    message_id=processing_msg.message_id
                )
                logger.info(f"Successfully processed request for user {user_id}")
            else:
                raise DatabaseError("Failed to deduct balance")
                
        except OpenAIError as e:
            self.bot.edit_message_text(
                f"❌ {str(e)}",
                chat_id=message.chat.id,
                message_id=processing_msg.message_id
            )
            logger.warning(f"OpenAI error for user {user_id}: {e}")
            
        except DatabaseError as e:
            self.bot.edit_message_text(
                "❌ Ошибка обработки запроса. Попробуйте позже.",
                chat_id=message.chat.id,
                message_id=processing_msg.message_id
            )
            logger.error(f"Database error for user {user_id}: {e}")
    
    def _build_welcome_message(self, balance: int, first_name: str) -> str:
        return f"""🤖 Добро пожаловать, {first_name}!

Я - AI-ассистент на базе OpenAI. Вы можете задавать мне любые вопросы!

💫 Ваш баланс: {balance} запросов

Доступные команды:
/balance - Проверить баланс
/buy - Купить запросы  
/promo - Активировать промокод
/help - Помощь

Для начала просто напишите ваш вопрос!"""
    
    def _build_response_text(self, response: str, remaining_balance: int) -> str:
        """Build final response text with balance info."""
        return f"{response}\n\n💫 Осталось запросов: {remaining_balance}"
    
    def _send_balance_warning(self, chat_id: int, balance: int) -> None:
        """Send balance warning message."""
        warning_text = f"""❌ Недостаточно запросов. Баланс: {balance}

💡 Пополните баланс: /buy
🎁 Или используйте промокод: /promo"""
        
        self.bot.send_message(chat_id, warning_text)


message_handler = MessageHandler(bot)


@bot.message_handler(commands=['start'])
def handle_start(message: types.Message):
    message_handler.handle_start_command(message)


@bot.message_handler(content_types=['text'])
def handle_text(message: types.Message):
    message_handler.handle_text_message(message)


def main():
    logger.info("Starting Telegram bot...")
    
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=30)
    except Exception as e:
        logger.critical(f"Bot crashed: {e}")
        raise
    finally:
        logger.info("Bot stopped")


if __name__ == "__main__":
    main()
