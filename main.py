import asyncio
from telegram import Bot, Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters, ConversationHandler
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
from web3 import Web3
import requests

# Конфигурация
TELEGRAM_TOKEN = "8357883688:AAG5E-IwqpbTn7hJ_320wpvKQpNfkm_QQeo"

# Разрешенные пользователи (добавьте сюда свои user_id)
# Чтобы получить свой user_id, отправьте сообщение боту @userinfobot в Telegram
AUTHORIZED_USERS = {
    1167694150  # Замените на ваш user_id
}

START_MENU, SPOT_SETTINGS_MENU, EXCHANGE_SETTINGS_MENU, SETTING_VALUE = range(4)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', 
    level=logging.INFO
)
logger = logging.getLogger(__name__)

DEX_CLIENTS = {
    "1inch": {"emoji": "1️⃣", "url_format": lambda s: f"https://app.1inch.io/#/1/swap/{s.replace('/USDT', '')}/USDT"},
    "matcha": {"emoji": "🍵", "url_format": lambda s: f"https://matcha.xyz/tokens/{s.replace('/USDT', '')}"},
    "paraswap": {"emoji": "💊", "url_format": lambda s: f"https://app.paraswap.io/#/{s.replace('/USDT', '')}/USDT"},
    "uniswap": {"emoji": "🦄", "url_format": lambda s: f"https://app.uniswap.org/swap?outputCurrency={s.split('/')[0]}"},
    "curve_finance": {"emoji": "➗", "url_format": lambda s: f"https://curve.fi/#/ethereum/pools"},
    "balancer": {"emoji": "⚖️", "url_format": lambda s: f"https://app.balancer.fi/#/pool"},
    "sushiswap": {"emoji": "🍣", "url_format": lambda s: f"https://app.sushi.com/swap"},
    "quickswap": {"emoji": "🦎", "url_format": lambda s: f"https://quickswap.exchange/#/swap"},
    "camelot_dex": {"emoji": "🛡️", "url_format": lambda s: f"https://camelot.exchange/"},
    "trader_joe": {"emoji": "🧑‍🌾", "url_format": lambda s: f"https://traderjoexyz.com/avalanche/trade"},
    "raydium": {"emoji": "🔆", "url_format": lambda s: f"https://raydium.io/swap/"},
    "orca": {"emoji": "🐋", "url_format": lambda s: f"https://www.orca.so/swap"},
    "jupiter": {"emoji": "🪐", "url_format": lambda s: f"https://jup.ag/swap/{s.replace('/USDT', '')}-USDT"},
    "ston_fi": {"emoji": "💎", "url_format": lambda s: f"https://app.ston.fi/swap"},
    "dedust": {"emoji": "💨", "url_format": lambda s: f"https://dedust.io/swap"},
    "pangolin": {"emoji": "🦎", "url_format": lambda s: f"https://app.pangolin.exchange/swap"},
    "osmosis": {"emoji": "⚛️", "url_format": lambda s: f"https://app.osmosis.zone/swap"},
    "maverick": {"emoji": "🐎", "url_format": lambda s: f"https://app.mav.xyz/swap"},
    "thorswap": {"emoji": "⚡", "url_format": lambda s: f"https://thorswap.finance/swap"}
}

DEX_EXCHANGES_SETTINGS = {dex: {"ENABLED": True} for dex in DEX_CLIENTS.keys()}

DEFAULT_SPOT_SETTINGS = {
    "THRESHOLD_PERCENT": 0.8,
    "MAX_THRESHOLD_PERCENT": 40,
    "CHECK_INTERVAL": 15,
    "MIN_EXCHANGES_FOR_PAIR": 2,
    "MIN_VOLUME_USD": 500000,
    "MIN_ENTRY_AMOUNT_USDT": 100,
    "MAX_ENTRY_AMOUNT_USDT": 5000,
    "MIN_NET_PROFIT_USD": 5,
    "ENABLED": True,
    "PRICE_CONVERGENCE_THRESHOLD": 0.5,
    "PRICE_CONVERGENCE_ENABLED": True
}

SETTINGS = {
    "SPOT": DEFAULT_SPOT_SETTINGS.copy(),
    "EXCHANGES": DEX_EXCHANGES_SETTINGS.copy()
}

OPPORTUNITIES_SENT = defaultdict(lambda: {"last_sent": None, "last_price": None})
CONVERGENCE_SENT = defaultdict(lambda: {"last_sent": None})

