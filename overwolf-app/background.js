/**
 * lol-coach Overwolf Bridge — Background Controller
 *
 * This Overwolf App connects to the Python lol-coach WebSocket server
 * and pushes TFT game state data in real-time.
 *
 * Setup:
 *   1. Install Overwolf desktop app
 *   2. Load this app as an unpacked extension in Overwolf
 *   3. Set overwolf.enabled: true in lol-coach config.yaml
 *   4. Start lol-coach (python main.py) first, then launch TFT
 *
 * Required features declared in manifest.json:
 *   "game_events": ["me", "match_info", "board", "store", "bench", "roster"]
 */

const PYTHON_WS_URL = "ws://127.0.0.1:7799";
const RECONNECT_INTERVAL_MS = 3000;
const REQUIRED_FEATURES = ["me", "match_info", "board", "store", "bench", "roster"];

let ws = null;
let reconnectTimer = null;
let lastState = {};

// ── WebSocket connection to Python ────────────────────────────────────────────

function connect() {
  if (ws && ws.readyState === WebSocket.OPEN) return;

  ws = new WebSocket(PYTHON_WS_URL);

  ws.onopen = () => {
    console.log("[Bridge] Connected to lol-coach Python server");
    clearTimeout(reconnectTimer);
    // Send current state immediately on connect
    if (Object.keys(lastState).length > 0) {
      sendState(lastState);
    }
  };

  ws.onclose = () => {
    console.log("[Bridge] Disconnected, retrying...");
    reconnectTimer = setTimeout(connect, RECONNECT_INTERVAL_MS);
  };

  ws.onerror = (err) => {
    console.error("[Bridge] WebSocket error:", err);
  };
}

function sendState(data) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: "tft_state", data }));
  }
}

// ── Overwolf Game Events ──────────────────────────────────────────────────────

function registerFeatures() {
  overwolf.games.events.setRequiredFeatures(REQUIRED_FEATURES, (result) => {
    if (result.status === "success") {
      console.log("[Bridge] Features registered:", REQUIRED_FEATURES);
    } else {
      console.warn("[Bridge] Feature registration failed:", result.reason);
      setTimeout(registerFeatures, 2000);
    }
  });
}

function onInfoUpdate(info) {
  // info.feature tells us which feature updated
  const feature = info.feature;
  const data = info.info;

  if (!data) return;

  // me: gold, hp, level, xp
  if (feature === "me" && data.me) {
    const me = data.me;
    if (me.health !== undefined) lastState.hp = parseInt(me.health) || 0;
    if (me.gold !== undefined) lastState.gold = parseInt(me.gold) || 0;
    if (me.level !== undefined) lastState.level = parseInt(me.level) || 1;
    if (me.xp !== undefined) {
      try { lastState.xp = JSON.parse(me.xp); } catch (_) {}
    }
  }

  // match_info: round, alive_players
  if (feature === "match_info" && data.match_info) {
    const mi = data.match_info;
    if (mi.round_type !== undefined) lastState.round_type = mi.round_type;
    if (mi.round_outcome !== undefined) lastState.round_outcome = mi.round_outcome;
    if (mi.local_player_damage !== undefined) lastState.last_damage = parseInt(mi.local_player_damage) || 0;
    if (mi.opponents !== undefined) {
      try {
        const opponents = JSON.parse(mi.opponents);
        lastState.alive_players = opponents.filter(p => p.health > 0).length + 1; // +1 for self
      } catch (_) {}
    }
  }

  // board: current board pieces
  if (feature === "board" && data.board) {
    try {
      const board = JSON.parse(data.board.board_pieces || "[]");
      lastState.board = board.map(p => ({
        name: p.name,
        star: p.level || 1,
        items: p.items || [],
        position: { x: p.location_x, y: p.location_y },
      }));
    } catch (_) {}
  }

  // store: shop champions
  if (feature === "store" && data.store) {
    try {
      const shop = JSON.parse(data.store.shop_choices || "[]");
      lastState.shop = shop.map(c => c.name || "");
    } catch (_) {}
  }

  // bench: bench pieces
  if (feature === "bench" && data.bench) {
    try {
      const bench = JSON.parse(data.bench.bench_pieces || "[]");
      lastState.bench = bench.map(p => ({
        name: p.name,
        star: p.level || 1,
        items: p.items || [],
      }));
    } catch (_) {}
  }

  sendState(lastState);
}

function onNewEvent(event) {
  // Forward notable events
  const notableEvents = ["round_start", "battle_start", "match_start", "match_end", "player_eliminated"];
  if (notableEvents.includes(event.name)) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: "tft_event", data: { event: event.name, ...lastState } }));
    }
  }
}

// ── Lifecycle ─────────────────────────────────────────────────────────────────

overwolf.games.onGameInfoUpdated.addListener((gameInfo) => {
  if (gameInfo && gameInfo.runningChanged) {
    if (gameInfo.gameInfo && gameInfo.gameInfo.isRunning) {
      console.log("[Bridge] Game started, registering features...");
      setTimeout(registerFeatures, 2000);
    }
  }
});

overwolf.games.events.onInfoUpdates2.addListener(onInfoUpdate);
overwolf.games.events.onNewEvents.addListener((evts) => {
  (evts.events || []).forEach(onNewEvent);
});

// Start WebSocket connection
connect();

// Check if game is already running
overwolf.games.getRunningGameInfo((gameInfo) => {
  if (gameInfo && gameInfo.isRunning) {
    setTimeout(registerFeatures, 1000);
  }
});

console.log("[Bridge] lol-coach Overwolf bridge initialized");
