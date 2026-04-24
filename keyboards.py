from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from typing import List, Optional, Dict, Any

from config import get_config

cfg = get_config()

# ===================================================================
# Main Menu Keyboard
# ===================================================================

def get_main_menu_keyboard(user_id: int = None, has_subscription: bool = None) -> InlineKeyboardMarkup:
    """
    Main navigation menu.
    If subscription status provided, shows premium features accordingly.
    """
    builder = InlineKeyboardBuilder()
    
    # Row 1: Signal & Price
    builder.row(
        InlineKeyboardButton(text="📈 Signal (BTC)", callback_data="signal_btc"),
        InlineKeyboardButton(text="💰 Price Check", callback_data="price_menu")
    )
    
    # Row 2: Market & News
    builder.row(
        InlineKeyboardButton(text="🌍 Market Summary", callback_data="market_summary"),
        InlineKeyboardButton(text="📰 Crypto News", callback_data="news_menu")
    )
    
    # Row 3: Subscription & Referral
    builder.row(
        InlineKeyboardButton(text="💎 Subscribe", callback_data="subscribe"),
        InlineKeyboardButton(text="👥 Referral", callback_data="referral")
    )
    
    # Row 4: Profile & Help
    builder.row(
        InlineKeyboardButton(text="👤 Profile", callback_data="profile"),
        InlineKeyboardButton(text="❓ Help", callback_data="help")
    )
    
    # Row 5: Settings & Support (if user has subscription, show extra features)
    builder.row(
        InlineKeyboardButton(text="⚙️ Settings", callback_data="settings"),
        InlineKeyboardButton(text="🆘 Support", callback_data="support")
    )
    
    # Optional: Premium badge if subscribed
    if has_subscription:
        builder.row(
            InlineKeyboardButton(text="⭐ Premium Active ⭐", callback_data="noop",)
        )
    
    return builder.as_markup()

# ===================================================================
# Subscription Keyboard
# ===================================================================

def get_subscription_keyboard(price_usd: float = None, days: int = None) -> InlineKeyboardMarkup:
    """Payment options keyboard"""
    if price_usd is None:
        price_usd = cfg.SUBSCRIPTION_PRICE_USD
    if days is None:
        days = cfg.SUBSCRIPTION_DAYS
    
    builder = InlineKeyboardBuilder()
    
    # Crypto payment options
    builder.row(
        InlineKeyboardButton(text=f"💳 Pay {price_usd} USDT", callback_data="pay_cryptobot"),
        InlineKeyboardButton(text="🔄 Binance Pay", callback_data="pay_binance")
    )
    
    builder.row(
        InlineKeyboardButton(text="💰 Manual Payment (USDT)", callback_data="pay_manual")
    )
    
    builder.row(
        InlineKeyboardButton(text="🎁 Redeem Promo Code", callback_data="redeem_promo")
    )
    
    builder.row(
        InlineKeyboardButton(text="🔙 Back to Menu", callback_data="main_menu")
    )
    
    return builder.as_markup()

def get_payment_method_keyboard() -> InlineKeyboardMarkup:
    """Choose payment method"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🤖 CryptoBot", callback_data="pay_cryptobot"),
        InlineKeyboardButton(text="📦 Binance Pay", callback_data="pay_binance"),
        InlineKeyboardButton(text="📝 Manual (Admin verify)", callback_data="pay_manual")
    )
    builder.row(InlineKeyboardButton(text="🔙 Back", callback_data="subscribe"))
    return builder.as_markup()

# ===================================================================
# Referral Keyboard
# ===================================================================

def get_referral_keyboard() -> InlineKeyboardMarkup:
    """Referral program actions"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📋 Copy Referral Link", callback_data="copy_ref_link"),
        InlineKeyboardButton(text="💰 Withdraw Bonus", callback_data="withdraw")
    )
    builder.row(
        InlineKeyboardButton(text="📊 Referral Stats", callback_data="ref_stats"),
        InlineKeyboardButton(text="🏆 Leaderboard", callback_data="ref_leaderboard")
    )
    builder.row(InlineKeyboardButton(text="🔙 Back to Menu", callback_data="main_menu"))
    return builder.as_markup()

# ===================================================================
# Settings Keyboard
# ===================================================================

