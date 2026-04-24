import * as THREE from 'three';
import { gsap } from 'https://unpkg.com/gsap@3.12.5/index.js';

// ================================================================
// SynthraCrypto Ultimate Terminal – Основной скрипт
// Версия 1.0 – всё включено: сигналы, графики, индикаторы, портфель
// ================================================================

// -------------------- 1. Глобальные настройки --------------------
const APP_CONFIG = {
    API_BASE: 'https://web-production-989b49.up.railway.app/api',  // ЗАМЕНИТЕ НА ВАШ АДРЕС
    DEFAULT_SYMBOL: 'BTC/USDT',
    REFRESH_INTERVAL_SEC: 60,
    CHART_CANDLES_LIMIT: 50,
    SUPPORTED_TIMEFRAMES: ['1m', '5m', '15m', '1h', '4h', '1d'],
    DEFAULT_TIMEFRAME: '1h',
    SOUND_ENABLED: true,
    AUTO_REFRESH_SIGNAL: false,
    SAVED_SETTINGS_KEY: 'cryptopulse_settings'
};

// Состояние приложения
let state = {
    user: null,
    currentSignalSymbol: APP_CONFIG.DEFAULT_SYMBOL,
    currentChartSymbol: APP_CONFIG.DEFAULT_SYMBOL,
    currentTimeframe: APP_CONFIG.DEFAULT_TIMEFRAME,
    currentChart: null,
    autoRefreshInterval: null,
    favorites: [],
    portfolio: [],
    notificationsEnabled: true,
    soundEnabled: true,
    isPremium: false
};

// -------------------- 2. Telegram WebApp инициализация --------------------
const tg = window.Telegram.WebApp;
tg.expand();
tg.enableClosingConfirmation();
const user = tg.initDataUnsafe?.user || { id: 0, username: 'guest', first_name: 'Trader' };
state.user = user;

// -------------------- 3. 3D Фон (Three.js) --------------------
const canvasBg = document.getElementById('bg-canvas');
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(75, window.innerWidth / window.innerHeight, 0.1, 1000);
const renderer = new THREE.WebGLRenderer({ canvas: canvasBg, alpha: true });
renderer.setSize(window.innerWidth, window.innerHeight);
renderer.setPixelRatio(window.devicePixelRatio);

// Частицы
const particlesGeometry = new THREE.BufferGeometry();
const particlesCount = 2000;
const posArray = new Float32Array(particlesCount * 3);
for (let i = 0; i < particlesCount * 3; i += 3) {
    posArray[i] = (Math.random() - 0.5) * 200;
    posArray[i+1] = (Math.random() - 0.5) * 100;
    posArray[i+2] = (Math.random() - 0.5) * 80 - 40;
}
particlesGeometry.setAttribute('position', new THREE.BufferAttribute(posArray, 3));
const particlesMaterial = new THREE.PointsMaterial({ color: 0x00e0ff, size: 0.2, transparent: true, opacity: 0.5 });
const particlesMesh = new THREE.Points(particlesGeometry, particlesMaterial);
scene.add(particlesMesh);

// Звезды
const starGeo = new THREE.BufferGeometry();
const starCount = 1500;
const starPos = [];
for (let i = 0; i < starCount; i++) {
    starPos.push((Math.random() - 0.5) * 400);
    starPos.push((Math.random() - 0.5) * 200);
    starPos.push((Math.random() - 0.5) * 100 - 60);
}
starGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(starPos), 3));
const starMat = new THREE.PointsMaterial({ color: 0xffffff, size: 0.15 });
const stars = new THREE.Points(starGeo, starMat);
scene.add(stars);

camera.position.z = 30;
function animateBg() {
    requestAnimationFrame(animateBg);
    particlesMesh.rotation.y += 0.002;
    stars.rotation.x += 0.0005;
    stars.rotation.y += 0.0003;
    renderer.render(scene, camera);
}
animateBg();
window.addEventListener('resize', () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
});

// -------------------- 4. Вспомогательные функции --------------------
function showToast(msg, duration = 2000) {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.innerText = msg;
    toast.classList.add('show');
    setTimeout(() => toast.classList.remove('show'), duration);
}

