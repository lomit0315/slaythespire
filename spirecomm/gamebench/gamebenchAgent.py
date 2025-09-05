# TODO potential ideas
# Merge/batch together detections and actions potentially to get more mileage per response

# I think there is potential to centralize agent interaction while maintaining decision making in individual files. (Would make config/making new agents way easier)

# potentially add a requeue incase of rate limit overflow

# TODO potential fixes 
# error in saying card_name instead of target_index

# potentially undetectable states for grid select. ie, top the draw pile doesn't have a flag i believe.

# matching event (match and keep) breaks down, CommunicationMod docs say it doesnt transmit match and keep game state so it may be impossible.

# figure out what bowl means??? (check card reward in agent.py) This would let the agent bowl. (whatever that means)

from spirecomm.spire.game import Game
from spirecomm.spire.character import PlayerClass
from spirecomm.spire.screen import RestOption
from spirecomm.communication.action import *
from spirecomm.ai.priorities import *
from main import log_to_file
import json
import os
import requests
import re
from google import genai
from openai import OpenAI
from dotenv import load_dotenv
import time
import yaml
from jinja2 import Template
from spirecomm.gamebench.research import append_to_decision_log # research only
from main import config 

class GameBenchAgent:
#Setup for agent
    def __init__(self, chosen_class=PlayerClass.IRONCLAD):
        self.game = Game() # Game state
        
        self.errors = 0 
        self.skipped_cards = False
        self.visited_shop = False
        self.chosen_potion = None
        self.chosen_class = chosen_class
        self.decision_log = [] # research only
        self.change_class(chosen_class)
        self.fetch_data()

    def get_prompt(self, name: str, context: dict) -> str:
        # Render a named prompt using Jinja2 and the provided context.
        if name not in config["prompts"]:
            raise KeyError(f"Prompt '{name}' not found.")
        template_str = config["prompts"][name]

        template = Template(template_str)

        return template.render(context)

    def fetch_data(self):
        self.fetch_card_data()
        self.fetch_potion_data()
        self.fetch_relic_data()
        self.fetch_power_data()
#Reports errors
    def handle_error(self, error):
        raise Exception(error)
#Gets current state of game and figures out next action
    def get_next_action_in_game(self, game_state):
        self.game = game_state

        if self.game.choice_available:
            return self.handle_screen()
        if self.game.proceed_available:
            return ProceedAction()
        if self.game.play_available:
            return self.get_combat_action()
        if self.game.end_available:
            return EndTurnAction()
        if self.game.cancel_available:
            return CancelAction()
#Start game w/ chosen class
    def get_next_action_out_of_game(self):
        return StartGameAction(self.chosen_class)
