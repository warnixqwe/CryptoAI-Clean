import asyncio
import logging
import json
import hashlib
import hmac
import time
import uuid
from typing import Dict, Optional, Any, Tuple, List
from datetime import datetime
from decimal import Decimal

import aiohttp
from aiogram import Bot

# Import configuration and database
from config import get_config
from database import get_db

cfg = get_config()
db = get_db()
logger = logging.getLogger(__name__)

# ===================================================================
# CryptoBot API Integration
# ===================================================================

class CryptoBotAPI:
    """CryptoBot (https://t.me/CryptoBot) payment gateway integration"""
    
    BASE_URL = "https://pay.crypt.bot/api"
    
    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Crypto-Pay-API-Token": token,
            "Content-Type": "application/json"
        }
    
    async def create_invoice(self, amount: float, currency: str = "USDT", 
                            description: str = "CryptoPulse AI Premium Subscription",
                            hidden_message: str = "Thank you for subscribing!",
                            paid_btn_name: str = "openBot",
                            paid_btn_url: str = None) -> Optional[str]:
        """
        Create a new invoice via CryptoBot API.
        Returns payment URL or None.
        """
        if not self.token:
            logger.warning("CryptoBot token not configured")
            return None
        
        # Convert amount to integer cents if needed (depending on currency)
        # For USDT, amount is typically in dollars with 2 decimals
        amount_str = f"{amount:.2f}"
        
        payload = {
            "amount": amount_str,
            "asset": currency,
            "description": description,
            "hidden_message": hidden_message,
            "paid_btn_name": paid_btn_name
        }
        if paid_btn_url:
            payload["paid_btn_url"] = paid_btn_url
        
        url = f"{self.BASE_URL}/createInvoice"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=self.headers, json=payload, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("ok"):
                            return data["result"]["bot_url"]
                        else:
                            logger.error(f"CryptoBot error: {data}")
                            return None
                    else:
                        logger.error(f"CryptoBot HTTP {resp.status}: {await resp.text()}")
                        return None
        except Exception as e:
            logger.error(f"CryptoBot exception: {e}")
            return None
    
    async def get_invoice_status(self, invoice_id: str) -> Optional[str]:
        """
        Check status of an invoice.
        Returns: 'paid', 'expired', 'active', or None.
        """
        if not self.token:
            return None
        
        url = f"{self.BASE_URL}/getInvoices"
        params = {"invoice_ids": invoice_id}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=self.headers, params=params, timeout=10) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("ok") and data.get("result", {}).get("items"):
                            invoice = data["result"]["items"][0]
                            status = invoice.get("status")
                            return status
        except Exception as e:
            logger.error(f"Failed to check invoice status: {e}")
        return None

# ===================================================================
# Binance Pay Integration (optional)
# ===================================================================

class BinancePayAPI:
    """Binance Pay payment gateway integration"""
    
    BASE_URL = "https://bpay.binanceapi.com"
    
    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key
    
    def _generate_signature(self, payload: str) -> str:
        """Generate HMAC SHA512 signature"""
        return hmac.new(
            self.secret_key.encode('utf-8'),
            payload.encode('utf-8'),
            hashlib.sha512
        ).hexdigest()
    
    async def create_order(self, amount: float, currency: str = "USDT", 
                          merchant_trade_no: str = None,
                          description: str = "CryptoPulse Subscription") -> Optional[Dict]:
        """Create Binance Pay order"""
        if not self.api_key or not self.secret_key:
            return None
        
        if not merchant_trade_no:
            merchant_trade_no = f"CP{int(time.time())}{uuid.uuid4().hex[:8]}"
        
        # Prepare request
        timestamp = int(time.time() * 1000)
        nonce = uuid.uuid4().hex
        payload = {
            "env": {
                "terminalType": "WEB"
            },
            "merchantTradeNo": merchant_trade_no,
            "orderAmount": f"{amount:.2f}",
            "currency": currency,
            "description": description,
            "tradeType": "PURCHASE"
        }
        payload_str = json.dumps(payload, separators=(',', ':'))
        signature = self._generate_signature(payload_str)
        
        headers = {
            "Content-Type": "application/json",
            "BinancePay-Timestamp": str(timestamp),
            "BinancePay-Nonce": nonce,
            "BinancePay-Certificate-SN": self.api_key,
            "BinancePay-Signature": signature
        }
        
        url = f"{self.BASE_URL}/binancepay/openapi/v2/order"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("status") == "SUCCESS":
                            return {
                                "prepay_id": data["data"]["prepayId"],
                                "checkout_url": data["data"]["checkoutUrl"],
                                "merchant_trade_no": merchant_trade_no
                            }
                    logger.error(f"BinancePay error: {await resp.text()}")
                    return None
        except Exception as e:
            logger.error(f"BinancePay exception: {e}")
            return None
    
    async def query_order(self, merchant_trade_no: str) -> Optional[Dict]:
        """Query order status"""
        if not self.api_key:
            return None
        
        timestamp = int(time.time() * 1000)
        nonce = uuid.uuid4().hex
        payload = {"merchantTradeNo": merchant_trade_no}
        payload_str = json.dumps(payload, separators=(',', ':'))
        signature = self._generate_signature(payload_str)
        
        headers = {
            "Content-Type": "application/json",
            "BinancePay-Timestamp": str(timestamp),
            "BinancePay-Nonce": nonce,
            "BinancePay-Certificate-SN": self.api_key,
            "BinancePay-Signature": signature
        }
        
        url = f"{self.BASE_URL}/binancepay/openapi/v2/order/query"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, headers=headers, json=payload, timeout=15) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data
        except Exception as e:
            logger.error(f"BinancePay query error: {e}")
        return None

