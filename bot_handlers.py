import asyncio
import logging
import re
import html
import json
from typing import Dict, Any, Optional, List
from datetime import datetime
from urllib.parse import quote

from aiogram import Router, F, types
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, CallbackQuery, InlineQuery, InlineQueryResultArticle,
    InputTextMessageContent, ReplyKeyboardMarkup, KeyboardButton,
    WebAppInfo, InlineKeyboardMarkup, InlineKeyboardButton,
    ChatMemberUpdated, ChatJoinRequest
)
from aiogram.enums import ParseMode
from aiogram.utils.deep_linking import create_start_link
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder

# Local imports
from config import get_config
from database import get_db
from market_data import get_market_provider
from ai_analyzer import get_analyzer
from news_parser import get_news_aggregator
from keyboards import (
    get_main_menu_keyboard, get_subscription_keyboard, get_referral_keyboard,
    get_settings_keyboard, get_back_button, get_language_keyboard,
    get_confirmation_keyboard, get_pagination_keyboard, get_signal_type_keyboard
)
from payments import get_payment_manager

cfg = get_config()
db = get_db()
market = get_market_provider()
analyzer = get_analyzer()
news = get_news_aggregator()
payment_manager = get_payment_manager()

logger = logging.getLogger(__name__)
router = Router()

# ===================================================================
# FSM States
# ===================================================================

class SubscriptionStates(StatesGroup):
    waiting_for_payment_confirmation = State()
    waiting_withdraw_address = State()
    waiting_feedback = State()
    waiting_support_message = State()

class AdminStates(StatesGroup):
    waiting_broadcast_message = State()
    waiting_add_balance_user = State()
    waiting_add_balance_amount = State()
    waiting_set_subscription_days = State()

# ===================================================================
# Helper functions
# ===================================================================

def escape_html(text: str) -> str:
    """Escape HTML special characters"""
    if not text:
        return ""
    return html.escape(str(text))

def format_price(price: float) -> str:
    """Format price with proper decimals"""
    if price < 0.01:
        return f"${price:.8f}"
    elif price < 1:
        return f"${price:.4f}"
    elif price < 10000:
        return f"${price:.2f}"
    else:
        return f"${price:,.0f}"

def format_large_number(num: float) -> str:
    """Format large numbers with K/M/B suffixes"""
    if num >= 1_000_000_000:
        return f"{num/1_000_000_000:.1f}B"
    elif num >= 1_000_000:
        return f"{num/1_000_000:.1f}M"
    elif num >= 1_000:
        return f"{num/1_000:.1f}K"
    else:
        return str(int(num))

async def get_user_language(user_id: int) -> str:
    """Get user's preferred language"""
    user = await db.get_user(user_id)
    if user and user.get("language"):
        return user["language"]
    return cfg.DEFAULT_LANGUAGE

# ===================================================================
# Start & Registration
# ===================================================================