COINS_TO_CHECK = [
    "WETH", "WBTC", "LINK", "UNI", "AAVE", "MATIC", "SOL", "AVAX", "FTM", "BNB", 
    "ADA", "DOT", "DOGE", "XRP", "LTC", "BCH", "ETC", "XLM", "XMR", "ZEC",
    "USDC", "DAI", "BUSD", "USDT", "TUSD", "USDP", "GUSD", 
    "CRV", "SUSHI", "COMP", "MKR", "YFI", "SNX", "BAL", "REN", "UMA", "BAND",
    "OMG", "ZRX", "BAT", "REP", "KNC", "LRC", "MANA", "ENJ", "SAND", "AXS",
    "CHZ", "ATM", "OGN", "STORJ", "GRT", "OCEAN", "NMR", "POLY", "ANKR", "COTI",
    "STMX", "HOT", "VET", "THETA", "TFUEL", "ONE", "ALGO", "NEAR", "FLOW", "ICP",
    "FIL", "AR", "XTZ", "ATOM", "EOS", "TRX", "WAVES", "NEO", "ONT", "VTHO",
    "HBAR", "IOTA", "FTT", "SRM", "RAY", "MER", "ORCA", "PORT", "MNGO", "SLND",
    "SAMO", "LIKE", "BONK", "WIF", "JUP", "PYTH", "JTO", "TIA", "SEI", "SUI",
    "APT", "ARB", "OP", "METIS", "MNT", "STRK", "ZRO", "ENA", "ETHFI", "WEETH"
]