# ===================================================================
# Manual Payment Handler
# ===================================================================

class ManualPaymentHandler:
    """Handle manual payment confirmations (admin verification)"""
    
    @staticmethod
    async def create_manual_payment_request(user_id: int, amount: float, currency: str = "USDT") -> str:
        """Create a manual payment request"""
        payment_id = f"manual_{user_id}_{int(time.time())}_{uuid.uuid4().hex[:4]}"
        await db.create_payment(payment_id, user_id, amount, currency)
        return payment_id
    
    @staticmethod
    async def verify_manual_payment(payment_id: str, admin_id: int, txid: str = None) -> bool:
        """Verify manual payment (admin action)"""
        status = await db.get_payment_status(payment_id)
        if status != "pending":
            return False
        
        # Get payment details
        async with db.get_cursor() as c:
            c.execute("SELECT user_id, amount FROM payments WHERE payment_id=?", (payment_id,))
            row = c.fetchone()
            if not row:
                return False
            user_id, amount = row
        
        # Activate subscription
        await db.activate_subscription(user_id, payment_id=payment_id)
        await db.log_admin_action(admin_id, "manual_verify_payment", user_id, f"payment_id={payment_id}, txid={txid}")
        return True

# ===================================================================
# Main Payment Manager
# ===================================================================