@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Handle /start command with referral support"""
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    language = message.from_user.language_code or cfg.DEFAULT_LANGUAGE
    
    # Register or update user
    is_new = await db.register_user(user_id, username, first_name, last_name, language)
    
    # Check for referral code in deep link
    args = message.text.split()
    if len(args) > 1 and args[1].startswith("ref_"):
        ref_code = args[1][4:]  # Remove "ref_" prefix
        referrer_id = await db.get_by_referral_code(ref_code)
        if referrer_id and referrer_id != user_id:
            await db.add_referral(referrer_id, user_id)
            # Notify referrer if they have active subscription (optional)
            await db.log_user_action(user_id, "referred_by", f"referrer={referrer_id}")
    
    # Welcome message
    welcome_text = (
        f"🚀 *Welcome to CryptoPulse AI* {escape_html(first_name)}!\n\n"
        f"🤖 *AI-Powered Crypto Signals*\n"
        f"• Real-time market analysis\n"
        f"• High-confidence BUY/SELL/HOLD signals\n"
        f"• Multi-exchange data aggregation\n"
        f"• News sentiment analysis\n\n"
        f"💰 *Subscription*: ${cfg.SUBSCRIPTION_PRICE_USD}/{cfg.SUBSCRIPTION_DAYS} days\n"
        f"🎁 *Referral bonus*: Earn ${cfg.REFERRAL_BONUS_ON_SUBSCRIBE} per friend\n\n"
        f"Use /menu to start trading!"
    )
    
    await message.answer(welcome_text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_menu_keyboard(user_id))
    await state.clear()

@router.message(Command("menu"))
async def cmd_menu(message: Message):
    """Show main menu"""
    user_id = message.from_user.id
    has_sub = await db.has_active_subscription(user_id)
    
    menu_text = (
        f"📋 *Main Menu*\n\n"
        f"🔹 Premium: {'✅ Active' if has_sub else '❌ Inactive'}\n"
        f"🔹 Subscribers: {await db.get_active_subscribers_count()}\n"
        f"🔹 Total users: {await db.get_user_count()}\n\n"
        f"Select an option below:"
    )
    await message.answer(menu_text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_main_menu_keyboard(user_id))

# ===================================================================
# Signal Commands
# ===================================================================

@router.message(Command("signal"))
@router.message(F.text.lower().in_({"📈 signal", "signal", "get signal"}))
async def cmd_signal(message: Message):
    """Get current signal for default symbol (BTC)"""
    user_id = message.from_user.id
    
    # Rate limiting check
    allowed, retry_after = await db.check_rate_limit(user_id, "signal")
    if not allowed:
        await message.answer(f"⏳ Rate limit. Try again in {retry_after} seconds.")
        return
    
    # Check subscription
    has_sub = await db.has_active_subscription(user_id)
    free_remaining = 0
    if not has_sub:
        # Count free signals today
        async with db.get_cursor() as c:
            day_start = int(datetime.now().replace(hour=0, minute=0, second=0).timestamp())
            c.execute("SELECT COUNT(*) FROM user_actions WHERE user_id=? AND action='free_signal' AND timestamp>?", 
                      (user_id, day_start))
            free_used = c.fetchone()[0]
            free_remaining = cfg.FREE_SIGNALS_PER_DAY - free_used
            if free_remaining <= 0:
                await message.answer(
                    f"❌ You've used all {cfg.FREE_SIGNALS_PER_DAY} free signals today.\n"
                    f"Subscribe for unlimited signals: /subscribe"
                )
                return
    
    # Get market data and generate signal
    await message.answer("📊 Fetching live market data and AI analysis... Please wait.")
    
    try:
        # Get market data for BTC/USDT
        market_data = await market.get_full_market_data("BTC/USDT")
        # Get news
        news_items = await news.get_news_by_coin("BTC", 5)
        
        # Generate signal via AI
        price_data = {
            "prices": await market.get_historical_prices("BTC/USDT", "1h", 60),
            "volumes": [],  # Would need volume history
            "price_changes": []
        }
        signal = await analyzer.get_signal("BTC/USDT", price_data, news_items)
        
        # Format signal message
        signal_text = (
            f"{signal['action_emoji']} *CRYPTO SIGNAL: {signal['action']}*\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📌 *Symbol*: {signal['symbol']}\n"
            f"💰 *Current Price*: {format_price(signal['current_price'])}\n"
            f"🎯 *Confidence*: {signal['confidence']}%\n"
            f"📊 *AI Score*: {signal['score']:.2f}\n\n"
            f"{signal['reasoning']}\n\n"
            f"🕐 {datetime.fromtimestamp(signal['timestamp']).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"⚠️ Not financial advice. DYOR."
        )
        
        # Log the action
        if not has_sub:
            await db.log_user_action(user_id, "free_signal", f"remaining={free_remaining-1}")
        
        # Update signal counter
        async with db.get_cursor() as c:
            c.execute("UPDATE users SET total_signals_requested = total_signals_requested + 1 WHERE user_id = ?", (user_id,))
        
        await message.answer(signal_text, parse_mode=ParseMode.MARKDOWN)
        
    except Exception as e:
        logger.error(f"Signal generation failed: {e}")
        await message.answer("⚠️ Signal generation temporarily unavailable. Please try again later.")

@router.message(Command("signal_custom"))
async def cmd_signal_custom(message: Message):
    """Get signal for specific symbol - example: /signal_custom ETH/USDT"""
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Usage: /signal_custom <symbol>\nExample: /signal_custom ETH/USDT")
        return
    
    symbol = args[1].upper()
    if "/USDT" not in symbol and "/BTC" not in symbol:
        symbol = symbol + "/USDT"
    
    user_id = message.from_user.id
    allowed, _ = await db.check_rate_limit(user_id, f"signal_{symbol}")
    if not allowed:
        await message.answer("Rate limit. Please wait.")
        return
    
    has_sub = await db.has_active_subscription(user_id)
    if not has_sub:
        remaining = await check_free_signals(user_id)
        if remaining <= 0:
            await message.answer("Free signals exhausted. Subscribe: /subscribe")
            return
    
    await message.answer(f"📊 Analyzing {symbol}...")
    try:
        market_data = await market.get_full_market_data(symbol)
        news_items = await news.get_news_by_coin(symbol.split("/")[0], 5)
        price_data = {"prices": await market.get_historical_prices(symbol, "1h", 60), "volumes": [], "price_changes": []}
        signal = await analyzer.get_signal(symbol, price_data, news_items)
        
        signal_text = (
            f"{signal['action_emoji']} *SIGNAL FOR {signal['symbol']}*\n"
            f"Action: *{signal['action']}*\n"
            f"Price: {format_price(signal['current_price'])}\n"
            f"Confidence: {signal['confidence']}%\n"
            f"Reason: {signal['reasoning'][:200]}..."
        )
        await message.answer(signal_text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await message.answer(f"Error fetching data for {symbol}: {e}")

async def check_free_signals(user_id: int) -> int:
    """Return remaining free signals for today"""
    day_start = int(datetime.now().replace(hour=0, minute=0, second=0).timestamp())
    async with db.get_cursor() as c:
        c.execute("SELECT COUNT(*) FROM user_actions WHERE user_id=? AND action='free_signal' AND timestamp>?", 
                  (user_id, day_start))
        used = c.fetchone()[0]
    return cfg.FREE_SIGNALS_PER_DAY - used

# ===================================================================
# Subscription Commands
# ===================================================================

@router.message(Command("subscribe"))
@router.message(F.text.lower().in_({"💎 subscribe", "subscribe", "buy subscription"}))
async def cmd_subscribe(message: Message):
    """Show subscription options"""
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    has_sub = await db.has_active_subscription(user_id)
    
    if has_sub:
        expiry = await db.get_subscription_expiry(user_id)
        expiry_str = datetime.fromtimestamp(expiry).strftime("%Y-%m-%d") if expiry else "unknown"
        text = (
            f"✅ *You already have an active subscription!*\n"
            f"Expires: {expiry_str}\n\n"
            f"Want to extend or upgrade? Contact @support."
        )
        await message.answer(text, parse_mode=ParseMode.MARKDOWN)
        return
    
    # Generate payment link via CryptoBot
    payment_id = await db.create_payment(user_id, cfg.SUBSCRIPTION_PRICE_USD, "USDT")
    payment_link = await payment_manager.create_invoice(cfg.SUBSCRIPTION_PRICE_USD, "USDT", payment_id)
    
    if not payment_link:
        text = f"💎 *Premium Subscription*\n\nPrice: ${cfg.SUBSCRIPTION_PRICE_USD}/{cfg.SUBSCRIPTION_DAYS} days\n\nContact @support for manual payment."
        await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_subscription_keyboard())
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Pay ${cfg.SUBSCRIPTION_PRICE_USD} USDT", url=payment_link)],
        [InlineKeyboardButton(text="🔄 Already Paid?", callback_data=f"check_payment_{payment_id}")]
    ])
    
    text = (
        f"💎 *CryptoPulse AI Premium*\n\n"
        f"✨ *Benefits:*\n"
        f"• Unlimited AI signals\n"
        f"• Real-time market data\n"
        f"• Priority support\n"
        f"• Advanced indicators\n\n"
        f"💰 *Price:* ${cfg.SUBSCRIPTION_PRICE_USD} USDT for {cfg.SUBSCRIPTION_DAYS} days\n\n"
        f"Click button below to pay via CryptoBot."
    )
    await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)

@router.callback_query(F.data.startswith("check_payment_"))
async def callback_check_payment(callback: CallbackQuery):
    """Check if payment was completed"""
    payment_id = callback.data.split("_")[-1]
    user_id = callback.from_user.id
    
    status = await payment_manager.check_payment(payment_id)
    
    if status == "paid":
        # Activate subscription
        expire = await db.activate_subscription(user_id, payment_id=payment_id)
        await callback.message.edit_text(
            f"✅ *Subscription Activated!*\n\nExpires: {datetime.fromtimestamp(expire).strftime('%Y-%m-%d')}\n\nUse /menu to get signals.",
            parse_mode=ParseMode.MARKDOWN
        )
        await callback.answer("Payment confirmed! Welcome to Premium!")
    elif status == "pending":
        await callback.answer("Payment still pending. Please wait or contact support.", show_alert=True)
    else:
        await callback.answer("No payment found. Please complete the payment first.")

# ===================================================================
# Referral Commands
# ===================================================================

@router.message(Command("referral"))
@router.message(F.text.lower().in_({"👥 referral", "referral", "invite"}))
async def cmd_referral(message: Message):
    """Display referral link and stats"""
    user_id = message.from_user.id
    stats = await db.get_referral_stats(user_id)
    balance = await db.get_balance(user_id)
    link = await db.get_referral_link(user_id)
    
    if not link:
        link = f"https://t.me/{cfg.BOT_USERNAME}?start=ref_waiting"
    
    text = (
        f"👥 *Referral Program*\n\n"
        f"Invite friends and earn ${cfg.REFERRAL_BONUS_ON_SUBSCRIBE} for each one!\n"
        f"Multi-level rewards up to {cfg.MAX_REFERRAL_LEVELS} levels.\n\n"
        f"🔗 *Your link:*\n`{link}`\n\n"
        f"📊 *Your stats:*\n"
        f"• Direct referrals: {stats['direct_count']}\n"
        f"• Total earned: ${stats['total_earned']:.2f}\n"
        f"• Bonus balance: ${balance:.2f}\n\n"
        f"💡 *Tip:* Share your link in crypto groups!"
    )
    
    await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_referral_keyboard())

@router.callback_query(F.data == "withdraw")
async def callback_withdraw(callback: CallbackQuery, state: FSMContext):
    """Initiate withdrawal process"""
    user_id = callback.from_user.id
    balance = await db.get_balance(user_id)
    
    if balance < cfg.REFERRAL_MIN_WITHDRAW:
        await callback.answer(f"Minimum withdrawal: ${cfg.REFERRAL_MIN_WITHDRAW}", show_alert=True)
        return
    
    await callback.message.answer(
        f"💸 *Withdrawal*\n\nBalance: ${balance:.2f}\nMinimum: ${cfg.REFERRAL_MIN_WITHDRAW}\n\nSend your USDT (TRC20) address:",
        parse_mode=ParseMode.MARKDOWN
    )
    await state.set_state(SubscriptionStates.waiting_withdraw_address)
    await callback.answer()

@router.message(SubscriptionStates.waiting_withdraw_address)
async def process_withdraw_address(message: Message, state: FSMContext):
    """Process withdrawal address submission"""
    address = message.text.strip()
    # Basic TRC20 address validation
    if not address.startswith("T") or len(address) != 34:
        await message.answer("❌ Invalid USDT TRC20 address. Please check and try again.")
        return
    
    user_id = message.from_user.id
    balance = await db.get_balance(user_id)
    
    if balance < cfg.REFERRAL_MIN_WITHDRAW:
        await message.answer("Balance insufficient for withdrawal.")
        await state.clear()
        return
    
    # Create withdrawal request in database
    async with db.get_cursor() as c:
        c.execute("INSERT INTO payments (payment_id, user_id, amount, currency, status) VALUES (?, ?, ?, 'withdraw_pending')",
                  (f"wd_{user_id}_{int(datetime.now().timestamp())}", user_id, balance, "USDT"))
    await db.deduct_balance(user_id, balance, "withdrawal")
    
    await message.answer(
        f"✅ Withdrawal request submitted for ${balance:.2f} USDT to address `{address}`\n"
        f"Processing within 24-48 hours.\n"
        f"Request ID: wd_{user_id}",
        parse_mode=ParseMode.MARKDOWN
    )
    await state.clear()
    # Notify admin
    for admin_id in cfg.ADMIN_IDS:
        try:
            await message.bot.send_message(admin_id, f"💸 Withdrawal request: ${balance:.2f} from user {user_id}\nAddress: {address}")
        except:
            pass

# ===================================================================
# Profile & Settings
# ===================================================================

@router.message(Command("profile"))
@router.message(F.text.lower().in_({"👤 profile", "profile"}))
async def cmd_profile(message: Message):
    """Display user profile"""
    user_id = message.from_user.id
    user = await db.get_user(user_id)
    if not user:
        await message.answer("User not found. Please /start")
        return
    
    has_sub = await db.has_active_subscription(user_id)
    expiry = await db.get_subscription_expiry(user_id)
    stats = await db.get_referral_stats(user_id)
    
    text = (
        f"👤 *Profile*\n\n"
        f"ID: `{user_id}`\n"
        f"Name: {escape_html(user.get('first_name', '') or '')}\n"
        f"Joined: {datetime.fromtimestamp(user['registered_at']).strftime('%Y-%m-%d')}\n"
        f"Language: {user.get('language', 'en')}\n\n"
        f"💰 *Premium:* {'✅ Active' if has_sub else '❌ Inactive'}\n"
        f"📅 Expires: {datetime.fromtimestamp(expiry).strftime('%Y-%m-%d') if expiry else 'N/A'}\n"
        f"📊 Signals used: {user.get('total_signals_requested', 0)}\n"
        f"👥 Referrals: {stats['direct_count']}\n"
        f"🎁 Bonus balance: ${user.get('balance', 0):.2f}"
    )
    await message.answer(text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_settings_keyboard())

@router.callback_query(F.data == "settings_language")
async def callback_language(callback: CallbackQuery):
    """Show language selection"""
    user_id = callback.from_user.id
    current_lang = (await db.get_user(user_id)).get("language", "en")
    
    text = f"🌐 *Language Selection*\n\nCurrent: {current_lang.upper()}\n\nSelect your preferred language:"
    await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=get_language_keyboard(current_lang))
    await callback.answer()

@router.callback_query(F.data.startswith("set_lang_"))
async def callback_set_lang(callback: CallbackQuery):
    """Set user language"""
    lang = callback.data.split("_")[-1]
    user_id = callback.from_user.id
    async with db.get_cursor() as c:
        c.execute("UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id))
    await callback.message.edit_text(f"✅ Language set to {lang.upper()}. /menu to continue.")
    await callback.answer()

# ===================================================================
# Balance Commands
# ===================================================================

@router.message(Command("balance"))
async def cmd_balance(message: Message):
    """Show user's bonus balance"""
    user_id = message.from_user.id
    balance = await db.get_balance(user_id)
    await message.answer(f"💰 *Your balance:* ${balance:.2f}\n\nUse /referral to earn more.", parse_mode=ParseMode.MARKDOWN)