class PriceFetcher:
    def __init__(self):
        self.session = None
        self.w3_eth = Web3(Web3.HTTPProvider('https://mainnet.infura.io/v3/YOUR_INFURA_PROJECT_ID'))
        self.w3_polygon = Web3(Web3.HTTPProvider('https://polygon-mainnet.infura.io/v3/YOUR_INFURA_PROJECT_ID'))
        self.w3_avax = Web3(Web3.HTTPProvider('https://avalanche-mainnet.infura.io/v3/YOUR_INFURA_PROJECT_ID'))
        self.w3_arbitrum = Web3(Web3.HTTPProvider('https://arbitrum-mainnet.infura.io/v3/YOUR_INFURA_PROJECT_ID'))
        self.w3_optimism = Web3(Web3.HTTPProvider('https://optimism-mainnet.infura.io/v3/YOUR_INFURA_PROJECT_ID'))
        
    async def init_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession()
    
    async def fetch_1inch_price(self, base_asset):
        try:
            url = f"https://api.1inch.io/v4.0/1/quote"
            params = {
                'fromTokenAddress': self.get_token_address(base_asset, 'ethereum'),
                'toTokenAddress': '0xdAC17F958D2ee523a2206206994597C13D831ec7',
                'amount': 1 * 10**self.get_token_decimals(base_asset)
            }
            async with self.session.get(url, params=params) as response:
                data = await response.json()
                return float(data['toTokenAmount']) / 10**6
        except Exception as e:
            logger.error(f"1inch API error: {e}")
            return None

    async def fetch_uniswap_price(self, base_asset):
        try:
            url = "https://api.thegraph.com/subgraphs/name/uniswap/uniswap-v3"
            query = {
                "query": f"""
                {{
                    token(id: "{self.get_token_address(base_asset, 'ethereum').lower()}") {{
                        derivedETH
                    }}
                    bundle(id: "1") {{
                        ethPrice
                    }}
                }}
                """
            }
            async with self.session.post(url, json=query) as response:
                data = await response.json()
                eth_price = float(data['data']['bundle']['ethPrice'])
                derived_eth = float(data['data']['token']['derivedETH'])
                return derived_eth * eth_price
        except Exception as e:
            logger.error(f"Uniswap API error: {e}")
            return None

    async def fetch_sushiswap_price(self, base_asset):
        try:
            url = "https://api.thegraph.com/subgraphs/name/sushiswap/exchange"
            query = {
                "query": f"""
                {{
                    token(id: "{self.get_token_address(base_asset, 'ethereum').lower()}") {{
                        derivedETH
                    }}
                    bundle(id: "1") {{
                        ethPrice
                    }}
                }}
                """
            }
            async with self.session.post(url, json=query) as response:
                data = await response.json()
                eth_price = float(data['data']['bundle']['ethPrice'])
                derived_eth = float(data['data']['token']['derivedETH'])
                return derived_eth * eth_price
        except Exception as e:
            logger.error(f"Sushiswap API error: {e}")
            return None

    async def fetch_curve_price(self, base_asset):
        try:
            url = "https://api.curve.fi/api/getPools/ethereum"
            async with self.session.get(url) as response:
                data = await response.json()
                for pool in data['data']['poolData']:
                    for coin in pool['coins']:
                        if coin['symbol'] == base_asset:
                            return float(coin['usdPrice'])
                return None
        except Exception as e:
            logger.error(f"Curve API error: {e}")
            return None

    async def fetch_balancer_price(self, base_asset):
        try:
            url = "https://api.thegraph.com/subgraphs/name/balancer-labs/balancer-v2"
            query = {
                "query": f"""
                {{
                    token(id: "{self.get_token_address(base_asset, 'ethereum').lower()}") {{
                        latestPrice {{
                            pricingAsset
                            price
                        }}
                    }}
                }}
                """
            }
            async with self.session.post(url, json=query) as response:
                data = await response.json()
                price_data = data['data']['token']['latestPrice']
                if price_data['pricingAsset'] == '0xeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee':
                    eth_price = await self.get_eth_price()
                    return float(price_data['price']) * eth_price
                return float(price_data['price'])
        except Exception as e:
            logger.error(f"Balancer API error: {e}")
            return None

    async def fetch_quickswap_price(self, base_asset):
        try:
            url = "https://api.thegraph.com/subgraphs/name/sameepsi/quickswap-v3"
            query = {
                "query": f"""
                {{
                    token(id: "{self.get_token_address(base_asset, 'polygon').lower()}") {{
                        derivedMatic
                    }}
                    bundle(id: "1") {{
                        maticPriceUSD
                    }}
                }}
                """
            }
            async with self.session.post(url, json=query) as response:
                data = await response.json()
                matic_price = float(data['data']['bundle']['maticPriceUSD'])
                derived_matic = float(data['data']['token']['derivedMatic'])
                return derived_matic * matic_price
        except Exception as e:
            logger.error(f"Quickswap API error: {e}")
            return None

    async def fetch_trader_joe_price(self, base_asset):
        try:
            url = "https://api.thegraph.com/subgraphs/name/traderjoe-xyz/exchange"
            query = {
                "query": f"""
                {{
                    token(id: "{self.get_token_address(base_asset, 'avalanche').lower()}") {{
                        derivedAVAX
                    }}
                    bundle(id: "1") {{
                        avaxPriceUSD
                    }}
                }}
                """
            }
            async with self.session.post(url, json=query) as response:
                data = await response.json()
                avax_price = float(data['data']['bundle']['avaxPriceUSD'])
                derived_avax = float(data['data']['token']['derivedAVAX'])
                return derived_avax * avax_price
        except Exception as e:
            logger.error(f"Trader Joe API error: {e}")
            return None

    async def fetch_raydium_price(self, base_asset):
        try:
            url = "https://api.raydium.io/v2/main/pairs"
            async with self.session.get(url) as response:
                data = await response.json()
                for pair in data['data']:
                    if pair['baseMint'] == self.get_token_address(base_asset, 'solana'):
                        return float(pair['price'])
                return None
        except Exception as e:
            logger.error(f"Raydium API error: {e}")
            return None

    async def fetch_orca_price(self, base_asset):
        try:
            url = "https://api.orca.so/pools"
            async with self.session.get(url) as response:
                data = await response.json()
                for pool in data:
                    for asset in pool['assets']:
                        if asset['mint'] == self.get_token_address(base_asset, 'solana'):
                            return float(asset['price'])
                return None
        except Exception as e:
            logger.error(f"Orca API error: {e}")
            return None

    async def fetch_jupiter_price(self, base_asset):
        try:
            url = f"https://quote-api.jup.ag/v6/quote?inputMint={self.get_token_address(base_asset, 'solana')}&outputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&amount=1000000"
            async with self.session.get(url) as response:
                data = await response.json()
                return float(data['outAmount']) / 1000000
        except Exception as e:
            logger.error(f"Jupiter API error: {e}")
            return None

    async def fetch_osmosis_price(self, base_asset):
        try:
            url = "https://api-osmosis.imperator.co/tokens/v2/all"
            async with self.session.get(url) as response:
                data = await response.json()
                for token in data:
                    if token['symbol'] == base_asset:
                        return float(token['price'])
                return None
        except Exception as e:
            logger.error(f"Osmosis API error: {e}")
            return None

    async def get_eth_price(self):
        try:
            url = "https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd"
            async with self.session.get(url) as response:
                data = await response.json()
                return data['ethereum']['usd']
        except Exception as e:
            logger.error(f"CoinGecko API error: {e}")
            return 3500

    def get_token_address(self, token, network='ethereum'):
        addresses = {
            'ethereum': {
                "WETH": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2",
                "WBTC": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599",
                "LINK": "0x514910771AF9Ca656af840dff83E8264EcF986CA",
                "UNI": "0x1f9840a85d5aF5bf1D1762F925BDADdC4201F984",
                "AAVE": "0x7Fc66500c84A76Ad7e9c93437bFc5Ac33E2DDaE9",
                "MATIC": "0x7D1AfA7B718fb893dB30A3aBcC0fFcC94aBcC0c9",
                "USDC": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
                "USDT": "0xdAC17F958D2ee523a2206206994597C13D831ec7",
                "DAI": "0x6B175474E89094C44Da98b954EedeAC495271d0F",
                "CRV": "0xD533a949740bb3306d119CC777fa900bA034cd52",
                "SUSHI": "0x6B3595068778DD592e39A122f4f5a5cF09C90fE2",
                "COMP": "0xc00e94Cb662C3520282E6f5717214004A7f26888",
                "MKR": "0x9f8F72aA9304c8B593d555F12eF6589cC3A579A2",
            },
            'polygon': {
                "WETH": "0x7ceB23fD6bC0adD59E62ac25578270cFf1b9f619",
                "WBTC": "0x1BFD67037B42Cf73acF2047067bd4F2C47D9BfD6",
                "MATIC": "0x0000000000000000000000000000000000001010",
                "USDC": "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174",
                "USDT": "0xc2132D05D31c914a87C6611C10748AEb04B58e8F",
            },
            'avalanche': {
                "WETH": "0x49D5c2BdFfac6CE2BFdB6640F4F80f226bc10bAB",
                "WBTC": "0x50b7545627a5162F82A992c33b87aDc75187B218",
                "AVAX": "0xB31f66AA3C1e785363F0875A1B74E27b85FD66c7",
                "USDC": "0xB97EF9Ef8734C71904D8002F8b6Bc66Dd9c48a6E",
                "USDT": "0x9702230A8Ea53601f5cD2dc00fDBc13d4dF4A8c6",
            },
            'solana': {
                "SOL": "So11111111111111111111111111111111111111112",
                "USDC": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
                "USDT": "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
            }
        }
        return addresses.get(network, {}).get(token, "")

    def get_token_decimals(self, token):
        decimals = {
            "WETH": 18, "WBTC": 8, "LINK": 18, "UNI": 18, "AAVE": 18, "MATIC": 18,
            "SOL": 9, "AVAX": 18, "FTM": 18, "BNB": 18, "ADA": 6, "DOT": 10,
            "DOGE": 8, "XRP": 6, "LTC": 8, "BCH": 8, "ETC": 18, "XLM": 7,
            "USDC": 6, "USDT": 6, "DAI": 18, "BUSD": 18
        }
        return decimals.get(token, 18)