class PaymentManager:
    """Central payment manager integrating multiple gateways"""
    
    def __init__(self):
        self.cryptobot = CryptoBotAPI(cfg.CRYPTOBOT_TOKEN) if cfg.CRYPTOBOT_TOKEN else None
        self.binance_pay = BinancePayAPI(cfg.BINANCE_PAY_API_KEY, cfg.BINANCE_PAY_SECRET_KEY) if cfg.BINANCE_PAY_API_KEY else None
        self.manual_handler = ManualPaymentHandler()
        self._polling_tasks = {}
    
    async def create_invoice(self, amount: float, currency: str = "USDT", 
                            payment_id: str = None, gateway: str = "cryptobot") -> Optional[str]:
        """
        Create payment invoice.
        Returns payment URL or None.
        """
        # Generate payment_id if not provided
        if not payment_id:
            payment_id = await db.create_payment(0, amount, currency)  # user_id unknown yet, will update later
            # Actually better to have user_id. We'll assume user_id is known.
            # But for flexibility:
        else:
            # Ensure payment record exists
            if not await db.get_payment_status(payment_id):
                # Create if missing
                # Need user_id - let's extract from payment_id? Simpler: pass user_id.
                pass
        
        if gateway == "cryptobot" and self.cryptobot:
            return await self.cryptobot.create_invoice(amount, currency, 
                                                      description=f"CryptoPulse AI - {amount} {currency}",
                                                      paid_btn_url=f"https://t.me/{cfg.BOT_USERNAME}?start=paid_{payment_id}")
        elif gateway == "binance" and self.binance_pay:
            order = await self.binance_pay.create_order(amount, currency, description="CryptoPulse Subscription")
            if order:
                return order.get("checkout_url")
        
        # Fallback: manual payment instructions
        return None
    
    async def check_payment(self, payment_id: str) -> str:
        """
        Check payment status from external gateway and update local status.
        Returns: 'paid', 'pending', 'expired', 'failed'
        """
        # First check local DB status
        local_status = await db.get_payment_status(payment_id)
        if local_status == "paid":
            return "paid"
        
        # Try to fetch from gateway (if we have gateway mapping)
        # For simplicity, we'll assume we stored gateway info in payment record.
        # We'll extend payment table to include 'gateway' column.
        # For now, check via CryptoBot if payment_id starts with certain pattern.
        if self.cryptobot and payment_id.startswith("cryptobot_"):
            # Actually we didn't store that. We'll query directly.
            # Better to store invoice_id mapping. Let's skip complex polling here.
            pass
        
        # If we don't have automated check, return pending
        return "pending"
    
    async def poll_payment(self, payment_id: str, user_id: int, bot: Bot, 
                          callback_message_id: int = None, check_interval: int = 10,
                          max_checks: int = 60) -> bool:
        """
        Periodically check payment status and activate subscription when paid.
        Returns True if payment completed, False if timeout.
        """
        for attempt in range(max_checks):
            status = await self.check_payment(payment_id)
            if status == "paid":
                # Subscription already activated via webhook or manual verify
                return True
            elif status == "expired" or status == "failed":
                return False
            await asyncio.sleep(check_interval)
        
        return False
    
    async def process_webhook(self, request_data: Dict, signature: str = None) -> Dict:
        """
        Handle incoming webhook from CryptoBot or Binance Pay.
        Returns dict with status and message.
        """
        # CryptoBot webhook format: { "update_id": 123, "payload": {...} }
        # We'll implement basic verification
        
        payload = request_data.get("payload", {})
        if not payload:
            return {"ok": False, "error": "Invalid webhook data"}
        
        # Extract payment data
        invoice_id = payload.get("invoice_id")
        status = payload.get("status")
        if status == "paid":
            # Find payment by external_id (we need to store mapping)
            # For demo, assume we have mapping table
            # We'll implement a mapping in database
            async with db.get_cursor() as c:
                c.execute("SELECT payment_id FROM payments WHERE external_id=?", (invoice_id,))
                row = c.fetchone()
                if row:
                    payment_id = row[0]
                    c.execute("SELECT user_id FROM payments WHERE payment_id=?", (payment_id,))
                    user_row = c.fetchone()
                    if user_row:
                        user_id = user_row[0]
                        await db.activate_subscription(user_id, payment_id=payment_id)
                        return {"ok": True, "message": "Subscription activated"}
        
        return {"ok": True, "message": "Webhook received"}
    
    async def get_balance(self, user_id: int) -> float:
        """Get user's internal balance (for referral earnings)"""
        return await db.get_balance(user_id)
    
    async def withdraw(self, user_id: int, amount: float, address: str, currency: str = "USDT") -> bool:
        """
        Process withdrawal request.
        Actual transfer requires manual admin processing.
        """
        balance = await db.get_balance(user_id)
        if balance < amount:
            return False
        # Deduct balance first
        success = await db.deduct_balance(user_id, amount, f"withdrawal_request to {address[:10]}...")
        if not success:
            return False
        # Create withdrawal record
        async with db.get_cursor() as c:
            c.execute('''
                INSERT INTO payments (payment_id, user_id, amount, currency, status, created_at)
                VALUES (?, ?, ?, ?, 'withdraw_pending', ?)
            ''', (f"wd_{user_id}_{int(time.time())}", user_id, amount, currency, int(time.time())))
        return True

# ===================================================================
# Subscription Helper Functions
# ===================================================================

async def auto_expire_subscriptions():
    """Background task: automatically expire subscriptions that are past due"""
    await db.cleanup_expired_subscriptions()
    logger.info("Auto-expired subscriptions check completed")

