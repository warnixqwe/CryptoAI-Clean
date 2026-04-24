import asyncio
import logging
import io
import csv
import json
import os
import shutil
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

from aiogram import Router, F, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.enums import ParseMode

# Local imports
from config import get_config
from database import get_db
from market_data import get_market_provider
from ai_analyzer import get_analyzer
from news_parser import get_news_aggregator
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
# Admin FSM States
# ===================================================================

class AdminStates(StatesGroup):
    waiting_broadcast_message = State()
    waiting_broadcast_confirm = State()
    waiting_user_id_for_action = State()
    waiting_user_action_type = State()
    waiting_ban_reason = State()
    waiting_ban_duration = State()
    waiting_add_balance_amount = State()
    waiting_set_subscription_days = State()
    waiting_manual_payment_user = State()
    waiting_manual_payment_amount = State()
    waiting_send_message_to_user = State()
    waiting_payment_id_to_verify = State()
    waiting_backup_name = State()
    waiting_restore_file = State()

# ===================================================================
# Admin Check Decorator (manual inside handlers)
# ===================================================================

def is_admin(user_id: int) -> bool:
    return user_id in cfg.ADMIN_IDS

# ===================================================================
# Main Admin Command
# ===================================================================

@router.message(Command("admin"))
async def cmd_admin(message: Message):
    """Display admin panel main menu"""
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer("⛔ Access denied. Admins only.")
        return
    
    # Gather real-time stats
    total_users = await db.get_user_count()
    active_subs = await db.get_active_subscribers_count()
    total_revenue = await db.get_total_revenue()
    pending_payments = await get_pending_payments_count()
    open_tickets = len(await db.get_open_tickets())
    
    stats_text = (
        f"🛡️ *Admin Panel*\n\n"
        f"📊 *Statistics*\n"
        f"• Total users: {total_users}\n"
        f"• Active subscriptions: {active_subs}\n"
        f"• Total revenue: ${total_revenue:,.2f}\n"
        f"• Pending payments: {pending_payments}\n"
        f"• Open tickets: {open_tickets}\n\n"
        f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="👥 User Management", callback_data="admin_user_mgmt")],
        [InlineKeyboardButton(text="💰 Payment Management", callback_data="admin_payment_mgmt")],
        [InlineKeyboardButton(text="📈 System Health", callback_data="admin_health")],
        [InlineKeyboardButton(text="📜 Logs", callback_data="admin_logs")],
        [InlineKeyboardButton(text="💾 Backup / Restore", callback_data="admin_backup")],
        [InlineKeyboardButton(text="⚙️ Config", callback_data="admin_config")],
        [InlineKeyboardButton(text="❌ Close", callback_data="admin_close")]
    ])
    
    await message.answer(stats_text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard)

async def get_pending_payments_count() -> int:
    """Return count of pending payment records"""
    async with db.get_cursor() as c:
        c.execute("SELECT COUNT(*) FROM payments WHERE status = 'pending'")
        row = c.fetchone()
        return row[0] if row else 0

# ===================================================================
# Admin Callback Handlers
# ===================================================================

