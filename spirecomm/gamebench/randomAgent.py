import time
import random

from spirecomm.spire.game import Game
from spirecomm.spire.character import PlayerClass
from spirecomm.communication.action import *
from spirecomm.ai.priorities import *
from spirecomm.gamebench.research import append_to_decision_log # research only
from main import config 

# TODO I think the console getting too long is lagging the game, figure out how to clear it

class RandomAgent:

    def __init__(self, chosen_class=PlayerClass.THE_SILENT):
        self.game = Game()
        self.errors = 0
        self.skipped_cards = False
        self.visited_shop = False
        self.decision_log = [] # research only
        self.chosen_class = chosen_class
        self.change_class(chosen_class)

    def change_class(self, new_class):
        self.chosen_class = new_class

    def handle_error(self, error):
        raise Exception(error)

    def get_next_action_in_game(self, game_state):
        self.game = game_state
        #time.sleep(0.07)
        if config["general"]["research"]: # Log the game state even if the agent doesn't generate decision for control group tracking
            append_to_decision_log(game=self.game, decision_log=self.decision_log, ai_response=None)

        if self.game.choice_available:
            return self.handle_screen()
        if self.game.proceed_available:
            return ProceedAction()
        if self.game.play_available:
            usable_potions = [p for p in self.game.get_real_potions() if p.can_use]
            num_potions = len(usable_potions)
            num_cards = len([card for card in self.game.hand if card.is_playable])

            if num_potions > 0:
                potion_use_chance = num_potions / ((num_potions + num_cards) * 10) # multiplies by 10 arbitrarily to make using potions rarer
                if random.random() < potion_use_chance:
                    potion = random.choice(usable_potions)
                    if potion.requires_target and potion.name != "Smoke Bomb": # Smoke bomb has malformed JSON meaning it says it has a target when it doesn't
                        available_monsters = [m for m in self.game.monsters if m.current_hp > 0 and not m.half_dead and not m.is_gone]
                        if available_monsters:
                            target = random.choice(available_monsters)
                            return PotionAction(True, potion=potion, target_monster=target)
                        else:
                            return EndTurnAction()
                    else:
                        if potion.name == "Smoke Bomb": # TODO remove once error is resolved, temporary block on all smoke bomb usage
                            return PotionAction(False, potion=potion)
                        return PotionAction(True, potion=potion)
                else:
                    return self.get_play_card_action() 

            return self.get_play_card_action()
            
        if self.game.end_available:
            return EndTurnAction()
        if self.game.cancel_available:
            return CancelAction()

    def get_next_action_out_of_game(self):
        return StartGameAction(self.chosen_class)

    def get_play_card_action(self):
        playable_cards = [card for card in self.game.hand if card.is_playable]
        if len(playable_cards) == 0:
            return EndTurnAction()
        
        card_to_play = random.choice(playable_cards)

        if card_to_play.has_target:
            available_monsters = [monster for monster in self.game.monsters if monster.current_hp > 0 and not monster.half_dead and not monster.is_gone]
            if len(available_monsters) == 0:
                return EndTurnAction()
            
            target = random.choice(available_monsters)
            return PlayCardAction(card=card_to_play, target_monster=target)
        else:
            return PlayCardAction(card=card_to_play)

    def handle_screen(self):
        if self.game.screen_type == ScreenType.EVENT:
            enabled_options = [option for option in self.game.screen.options if not option.disabled]

            choice_index = random.choice(enabled_options).choice_index
            return ChooseAction(choice_index)
        
        elif self.game.screen_type == ScreenType.CHEST:
            return OpenChestAction()
        
        elif self.game.screen_type == ScreenType.SHOP_ROOM:
            if not self.visited_shop:
                self.visited_shop = True
                return ChooseShopkeeperAction()
            else:
                self.visited_shop = False
                return ProceedAction()
            
        elif self.game.screen_type == ScreenType.REST: 
            return self.choose_rest_option()
        
        elif self.game.screen_type == ScreenType.CARD_REWARD: 
            return self.choose_card_reward()
        
        elif self.game.screen_type == ScreenType.COMBAT_REWARD:
            for reward_item in self.game.screen.rewards:
                if reward_item.reward_type == RewardType.POTION and self.game.are_potions_full():
                    continue
                elif reward_item.reward_type == RewardType.CARD and self.skipped_cards:
                    continue
                else:
                    return CombatRewardAction(reward_item)
            self.skipped_cards = False
            return ProceedAction()
        
        elif self.game.screen_type == ScreenType.MAP:
            return self.make_map_choice() 
        
        elif self.game.screen_type == ScreenType.BOSS_REWARD: 
            relics = self.game.screen.relics
            return BossRewardAction(random.choice(relics))
        
        elif self.game.screen_type == ScreenType.SHOP_SCREEN: 
            return self.choose_shop_item()
        
        elif self.game.screen_type == ScreenType.GRID:
            if not self.game.choice_available:
                return ProceedAction()

            num_cards = self.game.screen.num_cards
            available_cards = self.game.screen.cards

            if len(available_cards) <= num_cards:
                chosen_cards = available_cards  
            else:
                chosen_cards = random.sample(available_cards, num_cards)

            return CardSelectAction(chosen_cards)
        
        elif self.game.screen_type == ScreenType.HAND_SELECT: 
            if not self.game.choice_available:
                return ProceedAction()

            available_cards = self.game.screen.cards
            num_available = len(available_cards)


            if num_available <= self.game.screen.num_cards:
                if self.game.screen.num_cards == 99:
                    # As many cards as you want
                    cards_to_choose = random.randint(1, num_available)
                    chosen_cards = random.sample(available_cards, cards_to_choose)
                else:
                    # Cards available = to num required
                    chosen_cards = available_cards
            else:
                # Limited amount of cards to choose
                chosen_cards = random.sample(available_cards, self.game.screen.num_cards)

            return CardSelectAction(chosen_cards)
        else:
            return ProceedAction()

    def choose_rest_option(self):
        rest_options = self.game.screen.rest_options
        if len(rest_options) > 0 and not self.game.screen.has_rested:
            chosen_option = random.choice(rest_options)
            return RestAction(chosen_option)
        else:
            return ProceedAction()

    def choose_card_reward(self):
        reward_cards = self.game.screen.cards

        if self.game.screen.can_skip and random.randint(1, len(reward_cards)) == 1:
            self.skipped_cards = True
            return CancelAction()
        else:
            card = random.choice(reward_cards)
            return CardRewardAction(card)

    def make_map_choice(self):
        if len(self.game.screen.next_nodes) > 0 and self.game.screen.next_nodes[0].y == 0:
            self.game.screen.current_node.y = -1

        if self.game.screen.boss_available:
            return ChooseMapBossAction()

        if len(self.game.screen.next_nodes) > 0:
            choice = random.choice(self.game.screen.next_nodes)
            return ChooseMapNodeAction(choice)

        # This should never happen
        return ChooseAction(0)

    def choose_shop_item(self):
        actions = []
        probabilities = []

        if self.game.screen.purge_available and self.game.gold >= self.game.screen.purge_cost:
            actions.append(lambda: ChooseAction(name="purge"))
            probabilities.append(1)

        for card in self.game.screen.cards:
            if self.game.gold >= card.price:
                actions.append(lambda card=card: BuyCardAction(card))
                probabilities.append(1)  

        for relic in self.game.screen.relics:
            if self.game.gold >= relic.price:
                actions.append(lambda relic=relic: BuyRelicAction(relic))
                probabilities.append(1)  

        for potion in self.game.screen.potions:
            if self.game.gold >= potion.price and not self.game.are_potions_full():
                actions.append(lambda potion=potion: BuyPotionAction(potion))
                probabilities.append(1)  

        actions.append(lambda: CancelAction())
        probabilities.append(1)

        total = sum(probabilities)
        probabilities = [p / total for p in probabilities]

        chosen_action = random.choices(actions, weights=probabilities, k=1)[0]

        return chosen_action()
    
    