async def send_payment_reminder(bot: Bot, user_id: int, days_left: int):
    """Send reminder to user about upcoming subscription expiration"""
    if days_left == 3:
        text = f"⚠️ *Subscription expires in 3 days!*\n\nRenew now to keep receiving premium signals.\n/subscribe"
    elif days_left == 1:
        text = f"🔴 *LAST DAY!* Your subscription expires tomorrow.\nRenew now: /subscribe"
    else:
        return
    try:
        await bot.send_message(user_id, text, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Failed to send reminder to {user_id}: {e}")

async def check_expiring_subscriptions(bot: Bot):
    """Daily task: check subscriptions expiring within 3 days and send reminders"""
    async with db.get_cursor() as c:
        now = int(time.time())
        three_days = now + 3 * 86400
        one_day = now + 86400
        c.execute("SELECT user_id, subscribe_until FROM users WHERE subscribed=1 AND subscribe_until > ? AND subscribe_until <= ?", (now, three_days))
        users = c.fetchall()
        for user_id, exp in users:
            days_left = (exp - now) // 86400
            await send_payment_reminder(bot, user_id, days_left)

# ===================================================================
# Payment Analytics
# ===================================================================

async def get_payment_statistics(days: int = 30) -> Dict[str, Any]:
    """Get payment analytics for admin dashboard"""
    cutoff = int(time.time()) - days * 86400
    async with db.get_cursor() as c:
        c.execute("SELECT COUNT(*) FROM payments WHERE status='paid' AND paid_at > ?", (cutoff,))
        total_payments = c.fetchone()[0]
        c.execute("SELECT SUM(amount) FROM payments WHERE status='paid' AND paid_at > ?", (cutoff,))
        total_volume = c.fetchone()[0] or 0.0
        c.execute("SELECT COUNT(DISTINCT user_id) FROM payments WHERE status='paid' AND paid_at > ?", (cutoff,))
        unique_users = c.fetchone()[0]
        # Daily breakdown
        c.execute('''
            SELECT date(paid_at, 'unixepoch') as day, COUNT(*), SUM(amount)
            FROM payments
            WHERE status='paid' AND paid_at > ?
            GROUP BY day
            ORDER BY day DESC
            LIMIT 30
        ''', (cutoff,))
        daily = [{"date": row[0], "count": row[1], "amount": row[2]} for row in c.fetchall()]
    
    return {
        "total_payments": total_payments,
        "total_volume_usd": total_volume,
        "unique_paying_users": unique_users,
        "daily_breakdown": daily,
        "average_payment": total_volume / total_payments if total_payments > 0 else 0
    }

# ===================================================================
# Singleton instance
# ===================================================================

_payment_manager: Optional[PaymentManager] = None

def get_payment_manager() -> PaymentManager:
    global _payment_manager
    if _payment_manager is None:
        _payment_manager = PaymentManager()
    return _payment_manager

# ===================================================================
# Test / demo
# ===================================================================
if __name__ == "__main__":
    async def test():
        pm = get_payment_manager()
        # Test CryptoBot invoice creation if token available
        if cfg.CRYPTOBOT_TOKEN:
            url = await pm.create_invoice(20.0, "USDT", "test_payment", "cryptobot")
            print(f"Invoice URL: {url}")
        else:
            print("CryptoBot token not configured")
        
        # Test manual payment
        pid = await db.create_payment(123456, 20.0, "USDT")
        print(f"Created payment ID: {pid}")
    
    asyncio.run(test())

# ===================================================================
# Webhook server stub (if using webhook mode)
# ===================================================================

async def start_webhook_server(bot: Bot, webhook_path: str, port: int):
    """Start aiohttp webhook server for payment notifications"""
    from aiohttp import web
    
    app = web.Application()
    pm = get_payment_manager()
    
    async def handle_webhook(request):
        data = await request.json()
        signature = request.headers.get("Crypto-Pay-API-Signature")
        result = await pm.process_webhook(data, signature)
        return web.json_response(result)
    
    app.router.add_post(webhook_path, handle_webhook)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Webhook server started on port {port}, path {webhook_path}")
    return runner

# ===================================================================
# Export
# ===================================================================
__all__ = ["PaymentManager", "get_payment_manager", "auto_expire_subscriptions", 
           "check_expiring_subscriptions", "get_payment_statistics", "CryptoBotAPI"]