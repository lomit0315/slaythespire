import itertools
from datetime import datetime

from spirecomm.communication.coordinator import Coordinator
from spirecomm.spire.character import PlayerClass
from spirecomm.gamebench.research import *
import os
import yaml

# Load config
config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")

with open(config_path, "r", encoding="utf-8-sig") as f:
    config = yaml.safe_load(f)

class_map = {
    "ironclad" : 1,
    "the_silent" : 2,
    "defect" : 3
}

character = config["general"]["character"].lower()
chosen_class = class_map.get(character)

agent_name = config["general"]["agent"].lower()

def main():
    # Import here to avoid circular importing, refactor later if I want to.
    from spirecomm.ai.agent import SimpleAgent
    from spirecomm.gamebench.gamebenchAgent import GameBenchAgent
    from spirecomm.gamebench.randomAgent import RandomAgent

    match agent_name:
        case "ai":
            agent = GameBenchAgent(PlayerClass(chosen_class))
        case "random":
            agent = RandomAgent(PlayerClass(chosen_class))
        case "optimized":
            agent = SimpleAgent(PlayerClass(chosen_class))
        case _:
            agent = RandomAgent(PlayerClass(chosen_class))

    coordinator = Coordinator()
    coordinator.signal_ready()
    coordinator.register_command_error_callback(agent.handle_error)
    coordinator.register_state_change_callback(agent.get_next_action_in_game)
    coordinator.register_out_of_game_callback(agent.get_next_action_out_of_game)

    repetitions = 0

    for character_class in itertools.cycle(PlayerClass):
        if int(config["general"]["repetitions"]) > 0 and repetitions >= int(config["general"]["repetitions"]):
            log_to_file("Repetition limit exceeded")
            raise Exception("Repetition limit exceeded")

        chosen_seed = None
        if config["general"]["research"]: # research only
            chosen_entry = choose_random_entry()
            if chosen_entry is not None:
                chosen_seed = convert_seed_num_to_string(chosen_entry["seed"])
                character_name = chosen_entry["character"].upper()
                character_class = PlayerClass[character_name]
        
        agent.change_class(character_class)
        coordinator.play_one_game(character_class, seed=chosen_seed) 
        if config["general"]["research"]: # research only
            write_research_data(coordinator.last_game_state, agent.decision_log) 
        
        repetitions += 1


# log for debugging (doesn't mess with internal console system)
def log_to_file(*args, sep=" ", end="\n", file_name="debug_log.txt", timestamp=True):
    file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), file_name)
    with open(file_path, "a", encoding="utf-8") as f:
        prefix = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] " if timestamp else ""
        f.write(prefix + sep.join(map(str, args)) + end)

if __name__ == "__main__":
    main()


