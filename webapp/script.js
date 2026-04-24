const tg = window.Telegram.WebApp;
tg.expand();
const user = tg.initDataUnsafe?.user || { id: 0, username: 'guest' };

// API Base URL (подставьте ваш реальный домен, если нужно)
const API_BASE = '/api';

let currentSymbol = 'BTC/USDT';
let currentChart = null;
let chartData = [];

// -------------------- API Calls --------------------
async function callApi(method, params = {}) {
    const res = await fetch(`${API_BASE}/${method}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: user.id, params })
    });
    const data = await res.json();
    if (!data.ok) throw new Error(data.error);
    return data.result;
}

// -------------------- Signal --------------------
async function loadSignal() {
    try {
        const signal = await callApi('signal', { symbol: currentSymbol });
        document.getElementById('signalAction').innerText = signal.action;
        document.getElementById('signalPrice').innerText = `$${signal.price.toLocaleString()}`;
        document.getElementById('confidenceFill').style.width = `${signal.confidence}%`;
        document.getElementById('signalReason').innerText = signal.reason;
        // Обновить премиум-бейдж
        if (signal.is_premium) {
            document.getElementById('premiumBadge').innerText = '⭐ PREMIUM';
        }
    } catch(e) {
        console.error(e);
    }
}

// -------------------- Chart (Lightweight Charts) --------------------
async function loadChart(timeframe = '1h') {
    const data = await callApi('chart', { symbol: currentSymbol, timeframe, limit: 50 });
    const container = document.getElementById('chartContainer');
    if (!currentChart) {
        currentChart = LightweightCharts.createChart(container, {
            width: container.clientWidth,
            height: 280,
            layout: { background: { color: 'transparent' }, textColor: '#eef5ff' },
            grid: { vertLines: { color: '#2a2e3f' }, horzLines: { color: '#2a2e3f' } }
        });
    }
    const series = currentChart.addCandlestickSeries({
        upColor: '#00e676', downColor: '#ff3b30', borderVisible: false
    });
    series.setData(data.map(d => ({ time: d.time, open: d.open, high: d.high, low: d.low, close: d.close })));
    currentChart.timeScale().fitContent();
}

// -------------------- Profile --------------------
async function loadProfile() {
    const profile = await callApi('profile');
    document.getElementById('profileUserId').innerText = profile.user_id;
    document.getElementById('profilePremium').innerHTML = profile.has_subscription ? '✅ Active' : '❌ Free';
    document.getElementById('profileBalance').innerText = `$${profile.balance.toFixed(2)}`;
    document.getElementById('profileRefs').innerText = profile.referral_count;
}

async function getReferralLink() {
    const link = await callApi('referral_link');
    tg.showPopup({
        title: 'Your referral link',
        message: link,
        buttons: [{ type: 'default', text: 'Copy', id: 'copy' }]
    }, (btnId) => {
        if (btnId === 'copy') {
            tg.writeToClipboard(link);
            tg.showAlert('Copied!');
        }
    });
}

async function buyPremium() {
    const payLink = await callApi('create_payment');
    if (payLink) tg.openTelegramLink(payLink);
    else tg.showAlert('Payment gateway error');
}

// -------------------- Navigation --------------------
document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => {
        const tabId = btn.getAttribute('data-tab');
        document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        document.querySelectorAll('.tab-content').forEach(t => t.classList.remove('active'));
        document.getElementById(`${tabId}Tab`).classList.add('active');
        if (tabId === 'chart') loadChart();
    });
});

document.querySelectorAll('.sym-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        currentSymbol = btn.getAttribute('data-sym');
        document.querySelectorAll('.sym-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        loadSignal();
        if (document.getElementById('chartTab').classList.contains('active')) loadChart();
    });
});

document.querySelectorAll('.tf-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        const tf = btn.getAttribute('data-tf');
        loadChart(tf);
    });
});

document.getElementById('refreshSignal').addEventListener('click', loadSignal);
document.getElementById('referralLinkBtn').addEventListener('click', getReferralLink);
document.getElementById('subscribeBtn').addEventListener('click', buyPremium);

// Initial load
loadSignal();
loadProfile();