def get_settings_keyboard() -> InlineKeyboardMarkup:
    """User settings options"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🌐 Language", callback_data="settings_language"),
        InlineKeyboardButton(text="🔔 Notifications", callback_data="settings_notifications")
    )
    builder.row(
        InlineKeyboardButton(text="📊 Default Symbol", callback_data="settings_default_symbol"),
        InlineKeyboardButton(text="⏰ Signal Time", callback_data="settings_signal_time")
    )
    builder.row(
        InlineKeyboardButton(text="🗑 Delete My Data", callback_data="settings_delete_data")
    )
    builder.row(InlineKeyboardButton(text="🔙 Back to Menu", callback_data="main_menu"))
    return builder.as_markup()

def get_language_keyboard(current_lang: str = "en") -> InlineKeyboardMarkup:
    """Language selection keyboard"""
    languages = {
        "en": "🇬🇧 English",
        "ru": "🇷🇺 Русский",
        "es": "🇪🇸 Español",
        "de": "🇩🇪 Deutsch",
        "fr": "🇫🇷 Français",
        "zh": "🇨🇳 中文",
        "tr": "🇹🇷 Türkçe",
        "ar": "🇸🇦 العربية"
    }
    builder = InlineKeyboardBuilder()
    for code, name in languages.items():
        indicator = " ✅" if code == current_lang else ""
        builder.row(InlineKeyboardButton(text=f"{name}{indicator}", callback_data=f"set_lang_{code}"))
    builder.row(InlineKeyboardButton(text="🔙 Back", callback_data="settings"))
    return builder.as_markup()

def get_notification_keyboard(notifications_enabled: bool = True) -> InlineKeyboardMarkup:
    """Toggle notifications"""
    builder = InlineKeyboardBuilder()
    status = "✅ Enabled" if notifications_enabled else "❌ Disabled"
    builder.row(InlineKeyboardButton(text=f"Toggle Notifications ({status})", callback_data="toggle_notifications"))
    builder.row(InlineKeyboardButton(text="🔙 Back to Settings", callback_data="settings"))
    return builder.as_markup()

def get_default_symbol_keyboard(current_symbol: str = "BTC/USDT") -> InlineKeyboardMarkup:
    """Select default trading pair"""
    symbols = cfg.get_symbols_as_list()[:12]  # Limit to 12 for keyboard
    builder = InlineKeyboardBuilder()
    for sym in symbols:
        indicator = " ✅" if sym == current_symbol else ""
        builder.row(InlineKeyboardButton(text=f"{sym}{indicator}", callback_data=f"set_default_symbol_{sym}"))
    builder.row(InlineKeyboardButton(text="🔙 Back", callback_data="settings"))
    return builder.as_markup()

# ===================================================================
# News & Market Keyboards
# ===================================================================

def get_news_keyboard() -> InlineKeyboardMarkup:
    """News menu options"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📰 Latest News", callback_data="news_latest"),
        InlineKeyboardButton(text="🪙 News by Coin", callback_data="news_by_coin")
    )
    builder.row(
        InlineKeyboardButton(text="📊 Market Sentiment", callback_data="market_sentiment"),
        InlineKeyboardButton(text="🔍 Trending Topics", callback_data="news_trending")
    )
    builder.row(InlineKeyboardButton(text="🔙 Main Menu", callback_data="main_menu"))
    return builder.as_markup()

def get_price_keyboard(symbol: str = "BTC/USDT") -> InlineKeyboardMarkup:
    """Price submenu with quick symbols"""
    quick_symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "DOGE/USDT", "BNB/USDT", "XRP/USDT"]
    builder = InlineKeyboardBuilder()
    row = []
    for sym in quick_symbols[:3]:
        builder.add(InlineKeyboardButton(text=sym.split('/')[0], callback_data=f"price_{sym}"))
    builder.adjust(3)
    for sym in quick_symbols[3:]:
        builder.add(InlineKeyboardButton(text=sym.split('/')[0], callback_data=f"price_{sym}"))
    builder.adjust(3)
    builder.row(InlineKeyboardButton(text="🔍 Custom Symbol", callback_data="price_custom"))
    builder.row(InlineKeyboardButton(text="🔙 Back", callback_data="main_menu"))
    return builder.as_markup()

# ===================================================================
# Pagination Keyboard
# ===================================================================

