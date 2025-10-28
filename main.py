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
import aiohttp
import requests

# Общая конфигурация
TELEGRAM_TOKEN = "7990034184:AAFTx--E5GE0NIPA0Yghr6KpBC80aVtSACs"
TELEGRAM_CHAT_IDS = ["1167694150", "7916502470", "5381553894", "1111230981"]

# Конфигурация DEX-CEX арбитража
DEFAULT_ARBITRAGE_SETTINGS = {
    "THRESHOLD_PERCENT": 2.0,
    "MAX_THRESHOLD_PERCENT": 20,
    "CHECK_INTERVAL": 30,
    "MIN_VOLUME_USD": 50000,
    "MIN_ENTRY_AMOUNT_USDT": 10,
    "MAX_ENTRY_AMOUNT_USDT": 500,
    "MIN_NET_PROFIT_USD": 5,
    "ENABLED": True,
    "PRICE_CONVERGENCE_THRESHOLD": 0.5,
    "PRICE_CONVERGENCE_ENABLED": True,
    "MAX_DEX_RESULTS": 10
}

# Настройки CEX бирж
CEX_SETTINGS = {
    "bybit": {"ENABLED": True},
    "mexc": {"ENABLED": True},
    "okx": {"ENABLED": True},
    "gate": {"ENABLED": True},
    "bitget": {"ENABLED": True},
    "kucoin": {"ENABLED": True},
    "bingx": {"ENABLED": True},
    "phemex": {"ENABLED": True},
    "coinex": {"ENABLED": True},
    "blofin": {"ENABLED": True}
}

# Состояния для ConversationHandler
SETTINGS_MENU, ARBITRAGE_SETTINGS, EXCHANGE_SETTINGS_MENU, SETTING_VALUE = range(4)

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger("DEXCEXArbBot")

# Глобальные переменные
SHARED_BOT = None
CEX_EXCHANGES_LOADED = {}
SETTINGS = {
    "ARBITRAGE": DEFAULT_ARBITRAGE_SETTINGS.copy(),
    "CEX": CEX_SETTINGS.copy()
}

