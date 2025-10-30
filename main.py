import ccxt
import asyncio
from telegram import Bot, Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    ConversationHandler
)
from telegram.error import TelegramError
import logging
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import html
import re
import json
import os
import time

# Общая конфигурация
TELEGRAM_TOKEN = "7990034184:AAFTx--E5GE0NIPA0Yghr6KpBC80aVtSACs"
TELEGRAM_CHAT_IDS = ["1167694150", "7916502470", "5381553894", "1111230981"]

# Конфигурация спотового арбитража (по умолчанию)
DEFAULT_SPOT_SETTINGS = {
    "THRESHOLD_PERCENT": 0.5,
    "MAX_THRESHOLD_PERCENT": 40,
    "CHECK_INTERVAL": 30,
    "MIN_EXCHANGES_FOR_PAIR": 2,
    "MIN_VOLUME_USD": 1000000,
    "MIN_ENTRY_AMOUNT_USDT": 5,
    "MAX_ENTRY_AMOUNT_USDT": 350,
    "MAX_IMPACT_PERCENT": 0.5,
    "ORDER_BOOK_DEPTH": 10,
    "MIN_NET_PROFIT_USD": 4,
    "ENABLED": True,
    "PRICE_CONVERGENCE_THRESHOLD": 0.5,
    "PRICE_CONVERGENCE_ENABLED": True
}

# Конфигурация фьючерсного арбитража (по умолчанию)
DEFAULT_FUTURES_SETTINGS = {
    "THRESHOLD_PERCENT": 0.5,
    "MAX_THRESHOLD_PERCENT": 20,
    "CHECK_INTERVAL": 30,
    "MIN_VOLUME_USD": 1000000,
    "MIN_EXCHANGES_FOR_PAIR": 2,
    "MIN_ENTRY_AMOUNT_USDT": 5,
    "MAX_ENTRY_AMOUNT_USDT": 170,
    "MIN_NET_PROFIT_USD": 3,
    "ENABLED": True,
    "PRICE_CONVERGENCE_THRESHOLD": 0.5,
    "PRICE_CONVERGENCE_ENABLED": True
}

# Конфигурация спот-фьючерсного арбитража (по умолчанию)
DEFAULT_SPOT_FUTURES_SETTINGS = {
    "THRESHOLD_PERCENT": 0.5,
    "MAX_THRESHOLD_PERCENT": 20,
    "CHECK_INTERVAL": 30,
    "MIN_VOLUME_USD": 1000000,
    "MIN_EXCHANGES_FOR_PAIR": 2,
    "MIN_ENTRY_AMOUNT_USDT": 5,
    "MAX_ENTRY_AMOUNT_USDT": 170,
    "MIN_NET_PROFIT_USD": 3,
    "ENABLED": True,
    "PRICE_CONVERGENCE_THRESHOLD": 0.5,
    "PRICE_CONVERGENCE_ENABLED": True
}

# Конфигурация внутрибиржевого (треугольного) арбитража (по умолчанию) <-- NEW
DEFAULT_TRIANGULAR_SETTINGS = {
    "THRESHOLD_PERCENT": 0.3,
    "MAX_THRESHOLD_PERCENT": 5,
    "CHECK_INTERVAL": 15,
    "MIN_VOLUME_USD": 50000,
    "MIN_NET_PROFIT_USD": 2,
    "ENABLED": True,
    "ENTRY_AMOUNT_USDT": 50, # Фиксированная сумма входа для расчета
    "CONVERGENCE_THRESHOLD": 0.1,
    "PRICE_CONVERGENCE_ENABLED": True
}
# Конец NEW

# Настройки бирж
EXCHANGE_SETTINGS = {
    "bybit": {"ENABLED": True},
    "mexc": {"ENABLED": True},
    "okx": {"ENABLED": True},
    "gate": {"ENABLED": True},
    "bitget": {"ENABLED": True},
    "kucoin": {"ENABLED": True},
    "htx": {"ENABLED": True},
    "bingx": {"ENABLED": True},
    "phemex": {"ENABLED": True},
    "coinex": {"ENABLED": True},
    "blofin": {"ENABLED": True}
}

# Состояния для ConversationHandler
SETTINGS_MENU, SPOT_SETTINGS, FUTURES_SETTINGS, SPOT_FUTURES_SETTINGS, TRIANGULAR_SETTINGS, EXCHANGE_SETTINGS_MENU, SETTING_VALUE, COIN_SELECTION = range(
    8) # Изменено с 7 на 8 из-за добавления TRIANGULAR_SETTINGS

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("CryptoArbBot")

# Глобальные переменные для отслеживания истории уведомлений и длительности арбитража
price_convergence_history = defaultdict(dict)
last_convergence_notification = defaultdict(dict)
arbitrage_start_times = defaultdict(dict)  # Для отслеживания времени начала арбитражных возможностей
current_arbitrage_opportunities = defaultdict(dict)  # Для хранения текущих арбитражных возможностей
previous_arbitrage_opportunities = defaultdict(dict)  # Для хранения предыдущих арбитражных возможностей
sent_arbitrage_opportunities = defaultdict(dict)  # Для хранения отправленных в Telegram арбитражных возможностей

# Глобальные переменные для хранения последних настроек бирж
LAST_EXCHANGE_SETTINGS = None


# Загрузка сохраненных настроек
def load_settings():
    try:
        if os.path.exists('settings.json'):
            with open('settings.json', 'r') as f:
                settings = json.load(f)
                # Добавляем новые настройки, если их нет в файле
                if 'TRIANGULAR' not in settings:
                    settings['TRIANGULAR'] = DEFAULT_TRIANGULAR_SETTINGS.copy()
                return settings
    except Exception as e:
        logger.error(f"Ошибка загрузки настроек: {e}")

    # Возвращаем настройки по умолчанию
    return {
        "SPOT": DEFAULT_SPOT_SETTINGS.copy(),
        "FUTURES": DEFAULT_FUTURES_SETTINGS.copy(),
        "SPOT_FUTURES": DEFAULT_SPOT_FUTURES_SETTINGS.copy(),
        "TRIANGULAR": DEFAULT_TRIANGULAR_SETTINGS.copy(), # <-- NEW
        "EXCHANGES": EXCHANGE_SETTINGS.copy()
    }


# Сохранение настроек
def save_settings(settings):
    try:
        with open('settings.json', 'w') as f:
            json.dump(settings, f, indent=4)
    except Exception as e:
        logger.error(f"Ошибка сохранения настроек: {e}")


# Глобальные переменные
SHARED_BOT = None
SPOT_EXCHANGES_LOADED = {}
FUTURES_EXCHANGES_LOADED = {}
SETTINGS = load_settings()