#Player encounters an event
    def handle_screen(self):
        if self.game.screen_type == ScreenType.EVENT: 
            enabled_options = [i for i, option in enumerate(self.game.screen.options) if not option.disabled]

            if len(enabled_options) >= 2:
                return self.get_event_action()
            else:
                return ChooseAction(enabled_options[0])
        elif self.game.screen_type == ScreenType.CHEST:
            return OpenChestAction()
        elif self.game.screen_type == ScreenType.SHOP_ROOM:
            # This is the screen before entering the shop with merchant or proceed as options
            if not self.visited_shop and self.game.gold > 0:
                self.visited_shop = True
                return ChooseShopkeeperAction()
            else:
                self.visited_shop = False
                return ProceedAction()
        elif self.game.screen_type == ScreenType.REST: 
            return self.get_rest_action()
        elif self.game.screen_type == ScreenType.CARD_REWARD:
            return self.get_card_reward_action()
        elif self.game.screen_type == ScreenType.COMBAT_REWARD: 
            for reward_item in self.game.screen.rewards:
                if reward_item.reward_type == RewardType.POTION and self.game.are_potions_full() and self.chosen_potion == None:
                    # Only happens when potion is discarded
                    action = self.get_potion_reward_action()
                    if action == None:
                        continue
                    else:
                        return action
                elif reward_item.reward_type == RewardType.CARD and self.skipped_cards:
                    continue
                else:
                    if reward_item.reward_type == RewardType.POTION:
                        self.chosen_potion = None
                    return CombatRewardAction(reward_item)
            self.skipped_cards = False
            return ProceedAction()
        elif self.game.screen_type == ScreenType.MAP:
            return self.make_map_action()
        elif self.game.screen_type == ScreenType.BOSS_REWARD:
            return self.get_boss_relic_action()
        elif self.game.screen_type == ScreenType.SHOP_SCREEN:
            return self.get_shop_screen_action()
        elif self.game.screen_type == ScreenType.GRID:
            if not self.game.choice_available:
                return ProceedAction()
            return self.get_grid_action()
        elif self.game.screen_type == ScreenType.HAND_SELECT:
            # This is for choice screens (like calculated gamble) where you can discard, upgrade, or something else
            if not self.game.choice_available:
                return ProceedAction()
            return self.get_hand_select_action()
        else:
            return ProceedAction()
    
    # Loads info from cards
    def fetch_card_data(self):
        path = os.path.join(os.path.dirname(__file__), "cards.json")

        with open(path, "r", encoding="utf-8") as f:
            card_data = json.load(f)

        self.card_desc_lookup = {card["name"]: card["description"] for card in card_data}
    
    # Loads info from potions
    def fetch_potion_data(self):
        path = os.path.join(os.path.dirname(__file__), "potions.json")

        with open(path, "r", encoding="utf-8") as f:
            potion_data = json.load(f)

        self.potion_desc_lookup = {potion["name"]: potion["description"] for potion in potion_data}
 
    # Loads info from relics
    def fetch_relic_data(self):
        path = os.path.join(os.path.dirname(__file__), "relics.json")

        with open(path, "r", encoding="utf-8") as f:
            relic_data = json.load(f)

        self.relic_desc_lookup = {relic["name"]: relic["description"] for relic in relic_data}

    # Loads info from powers
    def fetch_power_data(self):
        path = os.path.join(os.path.dirname(__file__), "powers.json")

        with open(path, "r", encoding="utf-8") as f:
            power_data = json.load(f)

        self.power_desc_lookup = {power["name"]: power["description"] for power in power_data}

    def change_class(self, new_character):
        self.chosen_class = new_character
    #AI decides which card to play in combat
    def get_combat_action(self):
        # combat
        playable_cards = [card for card in self.game.hand if card.is_playable]

        hand_description = ",\n".join([
            f"- [Name: {card.name}, Cost: {card.cost}, Type: {card.type.name}, Targeted: {card.has_target}, Exhausts: {card.exhausts}, Description: " + 
            format_description(self.card_desc_lookup.get(card.name, "No description found"), card.upgrades > 0) + "]"
            for card in self.game.hand
        ])

        relic_description = ",\n".join([
            f"- [Name: {relic.name}, Description: {self.relic_desc_lookup.get(relic.name, "No description found")}]"
            for relic in self.game.relics
        ])

        has_sacred_bark = any(relic.name == "Sacred Bark" for relic in self.game.relics)

        potion_description = ",\n".join([
            f"- [Name: {potion.name}, Targeted: {potion.requires_target}, Usable: {potion.can_use}, Discardable: {potion.can_discard}  Description: " +
            format_description(self.potion_desc_lookup.get(potion.name, "No description found"), has_sacred_bark) +
            "]"
            for potion in self.game.potions
        ])

        enemy_description = ",\n".join([
            f"- [Index: {i}, Name: {monster.name}, " +
            (f"HP: Dead" if monster.current_hp <= 0 else f"HP: {monster.current_hp}/{monster.max_hp}") +
            f", Intent: {monster.intent}, " + 
            (f", Damage: {monster.move_adjusted_damage}" if monster.move_adjusted_damage != -1 else "") +
            f", Incoming Hits: {monster.move_hits}, Powers: {', '.join([f"{p.power_name} (Description: {self.power_desc_lookup.get(p.power_name, 'No power found')}, Amount: {p.amount})" for p in monster.powers])}]"
            for i, monster in enumerate(self.game.monsters)
        ])

        context = {
            "chosen_class": self.chosen_class.name,
            "current_hp": self.game.current_hp,
            "max_hp": self.game.max_hp,
            "gold": self.game.gold,
            "floor": self.game.floor,
            "relic_description": relic_description,
            "potion_description": potion_description,
            "block": self.game.player.block,
            "energy": self.game.player.energy,
            "enemy_description": enemy_description,
            "hand_description": hand_description,
        }
        prompt = self.get_prompt("combat-decision", context)

        raw_response = self.generate_ai_response(prompt).replace("\n", "")

        match = re.search(r"\{.*\}", raw_response)
        if match:
            ai_response = json.loads(match.group(0))
        else:
            ai_response = "{}"  # Fallback in case no JSON object is found

        action = ai_response.get("action")

        match action:
            case "play_card":
                target_card_name = ai_response.get("card", "")

                card_to_play = next(
                    (card for card in playable_cards
                    if card.name.startswith(target_card_name)),
                    None
                )

                if card_to_play is None:
                    log_to_file("Error in playing card:", target_card_name)
                    log_to_file("Playable cards:", [card.name for card in playable_cards])
                    return EndTurnAction()  

                if(self.game.player.energy >= card_to_play.cost):
                    if card_to_play.has_target:
                        target_index = ai_response.get("target_index", "")

                        if(target_index and len(self.game.monsters) > int(target_index)):
                            target_monster = self.game.monsters[int(target_index)]
                        else:
                            log_to_file("Error in selecting index")
                            target_monster = self.game.monsters[0]

                        if target_monster is None or target_monster.current_hp <= 0:
                            log_to_file("Error in hitting monster:", target_monster.name)
                            return EndTurnAction()  

                        return PlayCardAction(card=card_to_play, target_monster=target_monster)
                    else:
                        return PlayCardAction(card=card_to_play)
                else:
                    return EndTurnAction() 

            case "use_potion":
                target_potion_name = ai_response.get("potion", "")

                real_potions = self.game.get_real_potions()

                potion_to_use = next(
                    (potion for potion in real_potions
                    if potion.name == target_potion_name),
                    None
                )

                if potion_to_use is None:
                    log_to_file("Error in using potion:", target_potion_name)
                    return EndTurnAction()  # Maybe replace with error?

                if not potion_to_use.can_use:
                    log_to_file(f"Error in Potion '{potion_to_use.name}' cannot be used at this time.")
                    return EndTurnAction()

                if potion_to_use.requires_target and potion_to_use.name != "Smoke Bomb": # Smoke bomb is weird because it lists a target despite not having one
                    try:
                        target_index = int(ai_response.get("target_index", -1))
                        target_monster = self.game.monsters[target_index]
                        return PotionAction(True, potion=potion_to_use, target_monster=target_monster)
                    except (ValueError, IndexError):
                        log_to_file(f"Error due to invalid target index for potion '{potion_to_use.name}'.")
                        return EndTurnAction()
                else:
                    if potion_to_use.name == "Smoke Bomb": # TODO remove once error is resolved, temporary block on all smoke bomb usage
                        return PotionAction(False, potion=potion_to_use)
                    
                    return PotionAction(True, potion=potion_to_use)
                    
            case "discard_potion":
                target_potion_name = ai_response.get("potion", "")

                real_potions = self.game.get_real_potions()

                potion_to_play = next(
                    (potion for potion in real_potions
                    if potion.get("name", "") == target_potion_name),
                    None
                )

                if potion_to_play.can_discard:
                    return PotionAction(False, potion=potion_to_play)
            
            case "end_turn":
                return EndTurnAction()
   
    def get_boss_relic_action(self):
        relics = self.game.screen.relics

        boss_relics_description = ",\n".join([
            f"- [Name: {relic.name}, Description: {self.relic_desc_lookup.get(relic.name, 'No description found')}]" 
            for relic in relics
        ])

        relic_description = ",\n".join([
            f"- [Name: {relic.name}, Description: {self.relic_desc_lookup.get(relic.name, "No description found")}]"
            for relic in self.game.relics
        ])

        context = {
            "chosen_class_name": self.chosen_class.name,
            "current_hp": self.game.current_hp,
            "max_hp": self.game.max_hp,
            "gold": self.game.gold,
            "floor": self.game.floor,
            "relic_description": relic_description,  # string or None
            "boss_relics_description": boss_relics_description,
        }

        prompt = self.get_prompt("boss-relic-decision", context)

        raw_response = self.generate_ai_response(prompt).replace("\n", "")

        match = re.search(r"\{.*\}", raw_response)
        if match:
            ai_response = json.loads(match.group(0))
        else:
            ai_response = "{}"  # Fallback in case no JSON object is found

        chosen_relic = next((r for r in relics if r.name == ai_response.get("relic")), None)

        if chosen_relic:
            return BossRewardAction(chosen_relic)
        else:
            return BossRewardAction(relics[0]) # Fallback
        