price_fetcher = PriceFetcher()

async def fetch_dex_price(exchange_id: str, base_asset: str):
    await price_fetcher.init_session()
    
    try:
        if exchange_id == "1inch":
            price = await price_fetcher.fetch_1inch_price(base_asset)
        elif exchange_id == "uniswap":
            price = await price_fetcher.fetch_uniswap_price(base_asset)
        elif exchange_id == "sushiswap":
            price = await price_fetcher.fetch_sushiswap_price(base_asset)
        elif exchange_id == "curve_finance":
            price = await price_fetcher.fetch_curve_price(base_asset)
        elif exchange_id == "balancer":
            price = await price_fetcher.fetch_balancer_price(base_asset)
        elif exchange_id == "quickswap":
            price = await price_fetcher.fetch_quickswap_price(base_asset)
        elif exchange_id == "trader_joe":
            price = await price_fetcher.fetch_trader_joe_price(base_asset)
        elif exchange_id == "raydium":
            price = await price_fetcher.fetch_raydium_price(base_asset)
        elif exchange_id == "orca":
            price = await price_fetcher.fetch_orca_price(base_asset)
        elif exchange_id == "jupiter":
            price = await price_fetcher.fetch_jupiter_price(base_asset)
        elif exchange_id == "osmosis":
            price = await price_fetcher.fetch_osmosis_price(base_asset)
        else:
            price = await price_fetcher.fetch_1inch_price(base_asset)

        if price:
            return {
                'price': price,
                'volume': 1000000,
                'impact_percent': 0.1
            }
        return None
        
    except Exception as e:
        logger.error(f"Error fetching {exchange_id} price for {base_asset}: {e}")
        return None