def get_pagination_keyboard(page: int, total_pages: int, prefix: str = "page") -> InlineKeyboardMarkup:
    """Generic pagination keyboard"""
    builder = InlineKeyboardBuilder()
    if page > 1:
        builder.add(InlineKeyboardButton(text="◀️ Prev", callback_data=f"{prefix}_{page-1}"))
    if page < total_pages:
        builder.add(InlineKeyboardButton(text="Next ▶️", callback_data=f"{prefix}_{page+1}"))
    builder.row(InlineKeyboardButton(text=f"📄 {page}/{total_pages}", callback_data="noop"))
    builder.row(InlineKeyboardButton(text="🔙 Back", callback_data="main_menu"))
    return builder.as_markup()

def get_signal_history_keyboard(page: int, total_pages: int) -> InlineKeyboardMarkup:
    """Signal history pagination"""
    return get_pagination_keyboard(page, total_pages, prefix="signal_history")

# ===================================================================
# Confirmation Dialogs
# ===================================================================

def get_confirmation_keyboard(action: str, item_id: str = None) -> InlineKeyboardMarkup:
    """Yes/No confirmation dialog"""
    builder = InlineKeyboardBuilder()
    confirm_callback = f"confirm_{action}"
    if item_id:
        confirm_callback = f"confirm_{action}_{item_id}"
    builder.row(
        InlineKeyboardButton(text="✅ Yes", callback_data=confirm_callback),
        InlineKeyboardButton(text="❌ No", callback_data="cancel")
    )
    return builder.as_markup()

def get_delete_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Special delete account confirmation"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⚠️ YES, DELETE MY DATA", callback_data="confirm_delete_account"),
        InlineKeyboardButton(text="🔙 Cancel", callback_data="settings")
    )
    return builder.as_markup()

# ===================================================================
# Admin Keyboards
# ===================================================================

def get_admin_main_keyboard() -> InlineKeyboardMarkup:
    """Admin panel main menu (used in admin_panel.py, defined here for completeness)"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📢 Broadcast", callback_data="admin_broadcast"),
        InlineKeyboardButton(text="👥 User Management", callback_data="admin_user_mgmt")
    )
    builder.row(
        InlineKeyboardButton(text="💰 Payments", callback_data="admin_payment_mgmt"),
        InlineKeyboardButton(text="📊 Stats", callback_data="admin_stats")
    )
    builder.row(
        InlineKeyboardButton(text="🩺 System Health", callback_data="admin_health"),
        InlineKeyboardButton(text="📜 Logs", callback_data="admin_logs")
    )
    builder.row(
        InlineKeyboardButton(text="💾 Backup", callback_data="admin_backup"),
        InlineKeyboardButton(text="⚙️ Config", callback_data="admin_config")
    )
    builder.row(InlineKeyboardButton(text="❌ Close", callback_data="admin_close"))
    return builder.as_markup()

def get_user_management_keyboard() -> InlineKeyboardMarkup:
    """User management submenu"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="🔍 Lookup User", callback_data="admin_lookup_user"),
        InlineKeyboardButton(text="➕ Add Balance", callback_data="admin_add_balance")
    )
    builder.row(
        InlineKeyboardButton(text="🚫 Ban User", callback_data="admin_ban_user"),
        InlineKeyboardButton(text="✅ Unban User", callback_data="admin_unban_user")
    )
    builder.row(
        InlineKeyboardButton(text="🎁 Give Subscription", callback_data="admin_give_subscription"),
        InlineKeyboardButton(text="📊 Export Users", callback_data="admin_export_users")
    )
    builder.row(InlineKeyboardButton(text="🔙 Back to Admin", callback_data="admin_main"))
    return builder.as_markup()

def get_payment_management_keyboard() -> InlineKeyboardMarkup:
    """Payment management submenu"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="💳 Pending Payments", callback_data="admin_pending_payments"),
        InlineKeyboardButton(text="✅ Verify Payment", callback_data="admin_verify_payment")
    )
    builder.row(
        InlineKeyboardButton(text="📈 Revenue Stats", callback_data="admin_revenue_stats"),
        InlineKeyboardButton(text="🔄 Refund", callback_data="admin_refund")
    )
    builder.row(InlineKeyboardButton(text="🔙 Back to Admin", callback_data="admin_main"))
    return builder.as_markup()

# ===================================================================
# Signal Type Selection
# ===================================================================

def get_signal_type_keyboard() -> InlineKeyboardMarkup:
    """Choose signal type (quick, detailed, advanced)"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="⚡ Quick Signal", callback_data="signal_quick"),
        InlineKeyboardButton(text="📊 Detailed Signal", callback_data="signal_detailed")
    )
    builder.row(
        InlineKeyboardButton(text="🎯 Advanced (TA + AI)", callback_data="signal_advanced"),
        InlineKeyboardButton(text="🕒 Historical", callback_data="signal_history")
    )
    builder.row(InlineKeyboardButton(text="🔙 Back", callback_data="main_menu"))
    return builder.as_markup()