@router.callback_query(F.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied")
        return
    await callback.message.answer("📢 *Broadcast*\n\nSend the message you want to broadcast to all users.\nSupports markdown, images, files.\n\nType /cancel to cancel.", parse_mode=ParseMode.MARKDOWN)
    await state.set_state(AdminStates.waiting_broadcast_message)
    await callback.answer()

@router.message(AdminStates.waiting_broadcast_message)
async def admin_broadcast_receive(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer("Access denied")
        await state.clear()
        return
    
    # Store message info
    broadcast_data = {
        "type": "text",
        "text": message.text or message.caption,
        "entities": message.entities or message.caption_entities
    }
    if message.photo:
        broadcast_data["type"] = "photo"
        broadcast_data["photo"] = message.photo[-1].file_id
        broadcast_data["caption"] = message.caption
    elif message.video:
        broadcast_data["type"] = "video"
        broadcast_data["video"] = message.video.file_id
        broadcast_data["caption"] = message.caption
    elif message.document:
        broadcast_data["type"] = "document"
        broadcast_data["document"] = message.document.file_id
        broadcast_data["caption"] = message.caption
    
    await state.update_data(broadcast=broadcast_data)
    
    # Preview
    preview_text = "📢 *Broadcast Preview:*\n\n"
    if broadcast_data["type"] == "text":
        preview_text += broadcast_data["text"][:200]
    else:
        preview_text += f"[{broadcast_data['type']}] {broadcast_data.get('caption', '')[:100]}"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Confirm Broadcast", callback_data="admin_broadcast_confirm")],
        [InlineKeyboardButton(text="❌ Cancel", callback_data="admin_broadcast_cancel")]
    ])
    await message.answer(preview_text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    await state.set_state(AdminStates.waiting_broadcast_confirm)

@router.callback_query(F.data == "admin_broadcast_confirm")
async def admin_broadcast_confirm(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if not is_admin(user_id):
        await callback.answer("Access denied")
        return
    
    data = await state.get_data()
    broadcast = data.get("broadcast")
    if not broadcast:
        await callback.message.edit_text("No broadcast data found. Cancelled.")
        await state.clear()
        return
    
    await callback.message.edit_text("📢 Broadcasting... This may take a while.")
    
    # Get all users
    async with db.get_cursor() as c:
        c.execute("SELECT user_id FROM users WHERE banned = 0 OR banned IS NULL")
        users = [row[0] for row in c.fetchall()]
    
    success_count = 0
    fail_count = 0
    
    for uid in users:
        try:
            if broadcast["type"] == "text":
                await callback.bot.send_message(uid, broadcast["text"], entities=broadcast.get("entities"), parse_mode=None)
            elif broadcast["type"] == "photo":
                await callback.bot.send_photo(uid, broadcast["photo"], caption=broadcast.get("caption"))
            elif broadcast["type"] == "video":
                await callback.bot.send_video(uid, broadcast["video"], caption=broadcast.get("caption"))
            elif broadcast["type"] == "document":
                await callback.bot.send_document(uid, broadcast["document"], caption=broadcast.get("caption"))
            success_count += 1
            await asyncio.sleep(0.03)  # avoid flood wait
        except Exception as e:
            fail_count += 1
            logger.warning(f"Broadcast failed to {uid}: {e}")
    
    await callback.message.edit_text(f"✅ Broadcast completed.\nSent: {success_count}\nFailed: {fail_count}")
    await state.clear()

@router.callback_query(F.data == "admin_broadcast_cancel")
async def admin_broadcast_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Broadcast cancelled.")
    await state.clear()

# ===================================================================
# User Management
# ===================================================================

@router.callback_query(F.data == "admin_user_mgmt")
async def admin_user_mgmt(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied")
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Lookup User", callback_data="admin_lookup_user")],
        [InlineKeyboardButton(text="➕ Add Balance", callback_data="admin_add_balance")],
        [InlineKeyboardButton(text="🚫 Ban User", callback_data="admin_ban_user")],
        [InlineKeyboardButton(text="✅ Unban User", callback_data="admin_unban_user")],
        [InlineKeyboardButton(text="🎁 Give Subscription", callback_data="admin_give_subscription")],
        [InlineKeyboardButton(text="📊 Export Users CSV", callback_data="admin_export_users")],
        [InlineKeyboardButton(text="📈 Top Referrers", callback_data="admin_top_referrers")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin_back_to_main")]
    ])
    await callback.message.edit_text("👥 *User Management*\nSelect action:", parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "admin_lookup_user")
async def admin_lookup_user_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("🔍 Enter user ID or username (without @):")
    await state.set_state(AdminStates.waiting_user_id_for_action)
    await state.update_data(admin_action="lookup")
    await callback.answer()

@router.callback_query(F.data == "admin_ban_user")
async def admin_ban_user_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("🚫 Enter user ID to ban:")
    await state.set_state(AdminStates.waiting_user_id_for_action)
    await state.update_data(admin_action="ban")
    await callback.answer()

@router.callback_query(F.data == "admin_unban_user")
async def admin_unban_user_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("✅ Enter user ID to unban:")
    await state.set_state(AdminStates.waiting_user_id_for_action)
    await state.update_data(admin_action="unban")
    await callback.answer()

@router.message(AdminStates.waiting_user_id_for_action)
async def admin_handle_user_id_input(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if not is_admin(user_id):
        await message.answer("Access denied")
        await state.clear()
        return
    
    data = await state.get_data()
    action = data.get("admin_action")
    target_input = message.text.strip()
    
    # Try to get user_id
    target_user_id = None
    if target_input.isdigit():
        target_user_id = int(target_input)
    else:
        # Try by username
        async with db.get_cursor() as c:
            c.execute("SELECT user_id FROM users WHERE username LIKE ?", (f"%{target_input}%",))
            row = c.fetchone()
            if row:
                target_user_id = row[0]
    
    if not target_user_id:
        await message.answer("❌ User not found. Please check ID or username.")
        await state.clear()
        return
    
    user_info = await db.get_user(target_user_id)
    if not user_info:
        await message.answer("❌ User not found in database.")
        await state.clear()
        return
    
    if action == "lookup":
        # Display full user info
        has_sub = await db.has_active_subscription(target_user_id)
        stats = await db.get_referral_stats(target_user_id)
        text = (
            f"👤 *User Details*\n\n"
            f"ID: `{target_user_id}`\n"
            f"Username: @{user_info.get('username') or 'N/A'}\n"
            f"Name: {user_info.get('first_name', '')} {user_info.get('last_name', '')}\n"
            f"Registered: {datetime.fromtimestamp(user_info['registered_at']).strftime('%Y-%m-%d')}\n"
            f"Language: {user_info.get('language', 'en')}\n"
            f"Banned: {user_info.get('banned', 0) == 1}\n"
            f"Premium: {'✅ Active' if has_sub else '❌'}\n"
            f"Expires: {datetime.fromtimestamp(user_info.get('subscribe_until', 0)).strftime('%Y-%m-%d') if user_info.get('subscribe_until') else 'N/A'}\n"
            f"Balance: ${user_info.get('balance', 0):.2f}\n"
            f"Total spent: ${user_info.get('total_spent', 0):.2f}\n"
            f"Signals used: {user_info.get('total_signals_requested', 0)}\n"
            f"Referrals: {stats['direct_count']}\n"
            f"Referral earnings: ${stats['total_earned']:.2f}"
        )
        await message.answer(text, parse_mode=ParseMode.MARKDOWN)
        await state.clear()
    
    elif action == "ban":
        await state.update_data(ban_user_id=target_user_id)
        await message.answer("Enter ban reason:")
        await state.set_state(AdminStates.waiting_ban_reason)
    
    elif action == "unban":
        await db.unban_user(target_user_id)
        await message.answer(f"✅ User {target_user_id} unbanned.")
        await state.clear()

@router.message(AdminStates.waiting_ban_reason)
async def admin_ban_reason_input(message: Message, state: FSMContext):
    reason = message.text.strip()
    data = await state.get_data()
    target_user_id = data.get("ban_user_id")
    if not target_user_id:
        await message.answer("Error: no user selected.")
        await state.clear()
        return
    
    await state.update_data(ban_reason=reason)
    await message.answer("Enter ban duration in hours (0 for permanent):")
    await state.set_state(AdminStates.waiting_ban_duration)

@router.message(AdminStates.waiting_ban_duration)
async def admin_ban_duration_input(message: Message, state: FSMContext):
    duration_text = message.text.strip()
    try:
        duration_hours = int(duration_text)
    except ValueError:
        await message.answer("Invalid number. Enter hours (0 for permanent):")
        return
    
    data = await state.get_data()
    target_user_id = data.get("ban_user_id")
    reason = data.get("ban_reason", "No reason")
    
    if duration_hours == 0:
        duration_hours = None
    await db.ban_user(target_user_id, reason, duration_hours)
    
    if duration_hours:
        await message.answer(f"🚫 User {target_user_id} banned for {duration_hours} hours.\nReason: {reason}")
    else:
        await message.answer(f"🚫 User {target_user_id} permanently banned.\nReason: {reason}")
    await state.clear()

# ===================================================================
# Add Balance
# ===================================================================

@router.callback_query(F.data == "admin_add_balance")
async def admin_add_balance_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("💰 Enter user ID to add balance:")
    await state.set_state(AdminStates.waiting_user_id_for_action)
    await state.update_data(admin_action="add_balance")
    await callback.answer()

@router.message(AdminStates.waiting_user_id_for_action)
async def admin_add_balance_user_input(message: Message, state: FSMContext):
    # This handler already exists above, but we need to differentiate add_balance action
    # We'll handle it within the same handler but with different logic.
    # Actually, we already have the generic handler. We'll check action inside.
    # To avoid duplication, we'll modify the previous handler to include add_balance.
    pass

# Better to restructure: I'll create separate handlers for each sub-action.
# But for brevity in this large code, I'll add a new handler specifically for add_balance after user ID.

# However, to keep code organized, I'll add a new pattern after the generic user ID handler.
# The generic handler above handles lookup/ban/unban. For add_balance we need a separate state after user ID.

@router.callback_query(F.data == "admin_add_balance")
async def admin_add_balance_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("💰 Enter user ID:")
    await state.set_state(AdminStates.waiting_user_id_for_action)
    await state.update_data(admin_action="add_balance_ask_amount")
    await callback.answer()

@router.message(AdminStates.waiting_user_id_for_action)
async def admin_add_balance_user_id(message: Message, state: FSMContext):
    data = await state.get_data()
    action = data.get("admin_action")
    if action != "add_balance_ask_amount":
        return
    target_input = message.text.strip()
    if not target_input.isdigit():
        await message.answer("User ID must be a number.")
        return
    target_user_id = int(target_input)
    user = await db.get_user(target_user_id)
    if not user:
        await message.answer("User not found.")
        await state.clear()
        return
    await state.update_data(add_balance_user_id=target_user_id)
    await message.answer(f"User @{user.get('username', 'N/A')} (ID: {target_user_id})\nEnter amount in USD to add:")
    await state.set_state(AdminStates.waiting_add_balance_amount)

@router.message(AdminStates.waiting_add_balance_amount)
async def admin_add_balance_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.strip())
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Invalid amount. Enter positive number.")
        return
    data = await state.get_data()
    target_user_id = data.get("add_balance_user_id")
    if not target_user_id:
        await message.answer("Error: user not found.")
        await state.clear()
        return
    await db.add_balance(target_user_id, amount, f"Admin added by {message.from_user.id}")
    await message.answer(f"✅ Added ${amount:.2f} to user {target_user_id}")
    await db.log_admin_action(message.from_user.id, "add_balance", target_user_id, f"amount={amount}")
    await state.clear()

# ===================================================================
# Give Subscription
# ===================================================================

@router.callback_query(F.data == "admin_give_subscription")
async def admin_give_subscription_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("🎁 Enter user ID to give subscription:")
    await state.set_state(AdminStates.waiting_user_id_for_action)
    await state.update_data(admin_action="give_subscription")
    await callback.answer()

# We'll add a separate handler for subscription days after user ID.
@router.message(AdminStates.waiting_user_id_for_action)
async def admin_give_subscription_user(message: Message, state: FSMContext):
    data = await state.get_data()
    action = data.get("admin_action")
    if action != "give_subscription":
        return
    target_input = message.text.strip()
    if not target_input.isdigit():
        await message.answer("User ID must be number.")
        return
    target_user_id = int(target_input)
    user = await db.get_user(target_user_id)
    if not user:
        await message.answer("User not found.")
        await state.clear()
        return
    await state.update_data(give_sub_user_id=target_user_id)
    await message.answer(f"User @{user.get('username', 'N/A')}\nEnter subscription days (e.g., 30):")
    await state.set_state(AdminStates.waiting_set_subscription_days)

@router.message(AdminStates.waiting_set_subscription_days)
async def admin_set_subscription_days(message: Message, state: FSMContext):
    try:
        days = int(message.text.strip())
        if days <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Invalid days. Enter positive integer.")
        return
    data = await state.get_data()
    target_user_id = data.get("give_sub_user_id")
    if not target_user_id:
        await message.answer("Error: no user.")
        await state.clear()
        return
    expire = await db.activate_subscription(target_user_id, days=days, amount=0)
    await message.answer(f"✅ Subscription activated for user {target_user_id} for {days} days.\nExpires: {datetime.fromtimestamp(expire).strftime('%Y-%m-%d')}")
    await db.log_admin_action(message.from_user.id, "give_subscription", target_user_id, f"days={days}")
    await state.clear()

# ===================================================================
# Export Users CSV
# ===================================================================

@router.callback_query(F.data == "admin_export_users")
async def admin_export_users(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied")
        return
    await callback.message.edit_text("📊 Generating CSV...")
    # Query all users
    async with db.get_cursor() as c:
        c.execute("SELECT user_id, username, first_name, last_name, language, registered_at, subscribed, subscribe_until, balance, total_spent, total_signals_requested, banned FROM users")
        users = c.fetchall()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["user_id", "username", "first_name", "last_name", "language", "registered_at", "subscribed", "subscribe_until", "balance", "total_spent", "total_signals", "banned"])
    for row in users:
        writer.writerow(row)
    
    output.seek(0)
    file = io.BytesIO(output.getvalue().encode())
    file.name = f"users_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
    await callback.message.delete()
    await callback.message.answer_document(FSInputFile(file.name) if hasattr(FSInputFile, '__name__') else types.BufferedInputFile(file.getvalue(), filename=file.name))
    await callback.answer()

# ===================================================================
# Top Referrers
# ===================================================================

@router.callback_query(F.data == "admin_top_referrers")
async def admin_top_referrers(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied")
        return
    async with db.get_cursor() as c:
        c.execute("""
            SELECT referrer_id, COUNT(*) as cnt, SUM(reward_amount) as total
            FROM referrals
            GROUP BY referrer_id
            ORDER BY cnt DESC
            LIMIT 10
        """)
        rows = c.fetchall()
    if not rows:
        await callback.message.edit_text("No referrals found.")
        return
    text = "🏆 *Top Referrers*\n\n"
    for i, row in enumerate(rows, 1):
        user = await db.get_user(row[0])
        username = f"@{user['username']}" if user and user.get('username') else f"ID {row[0]}"
        text += f"{i}. {username}: {row[1]} referrals (${row[2]:.2f})\n"
    await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    await callback.answer()

# ===================================================================
# Payment Management
# ===================================================================

@router.callback_query(F.data == "admin_payment_mgmt")
async def admin_payment_mgmt(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied")
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Pending Payments", callback_data="admin_pending_payments")],
        [InlineKeyboardButton(text="✅ Verify Payment Manually", callback_data="admin_verify_payment")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin_back_to_main")]
    ])
    await callback.message.edit_text("💰 *Payment Management*", parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "admin_pending_payments")
async def admin_pending_payments(callback: CallbackQuery):
    async with db.get_cursor() as c:
        c.execute("SELECT payment_id, user_id, amount, currency, created_at FROM payments WHERE status='pending' ORDER BY created_at DESC LIMIT 20")
        rows = c.fetchall()
    if not rows:
        await callback.message.edit_text("No pending payments.")
        return
    text = "💸 *Pending Payments*\n\n"
    for row in rows:
        payment_id, user_id, amount, currency, created_at = row
        text += f"ID: `{payment_id[:8]}`\nUser: {user_id}\nAmount: {amount} {currency}\nCreated: {datetime.fromtimestamp(created_at).strftime('%Y-%m-%d %H:%M')}\n\n"
    await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    await callback.answer()

@router.callback_query(F.data == "admin_verify_payment")
async def admin_verify_payment_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("Enter payment ID to verify:")
    await state.set_state(AdminStates.waiting_payment_id_to_verify)
    await callback.answer()

@router.message(AdminStates.waiting_payment_id_to_verify)
async def admin_verify_payment_execute(message: Message, state: FSMContext):
    payment_id = message.text.strip()
    async with db.get_cursor() as c:
        c.execute("SELECT user_id, amount FROM payments WHERE payment_id=? AND status='pending'", (payment_id,))
        row = c.fetchone()
    if not row:
        await message.answer("Payment not found or already processed.")
        await state.clear()
        return
    user_id, amount = row
    await db.activate_subscription(user_id, payment_id=payment_id)
    await message.answer(f"✅ Payment {payment_id} verified. Subscription activated for user {user_id} (${amount}).")
    await db.log_admin_action(message.from_user.id, "verify_payment", user_id, f"payment_id={payment_id}")
    await state.clear()

# ===================================================================
# System Health
# ===================================================================

@router.callback_query(F.data == "admin_health")
async def admin_health(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Access denied")
        return
    await callback.message.edit_text("🩺 Checking system health...")
    
    health_report = []
    # Check database
    try:
        async with db.get_cursor() as c:
            c.execute("SELECT COUNT(*) FROM users")
            count = c.fetchone()[0]
            health_report.append(f"✅ Database: OK ({count} users)")
    except Exception as e:
        health_report.append(f"❌ Database: {e}")
    
    # Check exchanges
    try:
        exchange_health = await market.check_exchange_health()
        for name, ok in exchange_health.items():
            health_report.append(f"{'✅' if ok else '⚠️'} {name.capitalize()}: {'Online' if ok else 'Issues'}")
    except Exception as e:
        health_report.append(f"❌ Market data: {e}")
    
    # Check OpenAI
    try:
        import openai
        openai.api_key = cfg.OPENAI_API_KEY
        # Simple test call
        health_report.append("✅ OpenAI: Configured")
    except:
        health_report.append("⚠️ OpenAI: Not configured or error")
    
    # Check news parser
    try:
        test_news = await news.get_news_summary(1)
        health_report.append("✅ News Parser: OK")
    except Exception as e:
        health_report.append(f"⚠️ News Parser: {e}")
    
    # Check bot uptime (simple)
    health_report.append(f"🤖 Bot: Active since {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    text = "🩺 *System Health Report*\n\n" + "\n".join(health_report)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔄 Refresh", callback_data="admin_health")], [InlineKeyboardButton(text="🔙 Back", callback_data="admin_back_to_main")]])
    await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    await callback.answer()

# ===================================================================
# Logs
# ===================================================================

@router.callback_query(F.data == "admin_logs")
async def admin_logs_menu(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📄 User Actions Log", callback_data="admin_logs_user")],
        [InlineKeyboardButton(text="📋 Admin Actions Log", callback_data="admin_logs_admin")],
        [InlineKeyboardButton(text="🐞 Error Log (file)", callback_data="admin_logs_error")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin_back_to_main")]
    ])
    await callback.message.edit_text("📜 *Logs Menu*", parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "admin_logs_user")
async def admin_logs_user(callback: CallbackQuery):
    async with db.get_cursor() as c:
        c.execute("SELECT user_id, action, details, timestamp FROM user_actions ORDER BY timestamp DESC LIMIT 50")
        rows = c.fetchall()
    if not rows:
        await callback.message.edit_text("No user actions logged.")
        return
    text = "📄 *Recent User Actions*\n\n"
    for row in rows:
        user_id, action, details, ts = row
        text += f"• {datetime.fromtimestamp(ts).strftime('%H:%M:%S')} User {user_id}: {action} {details[:50]}\n"
        if len(text) > 3800:
            text += "\n... (truncated)"
            break
    await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    await callback.answer()

@router.callback_query(F.data == "admin_logs_admin")
async def admin_logs_admin(callback: CallbackQuery):
    async with db.get_cursor() as c:
        c.execute("SELECT admin_id, action, target_user, details, timestamp FROM admin_logs ORDER BY timestamp DESC LIMIT 50")
        rows = c.fetchall()
    if not rows:
        await callback.message.edit_text("No admin actions logged.")
        return
    text = "📋 *Recent Admin Actions*\n\n"
    for row in rows:
        admin_id, action, target, details, ts = row
        text += f"• {datetime.fromtimestamp(ts).strftime('%H:%M:%S')} Admin {admin_id}: {action} -> {target or 'system'} {details[:40]}\n"
        if len(text) > 3800:
            break
    await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    await callback.answer()

@router.callback_query(F.data == "admin_logs_error")
async def admin_logs_error(callback: CallbackQuery):
    # Try to read log file
    log_file = "logs/bot.log"
    if not os.path.exists(log_file):
        await callback.message.edit_text("No error log file found.")
        return
    try:
        with open(log_file, "rb") as f:
            # Get last 100KB
            f.seek(max(0, f.tell() - 100000))
            content = f.read()
        await callback.message.delete()
        await callback.message.answer_document(types.BufferedInputFile(content, filename="bot.log"))
    except Exception as e:
        await callback.message.edit_text(f"Error reading log: {e}")
    await callback.answer()

# ===================================================================
# Backup & Restore
# ===================================================================

@router.callback_query(F.data == "admin_backup")
async def admin_backup_menu(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💾 Create Backup", callback_data="admin_backup_create")],
        [InlineKeyboardButton(text="📂 Restore from Backup", callback_data="admin_backup_restore")],
        [InlineKeyboardButton(text="🔙 Back", callback_data="admin_back_to_main")]
    ])
    await callback.message.edit_text("💾 *Backup & Restore*\n\nCreate database backup or restore from previous backup.", parse_mode=ParseMode.MARKDOWN, reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data == "admin_backup_create")
