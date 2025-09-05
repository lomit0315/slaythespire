## Development Update Report

### 1. Configuration and Environment File Handling Improvements

- **Enhanced Encoding Compatibility**:
    - Implemented a robust loader for `.env` files that can auto-detect **BOM/UTF-16**.
    - Updated **YAML/JSON** file reads to consistently use `utf-8-sig`, preventing parse errors caused by BOM or unusual encodings.
- **Unified Loading Approach**:
    - Replaced all `load_dotenv()` calls with the new safe loader.
    - Adjusted config file opening logic to ensure stability across different platforms and encodings.

### 2. Fix for `map_to_json_structure` Crash

- **Issue**:
    - The `row` variable could be referenced before initialization, causing an **`UnboundLocalError`**.
    - The code also crashed when `next_nodes` was empty due to an out-of-range index access.
- **Changes Made**:
    - Replaced direct indexing with a safe fallback:
        
        ```python
        last_y = self.game.screen.next_nodes[0].y if self.game.screen.next_nodes else -1
        ```
        
    - Only build a `row` when `y > last_y`, and moved `map_json.append(row)` inside that conditional block.
- **Effect**:
    - Eliminated the `UnboundLocalError`.
    - Properly handles cases where `next_nodes` is empty, making the function more robust.

# game-bench
A benchmarking framework for testing AI agents in a card-based roguelike environment.

## IMPORTANT:
Before running the project, create a .env file in the root directory and add your API keys:

```
GEMINI_API_KEY=your_gemini_api_key
OPENAI_API_KEY=your_openai_api_key
```

## Configuration:
All configuration is handled through config.yaml.
You can tweak prompts and settings directly in the file.
Only tags explicitly defined in the prompts are supported by default.
Adding new tags like {{ new_tag }} requires manual updates to the context in gamebenchAgent.py.
For more details on prompt templating, refer to the Jinja2 [template documentation](https://jinja.palletsprojects.com/en/stable/templates/).

## Available Config Options:
character – Name of the character to use.  
model – Model name to use (see Supported Models for valid values).  
agent – Agent name to use (see Supported Agents for valid values).  
repetitions - Number of games repeat will run for (-1 or less means indefinite).  
research – true/false. Logs run data for research purposes and enables additional research-specific features.  
log_type – Type of log to record (none except Combat natively supported).  

## Supported Agents:
AI = AI agent, select a model below  
Random = Random agent  
Optimized = Optimized agent, made by ForgottenArbiter in [spirecomm](https://github.com/ForgottenArbiter/spirecomm/tree/master)  

## Supported Models:
Gemini_Flash = Gemini 2.5 Flash  
Gemini_Flash_Lite = Gemini 2.5 Flash Lite  
Gemma = Gemma 3 27b IT  
ChatGPT = ChatGPT 5  
ChatGPT_Mini = ChatGPT 5 Mini  
ChatGPT_Nano = ChatGPT 5 Nano  

## Adding New Agents / Models:
Custom Agents: Use the Random agent as a base and build your own logic on top.  
New Models: Modify the generate_ai_response function in gamebenchAgent.py and add your custom logic in the match statement.  

## Dependencies:
```
pip install google-genai
pip install openai
pip install pyyaml
pip install jinja2
pip install orjson (research specific for optimal logging)
```

## Known Issues:
- CommunicationMod doesn't pass data from the "Match and Keep" event to the bot, limiting AI interpretation.
- The Game Bench agent doesn't recognize potions in the shop screen when potion slots are full, as implementing potion discarding is currently too time-consuming.
- Weird issues with screen state after using a Smoke Bomb cause a rudimentary block on all agents, preventing its use.
- Orbs are not visible to the GameBench agent because this feature hasn’t been implemented yet, though the potential exists.

## Potential Improvements:
- Currently, prompts are minimal. Optimizing and refining prompts may significantly improve AI performance.
- Ascension levels have yet to be implemented. Incorporating them could strengthen benchmarking.
- Fallback mechanisms are somewhat limited at present. enhancing them, via reprompting or other methods, could prioritize better results over cost savings.