def format_telegram_message(title, opportunities):
    msg = f"<b>{title}</b>\n\n"
    for opt in opportunities:
        base = opt['base']
        symbol = opt['symbol']
        buy_exchange_name = opt['buy_exchange']['name']
        sell_exchange_name = opt['sell_exchange']['name']
        buy_price = opt['buy_exchange']['price']
        sell_price = opt['sell_exchange']['price']
        spread = opt['spread']
        net_spread = opt['net_spread']
        net_profit_usd = opt['net_profit_usd']
        volume_usd = opt['volume_usd']
        
        buy_url_format = DEX_CLIENTS[buy_exchange_name]['url_format']
        sell_url_format = DEX_CLIENTS[sell_exchange_name]['url_format']
        
        msg += f"🔗 <b>{base}/USDT</b> | <b>{net_spread:.2f}%</b> (Чистая)\n"
        msg += f"📈 Спред: {spread:.2f}% | Прибыль: <b>${net_profit_usd:.2f}</b>\n"
        msg += f"🔻 ПОКУПКА: <a href='{buy_url_format(symbol)}'>{DEX_CLIENTS[buy_exchange_name]['emoji']} {buy_exchange_name}</a> @ {buy_price:,.4f}\n"
        msg += f"🔺 ПРОДАЖА: <a href='{sell_url_format(symbol)}'>{DEX_CLIENTS[sell_exchange_name]['emoji']} {sell_exchange_name}</a> @ {sell_price:,.4f}\n"
        msg += f"Объем (мин): ${volume_usd:,.0f} | Влияние: {opt.get('impact', 0.0):.2f}%\n"
        
        if 'duration' in opt:
            msg += f"⏳ Длительность: {opt['duration']}\n"
        
        msg += "—" * 20 + "\n"
    return msg

async def send_telegram_message_to_users(message: str):
    """Отправляет сообщение всем авторизованным пользователям"""
    try:
        bot = Bot(token=TELEGRAM_TOKEN)
        for user_id in AUTHORIZED_USERS:
            try:
                await bot.send_message(
                    chat_id=user_id, 
                    text=message, 
                    parse_mode='HTML', 
                    disable_web_page_preview=True
                )
                logger.info(f"Message sent to user {user_id}")
            except TelegramError as e:
                logger.error(f"Failed to send message to user {user_id}: {e}")
        return True
    except TelegramError as e:
        logger.error(f"Telegram send error: {e}")
        return False

def add_opportunity_to_sent(key, spread, current_time):
    OPPORTUNITIES_SENT[key]['last_sent'] = current_time
    OPPORTUNITIES_SENT[key]['last_spread'] = spread
    logger.info(f"Opportunity {key} added to sent list.")

def add_convergence_to_sent(key, current_time):
    CONVERGENCE_SENT[key]['last_sent'] = current_time
    logger.info(f"Convergence {key} added to sent list.")