# Конфигурация CEX фьючерсных бирж
CEX_FUTURES_EXCHANGES = {
    "bybit": {
        "api": ccxt.bybit({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: (m.get('swap', False) or m.get('future', False)) and m['settle'] == 'USDT',
        "taker_fee": 0.0006,
        "maker_fee": 0.0001,
        "url_format": lambda s: f"https://www.bybit.com/trade/usdt/{s.replace('/', '').replace(':USDT', '')}",
        "emoji": "📊"
    },
    "mexc": {
        "api": ccxt.mexc({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and 'USDT' in m['id'],
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://futures.mexc.com/exchange/{s.replace('/', '_').replace(':USDT', '')}",
        "emoji": "📊"
    },
    "okx": {
        "api": ccxt.okx({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: (m.get('swap', False) or m.get('future', False)) and m['settle'] == 'USDT',
        "taker_fee": 0.0005,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.okx.com/trade-swap/{s.replace('/', '-').replace(':USDT', '').lower()}",
        "emoji": "📊"
    },
    "gate": {
        "api": ccxt.gateio({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and '_USDT' in m['id'],
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.gate.io/futures_trade/{s.replace('/', '_').replace(':USDT', '')}",
        "emoji": "📊"
    },
    "bitget": {
        "api": ccxt.bitget({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and 'USDT' in m['id'],
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.bitget.com/ru/futures/{s.replace('/', '').replace(':USDT', '')}",
        "emoji": "📊"
    },
    "kucoin": {
        "api": ccxt.kucoin({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and 'USDT' in m['id'],
        "taker_fee": 0.0006,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://www.kucoin.com/futures/trade/{s.replace('/', '-').replace(':USDT', '')}",
        "emoji": "📊"
    },
    "bingx": {
        "api": ccxt.bingx({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: m.get('swap', False) and 'USDT' in m['id'],
        "taker_fee": 0.0005,
        "maker_fee": 0.0002,
        "url_format": lambda s: f"https://bingx.com/en-us/futures/{s.replace('/', '')}",
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
        "emoji": "📊"
    },
    "coinex": {
        "api": ccxt.coinex({"enableRateLimit": True}),
        "symbol_format": lambda s: f"{s}/USDT:USDT",
        "is_futures": lambda m: (m.get('swap', False) or m.get('future', False)) and m['settle'] == 'USDT',
        "taker_fee": 0.001,
        "maker_fee": 0.001,
        "url_format": lambda s: f"https://www.coinex.com/perpetual/{s.replace('/', '-').replace(':USDT', '')}",
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
        "emoji": "📊"
    }
}

# Глобальные переменные для отслеживания
sent_arbitrage_opportunities = defaultdict(dict)
current_arbitrage_opportunities = defaultdict(dict)
arbitrage_start_times = defaultdict(dict)

# Reply-клавиатуры
def get_main_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("📈 Актуальные связки")], 
        [KeyboardButton("🔧 Настройки")],
        [KeyboardButton("📊 Статус бота"), KeyboardButton("ℹ️ Помощь")]
    ], resize_keyboard=True)

def get_settings_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🚀 DEX-CEX Арбитраж")],
        [KeyboardButton("🏛 CEX Биржи"), KeyboardButton("🔄 Сброс")],
        [KeyboardButton("🔙 Главное меню")]
    ], resize_keyboard=True)

def get_arbitrage_settings_keyboard():
    arb = SETTINGS['ARBITRAGE']
    return ReplyKeyboardMarkup([
        [KeyboardButton(f"Порог: {arb['THRESHOLD_PERCENT']}%"),
         KeyboardButton(f"Макс. порог: {arb['MAX_THRESHOLD_PERCENT']}%")],
        [KeyboardButton(f"Интервал: {arb['CHECK_INTERVAL']}с"),
         KeyboardButton(f"Объем: ${arb['MIN_VOLUME_USD'] / 1000:.0f}K")],
        [KeyboardButton(f"Мин. сумма: ${arb['MIN_ENTRY_AMOUNT_USDT']}"),
         KeyboardButton(f"Макс. сумма: ${arb['MAX_ENTRY_AMOUNT_USDT']}")],
        [KeyboardButton(f"Прибыль: ${arb['MIN_NET_PROFIT_USD']}"),
         KeyboardButton(f"Статус: {'ВКЛ' if arb['ENABLED'] else 'ВЫКЛ'}")],
        [KeyboardButton(f"DEX лимит: {arb['MAX_DEX_RESULTS']}"),
         KeyboardButton(f"Увед. сравн.: {'🔔' if arb['PRICE_CONVERGENCE_ENABLED'] else '🔕'}")],
        [KeyboardButton("🔙 Назад в настройки")]
    ], resize_keyboard=True)

def get_exchange_settings_keyboard():
    keyboard = []
    row = []
    for i, (exchange, config) in enumerate(SETTINGS['CEX'].items()):
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

def add_opportunity_to_sent(base: str, cex: str, dex_data: dict, spread: float,
                            cex_price: float, dex_price: float, profit: dict):
    """Добавляет связку в отправленные возможности"""
    key = f"{base}_{cex}_{dex_data['dexId']}"
    current_time = time.time()

    sent_arbitrage_opportunities[key] = {
        'base': base,
        'cex': cex,
        'dex_data': dex_data,
        'spread': spread,
        'cex_price': cex_price,
        'dex_price': dex_price,
        'profit': profit,
        'start_time': current_time,
        'last_updated': current_time
    }

    current_arbitrage_opportunities[key] = sent_arbitrage_opportunities[key].copy()
    arbitrage_start_times[key] = current_time

    logger.info(f"Связка добавлена в отправленные: {key}")

async def get_dex_screener_data():
    """Получает данные с DexScreener для всех пар"""
    try:
        url = "https://api.dexscreener.com/latest/dex/pairs?limit=100"
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get('pairs', [])
                else:
                    logger.error(f"DexScreener API error: {response.status}")
                    return []
    except Exception as e:
        logger.error(f"Ошибка получения данных с DexScreener: {e}")
        return []

def filter_dex_pairs(pairs, min_volume_usd=50000):
    """Фильтрует DEX пары по объему и другим критериям"""
    filtered = []
    
    for pair in pairs:
        try:
            # Базовые проверки
            if not pair.get('priceUsd'):
                continue
                
            volume = pair.get('volume', {}).get('h24', 0)
            if volume < min_volume_usd:
                continue
                
            # Проверяем ликвидность
            liquidity = pair.get('liquidity', {}).get('usd', 0)
            if liquidity < min_volume_usd * 0.1:  # Минимальная ликвидность
                continue
                
            # Проверяем, что цена разумная
            price = float(pair['priceUsd'])
            if price <= 0 or price > 100000:  # Фильтр экстремальных цен
                continue
                
            filtered.append(pair)
            
        except Exception as e:
            logger.debug(f"Ошибка фильтрации пары: {e}")
            continue
            
    # Сортируем по объему и ограничиваем количество
    filtered.sort(key=lambda x: x.get('volume', {}).get('h24', 0), reverse=True)
    return filtered[:SETTINGS['ARBITRAGE']['MAX_DEX_RESULTS']]

async def fetch_cex_futures_price(exchange, symbol: str):
    """Получает фьючерсную цену с CEX биржи"""
    try:
        ticker = await asyncio.get_event_loop().run_in_executor(
            None, exchange.fetch_ticker, symbol
        )

        if ticker and ticker.get('last'):
            price = float(ticker['last'])
            volume = ticker.get('quoteVolume', ticker.get('baseVolume', 0))
            if volume and isinstance(volume, (int, float)):
                volume = float(volume)
            else:
                volume = 0
                
            return {
                'price': price,
                'volume': volume,
                'symbol': symbol
            }
        return None
    except Exception as e:
        logger.debug(f"Ошибка данных {symbol} на {exchange.id}: {e}")
        return None

async def load_cex_exchanges():
    """Загружает CEX биржи на основе текущих настроек"""
    global CEX_EXCHANGES_LOADED

    exchanges = {}
    for name, config in CEX_FUTURES_EXCHANGES.items():
        if not SETTINGS['CEX'][name]['ENABLED']:
            continue

        try:
            exchange = await asyncio.get_event_loop().run_in_executor(
                None, lambda: ccxt.__dict__[name]({'enableRateLimit': True})
            )
            await asyncio.get_event_loop().run_in_executor(
                None, exchange.load_markets
            )
            exchanges[name] = {
                "api": exchange,
                "config": config
            }
            logger.info(f"{name.upper()} успешно загружена")
        except Exception as e:
            logger.error(f"Ошибка инициализации {name}: {e}")

    CEX_EXCHANGES_LOADED = exchanges
    return exchanges

def calculate_profit(dex_price: float, cex_price: float, amount: float, 
                    dex_fee: float = 0.003, cex_fee: float = 0.0006) -> dict:
    """Рассчитывает прибыль для арбитража DEX -> CEX"""
    try:
        # DEX -> CEX арбитраж (покупаем на DEX, продаем на CEX)
        if dex_price < cex_price:
            buy_cost = amount * dex_price * (1 + dex_fee)
            sell_revenue = amount * cex_price * (1 - cex_fee)
            net_profit = sell_revenue - buy_cost
            profit_percent = (net_profit / buy_cost) * 100 if buy_cost > 0 else 0
            
            return {
                "net": net_profit,
                "percent": profit_percent,
                "type": "DEX_TO_CEX",
                "entry_amount": amount * dex_price
            }
        # CEX -> DEX арбитраж (покупаем на CEX, продаем на DEX)
        else:
            buy_cost = amount * cex_price * (1 + cex_fee)
            sell_revenue = amount * dex_price * (1 - dex_fee)
            net_profit = sell_revenue - buy_cost
            profit_percent = (net_profit / buy_cost) * 100 if buy_cost > 0 else 0
            
            return {
                "net": net_profit,
                "percent": profit_percent,
                "type": "CEX_TO_DEX",
                "entry_amount": amount * cex_price
            }
    except Exception as e:
        logger.error(f"Ошибка расчета прибыли: {e}")
        return {"net": 0, "percent": 0, "type": "UNKNOWN", "entry_amount": 0}

async def check_dex_cex_arbitrage():
    """Проверяет арбитражные возможности между DEX и CEX"""
    logger.info("Запуск проверки DEX-CEX арбитража")

    if not SETTINGS['ARBITRAGE']['ENABLED']:
        logger.info("DEX-CEX арбитраж отключен в настройках")
        return

    # Загружаем CEX биржи
    await load_cex_exchanges()

    if not CEX_EXCHANGES_LOADED:
        logger.error("Нет активных CEX бирж")
        return

    while SETTINGS['ARBITRAGE']['ENABLED']:
        try:
            # Получаем данные с DexScreener
            dex_pairs = await get_dex_screener_data()
            if not dex_pairs:
                logger.warning("Не удалось получить данные с DexScreener")
                await asyncio.sleep(SETTINGS['ARBITRAGE']['CHECK_INTERVAL'])
                continue

            # Фильтруем пары
            filtered_pairs = filter_dex_pairs(dex_pairs, SETTINGS['ARBITRAGE']['MIN_VOLUME_USD'])
            logger.info(f"Отфильтровано {len(filtered_pairs)} DEX пар")

            found_opportunities = 0

            for dex_pair in filtered_pairs:
                try:
                    base_symbol = dex_pair.get('baseToken', {}).get('symbol', '').upper()
                    if not base_symbol or len(base_symbol) > 10:
                        continue

                    dex_price = float(dex_pair['priceUsd'])
                    dex_volume = dex_pair.get('volume', {}).get('h24', 0)
                    dex_liquidity = dex_pair.get('liquidity', {}).get('usd', 0)

                    # Проверяем на всех CEX биржах
                    for cex_name, cex_data in CEX_EXCHANGES_LOADED.items():
                        try:
                            # Формируем символ для CEX
                            symbol = cex_data["config"]["symbol_format"](base_symbol)
                            
                            # Получаем цену с CEX
                            cex_ticker = await fetch_cex_futures_price(cex_data["api"], symbol)
                            if not cex_ticker or not cex_ticker['price']:
                                continue

                            cex_price = cex_ticker['price']
                            cex_volume = cex_ticker.get('volume', 0)

                            # Рассчитываем спред
                            spread = abs(cex_price - dex_price) / min(cex_price, dex_price) * 100

                            # Проверяем порог арбитража
                            if spread >= SETTINGS['ARBITRAGE']['THRESHOLD_PERCENT']:
                                # Рассчитываем прибыль для минимальной и максимальной суммы
                                min_profit = calculate_profit(
                                    dex_price, cex_price, 
                                    SETTINGS['ARBITRAGE']['MIN_ENTRY_AMOUNT_USDT'] / min(dex_price, cex_price)
                                )
                                
                                max_profit = calculate_profit(
                                    dex_price, cex_price,
                                    SETTINGS['ARBITRAGE']['MAX_ENTRY_AMOUNT_USDT'] / min(dex_price, cex_price)
                                )

                                # Проверяем минимальную прибыль
                                if max_profit['net'] >= SETTINGS['ARBITRAGE']['MIN_NET_PROFIT_USD']:
                                    # Форматируем сообщение
                                    utc_plus_3 = timezone(timedelta(hours=3))
                                    current_time = datetime.now(utc_plus_3).strftime('%H:%M:%S')

                                    safe_base = html.escape(base_symbol)
                                    cex_url = cex_data["config"]["url_format"](symbol.replace(':USDT', ''))
                                    dex_url = dex_pair.get('url', f"https://dexscreener.com/{dex_pair.get('chainId', 'ethereum')}/{dex_pair.get('pairAddress', '')}")

                                    # Определяем направление арбитража
                                    if dex_price < cex_price:
                                        direction = "🟢 DEX → 🔴 CEX"
                                        action = f"Купить на DEX → Продать на {cex_name.upper()}"
                                        profit_color = "🟢"
                                    else:
                                        direction = "🔴 CEX → 🟢 DEX" 
                                        action = f"Купить на {cex_name.upper()} → Продать на DEX"
                                        profit_color = "🔴"

                                    message = (
                                        f"🚀 <b>DEX-CEX АРБИТРАЖ</b>\n\n"
                                        f"▫️ <b>Монета:</b> <code>{safe_base}</code>\n"
                                        f"▫️ <b>Направление:</b> {direction}\n"
                                        f"▫️ <b>Разница цен:</b> {spread:.2f}%\n\n"
                                        
                                        f"🔄 <b>Действие:</b> {action}\n\n"
                                        
                                        f"🏛 <b><a href='{dex_url}'>DEX</a>:</b>\n"
                                        f"   💰 Цена: <code>${dex_price:.8f}</code>\n"
                                        f"   📊 Объем 24ч: <code>${dex_volume:,.0f}</code>\n"
                                        f"   💧 Ликвидность: <code>${dex_liquidity:,.0f}</code>\n"
                                        f"   🔗 Блокчейн: {dex_pair.get('chainId', 'N/A')}\n\n"
                                        
                                        f"📊 <b><a href='{cex_url}'>{cex_name.upper()}</a>:</b>\n"
                                        f"   💰 Цена: <code>${cex_price:.8f}</code>\n"
                                        f"   📊 Объем 24ч: <code>${cex_volume:,.0f}</code>\n\n"
                                        
                                        f"💰 <b>Прибыль:</b>\n"
                                        f"   ▫️ Сумма входа: ${SETTINGS['ARBITRAGE']['MIN_ENTRY_AMOUNT_USDT']:.0f}-${SETTINGS['ARBITRAGE']['MAX_ENTRY_AMOUNT_USDT']:.0f}\n"
                                        f"   ▫️ Чистая прибыль: ${min_profit['net']:.2f}-${max_profit['net']:.2f}\n"
                                        f"   ▫️ Процент: {max_profit['percent']:.2f}%\n\n"
                                        
                                        f"⏰ {current_time}\n"
                                    )

                                    logger.info(f"Найдена арбитражная возможность: {base_symbol} ({spread:.2f}%)")

                                    # Отправляем сообщение
                                    await send_telegram_message(message)

                                    # Сохраняем возможность
                                    add_opportunity_to_sent(
                                        base_symbol, cex_name, dex_pair, spread,
                                        cex_price, dex_price, max_profit
                                    )

                                    found_opportunities += 1

                        except Exception as e:
                            logger.error(f"Ошибка проверки {base_symbol} на {cex_name}: {e}")

                except Exception as e:
                    logger.error(f"Ошибка обработки DEX пары {dex_pair.get('pairAddress')}: {e}")

            logger.info(f"Цикл DEX-CEX арбитража завершен. Найдено возможностей: {found_opportunities}")
            await asyncio.sleep(SETTINGS['ARBITRAGE']['CHECK_INTERVAL'])

        except Exception as e:
            logger.error(f"Ошибка в основном цикле DEX-CEX арбитража: {e}")
            await asyncio.sleep(60)

async def get_current_arbitrage_opportunities():
    """Возвращает текущие арбитражные возможности"""
    if not current_arbitrage_opportunities:
        return "📊 <b>Актуальные DEX-CEX арбитражные связки</b>\n\n" \
               "⏳ В данный момент активных арбитражных возможностей не обнаружено."

    # Группируем возможности
    opportunities_by_coin = defaultdict(list)
    
    for key, opportunity in current_arbitrage_opportunities.items():
        opportunities_by_coin[opportunity['base']].append(opportunity)

    utc_plus_3 = timezone(timedelta(hours=3))
    current_time_str = datetime.now(utc_plus_3).strftime('%H:%M:%S')

    message = "📊 <b>Актуальные DEX-CEX арбитражные связки</b>\n\n"

    for coin, opportunities in opportunities_by_coin.items():
        message += f"<b>🪙 {coin}:</b>\n"
        
        for opp in opportunities[:3]:  # Ограничиваем 3 связками на монету
            duration = time.time() - opp['start_time']
            duration_str = format_duration(duration)
            
            if opp['profit']['type'] == 'DEX_TO_CEX':
                direction = "DEX → CEX"
            else:
                direction = "CEX → DEX"

            message += (
                f"   ▫️ <b>{opp['cex'].upper()}</b>: {opp['spread']:.2f}%\n"
                f"      📈 Направление: {direction}\n"
                f"      💰 Прибыль: ${opp['profit']['net']:.2f}\n"
                f"      ⏱ Длительность: {duration_str}\n\n"
            )

    message += f"⏰ <i>Обновлено: {current_time_str}</i>\n"
    message += f"📈 <i>Всего активных связок: {len(current_arbitrage_opportunities)}</i>"

    return message

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    user_id = str(update.effective_user.id)
    if user_id not in TELEGRAM_CHAT_IDS:
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        return

    await update.message.reply_text(
        "🤖 <b>DEX-CEX Futures Arbitrage Bot</b>\n\n"
        "Бот для поиска арбитражных возможностей между DEX и CEX фьючерсами\n\n"
        "Используйте кнопки ниже для взаимодействия с ботом:",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка текстовых сообщений"""
    user_id = str(update.effective_user.id)
    if user_id not in TELEGRAM_CHAT_IDS:
        await update.message.reply_text("⛔ У вас нет доступа к этому боту.")
        return

    text = update.message.text

    if text == "🔧 Настройки":
        await update.message.reply_text(
            "⚙️ <b>Настройки DEX-CEX бота</b>\n\nВыберите категорию:",
            parse_mode="HTML",
            reply_markup=get_settings_keyboard()
        )
        return SETTINGS_MENU

    elif text == "📈 Актуальные связки":
        await update.message.reply_text(
            "⏳ Загружаем информацию о текущих арбитражных возможностях...",
            parse_mode="HTML"
        )

        response = await get_current_arbitrage_opportunities()

        await update.message.reply_text(
            text=response,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_markup=get_main_keyboard()
        )
        return

    elif text == "📊 Статус бота":
        arb_status = "✅ ВКЛ" if SETTINGS['ARBITRAGE']['ENABLED'] else "❌ ВЫКЛ"
        enabled_cex = [name for name, config in SETTINGS['CEX'].items() if config['ENABLED']]
        cex_status = ", ".join(enabled_cex) if enabled_cex else "Нет активных CEX"

        await update.message.reply_text(
            f"🤖 <b>Статус DEX-CEX бота</b>\n\n"
            f"🚀 DEX-CEX арбитраж: {arb_status}\n"
            f"🏛 Активные CEX: {cex_status}\n"
            f"📈 Активных связок: {len(current_arbitrage_opportunities)}",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
        return

    elif text == "ℹ️ Помощь":
        await update.message.reply_text(
            "🤖 <b>DEX-CEX Futures Arbitrage Bot</b>\n\n"
            "🔍 <b>Автоматический мониторинг</b> - бот постоянно ищет арбитраж между DEX и CEX фьючерсами\n"
            "📈 <b>Актуальные связки</b> - показывает текущие арбитражные возможности\n"
            "🔧 <b>Настройки</b> - позволяет настроить параметры арбитража и CEX биржи\n\n"
            "Бот использует:\n"
            "• DexScreener для данных с DEX\n"
            "• CEX биржи для фьючерсных цен\n"
            "• Автоматический расчет прибыли с учетом комиссий",
            parse_mode="HTML",
            reply_markup=get_main_keyboard()
        )
        return

    await update.message.reply_text(
        "Неизвестная команда. Используйте кнопки меню.",
        reply_markup=get_main_keyboard()
    )

async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка меню настроек"""
    text = update.message.text

    if text == "🚀 DEX-CEX Арбитраж":
        await update.message.reply_text(
            "🚀 <b>Настройки DEX-CEX арбитража</b>\n\nВыберите параметр для изменения:",
            parse_mode="HTML",
            reply_markup=get_arbitrage_settings_keyboard()
        )
        return ARBITRAGE_SETTINGS

    elif text == "🏛 CEX Биржи":
        await update.message.reply_text(
            "🏛 <b>Настройки CEX бирж</b>\n\nВыберите биржу для включения/выключения:",
            parse_mode="HTML",
            reply_markup=get_exchange_settings_keyboard()
        )
        return EXCHANGE_SETTINGS_MENU

    elif text == "🔄 Сброс":
        SETTINGS['ARBITRAGE'] = DEFAULT_ARBITRAGE_SETTINGS.copy()
        SETTINGS['CEX'] = CEX_SETTINGS.copy()
        await update.message.reply_text(
            "✅ Настройки сброшены к значениям по умолчанию",
            reply_markup=get_settings_keyboard()
        )
        return SETTINGS_MENU

    elif text == "🔙 Главное меню":
        await update.message.reply_text(
            "Главное меню:",
            reply_markup=get_main_keyboard()
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "Неизвестная команда. Используйте кнопки меню.",
        reply_markup=get_settings_keyboard()
    )
    return SETTINGS_MENU

async def handle_arbitrage_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка настроек арбитража"""
    text = update.message.text

    if text == "🔙 Назад в настройки":
        await update.message.reply_text(
            "⚙️ <b>Настройки DEX-CEX бота</b>\n\nВыберите категорию:",
            parse_mode="HTML",
            reply_markup=get_settings_keyboard()
        )
        return SETTINGS_MENU

    # Обработка изменения параметров
    if text.startswith("Порог:"):
        context.user_data['setting'] = ('ARBITRAGE', 'THRESHOLD_PERCENT')
        await update.message.reply_text(
            f"Введите новое значение для порога арбитража (текущее: {SETTINGS['ARBITRAGE']['THRESHOLD_PERCENT']}%):"
        )
        return SETTING_VALUE

    elif text.startswith("Макс. порог:"):
        context.user_data['setting'] = ('ARBITRAGE', 'MAX_THRESHOLD_PERCENT')
        await update.message.reply_text(
            f"Введите новое значение для максимального порога (текущее: {SETTINGS['ARBITRAGE']['MAX_THRESHOLD_PERCENT']}%):"
        )
        return SETTING_VALUE

    elif text.startswith("Интервал:"):
        context.user_data['setting'] = ('ARBITRAGE', 'CHECK_INTERVAL')
        await update.message.reply_text(
            f"Введите новое значение для интервала проверки (текущее: {SETTINGS['ARBITRAGE']['CHECK_INTERVAL']} сек):"
        )
        return SETTING_VALUE

    elif text.startswith("Объем:"):
        context.user_data['setting'] = ('ARBITRAGE', 'MIN_VOLUME_USD')
        await update.message.reply_text(
            f"Введите новое значение для минимального объема (текущее: ${SETTINGS['ARBITRAGE']['MIN_VOLUME_USD']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Мин. сумма:"):
        context.user_data['setting'] = ('ARBITRAGE', 'MIN_ENTRY_AMOUNT_USDT')
        await update.message.reply_text(
            f"Введите новое значение для минимальной суммы входа (текущее: ${SETTINGS['ARBITRAGE']['MIN_ENTRY_AMOUNT_USDT']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Макс. сумма:"):
        context.user_data['setting'] = ('ARBITRAGE', 'MAX_ENTRY_AMOUNT_USDT')
        await update.message.reply_text(
            f"Введите новое значение для максимальной суммы входа (текущее: ${SETTINGS['ARBITRAGE']['MAX_ENTRY_AMOUNT_USDT']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Прибыль:"):
        context.user_data['setting'] = ('ARBITRAGE', 'MIN_NET_PROFIT_USD')
        await update.message.reply_text(
            f"Введите новое значение для минимальной прибыли (текущее: ${SETTINGS['ARBITRAGE']['MIN_NET_PROFIT_USD']}):"
        )
        return SETTING_VALUE

    elif text.startswith("DEX лимит:"):
        context.user_data['setting'] = ('ARBITRAGE', 'MAX_DEX_RESULTS')
        await update.message.reply_text(
            f"Введите новое значение для лимита DEX результатов (текущее: {SETTINGS['ARBITRAGE']['MAX_DEX_RESULTS']}):"
        )
        return SETTING_VALUE

    elif text.startswith("Увед. сравн.:"):
        SETTINGS['ARBITRAGE']['PRICE_CONVERGENCE_ENABLED'] = not SETTINGS['ARBITRAGE']['PRICE_CONVERGENCE_ENABLED']
        status = "🔔 ВКЛ" if SETTINGS['ARBITRAGE']['PRICE_CONVERGENCE_ENABLED'] else "🔕 ВЫКЛ"
        await update.message.reply_text(
            f"✅ Уведомления о сравнении цен {status}",
            reply_markup=get_arbitrage_settings_keyboard()
        )
        return ARBITRAGE_SETTINGS

    elif text.startswith("Статус:"):
        SETTINGS['ARBITRAGE']['ENABLED'] = not SETTINGS['ARBITRAGE']['ENABLED']
        status = "ВКЛ" if SETTINGS['ARBITRAGE']['ENABLED'] else "ВЫКЛ"
        await update.message.reply_text(
            f"✅ DEX-CEX арбитраж {status}",
            reply_markup=get_arbitrage_settings_keyboard()
        )
        return ARBITRAGE_SETTINGS

    await update.message.reply_text(
        "Неизвестная команда. Используйте кнопки меню.",
        reply_markup=get_arbitrage_settings_keyboard()
    )
    return ARBITRAGE_SETTINGS

async def handle_exchange_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка настроек бирж"""
    text = update.message.text

    if text == "🔙 Назад в настройки":
        await update.message.reply_text(
            "⚙️ <b>Настройки DEX-CEX бота</b>\n\nВыберите категорию:",
            parse_mode="HTML",
            reply_markup=get_settings_keyboard()
        )
        return SETTINGS_MENU

    # Обработка включения/выключения бирж
    for exchange in SETTINGS['CEX'].keys():
        if text.startswith(f"{exchange}:"):
            SETTINGS['CEX'][exchange]['ENABLED'] = not SETTINGS['CEX'][exchange]['ENABLED']
            status = "✅ ВКЛ" if SETTINGS['CEX'][exchange]['ENABLED'] else "❌ ВЫКЛ"
            await update.message.reply_text(
                f"✅ Биржа {exchange.upper()} {status}",
                reply_markup=get_exchange_settings_keyboard()
            )
            return EXCHANGE_SETTINGS_MENU

    await update.message.reply_text(
        "Неизвестная команда. Используйте кнопки меню.",
        reply_markup=get_exchange_settings_keyboard()
    )
    return EXCHANGE_SETTINGS_MENU

async def handle_setting_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка ввода значения настройки"""
    text = update.message.text
    setting_info = context.user_data.get('setting')

    if not setting_info:
        await update.message.reply_text(
            "Ошибка: не удалось определить настройку. Попробуйте снова.",
            reply_markup=get_settings_keyboard()
        )
        return SETTINGS_MENU

    category, setting_key = setting_info

    try:
        # Обработка числовых значений
        if setting_key in ['THRESHOLD_PERCENT', 'MAX_THRESHOLD_PERCENT']:
            value = float(text)
        elif setting_key in ['CHECK_INTERVAL', 'MAX_DEX_RESULTS']:
            value = int(text)
        elif setting_key in ['MIN_VOLUME_USD', 'MIN_ENTRY_AMOUNT_USDT', 'MAX_ENTRY_AMOUNT_USDT', 'MIN_NET_PROFIT_USD']:
            value = float(text)
        else:
            value = text

        # Устанавливаем новое значение
        SETTINGS[category][setting_key] = value

        await update.message.reply_text(
            f"✅ Настройка {setting_key} изменена на {text}",
            reply_markup=get_arbitrage_settings_keyboard() if category == 'ARBITRAGE' else get_exchange_settings_keyboard()
        )

        return ARBITRAGE_SETTINGS if category == 'ARBITRAGE' else EXCHANGE_SETTINGS_MENU

    except ValueError:
        await update.message.reply_text(
            "❌ Неверный формат. Введите число.",
            reply_markup=get_arbitrage_settings_keyboard() if category == 'ARBITRAGE' else get_exchange_settings_keyboard()
        )
        return SETTING_VALUE

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена диалога"""
    await update.message.reply_text(
        "Операция отменена.",
        reply_markup=get_main_keyboard()
    )
    return ConversationHandler.END

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Ошибка: {context.error}", exc_info=context.error)

    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Произошла ошибка. Попробуйте позже.",
            reply_markup=get_main_keyboard()
        )

def main():
    """Основная функция запуска бота"""
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Conversation handler для настроек
    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
        ],
        states={
            SETTINGS_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_settings)
            ],
            ARBITRAGE_SETTINGS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_arbitrage_settings)
            ],
            EXCHANGE_SETTINGS_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exchange_settings)
            ],
            SETTING_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_setting_value)
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    # Добавляем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)

    # Запускаем DEX-CEX арбитражную задачу в фоне
    loop = asyncio.get_event_loop()
    loop.create_task(check_dex_cex_arbitrage())

    logger.info("DEX-CEX арбитражный бот запущен")

    # Запускаем бота
    application.run_polling()

if __name__ == '__main__':
    main()