#Decide what to do at rest site      
    def get_rest_action(self):
        if self.game.screen.has_rested:
            return ProceedAction()

        rest_options = self.game.screen.rest_options

        #Descriptions for prompt
        available_rest_options = ",\n".join([f"- {option.name}" for option in rest_options])
            
        relic_description = ",\n".join([
                f"- [Name: {relic.name}, Description: {self.relic_desc_lookup.get(relic.name, "No description found")}]"
                for relic in self.game.relics
            ])
        
        has_sacred_bark = any(relic.name == "Sacred Bark" for relic in self.game.relics)

        potion_description = ",\n".join([
            f"- [Name: {potion.name}, Targeted: {potion.requires_target}, Usable: {potion.can_use}, Discardable: {potion.can_discard}  Description: " +
            format_description(self.potion_desc_lookup.get(potion.name, "No description found"), has_sacred_bark) +
            "]"
            for potion in self.game.potions
        ])

        context = {
            "chosen_class_name": self.chosen_class.name,
            "current_hp": self.game.current_hp,
            "max_hp": self.game.max_hp,
            "gold": self.game.gold,
            "floor": self.game.floor,
            "relic_description": relic_description,
            "potion_description": potion_description,
            "available_rest_options": available_rest_options,
        }

        prompt = self.get_prompt("rest-decision", context)

        raw_response = self.generate_ai_response(prompt).replace("\n", "")

        match = re.search(r"\{.*\}", raw_response)
        if match:
            ai_response = json.loads(match.group(0))
        else:
            ai_response = "{}"

        chosen_option_str = ai_response.get("option", "").upper()
        valid_rest_option_names = [option.name for option in RestOption]

        if chosen_option_str in valid_rest_option_names:
            chosen_option = RestOption[chosen_option_str]
            if chosen_option in rest_options: 
                return RestAction(chosen_option)
            else: 
                return ProceedAction()
        else:
            log_to_file("Invalid rest option", chosen_option_str)
            return ProceedAction()