# ===================================================================
# Market Commands
# ===================================================================

@router.message(Command("price"))
async def cmd_price(message: Message):
    """Get current price for symbol"""
    args = message.text.split()
    symbol = args[1].upper() if len(args) > 1 else "BTC"
    if "/USDT" not in symbol and symbol not in ["BTC", "ETH", "SOL", "DOGE"]:
        symbol = symbol + "/USDT"
    elif symbol in ["BTC", "ETH", "SOL", "DOGE"]:
        symbol = symbol + "/USDT"
    
    await message.answer(f"📊 Fetching {symbol} price...")
    try:
        data = await market.get_full_market_data(symbol)
        price = data['current_price']
        change = data['change_24h_percent']
        change_emoji = "📈" if change >= 0 else "📉"
        text = (
            f"{change_emoji} *{symbol} Price*\n"
            f"Price: {format_price(price)}\n"
            f"24h Change: {change:+.2f}%\n"
            f"24h High: {format_price(data['high_24h'])}\n"
            f"24h Low: {format_price(data['low_24h'])}\n"
            f"24h Volume: ${format_large_number(data['volume_24h'])}"
        )
        await message.answer(text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await message.answer(f"Error fetching price: {e}")

@router.message(Command("market"))
async def cmd_market(message: Message):
    """Display market summary"""
    await message.answer("📊 Analyzing market...")
    try:
        summary = await market.get_market_summary()
        if not summary:
            await message.answer("Market data temporarily unavailable.")
            return
        
        text = (
            f"🌍 *Crypto Market Summary*\n\n"
            f"📈 Total coins: {summary.get('total_symbols', 0)}\n"
            f"💵 Total 24h volume: ${format_large_number(summary.get('total_volume_24h', 0))}\n"
            f"📊 Avg change: {summary.get('avg_change_percent', 0):+.2f}%\n"
            f"🎭 Sentiment: {summary.get('market_sentiment', 'neutral').upper()}\n\n"
            f"🔥 *Top Gainers:*\n"
        )
        for g in summary.get('top_gainers', [])[:3]:
            text += f"• {g['symbol']}: +{g['change']:.2f}%\n"
        text += f"\n📉 *Top Losers:*\n"
        for l in summary.get('top_losers', [])[:3]:
            text += f"• {l['symbol']}: {l['change']:.2f}%\n"
        
        await message.answer(text, parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await message.answer(f"Market summary error: {e}")

# ===================================================================
# News Commands
# ===================================================================

@router.message(Command("news"))
async def cmd_news(message: Message):
    """Display latest crypto news"""
    await message.answer("📰 Fetching latest crypto news...")
    try:
        summary = await news.get_news_summary(5)
        if not summary.get('articles'):
            await message.answer("No news available at the moment.")
            return
        
        text = f"📰 *Crypto News* (last {len(summary['articles'])} articles)\n\n"
        for i, article in enumerate(summary['articles'][:5], 1):
            sentiment_emoji = "🟢" if article.get('sentiment_score', 0) > 0.2 else "🔴" if article.get('sentiment_score', 0) < -0.2 else "⚪"
            title = escape_html(article['title'][:80])
            text += f"{i}. {sentiment_emoji} [{title}]({article['url']})\n"
        text += f"\n📊 Overall sentiment: {summary['sentiment']['average_score']:.2f}"
        await message.answer(text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    except Exception as e:
        await message.answer(f"News fetch error: {e}")

@router.message(Command("news_coin"))
async def cmd_news_coin(message: Message):
    """Get news for specific coin"""
    args = message.text.split()
    if len(args) < 2:
        await message.answer("Usage: /news_coin <symbol>\nExample: /news_coin ETH")
        return
    coin = args[1].upper()
    await message.answer(f"📰 News for {coin}...")
    try:
        articles = await news.get_news_by_coin(coin, 5)
        if not articles:
            await message.answer(f"No recent news for {coin}.")
            return
        text = f"📰 *{coin} News*\n\n"
        for i, art in enumerate(articles[:5], 1):
            title = escape_html(art['title'][:70])
            text += f"{i}. [{title}]({art['url']})\n"
        await message.answer(text, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    except Exception as e:
        await message.answer(f"Error: {e}")

# ===================================================================
# Support Commands
# ===================================================================

@router.message(Command("support"))
async def cmd_support(message: Message, state: FSMContext):
    """Open support ticket"""
    text = (
        "🆘 *Support*\n\n"
        "Send us your question or issue below. We'll respond within 24h.\n\n"
        "For urgent matters, contact admin directly."
    )
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)
    await state.set_state(SubscriptionStates.waiting_support_message)

@router.message(SubscriptionStates.waiting_support_message)
async def process_support_message(message: Message, state: FSMContext):
    """Process support ticket creation"""
    user_id = message.from_user.id
    subject = "Support request"
    msg_text = message.text
    
    ticket_id = await db.create_ticket(user_id, subject, msg_text)
    await message.answer(f"✅ Ticket #{ticket_id} created. We'll get back to you soon.")
    await state.clear()
    # Notify admins
    for admin_id in cfg.ADMIN_IDS:
        try:
            await message.bot.send_message(admin_id, f"🆘 New support ticket #{ticket_id}\nFrom: {user_id}\nMessage: {msg_text[:200]}")
        except:
            pass

# ===================================================================
# Feedback
# ===================================================================

@router.message(Command("feedback"))
async def cmd_feedback(message: Message, state: FSMContext):
    """Leave feedback"""
    await message.answer("💭 *Feedback*\n\nPlease share your thoughts, suggestions, or bug reports:\n(Type /cancel to cancel)", parse_mode=ParseMode.MARKDOWN)
    await state.set_state(SubscriptionStates.waiting_feedback)

@router.message(SubscriptionStates.waiting_feedback)
async def process_feedback(message: Message, state: FSMContext):
    """Save feedback"""
    user_id = message.from_user.id
    feedback_text = message.text
    await db.log_user_action(user_id, "feedback", feedback_text)
    await message.answer("✅ Thank you for your feedback! We appreciate it.")
    await state.clear()
    # Forward to admin
    for admin_id in cfg.ADMIN_IDS:
        try:
            await message.bot.send_message(admin_id, f"💬 Feedback from {user_id}:\n{feedback_text[:500]}")
        except:
            pass

# ===================================================================
# Help Command
# ===================================================================

@router.message(Command("help"))
async def cmd_help(message: Message):
    """Show help menu"""
    text = (
        "📖 *CryptoPulse AI Help*\n\n"
        "🤖 *Commands:*\n"
        "/start - Register / restart\n"
        "/menu - Main menu\n"
        "/signal - Get BTC signal\n"
        "/signal_custom <symbol> - Custom pair\n"
        "/price <symbol> - Current price\n"
        "/market - Market summary\n"
        "/news - Latest crypto news\n"
        "/news_coin <coin> - Coin-specific news\n"
        "/subscribe - Buy premium\n"
        "/referral - Invite friends\n"
        "/balance - Check bonus balance\n"
        "/profile - Your profile\n"
        "/support - Contact support\n"
        "/feedback - Send feedback\n"
        "/help - This menu\n\n"
        "💰 *Premium Benefits:*\n"
        "• Unlimited AI signals\n"
        "• Real-time data\n"
        "• Priority support\n\n"
        "❓ Questions? /support"
    )
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

# ===================================================================
# Cancel handler for FSM
# ===================================================================

@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext):
    """Cancel active state"""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("Nothing to cancel.")
        return
    await state.clear()
    await message.answer("✅ Operation cancelled.")

# ===================================================================
# Error handler for unknown messages (optional)
# ===================================================================

@router.message()
async def handle_unknown(message: Message):
    """Fallback for unknown messages"""
    await message.answer("❓ Unknown command. Use /help for available commands.")

@router.message(Command("app"))
async def cmd_webapp(message: Message):
    """Открыть мини-приложение"""
    user_id = message.from_user.id
    webapp_url = "https://your-domain.com/cryptopulse"  # Замени на свой HTTPS домен, где хостится index.html
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 Open CryptoPulse App", web_app={"url": webapp_url})]
    ])
    await message.answer(
        "🌟 *CryptoPulse AI Mini App*\n\n"
        "Advanced trading signals, charts, and profile management.\n"
        "Click below to launch:",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=keyboard
    )

@router.message(Command("app"))
async def open_miniapp(message: Message):
    webapp_url = "https://ТВОЙ-ДОМЕН/cryptopulse/index.html"  # замени на реальный HTTPS URL
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🚀 OPEN ULTIMATE TERMINAL", web_app={"url": webapp_url})]
    ])
    await message.answer("🔥 *CryptoPulse AI Ultimate Terminal*\n\nТоп-графики, AI-сигналы, портфель — всё в одном месте.", parse_mode="Markdown", reply_markup=kb)

# ===================================================================
# Export router
# ===================================================================

__all__ = ["router"]