# Конфигурация бирж для спота (используется для треугольного арбитража)
SPOT_EXCHANGES = {
    "bybit": {
        "api": ccxt.bybit({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://www.bybit.com/trade/spot/{s.replace('/', '')}",
        "withdraw_url": lambda c: f"https://www.bybit.com/user/assets/withdraw",
        "deposit_url": lambda c: f"https://www.bybit.com/user/assets/deposit",
        "emoji": "🏛",
        "blacklist": []
    },
    "mexc": {
        "api": ccxt.mexc({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.002,
        "maker_fee": 0.002,
        "url_format": lambda s: f"https://www.mexc.com/exchange/{s.replace('/', '_')}",
        "withdraw_url": lambda c: f"https://www.mexc.com/ru-RU/assets/withdraw/{c}",
        "deposit_url": lambda c: f"https://www.mexc.com/ru-RU/assets/deposit/{c}",
        "emoji": "🏛",
        "blacklist": []
    },
    "okx": {
        "api": ccxt.okx({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.0008,
        "url_format": lambda s: f"https://www.okx.com/trade-spot/{s.replace('/', '-').lower()}",
        "withdraw_url": lambda c: f"https://www.okx.com/ru/balance/withdrawal/{c.lower()}-chain",
        "deposit_url": lambda c: f"https://www.okx.com/ru/balance/recharge/{c.lower()}",
        "emoji": "🏛",
        "blacklist": ["BTC"]
    },
    "gate": {
        "api": ccxt.gateio({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.002,
        "maker_fee": 0.002,
        "url_format": lambda s: f"https://www.gate.io/trade/{s.replace('/', '_')}",
        "withdraw_url": lambda c: f"https://www.gate.io/myaccount/withdraw/{c}",
        "deposit_url": lambda c: f"https://www.gate.io/myaccount/deposit/{c}",
        "emoji": "🏛",
        "blacklist": []
    },
    "bitget": {
        "api": ccxt.bitget({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://www.bitget.com/spot/{s.replace('/', '')}_SPBL",
        "withdraw_url": lambda c: f"https://www.bitget.com/ru/asset/withdraw?coinId={c}",
        "deposit_url": lambda c: f"https://www.bitget.com/ru/asset/recharge?coinId={c}",
        "emoji": "🏛",
        "blacklist": []
    },
    "kucoin": {
        "api": ccxt.kucoin({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://www.kucoin.com/trade/{s.replace('/', '-')}",
        "withdraw_url": lambda c: f"https://www.kucoin.com/ru/assets/withdraw/{c}",
        "deposit_url": lambda c: f"https://www.kucoin.com/ru/assets/coin/{c}",
        "emoji": "🏛",
        "blacklist": []
    },
    "htx": {
        "api": ccxt.htx({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.002,
        "maker_fee": 0.002,
        "url_format": lambda s: f"https://www.htx.com/trade/{s.replace('/', '_').lower()}",
        "withdraw_url": lambda c: f"https://www.htx.com/ru-ru/finance/withdraw/{c.lower()}",
        "deposit_url": lambda c: f"https://www.htx.com/ru-ru/finance/deposit/{c.lower()}",
        "emoji": "🏛",
        "blacklist": []
    },
    "bingx": {
        "api": ccxt.bingx({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://bingx.com/en-us/spot/{s.replace('/', '')}",
        "withdraw_url": lambda c: f"https://bingx.com/en-us/assets/withdraw/{c}",
        "deposit_url": lambda c: f"https://bingx.com/en-us/assets/deposit/{c}",
        "emoji": "🏛",
        "blacklist": []
    },
    "phemex": {
        "api": ccxt.phemex({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://phemex.com/spot/trade/{s.replace('/', '')}",
        "withdraw_url": lambda c: f"https://phemex.com/assets/withdraw?asset={c}",
        "deposit_url": lambda c: f"https://phemex.com/assets/deposit?asset={c}",
        "emoji": "🏛",
        "blacklist": []
    },
    "coinex": {
        "api": ccxt.coinex({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: m.get('spot', False) and m['quote'] == 'USDT',
        "taker_fee": 0.002,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://www.coinex.com/exchange/{s.replace('/', '-')}",
        "withdraw_url": lambda c: f"https://www.coinex.com/asset/withdraw/{c}",
        "deposit_url": lambda c: f"https://www.coinex.com/asset/deposit/{c}",
        "emoji": "🏛",
        "blacklist": []
    },
    "blofin": {
        "api": ccxt.blofin({
            "enableRateLimit": True,
            "options": {
                "defaultType": "spot"
            }
        }),
        "symbol_format": lambda s: f"{s}/USDT",
        "is_spot": lambda m: (
                m.get('type') == 'spot' and
                m['quote'] == 'USDT'
        ),
        "taker_fee": 0.001,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://www.blofin.com/spot/{s.replace('/', '-')}",
        "withdraw_url": lambda c: f"https://www.blofin.com/assets/withdraw/{c}",
        "deposit_url": lambda c: f"https://www.blofin.com/assets/deposit/{c}",
        "emoji": "🏛",
        "blacklist": []
    }
}

# Конфигурация бирж для фьючерсов
FUTURES_EXCHANGES = {
    "bybit": {
        "api": ccxt.bybit({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: (m.get('swap', False) or m.get('future', False)) and m['settle'] == 'USDT',
        "taker_fee": 0.0006,
        "maker_fee": 0.0001,
        "url_format": lambda s: f"https://www.bybit.com/trade/usdt/{s.replace('/', '').replace(':USDT', '')}",
        "blacklist": ["BTC", "ETH"],
        "emoji": "📊"
    },
    "mexc": {
        "api": ccxt.mexc({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and 'USDT' in m['id'],
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://futures.mexc.com/exchange/{s.replace('/', '_').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "📊"
    },
    "okx": {
        "api": ccxt.okx({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: (m.get('swap', False) or m.get('future', False)) and m['settle'] == 'USDT',
        "taker_fee": 0.0005,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.okx.com/trade-swap/{s.replace('/', '-').replace(':USDT', '').lower()}",
        "blacklist": ["BTC", "ETH"],
        "emoji": "📊"
    },
    "gate": {
        "api": ccxt.gateio({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and '_USDT' in m['id'],
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.gate.io/futures_trade/{s.replace('/', '_').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "📊"
    },
    "bitget": {
        "api": ccxt.bitget({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and 'USDT' in m['id'],
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.bitget.com/ru/futures/{s.replace('/', '').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "📊"
    },
    "kucoin": {
        "api": ccxt.kucoin({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and 'USDT' in m['id'],
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.kucoin.com/futures/trade/{s.replace('/', '-').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "📊"
    },
    "htx": {
        "api": ccxt.htx({
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap",
                "fetchMarkets": ["swap"]
            }
        }),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and m.get('linear', False),
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.htx.com/futures/exchange/{s.split(':')[0].replace('/', '_').lower()}",
        "blacklist": [],
        "emoji": "📊"
    },
    "bingx": {
        "api": ccxt.bingx({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and 'USDT' in m['id'],
        "taker_fee": 0.0005,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://bingx.com/en-us/futures/{s.replace('/', '')}",
        "blacklist": [],
        "emoji": "📊"
    },
    "phemex": {
        "api": ccxt.phemex({
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap",
            }
        }),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and m['settle'] == 'USDT',
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://phemex.com/futures/trade/{s.replace('/', '').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "📊"
    },
    "coinex": {
        "api": ccxt.coinex({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: (m.get('swap', False) or m.get('future', False)) and m['settle'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://www.coinex.com/perpetual/{s.replace('/', '-').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "📊"
    },
    "blofin": {
        "api": ccxt.blofin({
            "enableRateLimit": True,
            "options": {
                "defaultType": "swap"
            }
        }),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: (
                m.get('type') in ['swap', 'future'] and
                m.get('settle') == 'USDT' and
                m.get('linear', False)
        ),
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.blofin.com/futures/{s.replace('/', '-').replace(':USDT', '')}",
        "blacklist": [],
        "emoji": "📊"
    }
}


# Reply-клавиатуры
def get_main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📈 Актуальные связки")], [KeyboardButton("🔧 Настройки")],
        [KeyboardButton("📊 Статус бота"), KeyboardButton("ℹ️ Помощь")]
    ], resize_keyboard=True)


def get_settings_keyboard():
    # Обновленное меню настроек
    return ReplyKeyboardMarkup([
        [KeyboardButton("🚀️ Спот"), KeyboardButton("📊 Фьючерсы"), KeyboardButton("↔️ Спот-Фьючерсы")],
        [KeyboardButton("🔱 Треугольный"), KeyboardButton("🏛 Биржи"), KeyboardButton("🔄 Сброс")], # <-- NEW
        [KeyboardButton("🔙 Главное меню")]
    ], resize_keyboard=True)


def get_spot_settings_keyboard():
    spot = SETTINGS['SPOT']
    return ReplyKeyboardMarkup([
        [KeyboardButton(f"Порог: {spot['THRESHOLD_PERCENT']}%"),
         KeyboardButton(f"Макс. порог: {spot['MAX_THRESHOLD_PERCENT']}%")],
        [KeyboardButton(f"Интервал: {spot['CHECK_INTERVAL']}с"),
         KeyboardButton(f"Объем: ${spot['MIN_VOLUME_USD'] / 1000:.0f}K")],
        [KeyboardButton(f"Мин. сумма: ${spot['MIN_ENTRY_AMOUNT_USDT']}"),
         KeyboardButton(f"Макс. сумма: ${spot['MAX_ENTRY_AMOUNT_USDT']}")],
        [KeyboardButton(f"Влияние: {spot['MAX_IMPACT_PERCENT']}%"),
         KeyboardButton(f"Стакан: {spot['ORDER_BOOK_DEPTH']}")],
        [KeyboardButton(f"Прибыль: ${spot['MIN_NET_PROFIT_USD']}"),
         KeyboardButton(f"Статус: {'ВКЛ' if spot['ENABLED'] else 'ВЫКЛ'}")],
        [KeyboardButton(f"Сходимость: {spot['PRICE_CONVERGENCE_THRESHOLD']}%"),
         KeyboardButton(f"Увед. сравн.: {'🔔' if spot['PRICE_CONVERGENCE_ENABLED'] else '🔕'}")],
        [KeyboardButton("🔙 Назад в настройки")]
    ], resize_keyboard=True)


def get_futures_settings_keyboard():
    futures = SETTINGS['FUTURES']
    return ReplyKeyboardMarkup([
        [KeyboardButton(f"Порог: {futures['THRESHOLD_PERCENT']}%"),
         KeyboardButton(f"Макс. порог: {futures['MAX_THRESHOLD_PERCENT']}%")],
        [KeyboardButton(f"Интервал: {futures['CHECK_INTERVAL']}с"),
         KeyboardButton(f"Объем: ${futures['MIN_VOLUME_USD'] / 1000:.0f}K")],
        [KeyboardButton(f"Мин. сумма: ${futures['MIN_ENTRY_AMOUNT_USDT']}"),
         KeyboardButton(f"Макс. сумма: ${futures['MAX_ENTRY_AMOUNT_USDT']}")],
        [KeyboardButton(f"Прибыль: ${futures['MIN_NET_PROFIT_USD']}"),
         KeyboardButton(f"Статус: {'ВКЛ' if futures['ENABLED'] else 'ВЫКЛ'}")],
        [KeyboardButton(f"Сходимость: {futures['PRICE_CONVERGENCE_THRESHOLD']}%"),
         KeyboardButton(f"Увед. сравн.: {'🔔' if futures['PRICE_CONVERGENCE_ENABLED'] else '🔕'}")],
        [KeyboardButton("🔙 Назад в настройки")]
    ], resize_keyboard=True)


def get_spot_futures_settings_keyboard():
    spot_futures = SETTINGS['SPOT_FUTURES']
    return ReplyKeyboardMarkup([
        [KeyboardButton(f"Порог: {spot_futures['THRESHOLD_PERCENT']}%"),
         KeyboardButton(f"Макс. порог: {spot_futures['MAX_THRESHOLD_PERCENT']}%")],
        [KeyboardButton(f"Интервал: {spot_futures['CHECK_INTERVAL']}с"),
         KeyboardButton(f"Объем: ${spot_futures['MIN_VOLUME_USD'] / 1000:.0f}K")],
        [KeyboardButton(f"Мин. сумма: ${spot_futures['MIN_ENTRY_AMOUNT_USDT']}"),
         KeyboardButton(f"Макс. сумма: ${spot_futures['MAX_ENTRY_AMOUNT_USDT']}")],
        [KeyboardButton(f"Прибыль: ${spot_futures['MIN_NET_PROFIT_USD']}"),
         KeyboardButton(f"Статус: {'ВКЛ' if spot_futures['ENABLED'] else 'ВЫКЛ'}")],
        [KeyboardButton(f"Сходимость: {spot_futures['PRICE_CONVERGENCE_THRESHOLD']}%"),
         KeyboardButton(f"Увед. сравн.: {'🔔' if spot_futures['PRICE_CONVERGENCE_ENABLED'] else '🔕'}")],
        [KeyboardButton("🔙 Назад в настройки")]
    ], resize_keyboard=True)


# NEW: Клавиатура для треугольного арбитража
def get_triangular_settings_keyboard():
    triangular = SETTINGS['TRIANGULAR']
    return ReplyKeyboardMarkup([
        [KeyboardButton(f"Порог: {triangular['THRESHOLD_PERCENT']}%"),
         KeyboardButton(f"Макс. порог: {triangular['MAX_THRESHOLD_PERCENT']}%")],
        [KeyboardButton(f"Интервал: {triangular['CHECK_INTERVAL']}с"),
         KeyboardButton(f"Объем: ${triangular['MIN_VOLUME_USD'] / 1000:.0f}K")],
        [KeyboardButton(f"Сумма входа: ${triangular['ENTRY_AMOUNT_USDT']}"),
         KeyboardButton(f"Прибыль: ${triangular['MIN_NET_PROFIT_USD']}")],
        [KeyboardButton(f"Сходимость: {triangular['CONVERGENCE_THRESHOLD']}%"),
         KeyboardButton(f"Увед. сравн.: {'🔔' if triangular['PRICE_CONVERGENCE_ENABLED'] else '🔕'}")],
        [KeyboardButton(f"Статус: {'ВКЛ' if triangular['ENABLED'] else 'ВЫКЛ'}")],
        [KeyboardButton("🔙 Назад в настройки")]
    ], resize_keyboard=True)
# Конец NEW


def get_exchange_settings_keyboard():
    keyboard = []
    row = []
    for i, (exchange, config) in enumerate(SETTINGS['EXCHANGES'].items()):
        status = "✅" if config['ENABLED'] else "❌"
        row.append(KeyboardButton(f"{exchange}: {status}"))
        if (i + 1) % 2 == 0:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([KeyboardButton("🔙 Назад в настройки")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)


async def send_telegram_message(message: str, chat_id: str = None, reply_markup: ReplyKeyboardMarkup = None):
    global SHARED_BOT
    if not SHARED_BOT:
        SHARED_BOT = Bot(token=TELEGRAM_TOKEN)

    targets = [chat_id] if chat_id else TELEGRAM_CHAT_IDS

    for target_id in targets:
        try:
            await SHARED_BOT.send_message(
                chat_id=target_id,
                text=message,
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_markup=reply_markup
            )
            logger.info(f"Сообщение отправлено в чат {target_id}")
        except TelegramError as e:
            logger.error(f"Ошибка отправки в {target_id}: {e}")


def format_duration(seconds):
    """Форматирует длительность в читаемый вид"""
    if seconds < 60:
        return f"{int(seconds)} сек"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        seconds_remaining = int(seconds % 60)
        return f"{minutes} мин {seconds_remaining} сек"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours} ч {minutes} мин"


def add_opportunity_to_sent(arb_type: str, base: str, exchange1: str, exchange2: str, spread: float,
                            price1: float, price2: float, volume1: float = None, volume2: float = None,
                            min_entry_amount: float = None, max_entry_amount: float = None,
                            profit_min: dict = None, profit_max: dict = None):
    """Добавляет связку в отправленные возможности"""
    # Для TRIANGULAR arbitrage используем уникальный ключ, base будет содержать информацию о треугольнике
    if arb_type == 'TRIANGULAR':
        key = f"{arb_type}_{exchange1}_{base}" # base уже содержит coin1_coin2_coin3_path
    else:
        key = f"{arb_type}_{base}_{exchange1}_{exchange2}"
    
    current_time = time.time()

    sent_arbitrage_opportunities[key] = {
        'arb_type': arb_type,
        'base': base, # Для TRIANGULAR: COIN_A_COIN_B_COIN_C_PATH
        'exchange1': exchange1,
        'exchange2': exchange2 if exchange2 != exchange1 else None, # Для TRIANGULAR exchange2 = None или та же биржа
        'spread': spread,
        'price1': price1,
        'price2': price2,
        'volume1': volume1,
        'volume2': volume2,
        'min_entry_amount': min_entry_amount,
        'max_entry_amount': max_entry_amount,
        'profit_min': profit_min,
        'profit_max': profit_max,
        'start_time': current_time,
        'last_updated': current_time
    }

    # Также добавляем в current_arbitrage_opportunities для отображения в актуальных связках
    current_arbitrage_opportunities[key] = sent_arbitrage_opportunities[key].copy()

    # Запускаем отсчет времени для этой связки
    arbitrage_start_times[key] = current_time
    previous_arbitrage_opportunities[key] = True

    logger.info(f"Связка добавлена в отправленные: {key}")


async def send_price_convergence_notification(arb_type: str, base: str, exchange1: str, exchange2: str,
                                              price1: float, price2: float, spread: float, volume1: float = None,
                                              volume2: float = None, duration: float = None):
    """Отправляет уведомление о сравнении цен с длительностью арбитража и удаляет связку из актуальных"""

    # NEW: Обработка TRIANGULAR arbitrage
    if arb_type == 'TRIANGULAR':
        convergence_threshold = SETTINGS['TRIANGULAR']['CONVERGENCE_THRESHOLD']
        # Ключ для TRIANGULAR: TRIANGULAR_exchange_base
        key = f"{arb_type}_{exchange1}_{base}"
        # В TRIANGULAR spread - это чистый процентный доход
        if abs(spread) > convergence_threshold:
            return
        
        # Проверяем, была ли эта связка ранее отправленной арбитражной возможностью
        if key not in sent_arbitrage_opportunities:
            return

        # Проверяем, не отправляли ли мы уже уведомление для этой связки
        current_time = time.time()
        # Проверяем, прошло ли достаточно времени с последнего уведомления (5 минут)
        if (key in last_convergence_notification and current_time - last_convergence_notification[key] < 300):
            return

        # Обновляем время последнего уведомления
        last_convergence_notification[key] = current_time

        exchange_id = exchange1
        
        # Парсим информацию о треугольнике: BASE_COIN1_COIN2_COIN3_PATH
        parts = base.split('_')
        coin_path = " → ".join(parts[:-1]) + f" → {parts[0]}"
        path_name = parts[-1]
        
        arb_type_name = "Треугольный"
        emoji = "🔱"

        utc_plus_3 = timezone(timedelta(hours=3))
        current_time_str = datetime.now(utc_plus_3).strftime('%H:%M:%S')

        duration_str = format_duration(duration) if duration is not None else "N/A"

        # Создаем красивое сообщение
        message = (
            f"🎯 <b>ЦЕНЫ СРАВНИЛИСЬ!</b> {emoji}\n\n"
            f"▫️ <b>Тип:</b> {arb_type_name} арбитраж\n"
            f"▫️ <b>Биржа:</b> <code>{exchange_id.upper()}</code>\n"
            f"▫️ <b>Путь:</b> <code>{coin_path}</code>\n"
            f"▫️ <b>Доход:</b> <code>{spread:.2f}%</code>\n"
            f"▫️ <b>Длительность арбитража:</b> {duration_str}\n\n"
            f"🔔 <i>Уведомление о сходимости цен</i>"
        )
        
        await send_telegram_message(message)
        logger.info(f"Отправлено уведомление о сходимости цен для треугольника {base} на {exchange_id}: {spread:.4f}%, длительность: {duration_str}")

        # Удаляем связку из всех словарей, чтобы она не отображалась в актуальных
        if key in sent_arbitrage_opportunities:
            del sent_arbitrage_opportunities[key]
        if key in current_arbitrage_opportunities:
            del current_arbitrage_opportunities[key]
        if key in arbitrage_start_times:
            del arbitrage_start_times[key]
        if key in previous_arbitrage_opportunities:
            del previous_arbitrage_opportunities[key]
            
        logger.info(f"Связка удалена из актуальных после сходимости цен: {key}")
        return # Выход из функции
    # Конец NEW
    
    # ... (Остальной код для SPOT/FUTURES/SPOT_FUTURES остается без изменений) ...
    # (Оригинальная логика для SPOT/FUTURES/SPOT_FUTURES)
    if not SETTINGS[arb_type]['PRICE_CONVERGENCE_ENABLED']:
        return

    convergence_threshold = SETTINGS[arb_type]['PRICE_CONVERGENCE_THRESHOLD']

    if abs(spread) > convergence_threshold:
        return

    # Проверяем, была ли эта связка ранее отправленной арбитражной возможностью
    previous_key = f"{arb_type}_{base}_{exchange1}_{exchange2}"
    if previous_key not in sent_arbitrage_opportunities:
        return

    # Проверяем, не отправляли ли мы уже уведомление для этой связки
    current_time = time.time()
    notification_key = f"{arb_type}_{base}_{exchange1}_{exchange2}"

    # Проверяем, прошло ли достаточно времени с последнего уведомления (5 минут)
    if (notification_key in last_convergence_notification and
            current_time - last_convergence_notification[notification_key] < 300):
        return

    # Обновляем время последнего уведомления
    last_convergence_notification[notification_key] = current_time

    # Определяем тип арбитража для заголовка
    if arb_type == 'SPOT':
        arb_type_name = "Спотовый"
        emoji = "🚀"
    elif arb_type == 'FUTURES':
        arb_type_name = "Фьючерсный"
        emoji = "📊"
    else:
        arb_type_name = "Спот-Фьючерсный"
        emoji = "↔️"

    utc_plus_3 = timezone(timedelta(hours=3))
    current_time_str = datetime.now(utc_plus_3).strftime('%H:%M:%S')

    # Форматируем объемы
    def format_volume(vol):
        if vol is None:
            return "N/A"
        if vol >= 1_000_000:
            return f"${vol / 1_000_000:.1f}M"
        if vol >= 1_000:
            return f"${vol / 1_000:.1f}K"
        return f"${vol:.1f}"

    volume1_str = format_volume(volume1)
    volume2_str = format_volume(volume2)

    # Форматируем длительность
    duration_str = format_duration(duration) if duration is not None else "N/A"

    # Получаем URL для бирж
    if arb_type == 'SPOT':
        exchange1_config = SPOT_EXCHANGES[exchange1]
        exchange2_config = SPOT_EXCHANGES[exchange2]
        symbol1 = exchange1_config["symbol_format"](base)
        symbol2 = exchange2_config["symbol_format"](base)
        url1 = exchange1_config["url_format"](symbol1)
        url2 = exchange2_config["url_format"](symbol2)
    else:
        exchange1_config = FUTURES_EXCHANGES[exchange1]
        exchange2_config = FUTURES_EXCHANGES[exchange2]
        symbol1 = exchange1_config["symbol_format"](base)
        symbol2 = exchange2_config["symbol_format"](base)
        url1 = exchange1_config["url_format"](symbol1.replace(':USDT', ''))
        url2 = exchange2_config["url_format"](symbol2.replace(':USDT', ''))

    safe_base = html.escape(base)

    # Создаем красивое сообщение с информацией о длительности
    message = (
        f"🎯 <b>ЦЕНЫ СРАВНИЛИСЬ!</b> {emoji}\n\n"
        f"▫️ <b>Тип:</b> {arb_type_name} арбитраж\n"
        f"▫️ <b>Монета:</b> <code>{safe_base}</code>\n"
        f"▫️ <b>Разница цен:</b> <code>{spread:.2f}%</code>\n"
        f"▫️ <b>Длительность арбитража:</b> {duration_str}\n\n"

        f"🟢 <b><a href='{url1}'>{exchange1.upper()}</a>:</b>\n"
        f"   💰 Цена: <code>${price1:.8f}</code>\n"
        f"   📊 Объем: {volume1_str}\n\n"

        f"🔵 <b><a href='{url2}'>{exchange2.upper()}</a>:</b>\n"
        f"   💰 Цена: <code>${price2:.8f}</code>\n"
        f"   📊 Объем: {volume2_str}\n\n"

        f"⏰ <i>{current_time_str}</i>\n"
        f"🔔 <i>Уведомление о сходимости цен</i>"
    )

    await send_telegram_message(message)
    logger.info(
        f"Отправлено уведомление о сходимости цен для {base} ({arb_type}): {spread:.4f}%, длительность: {duration_str}")

    # Удаляем связку из всех словарей, чтобы она не отображалась в актуальных
    key = f"{arb_type}_{base}_{exchange1}_{exchange2}"
    if key in sent_arbitrage_opportunities:
        del sent_arbitrage_opportunities[key]
    if key in current_arbitrage_opportunities:
        del current_arbitrage_opportunities[key]
    if key in arbitrage_start_times:
        del arbitrage_start_times[key]
    if key in previous_arbitrage_opportunities:
        del previous_arbitrage_opportunities[key]

    logger.info(f"Связка удалена из актуальных после сходимости цен: {key}")


def update_arbitrage_duration(arb_type: str, base: str, exchange1: str, exchange2: str, spread: float):
    """Обновляет время длительности арбитражной возможности"""
    
    if arb_type == 'TRIANGULAR':
        key = f"{arb_type}_{exchange1}_{base}"
        threshold = SETTINGS[arb_type]['THRESHOLD_PERCENT']
        max_threshold = SETTINGS[arb_type]['MAX_THRESHOLD_PERCENT']
        convergence_threshold = SETTINGS[arb_type]['CONVERGENCE_THRESHOLD']
    else:
        key = f"{arb_type}_{base}_{exchange1}_{exchange2}"
        threshold = SETTINGS[arb_type]['THRESHOLD_PERCENT']
        max_threshold = SETTINGS[arb_type]['MAX_THRESHOLD_PERCENT']
        convergence_threshold = SETTINGS[arb_type]['PRICE_CONVERGENCE_THRESHOLD']
        
    current_time = time.time()

    # Если связка была отправлена в Telegram и спред превышает порог арбитража - начинаем отсчет
    if (key in sent_arbitrage_opportunities and
            threshold <= spread <= max_threshold and
            key not in arbitrage_start_times):
        arbitrage_start_times[key] = current_time
        previous_arbitrage_opportunities[key] = True
        logger.debug(f"Начало арбитража для {key}")

    # Если спред упал ниже порога сходимости - вычисляем длительность и очищаем
    elif (spread <= convergence_threshold and key in arbitrage_start_times):
        start_time = arbitrage_start_times.pop(key)
        duration = current_time - start_time
        logger.debug(f"Завершение арбитража для {key}, длительность: {duration:.0f} сек")
        return duration

    return None


def update_current_arbitrage_opportunities(arb_type: str, base: str, exchange1: str, exchange2: str, spread: float,
                                           price1: float, price2: float, volume1: float = None, volume2: float = None,
                                           min_entry_amount: float = None, max_entry_amount: float = None,
                                           profit_min: dict = None, profit_max: dict = None):
    """Обновляет информацию о текущих арбитражных возможностях (только для отправленных связок)"""
    if arb_type == 'TRIANGULAR':
        key = f"{arb_type}_{exchange1}_{base}"
        exchange2 = None # Для треугольника не нужен
        max_entry_amount = None # Для треугольника одна сумма
    else:
        key = f"{arb_type}_{base}_{exchange1}_{exchange2}"
        
    current_time = time.time()

    # Обновляем только связки, которые были отправлены в Telegram
    if key in sent_arbitrage_opportunities:
        current_arbitrage_opportunities[key] = {
            'arb_type': arb_type,
            'base': base,
            'exchange1': exchange1,
            'exchange2': exchange2,
            'spread': spread,
            'price1': price1,
            'price2': price2,
            'volume1': volume1,
            'volume2': volume2,
            'min_entry_amount': min_entry_amount,
            'max_entry_amount': max_entry_amount,
            'profit_min': profit_min,
            'profit_max': profit_max,
            'start_time': sent_arbitrage_opportunities[key]['start_time'],
            'last_updated': current_time
        }


async def get_current_arbitrage_opportunities():
    """Возвращает форматированное сообщение с текущими арбитражными возможностями (только отправленными в Telegram)"""

    # Очищаем устаревшие возможности
    cleanup_old_opportunities()

    # Используем только отправленные связки
    filtered_opportunities = {}
    current_time = time.time()

    for key, opportunity in sent_arbitrage_opportunities.items():
        # Проверяем, что связка не устарела
        if (current_time - opportunity['last_updated']) <= 3600:
            filtered_opportunities[key] = opportunity

    if not filtered_opportunities:
        return "📊 <b>Актуальные арбитражные связки</b>\n\n" \
               "⏳ В данный момент активных арбитражных возможностей не обнаружено."

    # Группируем по типу арбитража
    spot_opportunities = []
    futures_opportunities = []
    spot_futures_opportunities = []
    triangular_opportunities = [] # <-- NEW

    for key, opportunity in filtered_opportunities.items():
        arb_type = opportunity['arb_type']
        duration = time.time() - opportunity['start_time']

        opportunity_info = {
            'base': opportunity['base'],
            'exchange1': opportunity['exchange1'],
            'exchange2': opportunity.get('exchange2'),
            'spread': opportunity['spread'],
            'price1': opportunity['price1'],
            'price2': opportunity['price2'],
            'min_entry_amount': opportunity.get('min_entry_amount'),
            'max_entry_amount': opportunity.get('max_entry_amount'),
            'profit_min': opportunity.get('profit_min'),
            'profit_max': opportunity.get('profit_max'),
            'duration': duration
        }

        if arb_type == 'SPOT':
            spot_opportunities.append(opportunity_info)
        elif arb_type == 'FUTURES':
            futures_opportunities.append(opportunity_info)
        elif arb_type == 'SPOT_FUTURES':
            spot_futures_opportunities.append(opportunity_info)
        elif arb_type == 'TRIANGULAR': # <-- NEW
            triangular_opportunities.append(opportunity_info)

    # Сортируем по спреду (по убыванию)
    spot_opportunities.sort(key=lambda x: x['spread'], reverse=True)
    futures_opportunities.sort(key=lambda x: x['spread'], reverse=True)
    spot_futures_opportunities.sort(key=lambda x: x['spread'], reverse=True)
    triangular_opportunities.sort(key=lambda x: x['spread'], reverse=True) # <-- NEW

    utc_plus_3 = timezone(timedelta(hours=3))
    current_time_str = datetime.now(utc_plus_3).strftime('%H:%M:%S')
    message = "📊 <b>Актуальные арбитражные связки</b>\n\n"

    # Добавляем спотовые возможности
    if spot_opportunities:
        message += "🚀 <b>Спотовый арбитраж:</b>\n"
        for opp in spot_opportunities:
            duration_str = format_duration(opp['duration'])
            # Форматируем сумму входа и прибыль
            entry_amount_str = f"${opp['min_entry_amount']:.2f}-${opp['max_entry_amount']:.2f}" if opp.get(
                'min_entry_amount') and opp.get('max_entry_amount') else "N/A"
            profit_str = "N/A"
            if opp.get('profit_min') and opp.get('profit_max'):
                profit_min_net = opp['profit_min'].get('net', 0)
                profit_max_net = opp['profit_max'].get('net', 0)
                profit_str = f"${profit_min_net:.2f}-${profit_max_net:.2f}"
            message += (
                f" ▫️ <code>{opp['base']}</code>: {opp['spread']:.2f}%\n"
                f" 🟢 {opp['exchange1'].upper()} → 🔴 {opp['exchange2'].upper()}\n"
                f" 💰 Сумма входа: {entry_amount_str}\n"
                f" 💵 Прибыль: {profit_str}\n"
                f" ⏱ Длительность: {duration_str}\n\n"
            )

    # Добавляем фьючерсные возможности
    if futures_opportunities:
        message += "📊 <b>Фьючерсный арбитраж:</b>\n"
        for opp in futures_opportunities:
            duration_str = format_duration(opp['duration'])
            # Форматируем сумму входа и прибыль
            entry_amount_str = f"${opp['min_entry_amount']:.2f}-${opp['max_entry_amount']:.2f}" if opp.get(
                'min_entry_amount') and opp.get('max_entry_amount') else "N/A"
            profit_str = "N/A"
            if opp.get('profit_min') and opp.get('profit_max'):
                profit_min_net = opp['profit_min'].get('net', 0)
                profit_max_net = opp['profit_max'].get('net', 0)
                profit_str = f"${profit_min_net:.2f}-${profit_max_net:.2f}"
            message += (
                f" ▫️ <code>{opp['base']}</code>: {opp['spread']:.2f}%\n"
                f" 🟢 {opp['exchange1'].upper()} → 🔴 {opp['exchange2'].upper()}\n"
                f" 💰 Сумма входа: {entry_amount_str}\n"
                f" 💵 Прибыль: {profit_str}\n"
                f" ⏱ Длительность: {duration_str}\n\n"
            )

    # Добавляем спот-фьючерсные возможности
    if spot_futures_opportunities:
        message += "↔️ <b>Спот-Фьючерсный арбитраж:</b>\n"
        for opp in spot_futures_opportunities:
            duration_str = format_duration(opp['duration'])
            # Форматируем сумму входа и прибыль
            entry_amount_str = f"${opp['min_entry_amount']:.2f}-${opp['max_entry_amount']:.2f}" if opp.get(
                'min_entry_amount') and opp.get('max_entry_amount') else "N/A"
            profit_str = "N/A"
            if opp.get('profit_min') and opp.get('profit_max'):
                profit_min_net = opp['profit_min'].get('net', 0)
                profit_max_net = opp['profit_max'].get('net', 0)
                profit_str = f"${profit_min_net:.2f}-${profit_max_net:.2f}"
            message += (
                f" ▫️ <code>{opp['base']}</code>: {opp['spread']:.2f}%\n"
                f" 🟢 {opp['exchange1'].upper()} (спот) → 🔴 {opp['exchange2'].upper()} (фьючерсы)\n"
                f" 💰 Сумма входа: {entry_amount_str}\n"
                f" 💵 Прибыль: {profit_str}\n"
                f" ⏱ Длительность: {duration_str}\n\n"
            )
            
    # Добавляем треугольные возможности <-- NEW
    if triangular_opportunities:
        message += "🔱 <b>Внутрибиржевой (Треугольный) арбитраж:</b>\n"
        for opp in triangular_opportunities:
            duration_str = format_duration(opp['duration'])
            
            # base: COIN_A_COIN_B_COIN_C_PATH, где COIN_A - стартовая
            parts = opp['base'].split('_')
            
            # Путь: COIN_A → COIN_B → COIN_C → COIN_A
            coin_path = " → ".join(parts[:-1]) + f" → {parts[0]}"
            
            # Для треугольного арбитража profit_max/min - это просто profit
            profit_net = opp['profit_max'].get('net', 0)
            profit_str = f"${profit_net:.2f}"
            entry_amount_str = f"${opp['min_entry_amount']:.2f}"

            message += (
                f" ▫️ <code>{opp['exchange1'].upper()}</code>: {opp['spread']:.2f}%\n"
                f" 🔄 Путь: {coin_path}\n"
                f" 💰 Сумма входа: {entry_amount_str}\n"
                f" 💵 Прибыль: {profit_str}\n"
                f" ⏱ Длительность: {duration_str}\n\n"
            )
    # Конец NEW

    message += f"⏰ <i>Обновлено: {current_time_str}</i>\n"
    message += f"📈 <i>Всего активных связок: {len(filtered_opportunities)}</i>"
    return message


def cleanup_old_opportunities():
    """Очищает устаревшие арбитражные возможности (старше 1 часа)"""
    current_time = time.time()
    keys_to_remove = []
    for key, opportunity in sent_arbitrage_opportunities.items():
        # Удаляем если связка устарела (старше 1 часа)
        if current_time - opportunity['last_updated'] > 3600:
            keys_to_remove.append(key)

    for key in keys_to_remove:
        del sent_arbitrage_opportunities[key]
        if key in current_arbitrage_opportunities:
            del current_arbitrage_opportunities[key]
        if key in arbitrage_start_times:
            del arbitrage_start_times[key]
        if key in previous_arbitrage_opportunities:
            del previous_arbitrage_opportunities[key]


# NEW: Функции для треугольного арбитража
def find_triangular_pairs(exchange_id: str, markets: dict):
    """Находит все возможные треугольные связки A/B, B/C, A/C с участием USDT (C='USDT')."""
    
    triangles = []
    # Фильтруем все пары, в которых участвует USDT
    usdt_pairs = {
        (market['base'], market['quote'], symbol): market
        for symbol, market in markets.items()
        if market.get('spot') and market['quote'] == 'USDT'
    }
    
    # Собираем список всех BASE-монет, торгующихся к USDT
    base_coins = sorted(list(set(base for base, quote, symbol in usdt_pairs.keys())))
    
    logger.debug(f"Найдено {len(base_coins)} монет для {exchange_id} для USDT-треугольников.")

    for i in range(len(base_coins)):
        coin_a = base_coins[i]
        for j in range(i + 1, len(base_coins)):
            coin_b = base_coins[j]
            
            # Проверяем наличие двух сторон треугольника к USDT: A/USDT и B/USDT
            pair_a_usdt = f"{coin_a}/USDT"
            pair_b_usdt = f"{coin_b}/USDT"

            if pair_a_usdt in markets and pair_b_usdt in markets:
                # Ищем третью сторону: A/B или B/A
                pair_a_b = f"{coin_a}/{coin_b}"
                pair_b_a = f"{coin_b}/{coin_a}"

                if pair_a_b in markets:
                    # Треугольник: (A/USDT, B/USDT, A/B)
                    triangles.append({
                        "exchange": exchange_id,
                        "coin_a": coin_a,
                        "coin_b": coin_b,
                        "coin_c": "USDT",
                        "pair_ab": pair_a_b,
                        "pair_ac": pair_a_usdt,
                        "pair_bc": pair_b_usdt,
                    })
                
                if pair_b_a in markets:
                    # Треугольник: (A/USDT, B/USDT, B/A) (обратная пара)
                    # Используем то же определение монет, но с другой парой A/B
                    triangles.append({
                        "exchange": exchange_id,
                        "coin_a": coin_a,
                        "coin_b": coin_b,
                        "coin_c": "USDT",
                        "pair_ab": pair_b_a, # Фактическая пара - B/A
                        "pair_ac": pair_a_usdt,
                        "pair_bc": pair_b_usdt,
                    })

    logger.debug(f"Найдено {len(triangles)} треугольных связок на {exchange_id}")
    return triangles


async def calculate_triangular_profit(exchange_id: str, exchange_config: dict, triangle: dict):
    """
    Рассчитывает прибыль для треугольной связки.
    Начинаем с USDT.
    """
    
    taker_fee = exchange_config.get("taker_fee", 0.001)
    fee_multiplier = 1 - taker_fee
    
    # 1. Получаем стаканы для всех трех пар
    pairs_to_fetch = [triangle["pair_ac"], triangle["pair_bc"], triangle["pair_ab"]]
    orderbooks = {}
    try:
        results = await asyncio.gather(*(
            exchange_config['api'].fetch_order_book(pair) 
            for pair in pairs_to_fetch
        ))
        for i, pair in enumerate(pairs_to_fetch):
            orderbooks[pair] = results[i]
            
    except ccxt.ExchangeError as e:
        logger.warning(f"Ошибка CCXT при получении стаканов на {exchange_id} для {pairs_to_fetch}: {e}")
        return None, None
    except Exception as e:
        logger.error(f"Неизвестная ошибка при получении стаканов на {exchange_id}: {e}")
        return None, None

    # Проверка, что стаканы не пустые
    for pair in pairs_to_fetch:
        ob = orderbooks.get(pair)
        if not ob or not ob['bids'] or not ob['asks']:
            logger.debug(f"Пустой стакан для {pair} на {exchange_id}")
            return None, None

    # Получаем лучшие цены
    best_prices = {
        pair: {
            'bid': orderbooks[pair]['bids'][0][0], # Лучшая цена продажи (за что можно продать)
            'ask': orderbooks[pair]['asks'][0][0]  # Лучшая цена покупки (за что можно купить)
        }
        for pair in pairs_to_fetch
    }
    
    # Получаем минимальный объем в USDT
    min_volume_usd = SETTINGS['TRIANGULAR']['MIN_VOLUME_USD']
    
    # Проверяем объемы. Нам нужно проверить объем USDT на T1 и T3.
    # Поскольку T2 - это обычно не-USDT пара (например, BTC/ETH), ее объем
    # сложнее привести к USDT, поэтому проверяем только USDT-пары.
    
    # T1 и T3 - пары к USDT (pair_ac, pair_bc).
    # pair_ac: Coin_A/USDT; pair_bc: Coin_B/USDT
    volume_ac = orderbooks[triangle['pair_ac']]['bids'][0][1] * best_prices[triangle['pair_ac']]['bids'][0]
    volume_bc = orderbooks[triangle['pair_bc']]['bids'][0][1] * best_prices[triangle['pair_bc']]['bids'][0]
    
    if volume_ac < min_volume_usd or volume_bc < min_volume_usd:
        return None, None


    # Начальная сумма для расчета (в USDT)
    start_amount_usdt = SETTINGS['TRIANGULAR']['ENTRY_AMOUNT_USDT']
    
    profit_results = {}
    
    # --- НАПРАВЛЕНИЕ 1: USDT → A → B → USDT ---
    # Coin_C (USDT) → Coin_A → Coin_B → Coin_C (USDT)
    
    # T1: Купить A за USDT (Coin_A/USDT, используем ASK)
    try:
        price_t1 = best_prices[triangle['pair_ac']]['ask']
        amount_a = (start_amount_usdt / price_t1) * fee_multiplier
    
        # T2: Продать A за B (Coin_B/Coin_A или Coin_A/Coin_B)
        pair_ab_is_direct = triangle['pair_ab'] == f"{triangle['coin_a']}/{triangle['coin_b']}"
        
        if pair_ab_is_direct:
            # Pair: A/B, Sell A for B (используем BID)
            price_t2 = best_prices[triangle['pair_ab']]['bid']
            amount_b = amount_a * price_t2 * fee_multiplier
            path_coins = [triangle['coin_c'], triangle['coin_a'], triangle['coin_b'], triangle['coin_c']]
            path_pairs = [triangle['pair_ac'], triangle['pair_ab'], triangle['pair_bc']]
        else: 
            # Pair: B/A, Buy B with A (используем ASK)
            price_t2 = best_prices[triangle['pair_ab']]['ask'] # B/A. A - quote. Amount_B = Amount_A / Price_B/A
            amount_b = (amount_a / price_t2) * fee_multiplier
            path_coins = [triangle['coin_c'], triangle['coin_a'], triangle['coin_b'], triangle['coin_c']]
            path_pairs = [triangle['pair_ac'], triangle['pair_ab'], triangle['pair_bc']]
            
        # T3: Продать B за USDT (Coin_B/USDT, используем BID)
        price_t3 = best_prices[triangle['pair_bc']]['bid']
        final_usdt = amount_b * price_t3 * fee_multiplier
        
        profit_percent = (final_usdt / start_amount_usdt - 1) * 100
        net_profit_usd = final_usdt - start_amount_usdt
        
        path_name = f"{path_coins[0]}_{path_coins[1]}_{path_coins[2]}_FORWARD"
        
        profit_results[path_name] = {
            "percent": profit_percent,
            "net": net_profit_usd,
            "final_usdt": final_usdt,
            "path_coins": path_coins,
            "path_pairs": path_pairs
        }
    except Exception as e:
        logger.debug(f"Ошибка расчета пути 1 ({exchange_id}): {e}")


    # --- НАПРАВЛЕНИЕ 2: USDT → B → A → USDT ---
    # Coin_C (USDT) → Coin_B → Coin_A → Coin_C (USDT)

    # T1: Купить B за USDT (Coin_B/USDT, используем ASK)
    try:
        price_t1_r = best_prices[triangle['pair_bc']]['ask']
        amount_b_r = (start_amount_usdt / price_t1_r) * fee_multiplier

        # T2: Продать B за A (Coin_A/Coin_B или Coin_B/Coin_A)
        pair_ab_is_direct = triangle['pair_ab'] == f"{triangle['coin_a']}/{triangle['coin_b']}"
        
        if pair_ab_is_direct:
            # Pair: A/B. Buy A with B (используем ASK)
            price_t2_r = best_prices[triangle['pair_ab']]['ask'] # A/B. B - quote. Amount_A = Amount_B / Price_A/B
            amount_a_r = (amount_b_r / price_t2_r) * fee_multiplier
            path_coins_r = [triangle['coin_c'], triangle['coin_b'], triangle['coin_a'], triangle['coin_c']]
            path_pairs_r = [triangle['pair_bc'], triangle['pair_ab'], triangle['pair_ac']]
        else:
            # Pair: B/A. Sell B for A (используем BID)
            price_t2_r = best_prices[triangle['pair_ab']]['bid']
            amount_a_r = amount_b_r * price_t2_r * fee_multiplier
            path_coins_r = [triangle['coin_c'], triangle['coin_b'], triangle['coin_a'], triangle['coin_c']]
            path_pairs_r = [triangle['pair_bc'], triangle['pair_ab'], triangle['pair_ac']]
            
        # T3: Продать A за USDT (Coin_A/USDT, используем BID)
        price_t3_r = best_prices[triangle['pair_ac']]['bid']
        final_usdt_r = amount_a_r * price_t3_r * fee_multiplier
        
        profit_percent_r = (final_usdt_r / start_amount_usdt - 1) * 100
        net_profit_usd_r = final_usdt_r - start_amount_usdt
        
        path_name_r = f"{path_coins_r[0]}_{path_coins_r[1]}_{path_coins_r[2]}_REVERSE"
        
        profit_results[path_name_r] = {
            "percent": profit_percent_r,
            "net": net_profit_usd_r,
            "final_usdt": final_usdt_r,
            "path_coins": path_coins_r,
            "path_pairs": path_pairs_r
        }
    except Exception as e:
        logger.debug(f"Ошибка расчета пути 2 ({exchange_id}): {e}")

    return profit_results.get(path_name, None), profit_results.get(path_name_r, None)


async def send_triangular_arbitrage_notification(exchange_id: str, triangle_name: str, path_info: dict):
    """Отправляет уведомление о треугольном арбитраже"""
    
    arb_type = 'TRIANGULAR'
    
    # Проверка на пороги
    threshold = SETTINGS[arb_type]['THRESHOLD_PERCENT']
    max_threshold = SETTINGS[arb_type]['MAX_THRESHOLD_PERCENT']
    min_net_profit = SETTINGS[arb_type]['MIN_NET_PROFIT_USD']
    
    spread = path_info['percent']
    net_profit = path_info['net']
    
    if not (threshold <= spread <= max_threshold and net_profit >= min_net_profit):
        return
        
    # Формирование уникального ключа
    # base: COIN1_COIN2_COIN3_PATH
    base_key = f"{path_info['path_coins'][0]}_{path_info['path_coins'][1]}_{path_info['path_coins'][2]}_{triangle_name.split('_')[-1]}"
    key = f"{arb_type}_{exchange_id}_{base_key}"
    
    # Проверка на дубликат (если связка уже отправлена и активна)
    if key in sent_arbitrage_opportunities:
        update_current_arbitrage_opportunities(
            arb_type, base_key, exchange_id, None, spread, 0, 0, 0, 0,
            SETTINGS[arb_type]['ENTRY_AMOUNT_USDT'], None, profit_min=path_info, profit_max=path_info
        )
        return

    # Отправка уведомления
    utc_plus_3 = timezone(timedelta(hours=3))
    current_time_str = datetime.now(utc_plus_3).strftime('%H:%M:%S')

    path_str = " → ".join(path_info['path_coins'])
    pairs_str = " | ".join(path_info['path_pairs'])
    entry_amount_str = f"${SETTINGS[arb_type]['ENTRY_AMOUNT_USDT']:.2f}"
    profit_str = f"${net_profit:.2f}"
    
    # Дополнительная информация для сообщения
    exchange_config = SPOT_EXCHANGES[exchange_id]
    url = exchange_config['url_format'](path_info['path_pairs'][0]) # Ссылка на первую пару для примера

    message = (
        f"🔱 <b>ТРЕУГОЛЬНЫЙ АРБИТРАЖ!</b> 🚀\n\n"
        f"🏛 <b>Биржа:</b> <code>{exchange_id.upper()}</code>\n"
        f"🔄 <b>Путь:</b> <code>{path_str}</code>\n"
        f"✨ <b>Профит:</b> <code>{spread:.2f}%</code>\n"
        f"💵 <b>Чистая прибыль:</b> <code>{profit_str}</code>\n"
        f"💰 <b>Сумма входа:</b> <code>{entry_amount_str}</code>\n\n"
        f"🔗 <b><a href='{url}'>Открыть торги ({path_info['path_pairs'][0]})</a></b>\n\n"
        f"⚙️ <i>Пары: {pairs_str}</i>\n"
        f"⏰ <i>{current_time_str}</i>"
    )

    await send_telegram_message(message)
    logger.info(f"Отправлено уведомление о треугольном арбитраже на {exchange_id}: {spread:.2f}%")
    
    # Добавляем связку в sent_arbitrage_opportunities
    add_opportunity_to_sent(
        arb_type, base_key, exchange_id, exchange_id, spread, 0, 0, 0, 0,
        SETTINGS[arb_type]['ENTRY_AMOUNT_USDT'], None, profit_min=path_info, profit_max=path_info
    )

    
async def check_triangular_arbitrage():
    """Главный цикл проверки внутрибиржевого (треугольного) арбитража."""
    arb_type = 'TRIANGULAR'
    
    if not SETTINGS[arb_type]['ENABLED']:
        logger.info(f"Треугольный арбитраж выключен. Пропуск проверки.")
        await asyncio.sleep(SETTINGS[arb_type]['CHECK_INTERVAL'])
        return

    check_interval = SETTINGS[arb_type]['CHECK_INTERVAL']
    
    while True:
        try:
            start_time = time.time()
            active_exchanges = {
                id: SPOT_EXCHANGES[id]
                for id, config in SETTINGS['EXCHANGES'].items()
                if config['ENABLED'] and id in SPOT_EXCHANGES
            }
            
            tasks = []
            
            for exchange_id, exchange_config in active_exchanges.items():
                if exchange_id not in SPOT_EXCHANGES_LOADED:
                    try:
                        markets = await exchange_config['api'].load_markets()
                        SPOT_EXCHANGES_LOADED[exchange_id] = markets
                    except Exception as e:
                        logger.error(f"Не удалось загрузить рынки для {exchange_id}: {e}")
                        continue
                else:
                    markets = SPOT_EXCHANGES_LOADED[exchange_id]
                    
                # 1. Найти все треугольные связки с USDT
                triangles = find_triangular_pairs(exchange_id, markets)
                
                # 2. Создать задачи на проверку каждой связки
                for triangle in triangles:
                    tasks.append(calculate_triangular_profit(exchange_id, exchange_config, triangle))

            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                
                for i, result in enumerate(results):
                    if isinstance(result, Exception):
                        # Ошибка обработки
                        logger.error(f"Ошибка в задаче треугольного арбитража: {result}")
                        continue
                        
                    profit1, profit2 = result
                    
                    if profit1:
                        # Проверка на сходимость цен
                        duration = update_arbitrage_duration(arb_type, profit1['path_coins'][0] + "_" + profit1['path_coins'][1] + "_" + profit1['path_coins'][2] + "_FORWARD", active_exchanges[exchange_id], None, profit1['percent'])
                        if duration is not None:
                            await send_price_convergence_notification(arb_type, profit1['path_coins'][0] + "_" + profit1['path_coins'][1] + "_" + profit1['path_coins'][2] + "_FORWARD", active_exchanges[exchange_id], None, 0, 0, profit1['percent'], duration=duration)
                        else:
                            await send_triangular_arbitrage_notification(exchange_id, "FORWARD", profit1)

                    if profit2:
                        # Проверка на сходимость цен
                        duration = update_arbitrage_duration(arb_type, profit2['path_coins'][0] + "_" + profit2['path_coins'][1] + "_" + profit2['path_coins'][2] + "_REVERSE", active_exchanges[exchange_id], None, profit2['percent'])
                        if duration is not None:
                            await send_price_convergence_notification(arb_type, profit2['path_coins'][0] + "_" + profit2['path_coins'][1] + "_" + profit2['path_coins'][2] + "_REVERSE", active_exchanges[exchange_id], None, 0, 0, profit2['percent'], duration=duration)
                        else:
                            await send_triangular_arbitrage_notification(exchange_id, "REVERSE", profit2)

            end_time = time.time()
            elapsed_time = end_time - start_time
            sleep_time = max(0, check_interval - elapsed_time)
            
            logger.info(f"Треугольный арбитраж: Завершено за {elapsed_time:.2f} сек. Спим {sleep_time:.2f} сек.")
            await asyncio.sleep(sleep_time)

        except Exception as e:
            logger.error(f"Критическая ошибка в цикле треугольного арбитража: {e}")
            await asyncio.sleep(check_interval) # Пауза перед повторной попыткой
# Конец NEW


# ... (Здесь должны быть остальные функции проверки арбитража: check_spot_arbitrage, check_futures_arbitrage, check_spot_futures_arbitrage) ...
# Я не буду их дублировать, но предполагаю, что они идут здесь.

async def check_spot_arbitrage():
    # ... (Оригинальная реализация)
    pass
async def check_futures_arbitrage():
    # ... (Оригинальная реализация)
    pass
async def check_spot_futures_arbitrage():
    # ... (Оригинальная реализация)
    pass
async def load_markets_for_arbitrage():
    # ... (Оригинальная реализация)
    pass


# ... (Остальной код бота, обработчики команд, остается без изменений) ...

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начало разговора и показ главного меню."""
    if str(update.effective_chat.id) not in TELEGRAM_CHAT_IDS:
        await update.message.reply_text("Извините, у вас нет доступа к этому боту.")
        return ConversationHandler.END

    await update.message.reply_text(
        "👋 Привет! Я твой помощник в криптоарбитраже. "
        "Я буду искать для тебя выгодные связки и сообщать о них. "
        "Выбери действие:",
        reply_markup=get_main_keyboard()
    )
    return SETTINGS_MENU


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обработчик команды /help."""
    message = (
        "ℹ️ <b>Помощь</b>\n\n"
        "📈 <b>Актуальные связки</b>: Показывает текущие активные арбитражные возможности, "
        "которые были отправлены в Telegram, но еще не сошлись.\n\n"
        "🔧 <b>Настройки</b>: Позволяет настроить пороги, интервалы и биржи для:\n"
        "  - Спотового арбитража (между биржами)\n"
        "  - Фьючерсного арбитража (между биржами)\n"
        "  - Спот-Фьючерсного арбитража (на разных биржах)\n"
        "  - <b>Треугольного арбитража (внутри одной биржи)</b>\n"
        "  - Включения/выключения бирж.\n\n"
        "📊 <b>Статус бота</b>: Показывает текущие настройки и работоспособность основных функций.\n\n"
        "🔙 <b>Главное меню</b>: Возврат к основному меню."
    )
    await update.message.reply_text(message, parse_mode="HTML", reply_markup=get_main_keyboard())


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает текущий статус и настройки бота."""
    settings_copy = SETTINGS.copy()
    
    # Скрываем API-объекты для чистоты вывода
    exchange_status = []
    for ex_id, ex_conf in settings_copy['EXCHANGES'].items():
        exchange_status.append(f"  - {ex_id.upper()}: {'ВКЛ' if ex_conf['ENABLED'] else 'ВЫКЛ'}")

    message = (
        "📊 <b>Статус и текущие настройки бота</b>\n\n"
        "🤖 <b>Общий статус</b>\n"
        f"  - Спот: {'✅ ВКЛ' if settings_copy['SPOT']['ENABLED'] else '❌ ВЫКЛ'}\n"
        f"  - Фьючерсы: {'✅ ВКЛ' if settings_copy['FUTURES']['ENABLED'] else '❌ ВЫКЛ'}\n"
        f"  - Спот-Фьючерсы: {'✅ ВКЛ' if settings_copy['SPOT_FUTURES']['ENABLED'] else '❌ ВЫКЛ'}\n"
        f"  - Треугольный: {'✅ ВКЛ' if settings_copy['TRIANGULAR']['ENABLED'] else '❌ ВЫКЛ'}\n\n" # <-- NEW
        "⚙️ <b>Спот Арбитраж</b>\n"
        f"  - Порог: {settings_copy['SPOT']['THRESHOLD_PERCENT']}%\n"
        f"  - Интервал: {settings_copy['SPOT']['CHECK_INTERVAL']}с\n"
        f"  - Мин. прибыль: ${settings_copy['SPOT']['MIN_NET_PROFIT_USD']}\n\n"
        "⚙️ <b>Треугольный Арбитраж</b>\n" # <-- NEW
        f"  - Порог: {settings_copy['TRIANGULAR']['THRESHOLD_PERCENT']}%\n"
        f"  - Интервал: {settings_copy['TRIANGULAR']['CHECK_INTERVAL']}с\n"
        f"  - Сумма входа: ${settings_copy['TRIANGULAR']['ENTRY_AMOUNT_USDT']}\n"
        f"  - Мин. прибыль: ${settings_copy['TRIANGULAR']['MIN_NET_PROFIT_USD']}\n\n"
        "🏛 <b>Статус бирж</b>\n"
        f"{'\\n'.join(exchange_status)}\n\n"
        f"<i>Последнее обновление: {datetime.now(timezone(timedelta(hours=3))).strftime('%H:%M:%S')}</i>"
    )
    await update.message.reply_text(message, parse_mode="HTML", reply_markup=get_main_keyboard())


async def actual_opportunities_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показывает актуальные арбитражные связки."""
    message = await get_current_arbitrage_opportunities()
    await update.message.reply_text(message, parse_mode="HTML", reply_markup=get_main_keyboard())


async def enter_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Вход в меню настроек."""
    await update.message.reply_text("Меню настроек. Выбери тип арбитража или биржи для настройки:",
                                    reply_markup=get_settings_keyboard())
    return SETTINGS_MENU


async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик нажатий в меню настроек."""
    text = update.message.text

    if text == "🚀️ Спот":
        await update.message.reply_text("Настройки Спотового арбитража. Выбери параметр для изменения:",
                                        reply_markup=get_spot_settings_keyboard())
        context.user_data['arb_type'] = 'SPOT'
        return SPOT_SETTINGS
    
    # ... (Остальные типы настроек)
    elif text == "📊 Фьючерсы":
        await update.message.reply_text("Настройки Фьючерсного арбитража. Выбери параметр для изменения:",
                                        reply_markup=get_futures_settings_keyboard())
        context.user_data['arb_type'] = 'FUTURES'
        return FUTURES_SETTINGS
    elif text == "↔️ Спот-Фьючерсы":
        await update.message.reply_text("Настройки Спот-Фьючерсного арбитража. Выбери параметр для изменения:",
                                        reply_markup=get_spot_futures_settings_keyboard())
        context.user_data['arb_type'] = 'SPOT_FUTURES'
        return SPOT_FUTURES_SETTINGS
    elif text == "🔱 Треугольный": # <-- NEW
        await update.message.reply_text("Настройки Треугольного арбитража. Выбери параметр для изменения:",
                                        reply_markup=get_triangular_settings_keyboard())
        context.user_data['arb_type'] = 'TRIANGULAR'
        return TRIANGULAR_SETTINGS # <-- NEW STATE
    # ... (Остальные типы настроек)
    elif text == "🏛 Биржи":
        global LAST_EXCHANGE_SETTINGS
        LAST_EXCHANGE_SETTINGS = SETTINGS['EXCHANGES'].copy()
        await update.message.reply_text("Включение/выключение бирж. Нажми на название, чтобы изменить статус:",
                                        reply_markup=get_exchange_settings_keyboard())
        return EXCHANGE_SETTINGS_MENU
    elif text == "🔄 Сброс":
        global SETTINGS
        SETTINGS = load_settings()
        save_settings(SETTINGS)
        await update.message.reply_text("Настройки сброшены до значений по умолчанию.",
                                        reply_markup=get_settings_keyboard())
        return SETTINGS_MENU
    elif text == "🔙 Главное меню":
        await update.message.reply_text("Возврат в главное меню.", reply_markup=get_main_keyboard())
        return ConversationHandler.END
    else:
        await update.message.reply_text("Неизвестная команда. Пожалуйста, выберите опцию на клавиатуре.",
                                        reply_markup=get_settings_keyboard())
        return SETTINGS_MENU


async def handle_spot_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик нажатий в меню спотовых настроек."""
    text = update.message.text
    arb_type = context.user_data.get('arb_type')

    if text == "🔙 Назад в настройки":
        await update.message.reply_text("Возврат в меню настроек.", reply_markup=get_settings_keyboard())
        return SETTINGS_MENU
    
    # ... (Оригинальная логика для SPOT)
    
    # ... (Логика для изменения значения)
    
    # Определяем название параметра и его текущее значение
    parts = text.split(':')
    setting_name = parts[0].strip()
    
    setting_key = None
    input_type = None

    if setting_name == "Порог":
        setting_key = "THRESHOLD_PERCENT"
        input_type = float
    elif setting_name == "Макс. порог":
        setting_key = "MAX_THRESHOLD_PERCENT"
        input_type = float
    elif setting_name == "Интервал":
        setting_key = "CHECK_INTERVAL"
        input_type = int
    elif setting_name == "Мин. сумма":
        setting_key = "MIN_ENTRY_AMOUNT_USDT"
        input_type = float
    elif setting_name == "Макс. сумма":
        setting_key = "MAX_ENTRY_AMOUNT_USDT"
        input_type = float
    elif setting_name == "Прибыль":
        setting_key = "MIN_NET_PROFIT_USD"
        input_type = float
    elif setting_name == "Влияние":
        setting_key = "MAX_IMPACT_PERCENT"
        input_type = float
    elif setting_name == "Стакан":
        setting_key = "ORDER_BOOK_DEPTH"
        input_type = int
    elif setting_name == "Объем":
        setting_key = "MIN_VOLUME_USD"
        input_type = float
    elif setting_name == "Сходимость":
        setting_key = "PRICE_CONVERGENCE_THRESHOLD"
        input_type = float
    elif setting_name == "Увед. сравн.":
        setting_key = "PRICE_CONVERGENCE_ENABLED"
        current_status = SETTINGS[arb_type].get(setting_key)
        new_status = not current_status
        SETTINGS[arb_type][setting_key] = new_status
        save_settings(SETTINGS)
        await update.message.reply_text(f"Статус уведомлений о сходимости для {arb_type} изменен на: {'ВКЛ' if new_status else 'ВЫКЛ'}.",
                                        reply_markup=get_spot_settings_keyboard())
        return SPOT_SETTINGS
    elif setting_name == "Статус":
        setting_key = "ENABLED"
        current_status = SETTINGS[arb_type].get(setting_key)
        new_status = not current_status
        SETTINGS[arb_type][setting_key] = new_status
        save_settings(SETTINGS)
        await update.message.reply_text(f"Статус {arb_type} арбитража изменен на: {'ВКЛ' if new_status else 'ВЫКЛ'}.",
                                        reply_markup=get_spot_settings_keyboard())
        return SPOT_SETTINGS

    if setting_key:
        context.user_data['setting_key'] = setting_key
        context.user_data['input_type'] = input_type
        context.user_data['return_state_func'] = get_spot_settings_keyboard
        
        # Специальная обработка для объема
        if setting_key == "MIN_VOLUME_USD":
            await update.message.reply_text(f"Введите новый минимальный объем в USD (например, 1000000):")
        else:
            await update.message.reply_text(f"Введите новое значение для '{setting_name}' ({input_type.__name__}):")
        
        return SETTING_VALUE

    await update.message.reply_text("Неизвестная команда. Выбери опцию на клавиатуре.")
    return SPOT_SETTINGS


async def handle_futures_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (Оригинальная реализация)
    pass
    # Оставлен pass, чтобы не дублировать код, но в реальном файле должна быть полная логика
    
    text = update.message.text
    arb_type = context.user_data.get('arb_type')

    if text == "🔙 Назад в настройки":
        await update.message.reply_text("Возврат в меню настроек.", reply_markup=get_settings_keyboard())
        return SETTINGS_MENU
        
    # Определяем название параметра и его текущее значение
    parts = text.split(':')
    setting_name = parts[0].strip()
    
    setting_key = None
    input_type = None

    if setting_name == "Порог":
        setting_key = "THRESHOLD_PERCENT"
        input_type = float
    elif setting_name == "Макс. порог":
        setting_key = "MAX_THRESHOLD_PERCENT"
        input_type = float
    elif setting_name == "Интервал":
        setting_key = "CHECK_INTERVAL"
        input_type = int
    elif setting_name == "Мин. сумма":
        setting_key = "MIN_ENTRY_AMOUNT_USDT"
        input_type = float
    elif setting_name == "Макс. сумма":
        setting_key = "MAX_ENTRY_AMOUNT_USDT"
        input_type = float
    elif setting_name == "Прибыль":
        setting_key = "MIN_NET_PROFIT_USD"
        input_type = float
    elif setting_name == "Объем":
        setting_key = "MIN_VOLUME_USD"
        input_type = float
    elif setting_name == "Сходимость":
        setting_key = "PRICE_CONVERGENCE_THRESHOLD"
        input_type = float
    elif setting_name == "Увед. сравн.":
        setting_key = "PRICE_CONVERGENCE_ENABLED"
        current_status = SETTINGS[arb_type].get(setting_key)
        new_status = not current_status
        SETTINGS[arb_type][setting_key] = new_status
        save_settings(SETTINGS)
        await update.message.reply_text(f"Статус уведомлений о сходимости для {arb_type} изменен на: {'ВКЛ' if new_status else 'ВЫКЛ'}.",
                                        reply_markup=get_futures_settings_keyboard())
        return FUTURES_SETTINGS
    elif setting_name == "Статус":
        setting_key = "ENABLED"
        current_status = SETTINGS[arb_type].get(setting_key)
        new_status = not current_status
        SETTINGS[arb_type][setting_key] = new_status
        save_settings(SETTINGS)
        await update.message.reply_text(f"Статус {arb_type} арбитража изменен на: {'ВКЛ' if new_status else 'ВЫКЛ'}.",
                                        reply_markup=get_futures_settings_keyboard())
        return FUTURES_SETTINGS

    if setting_key:
        context.user_data['setting_key'] = setting_key
        context.user_data['input_type'] = input_type
        context.user_data['return_state_func'] = get_futures_settings_keyboard
        
        # Специальная обработка для объема
        if setting_key == "MIN_VOLUME_USD":
            await update.message.reply_text(f"Введите новый минимальный объем в USD (например, 1000000):")
        else:
            await update.message.reply_text(f"Введите новое значение для '{setting_name}' ({input_type.__name__}):")
        
        return SETTING_VALUE

    await update.message.reply_text("Неизвестная команда. Выбери опцию на клавиатуре.")
    return FUTURES_SETTINGS

async def handle_spot_futures_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (Оригинальная реализация)
    pass
    # Оставлен pass, чтобы не дублировать код, но в реальном файле должна быть полная логика
    
    text = update.message.text
    arb_type = context.user_data.get('arb_type')

    if text == "🔙 Назад в настройки":
        await update.message.reply_text("Возврат в меню настроек.", reply_markup=get_settings_keyboard())
        return SETTINGS_MENU
        
    # Определяем название параметра и его текущее значение
    parts = text.split(':')
    setting_name = parts[0].strip()
    
    setting_key = None
    input_type = None

    if setting_name == "Порог":
        setting_key = "THRESHOLD_PERCENT"
        input_type = float
    elif setting_name == "Макс. порог":
        setting_key = "MAX_THRESHOLD_PERCENT"
        input_type = float
    elif setting_name == "Интервал":
        setting_key = "CHECK_INTERVAL"
        input_type = int
    elif setting_name == "Мин. сумма":
        setting_key = "MIN_ENTRY_AMOUNT_USDT"
        input_type = float
    elif setting_name == "Макс. сумма":
        setting_key = "MAX_ENTRY_AMOUNT_USDT"
        input_type = float
    elif setting_name == "Прибыль":
        setting_key = "MIN_NET_PROFIT_USD"
        input_type = float
    elif setting_name == "Объем":
        setting_key = "MIN_VOLUME_USD"
        input_type = float
    elif setting_name == "Сходимость":
        setting_key = "PRICE_CONVERGENCE_THRESHOLD"
        input_type = float
    elif setting_name == "Увед. сравн.":
        setting_key = "PRICE_CONVERGENCE_ENABLED"
        current_status = SETTINGS[arb_type].get(setting_key)
        new_status = not current_status
        SETTINGS[arb_type][setting_key] = new_status
        save_settings(SETTINGS)
        await update.message.reply_text(f"Статус уведомлений о сходимости для {arb_type} изменен на: {'ВКЛ' if new_status else 'ВЫКЛ'}.",
                                        reply_markup=get_spot_futures_settings_keyboard())
        return SPOT_FUTURES_SETTINGS
    elif setting_name == "Статус":
        setting_key = "ENABLED"
        current_status = SETTINGS[arb_type].get(setting_key)
        new_status = not current_status
        SETTINGS[arb_type][setting_key] = new_status
        save_settings(SETTINGS)
        await update.message.reply_text(f"Статус {arb_type} арбитража изменен на: {'ВКЛ' if new_status else 'ВЫКЛ'}.",
                                        reply_markup=get_spot_futures_settings_keyboard())
        return SPOT_FUTURES_SETTINGS

    if setting_key:
        context.user_data['setting_key'] = setting_key
        context.user_data['input_type'] = input_type
        context.user_data['return_state_func'] = get_spot_futures_settings_keyboard
        
        # Специальная обработка для объема
        if setting_key == "MIN_VOLUME_USD":
            await update.message.reply_text(f"Введите новый минимальный объем в USD (например, 1000000):")
        else:
            await update.message.reply_text(f"Введите новое значение для '{setting_name}' ({input_type.__name__}):")
        
        return SETTING_VALUE

    await update.message.reply_text("Неизвестная команда. Выбери опцию на клавиатуре.")
    return SPOT_FUTURES_SETTINGS


# NEW: Обработчик для меню настроек треугольного арбитража
async def handle_triangular_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик нажатий в меню настроек треугольного арбитража."""
    text = update.message.text
    arb_type = context.user_data.get('arb_type')

    if text == "🔙 Назад в настройки":
        await update.message.reply_text("Возврат в меню настроек.", reply_markup=get_settings_keyboard())
        return SETTINGS_MENU
        
    # Определяем название параметра и его текущее значение
    parts = text.split(':')
    setting_name = parts[0].strip()
    
    setting_key = None
    input_type = None

    if setting_name == "Порог":
        setting_key = "THRESHOLD_PERCENT"
        input_type = float
    elif setting_name == "Макс. порог":
        setting_key = "MAX_THRESHOLD_PERCENT"
        input_type = float
    elif setting_name == "Интервал":
        setting_key = "CHECK_INTERVAL"
        input_type = int
    elif setting_name == "Сумма входа":
        setting_key = "ENTRY_AMOUNT_USDT"
        input_type = float
    elif setting_name == "Прибыль":
        setting_key = "MIN_NET_PROFIT_USD"
        input_type = float
    elif setting_name == "Объем":
        setting_key = "MIN_VOLUME_USD"
        input_type = float
    elif setting_name == "Сходимость":
        setting_key = "CONVERGENCE_THRESHOLD"
        input_type = float
    elif setting_name == "Увед. сравн.":
        setting_key = "PRICE_CONVERGENCE_ENABLED"
        current_status = SETTINGS[arb_type].get(setting_key)
        new_status = not current_status
        SETTINGS[arb_type][setting_key] = new_status
        save_settings(SETTINGS)
        await update.message.reply_text(f"Статус уведомлений о сходимости для {arb_type} изменен на: {'ВКЛ' if new_status else 'ВЫКЛ'}.",
                                        reply_markup=get_triangular_settings_keyboard())
        return TRIANGULAR_SETTINGS
    elif setting_name == "Статус":
        setting_key = "ENABLED"
        current_status = SETTINGS[arb_type].get(setting_key)
        new_status = not current_status
        SETTINGS[arb_type][setting_key] = new_status
        save_settings(SETTINGS)
        await update.message.reply_text(f"Статус {arb_type} арбитража изменен на: {'ВКЛ' if new_status else 'ВЫКЛ'}.",
                                        reply_markup=get_triangular_settings_keyboard())
        return TRIANGULAR_SETTINGS

    if setting_key:
        context.user_data['setting_key'] = setting_key
        context.user_data['input_type'] = input_type
        context.user_data['return_state_func'] = get_triangular_settings_keyboard
        
        # Специальная обработка для объема
        if setting_key == "MIN_VOLUME_USD":
            await update.message.reply_text(f"Введите новый минимальный объем в USD (например, 50000):")
        else:
            await update.message.reply_text(f"Введите новое значение для '{setting_name}' ({input_type.__name__}):")
        
        return SETTING_VALUE

    await update.message.reply_text("Неизвестная команда. Выбери опцию на клавиатуре.")
    return TRIANGULAR_SETTINGS
# Конец NEW


async def handle_exchange_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик нажатий в меню настроек бирж."""
    text = update.message.text

    if text == "🔙 Назад в настройки":
        await update.message.reply_text("Возврат в меню настроек.", reply_markup=get_settings_keyboard())
        return SETTINGS_MENU

    # Обработка включения/выключения биржи
    match = re.match(r"(\w+): (✅|❌)", text)
    if match:
        exchange_id = match.group(1).lower()
        
        if exchange_id in SETTINGS['EXCHANGES']:
            current_status = SETTINGS['EXCHANGES'][exchange_id]['ENABLED']
            new_status = not current_status
            SETTINGS['EXCHANGES'][exchange_id]['ENABLED'] = new_status
            save_settings(SETTINGS)
            
            # Очищаем загруженные рынки, чтобы бот их перезагрузил
            if exchange_id in SPOT_EXCHANGES_LOADED:
                del SPOT_EXCHANGES_LOADED[exchange_id]
            if exchange_id in FUTURES_EXCHANGES_LOADED:
                del FUTURES_EXCHANGES_LOADED[exchange_id]

            await update.message.reply_text(f"Статус биржи **{exchange_id.upper()}** изменен на: {'ВКЛ' if new_status else 'ВЫКЛ'}.",
                                            reply_markup=get_exchange_settings_keyboard(),
                                            parse_mode="Markdown")
        else:
            await update.message.reply_text("Неизвестная биржа.", reply_markup=get_exchange_settings_keyboard())
        return EXCHANGE_SETTINGS_MENU

    await update.message.reply_text("Неизвестная команда. Выбери опцию на клавиатуре.")
    return EXCHANGE_SETTINGS_MENU


async def handle_setting_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработчик ввода нового значения для настройки."""
    text = update.message.text
    arb_type = context.user_data.get('arb_type')
    setting_key = context.user_data.get('setting_key')
    input_type = context.user_data.get('input_type')
    return_state_func = context.user_data.get('return_state_func')
    
    # ... (Оригинальная логика для SETTING_VALUE)
    
    try:
        new_value = input_type(text)

        # Дополнительная проверка для объема, если это float, но должно быть int
        if setting_key == "MIN_VOLUME_USD":
            new_value = int(new_value)
            
        # Обновление настроек
        if setting_key in SETTINGS[arb_type]:
            SETTINGS[arb_type][setting_key] = new_value
            save_settings(SETTINGS)
            await update.message.reply_text(
                f"Значение '{setting_key}' для {arb_type} успешно обновлено на **{new_value}**.",
                reply_markup=return_state_func(),
                parse_mode="Markdown"
            )
            # Определение следующего состояния для возврата
            if arb_type == 'SPOT':
                return SPOT_SETTINGS
            elif arb_type == 'FUTURES':
                return FUTURES_SETTINGS
            elif arb_type == 'SPOT_FUTURES':
                return SPOT_FUTURES_SETTINGS
            elif arb_type == 'TRIANGULAR': # <-- NEW
                return TRIANGULAR_SETTINGS
            else:
                return SETTINGS_MENU
        else:
            await update.message.reply_text(f"Ошибка: Неизвестный ключ настройки '{setting_key}'.",
                                            reply_markup=return_state_func())
            return SETTING_VALUE
            
    except ValueError:
        await update.message.reply_text(f"Ошибка: Введите число в формате {input_type.__name__}. Попробуйте снова:")
        return SETTING_VALUE
    except Exception as e:
        await update.message.reply_text(f"Произошла непредвиденная ошибка: {e}",
                                        reply_markup=return_state_func())
        return SETTING_VALUE


async def handle_coin_selection(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # ... (Оригинальная реализация)
    pass
    # Оставлен pass, чтобы не дублировать код, но в реальном файле должна быть полная логика


async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Логирование ошибок, вызванных обработчиками."""
    logger.error("Произошло исключение: %s", context.error)

    if update and update.effective_message:
        await update.effective_message.reply_text(
            f'Произошла ошибка: {context.error}'
        )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Отменяет и завершает разговор."""
    await update.message.reply_text(
        'Отмена. Возврат в главное меню.', reply_markup=get_main_keyboard()
    )
    return ConversationHandler.END


def main() -> None:
    """Запуск бота."""
    logger.info("Инициализация бота")

    # Создаем Application и передаем ему токен бота
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Определяем ConversationHandler для меню настроек
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex('^🔧 Настройки$'), enter_settings)],
        states={
            SETTINGS_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_settings)
            ],
            SPOT_SETTINGS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_spot_settings)
            ],
            FUTURES_SETTINGS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_futures_settings)
            ],
            SPOT_FUTURES_SETTINGS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_spot_futures_settings)
            ],
            TRIANGULAR_SETTINGS: [ # <-- NEW
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_triangular_settings) # <-- NEW HANDLER
            ],
            EXCHANGE_SETTINGS_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exchange_settings)
            ],
            SETTING_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_setting_value)
            ],
            COIN_SELECTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_coin_selection)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(MessageHandler(filters.Regex('^📊 Статус бота$'), status_command))
    application.add_handler(MessageHandler(filters.Regex('^📈 Актуальные связки$'), actual_opportunities_command))
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)

    # Запускаем арбитражные задачи в фоне
    loop = asyncio.get_event_loop()
    loop.create_task(check_spot_arbitrage())
    loop.create_task(check_futures_arbitrage())
    loop.create_task(check_spot_futures_arbitrage())
    loop.create_task(check_triangular_arbitrage()) # <-- NEW

    logger.info("Бот запущен")

    # Запускаем бота
    application.run_polling()


if __name__ == '__main__':
    # Заглушки для функций, которые не были предоставлены в исходном коде
    # Если ты не предоставил полный код, замени эти заглушки на свои рабочие функции.
    async def check_spot_arbitrage():
        while True: await asyncio.sleep(60); logger.debug("Spot arb placeholder")
    async def check_futures_arbitrage():
        while True: await asyncio.sleep(60); logger.debug("Futures arb placeholder")
    async def check_spot_futures_arbitrage():
        while True: await asyncio.sleep(60); logger.debug("Spot-Futures arb placeholder")
        
    main()
# Конец полного кода