#Use map route from above function and makes choice
    def make_map_action(self):
        # If at start, just force progress to row 0
        if len(self.game.screen.next_nodes) > 0 and self.game.screen.next_nodes[0].y == 0:
            self.game.screen.current_node.y = -1
        
        # If boss is available, choose boss
        if self.game.screen.boss_available:
            return ChooseMapBossAction()

        relic_description = ",\n".join([
            f"- [Name: {relic.name}, Description: {self.relic_desc_lookup.get(relic.name, "No description found")}]"
            for relic in self.game.relics
        ])

        has_sacred_bark = any(relic.name == "Sacred Bark" for relic in self.game.relics)

        potion_description = ",\n".join([
            f"- [Name: {potion.name}, Targeted: {potion.requires_target}, Usable: {potion.can_use}, Discardable: {potion.can_discard}  Description: " +
            format_description(self.potion_desc_lookup.get(potion.name, "No description found"), has_sacred_bark) +
            "]"
            for potion in self.game.potions
        ])
        
        context = {
            "chosen_class_name": self.chosen_class.name,
            "current_hp": self.game.current_hp,
            "max_hp": self.game.max_hp,
            "gold": self.game.gold,
            "floor": self.game.floor,
            "relic_description": relic_description,  # string or None
            "potion_description": potion_description,  # string describing potions
            "map_json": json.dumps(self.map_to_json_structure(), indent=2),
            "next_nodes": [
                f"  {{ index: {i}, x: {node.x}, y: {node.y}, type: '{node.symbol}' }}"
                for i, node in enumerate(self.game.screen.next_nodes)
            ]
        }

        prompt = self.get_prompt("map-decision", context)

        raw_response = self.generate_ai_response(prompt).replace("\n", "")

        match = re.search(r"\{.*\}", raw_response)
        if match:
            ai_response = json.loads(match.group(0))
        else:
            ai_response = "{}"  # Fallback in case no JSON object is found

        selected_node_index = ai_response.get("node_index")

        if(len(self.game.screen.next_nodes) > selected_node_index):
            selected_node = self.game.screen.next_nodes[int(selected_node_index)]
        
            return ChooseMapNodeAction(selected_node)
        else:
            log_to_file("Error in choosing map node by index:", selected_node_index)
            return ChooseMapNodeAction(self.game.screen.next_nodes[0])

    def get_potion_reward_action(self):
        if self.chosen_potion == None:
            has_sacred_bark = any(relic.name == "Sacred Bark" for relic in self.game.relics)

            potion_description = ",\n".join([
                f"- [Name: {potion.name}, Targeted: {potion.requires_target}, Usable: {potion.can_use}, Discardable: {potion.can_discard}  Description: " +
                format_description(self.potion_desc_lookup.get(potion.name, "No description found"), has_sacred_bark) +
                "]"
                for potion in self.game.potions
            ])
                
            relic_description = ",\n".join([
                f"- [Name: {relic.name}, Description: {self.relic_desc_lookup.get(relic.name, "No description found")}]"
                for relic in self.game.relics
            ])
            for reward_item in self.game.screen.rewards:
                if reward_item.reward_type == RewardType.POTION:
                    reward_potion = reward_item.potion.name

            context = {
                "chosen_class_name": self.chosen_class.name,
                "current_hp": self.game.current_hp,
                "max_hp": self.game.max_hp,
                "gold": self.game.gold,
                "floor": self.game.floor,
                "relic_description": relic_description,  # string or None
                "potion_description": potion_description,  # string describing current potions
                "reward_potion": reward_potion,  # string describing the potion offered as reward
            }

            prompt = self.get_prompt("potion-reward-decision", context)

            raw_response = self.generate_ai_response(prompt).replace("\n", "")

            match = re.search(r"\{.*\}", raw_response)
            if match:
                ai_response = json.loads(match.group(0))
            else:
                ai_response = "{}"  # Fallback in case no JSON object is found

            action = ai_response.get("action")

            if(action == "skip_reward"):
                return None
            
            discard_potion_name = ai_response.get("discard_potion")
            self.chosen_potion = ai_response.get("reward_potion")

        if discard_potion_name:
            potion_to_discard = next(
            (potion for potion in self.game.potions if potion.name == discard_potion_name),
            None
                )
            if potion_to_discard: 
                return PotionAction(False, potion=potion_to_discard)
            else:
                return PotionAction(False, potion=self.game.potions[0])
        else: 
            return None
        
    def map_to_json_structure(self):
        map_data = self.game.map.nodes  # Dict[int y] -> Dict[int x] -> node

        map_json = []

        for y in sorted(map_data.keys()):
            if y > self.game.screen.next_nodes[0].y:
                row = {"y": y, "nodes": []}
                for x, node in map_data[y].items():
                    node_entry = {
                        "x": x,
                        "y": y,
                        "symbol": node.symbol,
                        "children": [(child.x, child.y) for child in node.children]
                    }
                    row["nodes"].append(node_entry)
            map_json.append(row)

        return map_json

    def get_hand_select_action(self):
        
        cards_to_select_from = self.game.screen.cards
        number_of_cards_to_select = self.game.screen.num_cards

        card_description = ",\n".join([
            f"[Index: {i}, Name: {card.name}, Cost: {card.cost}, Type: {card.type.name}, Description: " +
            format_description(self.card_desc_lookup.get(card.name, "No description found"), card.upgrades > 0) +
            "]"
            for i, card in enumerate(cards_to_select_from)
        ])

        relic_description = ",\n".join([
                f"- [Name: {relic.name}, Description: {self.relic_desc_lookup.get(relic.name, "No description found")}]"
                for relic in self.game.relics
            ])

        has_sacred_bark = any(relic.name == "Sacred Bark" for relic in self.game.relics)

        potion_description = ",\n".join([
            f"- [Name: {potion.name}, Targeted: {potion.requires_target}, Usable: {potion.can_use}, Discardable: {potion.can_discard}  Description: " +
            format_description(self.potion_desc_lookup.get(potion.name, "No description found"), has_sacred_bark) +
            "]"
            for potion in self.game.potions
        ])

        card_action_descriptions = {
            "PutOnDeckAction": "Place a selected card on top of your draw pile for future use.",
            "ArmamentsAction": "Upgrade selected cards in your hand.",
            "DualWieldAction": "Create copies of an attack or power card in your hand.",
            "NightmareAction": "Choose a card to copy at the start of the next turn.",
            "RetainCardsAction": "Allow cards to be retained in hand for the next turn.",
            "SetupAction": "Place a card on top of your draw pile to play later at zero cost.",
            "DiscardAction": "Remove a card from your hand and place it into the discard pile.",
            "ExhaustAction": "Remove a card from your hand for the rest of combat.",
            "PutOnBottomOfDeckAction": "Place a card on the bottom of your draw pile.",
            "RecycleAction": "Exhaust a card to gain energy.",
            "ForethoughtAction": "Put a card into your draw pile to cost 0 when drawn.",
            "GamblingChipAction": "Discard any number of cards and draw that many at the start of combat."
        }

        # Convert camel case or PascalCase like "CurrentAction" -> "Current Action"
        current_action_human = re.sub(r'(?<!^)(?=[A-Z])', ' ', self.game.current_action)

        context = {
            "chosen_class_name": self.chosen_class.name,
            "current_hp": self.game.current_hp,
            "max_hp": self.game.max_hp,
            "gold": self.game.gold,
            "floor": self.game.floor,
            "relic_description": relic_description,  # string or None
            "potion_description": potion_description,  # string describing potions
            "current_action_human": current_action_human,
            "current_action_description": card_action_descriptions[self.game.current_action],  # string description
            "card_description": card_description,  # string listing cards by index
            "number_of_cards_to_select": number_of_cards_to_select,  # int
        }

        prompt = self.get_prompt("hand-select-decision", context)

        raw_response = self.generate_ai_response(prompt).replace("\n", "")

        # DEBUG made it here
        #{  "action": "select_cards",  "selected_indices": [0],  "strategy_note": "Upgrading a Strike card provides a consistent damage source and improves overall hand quality. Prioritizing upgrades for core attack cards."}

        match = re.search(r"\{.*\}", raw_response)
        if match:
            ai_response = json.loads(match.group(0))
        else:
            ai_response = "{}" 
        
        selected_indices = [int(i) for i in ai_response.get("selected_indices", [])]
        chosen_cards_objects = []

        for index in selected_indices :
            if 0 <= index < len(cards_to_select_from):
                chosen_cards_objects.append(cards_to_select_from[index])
        
        if len(chosen_cards_objects) == number_of_cards_to_select:
            return CardSelectAction(chosen_cards_objects)
  
        # fallback
        log_to_file("Failed to select cards at indices: " + ", ".join(str(i) for i in selected_indices))
        fallback_cards = cards_to_select_from[:number_of_cards_to_select]
        return CardSelectAction(fallback_cards)
    
    def get_event_action(self): 
        event_name = self.game.screen.event_name 
        body_text = self.game.screen.body_text

        enabled_options = [option for option in self.game.screen.options if not option.disabled]
        if len(enabled_options) == 1:
            return ChooseAction(enabled_options[0])

        available_event_options = ",\n".join([
            f"[Index: {option.choice_index}, Label: \"{option.label}\", Description: \"{option.text}\"]"
            for option in enabled_options
        ])

        relic_description = ",\n".join([
            f"- [Name: {relic.name}, Description: {self.relic_desc_lookup.get(relic.name, 'No description found')}]"
            for relic in self.game.relics
        ])

        has_sacred_bark = any(relic.name == "Sacred Bark" for relic in self.game.relics)

        potion_description = ",\n".join([
            f"- [Name: {potion.name}, Targeted: {potion.requires_target}, Usable: {potion.can_use}, Discardable: {potion.can_discard}  Description: " +
            format_description(self.potion_desc_lookup.get(potion.name, "No description found"), has_sacred_bark) +
            "]"
            for potion in self.game.potions
        ])

        deck_cards_description = ",\n".join([
            f"- [Name: {card.name}, Cost: {card.cost}, Type: {card.type.name}, Description: " +
            format_description(self.card_desc_lookup.get(card.name, "No description found"), card.upgrades > 0) + 
            "]"
            for card in self.game.deck
        ])

        context = {
            "chosen_class_name": self.chosen_class.name,
            "current_hp": self.game.current_hp,
            "max_hp": self.game.max_hp,
            "gold": self.game.gold,
            "floor": self.game.floor,
            "relic_description": relic_description,           # string or None
            "potion_description": potion_description,         # string
            "deck_cards_description": deck_cards_description, # string
            "event_name": event_name,                         # string
            "body_text": body_text,                           # string (can contain quotes)
            "available_event_options": available_event_options,  # string or block describing options
        }

        prompt = self.get_prompt("event-decision", context)

        raw_response = self.generate_ai_response(prompt).replace("\n", "")

        match = re.search(r"\{.*\}", raw_response)
        if match:
            ai_response = json.loads(match.group(0))
        else:
            ai_response = "{}"  # Fallback in case no JSON object is found  

        chosen_index = ai_response.get("option_index", 0)

        return ChooseAction(int(chosen_index))  # fallback to 0 if invalid or missing

    def get_card_reward_action(self): 
        reward_cards = self.game.screen.cards

    #AI Descriptions
        card_description = ",\n".join([
                f"[Index: {i}, Name: {card.name}, Cost: {card.cost}, Type: {card.type}, Description: " +
                format_description(self.card_desc_lookup.get(card.name, "No description found"), card.upgrades > 0) +
                "]"
                for i, card in enumerate(reward_cards)
            ])  if reward_cards else "No cards offered."

        relic_description = ",\n".join([
                f"- [Name: {relic.name}, Description: {self.relic_desc_lookup.get(relic.name, "No description found")}]"
                for relic in self.game.relics
            ])

        has_sacred_bark = any(relic.name == "Sacred Bark" for relic in self.game.relics)

        potion_description = ",\n".join([
                        f"- [Name: {potion.name}, Targeted: {potion.requires_target}, Usable: {potion.can_use}, Discardable: {potion.can_discard}  Description: " +
                        format_description(self.potion_desc_lookup.get(potion.name, "No description found"), has_sacred_bark) +
                        "]"
                        for potion in self.game.potions
                    ]) if self.game.potions else "None"
        
        deck_cards_description = ",\n".join([
                        f"- [Name: {card.name}, Cost: {card.cost}, Type: {card.type} Description: " +
                        format_description(self.card_desc_lookup.get(card.name, "No description found"), card.upgrades > 0) + 
                        "]"
                        for card in self.game.deck
                    ]) if self.game.deck else "Empty"
        
        context = {
            "chosen_class_name": self.chosen_class.name,
            "current_hp": self.game.current_hp,
            "max_hp": self.game.max_hp,
            "gold": self.game.gold,
            "floor": self.game.floor,
            "relic_description": relic_description,        # string or None
            "potion_description": potion_description,      # string
            "deck_cards_description": deck_cards_description,  # string
            "card_description": card_description,          # string describing the reward cards
        }
        
        prompt = self.get_prompt("card-reward-decision", context)

        raw_response = self.generate_ai_response(prompt).replace("\n", "")

        match = re.search(r"\{.*\}", raw_response)
        if match:
                ai_response = json.loads(match.group(0))
        else:
                ai_response = "{}" 

        chosen_card_name = ai_response.get("card_name")
        chosen_card = next((card for card in reward_cards if card.name == chosen_card_name), None)

        if chosen_card: 
            self.skipped_cards = False
            return CardRewardAction(chosen_card)
        elif self.game.screen.can_skip:
            self.skipped_cards = True 
            return CancelAction()
        else:
            return CardRewardAction(reward_cards[0]) # fallback incase AI tries to skip unskippable
        
    def get_shop_screen_action(self):
        shop_cards = self.game.screen.cards
        shop_relics = self.game.screen.relics
        shop_potions = self.game.screen.potions 
        purge_available = self.game.screen.purge_available
        purge_cost = self.game.screen.purge_cost
        current_gold = self.game.gold 

        # Shop Cards
        shop_cards_description = ",\n".join([
            f"- [Index: {i}, Name: {card.name}, Cost: {card.cost}, Type: {card.type}, Price: {card.price}, Description: " +
            format_description(self.card_desc_lookup.get(card.name, "No description found"), card.upgrades > 0) +
            "]"
            for i, card in enumerate(shop_cards)
        ]) if shop_cards else "No cards for sale."

        # Shop Relics
        shop_relics_description = ",\n".join([
            f"- [Index: {i}, Name: {relic.name}, Price: {relic.price}, Description: {self.relic_desc_lookup.get(relic.name, 'No description found')}]"
            for i, relic in enumerate(shop_relics)
        ]) if shop_relics else "No relics for sale."

        # Shop Potions
        has_sacred_bark = any(relic.name == "Sacred Bark" for relic in self.game.relics)
        shop_potions_description = ",\n".join([
            f"- [Index: {i}, Name: {potion.name}, Price: {potion.price}, Targeted: {potion.requires_target}, Description: " +
            format_description(self.potion_desc_lookup.get(potion.name, "No description found"), has_sacred_bark) +
            "]"
            for i, potion in enumerate(shop_potions)
        ]) if shop_potions and not self.game.are_potions_full() else "No potions for sale." # implementation of discarding potions for new ones omitted because it's too deep

        # Player Relics
        relic_description = ",\n".join([
            f"- [Name: {relic.name}, Description: {self.relic_desc_lookup.get(relic.name, 'No description found')}]"
            for relic in self.game.relics
        ]) if self.game.relics else "None"

        # Player Potions
        potion_description = ",\n".join([
            f"- [Name: {potion.name}, Targeted: {potion.requires_target}, Usable: {potion.can_use}, Discardable: {potion.can_discard}, Description: " +
            format_description(self.potion_desc_lookup.get(potion.name, "No description found"), has_sacred_bark) +
            "]"
            for potion in self.game.potions
        ])

        # Detailed Deck Description (for purging)
        deck_cards_description = ",\n".join([
            f"- [Index: {i}, Name: {card.name}, Cost: {card.cost}, Type: {card.type}, Description: " +
            format_description(self.card_desc_lookup.get(card.name, "No description found"), card.upgrades > 0) + "]"
            for i, card in enumerate(self.game.deck)
        ]) if self.game.deck else "Empty (No cards to purge)."

        context = {
            "chosen_class_name": self.chosen_class.name,
            "current_hp": self.game.current_hp,
            "max_hp": self.game.max_hp,
            "current_gold": current_gold,
            "floor": self.game.floor,
            "relic_description": relic_description,               # string or None
            "potion_description": potion_description,             # string
            "deck_cards_description": deck_cards_description,     # string
            "shop_cards_description": shop_cards_description,     # string
            "shop_relics_description": shop_relics_description,   # string
            "shop_potions_description": shop_potions_description, # string
            "purge_available": purge_available,                   # True/False
            "purge_cost": purge_cost,                             # integer or string
        }

        prompt = self.get_prompt("shop-screen-decision", context)

        raw_response = self.generate_ai_response(prompt).replace("\n", "")

        # made it here :
        #json{  "action": "buy_card",  "item_index": "4",  "strategy_note": "Inflame provides a cheap and reliable source of Strength, significantly boosting damage output early in the run."}

        match = re.search(r"\{.*\}", raw_response)
        if match:
            ai_response = json.loads(match.group(0))
        else:
            ai_response = "{}" 

        action = ai_response.get("action")
        item_index = int(ai_response.get("item_index", 0))

        match action:
            case "buy_card":
                if 0 <= item_index < len(shop_cards):
                    chosen_item = shop_cards[item_index]
                    if current_gold >= chosen_item.price:
                        return BuyCardAction(chosen_item)
                return CancelAction()

            case "buy_relic":
                if 0 <= item_index < len(shop_relics):
                    chosen_item = shop_relics[item_index]
                    if current_gold >= chosen_item.price:
                        return BuyRelicAction(chosen_item)
                return CancelAction()

            case "buy_potion":
                if 0 <= item_index < len(shop_potions):
                    chosen_item = shop_potions[item_index]
                    if current_gold >= chosen_item.price:
                        return BuyPotionAction(chosen_item)
                return CancelAction()
            case "purge_card":
                if purge_available and current_gold >= purge_cost:
                    return ChooseAction(name="purge")
                return CancelAction()

            case "cancel_shop":
                return CancelAction()
    
    def get_grid_action(self): 
        if not self.game.choice_available:
            return ProceedAction()

        grid_cards = self.game.screen.cards 
        is_for_upgrade = self.game.screen.for_upgrade
        is_for_purge = self.game.screen.for_purge
        is_for_transform = self.game.screen.for_transform
        num_cards_to_select = self.game.screen.num_cards

        deck_cards_description = ",\n".join([
            f"- [Index: {i}, Name: {card.name}, Cost: {card.cost}, Type: {card.type.name}, Description: " +
            format_description(self.card_desc_lookup.get(card.name, "No description found"), card.upgrades > 0) + 
            "]"
            for i, card in enumerate(grid_cards)
        ])  if grid_cards else "Empty (No cards available for this action)."
        
        relic_description = ",\n".join([
            f"- [Name: {relic.name}, Description: {self.relic_desc_lookup.get(relic.name, "No description found")}]"
            for relic in self.game.relics
        ]) if self.game.relics else "None"

        has_sacred_bark = any(relic.name == "Sacred Bark" for relic in self.game.relics)
        
        potion_description = ",\n".join([
            f"- [Name: {potion.name}, Targeted: {potion.requires_target}, Usable: {potion.can_use}, Discardable: {potion.can_discard} Description: " +
            format_description(self.potion_desc_lookup.get(potion.name, "No description found"), has_sacred_bark) +
            "]"
            for potion in self.game.potions
        ])

        action_type = {}

        if is_for_upgrade:
            action_type = {"name": "Upgrade", "description": "Choose one or more cards to upgrade."}
        elif is_for_purge:
            action_type = {"name": "Purge", "description": "Choose one or more cards to purge/remove from your deck."}
        elif is_for_transform:
            action_type = {"name": "Transform", "description": "Choose one or more cards to transform into different ones."}
        else:
            action_type = {"name": "Top Draw Pile", "description": "Choose one or more cards to put on top of the draw pile."}

        context = {
            "chosen_class_name": self.chosen_class.name,
            "current_hp": self.game.current_hp,
            "max_hp": self.game.max_hp,
            "gold": self.game.gold,
            "floor": self.game.floor,
            "relic_description": relic_description,             # string or None
            "potion_description": potion_description,           # string
            "action_name": action_type["name"],                 # e.g., "Upgrade", "Transform"
            "action_description": action_type["description"],   # string
            "num_cards_to_select": num_cards_to_select,         # int
            "deck_cards_description": deck_cards_description,   # formatted multiline string
        }
        # made it here
        prompt = self.get_prompt("grid-screen-decision", context)

        raw_response = self.generate_ai_response(prompt).replace("\n", "")

        match = re.search(r"\{.*\}", raw_response)
        if match:
            ai_response = json.loads(match.group(0))
        else:
            ai_response = "{}"

        action = ai_response.get("action")
        
        card_indices_to_select = [int(i) for i in ai_response.get("card_indices", [])]

        if action == "select_cards":
            selected_cards = []
            for index in card_indices_to_select:
                if 0 <= index < len(grid_cards):  
                    selected_cards.append(grid_cards[index])
                else:
                    log_to_file(
                        "Error selecting cards in grid:",
                        f"Invalid index: {index}",
                        f"Grid length: {len(grid_cards)}"
                    )
                    return CancelAction() 

            valid_selection_count = (len(selected_cards) == num_cards_to_select)

            if selected_cards and valid_selection_count:
                return CardSelectAction(selected_cards)
            elif not selected_cards and valid_selection_count and num_cards_to_select == 0:
                return CardSelectAction([])
            else:
                if grid_cards and num_cards_to_select > 0:
                    log_to_file(
                        "Fallback: Invalid card selection count or empty selection.",
                        f"Expected: {num_cards_to_select}, Got: {len(selected_cards)}"
                    )
                    return CardSelectAction(grid_cards[:num_cards_to_select])
                else:
                    log_to_file(
                        "Fallback: No grid cards available or zero cards requested.",
                        f"Grid cards: {len(grid_cards)}, Cards requested: {num_cards_to_select}"
                    )
                    return ProceedAction()
        elif action == "cancel_grid":
            return CancelAction()
        else:
            log_to_file(f"Unknown action: {action}")
            return ProceedAction()  
    #Core communication function with AI 
    def generate_ai_response(self, prompt):
        # Optional throttle for testing (to not overflow rate limit)
        # time.sleep(5) 

        prompt = smart_trim(prompt=prompt)

        # Load config
        config_path = get_project_path("config.yaml")

        with open(config_path, "r") as f:
            config = yaml.safe_load(f)

        model = config["general"]["model"].lower()

        output_response = None

        match model:
            case "local":
                local_url = "http://127.0.0.1:5000"
                internet_url = "your-online-url-here"
                current_url = local_url

                chat_request_body = {
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                }

                try:
                    response = requests.post(
                        f"{current_url}/v1/chat/completions",
                        headers={"Content-Type": "application/json"},
                        data=json.dumps(chat_request_body)
                    )
                    response.raise_for_status()
                    response_json = response.json()
                    output_response = response_json['choices'][0]['message']['content']
                except Exception as e:
                    log_to_file(f"Error generating AI response: {e}")
                    return "Error: Failed to generate AI response"
            
            case "gemini_flash":              
                try:
                    load_dotenv()
                    api_key = os.getenv("GEMINI_API_KEY")
                    if not api_key:
                        raise RuntimeError("GEMINI_API_KEY is not set")
                    
                    client = genai.Client(api_key=api_key)
                    response = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=prompt,
                    )
                    output_response = response.text
                except Exception as e:
                    log_to_file(f"Error generating response with Google model: {e}")
                    return "Error: Failed to generate AI response with Google" 

            case "gemini_flash_lite":              
                try:
                    load_dotenv()
                    api_key = os.getenv("GEMINI_API_KEY")
                    if not api_key:
                        raise RuntimeError("GEMINI_API_KEY is not set")
                    
                    client = genai.Client(api_key=api_key)
                    response = client.models.generate_content(
                        model="gemini-2.5-flash-lite",
                        contents=prompt,
                    )
                    output_response = response.textTODO
                except Exception as e:
                    log_to_file(f"Error generating response with Google model: {e}")
                    return "Error: Failed to generate AI response with Google"
                
            case "gemma":              
                try:
                    load_dotenv()
                    api_key = os.getenv("GEMINI_API_KEY")
                    if not api_key:
                        raise RuntimeError("GEMINI_API_KEY is not set")
                    
                    client = genai.Client(api_key=api_key)
                    response = client.models.generate_content(
                        model="gemma-3-27b-it",
                        contents=prompt,
                    )
                    output_response = response.text
                except Exception as e:
                    log_to_file(f"Error generating response with Google model: {e}")
                    return "Error: Failed to generate AI response with Google"
                
            case "chatgpt_nano":
                try:
                    load_dotenv()
                    api_key = os.getenv("OPENAI_API_KEY")
                    if not api_key:
                        raise RuntimeError("OPENAI_API_KEY is not set")
                    
                    client = OpenAI(api_key=api_key)

                    response = client.responses.create(
                        model="gpt-5-nano",
                        input=prompt
                    )

                    output_response = response.output_text
                except Exception as e:
                    log_to_file(f"Error generating response with ChatGPT: {e}")
                    return "Error: Failed to generate AI response with ChatGPT"
                
            case "chatgpt_mini":
                try:
                    # TODO potentially move to other chatgpts
                    load_dotenv()
                    api_key = os.getenv("OPENAI_API_KEY")
                    if not api_key:
                        raise RuntimeError("OPENAI_API_KEY is not set")

                    client = OpenAI(api_key=api_key)

                    response = client.chat.completions.create(
                        model="gpt-5-mini",
                        messages=[
                            {"role": "system", "content": "You are a game-playing AI. Respond ONLY in valid JSON."},
                            {"role": "user", "content": prompt}
                        ],
                        response_format={ "type": "json_object" }
                    )

                    output_response = response.choices[0].message.content

                except Exception as e:
                    log_to_file(f"Error generating response with ChatGPT: {e}")
                    return "Error: Failed to generate AI response with ChatGPT"
            
            case "chatgpt":
                try:
                    load_dotenv()
                    api_key = os.getenv("OPENAI_API_KEY")
                    if not api_key:
                        raise RuntimeError("OPENAI_API_KEY is not set")
                    
                    client = OpenAI(api_key=api_key)

                    response = client.responses.create(
                        model="gpt-5",
                        input=prompt,
                    )

                    output_response = response.output_text

                except Exception as e:
                    log_to_file(f"Error generating response with ChatGPT: {e}")
                    return "Error: Failed to generate AI response with ChatGPT"

        if config["general"]["research"]:
            append_to_decision_log(game=self.game, decision_log=self.decision_log, ai_response=output_response)

        # logs for debug
        log_to_file(output_response.replace("\n", ""))

        return output_response 

# smart trim for cost effective prompting       
def smart_trim(prompt: str) -> str:
    prompt = re.sub(r'## .+\n', '\n', prompt) # just remove the ## but keep newline
    prompt = re.sub(r'\n{2,}', '\n', prompt) # collapse multiple blank lines
    prompt = re.sub(r'[ \t]{2,}', ' ', prompt) # collapse spaces/tabs
    return prompt.strip()
        
# Helper for extracting upgrades for prompting
def format_description(description: str, upgraded: bool) -> str:
    if upgraded: # Replace base values with upgraded values inside parentheses.
        pattern = re.compile(r'([^\(]*?)\((.*?)\)([^\(]*)')
        result = ""
        idx = 0
        for match in pattern.finditer(description):
            before = match.group(1)
            upgraded_text = match.group(2).strip()
            after = match.group(3)
            result += before + upgraded_text + after
            idx = match.end()
        result += description[idx:]
        return result.strip()
    else: # Remove all parentheses and their contents.
        return re.sub(r'\s*\(.*?\)\s*', ' ', description).strip()
    
# Helper for finding paths
def get_project_path(*subpaths):
    base = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )
    return os.path.join(base, *subpaths)