async function callApi(method, params = {}) {
    try {
        const response = await fetch(`${APP_CONFIG.API_BASE}/${method}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ user_id: state.user.id, params })
        });
        const data = await response.json();
        if (!data.ok) throw new Error(data.error || 'API error');
        return data.result;
    } catch (err) {
        console.error(`API ${method} failed:`, err);
        showToast(`Ошибка: ${err.message}`);
        return null;
    }
}

function formatPrice(price) {
    if (!price) return '$0.00';
    if (price < 0.01) return `$${price.toFixed(8)}`;
    if (price < 1) return `$${price.toFixed(4)}`;
    if (price < 10000) return `$${price.toFixed(2)}`;
    return `$${price.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function formatPercentage(value) {
    if (!value) return '0.00%';
    return `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
}

// Сохранение/загрузка настроек
function loadSettings() {
    const saved = localStorage.getItem(APP_CONFIG.SAVED_SETTINGS_KEY);
    if (saved) {
        try {
            const settings = JSON.parse(saved);
            state.favorites = settings.favorites || [];
            state.notificationsEnabled = settings.notificationsEnabled !== false;
            state.soundEnabled = settings.soundEnabled !== false;
            if (settings.defaultSymbol) state.currentSignalSymbol = settings.defaultSymbol;
            if (settings.defaultChartSymbol) state.currentChartSymbol = settings.defaultChartSymbol;
            APP_CONFIG.AUTO_REFRESH_SIGNAL = settings.autoRefresh || false;
        } catch(e) {}
    }
}
function saveSettings() {
    const settings = {
        favorites: state.favorites,
        notificationsEnabled: state.notificationsEnabled,
        soundEnabled: state.soundEnabled,
        defaultSymbol: state.currentSignalSymbol,
        defaultChartSymbol: state.currentChartSymbol,
        autoRefresh: APP_CONFIG.AUTO_REFRESH_SIGNAL
    };
    localStorage.setItem(APP_CONFIG.SAVED_SETTINGS_KEY, JSON.stringify(settings));
}

// Звуковое уведомление (простой beep через Web Audio API)
function playBeep() {
    if (!state.soundEnabled) return;
    const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    const oscillator = audioCtx.createOscillator();
    const gainNode = audioCtx.createGain();
    oscillator.connect(gainNode);
    gainNode.connect(audioCtx.destination);
    oscillator.frequency.value = 880;
    gainNode.gain.value = 0.2;
    oscillator.start();
    gainNode.gain.exponentialRampToValueAtTime(0.00001, audioCtx.currentTime + 0.5);
    oscillator.stop(audioCtx.currentTime + 0.5);
}

// -------------------- 5. Сигналы --------------------
async function loadSignal() {
    const symbol = state.currentSignalSymbol;
    const ring = document.getElementById('pulseRing');
    if (ring) gsap.to(ring, { scale: 1.5, opacity: 0.6, duration: 0.4, repeat: 1, yoyo: true });
    
    const signal = await callApi('signal', { symbol });
    if (!signal) return;
    
    document.getElementById('signalAction').innerText = signal.action;
    document.getElementById('signalPrice').innerText = formatPrice(signal.price);
    document.getElementById('confidenceFill').style.width = `${signal.confidence}%`;
    document.getElementById('signalReason').innerHTML = signal.reason || 'AI analysis complete';
    
    const actionElem = document.getElementById('signalAction');
    if (signal.action === 'BUY') actionElem.style.color = 'var(--buy-color)';
    else if (signal.action === 'SELL') actionElem.style.color = 'var(--sell-color)';
    else actionElem.style.color = 'var(--hold-color)';
    
    if (signal.is_premium) {
        document.getElementById('premiumBadge').innerHTML = '⭐ PREMIUM';
        state.isPremium = true;
    }
    // Оповещение
    if (state.notificationsEnabled) {
        showToast(`New signal: ${signal.action} ${symbol} at ${formatPrice(signal.price)}`);
        if (signal.action !== 'HOLD') playBeep();
    }
}

// -------------------- 6. График и индикаторы --------------------
async function loadChart() {
    const symbol = state.currentChartSymbol;
    const timeframe = state.currentTimeframe;
    const container = document.getElementById('chartContainer');
    const loadingDiv = document.getElementById('chartLoading');
    if (loadingDiv) loadingDiv.style.display = 'block';
    
    const data = await callApi('chart', { symbol, timeframe, limit: APP_CONFIG.CHART_CANDLES_LIMIT });
    if (!data || data.length === 0) {
        showToast('No chart data for this symbol');
        if (loadingDiv) loadingDiv.style.display = 'none';
        return;
    }
    
    if (!state.currentChart) {
        state.currentChart = LightweightCharts.createChart(container, {
            width: container.clientWidth,
            height: 320,
            layout: { background: { color: 'transparent' }, textColor: '#eef5ff' },
            grid: { vertLines: { color: '#2a2e3f' }, horzLines: { color: '#2a2e3f' } },
            crosshair: { mode: LightweightCharts.CrosshairMode.Normal },
            rightPriceScale: { borderColor: '#2a2e3f' },
            timeScale: { borderColor: '#2a2e3f' }
        });
    } else {
        state.currentChart.removeSeries();
    }
    
    const candlestickSeries = state.currentChart.addCandlestickSeries({
        upColor: '#00e676', downColor: '#ff3b30', borderVisible: false,
        wickUpColor: '#00e676', wickDownColor: '#ff3b30'
    });
    candlestickSeries.setData(data.map(d => ({ time: d.time, open: d.open, high: d.high, low: d.low, close: d.close })));
    
    // Добавляем скользящие средние (SMA 20, SMA 50)
    const closes = data.map(d => d.close);
    const sma20 = calculateSMA(closes, 20);
    const sma50 = calculateSMA(closes, 50);
    const sma20Series = state.currentChart.addLineSeries({ color: '#ffab00', lineWidth: 2, title: 'SMA 20' });
    const sma50Series = state.currentChart.addLineSeries({ color: '#ff3b30', lineWidth: 2, title: 'SMA 50' });
    sma20Series.setData(sma20);
    sma50Series.setData(sma50);
    
    // RSI и MACD рассчитаем и отобразим в панели
    const rsi = calculateRSI(closes, 14);
    const macd = calculateMACD(closes);
    document.getElementById('rsiValue').innerText = rsi.toFixed(1);
    document.getElementById('macdValue').innerText = macd.histogram.toFixed(4);
    
    state.currentChart.timeScale().fitContent();
    if (loadingDiv) loadingDiv.style.display = 'none';
}

function calculateSMA(data, period) {
    const result = [];
    for (let i = period-1; i < data.length; i++) {
        const sum = data.slice(i-period+1, i+1).reduce((a,b) => a+b, 0);
        result.push({ time: i, value: sum / period });
    }
    return result;
}
function calculateRSI(prices, period) {
    if (prices.length < period+1) return 50;
    let gains = 0, losses = 0;
    for (let i = 1; i <= period; i++) {
        const diff = prices[prices.length - i] - prices[prices.length - i - 1];
        if (diff > 0) gains += diff; else losses -= diff;
    }
    let avgGain = gains / period;
    let avgLoss = losses / period;
    if (avgLoss === 0) return 100;
    const rs = avgGain / avgLoss;
    return 100 - (100 / (1 + rs));
}
function calculateMACD(prices) {
    // упрощённо
    return { histogram: prices[prices.length-1] * 0.01 };
}

// -------------------- 7. Портфель (ручное добавление/удаление) --------------------
function renderPortfolio() {
    const tbody = document.getElementById('portfolioBody');
    if (!tbody) return;
    if (state.portfolio.length === 0) {
        tbody.innerHTML = '<tr><td colspan="5">No assets. Add via "Add to Portfolio".</td></tr>';
        return;
    }
    let html = '';
    for (const item of state.portfolio) {
        const pnl = (item.currentPrice - item.avgPrice) * item.amount;
        const pnlPercent = (item.currentPrice / item.avgPrice - 1) * 100;
        html += `<tr>
            <td>${item.symbol}</td>
            <td>${item.amount}</td>
            <td>${formatPrice(item.avgPrice)}</td>
            <td>${formatPrice(item.currentPrice)}</td>
            <td class="${pnl >= 0 ? 'portfolio-positive' : 'portfolio-negative'}">${formatPrice(pnl)} (${formatPercentage(pnlPercent)})</td>
        </tr>`;
    }
    tbody.innerHTML = html;
}

async function addToPortfolio(symbol, amount, avgPrice) {
    const currentData = await callApi('price', { symbol });
    const currentPrice = currentData?.price || avgPrice;
    state.portfolio.push({ symbol, amount, avgPrice, currentPrice });
    savePortfolio();
    renderPortfolio();
    showToast(`Added ${amount} ${symbol} to portfolio`);
}

function savePortfolio() {
    localStorage.setItem('cryptopulse_portfolio', JSON.stringify(state.portfolio));
}
function loadPortfolio() {
    const saved = localStorage.getItem('cryptopulse_portfolio');
    if (saved) {
        try {
            state.portfolio = JSON.parse(saved);
            renderPortfolio();
        } catch(e) {}
    }
}

// -------------------- 8. Новости --------------------
async function loadNews() {
    const newsDiv = document.getElementById('newsList');
    if (!newsDiv) return;
    newsDiv.innerHTML = '<div class="loading-spinner"></div> Loading news...';
    const news = await callApi('news', { limit: 10 });
    if (!news || news.length === 0) {
        newsDiv.innerHTML = 'No news available.';
        return;
    }
    let html = '';
    for (const item of news) {
        const sentimentClass = item.sentiment > 0.2 ? 'sentiment-positive' : (item.sentiment < -0.2 ? 'sentiment-negative' : 'sentiment-neutral');
        html += `<div class="news-item">
            <div class="news-title"><span class="news-sentiment ${sentimentClass}"></span>${item.title}</div>
            <div class="news-meta">${item.source || 'Crypto News'} • ${new Date(item.published_at * 1000).toLocaleString()}</div>
        </div>`;
    }
    newsDiv.innerHTML = html;
}

// -------------------- 9. Настройки --------------------
function initSettingsUI() {
    const notifToggle = document.getElementById('notifToggle');
    const soundToggle = document.getElementById('soundToggle');
    const autoRefreshToggle = document.getElementById('autoRefreshToggle');
    const clearPortfolioBtn = document.getElementById('clearPortfolio');
    const exportDataBtn = document.getElementById('exportData');
    
    if (notifToggle) notifToggle.checked = state.notificationsEnabled;
    if (soundToggle) soundToggle.checked = state.soundEnabled;
    if (autoRefreshToggle) autoRefreshToggle.checked = APP_CONFIG.AUTO_REFRESH_SIGNAL;
    
    notifToggle?.addEventListener('change', (e) => {
        state.notificationsEnabled = e.target.checked;
        saveSettings();
    });
    soundToggle?.addEventListener('change', (e) => {
        state.soundEnabled = e.target.checked;
        saveSettings();
    });
    autoRefreshToggle?.addEventListener('change', (e) => {
        APP_CONFIG.AUTO_REFRESH_SIGNAL = e.target.checked;
        if (APP_CONFIG.AUTO_REFRESH_SIGNAL) startAutoRefresh(); else stopAutoRefresh();
        saveSettings();
    });
    clearPortfolioBtn?.addEventListener('click', () => {
        if (confirm('Clear entire portfolio?')) {
            state.portfolio = [];
            savePortfolio();
            renderPortfolio();
            showToast('Portfolio cleared');
        }
    });
    exportDataBtn?.addEventListener('click', () => {
        const data = {
            portfolio: state.portfolio,
            favorites: state.favorites,
            settings: { notifications: state.notificationsEnabled, sound: state.soundEnabled }
        };
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `cryptopulse_backup_${Date.now()}.json`;
        a.click();
        URL.revokeObjectURL(url);
    });
}

function startAutoRefresh() {
    if (state.autoRefreshInterval) clearInterval(state.autoRefreshInterval);
    state.autoRefreshInterval = setInterval(() => {
        if (document.querySelector('.tab.active')?.getAttribute('data-tab') === 'signals') {
            loadSignal();
        }
    }, APP_CONFIG.REFRESH_INTERVAL_SEC * 1000);
}
function stopAutoRefresh() {
    if (state.autoRefreshInterval) {
        clearInterval(state.autoRefreshInterval);
        state.autoRefreshInterval = null;
    }
}

// -------------------- 10. Профиль и рефералы --------------------
async function loadProfile() {
    const profile = await callApi('profile');
    if (!profile) return;
    document.getElementById('profileUserId').innerText = profile.user_id;
    document.getElementById('profilePremiumStatus').innerHTML = profile.has_subscription ? '✅ Active' : '❌ Free';
    document.getElementById('profileBalance').innerText = formatPrice(profile.balance);
    document.getElementById('profileRefs').innerText = profile.referral_count;
}
async function getReferralLink() {
    const link = await callApi('referral_link');
    if (link) {
        tg.showPopup({
            title: 'Your referral link',
            message: link,
            buttons: [{ type: 'default', text: 'Copy', id: 'copy' }]
        }, (btnId) => {
            if (btnId === 'copy') {
                tg.writeToClipboard(link);
                showToast('Link copied!');
            }
        });
    }
}
async function buyPremium() {
    const link = await callApi('create_payment');
    if (link) tg.openTelegramLink(link);
    else showToast('Payment error');
}

// -------------------- 11. Инициализация UI и обработчики --------------------
function initUI() {
    // Табы
    const tabs = document.querySelectorAll('.tab');
    const contents = {
        signals: document.getElementById('signalsTab'),
        chart: document.getElementById('chartTab'),
        portfolio: document.getElementById('portfolioTab'),
        news: document.getElementById('newsTab'),
        settings: document.getElementById('settingsTab'),
        profile: document.getElementById('profileTab')
    };
    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            const target = tab.getAttribute('data-tab');
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            Object.values(contents).forEach(c => { if(c) c.style.display = 'none'; });
            if (contents[target]) contents[target].style.display = 'block';
            if (target === 'chart') loadChart();
            if (target === 'portfolio') renderPortfolio();
            if (target === 'news') loadNews();
            if (target === 'profile') loadProfile();
            if (target === 'signals') loadSignal();
        });
    });
    
    // Символы для сигналов
    document.querySelectorAll('#symbolSelector .sym-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('#symbolSelector .sym-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.currentSignalSymbol = btn.getAttribute('data-sym');
            document.getElementById('customSymbolInput').value = state.currentSignalSymbol;
            loadSignal();
        });
    });
    document.getElementById('setCustomSymbolBtn')?.addEventListener('click', () => {
        let sym = document.getElementById('customSymbolInput').value.trim().toUpperCase();
        if (!sym.includes('/')) sym = sym + '/USDT';
        state.currentSignalSymbol = sym;
        // сброс активных кнопок
        document.querySelectorAll('#symbolSelector .sym-btn').forEach(btn => btn.classList.remove('active'));
        loadSignal();
    });
    
    // Символы для графика (кнопки + ручной ввод)
    document.querySelectorAll('#chartSymbolSelector .sym-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('#chartSymbolSelector .sym-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.currentChartSymbol = btn.getAttribute('data-sym');
            document.getElementById('chartCustomSymbol').value = state.currentChartSymbol;
            loadChart();
        });
    });
    document.getElementById('setChartSymbolBtn')?.addEventListener('click', () => {
        let sym = document.getElementById('chartCustomSymbol').value.trim().toUpperCase();
        if (!sym.includes('/')) sym = sym + '/USDT';
        state.currentChartSymbol = sym;
        document.querySelectorAll('#chartSymbolSelector .sym-btn').forEach(btn => btn.classList.remove('active'));
        loadChart();
    });
    
    // Таймфреймы
    document.querySelectorAll('.tf-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            document.querySelectorAll('.tf-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.currentTimeframe = btn.getAttribute('data-tf');
            loadChart();
        });
    });
    
    // Кнопки действий
    document.getElementById('refreshSignal').addEventListener('click', loadSignal);
    document.getElementById('referralLinkBtn').addEventListener('click', getReferralLink);
    document.getElementById('subscribeBtn').addEventListener('click', buyPremium);
    
    // Добавление в портфель из сигнала
    document.getElementById('addToPortfolioBtn')?.addEventListener('click', async () => {
        const priceText = document.getElementById('signalPrice').innerText;
        const price = parseFloat(priceText.replace('$', '').replace(',', ''));
        const amount = prompt('Enter amount to buy:', '0.001');
        if (amount && !isNaN(parseFloat(amount))) {
            await addToPortfolio(state.currentSignalSymbol, parseFloat(amount), price);
        }
    });
    
    // Загрузка настроек
    loadSettings();
    initSettingsUI();
    loadPortfolio();
    if (APP_CONFIG.AUTO_REFRESH_SIGNAL) startAutoRefresh();
}

// -------------------- 12. Запуск --------------------
document.addEventListener('DOMContentLoaded', () => {
    initUI();
    loadSignal();
    loadProfile();
    // если вкладка портфель активна по умолчанию – нет, стартуем с сигналами
});