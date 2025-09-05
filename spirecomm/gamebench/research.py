from main import log_to_file
import os
import json
import orjson
import yaml
import re

config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config.yaml")

with open(config_path, "r") as f:
    config = yaml.safe_load(f)

def write_research_data(game, decision_log):
    json_path = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")), "research_data.json")

    data = []
    run_id = 1

    if os.path.exists(json_path):
        with open(json_path, "rb") as f:
            try:
                data = orjson.loads(f.read())
                if isinstance(data, list) and data:
                    run_id = max(entry["run_id"] for entry in data) + 1
            except orjson.JSONDecodeError:
                data = []
                run_id = 1

    model = config["general"].get("model", "").lower()
    agent = config["general"].get("agent", "").lower()
    character = game.character.name
    seed = game.seed
    win = game.screen.victory
    floor_reached = 17 * (game.act - 1) + game.floor
    score = game.screen.score

    entry = {
        "run_id": run_id,
        "model": model if agent == "ai" else None,
        "agent": agent,
        "character": character,
        "seed": seed,
        "win": win,
        "floor_reached": floor_reached,
        "score": score,
        "decision_log": decision_log
    }

    data.append(entry)

    with open(json_path, "wb") as f:
        f.write(orjson.dumps(data))

    log_to_file(f"Run {run_id} written to {json_path}")


# Decision log to fetch step by step decision analysis from the ai to define its capabilities
def append_to_decision_log(game, decision_log, ai_response): 
    log_type = config["general"]["log-type"].lower()
    turn_log = None

    # Safely parse the AI response
    if isinstance(ai_response, str):
        match = re.search(r"\{.*\}", ai_response)
        ai_json = json.loads(match.group(0)) if match else "{}"
    else:
        ai_json = "{}"

    # Build log entry depending on type
    match log_type:
        case "combat":
            if game.play_available:
                hand_json = [
                    {
                        "name": card.name,
                        "cost": card.cost,
                    }
                    for card in game.hand
                ]

                monster_json = [
                    {
                        "name": monster.name,
                        "current_hp": monster.current_hp,
                        "max_hp": monster.max_hp,
                        "intent": monster.intent.name
                    }
                    for monster in game.monsters
                ]

                turn_log = {
                    "index": sum(len(floor_log) for floor_log in decision_log),
                    "turn_index": game.turn,
                    "floor": game.floor,
                    "monsters": monster_json,
                    "current_hp": game.current_hp,
                    "max_hp": game.max_hp,
                    "energy": game.player.energy,
                    "hand": hand_json,
                }

    if turn_log:
        # Find or create floor log
        if not decision_log or not decision_log[-1] or decision_log[-1][0]["floor"] != game.floor:
            decision_log.append([])

        current_floor_log = decision_log[-1]
        current_floor_log.append(turn_log)


# Inspired by bcreswell on reddit https://www.reddit.com/r/slaythespire/comments/nx15ad/comment/i0lowhc/
def convert_seed_num_to_string(seed_num: int) -> str:
    base_string = "0123456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
    result = ""
    
    # Convert to unsigned 64-bit equivalent if negative
    left_over = seed_num & 0xFFFFFFFFFFFFFFFF
    base_length = len(base_string)

    while left_over != 0:
        remainder = left_over % base_length
        left_over = left_over // base_length
        result = base_string[int(remainder)] + result

    return result

def choose_random_entry():
    json_path = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")), "research_data.json")

    data = []

    if os.path.exists(json_path):
        with open(json_path, "rb") as f:
            try:
                data = orjson.loads(f.read())
            except orjson.JSONDecodeError as e:
                log_to_file("JSON Decode Error:", e)

    current_agent = config["general"]["agent"].lower()
    current_model = config["general"]["model"].lower()

    filtered_entries = [
        entry for entry in data
        if entry.get("agent") == current_agent
        and (
            current_agent != "ai"
            or entry.get("model") == current_model
        )
    ]

    used_seeds = {entry["seed"] for entry in filtered_entries}
    unused_entries = [entry for entry in data if entry["seed"] not in used_seeds]

    return unused_entries[0] if unused_entries else None