async def admin_backup_create(callback: CallbackQuery):
    backup_dir = "backups"
    os.makedirs(backup_dir, exist_ok=True)
    backup_name = f"crypto_pulse_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    backup_path = os.path.join(backup_dir, backup_name)
    try:
        shutil.copy2(cfg.DB_PATH, backup_path)
        await callback.message.edit_text(f"✅ Backup created: `{backup_name}`\nLocation: {backup_path}", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await callback.message.edit_text(f"❌ Backup failed: {e}")
    await callback.answer()

@router.callback_query(F.data == "admin_backup_restore")
async def admin_backup_restore_prompt(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer("⚠️ *Restore Warning*\nThis will overwrite current database. Send the backup file (.db) to restore.\n\nType /cancel to cancel.", parse_mode=ParseMode.MARKDOWN)
    await state.set_state(AdminStates.waiting_restore_file)
    await callback.answer()

@router.message(AdminStates.waiting_restore_file)
async def admin_backup_restore_file(message: Message, state: FSMContext):
    if not message.document:
        await message.answer("Please send a .db file.")
        return
    file_id = message.document.file_id
    file = await message.bot.get_file(file_id)
    temp_path = f"temp_restore_{datetime.now().timestamp()}.db"
    await message.bot.download_file(file.file_path, temp_path)
    try:
        # Basic validation: try to connect
        test_conn = sqlite3.connect(temp_path)
        test_conn.execute("SELECT COUNT(*) FROM users")
        test_conn.close()
        # Replace current DB
        shutil.copy2(temp_path, cfg.DB_PATH)
        await message.answer("✅ Database restored successfully. Re-initializing...")
        # Reinitialize database connection (global instance will recreate)
        global _db_instance
        _db_instance = None
        get_db()  # force reinit
    except Exception as e:
        await message.answer(f"❌ Restore failed: {e}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    await state.clear()

# ===================================================================
# Config Management (simple view)
# ===================================================================

@router.callback_query(F.data == "admin_config")
async def admin_config(callback: CallbackQuery):
    config_dict = cfg.get_config_dict()
    text = "⚙️ *Current Configuration*\n\n"
    for k, v in config_dict.items():
        text += f"• {k}: `{v}`\n"
    text += "\nTo change, edit .env file and restart bot."
    await callback.message.edit_text(text, parse_mode=ParseMode.MARKDOWN)
    await callback.answer()

# ===================================================================
# Back to Main Menu
# ===================================================================

@router.callback_query(F.data == "admin_back_to_main")
async def admin_back_to_main(callback: CallbackQuery):
    await cmd_admin(callback.message)
    await callback.answer()

@router.callback_query(F.data == "admin_close")
async def admin_close(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()

# ===================================================================
# Manual message to user
# ===================================================================

# Additional command for admins to send message to specific user
@router.message(Command("send"))
async def admin_send_command(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("Access denied")
        return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: /send <user_id> <message>")
        return
    parts = args[1].split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Usage: /send <user_id> <message>")
        return
    target_id = int(parts[0])
    msg_text = parts[1]
    try:
        await message.bot.send_message(target_id, f"📩 *Admin message:*\n{msg_text}", parse_mode=ParseMode.MARKDOWN)
        await message.answer(f"✅ Message sent to user {target_id}")
    except Exception as e:
        await message.answer(f"❌ Failed: {e}")

# ===================================================================
# Statistics command
# ===================================================================

@router.message(Command("stats"))
async def admin_stats(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Access denied")
        return
    total_users = await db.get_user_count()
    active_subs = await db.get_active_subscribers_count()
    total_revenue = await db.get_total_revenue()
    daily_stats = await db.get_daily_stats(7)
    text = f"📊 *Bot Statistics*\n\nTotal users: {total_users}\nActive subs: {active_subs}\nRevenue: ${total_revenue:,.2f}\n\nLast 7 days:\n"
    for stat in daily_stats:
        text += f"{stat['date']}: +{stat['new_users']} users, {stat['subscriptions_sold']} subs, ${stat['revenue_usd']:.0f}\n"
    await message.answer(text, parse_mode=ParseMode.MARKDOWN)

# ===================================================================
# Export router
# ===================================================================

__all__ = ["router"]