async def check_dex_arbitrage():
    settings = SETTINGS['SPOT']
    
    while True:
        current_time = datetime.now(timezone.utc)
        
        if not settings['ENABLED']:
            await asyncio.sleep(settings['CHECK_INTERVAL'])
            continue

        try:
            available_dexes = [
                ex for ex, conf in SETTINGS['EXCHANGES'].items() 
                if conf['ENABLED'] and ex in DEX_CLIENTS
            ]
            
            if len(available_dexes) < settings['MIN_EXCHANGES_FOR_PAIR']:
                await asyncio.sleep(settings['CHECK_INTERVAL'])
                continue

            active_opportunities = []
            convergence_opportunities = []
            
            for base_asset in COINS_TO_CHECK:
                symbol = f"{base_asset}/USDT"
                prices_data = {}

                tasks = [fetch_dex_price(ex_id, base_asset) for ex_id in available_dexes]
                results = await asyncio.gather(*tasks)
                
                for ex_id, data in zip(available_dexes, results):
                    if data:
                        prices_data[ex_id] = data

                dexes_with_data = list(prices_data.keys())
                
                for i in range(len(dexes_with_data)):
                    for j in range(i + 1, len(dexes_with_data)):
                        
                        ex_buy_id = dexes_with_data[i]
                        ex_sell_id = dexes_with_data[j]
                        
                        for direction in [1, -1]:
                            if direction == 1:
                                buy_id, sell_id = ex_buy_id, ex_sell_id
                            else:
                                buy_id, sell_id = ex_sell_id, ex_buy_id
                            
                            buy_data = prices_data[buy_id]
                            sell_data = prices_data[sell_id]
                            
                            price_buy = buy_data['price']
                            price_sell = sell_data['price']
                            
                            raw_spread = ((price_sell - price_buy) / price_buy) * 100
                            
                            DEX_FEES_PERCENT_ESTIMATE = 0.5
                            net_spread = raw_spread - DEX_FEES_PERCENT_ESTIMATE 

                            entry_amount = settings['MIN_ENTRY_AMOUNT_USDT']
                            net_profit_usd = (entry_amount * net_spread / 100)

                            if net_spread >= settings['THRESHOLD_PERCENT'] and net_profit_usd >= settings['MIN_NET_PROFIT_USD']:
                                
                                key = f"{base_asset}|{buy_id}|{sell_id}"
                                
                                if OPPORTUNITIES_SENT[key]['last_sent'] is None or \
                                   (current_time - OPPORTUNITIES_SENT[key]['last_sent']).total_seconds() > settings['CHECK_INTERVAL'] * 2:
                                    
                                    opportunity = {
                                        'symbol': symbol,
                                        'base': base_asset,
                                        'spread': raw_spread,
                                        'net_spread': net_spread,
                                        'net_profit_usd': net_profit_usd,
                                        'volume_usd': min(buy_data['volume'], sell_data['volume']),
                                        'impact': max(buy_data.get('impact_percent', 0.0), sell_data.get('impact_percent', 0.0)),
                                        'buy_exchange': {'name': buy_id, 'price': price_buy},
                                        'sell_exchange': {'name': sell_id, 'price': price_sell},
                                    }
                                    active_opportunities.append(opportunity)
                                    add_opportunity_to_sent(key, net_spread, current_time)

                                if settings['PRICE_CONVERGENCE_ENABLED'] and \
                                   OPPORTUNITIES_SENT[key]['last_sent'] is not None and \
                                   net_spread < settings['PRICE_CONVERGENCE_THRESHOLD'] and \
                                   CONVERGENCE_SENT[key]['last_sent'] is None:
                                    
                                    duration = current_time - OPPORTUNITIES_SENT[key]['last_sent']
                                    
                                    convergence = {
                                        'symbol': symbol,
                                        'base': base_asset,
                                        'spread': raw_spread,
                                        'net_spread': net_spread,
                                        'net_profit_usd': net_profit_usd,
                                        'volume_usd': min(buy_data['volume'], sell_data['volume']),
                                        'impact': max(buy_data.get('impact_percent', 0.0), sell_data.get('impact_percent', 0.0)),
                                        'buy_exchange': {'name': buy_id, 'price': price_buy},
                                        'sell_exchange': {'name': sell_id, 'price': price_sell},
                                        'duration': str(timedelta(seconds=int(duration.total_seconds()))),
                                    }
                                    convergence_opportunities.append(convergence)
                                    add_convergence_to_sent(key, current_time)
                                    
                                    del OPPORTUNITIES_SENT[key]
            
            if active_opportunities:
                msg = format_telegram_message("🔥 НОВЫЙ DEX АРБИТРАЖ! 🔥", active_opportunities)
                await send_telegram_message_to_users(msg)

            if convergence_opportunities:
                msg = format_telegram_message("✅ СХОДИМОСТЬ ЦЕН (DEX) ✅", convergence_opportunities)
                await send_telegram_message_to_users(msg)

        except Exception as e:
            logger.error(f"DEX arbitrage error: {e}")
            
        await asyncio.sleep(settings['CHECK_INTERVAL'])

def authorized_only(handler):
    """Декоратор для проверки авторизации пользователя"""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id not in AUTHORIZED_USERS:
            await update.message.reply_text("❌ Доступ запрещен. Вы не авторизованы для использования этого бота.")
            logger.warning(f"Unauthorized access attempt from user {user_id}")
            return ConversationHandler.END
        return await handler(update, context, *args, **kwargs)
    return wrapper