# ===================================================================
# Inline Query Results (for inline mode)
# ===================================================================

def get_inline_signal_result(symbol: str, price: float, change: float, signal: str) -> Dict[str, Any]:
    """Build inline query result for signal preview"""
    return {
        "type": "article",
        "id": f"signal_{symbol}_{int(time.time())}",
        "title": f"{symbol} Signal: {signal}",
        "description": f"Price: ${price:.2f} | 24h: {change:+.2f}%",
        "input_message_content": {
            "message_text": f"📈 *{symbol} Signal*\n\nAction: *{signal}*\nPrice: ${price:.2f}\nConfidence: High",
            "parse_mode": "Markdown"
        },
        "reply_markup": get_signal_detail_keyboard(symbol)
    }

def get_signal_detail_keyboard(symbol: str) -> InlineKeyboardMarkup:
    """Keyboard for inline signal result"""
    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(text="📊 Full Analysis", callback_data=f"analyze_{symbol}"),
        InlineKeyboardButton(text="💰 Buy / Sell", callback_data=f"trade_{symbol}")
    )
    return builder.as_markup()

# ===================================================================
# Reply Keyboards (for user input)
# ===================================================================

def get_cancel_reply_keyboard() -> ReplyKeyboardMarkup:
    """Reply keyboard with Cancel button"""
    builder = ReplyKeyboardBuilder()
    builder.add(KeyboardButton(text="❌ Cancel"))
    return builder.as_markup(resize_keyboard=True)

def get_main_reply_keyboard() -> ReplyKeyboardMarkup:
    """Main reply keyboard for quick actions (optional)"""
    builder = ReplyKeyboardBuilder()
    builder.row(
        KeyboardButton(text="📈 Signal"),
        KeyboardButton(text="💰 Price"),
        KeyboardButton(text="🌍 Market")
    )
    builder.row(
        KeyboardButton(text="📰 News"),
        KeyboardButton(text="👤 Profile"),
        KeyboardButton(text="❓ Help")
    )
    return builder.as_markup(resize_keyboard=True)

# ===================================================================
# WebApp Keyboard (if using Telegram Web Apps)
# ===================================================================

def get_webapp_keyboard(webapp_url: str) -> InlineKeyboardMarkup:
    """Keyboard that opens a Web App"""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🚀 Open Trading Terminal", web_app={"url": webapp_url}))
    return builder.as_markup()

# ===================================================================
# Back Button (simple)
# ===================================================================

def get_back_button(callback_data: str = "main_menu") -> InlineKeyboardMarkup:
    """Simple back button to navigate up"""
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🔙 Back", callback_data=callback_data))
    return builder.as_markup()

# ===================================================================
# Utility to create dynamic keyboard from list
# ===================================================================

def create_keyboard_from_list(items: List[str], callback_prefix: str, columns: int = 2) -> InlineKeyboardMarkup:
    """
    Generate dynamic inline keyboard from a list of items.
    Each button's callback data becomes f"{callback_prefix}_{item}"
    """
    builder = InlineKeyboardBuilder()
    for item in items:
        builder.add(InlineKeyboardButton(text=item, callback_data=f"{callback_prefix}_{item}"))
    builder.adjust(columns)
    return builder.as_markup()

# ===================================================================
# Export
# ===================================================================

__all__ = [
    "get_main_menu_keyboard",
    "get_subscription_keyboard",
    "get_payment_method_keyboard",
    "get_referral_keyboard",
    "get_settings_keyboard",
    "get_language_keyboard",
    "get_notification_keyboard",
    "get_default_symbol_keyboard",
    "get_news_keyboard",
    "get_price_keyboard",
    "get_pagination_keyboard",
    "get_signal_history_keyboard",
    "get_confirmation_keyboard",
    "get_delete_confirmation_keyboard",
    "get_admin_main_keyboard",
    "get_user_management_keyboard",
    "get_payment_management_keyboard",
    "get_signal_type_keyboard",
    "get_inline_signal_result",
    "get_cancel_reply_keyboard",
    "get_main_reply_keyboard",
    "get_webapp_keyboard",
    "get_back_button",
    "create_keyboard_from_list"
]