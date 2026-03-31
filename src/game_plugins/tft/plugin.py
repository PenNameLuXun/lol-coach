from src.game_plugins.base import GameState, RuleResult
from src.game_plugins.tft.source import TftLiveDataSource
from src.lol_client import detect_game_type, extract_key_metrics


class TftPlugin:
    id = "tft"
    display_name = "Teamfight Tactics"
    manifest = {
        "id": "tft",
        "display_name": "Teamfight Tactics",
        "source": {"kind": "league_live_client"},
        "supports_rules": True,
        "supports_ai_context": True,
    }

    def __init__(self):
        self._source = TftLiveDataSource()

    def is_available(self) -> bool:
        return self._source.is_available()

    def fetch_live_data(self) -> dict | None:
        return self._source.fetch_live_data()

    def has_seen_activity(self) -> bool:
        return self._source.has_seen_activity()

    def detect(self, raw_data: dict, metrics: dict[str, int | str]) -> bool:
        return detect_game_type(raw_data) == "tft"

    def extract_state(self, raw_data: dict, metrics: dict[str, int | str]) -> GameState:
        metrics = metrics or extract_key_metrics(raw_data)
        active = raw_data.get("activePlayer", {})
        hp = _find_tft_hp(raw_data, active.get("summonerName", ""))
        alive = _count_tft_alive(raw_data)
        derived = {
            "player_hp": hp,
            "alive_players": alive,
            "level": int(active.get("level", 1) or 1),
            "gold": int(active.get("currentGold", 0) or 0),
        }
        return GameState(plugin_id=self.id, game_type="tft", raw_data=raw_data, metrics=metrics, derived=derived)

    def evaluate_rules(self, state: GameState) -> list[RuleResult]:
        hp = _int(state.derived.get("player_hp"))
        gold = _int(state.derived.get("gold"))
        level = _int(state.derived.get("level"))
        alive = _int(state.derived.get("alive_players"))

        rules: list[RuleResult] = []
        if hp <= 25 and gold >= 20:
            rules.append(RuleResult("tft_low_hp_roll", 96, "血量危险，别再贪利息，立刻搜牌保血。", ("roll", "survival")))
        if hp <= 40 and gold >= 50:
            rules.append(RuleResult("tft_convert_econ", 88, "血量开始危险，把50金的一部分转成战力，先保血。", ("economy", "survival")))
        if gold >= 50 and hp >= 45:
            rules.append(RuleResult("tft_hold_interest", 74, "经济健康，继续吃满50利息，别急着乱D。", ("economy",)))
        if alive <= 4 and gold >= 30:
            rules.append(RuleResult("tft_top4_push", 82, "已进决赛圈，别再纯贪经济，开始保血提质量。", ("top4", "tempo")))
        if level <= 6 and gold <= 10 and hp >= 60:
            rules.append(RuleResult("tft_rebuild_econ", 64, "经济偏薄，先稳住节奏，别在弱势回合硬搜。", ("economy", "tempo")))
        return rules

    def render_advice(self, rule: RuleResult, state: GameState) -> str:
        return rule.message

    def build_ai_context(self, state: GameState) -> str:
        return (
            f"规则观察：当前生命{state.derived.get('player_hp', '?')}，"
            f"存活玩家{state.derived.get('alive_players', '?')}，"
            f"金币{state.derived.get('gold', '?')}。"
        )


def _find_tft_hp(data: dict, summoner_name: str) -> int:
    for player in data.get("allPlayers", []):
        if player.get("summonerName") == summoner_name:
            hp = player.get("championStats", {}).get("currentHealth")
            if hp is not None:
                return int(hp)
    return 100


def _count_tft_alive(data: dict) -> int:
    seen: set[str] = set()
    alive = 0
    for player in data.get("allPlayers", []):
        name = player.get("summonerName", "")
        if name in seen:
            continue
        seen.add(name)
        hp = int(player.get("championStats", {}).get("currentHealth", 0) or 0)
        if hp > 0:
            alive += 1
    return alive


def _int(value: int | str | None) -> int:
    return value if isinstance(value, int) else 0