@authorized_only
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [KeyboardButton("⚙️ Настройки SPOT-арбитража (DEX)")],
        [KeyboardButton("📊 Текущие связки"), KeyboardButton("🌐 Настройки DEX-бирж")],
        [KeyboardButton("✅ Вкл/Выкл арбитраж")]
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    
    status = "ВКЛЮЧЕН" if SETTINGS['SPOT']['ENABLED'] else "ВЫКЛЮЧЕН"
    message = f"DEX арбитражный бот. Статус: <b>{status}</b>."
    await update.message.reply_html(message, reply_markup=reply_markup)
    return START_MENU

@authorized_only
async def toggle_arbitrage(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    SETTINGS['SPOT']['ENABLED'] = not SETTINGS['SPOT']['ENABLED']
    status = "ВКЛЮЧЕН" if SETTINGS['SPOT']['ENABLED'] else "ВЫКЛЮЧЕН"
    await update.message.reply_text(f"DEX арбитраж: <b>{status}</b>", parse_mode='HTML')
    return START_MENU

def get_spot_settings_keyboard():
    settings = SETTINGS['SPOT']
    keyboard = [
        [KeyboardButton(f"✅ Порог спреда: {settings['THRESHOLD_PERCENT']:.2f}%")],
        [KeyboardButton(f"⏳ Интервал проверки: {settings['CHECK_INTERVAL']} сек")],
        [KeyboardButton(f"💰 Мин. вход (USDT): {settings['MIN_ENTRY_AMOUNT_USDT']}"), 
         KeyboardButton(f"💵 Мин. чистая прибыль: ${settings['MIN_NET_PROFIT_USD']}")],
        [KeyboardButton("◀️ Назад в Главное меню")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

@authorized_only
async def spot_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = get_spot_settings_keyboard()
    await update.message.reply_text("Настройки SPOT-арбитража:", reply_markup=keyboard)
    return SPOT_SETTINGS_MENU

@authorized_only
async def handle_spot_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    context.user_data['setting_type'] = 'SPOT'
    
    if "Назад" in text:
        return await start(update, context)
    
    if "Порог спреда" in text:
        context.user_data['setting_key'] = 'THRESHOLD_PERCENT'
        await update.message.reply_text("Введите новый порог спреда %:")
        return SETTING_VALUE
    elif "Интервал проверки" in text:
        context.user_data['setting_key'] = 'CHECK_INTERVAL'
        await update.message.reply_text("Введите интервал проверки (сек):")
        return SETTING_VALUE
    elif "Мин. вход (USDT)" in text:
        context.user_data['setting_key'] = 'MIN_ENTRY_AMOUNT_USDT'
        await update.message.reply_text("Введите мин. сумму входа USDT:")
        return SETTING_VALUE
    elif "Мин. чистая прибыль" in text:
        context.user_data['setting_key'] = 'MIN_NET_PROFIT_USD'
        await update.message.reply_text("Введите мин. чистую прибыль USD:")
        return SETTING_VALUE
        
    await update.message.reply_text("Неизвестная команда.")
    return SPOT_SETTINGS_MENU

def get_exchange_settings_keyboard():
    keyboard = []
    
    dex_keys = list(SETTINGS['EXCHANGES'].keys())
    row = []
    for i, dex in enumerate(dex_keys):
        status = "🟢" if SETTINGS['EXCHANGES'][dex]['ENABLED'] else "🔴"
        row.append(KeyboardButton(f"{status} {dex}"))
        if (i + 1) % 3 == 0 or i == len(dex_keys) - 1:
            keyboard.append(row)
            row = []
            
    keyboard.append([KeyboardButton("◀️ Назад в Главное меню")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)

@authorized_only
async def exchange_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = get_exchange_settings_keyboard()
    await update.message.reply_text("Настройки DEX-бирж:", reply_markup=keyboard)
    return EXCHANGE_SETTINGS_MENU

@authorized_only
async def handle_exchange_settings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    
    if "Назад" in text:
        return await start(update, context)

    exchange_name = re.sub(r'^[🟢🔴]\s*', '', text) 
    
    if exchange_name in SETTINGS['EXCHANGES']:
        current_status = SETTINGS['EXCHANGES'][exchange_name]['ENABLED']
        SETTINGS['EXCHANGES'][exchange_name]['ENABLED'] = not current_status
        new_status = "ВКЛЮЧЕНА" if not current_status else "ВЫКЛЮЧЕНА"
        
        await update.message.reply_text(f"DEX {exchange_name}: {new_status}", parse_mode='HTML')
    else:
        await update.message.reply_text("Неизвестная биржа.")
        
    return await exchange_settings_menu(update, context)

@authorized_only
async def handle_setting_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text
    setting_key = context.user_data.get('setting_key')
    setting_type = context.user_data.get('setting_type')
    
    if not setting_key or not setting_type:
        await update.message.reply_text("Ошибка контекста.")
        return await start(update, context)

    try:
        if setting_key in ['THRESHOLD_PERCENT', 'MIN_ENTRY_AMOUNT_USDT', 'MIN_NET_PROFIT_USD']:
            new_value = float(text)
        elif setting_key == 'CHECK_INTERVAL':
            new_value = int(text)
        else:
            raise ValueError("Неизвестный тип настройки.")

        SETTINGS[setting_type][setting_key] = new_value
        await update.message.reply_text(f"Настройка {setting_key} изменена на {new_value}.", parse_mode='HTML')
        
    except ValueError:
        await update.message.reply_text("Некорректный ввод.")
        return SETTING_VALUE
        
    return await spot_settings_menu(update, context)

@authorized_only
async def current_opportunities_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    if not OPPORTUNITIES_SENT:
        msg = "Нет активных арбитражных связок."
    else:
        opportunities = []
        for key, data in OPPORTUNITIES_SENT.items():
            if data['last_sent'] is not None:
                base, buy_id, sell_id = key.split('|')
                price_info = f"Последний спред: {data['last_spread']:.2f}%"
                time_info = f"Отправлено: {(datetime.now(timezone.utc) - data['last_sent']).seconds} сек. назад"
                opportunities.append(f"🔗 {base}/USDT ({buy_id} ➡️ {sell_id})\n   {price_info}\n   {time_info}\n")
            
        msg = "Текущие связки:\n" + "\n".join(opportunities) if opportunities else "Нет активных арбитражных связок."

    keyboard = [[KeyboardButton("◀️ Назад в Главное меню")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=False)
    await update.message.reply_html(msg, reply_markup=reply_markup)
    return START_MENU

@authorized_only
async def add_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда для добавления нового пользователя (только для администраторов)"""
    if context.args:
        try:
            new_user_id = int(context.args[0])
            AUTHORIZED_USERS.add(new_user_id)
            await update.message.reply_text(f"✅ Пользователь {new_user_id} добавлен в список разрешенных.")
            logger.info(f"User {new_user_id} added to authorized users by {update.effective_user.id}")
        except ValueError:
            await update.message.reply_text("❌ Неверный формат user_id. Используйте: /add_user USER_ID")
    else:
        await update.message.reply_text("❌ Используйте: /add_user USER_ID")

@authorized_only
async def list_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Команда для просмотра списка авторизованных пользователей"""
    users_list = "\n".join([f"• {user_id}" for user_id in AUTHORIZED_USERS])
    await update.message.reply_text(f"📋 Авторизованные пользователи:\n{users_list}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception:", exc_info=context.error)

@authorized_only
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('Отменено.', reply_markup=ReplyKeyboardMarkup([['/start']], resize_keyboard=True))
    return ConversationHandler.END

def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Добавляем команды управления пользователями
    application.add_handler(CommandHandler("add_user", add_user_command))
    application.add_handler(CommandHandler("list_users", list_users_command))

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            START_MENU: [
                MessageHandler(filters.Regex("^⚙️ Настройки SPOT-арбитража"), spot_settings_menu),
                MessageHandler(filters.Regex("^🌐 Настройки DEX-бирж"), exchange_settings_menu),
                MessageHandler(filters.Regex("^✅ Вкл/Выкл арбитраж"), toggle_arbitrage),
                MessageHandler(filters.Regex("^📊 Текущие связки"), current_opportunities_menu),
            ],
            SPOT_SETTINGS_MENU: [
                MessageHandler(filters.Regex("^◀️ Назад в Главное меню"), start),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_spot_settings),
            ],
            EXCHANGE_SETTINGS_MENU: [
                MessageHandler(filters.Regex("^◀️ Назад в Главное меню"), start),
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_exchange_settings),
            ],
            SETTING_VALUE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_setting_value),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    application.add_handler(conv_handler)
    application.add_error_handler(error_handler)

    loop = asyncio.get_event_loop()
    loop.create_task(check_dex_arbitrage()) 

    logger.info("DEX Arbitrage Bot started")
    logger.info(f"Authorized users: {AUTHORIZED_USERS}")
    application.run_polling()

if __name__ == '__main__':
    main()
